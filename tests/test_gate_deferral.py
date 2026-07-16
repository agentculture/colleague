"""Gate-skip guard + final-episode union gate set (issue #335 t6 — c8/h8, c10/h10, c23/h18).

A chain episode whose exit is continuation-shaped (budget-exhausted, or a
declared fill-line finish-with-handoff) defers the four pre-finish gates
(lint / coherence / test-integrity / affected-tests) to the chain's FINAL
episode: mid-chain gates would burn per-episode budget grading intermediate
trees the next episode immediately rewrites. The skip is recorded ONCE per
episode on ``result.capacity_warning`` (the ``_record_fillline_cap``
precedent) — never silent. On the final (finish-shaped) episode the gates run
over the UNION of that episode's changed files and the chain's accumulated
``prior_changed``, filtered to paths existing in the episode worktree.

Three levels, mirroring the sibling gate tests:

- predicate matrix — the guard fires exactly on
  ``chain_episode AND (outcome == budget OR declared finish-with-handoff)``
  and never otherwise (criterion 1), pinned against
  :func:`colleague.chain.should_continue` across the five exit shapes
  (criterion 2 — the guard IMPORTS ``declared_capacity_handoff`` from
  chain.py, so the equivalence is structural AND tested);
- ``run()`` integration — the tests/test_loop_lint_gate.py scripted-complete
  harness, gates observed at their module seams;
- chained mock e2e — the tests/test_chain_e2e.py in-process dispatch pattern
  (criterion 3): mid-episode artifacts carry NO gate reports but DO carry the
  deferral note; the final episode's artifact carries all four reports, run
  over the union changed-set (criterion 4).
"""

from __future__ import annotations

import builtins
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from colleague import chain
from colleague import loop as loop_mod
from colleague.affectedtests import AffectedTestsReport
from colleague.artifact import find_artifact
from colleague.contract import (
    ERROR,
    INCOMPLETE,
    OK,
    CapacityDecision,
    CoherenceReport,
    LintReport,
    Task,
    TaskResult,
)
from colleague.loop import ContextControls, ModelResponse, ToolCall, run
from colleague.testintegrity import MirrorFinding, TestIntegrityReport

# The stable substring every deferral-note assertion keys on.
_NOTE = "deferred to the chain's final episode (#335)"

# The four artifact keys the deferred gates would have written.
_REPORT_KEYS = (
    "lint_report",
    "coherence_report",
    "test_integrity_report",
    "affected_tests_report",
)


# ---------------------------------------------------------------------------
# Harness — scripted complete (the tests/test_loop_lint_gate.py idiom)
# ---------------------------------------------------------------------------


def scripted(responses: list[ModelResponse]):
    state = {"i": 0}

    def complete(_messages: list[dict]) -> ModelResponse:
        i = min(state["i"], len(responses) - 1)
        state["i"] += 1
        return responses[i]

    return complete


def _write(path: str) -> ModelResponse:
    return ModelResponse(
        tool_calls=[ToolCall("w", "write_file", {"path": path, "content": "work\n"})]
    )


def _finish(summary: str = "done") -> ModelResponse:
    return ModelResponse(tool_calls=[ToolCall("f", "finish", {"summary": summary})])


