"""Task t11 — stale-pin refresh warnings land in the run artifact.

A TaskResult with warnings round-trips through artifact write + read preserving
the dicts; a TaskResult without warnings still reads back (back-compat: an
artifact JSON written before this field loads with warnings == []).
"""

import json
from pathlib import Path

from colleague.artifact import read_artifact, write
from colleague.contract import TaskResult


def _make_result(warnings=None):
    """Build a minimal TaskResult for artifact round-trip tests."""
    return TaskResult(
        task_id="t11-test",
        status="ok",
        summary="test",
        warnings=warnings or [],
    )


def test_warnings_roundtrip_preserves_dicts(tmp_path: Path):
    """A TaskResult with warnings writes and reads back with the same dicts."""
    warnings = [
        {
            "role": "cortex",
            "stale_id": "old-model-1",
            "source": "flag",
            "refreshed_id": "new-model-1",
            "point": "resolution",
        },
        {
            "role": "worker",
            "stale_id": "old-model-2",
            "source": "config.json",
            "refreshed_id": "new-model-2",
            "point": "call",
        },
    ]
    result = _make_result(warnings=warnings)
    artifact_dir = tmp_path / ".colleague"
    artifact_dir.mkdir()

    path = write(result, artifact_dir)
    # Verify the JSON on disk contains the warnings key
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert "warnings" in raw
    assert raw["warnings"] == warnings

    # Read back via read_artifact
    read = read_artifact(tmp_path, "t11-test")
    assert read is not None
    assert read.warnings == warnings


def test_no_warnings_roundtrip_empty_list(tmp_path: Path):
    """A TaskResult with no warnings round-trips with warnings == []."""
    result = _make_result()
    artifact_dir = tmp_path / ".colleague"
    artifact_dir.mkdir()

    path = write(result, artifact_dir)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert "warnings" not in raw  # omit-when-empty: pre-feature byte-identity
    read = read_artifact(tmp_path, "t11-test")
    assert read is not None
    assert read.warnings == []


def test_back_compat_artifact_without_warnings_key(tmp_path: Path):
    """An artifact JSON written before the warnings field still loads."""
    artifact_dir = tmp_path / ".colleague"
    artifact_dir.mkdir()

    # Simulate a pre-warnings artifact (no "warnings" key)
    old_json = {
        "task_id": "legacy-task",
        "status": "ok",
        "summary": "old run",
        "changed_files": [],
        "steps": [],
        "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        "stats": {
            "request": "old",
            "step_count": 0,
            "tool_calls": 0,
            "bytes_produced": 0,
            "chars_produced": 0,
            "wall_seconds": 0.0,
        },
        "finish_states": [],
    }
    artifact_file = artifact_dir / "legacy-task.json"
    artifact_file.write_text(json.dumps(old_json, indent=2) + "\n")

    read = read_artifact(tmp_path, "legacy-task")
    assert read is not None
    assert read.warnings == []
