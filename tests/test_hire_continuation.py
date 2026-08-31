"""Plan t14 (delegation-follow-ups-a7-p3-hire, covers c38/h22): hires are
dead at the cut (decision D43).

Acceptance criterion 2 under test: ``work --continue`` and an ``--until-done``
episode load the prior artifact's hires with ``status=expired`` (the seed
names them and their death readably); ``assign_to_colleague`` on an expired id
returns ``no live hire``; hires are never rehydrated as live — a continued
run's fresh executor holds NO roster entry for a prior hire, and its result
carries no ``hires`` block it did not earn.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from colleague import chain as chain_mod
from colleague.agents.state.ledger import TaskLedger, ledger_path
from colleague.artifact import artifact_dir, write
from colleague.config import EngineConfig
from colleague.continuation import resolve_continuation
from colleague.contract import OK, Task, TaskResult, WorkStats
from colleague.engines.mock import MockEngine
from colleague.hire import mint_hire
from colleague.tools import ToolExecutor

TASK_ID = "task-hire-1"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / ".colleague").mkdir()
    return tmp_path


def _stats() -> WorkStats:
    return WorkStats(
        request="build the widget",
        started_at="2026-01-01T00:00:00Z",
        duration_seconds=30.0,
        model_turns=5,
        step_count=10,
        tool_counts={"read_file": 3},
        files_changed=1,
        bytes_written=100,
    )


def _hire_entry(**overrides: Any) -> dict[str, Any]:
    kwargs = dict(
        agent_id="hire-1",
        hirer_id="cortex",
        base_role="scout",
        purpose="survey the tests",
        when="whenever a multi-file survey is needed",
        prompt_fragment="You are a hired scout with a standing brief.",
        task_id=TASK_ID,
        created_step=3,
    )
    kwargs.update(overrides)
    entry = mint_hire(**kwargs).to_dict()
    entry["assignments"] = []
    return entry


def _result(hires: list[dict[str, Any]], status: str = "incomplete") -> TaskResult:
    return TaskResult(
        task_id=TASK_ID,
        status=status,
        summary="ran out of steps mid-widget",
        error="step budget exhausted",
        stats=_stats(),
        hires=hires,
    )


def _seed(repo: Path, result: TaskResult) -> Path:
    return write(result, artifact_dir(repo))


# ---------------------------------------------------------------------------
# The continuation seed marks prior hires expired (D43)
# ---------------------------------------------------------------------------


def test_continue_seed_loads_prior_hires_as_expired(repo: Path) -> None:
    _seed(repo, _result([_hire_entry(), _hire_entry(agent_id="hire-2", base_role="writer")]))
    task_id, seed = resolve_continuation(repo, TASK_ID)
    assert task_id == TASK_ID
    assert "Prior hires" in seed
    assert "expired" in seed
    assert "hire-1" in seed
    assert "hire-2" in seed
    # The seed states the runtime contract verbatim so the model expects it.
    assert "no live hire" in seed
    # Never presented as live.
    assert "status: live" not in seed


def test_seed_without_hires_carries_no_section(repo: Path) -> None:
    """A hire-less prior artifact seeds byte-identically to the pre-t14 text."""
    _seed(repo, _result([]))
    _, seed = resolve_continuation(repo, TASK_ID)
    assert "Prior hires" not in seed
    assert "no live hire" not in seed


def test_chain_seed_loads_prior_hires_as_expired(repo: Path) -> None:
    """The --until-done episode path (resolve_chain_seed wraps the same seam)."""
    _seed(repo, _result([_hire_entry()]))
    resolved, halt = chain_mod.resolve_chain_seed(repo, TASK_ID)
    assert halt is None
    task_id, seed = resolved
    assert task_id == TASK_ID
    assert "Prior hires" in seed
    assert "expired" in seed
    assert "hire-1" in seed


def test_ledger_seed_path_also_marks_hires_expired(repo: Path) -> None:
    """Armed agents mode (the t17 ledger-seed body) keeps the expired section."""
    _seed(repo, _result([_hire_entry()]))
    led = TaskLedger(ledger_path(repo, TASK_ID))
    led.append("operator_request", {"text": "build the widget"})
    _, seed = resolve_continuation(repo, TASK_ID, agents_armed=True)
    assert "## Original request (verbatim)" in seed  # the ledger body ran
    assert "Prior hires" in seed
    assert "expired" in seed


def test_malformed_hire_entries_never_crash_the_seed(repo: Path) -> None:
    """A corrupt hires list on disk (a non-dict entry) is skipped, never a
    crash — the ``TaskResult.from_dict`` tolerance carried through the seed."""
    import json

    path = _seed(repo, _result([_hire_entry()]))
    data = json.loads(path.read_text(encoding="utf-8"))
    data["hires"].append("not-a-dict")
    path.write_text(json.dumps(data), encoding="utf-8")
    _, seed = resolve_continuation(repo, TASK_ID)
    assert "hire-1" in seed
    assert "Prior hires" in seed


# ---------------------------------------------------------------------------
# End-to-end: the continued run never rehydrates a hire as live
# ---------------------------------------------------------------------------


def test_continued_mock_run_never_rehydrates_hires(repo: Path) -> None:
    """Drive the mock engine (the contract reference) with a work
    --continue-shaped seed: the continued run earns NO hires block of its own
    — the prior hires exist only as the seed's expired section."""
    _seed(repo, _result([_hire_entry()]))
    _, seed = resolve_continuation(repo, TASK_ID)

    result = MockEngine().work(Task.new(str(repo), seed, engine="mock"), EngineConfig.resolve())
    assert result.status == OK
    assert result.hires == []
    assert "hires" not in result.to_dict()


def test_assign_on_an_expired_id_returns_no_live_hire(repo: Path) -> None:
    """The runtime half of D43: a continued run's executor (fresh, loop-shaped
    — no roster rehydration) refuses the prior id readably, spawning nothing."""
    _seed(repo, _result([_hire_entry()]))
    resolve_continuation(repo, TASK_ID)  # the seed marks them expired

    calls: list[Any] = []

    def _spawn(*a: Any, **k: Any):  # pragma: no cover - must never fire
        calls.append((a, k))
        raise AssertionError("an expired hire must never spawn")

    ex = ToolExecutor(repo, spawn=_spawn)
    outcome = ex.execute("assign_to_colleague", {"agent_id": "hire-1", "task": "t"})
    assert outcome.result == "no live hire: hire-1"
    assert calls == []
