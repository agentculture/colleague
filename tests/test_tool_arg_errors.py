"""Malformed tool arguments cost one step, never the run (best-colleague arc t9).

Live evidence: work item ``4c6a96107269`` (a substantial multi-module build with
4 folded sub-results) died at step 12 with ``engine 'vllm-openai' failed:
'path'`` — the model emitted a tool call without its required ``path`` argument,
the bare ``arguments["path"]`` raised ``KeyError``, and the KeyError escaped the
dispatch (which caught only ``ToolError``), aborting the entire run.

Two layers, both pinned here:

1. tools validate required args and raise ``ToolError`` with a self-correcting
   message (the model reads it and retries with the arg);
2. the loop's dispatch boundary converts residual argument-shaped errors
   (``KeyError``/``TypeError``/``ValueError``) into a non-ok step + tool
   message, exactly like a ``ToolError`` — a genuinely unexpected exception
   still aborts (a harness bug should surface, not be eaten).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from colleague.contract import OK, Task
from colleague.loop import ModelResponse, ToolCall, run
from colleague.tools import ToolError, ToolExecutor


@pytest.fixture()
def executor(tmp_path: Path) -> ToolExecutor:
    return ToolExecutor(str(tmp_path))


class TestRequiredArgsRaiseToolError:
    def test_read_file_without_path(self, executor: ToolExecutor) -> None:
        with pytest.raises(ToolError, match="read_file requires 'path'"):
            executor.execute("read_file", {})

    def test_write_file_without_path(self, executor: ToolExecutor) -> None:
        with pytest.raises(ToolError, match="write_file requires 'path'"):
            executor.execute("write_file", {"content": "x"})

    def test_edit_file_without_path(self, executor: ToolExecutor) -> None:
        with pytest.raises(ToolError, match="edit_file requires 'path'"):
            executor.execute("edit_file", {"old_string": "a", "new_string": "b"})

    def test_edit_file_without_old_string(self, executor: ToolExecutor, tmp_path: Path) -> None:
        (tmp_path / "f.txt").write_text("hello")
        with pytest.raises(ToolError, match="edit_file requires 'old_string'"):
            executor.execute("edit_file", {"path": "f.txt", "new_string": "b"})

    def test_edit_file_without_new_string(self, executor: ToolExecutor, tmp_path: Path) -> None:
        (tmp_path / "f.txt").write_text("hello")
        with pytest.raises(ToolError, match="edit_file requires 'new_string'"):
            executor.execute("edit_file", {"path": "f.txt", "old_string": "hello"})


def test_malformed_tool_call_costs_one_step_not_the_run(tmp_path: Path) -> None:
    """The observed crash shape: a bad call mid-run; the run must recover."""
    responses = [
        ModelResponse(tool_calls=[ToolCall("1", "read_file", {})]),  # missing path
        ModelResponse(tool_calls=[ToolCall("2", "finish", {"summary": "recovered and finished"})]),
    ]
    state = {"i": 0}

    def complete(_messages: list[dict]) -> ModelResponse:
        i = min(state["i"], len(responses) - 1)
        state["i"] += 1
        return responses[i]

    result = run(complete, Task.new(str(tmp_path), "task"), max_steps=5)

    assert result.status == OK
    assert result.summary == "recovered and finished"
    bad = result.steps[0]
    assert bad.ok is False
    assert "path" in bad.result


def test_residual_arg_error_converted_at_dispatch_boundary(tmp_path: Path) -> None:
    """Even an unvalidated KeyError from a tool becomes a step, not an abort."""
    executor = ToolExecutor(str(tmp_path))

    def bad_tool(arguments: dict) -> None:
        raise KeyError("path")

    # Shadow the bound method: execute() builds its dispatch table from
    # ``self._read_file`` per call, so the instance attribute wins.
    executor._read_file = bad_tool  # type: ignore[method-assign]

    responses = [
        ModelResponse(tool_calls=[ToolCall("1", "read_file", {"path": "x"})]),
        ModelResponse(tool_calls=[ToolCall("2", "finish", {"summary": "done"})]),
    ]
    state = {"i": 0}

    def complete(_messages: list[dict]) -> ModelResponse:
        i = min(state["i"], len(responses) - 1)
        state["i"] += 1
        return responses[i]

    result = run(complete, Task.new(str(tmp_path), "task"), max_steps=5, executor=executor)

    assert result.status == OK
    assert result.steps[0].ok is False
