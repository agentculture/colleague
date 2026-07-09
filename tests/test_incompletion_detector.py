"""Tests for colleague.incompletion — the incompletion classifier."""

from colleague.contract import IncompletionRecord
from colleague.incompletion import (
    _REASON_ADVICE,
    _is_meta,
    classify_incompletion,
)


# --- write_intent=True, 0 changes -> write-no-changes ---
def test_write_no_changes() -> None:
    result = classify_incompletion(
        outcome="finished",
        write_intent=True,
        changed_files=0,
        summary="no files changed",
        step_count=5,
    )
    assert result is not None
    assert result.reason == "write-no-changes"
    assert result.recommendation  # non-empty


# --- write_intent=True, 1 change -> None (absence != incorrectness) ---
def test_write_with_change_is_deliverable() -> None:
    result = classify_incompletion(
        outcome="finished",
        write_intent=True,
        changed_files=1,
        summary="still broken",
        step_count=3,
    )
    assert result is None


# --- write_intent=False, real multi-sentence summary -> None ---
def test_read_only_real_summary_is_deliverable() -> None:
    result = classify_incompletion(
        outcome="finished",
        write_intent=False,
        changed_files=0,
        summary=(
            "The codebase uses pytest with parallel execution. "
            "Coverage is gated at 80%. No blockers found."
        ),
        step_count=4,
    )
    assert result is None


# --- write_intent=False, empty summary -> empty-deliverable ---
def test_read_only_empty_summary() -> None:
    result = classify_incompletion(
        outcome="finished",
        write_intent=False,
        changed_files=0,
        summary="",
        step_count=3,
    )
    assert result is not None
    assert result.reason == "empty-deliverable"


# --- write_intent=False, meta summary -> not None ---
def test_read_only_meta_summary() -> None:
    result = classify_incompletion(
        outcome="finished",
        write_intent=False,
        changed_files=0,
        summary="I have read the files. Need to continue implementation.",
        step_count=2,
    )
    assert result is not None


# --- step_count == 0 -> no-progress-zero-steps (highest priority) ---
def test_zero_steps() -> None:
    result = classify_incompletion(
        outcome="finished",
        write_intent=True,
        changed_files=0,
        summary="",
        step_count=0,
    )
    assert result is not None
    assert result.reason == "no-progress-zero-steps"


# --- budget outcome -> budget-exhausted (when step_count > 0) ---
def test_budget_exhausted() -> None:
    result = classify_incompletion(
        outcome="budget",
        write_intent=True,
        changed_files=0,
        summary="",
        step_count=10,
    )
    assert result is not None
    assert result.reason == "budget-exhausted"


# --- every _REASON_ADVICE key maps to a non-empty string ---
def test_reason_advice_coverage() -> None:
    for reason, advice in _REASON_ADVICE.items():
        assert reason, "reason key must be non-empty"
        assert advice, f"advice for {reason!r} must be non-empty"


# --- _is_meta helpers ---
def test_is_meta_positive() -> None:
    for marker in (
        "need to continue",
        "remaining work",
        "i have read",
        "i will ",
        "next i ",
        "to be implemented",
        "not yet implemented",
        "need to implement",
    ):
        assert _is_meta(marker), f"_is_meta should catch: {marker!r}"


def test_is_meta_case_insensitive() -> None:
    assert _is_meta("I HAVE READ the files")
    assert _is_meta("Need To Continue")


def test_is_meta_negative() -> None:
    assert not _is_meta("The implementation is complete.")
    assert not _is_meta("All tests pass.")
    assert not _is_meta("")


# --- NO_RESULT_PRODUCED sentinel is not a deliverable ---
def test_no_result_produced_sentinel() -> None:
    from colleague.contract import NO_RESULT_PRODUCED

    result = classify_incompletion(
        outcome="finished",
        write_intent=False,
        changed_files=0,
        summary=NO_RESULT_PRODUCED,
        step_count=1,
    )
    assert result is not None
    assert result.reason == "empty-deliverable"


# --- IncompletionRecord round-trips ---
def test_incompletion_record_roundtrip() -> None:
    rec = IncompletionRecord(
        reason="write-no-changes",
        evidence="finished outcome='finished' with 0 changed file(s) over 5 step(s)",
        recommendation="re-scope or take over: colleague finished without changing any files.",
    )
    d = rec.to_dict()
    rec2 = IncompletionRecord.from_dict(d)
    assert rec.reason == rec2.reason
    assert rec.evidence == rec2.evidence
    assert rec.recommendation == rec2.recommendation
