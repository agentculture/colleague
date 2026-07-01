"""Backpressure classification helpers (#254, R2): pure, leaf-level (colleague#5.t5).

These helpers classify a ROLLING mean of recent per-turn wall-clock latencies
against fractions of the request timeout into one of three states — CLEAR,
ARMED, ESCALATED — and turn that state into two recommended tightenings (a
context-window shrink fraction, a throttled concurrency cap). No clock, no
threads, no I/O: the caller (`colleague/loop.py`, in a later task) supplies
the latency series and interprets the state; this module owns only the maths.
"""

from __future__ import annotations

from colleague import backpressure

# ---------------------------------------------------------------------------
# assess()
# ---------------------------------------------------------------------------


def test_assess_all_fast_is_clear() -> None:
    latencies = [1.0, 1.0, 1.0]
    assert backpressure.assess(latencies, timeout=100.0) == backpressure.CLEAR


def test_assess_drifting_past_arm_threshold_is_armed() -> None:
    # arm_fraction default 0.5 -> arm threshold = 50.0; mean of last 3 = 60.0
    latencies = [10.0, 60.0, 60.0, 60.0]
    assert backpressure.assess(latencies, timeout=100.0) == backpressure.ARMED


def test_assess_past_escalate_threshold_is_escalated() -> None:
    # escalate_fraction default 0.75 -> escalate threshold = 75.0; mean of last 3 = 90.0
    latencies = [10.0, 90.0, 90.0, 90.0]
    assert backpressure.assess(latencies, timeout=100.0) == backpressure.ESCALATED


def test_assess_recovery_back_to_clear() -> None:
    # A run that escalated but has since recovered: only the last `window` samples
    # matter, so old escalated samples must not linger once they roll off.
    latencies = [95.0, 95.0, 95.0, 5.0, 5.0, 5.0]
    assert backpressure.assess(latencies, timeout=100.0) == backpressure.CLEAR


def test_assess_window_ignores_older_samples() -> None:
    # window=3: only the last 3 samples are averaged, regardless of history length.
    latencies = [95.0, 95.0, 95.0, 95.0, 95.0, 1.0, 1.0, 1.0]
    assert backpressure.assess(latencies, timeout=100.0, window=3) == backpressure.CLEAR
    # A smaller window that still captures a hot sample stays escalated.
    latencies2 = [1.0, 1.0, 95.0]
    assert backpressure.assess(latencies2, timeout=100.0, window=1) == backpressure.ESCALATED


def test_assess_exact_threshold_boundaries() -> None:
    # At exactly the arm fraction: armed (>=), not clear.
    assert backpressure.assess([50.0, 50.0, 50.0], timeout=100.0) == backpressure.ARMED
    # Just under the arm fraction: clear.
    assert backpressure.assess([49.9, 49.9, 49.9], timeout=100.0) == backpressure.CLEAR
    # At exactly the escalate fraction: escalated.
    assert backpressure.assess([75.0, 75.0, 75.0], timeout=100.0) == backpressure.ESCALATED
    # Just under the escalate fraction: armed, not escalated.
    assert backpressure.assess([74.9, 74.9, 74.9], timeout=100.0) == backpressure.ARMED


def test_assess_custom_fractions() -> None:
    latencies = [30.0, 30.0, 30.0]
    # arm threshold 20, escalate threshold 25 -> mean 30 is past both -> escalated.
    assert (
        backpressure.assess(latencies, timeout=100.0, arm_fraction=0.2, escalate_fraction=0.25)
        == backpressure.ESCALATED
    )
    # arm threshold 40, escalate threshold 60 -> mean 30 is under both -> clear.
    assert (
        backpressure.assess(latencies, timeout=100.0, arm_fraction=0.4, escalate_fraction=0.6)
        == backpressure.CLEAR
    )


# ---------------------------------------------------------------------------
# Degenerate inputs
# ---------------------------------------------------------------------------


def test_assess_empty_latencies_is_clear() -> None:
    assert backpressure.assess([], timeout=100.0) == backpressure.CLEAR


def test_assess_short_input_uses_what_is_there() -> None:
    # Fewer samples than `window`: use what's there rather than erroring or padding.
    assert backpressure.assess([95.0], timeout=100.0) == backpressure.ESCALATED
    assert backpressure.assess([5.0], timeout=100.0) == backpressure.CLEAR


def test_assess_zero_timeout_is_clear_never_raises() -> None:
    assert backpressure.assess([50.0, 50.0, 50.0], timeout=0.0) == backpressure.CLEAR


def test_assess_negative_timeout_is_clear_never_raises() -> None:
    assert backpressure.assess([50.0, 50.0, 50.0], timeout=-5.0) == backpressure.CLEAR


def test_assess_window_of_one() -> None:
    assert backpressure.assess([5.0, 5.0, 95.0], timeout=100.0, window=1) == (
        backpressure.ESCALATED
    )


# ---------------------------------------------------------------------------
# shrink_fraction()
# ---------------------------------------------------------------------------


def test_shrink_fraction_table() -> None:
    assert backpressure.shrink_fraction(backpressure.CLEAR) == 1.0
    assert backpressure.shrink_fraction(backpressure.ARMED) == 0.75
    assert backpressure.shrink_fraction(backpressure.ESCALATED) == 0.5


def test_shrink_fraction_unknown_state_is_clear_identity() -> None:
    assert backpressure.shrink_fraction("bogus") == 1.0


# ---------------------------------------------------------------------------
# throttled_concurrency()
# ---------------------------------------------------------------------------


def test_throttled_concurrency_clear_is_unchanged() -> None:
    assert backpressure.throttled_concurrency(backpressure.CLEAR, 4) == 4
    assert backpressure.throttled_concurrency(backpressure.CLEAR, 1) == 1


def test_throttled_concurrency_armed_drops_by_one_floored_at_one() -> None:
    assert backpressure.throttled_concurrency(backpressure.ARMED, 4) == 3
    assert backpressure.throttled_concurrency(backpressure.ARMED, 1) == 1


def test_throttled_concurrency_escalated_is_always_one() -> None:
    assert backpressure.throttled_concurrency(backpressure.ESCALATED, 4) == 1
    assert backpressure.throttled_concurrency(backpressure.ESCALATED, 1) == 1


def test_throttled_concurrency_degenerate_configured_floors_at_one() -> None:
    # A non-positive configured concurrency is degenerate (no caller ever configures
    # zero/negative fan-out); guard it to the same floor as any other state, never a
    # <1 result and never a crash.
    assert backpressure.throttled_concurrency(backpressure.CLEAR, 0) == 1
    assert backpressure.throttled_concurrency(backpressure.ESCALATED, 0) == 1
    assert backpressure.throttled_concurrency(backpressure.ARMED, -3) == 1


def test_throttled_concurrency_unknown_state_is_clear_identity() -> None:
    assert backpressure.throttled_concurrency("bogus", 4) == 4
