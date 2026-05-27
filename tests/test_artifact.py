"""Result artifact + trace: always-written, valid JSON, error survives (R5, h5)."""

from __future__ import annotations

import json
from pathlib import Path

from convertible.artifact import failed_result, write
from convertible.contract import ERROR, OK, Step, Task, TaskResult, Usage
from convertible.loop import ModelResponse, ToolCall, run


def _result_with_steps(tmp_path: Path) -> TaskResult:
    return TaskResult(
        task_id="t1",
        status=OK,
        summary="did a thing",
        changed_files=["a.txt"],
        steps=[Step(0, "write_file", {"path": "a.txt"}, "wrote 1 bytes to a.txt")],
        usage=Usage(prompt_tokens=5, completion_tokens=2, total_tokens=7),
    )


def test_write_produces_valid_json_with_required_keys(tmp_path: Path) -> None:
    path = write(_result_with_steps(tmp_path), tmp_path / ".convertible")
    payload = json.loads(path.read_text())
    for key in ("status", "changed_files", "steps", "usage"):
        assert key in payload
    assert payload["status"] == OK
    assert payload["changed_files"] == ["a.txt"]


def test_write_sets_artifacts_path() -> None:
    result = TaskResult(task_id="t2", status=OK)
    path = write(result, "/tmp/conv-test-artifact")
    assert result.artifacts_path == str(path)


def test_failed_run_still_writes_error_artifact(tmp_path: Path) -> None:
    result = failed_result("crashed", "boom: engine raised RuntimeError")
    path = write(result, tmp_path / ".convertible")
    payload = json.loads(path.read_text())
    assert payload["status"] == ERROR
    assert "boom" in payload["error"]


def test_trace_jsonl_has_one_line_per_step(tmp_path: Path) -> None:
    out = tmp_path / ".convertible"
    write(_result_with_steps(tmp_path), out)
    trace = (out / "t1.trace.jsonl").read_text().strip().splitlines()
    assert len(trace) == 1
    assert json.loads(trace[0])["tool"] == "write_file"


def test_real_drive_artifact_round_trips(tmp_path: Path) -> None:
    responses = [
        ModelResponse(tool_calls=[ToolCall("1", "write_file", {"path": "x", "content": "y"})]),
        ModelResponse(tool_calls=[ToolCall("2", "finish", {"summary": "done"})]),
    ]
    state = {"i": 0}

    def complete(_m: list[dict]) -> ModelResponse:
        r = responses[min(state["i"], 1)]
        state["i"] += 1
        return r

    task = Task.new(str(tmp_path), "write x")
    result = run(complete, task, max_steps=5)
    path = write(result, tmp_path / ".convertible")
    reloaded = TaskResult.from_dict(json.loads(path.read_text()))
    assert reloaded.changed_files == ["x"]
