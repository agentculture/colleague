"""Tests for the ``subagents`` (plural) batch tool in :mod:`colleague.tools`.

Acceptance criteria (task t4):
1. ``ToolExecutor`` exposes a ``subagents`` tool whose schema accepts
   ``instructions[]`` (+ optional per-item engine/model); the existing
   single-child ``subagent`` tool schema is UNCHANGED (snapshot + compare).
2. A batch with >3 instructions is refused with a ``ToolError`` BEFORE
   ``self._batch_spawn`` is called — injected fake records if called.
3. A valid batch (≤3) calls ``batch_spawn`` once with the parsed items and
   folds the returned ``SubResult`` list into ``self.sub_results``.
"""

from __future__ import annotations

from typing import List

import pytest

from colleague.config import MAX_SUBAGENT_FANOUT
from colleague.contract import SubResult
from colleague.tools import SCHEMAS, TOOL_NAMES, ToolError, ToolExecutor, ToolOutcome

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SUBAGENT_SCHEMA_SNAPSHOT = {
    "type": "function",
    "function": {
        "name": "subagent",
        "description": (
            "Delegate a scoped sub-task to a nested in-process child work item, "
            "optionally on a different engine or model. The child work item runs "
            "the full bounded tool-loop (no git handoff) and returns a result "
            "summary; any files the child writes are merged into the parent's "
            "changed-file set so they reach the single top-level handoff. "
            "Use this to break a large task into independently executable "
            "pieces or to run part of the work on a specialised model."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "instruction": {
                    "type": "string",
                    "description": "A scoped sub-task for a nested child work item.",
                },
                "engine": {
                    "type": "string",
                    "description": "Engine wheel for the subagent (omit to inherit parent).",
                },
                "model": {
                    "type": "string",
                    "description": "Model override for the subagent (omit to inherit parent).",
                },
            },
            "required": ["instruction"],
        },
    },
}


def _fake_sub_result(
    task_id="bs1",
    engine="mock",
    model="m",
    status="ok",
    summary="batch child done",
    changed_files=None,
) -> SubResult:
    return SubResult(
        task_id=task_id,
        engine=engine,
        model=model,
        status=status,
        summary=summary,
        changed_files=list(changed_files or []),
    )


def _make_batch_spawn(results: List[SubResult] | None = None, *, call_log: list | None = None):
    """Return a fake batch_spawn callable.

    If ``call_log`` is provided, each call appends the ``items`` argument so
    tests can assert whether and how often it was called.
    """
    ret = results if results is not None else []

    def batch_spawn(items: list) -> List[SubResult]:
        if call_log is not None:
            call_log.append(items)
        return ret

    return batch_spawn


# ---------------------------------------------------------------------------
# AC1 — schema presence for ``subagents`` and snapshot of ``subagent``
# ---------------------------------------------------------------------------


def test_subagents_in_schemas():
    names = [s["function"]["name"] for s in SCHEMAS]
    assert "subagents" in names, "SCHEMAS must include a 'subagents' function"


def test_subagents_in_tool_names():
    assert "subagents" in TOOL_NAMES, "TOOL_NAMES must include 'subagents'"


def test_subagents_schema_accepts_instructions_array():
    schema = next(s for s in SCHEMAS if s["function"]["name"] == "subagents")
    props = schema["function"]["parameters"]["properties"]
    assert "instructions" in props, "'instructions' must be a property of the subagents schema"
    inst = props["instructions"]
    assert inst["type"] == "array", "'instructions' must be an array type"
    # Each item must have 'instruction' (required) and optional 'engine'/'model'
    item_props = inst["items"]["properties"]
    assert "instruction" in item_props, "each item must have an 'instruction' property"
    assert "engine" in item_props, "each item must have an 'engine' property"
    assert "model" in item_props, "each item must have a 'model' property"
    # 'instruction' must be required in the item schema
    assert "instruction" in inst["items"].get(
        "required", []
    ), "'instruction' must be required in the item schema"


def test_subagents_schema_instructions_required():
    schema = next(s for s in SCHEMAS if s["function"]["name"] == "subagents")
    fn = schema["function"]
    assert "instructions" in fn["parameters"].get(
        "required", []
    ), "'instructions' must be a required parameter of the subagents schema"


