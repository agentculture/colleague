"""Chain driver core decisions (indefinite-run t3; decisions c21/c22/c24).

Test-first: these tests define the contract for ``colleague/chain.py`` — the
PURE decision layer the episode-chain dispatch loop (t5) consumes — plus the
two config knobs (``until_done`` / ``max_episodes``) riding ``resolve()``.

Pinned here:

- the continuable-exit ALLOW-LIST is an explicit enumeration — exactly
  ``{"budget-exhausted"}`` — never a ``status != ok`` catch-all (spec c24/h20:
  a catch-all would re-dispatch pilot-stopped and protocol-broken runs);
- one halt test per non-continuable exit: ok, pilot-stop,
  tool-protocol-broken, no-progress-zero-steps, write-no-changes,
  empty-deliverable, error;
- the no-progress guard (decision c22): no new commits AND no new artifact
  evidence = halt;
- the episode cap (decision c21): default 5 armed, 0 = unlimited;
- ``ContinuationError`` = clean halt verdict, never a crash (h5);
- knob precedence: env > config.json > default; unset = today's
  single-episode behavior byte-identical (c13/h12).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from colleague.artifact import artifact_dir, write
from colleague.chain import (
    CONTINUABLE_REASONS,
    HALT_CAP_REACHED,
    HALT_CONTINUATION_ERROR,
    HALT_NO_PROGRESS,
    HALT_NON_CONTINUABLE,
    HALT_OK_FINISH,
    ChainState,
    ChainVerdict,
    episode_progressed,
    exit_reason,
    resolve_chain_seed,
    should_continue,
)
from colleague.config import EngineConfig
from colleague.contract import ERROR, INCOMPLETE, OK, IncompletionRecord, TaskResult, WorkStats

# ---------------------------------------------------------------------------
# Result factories — each mirrors the persisted terminal facts the loop
# actually writes for that exit (see loop.py _apply_outcome_flags /
# _maybe_flag_incompletion and incompletion.py's exact reason literals).
# ---------------------------------------------------------------------------


def _stats() -> WorkStats:
    return WorkStats(
        request="implement the new feature",
        started_at="2026-01-01T00:00:00Z",
        duration_seconds=30.0,
        model_turns=5,
        step_count=10,
        tool_counts={"read_file": 3, "write_file": 2},
        files_changed=2,
        bytes_written=5000,
    )


def _ok_result(task_id: str = "task-ok") -> TaskResult:
    return TaskResult(task_id=task_id, status=OK, summary="Done.", stats=_stats())


def _budget_result(task_id: str = "task-budget") -> TaskResult:
    """A budget exit with NO deliverable: incompletion reason budget-exhausted."""
    return TaskResult(
        task_id=task_id,
        status=INCOMPLETE,
        summary="ran out of steps",
        stats=_stats(),
        not_finished=True,
        incompletion=IncompletionRecord(
            reason="budget-exhausted",
            evidence="finished outcome='budget' with 0 changed file(s) over 10 step(s)",
            recommendation="split the task or raise --max-steps",
        ),
    )


def _budget_partial_result(task_id: str = "task-budget-partial") -> TaskResult:
    """A budget exit WITH partial progress (changed files).

    The #313 soft rule suppresses the incompletion record (files changed =
    not absence), but the budget exit persists on ``not_finished`` — this is
    the headline chaining case and MUST map to the budget-exhausted reason.
    """
    return TaskResult(
        task_id=task_id,
        status=INCOMPLETE,
        summary="edited two files, then ran out of steps",
        changed_files=["src/feature.py", "tests/test_feature.py"],
        stats=_stats(),
        not_finished=True,
        incompletion=None,
    )


def _pilot_stop_result(task_id: str = "task-pilot") -> TaskResult:
    """A pilot-stopped run: cooperative flight stop, partial, record-less."""
    return TaskResult(
        task_id=task_id,
        status=INCOMPLETE,
        summary="Stopped by pilot after 3 step(s) (partial).",
        stats=_stats(),
        stopped_without_finish=True,
    )


def _reasoned_result(reason: str, task_id: str = "task-reasoned") -> TaskResult:
    return TaskResult(
        task_id=task_id,
        status=INCOMPLETE,
        summary="",
        stats=_stats(),
        stopped_without_finish=(reason == "tool-protocol-broken"),
        incompletion=IncompletionRecord(reason=reason, evidence="e", recommendation="r"),
    )


def _error_result(task_id: str = "task-error") -> TaskResult:
    return TaskResult(task_id=task_id, status=ERROR, error="backend aborted", stats=_stats())


# ---------------------------------------------------------------------------
# The allow-list is an explicit enumeration (c24/h20)
# ---------------------------------------------------------------------------


def test_allow_list_is_exactly_budget_exhausted() -> None:
    """The continuable set is enumerated — never a status!=ok catch-all."""
    assert CONTINUABLE_REASONS == frozenset({"budget-exhausted"})
    assert isinstance(CONTINUABLE_REASONS, frozenset)


def test_allow_list_uses_incompletion_reason_literals() -> None:
    """Drift guard: every allow-listed reason is a real incompletion.py reason."""
    from colleague.incompletion import _REASON_ADVICE

    assert CONTINUABLE_REASONS <= set(_REASON_ADVICE)


# ---------------------------------------------------------------------------
# exit_reason: persisted terminal facts -> canonical exit-reason string
# ---------------------------------------------------------------------------


def test_exit_reason_ok() -> None:
    assert exit_reason(_ok_result()) == "ok"


def test_exit_reason_prefers_incompletion_record() -> None:
    assert exit_reason(_budget_result()) == "budget-exhausted"
    assert exit_reason(_reasoned_result("tool-protocol-broken")) == "tool-protocol-broken"


def test_exit_reason_budget_partial_maps_to_budget_exhausted() -> None:
    """The #313 soft rule suppresses the record; the flag still names the exit."""
    assert exit_reason(_budget_partial_result()) == "budget-exhausted"