def _arm_gate_recorders(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[list[str]]]:
    """Stub the four gates at their module seams; return the changed-set call log.

    Each stub records the changed-set it was handed and returns a minimal
    non-None report (with a finding, for test-integrity — the loop records that
    report only when findings exist), so a gate that RUNS provably lands its
    report key on the artifact. The loop calls these through its module
    aliases (``_lint`` etc. are the module objects), so patching the source
    modules is visible to the loop.
    """
    calls: dict[str, list[list[str]]] = {
        "lint": [],
        "coherence": [],
        "integrity": [],
        "affected": [],
    }

    def fake_lint(repo, changed):
        calls["lint"].append(list(changed))
        return LintReport(fixed=["stub: reformatted"])

    def fake_coherence(repo, changed, env_overrides=None):
        calls["coherence"].append(list(changed))
        return CoherenceReport(status="scored", files=[{"path": "stub.md"}])

    def fake_mirror(repo, changed):
        calls["integrity"].append(list(changed))
        return TestIntegrityReport(
            findings=[
                MirrorFinding(symbol="s", kind="attribute", test_file="t.py", impl_file="i.py")
            ]
        )

    def fake_affected(repo, changed, **kwargs):
        calls["affected"].append(list(changed))
        return AffectedTestsReport(
            status="passed", selected=["tests/test_stub.py"], total=1, passed=1
        )

    monkeypatch.setattr("colleague.lint.run_lint_gate", fake_lint)
    monkeypatch.setattr("colleague.coherence.run_coherence_gate", fake_coherence)
    monkeypatch.setattr("colleague.testintegrity.detect_mirror", fake_mirror)
    monkeypatch.setattr("colleague.affectedtests.run_affected_tests", fake_affected)
    return calls


def _gate_calls(calls: dict[str, list[list[str]]]) -> int:
    return sum(len(v) for v in calls.values())


def _controls(**kwargs) -> ContextControls:
    """All four gates armed (lint/coherence explicit; integrity defaults on)."""
    kwargs.setdefault("lint", True)
    kwargs.setdefault("coherence", True)
    kwargs.setdefault("affectedtests", True)
    return ContextControls(**kwargs)


# ---------------------------------------------------------------------------
# Criterion 1 — the guard predicate fires exactly on
# (chain-episode AND (budget outcome OR declared finish-with-handoff))
# ---------------------------------------------------------------------------


def _predicate_ctx(chain_episode: bool, handoff: bool) -> SimpleNamespace:
    result = TaskResult(task_id="t", status=OK)
    if handoff:
        result.capacity_decision = CapacityDecision(kind="finish-with-handoff", reason="fill line")
    return SimpleNamespace(chain_episode=chain_episode, result=result)


_ALL_OUTCOMES = (
    loop_mod._EXIT_FINISHED,
    loop_mod._EXIT_STOPPED,
    loop_mod._EXIT_BUDGET,
    loop_mod._EXIT_PILOT_STOP,
    loop_mod._EXIT_TOOL_PROTOCOL,
)


@pytest.mark.parametrize("outcome", _ALL_OUTCOMES)
@pytest.mark.parametrize("chain_episode", (True, False))
@pytest.mark.parametrize("handoff", (True, False))
def test_gate_skip_predicate_matrix(outcome: str, chain_episode: bool, handoff: bool) -> None:
    """Skip fires exactly on (chain-episode AND (budget OR declared handoff))."""
    ctx = _predicate_ctx(chain_episode, handoff)
    expected = chain_episode and (outcome == loop_mod._EXIT_BUDGET or handoff)
    assert loop_mod._gates_deferred_to_chain(ctx, outcome, None) is expected


def test_gate_skip_never_fires_on_aborted() -> None:
    """An aborted run is an error halt (chain never continues it): no skip, no
    note — even though run()'s ``outcome`` still holds its ``budget`` initial
    value on the aborted path (the trap the guard's aborted arm exists for)."""
    ctx = _predicate_ctx(chain_episode=True, handoff=True)
    aborted = RuntimeError("engine failure")
    assert loop_mod._gates_deferred_to_chain(ctx, loop_mod._EXIT_BUDGET, aborted) is False


def test_gate_skip_ignores_non_handoff_capacity_decision() -> None:
    """A declared compact/split move is not a continuation exit — no skip."""
    result = TaskResult(task_id="t", status=OK)
    result.capacity_decision = CapacityDecision(kind="compact", reason="fill line")
    ctx = SimpleNamespace(chain_episode=True, result=result)
    assert loop_mod._gates_deferred_to_chain(ctx, loop_mod._EXIT_FINISHED, None) is False


# ---------------------------------------------------------------------------
# Criterion 2 — loop-skip <=> chain-would-continue (chain.py is the ground
# truth: the guard imports declared_capacity_handoff; this pins the whole
# predicate against chain.should_continue across the five exit shapes)
# ---------------------------------------------------------------------------