def test_subagent_schema_unchanged():
    """The existing single-child 'subagent' tool schema must be byte-identical to the snapshot."""
    schema = next(s for s in SCHEMAS if s["function"]["name"] == "subagent")
    assert schema == _SUBAGENT_SCHEMA_SNAPSHOT, (
        "The 'subagent' tool schema was modified — it must stay byte-identical. "
        f"Got:\n{schema}\n\nExpected:\n{_SUBAGENT_SCHEMA_SNAPSHOT}"
    )


# ---------------------------------------------------------------------------
# AC2 — batch with >3 instructions refused BEFORE batch_spawn is called
# ---------------------------------------------------------------------------


def test_subagents_over_cap_raises_tool_error(tmp_path):
    """A batch of MAX_SUBAGENT_FANOUT (=4) instructions is too many; refused."""
    call_log: list = []
    executor = ToolExecutor(tmp_path, batch_spawn=_make_batch_spawn(call_log=call_log))
    # MAX_SUBAGENT_FANOUT - 1 = 3 is the cap; 4 instructions is one too many.
    instructions = [{"instruction": f"task {i}"} for i in range(MAX_SUBAGENT_FANOUT)]
    with pytest.raises(ToolError):
        executor.execute("subagents", {"instructions": instructions})
    # batch_spawn must NOT have been called
    assert call_log == [], "batch_spawn must not be called when the cap is exceeded"


def test_subagents_exactly_at_cap_allowed(tmp_path):
    """Exactly MAX_SUBAGENT_FANOUT - 1 (=3) instructions must be accepted."""
    results = [_fake_sub_result(task_id=f"c{i}") for i in range(MAX_SUBAGENT_FANOUT - 1)]
    executor = ToolExecutor(tmp_path, batch_spawn=_make_batch_spawn(results))
    instructions = [{"instruction": f"task {i}"} for i in range(MAX_SUBAGENT_FANOUT - 1)]
    outcome = executor.execute("subagents", {"instructions": instructions})
    assert isinstance(outcome, ToolOutcome)


def test_subagents_cap_error_message_mentions_limit(tmp_path):
    """The ToolError message should mention the cap or 'limit'."""
    executor = ToolExecutor(tmp_path, batch_spawn=_make_batch_spawn())
    instructions = [{"instruction": f"task {i}"} for i in range(MAX_SUBAGENT_FANOUT)]
    with pytest.raises(ToolError, match=r"[Ll]imit|cap|\d"):
        executor.execute("subagents", {"instructions": instructions})


def test_subagents_batch_spawn_not_called_on_cap_exceeded(tmp_path):
    """Stricter check: batch_spawn must not be called, even partially, on cap exceeded."""
    was_called = []

    def batch_spawn(items):
        was_called.append(items)
        return []

    executor = ToolExecutor(tmp_path, batch_spawn=batch_spawn)
    big_batch = [{"instruction": f"step {i}"} for i in range(MAX_SUBAGENT_FANOUT + 1)]
    with pytest.raises(ToolError):
        executor.execute("subagents", {"instructions": big_batch})
    assert was_called == [], "batch_spawn must not be called before the ToolError is raised"


# ---------------------------------------------------------------------------
# AC3 — valid batch calls batch_spawn and folds results
# ---------------------------------------------------------------------------


def test_subagents_calls_batch_spawn_once(tmp_path):
    call_log: list = []
    results = [_fake_sub_result()]
    executor = ToolExecutor(tmp_path, batch_spawn=_make_batch_spawn(results, call_log=call_log))
    executor.execute("subagents", {"instructions": [{"instruction": "do thing"}]})
    assert len(call_log) == 1, "batch_spawn must be called exactly once"


def test_subagents_passes_items_to_batch_spawn(tmp_path):
    call_log: list = []
    results = [_fake_sub_result()]
    executor = ToolExecutor(tmp_path, batch_spawn=_make_batch_spawn(results, call_log=call_log))
    instructions = [
        {"instruction": "task A", "engine": "mock"},
        {"instruction": "task B", "model": "m2"},
    ]
    executor.execute("subagents", {"instructions": instructions})
    passed = call_log[0]
    assert len(passed) == 2
    assert passed[0]["instruction"] == "task A"
    assert passed[0].get("engine") == "mock"
    assert passed[1]["instruction"] == "task B"
    assert passed[1].get("model") == "m2"


