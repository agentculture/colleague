"""Bounded agentic tool-loop: execution, termination, usage, errors (R3, h3)."""

from __future__ import annotations

import json
from pathlib import Path

from convertible.contract import OK, Task
from convertible.loop import CompleteFn, ModelResponse, ToolCall, _assistant_message, run


def scripted(responses: list[ModelResponse]) -> CompleteFn:
    """A complete() that returns each canned response in turn (then repeats last)."""
    state = {"i": 0}

    def complete(_messages: list[dict]) -> ModelResponse:
        i = min(state["i"], len(responses) - 1)
        state["i"] += 1
        return responses[i]

    return complete


def test_loop_writes_file_and_finishes(tmp_path: Path) -> None:
    responses = [
        ModelResponse(
            tool_calls=[ToolCall("1", "write_file", {"path": "out.txt", "content": "hello"})],
            prompt_tokens=10,
            completion_tokens=2,
        ),
        ModelResponse(
            tool_calls=[ToolCall("2", "finish", {"summary": "wrote out.txt"})],
            completion_tokens=1,
        ),
    ]
    task = Task.new(str(tmp_path), "write out.txt")
    result = run(scripted(responses), task, max_steps=10)

    assert result.status == OK
    assert result.changed_files == ["out.txt"]
    assert (tmp_path / "out.txt").read_text() == "hello"
    assert result.summary == "wrote out.txt"
    assert result.usage.total_tokens == 13
    assert len(result.steps) == 2


def test_loop_stops_at_budget_when_never_finishing(tmp_path: Path) -> None:
    def never_finish(_messages: list[dict]) -> ModelResponse:
        return ModelResponse(tool_calls=[ToolCall("x", "list_dir", {"path": "."})])

    task = Task.new(str(tmp_path), "loop forever")
    result = run(never_finish, task, max_steps=3)

    assert result.status == OK
    assert len(result.steps) == 3
    assert "budget" in result.summary


def test_loop_terminates_on_empty_tool_calls(tmp_path: Path) -> None:
    task = Task.new(str(tmp_path), "just answer")
    result = run(scripted([ModelResponse(content="nothing to do here")]), task, max_steps=5)
    assert result.summary == "nothing to do here"
    assert result.steps == []


def test_assistant_message_serializes_arguments_as_json_string() -> None:
    # OpenAI wire format: function.arguments must be a JSON *string*, not a dict,
    # or strict servers reject replayed turns.
    resp = ModelResponse(tool_calls=[ToolCall("1", "write_file", {"path": "a", "content": "b"})])
    msg = _assistant_message(resp)
    args = msg["tool_calls"][0]["function"]["arguments"]
    assert isinstance(args, str)
    assert json.loads(args) == {"path": "a", "content": "b"}


def test_assistant_message_passes_string_arguments_through() -> None:
    resp = ModelResponse(tool_calls=[ToolCall("1", "finish", '{"summary": "done"}')])
    args = _assistant_message(resp)["tool_calls"][0]["function"]["arguments"]
    assert args == '{"summary": "done"}'


def test_loop_records_tool_error_and_continues(tmp_path: Path) -> None:
    responses = [
        ModelResponse(tool_calls=[ToolCall("1", "read_file", {"path": "missing.txt"})]),
        ModelResponse(tool_calls=[ToolCall("2", "finish", {"summary": "gave up reading"})]),
    ]
    task = Task.new(str(tmp_path), "read a missing file")
    result = run(scripted(responses), task, max_steps=5)

    assert result.status == OK  # a failed tool call is not a failed drive
    assert result.steps[0].ok is False
    assert "error:" in result.steps[0].result
    assert result.summary == "gave up reading"
