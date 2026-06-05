"""Result artifact + trace: always-written, valid JSON, error survives (R5, h5)."""

from __future__ import annotations

import json
from pathlib import Path

from colleague.artifact import failed_result, find_artifact, read_request, write
from colleague.contract import ERROR, OK, HookFiring, Step, Task, TaskResult, Usage, WorkStats
from colleague.loop import ModelResponse, ToolCall, run


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
    path = write(_result_with_steps(tmp_path), tmp_path / ".colleague")
    payload = json.loads(path.read_text())
    for key in ("status", "changed_files", "steps", "usage"):
        assert key in payload
    assert payload["status"] == OK
    assert payload["changed_files"] == ["a.txt"]


def test_write_sets_artifacts_path(tmp_path: Path) -> None:
    result = TaskResult(task_id="t2", status=OK)
    path = write(result, tmp_path / "conv-test-artifact")
    assert result.artifacts_path == str(path)


# ---------------------------------------------------------------------------
# #132: request-slugged artifact filenames + back-compat readers
# ---------------------------------------------------------------------------


def test_write_slugs_filename_from_request(tmp_path: Path) -> None:
    """A drive with a request is named <task_id>.<slug>.json (+ .trace.jsonl)."""
    out = tmp_path / ".colleague"
    result = TaskResult(
        task_id="abc123",
        status=OK,
        summary="x",
        steps=[Step(0, "finish", {}, "done")],
        stats=WorkStats(request="Add a Hello Function!"),
    )
    path = write(result, out)
    assert path.name == "abc123.add-a-hello-function.json"
    assert result.artifacts_path == str(path)  # the slugged path is authoritative
    assert (out / "abc123.add-a-hello-function.trace.jsonl").is_file()


def test_write_falls_back_to_bare_name_when_no_request(tmp_path: Path) -> None:
    """No request (or all-punctuation) → bare <task_id>.json (always a valid name)."""
    out = tmp_path / ".colleague"
    path = write(TaskResult(task_id="bare1", status=OK, stats=WorkStats(request="")), out)
    assert path.name == "bare1.json"


def test_find_artifact_resolves_bare_and_slugged(tmp_path: Path) -> None:
    out = tmp_path / ".colleague"
    write(TaskResult(task_id="slug1", status=OK, stats=WorkStats(request="refactor parser")), out)
    write(TaskResult(task_id="bare2", status=OK, stats=WorkStats(request="")), out)
    assert find_artifact(tmp_path, "slug1").name == "slug1.refactor-parser.json"
    assert find_artifact(tmp_path, "bare2").name == "bare2.json"
    assert find_artifact(tmp_path, "missing") is None


def test_find_artifact_ignores_feedback_file_and_unsafe_id(tmp_path: Path) -> None:
    out = tmp_path / ".colleague"
    out.mkdir()
    # A lone feedback record must never be mistaken for the drive's artifact.
    (out / "ghost.feedback.json").write_text("{}\n", encoding="utf-8")
    assert find_artifact(tmp_path, "ghost") is None
    # A traversal id is refused outright.
    assert find_artifact(tmp_path, "../escape") is None


def test_read_request_returns_recorded_request(tmp_path: Path) -> None:
    write(
        TaskResult(task_id="r1", status=OK, stats=WorkStats(request="do the thing")),
        tmp_path / ".colleague",
    )
    assert read_request(tmp_path, "r1") == "do the thing"
    assert read_request(tmp_path, "nope") is None


def test_failed_run_still_writes_error_artifact(tmp_path: Path) -> None:
    result = failed_result("crashed", "boom: engine raised RuntimeError")
    path = write(result, tmp_path / ".colleague")
    payload = json.loads(path.read_text())
    assert payload["status"] == ERROR
    assert "boom" in payload["error"]
    # No request → empty stats, bare filename (prior behavior, byte-identical).
    assert path.name == "crashed.json"
    assert payload["stats"]["request"] == ""


def test_failed_result_with_request_is_discoverable(tmp_path: Path) -> None:
    """An early-failure result given the request records it in stats → slugged name,
    non-empty request + a start timestamp for `feedback list` (#132 / #139 qodo)."""
    result = failed_result("crashed", "boom", request="refactor the parser")
    path = write(result, tmp_path / ".colleague")
    payload = json.loads(path.read_text())
    assert payload["status"] == ERROR
    assert payload["stats"]["request"] == "refactor the parser"
    assert payload["stats"]["started_at"]  # stamped, so list_work_items can sort it
    assert path.name == "crashed.refactor-the-parser.json"  # slugged like any drive