def test_subagents_folds_results_into_sub_results(tmp_path):
    r1 = _fake_sub_result(task_id="c1", summary="first child")
    r2 = _fake_sub_result(task_id="c2", summary="merge child")
    executor = ToolExecutor(tmp_path, batch_spawn=_make_batch_spawn([r1, r2]))
    executor.execute("subagents", {"instructions": [{"instruction": "one"}]})
    assert r1 in executor.sub_results
    assert r2 in executor.sub_results


def test_subagents_returns_tool_outcome(tmp_path):
    executor = ToolExecutor(
        tmp_path,
        batch_spawn=_make_batch_spawn([_fake_sub_result()]),
    )
    outcome = executor.execute("subagents", {"instructions": [{"instruction": "x"}]})
    assert isinstance(outcome, ToolOutcome)


def test_subagents_outcome_result_is_string(tmp_path):
    executor = ToolExecutor(
        tmp_path,
        batch_spawn=_make_batch_spawn([_fake_sub_result(summary="child done")]),
    )
    outcome = executor.execute("subagents", {"instructions": [{"instruction": "x"}]})
    assert isinstance(outcome.result, str)
    assert len(outcome.result) > 0


# ---------------------------------------------------------------------------
# No batch_spawn → ToolError
# ---------------------------------------------------------------------------


def test_subagents_no_batch_spawn_raises_tool_error(tmp_path):
    executor = ToolExecutor(tmp_path)  # no batch_spawn
    with pytest.raises(ToolError, match="not available"):
        executor.execute("subagents", {"instructions": [{"instruction": "x"}]})


# ---------------------------------------------------------------------------
# Empty / invalid instructions
# ---------------------------------------------------------------------------


def test_subagents_empty_instructions_raises_tool_error(tmp_path):
    executor = ToolExecutor(tmp_path, batch_spawn=_make_batch_spawn([]))
    with pytest.raises(ToolError):
        executor.execute("subagents", {"instructions": []})


def test_subagents_item_missing_instruction_raises_tool_error(tmp_path):
    executor = ToolExecutor(tmp_path, batch_spawn=_make_batch_spawn([_fake_sub_result()]))
    with pytest.raises(ToolError, match="instruction"):
        executor.execute("subagents", {"instructions": [{"engine": "mock"}]})


# ---------------------------------------------------------------------------
# Exception from batch_spawn converted to ToolError
# ---------------------------------------------------------------------------


def test_subagents_launcher_exception_converted_to_tool_error(tmp_path):
    def bad_spawn(items):
        raise RuntimeError("batch exploded")

    executor = ToolExecutor(tmp_path, batch_spawn=bad_spawn)
    with pytest.raises(ToolError, match="subagents failed"):
        executor.execute("subagents", {"instructions": [{"instruction": "x"}]})


def test_subagents_tool_error_from_batch_spawn_propagated(tmp_path):
    def bad_spawn(items):
        raise ToolError("inner batch error")

    executor = ToolExecutor(tmp_path, batch_spawn=bad_spawn)
    with pytest.raises(ToolError, match="inner batch error"):
        executor.execute("subagents", {"instructions": [{"instruction": "x"}]})


# ---------------------------------------------------------------------------
# ToolExecutor backward-compat: batch_spawn is keyword-only
# ---------------------------------------------------------------------------


def test_tool_executor_batch_spawn_defaults_to_none(tmp_path):
    executor = ToolExecutor(tmp_path)
    assert executor._batch_spawn is None


def test_tool_executor_batch_spawn_stored(tmp_path):
    fake = _make_batch_spawn([])
    executor = ToolExecutor(tmp_path, batch_spawn=fake)
    assert executor._batch_spawn is fake


def test_tool_executor_batch_spawn_keyword_only(tmp_path):
    """batch_spawn is keyword-only; existing positional callers are unaffected."""
    # Passing nothing must work (default None)
    ex1 = ToolExecutor(tmp_path)
    assert ex1._batch_spawn is None
    # Passing via keyword must work
    fake = _make_batch_spawn([])
    ex2 = ToolExecutor(tmp_path, batch_spawn=fake)
    assert ex2._batch_spawn is fake