_EXIT_SHAPES = (
    # (label, loop outcome at gate time, aborted, result-as-persisted)
    ("ok-finish", loop_mod._EXIT_FINISHED, None, dict(status=OK)),
    ("budget", loop_mod._EXIT_BUDGET, None, dict(status=INCOMPLETE, not_finished=True)),
    (
        "capacity-handoff",
        loop_mod._EXIT_FINISHED,
        None,
        dict(
            status=INCOMPLETE,
            capacity_decision=CapacityDecision(kind="finish-with-handoff", reason="fill line"),
        ),
    ),
    # On the aborted path run()'s ``outcome`` keeps its pre-try initial value
    # (``budget``) — the persisted facts are status=ERROR either way.
    ("timeout", loop_mod._EXIT_BUDGET, TimeoutError("per-request timeout"), dict(status=ERROR)),
    ("error", loop_mod._EXIT_BUDGET, RuntimeError("boom"), dict(status=ERROR)),
)


@pytest.mark.parametrize("label,outcome,aborted,fields", _EXIT_SHAPES)
def test_loop_skip_equivalent_to_chain_continue(label, outcome, aborted, fields) -> None:
    """The gate skip fires exactly when the chain would dispatch another episode
    (cap unlimited, no progress evidence — only the exit SHAPE is in play)."""
    result = TaskResult(task_id="e1", **fields)
    ctx = SimpleNamespace(chain_episode=True, result=result)
    loop_skip = loop_mod._gates_deferred_to_chain(ctx, outcome, aborted)
    verdict = chain.should_continue(result, 1, 0)
    assert loop_skip == verdict.should_continue, (
        f"{label}: loop-skip {loop_skip} diverged from chain verdict "
        f"{verdict.should_continue} ({verdict.reason})"
    )


# ---------------------------------------------------------------------------
# Criterion 4 — the union changed-set helper
# ---------------------------------------------------------------------------


def _union_ctx(tmp_path: Path, changed: set[str], prior: tuple[str, ...]) -> SimpleNamespace:
    return SimpleNamespace(
        executor=SimpleNamespace(changed=changed),
        chain_prior_changed=prior,
        task=SimpleNamespace(repo_path=str(tmp_path)),
        # The dropped-path recorder's surface (#342): the once-cell, the result
        # the note lands on, and the observability attrs _emit_phase reads.
        result=TaskResult(task_id="t", status=OK),
        _gate_drop_noted=[],
        flight=None,
        progress=None,
    )


def test_gate_changed_set_unions_and_filters_to_existing(tmp_path: Path) -> None:
    """union(this episode's changed, prior_changed), filtered to existing paths."""
    (tmp_path / "m.py").write_text("x = 1\n")
    (tmp_path / "prior.txt").write_text("carried\n")
    ctx = _union_ctx(tmp_path, {"m.py"}, ("prior.txt", "ghost.txt"))
    assert loop_mod._gate_changed_set(ctx) == ["m.py", "prior.txt"]


def test_gate_changed_set_empty_prior_is_byte_identical(tmp_path: Path) -> None:
    """No prior_changed == today's behavior exactly: no existence filter, so a
    changed-then-deleted path still reaches the gate as before."""
    ctx = _union_ctx(tmp_path, {"gone.py", "m.py"}, ())
    assert loop_mod._gate_changed_set(ctx) == ["gone.py", "m.py"]


# ---------------------------------------------------------------------------
# #342(1) — union paths the existence filter removed are recorded, ONCE
# ---------------------------------------------------------------------------

_DROP_NOTE = "no longer exist and were not graded"


def test_gate_changed_set_records_dropped_paths_once(tmp_path: Path) -> None:
    """The existence filter's removals land ONE note on capacity_warning even
    though all four gates call _gate_changed_set (up to twice each)."""
    (tmp_path / "m.py").write_text("x = 1\n")
    ctx = _union_ctx(tmp_path, {"m.py"}, ("ghost.txt", "gone.py"))
    for _ in range(8):
        assert loop_mod._gate_changed_set(ctx) == ["m.py"]
    warning = ctx.result.capacity_warning
    assert warning is not None
    assert warning.count(_DROP_NOTE) == 1
    assert "2 prior-episode path(s)" in warning
    assert "ghost.txt" in warning and "gone.py" in warning


