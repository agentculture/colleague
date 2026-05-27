"""Task contract: typed Task/TaskResult and lossless JSON round-trip (R1, h1)."""

from __future__ import annotations

import json

from convertible.contract import OK, Step, Task, TaskResult, Usage


def test_task_new_assigns_id_and_fields() -> None:
    task = Task.new(
        "/tmp/repo", "add a README", engine="mock", context="ctx", constraints=["no deps"]
    )
    assert task.id
    assert task.repo_path == "/tmp/repo"
    assert task.instruction == "add a README"
    assert task.engine == "mock"
    assert task.constraints == ["no deps"]


def test_task_round_trips() -> None:
    task = Task.new("/repo", "do work", engine="vllm-openai")
    assert Task.from_dict(task.to_dict()) == task


def test_usage_add_accumulates() -> None:
    usage = Usage()
    usage.add(10, 5)
    usage.add(2, 3)
    assert usage.to_dict() == {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20}


def test_task_result_round_trips_through_json() -> None:
    result = TaskResult(
        task_id="abc123",
        status=OK,
        summary="wrote a file",
        changed_files=["README.md"],
        steps=[Step(index=0, tool="write_file", arguments={"path": "README.md"}, result="wrote")],
        usage=Usage(prompt_tokens=10, completion_tokens=4, total_tokens=14),
        artifacts_path=".convertible/result.json",
        branch="convertible/abc123",
        pr_url="https://github.com/x/y/pull/1",
    )
    # serialize -> json -> load -> reconstruct must equal the original
    reloaded = TaskResult.from_dict(json.loads(json.dumps(result.to_dict())))
    assert reloaded == result


def test_task_result_defaults_are_independent() -> None:
    a = TaskResult(task_id="1", status=OK)
    b = TaskResult(task_id="2", status=OK)
    a.changed_files.append("x")
    assert b.changed_files == []
