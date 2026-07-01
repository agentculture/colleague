"""Pure adaptive-backpressure helpers (#254, R2: colleague's work modes plan, t5).

The loop measures per-turn wall-clock latency; when turns drift toward the
request timeout, colleague should proactively tighten — shrink the context
window it feeds the model (the #229 move) and throttle effective subagent
concurrency/fan-out — bounded and advisory-first. This module owns only the
*classification maths*: turning a rolling mean of recent turn latencies into
one of three states, and turning a state into two recommended tightenings.

Deliberately **leaf-level**: no clock, no threads, no I/O, and no import from
``colleague.loop`` or ``colleague.config`` — the loop (a later task) is the one
that will call into this module, measure real latencies, and act on the
recommendation, so this module must stay free of any dependency that would
create a cycle. Stdlib only.

Design intent, for the caller that wires this in later:

- ``assess`` classifies a *rolling* mean (the last ``window`` samples) of
  per-turn latencies against fractions of the request timeout — a caller
  passes the full latency series it has collected so far and gets back the
  state for right now.
- ``shrink_fraction`` is a recommended multiplier on the caller's own context
  budget/window size. It composes with whatever floor the caller already
  enforces (e.g. the loop's own minimum window) — this module does not know
  or enforce a floor itself, it only recommends the multiplier. The three
  constants echo the spirit of ``colleague/loop.py``'s existing
  ``_OVERFLOW_SHRINK_FACTOR`` (0.6, applied per overflow retry) without
  importing it: backpressure tightens in coarser, state-based steps instead
  of a per-retry decay.
- ``throttled_concurrency`` is a recommended cap on the caller's configured
  subagent concurrency (e.g. ``COLLEAGUE_SUBAGENT_CONCURRENCY``).

Backpressure only ever tightens toward safety: it never raises a shrink
fraction above 1.0, never raises concurrency above what was configured, and
never selects a different model or backend (not a router).
"""

from __future__ import annotations

from typing import Sequence

__all__ = [
    "CLEAR",
    "ARMED",
    "ESCALATED",
    "assess",
    "shrink_fraction",
    "throttled_concurrency",
]

# The three backpressure states, ordered from healthiest to most tightened.
CLEAR = "clear"
ARMED = "armed"
ESCALATED = "escalated"

# Recommended context-window shrink multiplier per state. The caller composes
# this with its own floor (never below whatever minimum window it already
# enforces) — this module does not know that floor.
_SHRINK_FRACTIONS = {
    CLEAR: 1.0,
    ARMED: 0.75,
    ESCALATED: 0.5,
}


def assess(
    turn_latencies: Sequence[float],
    timeout: float,
    *,
    arm_fraction: float = 0.5,
    escalate_fraction: float = 0.75,
    window: int = 3,
) -> str:
    """Classify the rolling mean of the last ``window`` turn latencies.

    Compares the mean of ``turn_latencies[-window:]`` against
    ``timeout * escalate_fraction`` and ``timeout * arm_fraction``:

    - mean >= escalate threshold -> :data:`ESCALATED`
    - mean >= arm threshold      -> :data:`ARMED`
    - otherwise                  -> :data:`CLEAR`

    Both threshold comparisons are inclusive (``>=``), so a mean landing
    exactly on a fraction boundary reads as the tightened side.

    ``turn_latencies`` may hold fewer than ``window`` samples — the mean is
    taken over whatever is there (no padding, no lookback beyond what was
    given); zero samples is :data:`CLEAR` (nothing observed yet, nothing to
    react to). ``timeout <= 0`` is degenerate (no request timeout to measure
    against) and always classifies :data:`CLEAR` rather than raising
    ``ZeroDivisionError`` or dividing by a negative number.
    """
    if timeout <= 0:
        return CLEAR
    if not turn_latencies:
        return CLEAR

    window = max(1, window)
    recent = list(turn_latencies)[-window:]
    mean_latency = sum(recent) / len(recent)

    if mean_latency >= timeout * escalate_fraction:
        return ESCALATED
    if mean_latency >= timeout * arm_fraction:
        return ARMED
    return CLEAR


def shrink_fraction(state: str) -> float:
    """Recommended context-window multiplier for *state*.

    ``CLEAR`` -> 1.0 (no change), ``ARMED`` -> 0.75, ``ESCALATED`` -> 0.5. An
    unrecognized state degrades to the ``CLEAR`` identity (1.0) rather than
    raising — this module never invents a tightening for a state it doesn't
    know. The caller is expected to multiply its own current window/budget by
    this fraction and still apply its own minimum-window floor.
    """
    return _SHRINK_FRACTIONS.get(state, 1.0)


def throttled_concurrency(state: str, configured: int) -> int:
    """Recommended subagent concurrency cap for *state*.

    ``CLEAR`` -> ``configured`` (unchanged), ``ARMED`` -> ``configured - 1``
    (never below 1), ``ESCALATED`` -> 1. An unrecognized state degrades to the
    ``CLEAR`` identity (``configured`` unchanged).

    A non-positive ``configured`` is degenerate (no caller configures
    zero/negative fan-out) and is floored to 1 before the state multiplier is
    applied, so the result is always a usable concurrency of at least 1 and
    never above ``configured`` (once ``configured`` is itself at least 1).
    """
    configured = max(1, configured)
    if state == ESCALATED:
        return 1
    if state == ARMED:
        return max(1, configured - 1)
    return configured