def test_gate_changed_set_nothing_dropped_no_note(tmp_path: Path) -> None:
    """Every union path exists → no note, capacity_warning untouched (byte-identical)."""
    (tmp_path / "m.py").write_text("x = 1\n")
    (tmp_path / "prior.txt").write_text("carried\n")
    ctx = _union_ctx(tmp_path, {"m.py"}, ("prior.txt",))
    assert loop_mod._gate_changed_set(ctx) == ["m.py", "prior.txt"]
    assert ctx.result.capacity_warning is None


def test_gate_changed_set_drop_note_appends_to_existing_warning(tmp_path: Path) -> None:
    """An earlier note (e.g. the fill-line cap) is appended to, never replaced."""
    (tmp_path / "m.py").write_text("x = 1\n")
    ctx = _union_ctx(tmp_path, {"m.py"}, ("ghost.txt",))
    ctx.result.capacity_warning = "earlier note"
    loop_mod._gate_changed_set(ctx)
    assert ctx.result.capacity_warning.startswith("earlier note; ")
    assert _DROP_NOTE in ctx.result.capacity_warning


def test_final_episode_drop_note_on_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """run()-level (the deleted-prior-file shape): a finish-shaped chain episode
    whose prior_changed names a path a later episode deleted records the
    dropped path on the final artifact's capacity_warning."""
    _arm_gate_recorders(monkeypatch)
    (tmp_path / "prior.txt").write_text("carried from episode 1\n")
    result = run(
        scripted([_finish("wrap up")]),
        Task.new(str(tmp_path), "wrap up"),
        max_steps=5,
        context=_controls(chain_episode=True, chain_prior_changed=("prior.txt", "deleted.py")),
    )
    assert result.status == OK
    assert result.capacity_warning is not None
    assert result.capacity_warning.count(_DROP_NOTE) == 1
    assert "1 prior-episode path(s)" in result.capacity_warning
    assert "deleted.py" in result.capacity_warning


# ---------------------------------------------------------------------------
# #341 — the deferral stamps the STRUCTURED marker, not just the note
# ---------------------------------------------------------------------------


def test_gate_deferral_stamps_structured_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A deferring chain episode carries gates_deferred=True on the result and
    the artifact key — consumers never string-match capacity_warning."""
    _arm_gate_recorders(monkeypatch)
    result = run(
        scripted([_write("m.py")]),
        Task.new(str(tmp_path), "keep working"),
        max_steps=1,
        context=_controls(chain_episode=True),
    )
    assert result.gates_deferred is True
    assert result.to_dict()["gates_deferred"] is True


def test_gated_episode_has_no_structured_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A clean-finish (gated) episode stays unmarked — key absent, byte-identical."""
    _arm_gate_recorders(monkeypatch)
    result = run(
        scripted([_write("m.py"), _finish()]),
        Task.new(str(tmp_path), "finish the work"),
        max_steps=5,
        context=_controls(chain_episode=True),
    )
    assert result.gates_deferred is False
    assert "gates_deferred" not in result.to_dict()


# ---------------------------------------------------------------------------
# run() integration — skip + note on continuation-shaped chain-episode exits;
# gates (over the union) on everything else
# ---------------------------------------------------------------------------


