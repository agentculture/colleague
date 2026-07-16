"""Tests for the ``work --until-done`` episode chain loop (indefinite-run t5).

Acceptance criteria:

1. ``colleague work --until-done [--max-episodes N]`` runs the episode chain:
   each non-final episode suppresses push/PR, the FINAL episode hands off once
   with the cumulative diff (episode branches chain from each other), and
   intermediate ``colleague/<id>`` branches are reaped after completion — a
   3-episode ``--pr`` chain opens exactly one PR (c26/h21).
2. Every episode inherits the arming invocation's resolved options verbatim
   (engine, ``--no-pr``, budgets); nothing re-resolves from a mid-chain
   config/env change (c28/h23).
3. Lineage stamps ``continued_from`` episode-to-episode and the chain view
   accumulates exact per-episode usage; the ok-guard holds inside the chain
   (an ok episode is never re-dispatched).

The episodes are driven end-to-end through ``colleague.cli.main`` with the
mock engine, its script monkeypatched per episode (the same in-process e2e
harness pattern as ``tests/test_cli_work_continue.py``); the PR boundary is
gated at the handoff-function seam (``gh_available`` / ``_gh_pr_create``
monkeypatched — the ``tests/test_handoff.py`` fake pattern), never a real
``gh`` call.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from colleague import flight
from colleague import handoff as ho
from colleague.artifact import find_artifact
from colleague.loop import ModelResponse, ToolCall

# ---------------------------------------------------------------------------
# Harness
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


@pytest.fixture
def origin(tmp_path: Path, git_repo: Path) -> Path:
    """A bare 'origin' remote wired onto ``git_repo`` (real pushes, no network)."""
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True, capture_output=True)
    _run_git(git_repo, "remote", "add", "origin", str(bare))
    return bare


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


def _handoff_reply(episode: int, messages) -> ModelResponse:
    """A REAL declared fill-line finish-with-handoff episode (the d1 shape).

    The working turn's prompt_tokens cross the fill line (90 >= 0.8 * 100 with
    ``COLLEAGUE_CONTEXT_BUDGET=100``); the fill-line decision prompt is answered
    with finish → classified finish-with-handoff → an ok finish the chain's
    ok-guard halts on (completed), while the loop deferred its gates (#340).
    """
    last = str(messages[-1].get("content") or "")
    if "declare ONE move" in last:
        return ModelResponse(
            content="handing off",
            tool_calls=[ToolCall("f", "finish", {"summary": "continuation summary"})],
            prompt_tokens=90,
            completion_tokens=1,
        )
    return ModelResponse(
        content="",
        tool_calls=[
            ToolCall(
                f"h{episode}",
                "write_file",
                {"path": f"episode-{episode}.txt", "content": f"episode {episode} work\n"},
            )
        ],
        prompt_tokens=90,
        completion_tokens=1,
    )


def _script_episodes(monkeypatch: pytest.MonkeyPatch, plan, on_episode=None) -> dict:
    """Monkeypatch the mock engine's script: one entry of *plan* per episode.

    ``plan`` is a list of "budget" / "idle" / "finish" strings; episode N uses
    ``plan[N-1]`` (the last entry repeats past the end). ``on_episode(n)``, when
    given, runs as each episode's script is built — the hook the mid-chain
    config-change test uses. Returns the shared counter dict.
    """
    counter = {"n": 0}

    def fake_script(task):
        counter["n"] += 1
        n = counter["n"]
        if on_episode is not None:
            on_episode(n)
        kind = plan[min(n, len(plan)) - 1]

        def complete(messages):
            if kind == "budget":
                return _budget_turn(n)
            if kind == "idle":
                return _idle_turn(n)
            if kind == "handoff":
                return _handoff_reply(n, messages)
            return _finish_turn()

        return complete

    monkeypatch.setattr("colleague.engines.mock._script", fake_script)
    return counter


def _gate_pr_boundary(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Gate PR creation at the handoff-function boundary; return the call log."""
    calls: list[dict] = []

    def fake_pr_create(repo, base_branch, title, head=None, body=None):
        calls.append(
            {"repo": Path(repo), "base": base_branch, "title": title, "head": head, "body": body}
        )
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


# ---------------------------------------------------------------------------
# Criterion 1 — handoff-once + reap (c26 / h21)
# ---------------------------------------------------------------------------


class TestChainHandoffOnce:
    def test_three_episode_chain_opens_exactly_one_pr(self, git_repo, origin, monkeypatch):
        """3 episodes, --pr default: ONE PR, cumulative diff, intermediates reaped."""
        from colleague.cli import main

        _script_episodes(monkeypatch, ["budget", "budget", "finish"])
        pr_calls = _gate_pr_boundary(monkeypatch)

        rc = main(_work_argv(git_repo, "--until-done", "--max-episodes", "5"))
        assert rc == 0

        # Exactly one PR, opened for the FINAL episode's branch (h21).
        episodes = _lineage_artifacts(git_repo)
        assert len(episodes) == 3
        final = episodes[-1]
        assert len(pr_calls) == 1
        assert pr_calls[0]["head"] == final["branch"]

        # The final artifact carries the real pr_url, never synthesized.
        assert final["pr_url"] == "https://example.test/pr/1"

        # Exactly one colleague/* branch reached the remote (non-final suppressed).
        remote_refs = subprocess.run(
            ["git", "ls-remote", "--heads", str(origin), "refs/heads/colleague/*"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()
        assert len([r for r in remote_refs if r.strip()]) == 1

        # Cumulative diff: the final branch carries BOTH prior episodes' work
        # (episode N+1's worktree was based on episode N's tip — tree carry).
        files = _branch_tree_files(git_repo, final["branch"])
        assert "episode-1.txt" in files
        assert "episode-2.txt" in files

        # Intermediate colleague/<id> branches were reaped; only the final stays.
        assert _colleague_branches(git_repo) == [final["branch"]]

    def test_halted_chain_leaves_every_branch(self, git_repo, origin, monkeypatch):
        """A no-progress halt keeps all episode branches (WIP) and opens no PR."""
        from colleague.cli import main

        _script_episodes(monkeypatch, ["budget", "idle"])
        pr_calls = _gate_pr_boundary(monkeypatch)

        rc = main(_work_argv(git_repo, "--until-done", "--max-episodes", "5"))
        assert rc == 2  # final episode is honest INCOMPLETE

        episodes = _lineage_artifacts(git_repo)
        assert len(episodes) == 2
        assert pr_calls == []
        # Both episode branches remain — the operator may want the WIP.
        assert len(_colleague_branches(git_repo)) == 2

    def test_cap_reached_halts_without_pr(self, git_repo, origin, monkeypatch):
        """Hitting --max-episodes halts honestly: no PR, branches kept, exit 2."""
        from colleague.cli import main

        _script_episodes(monkeypatch, ["budget", "budget", "budget"])
        pr_calls = _gate_pr_boundary(monkeypatch)

        rc = main(_work_argv(git_repo, "--until-done", "--max-episodes", "2"))
        assert rc == 2

        episodes = _lineage_artifacts(git_repo)
        assert len(episodes) == 2
        assert episodes[-1]["chain"]["episode_index"] == 2
        assert pr_calls == []
        assert len(_colleague_branches(git_repo)) == 2


# ---------------------------------------------------------------------------
# Gate-deferral surfacing (#341 halted / #340 completed) — chained e2e
# ---------------------------------------------------------------------------


class TestChainGateDeferralSurfacing:
    def test_halted_chain_outcome_names_deferred_episodes(self, git_repo, monkeypatch, capsys):
        """#341: a cap-halted chain's outcome names the deferring episodes and
        the kept WIP branches; the final artifact's chain view carries
        deferred_gate_episodes (typed, no string-matching)."""
        from colleague.cli import main

        _script_episodes(monkeypatch, ["budget", "budget", "budget"])
        _gate_pr_boundary(monkeypatch)

        rc = main(_work_argv(git_repo, "--until-done", "--max-episodes", "2"))
        assert rc == 2

        episodes = _lineage_artifacts(git_repo)
        ids = [ep["task_id"] for ep in episodes]
        # Both budget-exited episodes deferred: per-episode marker + chain list.
        assert all(ep.get("gates_deferred") is True for ep in episodes)
        assert episodes[-1]["chain"]["deferred_gate_episodes"] == ids

        err = capsys.readouterr().err
        assert "gates deferred on episode(s)" in err
        for task_id in ids:
            assert task_id in err
        assert "ungated WIP" in err
        for branch in _colleague_branches(git_repo):
            assert branch in err

    def test_completed_chain_with_deferred_final_warns_everywhere(
        self, git_repo, origin, monkeypatch, capsys
    ):
        """#340 B: ok-finish + declared fill-line handoff completes the chain and
        fires the handoff with the final episode's gates skipped — the outcome
        line, the artifact flag, and the PR body all say so; exit stays 0."""
        from colleague.cli import main

        monkeypatch.setenv("COLLEAGUE_CONTEXT_BUDGET", "100")
        _script_episodes(monkeypatch, ["budget", "handoff"])
        pr_calls = _gate_pr_boundary(monkeypatch)

        rc = main(_work_argv(git_repo, "--until-done", "--max-episodes", "5", "--max-steps", "3"))
        assert rc == 0

        episodes = _lineage_artifacts(git_repo)
        assert len(episodes) == 2
        final = episodes[-1]
        # The final episode really took the declared-handoff shape and deferred.
        assert final["capacity_decision"]["kind"] == "finish-with-handoff"
        assert final["gates_deferred"] is True
        assert final["task_id"] in final["chain"]["deferred_gate_episodes"]

        # The ONE handoff fired, its PR body carrying the warning.
        assert len(pr_calls) == 1
        assert pr_calls[0]["body"] is not None
        assert "gates" in pr_calls[0]["body"] and "deferred" in pr_calls[0]["body"]

        err = capsys.readouterr().err
        assert "handed off with the final episode's pre-finish gates deferred" in err

    def test_halted_then_continued_chain_ends_gated(self, git_repo, monkeypatch):
        """#341(3): continue-the-chain is the documented remedy for ungated
        halted WIP — a cap-halted chain resumed with --continue --until-done
        ends with a GATED final episode whose gates graded the inherited
        union, and the resumed accounting still names every deferring episode.
        """
        from colleague.cli import main

        # Record what the lint gate was asked to grade (the union evidence);
        # the loop calls through its module alias, so patching the source
        # module is visible (the tests/test_gate_deferral.py recorder shape).
        lint_calls: list[list[str]] = []

        def fake_lint(repo, changed):
            lint_calls.append(list(changed))
            from colleague.contract import LintReport

            return LintReport(fixed=["stub: reformatted"])

        monkeypatch.setattr("colleague.lint.run_lint_gate", fake_lint)

        # Cut chain: two budget episodes, cap 2 → halted with ungated WIP.
        _script_episodes(monkeypatch, ["budget", "budget", "budget", "finish"])
        rc = main(_work_argv(git_repo, "--until-done", "--max-episodes", "2", "--no-pr"))
        assert rc == 2
        halted = _lineage_artifacts(git_repo)
        halted_ids = [ep["task_id"] for ep in halted]
        assert halted[-1]["chain"]["deferred_gate_episodes"] == halted_ids

        # Continue the halted chain; script entries 3 (budget) + 4 (finish)
        # become continuation episodes 1-2.
        rc2 = main(
            [
                "work",
                "--engine",
                "mock",
                "--repo",
                str(git_repo),
                "--max-steps",
                "1",
                "--continue",
                "last",
                "--until-done",
                "--no-pr",
            ]
        )
        assert rc2 == 0

        lineage = _lineage_artifacts(git_repo)
        final = lineage[-1]
        # The finishing episode ran its gates — no deferral marker on it...
        assert final["status"] == "ok"
        assert "gates_deferred" not in final
        # ...over the inherited union: episode 3's file reached the gate even
        # though the finishing episode itself changed nothing.
        assert lint_calls, "the final episode never ran the lint gate"
        assert "episode-3.txt" in lint_calls[-1]
        # The resumed accounting still names every deferring episode (the cut
        # run's two + the continuation's budget episode), and not the final.
        deferred = final["chain"]["deferred_gate_episodes"]
        assert lineage[-2]["task_id"] in deferred
        assert set(halted_ids) <= set(deferred)
        assert final["task_id"] not in deferred

    def test_continued_halt_outcome_resolves_inherited_deferred_branches(
        self, git_repo, monkeypatch, capsys
    ):
        """#341 (Qodo, PR #345): a chain resumed via --continue inherits the cut
        run's deferred_gate_episodes, but those episodes' WIP branches were
        minted by the FIRST invocation — the resumed halt's outcome line must
        resolve each inherited id's branch from the episode's own artifact
        (or mark it explicitly unresolved), never render a silently shorter
        branch list than the ids it names."""
        from colleague.cli import main

        # Cut chain: two budget episodes, cap 2 → halted with ungated WIP.
        _script_episodes(monkeypatch, ["budget", "budget", "budget", "budget"])
        rc = main(_work_argv(git_repo, "--until-done", "--max-episodes", "2", "--no-pr"))
        assert rc == 2
        inherited = {ep["task_id"]: ep["branch"] for ep in _lineage_artifacts(git_repo)}
        assert all(inherited.values())  # each cut episode recorded its branch
        capsys.readouterr()  # flush the first invocation's outcome lines

        # Continue the halted chain; script entries 3-4 (both budget) hit the
        # cap again, so the CONTINUED chain also halts with inherited deferrals.
        rc2 = main(
            [
                "work",
                "--engine",
                "mock",
                "--repo",
                str(git_repo),
                "--max-steps",
                "1",
                "--continue",
                "last",
                "--until-done",
                "--max-episodes",
                "2",
                "--no-pr",
            ]
        )
        assert rc2 == 2

        err = capsys.readouterr().err
        deferral_lines = [ln for ln in err.splitlines() if "gates deferred on episode(s)" in ln]
        assert deferral_lines, "the resumed halt never emitted the deferral outcome line"
        line = deferral_lines[-1]
        # The inherited ids are named AND each carries its real WIP branch
        # (resolved from its artifact) or the explicit unresolved marker.
        for task_id, branch in inherited.items():
            assert task_id in line
            assert branch in line or f"{task_id} (branch not resolved)" in line

    def test_unresolvable_deferred_id_gets_explicit_marker(self, tmp_path, capsys):
        """The honest fallback: a deferred id with no id→branch entry AND no
        resolvable artifact renders '<id> (branch not resolved)' — the outcome
        line never silently claims the branch list is complete."""
        from types import SimpleNamespace

        from colleague.cli._commands.work import _emit_chain_outcome

        _emit_chain_outcome(
            SimpleNamespace(reason="cap-reached", detail=""),
            SimpleNamespace(episode_count=1, episode_ids=["cur1"]),
            completed=False,
            branches=["colleague/cur1-current-work"],
            deferred=("cur1", "ghost1"),
            repo=tmp_path,  # no .colleague/ dir → ghost1's artifact resolves to None
        )

        err = capsys.readouterr().err
        line = [ln for ln in err.splitlines() if "gates deferred on episode(s)" in ln][-1]
        assert "colleague/cur1-current-work" in line
        assert "ghost1 (branch not resolved)" in line

    def test_completed_gated_chain_renders_no_warning(self, git_repo, origin, monkeypatch, capsys):
        """Byte-identity: a completed chain whose final episode ran its gates
        gets today's outcome lines exactly — no warning, --fill PR body."""
        from colleague.cli import main

        _script_episodes(monkeypatch, ["budget", "finish"])
        pr_calls = _gate_pr_boundary(monkeypatch)

        rc = main(_work_argv(git_repo, "--until-done", "--max-episodes", "5"))
        assert rc == 0

        assert len(pr_calls) == 1
        assert pr_calls[0]["body"] is None  # the --fill path, byte-identical

        err = capsys.readouterr().err
        assert "gates deferred on episode(s)" not in err
        assert "pre-finish gates deferred" not in err


# ---------------------------------------------------------------------------
# Criterion 2 — verbatim inheritance (c28 / h23)
# ---------------------------------------------------------------------------


class TestChainInheritance:
    def test_engine_and_no_pr_survive_mid_chain_config_change(self, git_repo, origin, monkeypatch):
        """--engine mock --no-pr hold on every episode; a mid-chain config.json /
        env change is never re-resolved (h23)."""
        from colleague.cli import main

        def sabotage(n: int) -> None:
            # Before episode 2 dispatches, rewrite the on-disk config and env to
            # values that would (if re-read) disarm the chain and cap it at 1.
            if n == 2:
                cfg = git_repo / ".colleague" / "config.json"
                cfg.parent.mkdir(parents=True, exist_ok=True)
                cfg.write_text(json.dumps({"until_done": False, "max_episodes": 1}))
                monkeypatch.setenv("COLLEAGUE_UNTIL_DONE", "0")
                monkeypatch.setenv("COLLEAGUE_MAX_EPISODES", "1")
                monkeypatch.setenv("COLLEAGUE_ENGINE", "vllm-openai")

        _script_episodes(monkeypatch, ["budget", "budget", "finish"], on_episode=sabotage)
        pr_calls = _gate_pr_boundary(monkeypatch)

        rc = main(_work_argv(git_repo, "--until-done", "--no-pr"))
        assert rc == 0

        episodes = _lineage_artifacts(git_repo)
        # The mid-chain change did NOT shrink the chain (3 episodes ran)...
        assert len(episodes) == 3
        # ...every episode ran the arming invocation's engine...
        assert [e["stats"]["engine"] for e in episodes] == ["mock", "mock", "mock"]
        # ...and --no-pr held on every episode INCLUDING the final handoff
        # (remote + gh were available, so a dropped --no-pr would have PR'd).
        assert pr_calls == []
        assert all(e["pr_url"] is None for e in episodes)

    def test_budgets_inherited_every_episode(self, git_repo, monkeypatch):
        """--max-steps 1 rides every episode: each artifact shows one step."""
        from colleague.cli import main

        _script_episodes(monkeypatch, ["budget", "budget", "finish"])
        rc = main(_work_argv(git_repo, "--until-done", "--no-pr"))
        assert rc == 0

        episodes = _lineage_artifacts(git_repo)
        assert len(episodes) == 3
        for data in episodes[:-1]:  # budget episodes stopped at exactly 1 step
            assert len(data["steps"]) == 1


# ---------------------------------------------------------------------------
# Criterion 3 — lineage, chain view, ok-guard
# ---------------------------------------------------------------------------


class TestChainLineageAndView:
    def test_lineage_and_chain_view_accumulate(self, git_repo, monkeypatch):
        from colleague.cli import main

        _script_episodes(monkeypatch, ["budget", "budget", "finish"])
        rc = main(_work_argv(git_repo, "--until-done", "--no-pr"))
        assert rc == 0

        episodes = _lineage_artifacts(git_repo)
        assert len(episodes) == 3
        # Episode-to-episode lineage: 1 <- 2 <- 3; episode 1 is the chain root.
        assert episodes[0].get("continued_from") is None
        assert episodes[1]["continued_from"] == episodes[0]["task_id"]
        assert episodes[2]["continued_from"] == episodes[1]["task_id"]
        # Chain view per artifact: 1-based index; totals are sums of exacts (h19).
        for i, data in enumerate(episodes, start=1):
            assert data["chain"]["episode_index"] == i
        expected_steps = sum(len(d["steps"]) for d in episodes)
        assert episodes[-1]["chain"]["total_steps"] == expected_steps
        expected_tokens = sum(d["usage"]["total_tokens"] for d in episodes)
        assert episodes[-1]["chain"]["total_tokens"] == expected_tokens

    def test_ok_first_episode_never_redispatched(self, git_repo, monkeypatch):
        """The ok-guard holds inside the chain: an ok finish ends it at episode 1."""
        from colleague.cli import main

        counter = _script_episodes(monkeypatch, ["finish"])
        rc = main(_work_argv(git_repo, "--until-done", "--no-pr"))
        assert rc == 0
        assert counter["n"] == 1
        episodes = _lineage_artifacts(git_repo)
        assert len(episodes) == 1
        assert episodes[0]["status"] == "ok"
        assert episodes[0]["chain"]["episode_index"] == 1


# ---------------------------------------------------------------------------
# Arming — flag / env / config.json precedence; unarmed byte-identical
# ---------------------------------------------------------------------------


class TestChainArming:
    def test_unarmed_run_has_no_chain_key(self, git_repo, monkeypatch):
        """Without --until-done the run is single-episode and carries no chain view."""
        from colleague.cli import main

        counter = _script_episodes(monkeypatch, ["budget"])
        rc = main(_work_argv(git_repo, "--no-pr"))
        assert rc == 2
        assert counter["n"] == 1
        episodes = _lineage_artifacts(git_repo)
        assert len(episodes) == 1
        assert "chain" not in episodes[0]

    def test_config_json_arms_the_chain(self, git_repo, monkeypatch):
        """.colleague/config.json {"until_done": true, "max_episodes": 2} arms it."""
        from colleague.cli import main

        cfg = git_repo / ".colleague" / "config.json"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(json.dumps({"until_done": True, "max_episodes": 2}))

        _script_episodes(monkeypatch, ["budget", "budget", "budget"])
        rc = main(_work_argv(git_repo, "--no-pr"))
        assert rc == 2  # cap-reached, final episode incomplete

        episodes = _lineage_artifacts(git_repo)
        assert len(episodes) == 2

    def test_flag_beats_config_for_cap(self, git_repo, monkeypatch):
        """--max-episodes (explicit flag) wins over config.json's cap."""
        from colleague.cli import main

        cfg = git_repo / ".colleague" / "config.json"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(json.dumps({"until_done": True, "max_episodes": 5}))

        _script_episodes(monkeypatch, ["budget", "budget", "budget"])
        rc = main(_work_argv(git_repo, "--max-episodes", "2", "--no-pr"))
        assert rc == 2

        episodes = _lineage_artifacts(git_repo)
        assert len(episodes) == 2

    def test_continue_combines_with_until_done(self, git_repo, monkeypatch):
        """--continue + --until-done: continue a cut run, then chain onward.

        Episode 1 is the continued task (dispatched at HEAD, exactly like an
        unchained --continue) and carries continued_from=<cut run>; the chain
        then proceeds episode-to-episode as usual.
        """
        from colleague.cli import main

        _script_episodes(monkeypatch, ["budget", "budget", "budget", "finish"])
        # Cut run: unchained, budget-exhausted.
        rc = main(_work_argv(git_repo, "--no-pr", instruction="original request"))
        assert rc == 2
        cut_id = (git_repo / ".colleague" / "last_work").read_text().strip()

        # Continue it with chaining armed; episodes 2-3 of the script plan run
        # as chain episodes 1-2, episode 4 ("finish") completes the chain.
        rc2 = main(
            [
                "work",
                "--engine",
                "mock",
                "--repo",
                str(git_repo),
                "--max-steps",
                "1",
                "--continue",
                "last",
                "--until-done",
                "--no-pr",
            ]
        )
        assert rc2 == 0

        lineage = _lineage_artifacts(git_repo)
        # The walk-back crosses the chain INTO the cut run: cut + 3 episodes.
        assert len(lineage) == 4
        assert lineage[0]["task_id"] == cut_id
        assert "chain" not in lineage[0]  # the cut run itself was unchained
        assert lineage[1]["continued_from"] == cut_id
        assert [e["chain"]["episode_index"] for e in lineage[1:]] == [1, 2, 3]
        assert lineage[-1]["status"] == "ok"


# ---------------------------------------------------------------------------
# t6 — flight continuity + episode-transition observability
# ---------------------------------------------------------------------------


def _stop_after_episode(monkeypatch, repo: Path, counter: dict, *, after: int) -> None:
    """Simulate a pilot's ``flight stop`` written in the between-episode window.

    Wraps the loop's flight reap (the last flight act of an episode) so the
    stop lands AFTER episode *after* finished — and after its live plane was
    reaped — but BEFORE the chain's boundary decision runs: exactly the moment
    a real pilot's ``colleague flight stop <id>`` would land between episodes.
    """
    import colleague.loop as loop_mod

    real_reap = loop_mod._reap_flight

    def reap_then_stop(ctx):
        real_reap(ctx)
        if counter["n"] == after:
            flight.write_stop(repo, ctx.task.id)

    monkeypatch.setattr(loop_mod, "_reap_flight", reap_then_stop)


class TestChainFlightContinuity:
    def test_between_episode_stop_prevents_next_episode(self, git_repo, monkeypatch, capsys):
        """write_stop before the boundary halts the chain: episode 2 never starts."""
        from colleague.cli import main

        counter = _script_episodes(monkeypatch, ["budget", "budget", "finish"])
        pr_calls = _gate_pr_boundary(monkeypatch)
        _stop_after_episode(monkeypatch, git_repo, counter, after=1)

        rc = main(_work_argv(git_repo, "--until-done", "--max-episodes", "5"))
        assert rc == 2  # the stopped chain reports its last episode honestly

        # Episode 2 was never dispatched — the boundary check caught the stop.
        assert counter["n"] == 1
        episodes = _lineage_artifacts(git_repo)
        assert len(episodes) == 1
        # A halted chain keeps its branches (WIP) and never hands off.
        assert pr_calls == []
        assert len(_colleague_branches(git_repo)) == 1
        # The halt names its honest reason on the progress channel.
        assert "pilot-stop" in capsys.readouterr().err
        # No transition marker was written — the chain never hopped.
        feed = flight.feed_path(git_repo, episodes[0]["task_id"])
        if feed.exists():
            markers = [
                json.loads(line)
                for line in feed.read_text().splitlines()
                if line.strip() and json.loads(line).get("type") == "episode-transition"
            ]
            assert markers == []

    def test_boundary_records_transition_marker_and_announces(self, git_repo, monkeypatch, capsys):
        """Each boundary appends an episode-transition marker to the PRIOR episode's
        feed and announces the hop on the progress sink — a pilot following
        episode 1 can locate every later episode."""
        from colleague.cli import main

        _script_episodes(monkeypatch, ["budget", "budget", "finish"])
        rc = main(_work_argv(git_repo, "--until-done", "--max-episodes", "5", "--no-pr"))
        assert rc == 0

        episodes = _lineage_artifacts(git_repo)
        assert len(episodes) == 3

        # Hop-by-hop: episode N's feed carries episode N+1's id.
        for prior, nxt, idx in (
            (episodes[0], episodes[1], 2),
            (episodes[1], episodes[2], 3),
        ):
            feed = flight.feed_path(git_repo, prior["task_id"])
            records = [json.loads(line) for line in feed.read_text().splitlines() if line.strip()]
            markers = [r for r in records if r.get("type") == "episode-transition"]
            assert len(markers) == 1
            marker = markers[0]
            assert marker["next_task_id"] == nxt["task_id"]
            assert marker["episode_index"] == idx
            assert marker["cap"] == 5

        # The FINAL episode's feed carries no marker (the chain ended there);
        # its live plane was reaped at finish and never recreated.
        assert not flight.feed_path(git_repo, episodes[-1]["task_id"]).exists()

        # The progress channel announced every hop, in the exact pilot-facing form.
        err = capsys.readouterr().err
        assert f"episode 2 of 5: continuing {episodes[0]['task_id']}" in err
        assert f"episode 3 of 5: continuing {episodes[1]['task_id']}" in err

    def test_unlimited_cap_announces_unlimited(self, git_repo, monkeypatch, capsys):
        """--max-episodes 0: the announcement and marker say 'unlimited' / cap 0."""
        from colleague.cli import main

        _script_episodes(monkeypatch, ["budget", "finish"])
        rc = main(_work_argv(git_repo, "--until-done", "--max-episodes", "0", "--no-pr"))
        assert rc == 0

        episodes = _lineage_artifacts(git_repo)
        assert len(episodes) == 2
        err = capsys.readouterr().err
        assert f"episode 2 of unlimited: continuing {episodes[0]['task_id']}" in err

        feed = flight.feed_path(git_repo, episodes[0]["task_id"])
        records = [json.loads(line) for line in feed.read_text().splitlines() if line.strip()]
        markers = [r for r in records if r.get("type") == "episode-transition"]
        assert len(markers) == 1
        assert markers[0]["cap"] == 0

    def test_no_watch_chain_ignores_stop_and_writes_no_marker(self, git_repo, monkeypatch):
        """--no-watch: the flight plane is disarmed, so the boundary neither honors
        a stop (matching the in-episode unwatched semantics) nor writes markers."""
        from colleague.cli import main

        counter = _script_episodes(monkeypatch, ["budget", "finish"])
        _stop_after_episode(monkeypatch, git_repo, counter, after=1)

        rc = main(
            _work_argv(git_repo, "--until-done", "--max-episodes", "5", "--no-pr", "--no-watch")
        )
        assert rc == 0

        # The stop was ignored — episode 2 dispatched and finished the chain.
        assert counter["n"] == 2
        episodes = _lineage_artifacts(git_repo)
        assert len(episodes) == 2
        # No transition marker recreated episode 1's feed.
        assert not flight.feed_path(git_repo, episodes[0]["task_id"]).exists()


class TestReadOnlyModeChain:
    """t12 live-dogfood catch: a read-only MODE gets read-only chain semantics."""

    def test_review_mode_chain_survives_a_no_commit_episode(self, git_repo, monkeypatch):
        """A ``--mode review --until-done`` chain does NOT halt 'no-progress'
        after a commit-less episode — the live dogfood (the arc's own review)
        halted exactly there before the fix. Read-only-mode chains bypass the
        c22 commit-evidence guard (the read-only-role treatment); the episode
        cap still bounds them, and they stay handoff-free (h21)."""
        from colleague.cli import main

        counter = _script_episodes(monkeypatch, ["idle", "finish"])
        rc = main(_work_argv(git_repo, "--mode", "review", "--until-done", "--max-episodes", "3"))
        assert rc == 0
        assert counter["n"] == 2  # continued PAST the commit-less idle episode
        episodes = _lineage_artifacts(git_repo)
        assert len(episodes) == 2
        assert episodes[-1]["status"] == "ok"

    def test_write_mode_no_progress_halt_is_unchanged(self, git_repo, monkeypatch):
        """The write-run guard still halts a commit-less chain (c22 intact)."""
        from colleague.cli import main

        counter = _script_episodes(monkeypatch, ["idle", "finish"])
        rc = main(_work_argv(git_repo, "--until-done", "--max-episodes", "3", "--no-pr"))
        assert rc == 2
        assert counter["n"] == 1  # halted at the guard, never reached the finish bait


class TestNoOpChainAndUnsafeFlightIds:
    """Qodo PR #333 inline findings: no-op chains + flight ValueError leaks."""

    def test_completed_chain_with_no_changes_skips_finalize(
        self, git_repo, monkeypatch, capsys
    ) -> None:
        """An ok-finish chain that landed zero commits mirrors handoff()'s
        no-changes semantics: no push, no PR, and an explicit diagnostic."""
        from colleague.cli import main

        pr_calls = _gate_pr_boundary(monkeypatch)
        finalizes: list = []
        real_finalize = ho.chain_handoff_finalize
        monkeypatch.setattr(
            ho,
            "chain_handoff_finalize",
            lambda *a, **k: finalizes.append(a) or real_finalize(*a, **k),
        )
        _script_episodes(monkeypatch, ["finish"])  # finishes immediately, no writes
        rc = main(_work_argv(git_repo, "--until-done"))  # PR-on is the default
        assert rc == 0
        assert pr_calls == [] and finalizes == []
        assert "no changes; no handoff performed" in capsys.readouterr().err

    def test_flight_helpers_swallow_unsafe_task_ids(self, git_repo) -> None:
        """feed_path/control_path ValueError on unsafe ids stays best-effort."""
        flight.append_episode_transition(
            git_repo, "../evil", next_task_id="n1", episode_index=2, cap=3
        )  # must not raise
        assert flight.read_stop(git_repo, "../evil") is False  # must not raise