def test_trace_jsonl_has_one_line_per_step(tmp_path: Path) -> None:
    out = tmp_path / ".colleague"
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
    path = write(result, tmp_path / ".colleague")
    reloaded = TaskResult.from_dict(json.loads(path.read_text()))
    assert reloaded.changed_files == ["x"]


# ---------------------------------------------------------------------------
# t2: denied tool call — hook_firings + non-ok step persisted in artifact
# ---------------------------------------------------------------------------


def test_denied_tool_call_written_to_artifact(tmp_path: Path) -> None:
    """A TaskResult with a denied (ok=False) step and a deny HookFiring
    round-trips fully through artifact.write → JSON reload."""
    deny_firing = HookFiring(
        event="pre_tool",
        tool="run_command",
        command="security-check.sh",
        decision="deny",
        exit_code=1,
        reason="command blocked: rm -rf pattern",
    )
    result = TaskResult(
        task_id="denied1",
        status=ERROR,
        summary="drive blocked by hook",
        steps=[
            Step(
                index=0,
                tool="run_command",
                arguments={"command": "rm -rf /tmp"},
                result="hook denied: command blocked: rm -rf pattern",
                ok=False,
            )
        ],
        hook_firings=[deny_firing],
        command="clean",
        error="hook denied the tool call",
    )

    out_dir = tmp_path / ".colleague"
    path = write(result, out_dir)
    payload = json.loads(path.read_text())

    # --- new fields present ---
    assert "hook_firings" in payload
    assert "command" in payload
    assert payload["command"] == "clean"

    firings = payload["hook_firings"]
    assert len(firings) == 1
    f = firings[0]
    assert f["event"] == "pre_tool"
    assert f["decision"] == "deny"
    assert f["exit_code"] == 1
    assert "rm -rf pattern" in f["reason"]

    # --- non-ok step present ---
    steps = payload["steps"]
    assert len(steps) == 1
    assert steps[0]["ok"] is False
    assert "hook denied" in steps[0]["result"]

    # --- full round-trip equality ---
    reloaded = TaskResult.from_dict(payload)
    assert reloaded.hook_firings == [deny_firing]
    assert reloaded.command == "clean"
    assert reloaded.steps[0].ok is False


def test_artifact_without_new_fields_loads_with_defaults(tmp_path: Path) -> None:
    """An artifact written without hook_firings/command (old format) loads cleanly."""
    old_payload = {
        "task_id": "old1",
        "status": OK,
        "summary": "legacy result",
        "changed_files": ["README.md"],
        "steps": [],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        "artifacts_path": None,
        "error": None,
        "branch": None,
        "pr_url": None,
    }
    artifact_file = tmp_path / "old1.json"
    artifact_file.write_text(json.dumps(old_payload) + "\n", encoding="utf-8")

    reloaded = TaskResult.from_dict(json.loads(artifact_file.read_text()))
    assert reloaded.hook_firings == []
    assert reloaded.command is None
    assert reloaded.changed_files == ["README.md"]


# ---------------------------------------------------------------------------
# t3: destination / announcement keys in written artifact (omit-when-None)
# ---------------------------------------------------------------------------


def test_artifact_includes_destination_and_announcement_when_set(tmp_path: Path) -> None:
    """Writing a result with destination + announcement → both keys appear in the JSON file."""
    result = TaskResult(
        task_id="dest-art1",
        status=OK,
        summary="reached goal",
        destination="goal-frame-x",
        announcement="Arrived at goal-frame-x.",
    )
    path = write(result, tmp_path / ".colleague")
    payload = json.loads(path.read_text())
    assert "destination" in payload
    assert payload["destination"] == "goal-frame-x"
    assert "announcement" in payload
    assert payload["announcement"] == "Arrived at goal-frame-x."


def test_artifact_omits_destination_and_announcement_when_none(tmp_path: Path) -> None:
    """Writing a result with no destination → neither key appears in the JSON file.

    This preserves byte-identical output for the no-destination path (c8/h8).
    """
    result = TaskResult(task_id="nodest-art1", status=OK, summary="plain drive")
    path = write(result, tmp_path / ".colleague")
    payload = json.loads(path.read_text())
    assert "destination" not in payload
    assert "announcement" not in payload
