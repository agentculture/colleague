"""Verbatim-tail repetition guard (adopt-from-qwen-code follow-up, spec c39/h31/h26).

Guards against the shape of colleague run ``2bd306a6916a``: 271,486 characters
of ONE insight repeated verbatim until ``finish_reason=length``, with no
answer ever delivered. :func:`colleague.loopguards.check` already covers the
two unconditional qwen-code guards (identical tool calls, calls-per-turn);
this module ports ONLY the verbatim-tail tier of qwen-code's repetition
detector. The other tier qwen-code shipped — an entropy/content heuristic
over free-form text — is off upstream for false positives and is explicitly
NOT ported here (see :mod:`colleague.loopguards`'s docstring, spec c17/c20).
Deliberately conservative: the incident gave roughly five orders of magnitude
of margin over the threshold below, so this module spends none of that margin
on cleverness.

This module imports **nothing** from :mod:`colleague.loop`, its ``loop_*``
siblings, or :mod:`colleague.engines` — so the streaming call site (fed
arriving chunks incrementally) and the blocking call site (handed the whole
reasoning text at once) share exactly one definition of "repetition" and
cannot drift apart. Detector state is a plain, JSON-serialisable ``dict``
passed in and returned by :func:`check` — never held at module scope — so two
detectors can run concurrently (e.g. one per streaming reasoning channel)
without interfering with each other.

adapted-from: qwen-code packages/core/src/services/loopDetectionService.ts
(the verbatim content-repetition tier only; the entropy tier is NOT ported).
"""

from __future__ import annotations

from typing import Any, Optional

#: Minimum length, in characters, of the verbatim unit that must recur for a
#: trip to fire. Below this, short incidental repeats (a repeated word, a
#: numbered-list marker) are common in ordinary reasoning prose and must
#: never trip the guard.
TAIL_REPEAT_MIN_LENGTH = 48

#: Minimum number of consecutive, verbatim, tail-anchored occurrences of the
#: repeating unit required before a trip fires.
TAIL_REPEAT_MIN_COUNT = 8

#: Bound on how much trailing text a detector state retains. Large enough to
#: find a repeating unit up to ``MAX_BUFFER_CHARS // TAIL_REPEAT_MIN_COUNT``
#: characters long recurring ``TAIL_REPEAT_MIN_COUNT`` times, small enough to
#: keep every check O(bounded) rather than O(n) over an ever-growing stream.
#: Four orders of magnitude below the 271,486-character incident.
MAX_BUFFER_CHARS = 8192

#: How many guard trips within ONE run escalate the response from cutting the
#: current turn to ending the run outright. A single trip cuts the turn; the
#: run only ends once trips reach this count.
ESCALATION_TRIP_LIMIT = 3

WARNING_KIND = "repetition-guard"

#: The shape of detector state: ``{"buffer": str}``. Callers must treat this
#: as opaque and thread it through via :func:`new_state` / :func:`check` —
#: never read or write ``"buffer"`` directly, so the internal representation
#: stays free to change.
RepetitionState = dict


def new_state() -> RepetitionState:
    """A fresh, empty detector state.

    Both call sites start here: the streaming caller keeps the returned
    state across chunks; the blocking caller may call :func:`check` once
    with a fresh state and the whole reasoning text as the one "chunk".
    """
    return {"buffer": ""}


def _minimal_period(s: str) -> int:
    """The smallest ``p`` such that *s* is exactly ``s[:p]`` repeated whole.

    Standard KMP-failure-function trick: if ``p = len(s) - fail[-1]``
    divides ``len(s)`` evenly, *s* is *p*-periodic; otherwise *s* has no
    period shorter than its own length (``len(s)`` is returned).
    """
    n = len(s)
    if n == 0:
        return 0
    fail = [0] * n
    k = 0
    for i in range(1, n):
        while k > 0 and s[i] != s[k]:
            k = fail[k - 1]
        if s[i] == s[k]:
            k += 1
        fail[i] = k
    p = n - fail[-1]
    return p if n % p == 0 else n


def _find_tail_repeat(buffer: str) -> Optional[int]:
    """Return the period (unit length) of a qualifying tail repeat, or ``None``.

    A "qualifying tail repeat" is a substring of at least
    :data:`TAIL_REPEAT_MIN_LENGTH` characters that appears, verbatim and
    immediately adjacent, at least :data:`TAIL_REPEAT_MIN_COUNT` times at the
    very end of *buffer* — where that substring is the *fundamental* (i.e.
    smallest) repeating unit, not merely an accidental integer multiple of a
    shorter one. Without that check a genuinely short repeat (e.g. 24 chars)
    running on long enough would also satisfy a longer nominal period (48,
    72, ...) purely because a multiple of a short period is trivially itself
    periodic — which must never count as a qualifying 48-character repeat.

    Search is bounded: only periods for which the
    ``period * TAIL_REPEAT_MIN_COUNT``-character tail window actually fits in
    *buffer* are tried, so cost scales with the (capped) buffer size, never
    with the full accumulated stream.
    """
    n = len(buffer)
    max_period = n // TAIL_REPEAT_MIN_COUNT
    if max_period < TAIL_REPEAT_MIN_LENGTH:
        return None
    for period in range(TAIL_REPEAT_MIN_LENGTH, max_period + 1):
        total = period * TAIL_REPEAT_MIN_COUNT
        window = buffer[-total:]
        unit = window[:period]
        if unit * TAIL_REPEAT_MIN_COUNT != window:
            continue
        if _minimal_period(unit) != period:
            # This "period" is just a multiple of a shorter fundamental
            # repeat — not itself a qualifying >=48-char repeating unit.
            continue
        return period
    return None


def check(
    chunk: str, state: Optional[RepetitionState]
) -> tuple[RepetitionState, Optional[dict[str, Any]]]:
    """Feed *chunk* into *state* and report a verbatim-tail-repeat trip, if any.

    *state* is the detector state returned by a prior call, or ``None`` /
    :func:`new_state` to start fresh — never a module-level global, so
    independent streams (or independent runs) never share a detector.
    Returns ``(new_state, trip_or_None)``; *state* itself is never mutated
    in place.

    The **streaming** call site calls this once per arriving chunk, threading
    the returned state to the next call. The **blocking** call site calls
    this once with the whole reasoning text as *chunk* and a fresh state.

    A trip fires ONLY on a verbatim tail repeat of at least
    :data:`TAIL_REPEAT_MIN_LENGTH` characters recurring at least
    :data:`TAIL_REPEAT_MIN_COUNT` times — never on an entropy/content
    heuristic (that tier is deliberately not ported; see the module
    docstring).
    """
    if state is None:
        state = new_state()
    buffer = state.get("buffer", "") + chunk
    if len(buffer) > MAX_BUFFER_CHARS:
        buffer = buffer[-MAX_BUFFER_CHARS:]
    next_state: RepetitionState = {"buffer": buffer}

    period = _find_tail_repeat(buffer)
    if period is None:
        return next_state, None

    unit = buffer[-period:]
    trip = {
        "kind": WARNING_KIND,
        "period": period,
        "repeats": TAIL_REPEAT_MIN_COUNT,
        "min_length": TAIL_REPEAT_MIN_LENGTH,
        "unit_preview": unit[:80],
    }
    return next_state, trip