def test_exit_reason_error() -> None:
    assert exit_reason(_error_result()) == "error"


def test_exit_reason_pilot_stop_is_stopped_without_finish() -> None:
    assert exit_reason(_pilot_stop_result()) == "stopped-without-finish"


# ---------------------------------------------------------------------------
# should_continue: one test per non-continuable exit (acceptance 1)
# ---------------------------------------------------------------------------


def test_ok_finish_halts() -> None:
    """The ok-guard: an ok-status episode is never re-dispatched."""
    verdict = should_continue(_ok_result(), episode_index=1, cap=5)
    assert verdict.should_continue is False
    assert verdict.reason == HALT_OK_FINISH


def test_pilot_stop_halts() -> None:
    """A pilot's cooperative stop is a deliberate halt, never re-dispatched."""
    verdict = should_continue(_pilot_stop_result(), episode_index=1, cap=5)
    assert verdict.should_continue is False
    assert verdict.reason == HALT_NON_CONTINUABLE
    assert "stopped-without-finish" in verdict.detail


def test_tool_protocol_broken_halts() -> None:
    """A broken tool-call channel halts: re-dispatch cannot fix the parser."""
    verdict = should_continue(_reasoned_result("tool-protocol-broken"), episode_index=1, cap=5)
    assert verdict.should_continue is False
    assert verdict.reason == HALT_NON_CONTINUABLE
    assert "tool-protocol-broken" in verdict.detail


def test_no_progress_zero_steps_halts() -> None:
    """A zero-tool-call episode halts: the backend never engaged."""
    verdict = should_continue(_reasoned_result("no-progress-zero-steps"), episode_index=1, cap=5)
    assert verdict.should_continue is False
    assert verdict.reason == HALT_NON_CONTINUABLE
    assert "no-progress-zero-steps" in verdict.detail


def test_write_no_changes_halts() -> None:
    verdict = should_continue(_reasoned_result("write-no-changes"), episode_index=1, cap=5)
    assert verdict.should_continue is False
    assert verdict.reason == HALT_NON_CONTINUABLE


def test_empty_deliverable_halts() -> None:
    verdict = should_continue(_reasoned_result("empty-deliverable"), episode_index=1, cap=5)
    assert verdict.should_continue is False
    assert verdict.reason == HALT_NON_CONTINUABLE


def test_error_status_halts() -> None:
    verdict = should_continue(_error_result(), episode_index=1, cap=5)
    assert verdict.should_continue is False
    assert verdict.reason == HALT_NON_CONTINUABLE
    assert "error" in verdict.detail


# ---------------------------------------------------------------------------
# should_continue: the continuable exit
# ---------------------------------------------------------------------------


def test_budget_exhausted_continues() -> None:
    verdict = should_continue(_budget_result(), episode_index=1, cap=5)
    assert verdict.should_continue is True
    assert verdict.reason == "budget-exhausted"


