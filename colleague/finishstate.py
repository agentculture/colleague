"""Finish-state classifier — pure, deterministic, IO-free (plan task t1,
covers c4/h4, decision c30).

Maps a work item's (or one seat's) terminal facts onto one of five
distinguishable states colleague reports on every artifact
(:data:`colleague.contract.FINISH_STATES`), independent of which backend
produced the raw wire value:

- ``FINISH_DELIBERATE`` — the model reached its own decision to stop with a
  real answer (a clean ``finish`` call, or a no-tool-call turn that answered
  in prose).
- ``FINISH_TRUNCATED`` — cut short by a resource ceiling: a raw wire
  ``finish_reason == "length"`` (the backend hit its own token cap) OR the
  loop's own step-budget ceiling (``outcome == "budget"``). Both are the
  harness/backend truncating the model before ITS OWN decision to stop —
  grouping them keeps "truncated" meaning "cut short by a resource limit",
  not only the narrower wire-vocabulary sense.
- ``FINISH_STOPPED`` — an external stop: a pilot's cooperative ``stop``
  directive (``outcome == "pilot_stop"``), or the loop halting a provably
  broken tool-call channel (colleague#321, ``outcome == "tool_protocol"``).
  Neither is the model's own decision — note this is DIFFERENT from the
  loop's OWN ``"stopped"``-spelled exit reason (a no-tool-call turn that
  simply ran out of nudges), which is intentionally classified
  ``FINISH_DELIBERATE`` (the model itself chose to stop talking) — the
  string "stopped" is reused by both vocabularies but means something
  different in each; do not conflate them.
- ``FINISH_TIMEOUT`` — the underlying request timed out and the work item
  never recovered (a degradable ``"timeout"`` signal, see
  :func:`colleague.context.classify_degradable`) — takes precedence over
  every other signal.
- ``FINISH_EMPTY`` — no usable result was produced: ``summary`` is literally
  :data:`colleague.contract.NO_RESULT_PRODUCED`, OR the work item aborted
  (engine exception) without timing out — an abort's ``summary`` holds a
  diagnostic fallback note, not a real answer, so it is the same "nothing
  delivered" bucket. This state (checked right after ``timed_out``) ALWAYS
  wins over every other signal once it applies — the acceptance-criterion
  invariant this module exists to uphold: the sentinel must never be
  reported as ``FINISH_DELIBERATE`` (a completed answer).

This module imports only from :mod:`colleague.contract` and the stdlib — the
same "pure, IO-free" discipline as :mod:`colleague.incompletion`, which this
mirrors (a leaf module: :mod:`colleague.loop` imports this, never the
reverse).
"""

from __future__ import annotations

from colleague.contract import (
    FINISH_DELIBERATE,
    FINISH_EMPTY,
    FINISH_STOPPED,
    FINISH_TIMEOUT,
    FINISH_TRUNCATED,
    NO_RESULT_PRODUCED,
)

# The loop's own terminal-outcome labels this classifier keys on — plain
# string literals (not an import of colleague.loop's private ``_EXIT_*``
# constants) so this module stays a leaf: colleague.loop imports
# colleague.finishstate, never the reverse. Mirrors colleague.incompletion's
# own convention of taking ``outcome`` as a plain string.
_OUTCOME_BUDGET = "budget"
_OUTCOME_PILOT_STOP = "pilot_stop"
_OUTCOME_TOOL_PROTOCOL = "tool_protocol"


def classify_finish_state(
    *,
    summary: str,
    finish_reason: str = "",
    outcome: str = "",
    timed_out: bool = False,
    aborted: bool = False,
) -> str:
    """Classify one seat's terminal state onto the five ``FINISH_*`` states.

    Parameters
    ----------
    summary:
        The work item's (or seat's) resolved summary/answer text. Compared
        verbatim against :data:`colleague.contract.NO_RESULT_PRODUCED`.
    finish_reason:
        The raw backend-reported finish reason for the LAST completion on
        this seat (``""`` when the backend/engine never reports the field).
    outcome:
        The loop's terminal outcome label for this seat — one of
        ``"finished"``/``"stopped"``/``"budget"``/``"pilot_stop"``/
        ``"tool_protocol"`` — or ``""`` when not applicable (e.g. an aborted
        run, or a seat with no loop-exit concept of its own).
    timed_out:
        ``True`` when the underlying request that ended this seat's work
        timed out (a degradable ``"timeout"`` signal). Takes precedence over
        every other signal — a timeout means the request never completed at
        all, so nothing else about it can be trusted.
    aborted:
        ``True`` when the seat's work ended via an engine-level abort that
        was NOT specifically a timeout (a context-overflow give-up at the
        degradation floor, or an unexpected engine exception). ``summary`` on
        this path is a diagnostic fallback note, never a real deliverable, so
        this maps to ``FINISH_EMPTY`` exactly like the ``NO_RESULT_PRODUCED``
        sentinel — checked before the sentinel comparison since an aborted
        run's summary is never literally the sentinel.
    """
    if timed_out:
        return FINISH_TIMEOUT
    if aborted:
        return FINISH_EMPTY
    if summary == NO_RESULT_PRODUCED:
        return FINISH_EMPTY
    if outcome in (_OUTCOME_PILOT_STOP, _OUTCOME_TOOL_PROTOCOL):
        return FINISH_STOPPED
    if finish_reason == "length" or outcome == _OUTCOME_BUDGET:
        return FINISH_TRUNCATED
    return FINISH_DELIBERATE
