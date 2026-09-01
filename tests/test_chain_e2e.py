"""E2E chain proofs + dormancy/boundary guards (indefinite-run t10 — tests only).

Drives the whole ``--until-done`` episode chain end-to-end through
``colleague.cli.main`` on the scripted mock engine (the contract reference) and
pins the c16 before-state limits as REMOVED by asserting the new behavior:

- **chain-completes** — a task sized to need >= 3 episodes lands its
  deliverable (cumulative tree carry, the removed carry limit) with status ok,
  lineage chain length >= 3, and zero operator interventions.
- **chain-halts-honestly** — a deliberately no-progress task halts within 2
  episodes, reporting non-ok with an incompletion reason (#313 intact inside
  the chain).
- **compaction-validated** — an empty/unrepairable compaction summary never
  silently replaces history (the removed no-validation limit); the rejection
  is observable on the trace. Plus the per-crossing re-arm (the removed
  fires-at-most-once limit) proven in one real dispatch.
- **dormancy** — with no flag/env/config a bare work item's artifact carries
  the exact pre-feature key set (no ``chain`` key), the ``test_boundary.py``
  sanctioned subprocess/thread lists are unchanged, and the ``TaskResult``
  shape stays identical across ``mock`` and ``vllm-openai`` including a
  dispatch-stamped chain view (the all-engines guard, extended).

TDD baseline — fails-on-main proof (criterion 5)
------------------------------------------------
Each named test was run against pre-arc main (the merge-base
``git merge-base HEAD main`` = ``f94063f``, "Interactive finishes what it
starts", PR #331) in a throwaway worktree, with this file copied in
(worktree removed after the run):

    git worktree add --detach <scratch>/chain-e2e-main-proof f94063f
    cp tests/test_chain_e2e.py <scratch>/chain-e2e-main-proof/tests/
    cd <scratch>/chain-e2e-main-proof && uv sync
    uv run pytest tests/test_chain_e2e.py -q \
        -k "test_chain_completes or test_chain_halts_honestly or test_compaction_validated"

Recorded on f94063f, 2026-07-15: ``3 failed, 4 deselected``.

- ``test_chain_completes`` — FAILED ``assert 1 == 0``: pre-arc main has no
  chain loop, so the CLI rejects the arming flag
  (``error: unrecognized arguments: --until-done`` /
  ``hint: check usage with --help``) and ``main`` returns 1.
- ``test_chain_halts_honestly`` — FAILED ``assert 1 == 2``: same unrecognized
  ``--until-done`` flag, rc == 1; no episode ever dispatched.
- ``test_compaction_validated`` — FAILED
  ``AssertionError: assert ['   \\n '] == []``: on main the empty compaction
  note IS silently applied — the spy saw ``apply_compaction`` called with the
  whitespace summary (the pre-t2 "(no summary produced)" silent-amnesia
  placeholder replaces history) and no rejection notice reached stderr.

Integration level for compaction-validated: the FULL work dispatch
(``colleague.cli.main`` -> ``execute_work`` -> mock engine -> shared loop),
one level deeper than ``tests/test_fillline.py``'s direct ``run()`` harness.
The fill line is crossed in the real dispatch by scripting the mock turn's
exact ``prompt_tokens`` (usage-exact by contract) against a
``COLLEAGUE_CONTEXT_BUDGET`` env arm — no loop internals are touched; the
rejection is observed on the stderr trace (the #206 phase-notice channel) and
at the one seam a summary can replace history through
(``colleague.fillline.apply_compaction``, spied, never stubbed).
"""

from __future__ import annotations

import builtins
import json
import subprocess
from pathlib import Path

import pytest

from colleague import fillline
from colleague import handoff as ho
from colleague.artifact import find_artifact
from colleague.loop import ModelResponse, ToolCall

# ---------------------------------------------------------------------------
# Harness (the tests/test_work_chain.py in-process e2e pattern)
# ---------------------------------------------------------------------------


