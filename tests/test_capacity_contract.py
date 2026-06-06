"""Contract tests for the #156 capacity fields on TaskResult.

The capacity-standard feature records one declared fill-line move
(``capacity_decision``) and an optional warn-only cross-repo warning
(``capacity_warning``) on :class:`~colleague.contract.TaskResult`. Both follow the
established destination/announcement omit-when-None pattern, so a work item that
never crossed the fill-line threshold serializes byte-identically to today.
"""

from __future__ import annotations

from colleague.contract import OK, CapacityDecision, TaskResult


def test_default_taskresult_omits_capacity_keys() -> None:
    """A result with no fill-line event omits BOTH keys (byte-identical default)."""
    serialized = TaskResult(task_id="x", status=OK).to_dict()
    assert "capacity_decision" not in serialized
    assert "capacity_warning" not in serialized


def test_capacity_fields_serialize_when_set() -> None:
    """When set, both keys appear and round-trip through from_dict equal."""
    result = TaskResult(
        task_id="x",
        status=OK,
        capacity_decision=CapacityDecision(kind="compact", reason="prompt 200k >= 80% of 250k"),
        capacity_warning="assignment exceeds split capacity — split across repos/instances",
    )
    serialized = result.to_dict()
    assert serialized["capacity_decision"] == {
        "kind": "compact",
        "reason": "prompt 200k >= 80% of 250k",
    }
    assert serialized["capacity_warning"].startswith("assignment exceeds split capacity")

    restored = TaskResult.from_dict(serialized)
    assert restored.capacity_decision == result.capacity_decision
    assert restored.capacity_warning == result.capacity_warning


def test_capacity_decision_roundtrip() -> None:
    """CapacityDecision.to_dict / from_dict round-trip every move kind."""
    for kind in ("compact", "split", "finish-with-handoff"):
        d = CapacityDecision(kind=kind, reason="r")
        assert CapacityDecision.from_dict(d.to_dict()) == d
