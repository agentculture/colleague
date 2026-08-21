"""Step-stall watchdog primitives (#400) — a PROGRESS bound, not a duration one.

Headless streaming (#393) removed the request timeout's accidental second job:
bounding a turn that had stopped making progress. A saturated-context turn can
now stream healthily for hours while ``step_index`` never advances and nothing
is persisted. This leaf module gives the loop a per-turn **deadline keyed to
time-since-last-completed-step** that a streaming transport can consult
between frames, and the loop an honest way to end the episode with a partial.

Leaf-level by design: stdlib only (``contextvars`` + ``time``), no clock
ownership beyond reading ``time.monotonic()``, no threads, no I/O, no import
from ``colleague.loop`` / ``colleague.config`` / any engine. ``contextvars``
keeps the armed deadline per execution context — a subagent child's loop
(running in its own thread) arms and reads its OWN deadline; a context with
nothing armed makes :func:`check` a no-op, so engines may call it
unconditionally.

The loop owns the policy (the bound, the operator knob
``COLLEAGUE_MAX_STEP_STALL``, what to record); this module owns only the
arm/check mechanics.
"""

from __future__ import annotations

import contextvars
import time
from typing import Optional

__all__ = ["TurnStalled", "arm", "disarm", "check", "armed"]


class TurnStalled(Exception):
    """Raised by :func:`check` once the armed progress deadline has passed.

    ``seconds`` is the elapsed time since the last completed step at the moment
    of detection; ``bound`` is the limit that was crossed.
    """

    def __init__(self, seconds: float, bound: float) -> None:
        self.seconds = seconds
        self.bound = bound
        super().__init__(f"no completed step for {seconds:.0f}s (step-stall bound {bound:.0f}s)")


# (deadline, since) in ``time.monotonic()`` seconds, or None when nothing is armed.
_ARMED: contextvars.ContextVar[Optional[tuple[float, float]]] = contextvars.ContextVar(
    "colleague_stall_deadline", default=None
)


def arm(*, since: float, bound: float) -> contextvars.Token:
    """Arm the progress deadline at ``since + bound`` for the current context.

    Returns the token :func:`disarm` needs. ``since`` is the monotonic time of
    the last completed step (or the turn start when none has completed yet).
    """
    return _ARMED.set((since + bound, since))


def disarm(token: contextvars.Token) -> None:
    """Restore the previous armed state (pair with :func:`arm` in a ``finally``)."""
    _ARMED.reset(token)


def armed() -> Optional[tuple[float, float]]:
    """The current ``(deadline, since)`` pair, or ``None`` when nothing is armed."""
    return _ARMED.get()


def check(now: Optional[float] = None) -> None:
    """Raise :class:`TurnStalled` if an armed deadline has passed; else return.

    Cheap enough to call per streamed frame. A context with nothing armed is a
    strict no-op, so transports call it unconditionally.
    """
    state = _ARMED.get()
    if state is None:
        return
    deadline, since = state
    current = time.monotonic() if now is None else now
    if current > deadline:
        raise TurnStalled(current - since, deadline - since)