def _run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, check=True)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """A git-initialised repo with an initial commit (cwd-scoped identity)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git(repo, "init", "-q")
    _run_git(repo, "config", "user.email", "test@example.com")
    _run_git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("hello\n")
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-q", "-m", "init")
    return repo


def _budget_turn(episode: int) -> ModelResponse:
    """A turn that writes an episode-unique file and never finishes (budget exit)."""
    return ModelResponse(
        content=f"episode {episode} still working",
        tool_calls=[
            ToolCall(
                f"e{episode}",
                "write_file",
                {"path": f"episode-{episode}.txt", "content": f"episode {episode} work\n"},
            )
        ],
        prompt_tokens=1,
        completion_tokens=1,
    )


def _idle_turn(episode: int) -> ModelResponse:
    """A turn that only reads (no changes, never finishes) — the no-progress shape."""
    return ModelResponse(
        content=f"episode {episode} reading",
        tool_calls=[ToolCall(f"r{episode}", "read_file", {"path": "README.md"})],
        prompt_tokens=1,
        completion_tokens=1,
    )


def _finish_turn() -> ModelResponse:
    return ModelResponse(
        content="done",
        tool_calls=[ToolCall("fin", "finish", {"summary": "chain complete"})],
        prompt_tokens=1,
        completion_tokens=1,
    )


def _script_episodes(monkeypatch: pytest.MonkeyPatch, plan: list[str]) -> dict:
    """Monkeypatch the mock engine's script: one entry of *plan* per episode.

    ``plan`` entries are "budget" / "idle" / "finish"; episode N uses
    ``plan[N-1]`` (the last entry repeats past the end). Returns the shared
    episode counter dict — ``counter["n"]`` is how many episodes DISPATCHED.
    """
    counter = {"n": 0}

    def fake_script(task):
        counter["n"] += 1
        kind = plan[min(counter["n"], len(plan)) - 1]
        n = counter["n"]

        def complete(_messages):
            if kind == "budget":
                return _budget_turn(n)
            if kind == "idle":
                return _idle_turn(n)
            return _finish_turn()

        return complete

    monkeypatch.setattr("colleague.engines.mock._script", fake_script)
    return counter


def _gate_pr_boundary(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Gate PR creation at the handoff-function boundary; return the call log."""
    calls: list[dict] = []

    def fake_pr_create(repo, base_branch, title, head=None, body=None):
        calls.append({"repo": Path(repo), "base": base_branch, "title": title, "head": head})
        return f"https://example.test/pr/{len(calls)}"

    monkeypatch.setattr(ho, "gh_available", lambda: True)
    monkeypatch.setattr(ho, "_gh_pr_create", fake_pr_create)
    return calls


def _work_argv(repo: Path, *extra: str, instruction: str = "chain the work") -> list[str]:
    return [
        "work",
        "--engine",
        "mock",
        "--repo",
        str(repo),
        "--max-steps",
        "1",
        *extra,
        instruction,
    ]


def _colleague_branches(repo: Path) -> list[str]:
    proc = _run_git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads/colleague/")
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _lineage_artifacts(repo: Path) -> list[dict]:
    """The chain's artifacts oldest-first, walked back from ``last_work``."""
    last = (repo / ".colleague" / "last_work").read_text().strip()
    chain: list[dict] = []
    task_id: str | None = last
    while task_id:
        path = find_artifact(repo, task_id)
        assert path is not None, f"artifact missing for {task_id}"
        data = json.loads(path.read_text())
        chain.append(data)
        task_id = data.get("continued_from")
    chain.reverse()
    return chain


def _branch_tree_files(repo: Path, branch: str) -> set[str]:
    proc = _run_git(repo, "ls-tree", "-r", "--name-only", branch)
    return {line.strip() for line in proc.stdout.splitlines() if line.strip()}


def _no_intervention(*_args, **_kwargs) -> str:
    raise AssertionError("operator intervention requested — the chain must run unattended")


