"""Tests for the finish-nudge + ``stopped_without_finish`` flag (colleague#142).

A drive that ends a turn with no tool call used to be treated as a clean finish,
so a model trailing off mid-task ("Now I have enough… let me verify one more
thing") was returned as the authoritative summary with ``not_finished=False`` and
no signal. The loop now:

* **nudges once** — on a no-tool-call turn it reminds the model to call ``finish``
  and continues, recovering the common forgot-to-finish case; and
* **signals the residual** — if the model still stops without finishing, the drive
  sets ``TaskResult.stopped_without_finish=True`` (orthogonal to ``not_finished``,
  which stays the step-budget signal).
"""

from __future__ import annotations

from pathlib import Path

from colleague.contract import Task, TaskResult
from colleague.loop import _FINISH_NUDGE, ModelResponse, ToolCall, run

# ---------------------------------------------------------------------------
# Field contract
# ---------------------------------------------------------------------------


def test_field_defaults_false() -> None:
    assert TaskResult(task_id="x", status="ok").stopped_without_finish is False


def test_field_round_trips() -> None:
    original = TaskResult(task_id="abc", status="ok", stopped_without_finish=True)
    restored = TaskResult.from_dict(original.to_dict())
    assert restored.stopped_without_finish is True
    assert "stopped_without_finish" in original.to_dict()


# ---------------------------------------------------------------------------
# Nudge recovery: a forgot-to-finish turn becomes a real finish
# ---------------------------------------------------------------------------


def test_nudge_recovers_a_real_finish(tmp_path: Path) -> None:
    """Trail off once → after the nudge the model calls finish → clean result."""
    seen: list[dict] = []
    turn = {"n": 0}

    def trails_then_finishes(messages: list[dict]) -> ModelResponse:
        seen.append(messages[-1])
        turn["n"] += 1
        if turn["n"] == 1:
            return ModelResponse(content="Now I have enough. Let me verify one more thing:")
        return ModelResponse(tool_calls=[ToolCall("1", "finish", {"summary": "real review"})])

    result = run(trails_then_finishes, Task.new(str(tmp_path), "nudge recovery"), max_steps=5)

    assert result.stopped_without_finish is False
    assert result.not_finished is False
    assert result.summary == "real review"  # the finish summary, not the trailing prose
    # The reminder was actually injected into the conversation before turn 2.
    assert any(m.get("content") == _FINISH_NUDGE for m in seen)


# ---------------------------------------------------------------------------
# Stubborn stop: still no finish after the nudge → flagged, summary preserved
# ---------------------------------------------------------------------------


def test_stubborn_no_tool_call_sets_stopped_without_finish(tmp_path: Path) -> None:
    """Prose every turn, never a tool → after the nudge, stopped_without_finish=True."""

    def always_trails(_messages: list[dict]) -> ModelResponse:
        return ModelResponse(content="Here is the answer.")  # never a tool call

    result = run(always_trails, Task.new(str(tmp_path), "stubborn stop"), max_steps=5)

    assert result.stopped_without_finish is True
    assert result.not_finished is False  # not a budget exhaustion
    assert result.status == "ok"
    assert result.summary == "Here is the answer."  # trailing prose preserved as partial


def test_budget_exhaustion_is_not_stopped_without_finish(tmp_path: Path) -> None:
    """A drive that burns its steps via tool calls is budget-not-finished, not stopped."""

    def keeps_calling_tools(_messages: list[dict]) -> ModelResponse:
        return ModelResponse(tool_calls=[ToolCall("1", "list_dir", {"path": "."})])

    result = run(keeps_calling_tools, Task.new(str(tmp_path), "budget"), max_steps=3)

    assert result.not_finished is True
    assert result.stopped_without_finish is False


def test_clean_finish_sets_neither_flag(tmp_path: Path) -> None:
    def finish_now(_messages: list[dict]) -> ModelResponse:
        return ModelResponse(tool_calls=[ToolCall("1", "finish", {"summary": "done"})])

    result = run(finish_now, Task.new(str(tmp_path), "clean"), max_steps=5)

    assert result.not_finished is False
    assert result.stopped_without_finish is False
