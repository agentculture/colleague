"""Unit pins for the token-streaming livecheck classifier (feels-alive t9).

The classifier grades wall-clock evidence only — a fabricated pass on an
unreachable rig, or on an armed stream that never produced deltas, is exactly
the dishonesty the livecheck contract forbids.
"""

from __future__ import annotations

from colleague.livecheck import classify_streaming_check


def test_error_skips_honestly_never_passes() -> None:
    status, detail = classify_streaming_check(None, None, 0, error="rig unreachable: refused")
    assert status == "skipped"
    assert "rig unreachable" in detail


def test_zero_deltas_from_an_armed_stream_fails() -> None:
    status, detail = classify_streaming_check(None, 10.0, 0)
    assert status == "failed"
    assert "no deltas" in detail


def test_a_single_terminal_burst_is_not_a_stream() -> None:
    status, detail = classify_streaming_check(9.8, 10.0, 1)
    assert status == "failed"
    assert "terminal burst" in detail


def test_first_delta_within_target_passes() -> None:
    status, detail = classify_streaming_check(1.2, 13.6, 40)
    assert status == "passed"
    assert "1.20s" in detail and "13.60s" in detail


def test_first_delta_late_but_inside_half_the_turn_passes() -> None:
    # A slow prefill on a long turn still counts as streaming: 4s into a 20s turn.
    status, _ = classify_streaming_check(4.0, 20.0, 15)
    assert status == "passed"


def test_first_delta_arriving_late_fails_with_the_numbers() -> None:
    # 70% into the turn: late enough to fail, below the 90% terminal-burst
    # signature that would attribute it to rig-side buffering instead.
    status, detail = classify_streaming_check(7.0, 10.0, 3)
    assert status == "failed"
    assert "7.00s" in detail and "10.00s" in detail


def test_total_missing_is_never_graded_as_a_pass() -> None:
    status, _ = classify_streaming_check(1.0, None, 5)
    assert status == "failed"


def test_terminal_burst_with_many_deltas_skips_as_rig_side_buffering() -> None:
    # 220 deltas all landing at the very end of a 33.6s turn (the live
    # 2026-07-10 signature through the buffering lobes gateway): the server
    # streamed, an intermediary batched — rig-side, so SKIP, never FAIL.
    status, detail = classify_streaming_check(33.60, 33.60, 220)
    assert status == "skipped"
    assert "terminal burst" in detail and "rig-side" in detail


def test_late_but_not_terminal_first_delta_still_fails() -> None:
    # 80% into the turn is late (a real colleague-side lag would look like
    # this) — only the >=90% terminal-burst signature is rig-attributed.
    status, _ = classify_streaming_check(8.0, 10.0, 30)
    assert status == "failed"