def test_chain_episode_budget_exit_skips_gates_and_notes_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A chain episode exiting on budget runs NO gate and records ONE deferral
    note on capacity_warning; no gate report key reaches the artifact."""
    calls = _arm_gate_recorders(monkeypatch)
    result = run(
        scripted([_write("m.py")]),
        Task.new(str(tmp_path), "keep working"),
        max_steps=1,
        context=_controls(chain_episode=True),
    )
    assert _gate_calls(calls) == 0
    assert result.capacity_warning is not None
    assert _NOTE in result.capacity_warning
    assert result.capacity_warning.count(_NOTE) == 1
    for key in _REPORT_KEYS:
        assert key not in result.to_dict()


def test_chain_episode_clean_finish_runs_gates_no_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The final (finish-shaped) episode runs all four gates — no deferral note."""
    calls = _arm_gate_recorders(monkeypatch)
    result = run(
        scripted([_write("m.py"), _finish()]),
        Task.new(str(tmp_path), "finish the work"),
        max_steps=5,
        context=_controls(chain_episode=True),
    )
    assert result.status == OK
    assert [len(v) for v in calls.values()] == [1, 1, 1, 1]
    assert "capacity_warning" not in result.to_dict()
    for key in _REPORT_KEYS:
        assert key in result.to_dict()


def test_non_chain_budget_exit_still_runs_gates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """chain_episode=False (a plain run): a budget exit gates as today, no note."""
    calls = _arm_gate_recorders(monkeypatch)
    result = run(
        scripted([_write("m.py")]),
        Task.new(str(tmp_path), "keep working"),
        max_steps=1,
        context=_controls(),
    )
    assert [len(v) for v in calls.values()] == [1, 1, 1, 1]
    assert "capacity_warning" not in result.to_dict()


def test_subagent_shaped_until_done_run_gates_on_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An until_done-armed run WITHOUT a chain dispatch (chain_armed=True but
    chain_episode=False — the subagent-child / plain-armed shape, c22) still
    runs its gates on a budget exit: the marker is dispatch-keyed, never
    derived from until_done."""
    calls = _arm_gate_recorders(monkeypatch)
    result = run(
        scripted([_write("m.py")]),
        Task.new(str(tmp_path), "keep working"),
        max_steps=1,
        context=_controls(chain_armed=True, chain_episode=False),
    )
    assert [len(v) for v in calls.values()] == [1, 1, 1, 1]
    assert "capacity_warning" not in result.to_dict()


def test_chain_episode_declared_handoff_skips_gates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A REAL declared fill-line finish-with-handoff (the d1 continuation shape,
    driven through the fill-line offer, not a stamped field) skips the gates and
    records the note — even though the loop outcome is a finish."""
    calls = _arm_gate_recorders(monkeypatch)

    def complete(messages):
        last = str(messages[-1].get("content") or "")
        if "declare ONE move" in last:
            # The declaring turn calls finish → classified finish-with-handoff.
            return ModelResponse(
                content="handing off",
                tool_calls=[ToolCall("f", "finish", {"summary": "continuation summary"})],
                prompt_tokens=90,
                completion_tokens=1,
            )
        # First working turn crosses the fill line (90 >= 0.8 * 100).
        return ModelResponse(
            content="",
            tool_calls=[ToolCall("w", "write_file", {"path": "m.py", "content": "x\n"})],
            prompt_tokens=90,
            completion_tokens=1,
        )

    result = run(
        complete,
        Task.new(str(tmp_path), "a long thing"),
        max_steps=10,
        context=_controls(budget=100, fillline_threshold=0.8, chain_episode=True),
    )
    assert result.capacity_decision is not None
    assert result.capacity_decision.kind == "finish-with-handoff"
    assert _gate_calls(calls) == 0
    assert result.capacity_warning is not None
    assert result.capacity_warning.count(_NOTE) == 1


