"""Task.attachments — optional media attachments on the task contract (task t1).

Mirrors the existing ``goal``/``acceptance`` omit-when-None pattern on
``colleague.contract.Task`` exactly: default ``None``, a ``Task.new`` keyword,
``to_dict`` omits the key when ``None``, and ``from_dict`` tolerates absence
and degrades malformed shapes to ``None`` rather than raising.
"""

from __future__ import annotations

import json

from colleague.contract import Task

# ---------------------------------------------------------------------------
# (1) Byte-identical when attachments is not set
# ---------------------------------------------------------------------------


def test_task_new_without_attachments_is_byte_identical() -> None:
    """A Task authored without attachments serializes with the pre-t1 key set."""
    task = Task.new("/repo", "add a README", engine="mock")

    assert task.attachments is None

    serialized = task.to_dict()
    assert "attachments" not in serialized

    expected_keys = {"id", "repo_path", "instruction", "context", "constraints", "engine"}
    assert set(serialized.keys()) == expected_keys


def test_task_round_trips_without_attachments() -> None:
    task = Task.new("/repo", "add a README", engine="mock")
    reloaded = Task.from_dict(json.loads(json.dumps(task.to_dict())))
    assert reloaded == task
    assert reloaded.attachments is None


# ---------------------------------------------------------------------------
# (2) Round-trip with attachments
# ---------------------------------------------------------------------------


def test_task_new_with_attachments_carries_them() -> None:
    task = Task.new(
        "/repo",
        "describe this image",
        engine="mock",
        attachments=[{"path": "a.png", "media_type": "image/png"}],
    )

    assert task.attachments == [{"path": "a.png", "media_type": "image/png"}]

    serialized = task.to_dict()
    assert serialized["attachments"] == [{"path": "a.png", "media_type": "image/png"}]


def test_task_attachments_round_trip_through_json() -> None:
    task = Task.new(
        "/repo",
        "describe this image",
        engine="vllm-openai",
        attachments=[{"path": "a.png", "media_type": "image/png"}],
    )
    reloaded = Task.from_dict(json.loads(json.dumps(task.to_dict())))
    assert reloaded == task
    assert reloaded.attachments == [{"path": "a.png", "media_type": "image/png"}]


def test_task_attachments_round_trip_multiple_entries() -> None:
    entries = [
        {"path": "a.png", "media_type": "image/png"},
        {"path": "b.wav", "media_type": "audio/wav"},
    ]
    task = Task.new("/repo", "describe these files", attachments=entries)
    reloaded = Task.from_dict(json.loads(json.dumps(task.to_dict())))
    assert reloaded == task
    assert reloaded.attachments == entries


def test_task_from_dict_reads_attachments_when_present() -> None:
    payload = {
        "id": "def456",
        "repo_path": "/repo",
        "instruction": "do work",
        "context": "",
        "constraints": [],
        "engine": "mock",
        "attachments": [{"path": "a.png", "media_type": "image/png"}],
    }
    task = Task.from_dict(payload)
    assert task.attachments == [{"path": "a.png", "media_type": "image/png"}]


def test_task_from_dict_tolerates_missing_attachments() -> None:
    """from_dict defaults attachments to None when absent (back-compat with today's tasks)."""
    old_payload = {
        "id": "abc123",
        "repo_path": "/repo",
        "instruction": "do work",
        "context": "",
        "constraints": [],
        "engine": "mock",
    }
    task = Task.from_dict(old_payload)
    assert task.attachments is None


# ---------------------------------------------------------------------------
# (3) Malformed payloads degrade to None, never raise
# ---------------------------------------------------------------------------


def test_from_dict_string_attachments_degrades_to_none() -> None:
    """A bare-string payload must not explode into per-character entries."""
    base = Task.new("/tmp/x", "do x").to_dict()
    base["attachments"] = "a.png"
    assert Task.from_dict(base).attachments is None


def test_from_dict_dict_attachments_degrades_to_none() -> None:
    """A bare dict (not wrapped in a list) is not a valid attachments payload."""
    base = Task.new("/tmp/x", "do x").to_dict()
    base["attachments"] = {"path": "a.png", "media_type": "image/png"}
    assert Task.from_dict(base).attachments is None


def test_from_dict_list_with_non_dict_entries_degrades_to_none() -> None:
    """A list containing a non-dict entry is malformed as a whole, not partially dropped."""
    base = Task.new("/tmp/x", "do x").to_dict()
    base["attachments"] = [{"path": "a.png", "media_type": "image/png"}, "oops"]
    assert Task.from_dict(base).attachments is None


def test_from_dict_list_attachments_coerces_entry_values_to_str() -> None:
    base = Task.new("/tmp/x", "do x").to_dict()
    base["attachments"] = [{"path": 123, "media_type": 456}]
    assert Task.from_dict(base).attachments == [{"path": "123", "media_type": "456"}]


def test_from_dict_empty_list_attachments_is_empty_not_none() -> None:
    """An explicit empty list is distinct from the key being absent entirely."""
    base = Task.new("/tmp/x", "do x").to_dict()
    base["attachments"] = []
    result = Task.from_dict(base)
    assert result.attachments == []
    assert result.attachments is not None
