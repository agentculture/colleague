"""Tests for child budget scaling + the read-only merge-slot skip (plan t12 / spec R5).

A batch child no longer inherits the parent's FULL context/step budget when
children run concurrently: at effective width W > 1 each child resolves a
clamped share (parent // W, floored, never above the parent), so a fan-out of
3 cannot schedule 3x the parent's context appetite against one served model.
Width 1 stays byte-identical (h5). An explicit per-item override wins.

A batch whose children are ALL read-only roles cannot write, so its merge
child is structurally a no-op — such a batch stops reserving the merge slot
(items cap and width may use the full MAX_SUBAGENT_FANOUT).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import List

import pytest

from colleague.config import MAX_SUBAGENT_FANOUT, EngineConfig
from colleague.contract import OK, SubResult, Usage
from colleague.subagents import (
    _MIN_CHILD_CONTEXT_BUDGET,
    _MIN_CHILD_MAX_STEPS,
    ChildSpec,
    _child_budget_share,
    _resolve_batch_width,
    run_subagent,
)
from colleague.tools import ToolError, ToolExecutor, ToolOutcome


def _fake_taskresult():
    return SimpleNamespace(task_id="t", status=OK, summary="ok", changed_files=[], usage=Usage())


class _RecorderEngine:
    def __init__(self, recorder: list) -> None:
        self.recorder = recorder

    def work(self, task, config):
        self.recorder.append(config)
        return _fake_taskresult()


@pytest.fixture
def recorded_configs(monkeypatch) -> list:
    recorder: list = []
    monkeypatch.setattr(
        "colleague.subagents.registry.load",
        lambda name: _RecorderEngine(recorder),
    )
    return recorder


# ---------------------------------------------------------------------------
# _child_budget_share — the scaling rule
# ---------------------------------------------------------------------------


def test_child_budget_share_width_one_is_none():
    config = EngineConfig()
    assert _child_budget_share(config, 1) == (None, None)
    assert _child_budget_share(config, 0) == (None, None)


def test_child_budget_share_scales_with_width():
    config = EngineConfig()
    steps, budget = _child_budget_share(config, 3)
    assert steps == max(_MIN_CHILD_MAX_STEPS, config.max_steps // 3)
    assert budget == max(_MIN_CHILD_CONTEXT_BUDGET, config.context_budget_tokens // 3)


def test_child_budget_share_floor_never_exceeds_parent():
    config = EngineConfig(max_steps=8, context_budget_tokens=9000)
    steps, budget = _child_budget_share(config, 2)
    assert steps == 8
    assert budget == 9000


# ---------------------------------------------------------------------------
# run_subagent — explicit overrides vs full inheritance
# ---------------------------------------------------------------------------


def test_run_subagent_applies_budget_overrides(tmp_path, recorded_configs):
    parent = EngineConfig()
    run_subagent(
        "scoped child",
        repo_path=str(tmp_path),
        parent_config=parent,
        parent_engine="mock",
        depth=1,
        spec=ChildSpec(max_steps=7, context_budget_tokens=20000),
    )
    child_config = recorded_configs[0]
    assert child_config.max_steps == 7
    assert child_config.context_budget_tokens == 20000


def test_run_subagent_without_overrides_is_byte_identical(tmp_path, recorded_configs):
    parent = EngineConfig()
    run_subagent(
        "scoped child",
        repo_path=str(tmp_path),
        parent_config=parent,
        parent_engine="mock",
        depth=1,
    )
    child_config = recorded_configs[0]
    assert child_config.max_steps == parent.max_steps
    assert child_config.context_budget_tokens == parent.context_budget_tokens


# ---------------------------------------------------------------------------
# _resolve_batch_width — the merge-slot reservation
# ---------------------------------------------------------------------------


def test_resolve_batch_width_reserves_merge_slot_by_default():
    config = EngineConfig(subagent_concurrency=MAX_SUBAGENT_FANOUT + 5)
    items = [{"instruction": "a"} for _ in range(MAX_SUBAGENT_FANOUT)]
    assert _resolve_batch_width(config, items, None) == MAX_SUBAGENT_FANOUT - 1


def test_resolve_batch_width_readonly_batch_frees_merge_slot():
    config = EngineConfig(subagent_concurrency=MAX_SUBAGENT_FANOUT + 5)
    items = [{"instruction": "a"} for _ in range(MAX_SUBAGENT_FANOUT)]
    assert _resolve_batch_width(config, items, "explorer") == MAX_SUBAGENT_FANOUT


def test_resolve_batch_width_mixed_roles_keep_reservation():
    config = EngineConfig(subagent_concurrency=9)
    items = [
        {"instruction": "a", "role": "explorer"},
        {"instruction": "b", "role": "writer"},
        {"instruction": "c"},
    ]
    assert _resolve_batch_width(config, items, "explorer") == min(
        MAX_SUBAGENT_FANOUT - 1, len(items)
    )


def test_resolve_batch_width_sequential_default_unchanged():
    config = EngineConfig()  # subagent_concurrency = 1
    items = [{"instruction": "a"} for _ in range(MAX_SUBAGENT_FANOUT)]
    assert _resolve_batch_width(config, items, "explorer") == 1


def test_resolve_batch_width_clamped_to_item_count():
    config = EngineConfig(subagent_concurrency=9)
    items = [{"instruction": "a"}, {"instruction": "b"}]
    assert _resolve_batch_width(config, items, None) == 2


# ---------------------------------------------------------------------------
# The subagents tool cap — read-only batches get the freed slot
# ---------------------------------------------------------------------------


def _fake_sub_result(task_id="c0") -> SubResult:
    return SubResult(
        task_id=task_id,
        engine="mock",
        model="m",
        status="ok",
        summary="done",
        changed_files=[],
    )


def _make_batch_spawn(results: List[SubResult] | None = None, *, call_log=None):
    ret = results if results is not None else []

    def batch_spawn(items: list, role=None) -> List[SubResult]:
        if call_log is not None:
            call_log.append(items)
        return ret

    return batch_spawn


def test_readonly_batch_of_full_fanout_is_allowed(tmp_path):
    results = [_fake_sub_result(f"c{i}") for i in range(MAX_SUBAGENT_FANOUT)]
    executor = ToolExecutor(tmp_path, batch_spawn=_make_batch_spawn(results))
    instructions = [
        {"instruction": f"survey {i}", "role": "explorer"} for i in range(MAX_SUBAGENT_FANOUT)
    ]
    outcome = executor.execute("subagents", {"instructions": instructions})
    assert isinstance(outcome, ToolOutcome)


def test_readonly_batch_role_argument_also_lifts_cap(tmp_path):
    results = [_fake_sub_result(f"c{i}") for i in range(MAX_SUBAGENT_FANOUT)]
    executor = ToolExecutor(tmp_path, batch_spawn=_make_batch_spawn(results))
    instructions = [{"instruction": f"survey {i}"} for i in range(MAX_SUBAGENT_FANOUT)]
    outcome = executor.execute("subagents", {"instructions": instructions, "role": "reviewer"})
    assert isinstance(outcome, ToolOutcome)


def test_writer_batch_of_full_fanout_still_refused(tmp_path):
    call_log: list = []
    executor = ToolExecutor(tmp_path, batch_spawn=_make_batch_spawn(call_log=call_log))
    instructions = [{"instruction": f"edit {i}"} for i in range(MAX_SUBAGENT_FANOUT)]
    with pytest.raises(ToolError):
        executor.execute("subagents", {"instructions": instructions})
    assert call_log == []


def test_readonly_batch_beyond_full_fanout_refused(tmp_path):
    call_log: list = []
    executor = ToolExecutor(tmp_path, batch_spawn=_make_batch_spawn(call_log=call_log))
    instructions = [
        {"instruction": f"survey {i}", "role": "explorer"} for i in range(MAX_SUBAGENT_FANOUT + 1)
    ]
    with pytest.raises(ToolError):
        executor.execute("subagents", {"instructions": instructions})
    assert call_log == []


def test_one_writer_item_in_readonly_batch_keeps_old_cap(tmp_path):
    call_log: list = []
    executor = ToolExecutor(tmp_path, batch_spawn=_make_batch_spawn(call_log=call_log))
    instructions = [
        {"instruction": "survey 0", "role": "explorer"},
        {"instruction": "survey 1", "role": "explorer"},
        {"instruction": "survey 2", "role": "explorer"},
        {"instruction": "edit 3", "role": "writer"},
    ]
    with pytest.raises(ToolError):
        executor.execute("subagents", {"instructions": instructions})
    assert call_log == []
