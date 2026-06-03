"""Tests for the explicit not_finished flag on TaskResult (issue #106, task t5).

AC1: ``TaskResult.not_finished`` is a boolean field with default ``False``.
AC2: Set from ``_drive_loop``'s return value (NOT from step_count).
AC3: True iff the drive exhausted the step budget without calling finish AND
     without raising ``DriveAborted``.
AC4: False on a clean finish (finish tool called).
AC5: False on a no-tool-call terminating answer.
AC6: False on the aborted path (that is a different signal).
"""

from __future__ import annotations

from dataclasses import fields as dc_fields
from pathlib import Path

import pytest

from colleague.contract import TaskResult
from colleague.loop import ModelResponse, ToolCall, run

# ---------------------------------------------------------------------------
# Field contract
# ---------------------------------------------------------------------------


def test_not_finished_field_exists_on_task_result():
    """``TaskResult`` must carry a ``not_finished`` field."""
    field_names = {f.name for f in dc_fields(TaskResult)}
    assert (
        "not_finished" in field_names
    ), "TaskResult is missing the 'not_finished' field — add it to colleague/contract.py"


def test_not_finished_default_is_false():
    """The default for ``not_finished`` must be ``False`` (existing constructors stay valid)."""
    result = TaskResult(task_id="x", status="ok")
    assert result.not_finished is False


# ---------------------------------------------------------------------------
# True path: step budget exhausted without finish
# ---------------------------------------------------------------------------


def test_budget_exhaustion_sets_not_finished_true(tmp_path: Path) -> None:
    """A drive that burns all steps without calling ``finish`` → not_finished is True.

    This is the primary AC: the _drive_loop returns False (budget hit),
    run() captures that and sets result.not_finished = True.
    """

    def silent_looper(_messages: list[dict]) -> ModelResponse:
        # Content-less tool call — never finishes, burns the budget.
        return ModelResponse(tool_calls=[ToolCall("1", "list_dir", {"path": "."})])

    task = __import__("colleague.contract", fromlist=["Task"]).Task.new(
        str(tmp_path), "budget exhaustion test"
    )
    result = run(silent_looper, task, max_steps=3)

    assert (
        result.not_finished is True
    ), "Drive that exhausted the step budget must have not_finished=True"


def test_budget_exhaustion_with_narration_sets_not_finished_true(tmp_path: Path) -> None:
    """Budget exhaustion while emitting content still sets not_finished = True.

    The drive emits non-empty content each turn but never calls finish.
    not_finished tracks the finish status, not whether content was produced.
    """

    def narrating_looper(_messages: list[dict]) -> ModelResponse:
        return ModelResponse(
            content="still working",
            tool_calls=[ToolCall("1", "list_dir", {"path": "."})],
        )

    from colleague.contract import Task

    task = Task.new(str(tmp_path), "narrating budget test")
    result = run(narrating_looper, task, max_steps=2)

    assert result.not_finished is True


# ---------------------------------------------------------------------------
# False path: clean finish
# ---------------------------------------------------------------------------


def test_finish_tool_sets_not_finished_false(tmp_path: Path) -> None:
    """A drive that calls the finish tool → not_finished is False."""
    from colleague.contract import Task

    def finish_immediately(_messages: list[dict]) -> ModelResponse:
        return ModelResponse(tool_calls=[ToolCall("1", "finish", {"summary": "done"})])

    task = Task.new(str(tmp_path), "clean finish test")
    result = run(finish_immediately, task, max_steps=5)

    assert result.not_finished is False


# ---------------------------------------------------------------------------
# False path: no-tool-call terminating answer
# ---------------------------------------------------------------------------


def test_no_tool_call_answer_sets_not_finished_false(tmp_path: Path) -> None:
    """A drive where the model answers without tool calls → not_finished is False.

    _drive_loop returns True when the model stops calling tools; the flag
    must remain False (the drive DID finish, just without the finish tool).
    """
    from colleague.contract import Task

    def answer_directly(_messages: list[dict]) -> ModelResponse:
        return ModelResponse(content="Here is the answer.")  # no tool_calls

    task = Task.new(str(tmp_path), "direct answer test")
    result = run(answer_directly, task, max_steps=5)

    assert result.not_finished is False


# ---------------------------------------------------------------------------
# False path: aborted (exception)
# ---------------------------------------------------------------------------


def test_aborted_drive_leaves_not_finished_false(tmp_path: Path) -> None:
    """A drive aborted by an engine exception must NOT set not_finished = True.

    DriveAborted is a separate signal; not_finished is only for the
    budget-exhaustion case. The default False must hold through the aborted path.
    """
    from colleague.loop import DriveAborted

    call_count = {"n": 0}

    def blows_up(_messages: list[dict]) -> ModelResponse:
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("engine exploded")
        return ModelResponse(tool_calls=[ToolCall("1", "list_dir", {"path": "."})])

    from colleague.contract import Task

    task = Task.new(str(tmp_path), "aborted drive test")
    with pytest.raises(DriveAborted) as exc_info:
        run(blows_up, task, max_steps=10)

    result = exc_info.value.result
    assert (
        result.not_finished is False
    ), "Aborted drives must leave not_finished=False — DriveAborted is the signal, not this flag"


# ---------------------------------------------------------------------------
# Serialisation round-trip
# ---------------------------------------------------------------------------


def test_not_finished_serialises_in_to_dict(tmp_path: Path) -> None:
    """``not_finished`` must appear in ``to_dict()`` so the artifact carries it."""
    from colleague.contract import Task

    def looper(_messages: list[dict]) -> ModelResponse:
        return ModelResponse(tool_calls=[ToolCall("1", "list_dir", {"path": "."})])

    task = Task.new(str(tmp_path), "serialisation test")
    result = run(looper, task, max_steps=2)

    d = result.to_dict()
    assert "not_finished" in d
    assert d["not_finished"] is True  # budget hit


def test_not_finished_round_trips_through_from_dict() -> None:
    """``TaskResult.from_dict`` must restore ``not_finished`` faithfully."""
    original = TaskResult(task_id="abc", status="ok", not_finished=True)
    d = original.to_dict()
    restored = TaskResult.from_dict(d)
    assert restored.not_finished is True

    original_false = TaskResult(task_id="xyz", status="ok", not_finished=False)
    d_false = original_false.to_dict()
    restored_false = TaskResult.from_dict(d_false)
    assert restored_false.not_finished is False