def _last_artifact(repo: Path) -> dict:
    last = (repo / ".colleague" / "last_work").read_text().strip()
    path = find_artifact(repo, last)
    assert path is not None
    return json.loads(path.read_text())


# ---------------------------------------------------------------------------
# Criterion 1 — chain-completes (c1/h1, c9, c16 carry, c17)
# ---------------------------------------------------------------------------


def test_chain_completes(git_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    """A mock-engine task sized to need >= 3 episodes (three budget exits, then
    a finish — 4 episodes) lands its deliverable with status ok, lineage chain
    length >= 3, and ZERO operator interventions: no prompt (``input`` guarded),
    no PR (``--no-pr`` held), no flag beyond the arming ``--until-done`` — the
    episode cap is the armed DEFAULT (5, decision c21), never re-supplied."""
    from colleague.cli import main

    _script_episodes(monkeypatch, ["budget", "budget", "budget", "finish"])
    pr_calls = _gate_pr_boundary(monkeypatch)
    monkeypatch.setattr(builtins, "input", _no_intervention)

    rc = main(_work_argv(git_repo, "--until-done", "--no-pr"))
    assert rc == 0

    episodes = _lineage_artifacts(git_repo)
    assert len(episodes) >= 3
    assert len(episodes) == 4
    final = episodes[-1]
    assert final["status"] == "ok"

    # The deliverable LANDED: the final branch carries every episode's work —
    # cumulative tree carry (the c16 carry limit removed: episode N+1 based on
    # episode N's tip, not a fresh HEAD).
    files = _branch_tree_files(git_repo, final["branch"])
    assert {"episode-1.txt", "episode-2.txt", "episode-3.txt"} <= files

    # Lineage: an unbroken continued_from chain, rooted at episode 1.
    assert episodes[0].get("continued_from") is None
    for prev, cur in zip(episodes, episodes[1:]):
        assert cur["continued_from"] == prev["task_id"]

    # Chain view: the final artifact describes the whole chain — sums of the
    # per-episode exacts (h19), 1-based indexing.
    assert [e["chain"]["episode_index"] for e in episodes] == [1, 2, 3, 4]
    assert final["chain"]["episode_count"] == 4
    assert final["chain"]["total_tokens"] == sum(e["usage"]["total_tokens"] for e in episodes)
    assert final["chain"]["total_steps"] == sum(len(e["steps"]) for e in episodes)

    # Zero operator interventions: no PR was opened (--no-pr held on the one
    # chain handoff), input was never consulted (the monkeypatch would have
    # raised), and the run needed no mid-chain flags/answers.
    assert pr_calls == []
    assert all(e["pr_url"] is None for e in episodes)

    # The armed DEFAULT cap (c21) drove the boundary announcements — no
    # --max-episodes flag was passed anywhere in this test.
    err = capsys.readouterr().err
    assert f"episode 2 of 5: continuing {episodes[0]['task_id']}" in err
    assert f"episode 4 of 5: continuing {episodes[2]['task_id']}" in err

    # Intermediates reaped after the one handoff: only the final branch stays.
    assert _colleague_branches(git_repo) == [final["branch"]]


# ---------------------------------------------------------------------------
# Chain-episode marker plumbing (indefinite-run follow-up, issue #335, c22):
# execute_work_chain accumulates each episode's result.changed_files into the
# UNION handed to the NEXT episode's ChainEpisodeOptions.prior_changed.
# ---------------------------------------------------------------------------


def test_chain_accumulates_changed_files_across_episodes(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real 2-episode chain (episode 1 budget-exits after writing
    ``episode-1.txt``, episode 2 finishes): the SECOND episode's
    ``ChainEpisodeOptions.prior_changed`` carries episode 1's changed file, and
    the FIRST episode's carries none (nothing to inherit yet)."""
    from colleague.cli import main
    from colleague.cli._commands import work as work_mod

    _script_episodes(monkeypatch, ["budget", "finish"])
    _gate_pr_boundary(monkeypatch)
    monkeypatch.setattr(builtins, "input", _no_intervention)

    seen_chains: list = []
    orig_execute_work = work_mod.execute_work

    def _spy_execute_work(**kwargs):
        seen_chains.append(kwargs.get("chain"))
        return orig_execute_work(**kwargs)

    monkeypatch.setattr(work_mod, "execute_work", _spy_execute_work)

    rc = main(_work_argv(git_repo, "--until-done", "--no-pr"))
    assert rc == 0

    episodes = _lineage_artifacts(git_repo)
    assert len(episodes) == 2
    assert episodes[0]["changed_files"] == ["episode-1.txt"]

    # execute_work_chain dispatched exactly 2 episodes through execute_work
    # (the chain loop's only caller of it), each carrying a ChainEpisodeOptions.
    assert len(seen_chains) == 2
    assert seen_chains[0] is not None
    assert seen_chains[0].prior_changed == ()  # episode 1: nothing prior yet
    assert seen_chains[1] is not None
    # episode 2 inherits the UNION of every prior episode's changed files.
    assert seen_chains[1].prior_changed == ("episode-1.txt",)


# ---------------------------------------------------------------------------
# Criterion 2 — chain-halts-honestly (c10/h10, c22, #313 intact)
# ---------------------------------------------------------------------------


def test_chain_halts_honestly(git_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    """A deliberately no-progress task (read-only turns: no commits, no new
    artifact evidence) halts within 2 episodes with a non-ok status and an
    incompletion reason. The scripted plan ends in a "finish" BAIT: if the
    no-progress guard failed and the chain kept dispatching, a later episode
    would finish ok (rc 0) and this test would fail — the halt is provably the
    guard's, not the script running out."""
    from colleague.cli import main

    counter = _script_episodes(monkeypatch, ["idle", "idle", "finish"])
    pr_calls = _gate_pr_boundary(monkeypatch)

    rc = main(_work_argv(git_repo, "--until-done", "--no-pr"))
    assert rc == 2  # the halted chain reports its last episode honestly (#313)

    # Halted within 2 episodes; the "finish" bait episode never dispatched.
    assert counter["n"] <= 2
    episodes = _lineage_artifacts(git_repo)
    assert 1 <= len(episodes) <= 2

    # Non-ok, with an honest incompletion reason on the final artifact.
    final = episodes[-1]
    assert final["status"] != "ok"
    assert final["status"] == "incomplete"
    record = final.get("incompletion")
    assert record is not None
    assert record.get("reason") == "budget-exhausted"
    assert record.get("recommendation")

    # The halt names no-progress on the progress channel (observable trace).
    err = capsys.readouterr().err
    assert "no-progress" in err

    # An honest halt never hands off.
    assert pr_calls == []
    assert all(e["pr_url"] is None for e in episodes)


# ---------------------------------------------------------------------------
# Criterion 3 — compaction-validated (c16 validation limit removed, h15/h16)
# ---------------------------------------------------------------------------


def _fillline_script(monkeypatch: pytest.MonkeyPatch, *, summary: str, crossings: int) -> None:
    """Script the mock engine to cross the fill line in a REAL work dispatch.

    Turn shape (content-matched, the tests/test_fillline.py idiom, but through
    the real dispatch): each of the first *crossings* working turns reports
    ``prompt_tokens=90_000`` against a 100_000 budget (>= the 0.8 default
    threshold — usage-exact by contract, so the crossing is deterministic);
    the decision prompt is answered with a pure no-tool reply (declares
    COMPACT); the summarization turn returns *summary*; between crossings one
    working turn reports 5_000 tokens (back under the line — the re-arm
    window); everything after the last crossing finishes.
    """
    state = {"work": 0}

    def fake_script(task):
        def complete(messages):
            last = str(messages[-1].get("content") or "")
            if "Summarize everything done" in last:
                return ModelResponse(content=summary, prompt_tokens=5, completion_tokens=1)
            if "declare ONE move" in last:
                return ModelResponse(
                    content="compacting", prompt_tokens=90_000, completion_tokens=1
                )
            state["work"] += 1
            n = state["work"]
            if n <= 2 * crossings - 1:
                over = n % 2 == 1  # odd working turns cross; even ones drop back under
                return ModelResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            f"w{n}", "write_file", {"path": f"work-{n}.txt", "content": "work\n"}
                        )
                    ],
                    prompt_tokens=90_000 if over else 5_000,
                    completion_tokens=1,
                )
            return ModelResponse(
                content="done",
                tool_calls=[ToolCall("fin", "finish", {"summary": "delivered the work files"})],
                prompt_tokens=5,
                completion_tokens=1,
            )

        return complete

    monkeypatch.setattr("colleague.engines.mock._script", fake_script)


