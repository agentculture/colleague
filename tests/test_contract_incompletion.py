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


# --- Robustness on malformed artifacts (#314 Qodo): degrade, never crash ---


def test_incompletion_record_from_non_dict_is_empty():
    """A non-dict payload (string/list/number) yields an all-empty record, never a crash."""
    for bad in ("just a string", ["a", "b"], 42, True):
        rec = IncompletionRecord.from_dict(bad)
        assert rec == IncompletionRecord("", "", "")


def test_incompletion_record_null_fields_coerce_to_empty():
    """An explicit null field coerces to '' — never the string 'None'."""
    rec = IncompletionRecord.from_dict({"reason": None, "evidence": None, "recommendation": None})
    assert rec == IncompletionRecord("", "", "")


def test_task_result_from_dict_ignores_non_dict_incompletion():
    """A malformed 'incompletion' (non-dict truthy) is ignored, not fatal to reload."""
    for bad in ("oops", ["x"], 7):
        d = {"task_id": "t", "status": "incomplete", "summary": "s", "incompletion": bad}
        restored = TaskResult.from_dict(d)  # must not raise
        assert restored.incompletion is None
