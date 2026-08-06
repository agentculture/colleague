"""Tests for colleague.finishstate — the finish-state classifier (plan task
t1, covers c4/h4, decision c30).

Acceptance criterion 2: truncated / stopped / timeout / empty / deliberate
are distinguishable states with tests; the ``NO_RESULT_PRODUCED`` sentinel
must never register as ``deliberate``/completed.
"""

from __future__ import annotations

from colleague.contract import (
    FINISH_DELIBERATE,
    FINISH_EMPTY,
    FINISH_STATES,
    FINISH_STOPPED,
    FINISH_TIMEOUT,
    FINISH_TRUNCATED,
    NO_RESULT_PRODUCED,
)
from colleague.finishstate import classify_finish_state

# ---------------------------------------------------------------------------
# The five states are distinguishable — one dedicated test each.
# ---------------------------------------------------------------------------


def test_five_states_are_distinct_strings() -> None:
    assert len(FINISH_STATES) == 5
    assert len(set(FINISH_STATES)) == 5  # no accidental collisions


def test_clean_finish_with_a_real_summary_is_deliberate() -> None:
    state = classify_finish_state(summary="did the thing", finish_reason="stop", outcome="finished")
    assert state == FINISH_DELIBERATE


def test_no_tool_call_stop_with_real_content_is_also_deliberate() -> None:
    """The loop's OWN "stopped" exit reason (a no-tool-call turn that answered
    in prose, then ran out of nudges) is the model's own decision to stop —
    classified deliberate, NOT the FINISH_STOPPED state (which is reserved for
    an EXTERNAL stop). The two vocabularies both spell "stopped" but mean
    different things; this test locks in the (deliberately) non-obvious
    mapping."""
    state = classify_finish_state(summary="here is my answer", outcome="stopped")
    assert state == FINISH_DELIBERATE


def test_wire_length_finish_reason_is_truncated() -> None:
    state = classify_finish_state(
        summary="partial answer", finish_reason="length", outcome="finished"
    )
    assert state == FINISH_TRUNCATED


def test_budget_exhaustion_is_truncated_even_with_no_wire_finish_reason() -> None:
    """The loop's own step-budget ceiling is a resource cutoff exactly like a
    token-length cap — grouped into the same TRUNCATED bucket even when the
    backend never reported a raw finish_reason (e.g. the mock engine, or a
    backend the loop budget-capped before its own turn's finish_reason would
    have mattered)."""
    state = classify_finish_state(summary="still working", finish_reason="", outcome="budget")
    assert state == FINISH_TRUNCATED


def test_pilot_stop_is_stopped() -> None:
    state = classify_finish_state(
        summary="Stopped by pilot after 3 step(s) (partial).", outcome="pilot_stop"
    )
    assert state == FINISH_STOPPED


def test_tool_protocol_break_is_stopped() -> None:
    state = classify_finish_state(
        summary="Stopped after 3 step(s): the tool-call channel is broken", outcome="tool_protocol"
    )
    assert state == FINISH_STOPPED


def test_timed_out_is_timeout_regardless_of_other_signals() -> None:
    state = classify_finish_state(
        summary="", finish_reason="length", outcome="budget", timed_out=True
    )
    assert state == FINISH_TIMEOUT


def test_no_result_produced_sentinel_is_empty() -> None:
    state = classify_finish_state(summary=NO_RESULT_PRODUCED, outcome="stopped")
    assert state == FINISH_EMPTY


def test_non_timeout_abort_is_empty() -> None:
    """An engine-level abort that is NOT a timeout (e.g. an unexpected engine
    exception, or a context-overflow degradation give-up at the floor) — the
    result.summary on this path is a diagnostic fallback note, never a real
    deliverable, so this maps to EMPTY exactly like the sentinel does."""
    state = classify_finish_state(
        summary="aborted after 4 step(s): RuntimeError: engine exploded", aborted=True
    )
    assert state == FINISH_EMPTY


# ---------------------------------------------------------------------------
# The core acceptance-criterion invariant: NO_RESULT_PRODUCED never registers
# as deliberate/completed — checked against every other input combination.
# ---------------------------------------------------------------------------


def test_sentinel_never_registers_as_deliberate_no_matter_the_outcome() -> None:
    for outcome in ("finished", "stopped", "budget", "pilot_stop", "tool_protocol", ""):
        for finish_reason in ("stop", "tool_calls", "length", ""):
            state = classify_finish_state(
                summary=NO_RESULT_PRODUCED, finish_reason=finish_reason, outcome=outcome
            )
            assert state != FINISH_DELIBERATE
            assert state == FINISH_EMPTY


# ---------------------------------------------------------------------------
# Precedence — documented and locked in by test.
# ---------------------------------------------------------------------------


def test_timeout_wins_over_empty() -> None:
    state = classify_finish_state(summary=NO_RESULT_PRODUCED, timed_out=True)
    assert state == FINISH_TIMEOUT


def test_empty_wins_over_stopped_and_truncated() -> None:
    """Even when the loop's outcome says "pilot_stop" or "budget", a summary
    that IS the sentinel reports EMPTY — "nothing was produced" is the more
    load-bearing fact for a caller than "why it ended"."""
    assert classify_finish_state(summary=NO_RESULT_PRODUCED, outcome="pilot_stop") == FINISH_EMPTY
    assert classify_finish_state(summary=NO_RESULT_PRODUCED, outcome="budget") == FINISH_EMPTY


def test_aborted_wins_over_a_stale_budget_outcome() -> None:
    """On the aborted path the loop's own `outcome` local variable is stale
    (``_work_loop`` never returned, so it still holds its pre-loop default,
    "budget") — ``aborted=True`` must short-circuit BEFORE that stale outcome
    is ever consulted, or a generic engine crash would be misreported as
    TRUNCATED instead of the honest EMPTY (nothing was delivered)."""
    state = classify_finish_state(
        summary="aborted after 0 step(s): boom", outcome="budget", aborted=True
    )
    assert state == FINISH_EMPTY


def test_truncated_beats_deliberate_default() -> None:
    assert classify_finish_state(summary="ok", finish_reason="length") == FINISH_TRUNCATED