def test_budget_partial_progress_continues() -> None:
    """The headline case: budget exhausted mid-task with files already changed."""
    verdict = should_continue(_budget_partial_result(), episode_index=1, cap=5)
    assert verdict.should_continue is True
    assert verdict.reason == "budget-exhausted"


# ---------------------------------------------------------------------------
# Episode cap (decision c21: default 5 armed, 0 = unlimited)
# ---------------------------------------------------------------------------


def test_cap_reached_halts() -> None:
    verdict = should_continue(_budget_result(), episode_index=5, cap=5)
    assert verdict.should_continue is False
    assert verdict.reason == HALT_CAP_REACHED


def test_below_cap_continues() -> None:
    verdict = should_continue(_budget_result(), episode_index=4, cap=5)
    assert verdict.should_continue is True


def test_cap_zero_is_unlimited() -> None:
    verdict = should_continue(_budget_result(), episode_index=500, cap=0)
    assert verdict.should_continue is True


def test_ok_finish_wins_over_cap() -> None:
    """At the cap AND finished ok: the truthful halt reason is ok-finish."""
    verdict = should_continue(_ok_result(), episode_index=5, cap=5)
    assert verdict.reason == HALT_OK_FINISH


# ---------------------------------------------------------------------------
# No-progress guard (decision c22)
# ---------------------------------------------------------------------------


def test_no_progress_halts() -> None:
    """No new commits AND no new artifact evidence = clean halt (c22)."""
    verdict = should_continue(_budget_result(), episode_index=2, cap=5, progressed=False)
    assert verdict.should_continue is False
    assert verdict.reason == HALT_NO_PROGRESS


def test_progress_continues() -> None:
    verdict = should_continue(_budget_result(), episode_index=2, cap=5, progressed=True)
    assert verdict.should_continue is True


def test_unknown_progress_continues() -> None:
    """progressed=None (first episode / no evidence yet) never triggers the guard."""
    verdict = should_continue(_budget_result(), episode_index=1, cap=5, progressed=None)
    assert verdict.should_continue is True


def test_no_progress_wins_over_cap() -> None:
    """Both no-progress and cap apply: the more specific halt reason wins."""
    verdict = should_continue(_budget_result(), episode_index=5, cap=5, progressed=False)
    assert verdict.reason == HALT_NO_PROGRESS


def test_ok_finish_wins_over_no_progress() -> None:
    """The ok-guard is checked first: an ok finish is a success, not a stall."""
    verdict = should_continue(_ok_result(), episode_index=2, cap=5, progressed=False)
    assert verdict.reason == HALT_OK_FINISH


def test_episode_progressed_new_commits() -> None:
    assert episode_progressed(new_commits=1, new_evidence=False) is True


def test_episode_progressed_new_evidence() -> None:
    assert episode_progressed(new_commits=0, new_evidence=True) is True


def test_episode_progressed_neither_is_no_progress() -> None:
    assert episode_progressed(new_commits=0, new_evidence=False) is False


# ---------------------------------------------------------------------------
# ChainState bookkeeping
# ---------------------------------------------------------------------------


def test_chain_state_records_episodes_in_order() -> None:
    state = ChainState(cap=5)
    state.record_episode("ep-1")
    state.record_episode("ep-2")
    assert state.episode_ids == ["ep-1", "ep-2"]
    assert state.episode_count == 2


def test_chain_state_new_evidence_flags_new_changed_files() -> None:
    state = ChainState(cap=5)
    assert state.record_episode("ep-1", changed_files=["a.py"]) is True
    # Same file again: nothing new — no artifact evidence.
    assert state.record_episode("ep-2", changed_files=["a.py"]) is False
    # A new file is new evidence.
    assert state.record_episode("ep-3", changed_files=["a.py", "b.py"]) is True


def test_chain_state_no_changed_files_is_not_evidence() -> None:
    state = ChainState(cap=5)
    assert state.record_episode("ep-1", changed_files=[]) is False


def test_chain_state_carries_halt_verdict() -> None:
    state = ChainState(cap=5)
    assert state.halt is None
    state.halt = ChainVerdict(should_continue=False, reason=HALT_NO_PROGRESS)
    assert state.halt.reason == HALT_NO_PROGRESS


# ---------------------------------------------------------------------------
# resolve_chain_seed: ContinuationError = clean halt, never a crash (h5)
# ---------------------------------------------------------------------------


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    (tmp_path / ".colleague").mkdir()
    return tmp_path


