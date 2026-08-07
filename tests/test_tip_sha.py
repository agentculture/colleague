"""TaskResult.tip_sha: the handoff's branch tip commit SHA (plan task t5, covers c5).

Omit-when-None, mirroring the ``mode``/``destination``/``config_digest`` precedent
in ``tests/test_contract.py``: a run whose handoff produced no commit serializes
byte-identically to the pre-``tip_sha`` artifact shape (no extra key). The handoff
itself (``colleague/handoff.py``) populates the field — covered in
``tests/test_handoff.py`` (unit-level) and ``tests/test_drive.py`` (the e2e mock
CLI flow).
"""

from __future__ import annotations

import json

from colleague.contract import OK, TaskResult


def test_tip_sha_present_when_set() -> None:
    """to_dict() carries 'tip_sha' when it was set on the result."""
    result = TaskResult(
        task_id="tip1",
        status=OK,
        summary="did work",
        tip_sha="a" * 40,
    )
    serialized = result.to_dict()
    assert serialized["tip_sha"] == "a" * 40


def test_tip_sha_omitted_when_none() -> None:
    """to_dict() OMITS 'tip_sha' when it is None — the byte-identical guard: a run
    whose handoff produced no commit must produce the exact same key set as before
    this field existed.
    """
    result = TaskResult(task_id="notip1", status=OK, summary="plain drive")
    serialized = result.to_dict()
    assert "tip_sha" not in serialized
    # Strongest form: assert the exact key set matches the pre-tip_sha contract.
    expected_keys = {
        "task_id",
        "status",
        "summary",
        "changed_files",
        "steps",
        "usage",
        "stats",
        "finish_states",
        "artifacts_path",
        "error",
        "branch",
        "pr_url",
        "hook_firings",
        "command",
        "not_finished",
        "stopped_without_finish",
    }
    assert set(serialized.keys()) == expected_keys


def test_tip_sha_round_trips_through_json() -> None:
    """TaskResult with tip_sha set round-trips through to_dict/json/from_dict unchanged."""
    result = TaskResult(
        task_id="tip2",
        status=OK,
        summary="landed a commit",
        branch="colleague/tip2",
        tip_sha="0123456789abcdef0123456789abcdef01234567",
    )
    reloaded = TaskResult.from_dict(json.loads(json.dumps(result.to_dict())))
    assert reloaded == result
    assert reloaded.tip_sha == "0123456789abcdef0123456789abcdef01234567"


def test_from_dict_tolerates_missing_tip_sha() -> None:
    """from_dict defaults tip_sha to None when absent — a legacy artifact (written
    before this field existed) loads unchanged."""
    legacy_payload = {
        "task_id": "legacy-tip1",
        "status": OK,
        "summary": "",
        "changed_files": [],
        "steps": [],
        "usage": {},
        "branch": "colleague/legacy-tip1",
        "pr_url": None,
    }
    result = TaskResult.from_dict(legacy_payload)
    assert result.tip_sha is None


def test_from_dict_reads_tip_sha_when_present() -> None:
    """from_dict correctly reads the tip_sha key when it exists in the dict."""
    payload = {
        "task_id": "tip3",
        "status": OK,
        "summary": "committed",
        "changed_files": [],
        "steps": [],
        "usage": {},
        "tip_sha": "deadbeef" * 5,
    }
    result = TaskResult.from_dict(payload)
    assert result.tip_sha == "deadbeef" * 5