def _spy_apply_compaction(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Spy (never stub) the ONE seam a summary replaces history through."""
    applied: list[str] = []
    real_apply = fillline.apply_compaction

    def spy(messages, summary):
        applied.append(summary)
        return real_apply(messages, summary)

    monkeypatch.setattr(fillline, "apply_compaction", spy)
    return applied


def test_compaction_validated(git_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    """An empty (unrepairable) compaction summary NEVER silently replaces
    history, proven through the FULL dispatch (``colleague.cli.main`` work verb
    on the mock engine — see the module docstring for the level rationale):
    ``apply_compaction`` — the only seam history is replaced through — is spied
    and never called, and the rejection is OBSERVABLE on the trace (the #206
    phase-notice line on stderr). The run still completes (rejection degrades,
    never aborts) and the declared move stays recorded on the artifact."""
    from colleague.cli import main

    monkeypatch.setenv("COLLEAGUE_CONTEXT_BUDGET", "100000")
    _fillline_script(monkeypatch, summary="   \n ", crossings=1)
    applied = _spy_apply_compaction(monkeypatch)

    rc = main(
        ["work", "--engine", "mock", "--repo", str(git_repo), "--no-pr", "cross the fill line"]
    )
    assert rc == 0  # rejection is a floor, never an abort

    # The empty note never replaced history — the seam was never crossed.
    assert applied == []

    # The rejection is observable on the trace, with its floor policy named.
    err = capsys.readouterr().err
    assert "compaction produced an empty summary — rejected (history not replaced)" in err

    # The declaration itself was honestly recorded (the move ran and was
    # rejected — not silently skipped).
    data = _last_artifact(git_repo)
    assert data["capacity_decision"]["kind"] == "compact"
    assert "fill line" in data["capacity_decision"]["reason"]


def test_fillline_rearms_per_crossing_in_one_dispatch(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """The c16 fires-at-most-once limit is REMOVED (indefinite-run t1), proven
    in one real dispatch: two separate fill-line crossings in the same work
    item each get an offer and each compact — a validated summary replaces
    history TWICE (the v1 behavior compacted at most once per work item)."""
    from colleague.cli import main

    monkeypatch.setenv("COLLEAGUE_CONTEXT_BUDGET", "100000")
    _fillline_script(monkeypatch, summary="did some work so far; more remains", crossings=2)
    applied = _spy_apply_compaction(monkeypatch)

    rc = main(
        ["work", "--engine", "mock", "--repo", str(git_repo), "--no-pr", "cross the line twice"]
    )
    assert rc == 0

    # TWO validated compactions landed in one work item (v1 allowed one).
    assert len(applied) == 2
    # Each applied note passed validation: non-empty, and carrying the run's
    # own evidence (the t2 validator repairs the changed-file paths in).
    for note in applied:
        assert note.strip()
        assert "did some work so far" in note
    assert "work-1.txt" in applied[0]

    # Both compaction turns were announced on the trace (#206).
    err = capsys.readouterr().err
    assert err.count("compacting the conversation") == 2

    data = _last_artifact(git_repo)
    assert data["capacity_decision"]["kind"] == "compact"


# ---------------------------------------------------------------------------
# Criterion 4 — dormancy (c9/h9, c19/h18: unarmed = byte-identical)
# ---------------------------------------------------------------------------

#: The pre-feature artifact key set for a clean mock work item — the SAME pin
#: tests/test_e2e_mock.py guards (the artifact JSON is exactly
#: ``TaskResult.to_dict()``, see colleague/artifact.py::write), PLUS
#: ``tip_sha``: unlike ``tests/test_e2e_mock.py``'s pin (which calls the mock
#: engine directly, bypassing the CLI handoff), this test drives the real
#: ``main(["work", ...])`` path in a real git repo, so the handoff really lands
#: a commit and ``tip_sha`` is legitimately populated (plan task t5, c5) — a
#: baseline handoff key like ``branch``/``pr_url``, not a chain/indefinite-run
#: arc key.
_PRE_FEATURE_ARTIFACT_KEYS = frozenset(
    {
        "task_id",
        "status",
        "summary",
        "changed_files",
        "steps",
        "usage",
        "stats",
        "finish_states",
        "artifacts_path",
        "error",
        "branch",
        "pr_url",
        "hook_firings",
        "command",
        "not_finished",
        "stopped_without_finish",
        "tip_sha",
        # prompt_digest (plan task t7): the sha256 of the composed system
        # prompt is UNCONDITIONAL observability — every run that composes a
        # prompt carries it, so a live-testing row can attribute its prose
        # arm. Omitted only when the backend composed no prompt at all.
        "prompt_digest",
        # offered_tools (delegation-follow-ups t2): rendered tool names, omit-when-None.
        "offered_tools",
        "effort",  # t5: the resolved-rung block (v4 default always resolves)
        "warnings",  # #479 t9: the resolved sampling profile (kind="sampling")
    }
)

#: Every serialized key the indefinite-run arc introduced. The chain view is
#: the arc's ONE new artifact key; ``continued_from`` predates the arc (#167)
#: but must equally stay absent from a bare run.
_ARC_KEYS_ABSENT_WHEN_DORMANT = ("chain", "continued_from")


def test_dormant_bare_work_artifact_is_byte_identical(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """With NO chain flag/env/config, a bare work item's artifact carries
    exactly the pre-feature key set: key-set equality against the pinned
    reference plus explicit absence of every arc key (an exact golden-string
    comparison would pin volatile ids/paths; key-set equality is the honest
    byte-identity guard, matching the tests/test_e2e_mock.py convention)."""
    from colleague.cli import main

    # Hermetic against ambient machine state the conftest scrub doesn't cover:
    # a set COHERENCE_EMBED_URL would legitimately add coherence_report.
    monkeypatch.delenv("COHERENCE_EMBED_URL", raising=False)

    rc = main(["work", "--engine", "mock", "--repo", str(git_repo), "--no-pr", "a bare work item"])
    assert rc == 0

    data = _last_artifact(git_repo)
    assert data["status"] == "ok"
    assert set(data.keys()) == _PRE_FEATURE_ARTIFACT_KEYS
    for key in _ARC_KEYS_ABSENT_WHEN_DORMANT:
        assert key not in data, f"dormant run leaked the {key!r} key into its artifact"


def test_boundary_sanctioned_lists_unchanged() -> None:
    """The tests/test_boundary.py authority lists are UNCHANGED by the arc:
    the chain lives at the dispatch layer (pure verdicts over persisted
    artifacts) and joined neither sanctioned list. Pins the exact entries so a
    silent addition fails here even if test_boundary.py were edited in the
    same change; also sweeps the arc's new module directly (the flight.py
    named-check precedent)."""
    from tests.test_boundary import _SUBPROCESS_ALLOWED, _THREADS_ALLOWED

    assert _SUBPROCESS_ALLOWED == frozenset(
        {
            "colleague/hooks.py",
            "colleague/tools.py",
            "colleague/handoff.py",
            "colleague/neighbours.py",
            "colleague/culture.py",
            "colleague/devague.py",
            "colleague/worktrees.py",
            "colleague/lint.py",
            "colleague/resident/steward.py",
            "colleague/affectedtests.py",
            "colleague/background.py",
            "colleague/memory.py",
            "colleague/coherence.py",
            "colleague/livecheck.py",
            "colleague/experiment.py",
            # self-learning arc: strive.py runs the operator-supplied measure
            # command (approval-gated, t14); correction.py shells git/gh for
            # the integrator-correction diff (t7) — reasons in test_boundary.py.
            "colleague/strive.py",
            "colleague/correction.py",
            # search-tools arc (task t5): grep_search's ripgrep fast path
            # shells out to the operator-installed `rg` CLI; the stdlib
            # walker is the fallback — reasons pinned in test_boundary.py.
            "colleague/search_tools.py",
            # web-scout arc (task t1): the curated `web` tool shells out to the
            # operator-installed `webglass` CLI in its own process group.
            "colleague/web.py",
        }
    )
    # colleague/realtime.py joined this list under the realtime-speech arc
    # (plan task t2), unrelated to this one — the chain/dispatch layer still
    # joined neither list, which is the only claim this test makes.
    assert _THREADS_ALLOWED == frozenset(
        {
            "colleague/subagents.py",
            "colleague/cli/_commands/_input_line.py",
            "colleague/realtime.py",
            "colleague/toolbatch.py",
            # PR #464 (Qodo 4/7): a threading.Lock around the one-per-process
            # associate /tokenize probe — a lock only, no thread is started.
            "colleague/associate.py",
        }
    )

    # The arc's decision module is pure: no subprocess/thread/socket/daemon
    # primitive — it never needed a sanction.
    chain_src = (Path(__file__).resolve().parents[1] / "colleague" / "chain.py").read_text(
        encoding="utf-8"
    )
    for forbidden in (
        "import subprocess",
        "import threading",
        "concurrent.futures",
        "import socket",
        "import asyncio",
    ):
        assert forbidden not in chain_src, f"chain.py must not use {forbidden!r}"


def test_chain_view_shape_identical_across_engines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """All-engines guard, extended for the chain field: neither engine stamps a
    chain view of its own (dormant on both — no ``chain`` key), and the
    dispatch-layer stamp (``ChainView.accumulate``, the same call
    ``execute_work`` makes for a chained episode) yields the IDENTICAL
    serialized shape on a mock result and a vllm-openai-shaped result."""
    from colleague import registry
    from colleague.config import EngineConfig
    from colleague.contract import OK, ChainView, Task
    from tests.test_e2e_mock import _key_shape, _mock_vllm_http

    _mock_vllm_http(monkeypatch)
    cfg = EngineConfig.resolve()

    mock_repo = tmp_path / "mock"
    vllm_repo = tmp_path / "vllm"
    mock_repo.mkdir()
    vllm_repo.mkdir()

    mock_result = registry.load("mock").work(Task.new(str(mock_repo), "do work"), cfg)
    vllm_result = registry.load("vllm-openai").work(Task.new(str(vllm_repo), "do work"), cfg)

    # Dormant on BOTH engines: the loop/engine never sets the chain view.
    for result in (mock_result, vllm_result):
        assert result.status == OK
        assert result.chain is None
        assert "chain" not in result.to_dict()

    # The dispatch layer stamps it engine-agnostically — identical shape.
    mock_result.chain = ChainView.accumulate(None, mock_result)
    vllm_result.chain = ChainView.accumulate(None, vllm_result)
    assert _key_shape(mock_result.to_dict()) == _key_shape(vllm_result.to_dict())
    for result in (mock_result, vllm_result):
        assert set(result.to_dict()["chain"].keys()) == {
            "episode_index",
            "episode_count",
            "total_steps",
            "total_prompt_tokens",
            "total_completion_tokens",
            "total_tokens",
        }