def test_seed_from_continuable_artifact(repo: Path) -> None:
    result = _budget_partial_result("task-cont")
    write(result, artifact_dir(repo))
    resolved, halt = resolve_chain_seed(repo, "task-cont")
    assert halt is None
    assert resolved is not None
    task_id, seed = resolved
    assert task_id == "task-cont"
    assert "implement the new feature" in seed  # original request rides the seed


def test_seed_from_ok_artifact_is_clean_halt(repo: Path) -> None:
    """The ok-guard holds inside the chain: never re-dispatched, never a crash."""
    write(_ok_result("task-done"), artifact_dir(repo))
    resolved, halt = resolve_chain_seed(repo, "task-done")
    assert resolved is None
    assert halt is not None
    assert halt.should_continue is False
    assert halt.reason == HALT_CONTINUATION_ERROR
    assert "finished ok" in halt.detail


def test_seed_from_missing_artifact_is_clean_halt(repo: Path) -> None:
    resolved, halt = resolve_chain_seed(repo, "task-nope")
    assert resolved is None
    assert halt is not None
    assert halt.reason == HALT_CONTINUATION_ERROR


def test_seed_from_corrupt_artifact_is_clean_halt(repo: Path) -> None:
    (artifact_dir(repo) / "task-corrupt.json").write_text("{not json", encoding="utf-8")
    resolved, halt = resolve_chain_seed(repo, "task-corrupt")
    assert resolved is None
    assert halt is not None
    assert halt.reason == HALT_CONTINUATION_ERROR


# ---------------------------------------------------------------------------
# Config knobs (decision c21; c13/h12: env > config.json > default)
# ---------------------------------------------------------------------------


def _write_config(repo: Path, payload: dict) -> None:
    cfg_dir = repo / ".colleague"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.json").write_text(json.dumps(payload), encoding="utf-8")


def test_knobs_default_dormant() -> None:
    """Unset = today's single-episode behavior: unarmed, cap at the armed default."""
    cfg = EngineConfig.resolve()
    assert cfg.until_done is False
    assert cfg.max_episodes == 5


def test_env_arms_until_done(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_UNTIL_DONE", "1")
    assert EngineConfig.resolve().until_done is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off"])
def test_env_falsey_leaves_until_done_dormant(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("COLLEAGUE_UNTIL_DONE", value)
    assert EngineConfig.resolve().until_done is False


def test_convertible_until_done_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONVERTIBLE_UNTIL_DONE", "1")
    assert EngineConfig.resolve().until_done is True


def test_env_max_episodes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_MAX_EPISODES", "9")
    assert EngineConfig.resolve().max_episodes == 9


def test_env_max_episodes_zero_unlimited(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_MAX_EPISODES", "0")
    assert EngineConfig.resolve().max_episodes == 0


def test_env_max_episodes_garbage_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_MAX_EPISODES", "many")
    assert EngineConfig.resolve().max_episodes == 5


def test_convertible_max_episodes_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONVERTIBLE_MAX_EPISODES", "7")
    assert EngineConfig.resolve().max_episodes == 7


def test_config_file_knobs(tmp_path: Path) -> None:
    _write_config(tmp_path, {"until_done": True, "max_episodes": 3})
    cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.until_done is True
    assert cfg.max_episodes == 3


def test_env_beats_config_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_config(tmp_path, {"until_done": True, "max_episodes": 3})
    monkeypatch.setenv("COLLEAGUE_UNTIL_DONE", "0")
    monkeypatch.setenv("COLLEAGUE_MAX_EPISODES", "8")
    cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.until_done is False
    assert cfg.max_episodes == 8


def test_knobs_absent_from_config_snapshot() -> None:
    """The artifact config snapshot must not grow keys: a dormant run's artifact
    stays byte-identical (h1; the ``watch`` knob precedent — behavior, not new
    snapshot surface). t5/t7 may revisit when the chain view lands."""
    d = EngineConfig.resolve().to_dict()
    assert "until_done" not in d
    assert "max_episodes" not in d


# ---------------------------------------------------------------------------
# Boundary: chain.py is a pure decision layer
# ---------------------------------------------------------------------------


def test_chain_module_is_pure_stdlib() -> None:
    """chain.py never imports loop internals, subprocess, threads, or sockets."""
    import ast

    source = (Path(__file__).parent.parent / "colleague" / "chain.py").read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    forbidden = {"colleague.loop", "subprocess", "socket", "threading", "concurrent"}
    hits = {
        name
        for name in imported
        if name in forbidden or any(name.startswith(f"{f}.") for f in forbidden)
    }
    assert not hits, f"chain.py must not import {sorted(hits)}"
