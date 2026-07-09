"""Round-trip tests for IncompletionRecord and TaskResult.incompletion."""

from colleague.contract import IncompletionRecord, TaskResult


def test_incompletion_record_round_trip():
    """IncompletionRecord.to_dict -> from_dict produces an equal record."""
    original = IncompletionRecord(
        reason="step budget exhausted",
        evidence="last tool call returned partial output",
        recommendation="increase step budget or split the task",
    )
    d = original.to_dict()
    restored = IncompletionRecord.from_dict(d)
    assert restored == original


def test_task_result_with_incompletion_round_trips():
    """TaskResult carrying an IncompletionRecord serializes and round-trips."""
    record = IncompletionRecord(
        reason="budget",
        evidence="hit limit",
        recommendation="split",
    )
    result = TaskResult(
        task_id="t1",
        status="success",
        summary="done",
        incompletion=record,
    )
    d = result.to_dict()
    assert "incompletion" in d
    assert d["incompletion"] == record.to_dict()

    restored = TaskResult.from_dict(d)
    assert restored.incompletion is not None
    assert restored.incompletion == record


def test_task_result_without_incompletion_omits_key():
    """TaskResult with incompletion=None produces NO 'incompletion' key."""
    result = TaskResult(
        task_id="t2",
        status="success",
        summary="done",
        incompletion=None,
    )
    d = result.to_dict()
    assert "incompletion" not in d
