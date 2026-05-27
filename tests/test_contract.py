"""Task contract: typed Task/TaskResult and lossless JSON round-trip (R1, h1)."""

from __future__ import annotations

import json

from convertible.contract import OK, HookFiring, Step, Task, TaskResult, Usage


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


# ---------------------------------------------------------------------------
# t2: HookFiring dataclass and new TaskResult fields (hook_firings, command)
# ---------------------------------------------------------------------------


def test_hook_firing_defaults() -> None:
    """HookFiring has sensible defaults for optional fields."""
    hf = HookFiring(event="task_start")
    assert hf.event == "task_start"
    assert hf.tool is None
    assert hf.command is None
    assert hf.decision == "observe"
    assert hf.exit_code is None
    assert hf.reason == ""


def test_hook_firing_round_trips() -> None:
    """HookFiring serializes to dict and reconstructs identically."""
    hf = HookFiring(
        event="pre_tool",
        tool="write_file",
        command="echo pre",
        decision="allow",
        exit_code=0,
        reason="",
    )
    assert HookFiring.from_dict(hf.to_dict()) == hf


def test_hook_firing_deny_round_trips() -> None:
    """A deny firing with a reason round-trips correctly."""
    hf = HookFiring(
        event="post_tool",
        tool="run_command",
        command="validate.sh",
        decision="deny",
        exit_code=1,
        reason="forbidden pattern detected",
    )
    reloaded = HookFiring.from_dict(json.loads(json.dumps(hf.to_dict())))
    assert reloaded == hf
    assert reloaded.decision == "deny"
    assert reloaded.reason == "forbidden pattern detected"


def test_hook_firing_from_dict_tolerates_missing_optional_keys() -> None:
    """from_dict must apply defaults when optional keys are absent (back-compat)."""
    hf = HookFiring.from_dict({"event": "finish"})
    assert hf.event == "finish"
    assert hf.tool is None
    assert hf.command is None
    assert hf.decision == "observe"
    assert hf.exit_code is None
    assert hf.reason == ""


def test_task_result_hook_firings_and_command_round_trip() -> None:
    """TaskResult with hook_firings + command set round-trips through to_dict/from_dict."""
    firings = [
        HookFiring(event="pre_tool", tool="write_file", decision="allow", exit_code=0),
        HookFiring(event="post_tool", tool="write_file", decision="observe"),
    ]
    result = TaskResult(
        task_id="xyz789",
        status=OK,
        summary="ran with hooks",
        hook_firings=firings,
        command="scaffold",
    )
    reloaded = TaskResult.from_dict(json.loads(json.dumps(result.to_dict())))
    assert reloaded == result
    assert len(reloaded.hook_firings) == 2
    assert reloaded.hook_firings[0].decision == "allow"
    assert reloaded.hook_firings[1].event == "post_tool"
    assert reloaded.command == "scaffold"


def test_task_result_from_dict_defaults_new_fields_when_absent() -> None:
    """from_dict tolerates absence of hook_firings + command (old payloads / other engines)."""
    old_payload = {
        "task_id": "legacy1",
        "status": OK,
        "summary": "",
        "changed_files": [],
        "steps": [],
        "usage": {},
    }
    result = TaskResult.from_dict(old_payload)
    assert result.hook_firings == []
    assert result.command is None


def test_task_result_full_round_trip_with_hooks_and_command() -> None:
    """Full round-trip: existing fields + new fields serialize/deserialize to equal object."""
    result = TaskResult(
        task_id="full1",
        status=OK,
        summary="full test",
        changed_files=["f.py"],
        steps=[Step(index=0, tool="read_file", arguments={"path": "f.py"}, result="ok")],
        usage=Usage(prompt_tokens=3, completion_tokens=1, total_tokens=4),
        branch="convertible/full1",
        hook_firings=[
            HookFiring(
                event="pre_tool",
                tool="read_file",
                command="pre-hook.sh",
                decision="allow",
                exit_code=0,
                reason="",
            )
        ],
        command="review",
    )
    reloaded = TaskResult.from_dict(json.loads(json.dumps(result.to_dict())))
    assert reloaded == result
