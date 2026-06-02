"""Deterministic replay of a captured event log through the pure TUI reducer.

This module is intentionally free of I/O, clocks, and randomness.  It imports
nothing from ``os``, ``time``, or ``random`` — only stdlib types plus the
project-local ``reducer``, ``events``, and ``state`` modules.

Public API
----------
:func:`replay`
    Fold a list of events through :func:`~colleague.tui.reducer.reduce`
    starting from *initial* (or a fresh :class:`~colleague.tui.state.CockpitState`
    when ``None``) and return the final state.

:func:`replay_from_jsonl`
    Parse JSONL text via
    :func:`~colleague.tui.events.loads_events` and then call :func:`replay`.
"""

from __future__ import annotations

from typing import Optional

from colleague.tui.events import loads_events
from colleague.tui.reducer import reduce
from colleague.tui.state import CockpitState


def replay(
    events: list,
    initial: Optional[CockpitState] = None,
) -> CockpitState:
    """Fold *events* through the pure reducer and return the final state.

    Parameters
    ----------
    events:
        Ordered list of event objects (any type accepted by
        :func:`~colleague.tui.reducer.reduce`).
    initial:
        Starting state.  When ``None`` a fresh :class:`CockpitState` is used.
        The object is **not mutated** — each :func:`~colleague.tui.reducer.reduce`
        call returns a new instance.

    Returns
    -------
    CockpitState
        The state produced by folding every event in *events*.
    """
    state: CockpitState = initial if initial is not None else CockpitState()
    for event in events:
        state = reduce(state, event)
    return state


def replay_from_jsonl(
    text: str,
    initial: Optional[CockpitState] = None,
) -> CockpitState:
    """Parse JSONL *text* into events and replay them.

    Parameters
    ----------
    text:
        JSONL-formatted string as produced by
        :func:`~colleague.tui.events.dumps_events`.
    initial:
        Passed unchanged to :func:`replay`.

    Returns
    -------
    CockpitState
        The state produced by folding every parsed event.
    """
    return replay(loads_events(text), initial=initial)
