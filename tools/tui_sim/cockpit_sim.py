"""Surfaces 2 & 3 — the live drive cockpit and the popup overlays.

Folds a timed event stream through the *real* pure reducer
(:func:`colleague.tui.reducer.reduce`) and renders each resulting state with the
*real* ANSI renderer (:func:`colleague.tui.render.ansi.render`). ``Tick`` events
animate the prompt spinner between tool steps; ``DriveStep`` events grow the
conversation tool-by-tool; a failing ``DriveStep`` and a ``SkillSuggested`` event
open the error / boost popups — exactly as a live drive or ``tui replay`` would.

A scenario here yields both a :class:`~tools.tui_sim.filmstrip.Filmstrip` *and*
the ``(final_state, events)`` pair, so the caller can also emit a snapshot quad
and run :func:`colleague.tui.diagnose.diagnose` over it.
"""

from __future__ import annotations

import copy
from dataclasses import replace
from typing import List, Tuple

from colleague.tui.events import Event, Tick
from colleague.tui.reducer import reduce
from colleague.tui.render.ansi import render
from colleague.tui.state import CockpitState, Drive

from .filmstrip import DEFAULT_WIDTH, FrameT

#: ``(event, hold_ms)`` — an event to fold and how long to hold the frame after.
TimedEvent = Tuple[Event, int]


def drive_state(
    base: CockpitState, *, engine: str = "mock", task_id: str = "t-7f3a2c"
) -> CockpitState:
    """Return a copy of *base* turned into a live-drive cockpit.

    Starts a running :class:`Drive` (so ``DriveStep`` events bump ``step_count``)
    and switches the background animation on (so the prompt spinner spins as
    ``Tick`` events advance the frame counter).
    """
    state = copy.deepcopy(base)
    state.drive = Drive(task_id=task_id, engine=engine, step_count=0, running=True)
    state.background = replace(state.background, animation="spin", semantic="busy")
    return state


def ticks(n: int, hold_ms: int) -> List[TimedEvent]:
    """``n`` spinner ticks, each held ``hold_ms`` — visible spinner motion."""
    return [(Tick(), hold_ms) for _ in range(n)]


def fold(
    initial: CockpitState,
    timed_events: List[TimedEvent],
    *,
    width: int = DEFAULT_WIDTH,
    open_hold: int = 600,
) -> Tuple[List[FrameT], List[CockpitState], List[Event]]:
    """Fold *timed_events* into *initial*, rendering a frame after each.

    Returns ``(frames, states, events)``. ``frames[i]`` and ``states[i]`` are
    aligned: index 0 is the initial state (held ``open_hold``); index ``i`` is the
    state after applying event ``i-1``. ``events`` is the applied stream (length
    ``len(frames) - 1``). ``Tick`` events are kept — they are real reducer events,
    so a snapshot's ``events.jsonl`` stays a faithful, replayable timeline.
    """
    state = copy.deepcopy(initial)
    frames: List[FrameT] = [(render(state, width=width), open_hold)]
    states: List[CockpitState] = [state]
    events: List[Event] = []
    for event, hold in timed_events:
        state = reduce(state, event)
        events.append(event)
        states.append(state)
        frames.append((render(state, width=width), hold))
    return frames, states, events


def first_state_with_visible_popup(states: List[CockpitState]) -> int:
    """Index of the first state carrying a visible popup, or ``-1`` (none)."""
    for i, st in enumerate(states):
        if any(p.visible for p in st.popups):
            return i
    return -1
