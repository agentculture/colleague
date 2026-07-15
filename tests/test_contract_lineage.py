"""``TaskResult.continued_from`` lineage (#167) — omit-when-None, round-trips.

A continued run records the prior work item's task id; an ordinary run's
artifact stays byte-identical (no ``continued_from`` key at all).
"""

from __future__ import annotations

from colleague.contract import OK, TaskResult


def test_default_is_none_and_key_omitted() -> None:
    result = TaskResult(task_id="abc", status=OK, summary="done")
    assert result.continued_from is None
    assert "continued_from" not in result.to_dict()


def test_populated_field_serializes() -> None:
    result = TaskResult(task_id="new1", status=OK, summary="done", continued_from="old0")
    assert result.to_dict()["continued_from"] == "old0"


def test_round_trip() -> None:
    original = TaskResult(task_id="new1", status=OK, summary="done", continued_from="old0")
    restored = TaskResult.from_dict(original.to_dict())
    assert restored.continued_from == "old0"


def test_round_trip_absent_key_stays_none() -> None:
    original = TaskResult(task_id="abc", status=OK, summary="done")
    restored = TaskResult.from_dict(original.to_dict())
    assert restored.continued_from is None


def test_explicit_null_reads_as_none() -> None:
    data = TaskResult(task_id="abc", status=OK, summary="done").to_dict()
    data["continued_from"] = None
    assert TaskResult.from_dict(data).continued_from is None