def test_final_episode_gates_operate_over_union(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Criterion 4 at the run() level: the finish-shaped episode's gates see
    union(this episode's changed, prior_changed) filtered to existing paths —
    including a final episode that changed NOTHING itself (prior work alone
    must still be graded; today's empty-changed early-return would skip it)."""
    calls = _arm_gate_recorders(monkeypatch)
    (tmp_path / "prior.txt").write_text("carried from episode 1\n")
    result = run(
        scripted([_finish("nothing left to change")]),
        Task.new(str(tmp_path), "wrap up"),
        max_steps=5,
        context=_controls(chain_episode=True, chain_prior_changed=("prior.txt", "ghost.txt")),
    )
    assert result.status == OK
    for log in calls.values():
        assert log == [["prior.txt"]]  # ghost.txt filtered (not in the worktree)


# ---------------------------------------------------------------------------
# Criterion 3 — chained mock e2e (the tests/test_chain_e2e.py dispatch pattern)
# ---------------------------------------------------------------------------


def _run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, check=True)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git(repo, "init", "-q")
    _run_git(repo, "config", "user.email", "test@example.com")
    _run_git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("hello\n")
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-q", "-m", "init")
    return repo


def _script_episodes(monkeypatch: pytest.MonkeyPatch, plan: list[str]) -> None:
    """One plan entry per episode: 'budget' writes episode-N.txt and never
    finishes; 'finish' finishes without changing anything (so the final
    episode's own changed-set is empty — the union must carry the gates)."""
    counter = {"n": 0}

    def fake_script(task):
        counter["n"] += 1
        kind = plan[min(counter["n"], len(plan)) - 1]
        n = counter["n"]

        def complete(_messages):
            if kind == "budget":
                return ModelResponse(
                    content=f"episode {n} still working",
                    tool_calls=[
                        ToolCall(
                            f"e{n}",
                            "write_file",
                            {"path": f"episode-{n}.txt", "content": f"episode {n} work\n"},
                        )
                    ],
                    prompt_tokens=1,
                    completion_tokens=1,
                )
            return ModelResponse(
                content="done",
                tool_calls=[ToolCall("fin", "finish", {"summary": "chain complete"})],
                prompt_tokens=1,
                completion_tokens=1,
            )

        return complete

    monkeypatch.setattr("colleague.engines.mock._script", fake_script)


def _lineage_artifacts(repo: Path) -> list[dict]:
    last = (repo / ".colleague" / "last_work").read_text().strip()
    episodes: list[dict] = []
    task_id: str | None = last
    while task_id:
        path = find_artifact(repo, task_id)
        assert path is not None, f"artifact missing for {task_id}"
        data = json.loads(path.read_text())
        episodes.append(data)
        task_id = data.get("continued_from")
    episodes.reverse()
    return episodes


def _no_intervention(*_args, **_kwargs) -> str:
    raise AssertionError("operator intervention requested — the chain must run unattended")


def test_chained_e2e_mid_episode_defers_gates_final_episode_reports(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 2-episode --until-done chain on the mock engine: the mid (budget-exit)
    episode's artifact carries NO lint/coherence/test-integrity/affected-tests
    report but DOES carry the ONE deferral note; the final episode's artifact
    carries all four reports, produced over the union changed-set (the final
    episode changed nothing itself — episode 1's file alone reached the gates,
    proving both the deferral hand-off and the c23 union, criteria 3+4)."""
    from colleague.cli import main

    _script_episodes(monkeypatch, ["budget", "finish"])
    calls = _arm_gate_recorders(monkeypatch)
    monkeypatch.setattr(builtins, "input", _no_intervention)

    rc = main(
        [
            "work",
            "--engine",
            "mock",
            "--repo",
            str(git_repo),
            "--max-steps",
            "1",
            "--until-done",
            "--no-pr",
            "chain the work",
        ]
    )
    assert rc == 0

    episodes = _lineage_artifacts(git_repo)
    assert len(episodes) == 2
    mid, final = episodes

    # Mid-episode: NO gate report keys, ONE deferral note on capacity_warning.
    for key in _REPORT_KEYS:
        assert key not in mid, f"mid-chain episode leaked {key!r} — its gates must be deferred"
    assert _NOTE in mid.get("capacity_warning", "")
    assert mid["capacity_warning"].count(_NOTE) == 1

    # Final episode: all four reports, and no deferral note of its own.
    for key in _REPORT_KEYS:
        assert key in final, f"final episode must carry {key!r}"
    assert _NOTE not in final.get("capacity_warning", "")

    # The gates ran EXACTLY once each (the final episode), over the union:
    # the final episode wrote nothing, so episode 1's file alone got graded —
    # present in the final worktree via the chain's tree carry.
    for name, log in calls.items():
        assert log == [["episode-1.txt"]], f"{name} gate saw {log}"
