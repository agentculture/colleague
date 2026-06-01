"""Foreground TTY driver for the convertible TUI cockpit.

Public surface
--------------
:func:`key_to_event` — pure function: map one key token to an Event or None
    (None signals quit).
:func:`run` — the main loop.  Accepts injected ``keys`` + ``out`` for
    test-mode (no real terminal); uses ``termios``/``tty`` raw-mode when
    called without ``keys`` (live terminal).

Design notes
------------
* Zero third-party imports — stdlib only (``sys``, ``termios``, ``tty``,
  ``typing``).
* No socket, no subprocess, no asyncio, no process forking, no threads.
* Single foreground loop that **returns** on quit.
* Dependency-injection seam: pass ``keys`` (any ``Iterable[str]``) and an
  ``out`` file-like to exercise the entire loop logic without touching
  a real terminal.
* Live mode: reads one byte at a time from ``sys.stdin`` in raw mode,
  restores terminal state in a ``try/finally`` so the terminal is always
  left clean.
"""

from __future__ import annotations

import sys
import termios
import tty
from typing import TYPE_CHECKING, Iterable, Optional

from convertible.tui.events import Event, Key
from convertible.tui.reducer import reduce
from convertible.tui.render.ansi import render
from convertible.tui.state import CockpitState

if TYPE_CHECKING:
    pass

# ---------------------------------------------------------------------------
# ANSI clear-screen escape — prepended before each frame in live mode
# ---------------------------------------------------------------------------

_CLEAR = "\x1b[2J\x1b[H"

# ---------------------------------------------------------------------------
# Quit keys
# ---------------------------------------------------------------------------

_QUIT_KEYS = frozenset(["q", "\x1b"])  # 'q' and ESC


# ---------------------------------------------------------------------------
# Public: pure key mapper
# ---------------------------------------------------------------------------


def key_to_event(key: str) -> Optional[Event]:
    """Map *key* to an :class:`~convertible.tui.events.Event`, or ``None`` for quit.

    Parameters
    ----------
    key:
        A single key token — one character, an escape sequence, or a named
        token such as ``"up"`` / ``"down"`` / ``"enter"``.

    Returns
    -------
    Event | None
        ``None`` means quit; any other value is an event to feed to
        :func:`~convertible.tui.reducer.reduce`.
    """
    if key in _QUIT_KEYS:
        return None
    return Key(key=key)


# ---------------------------------------------------------------------------
# Public: main loop
# ---------------------------------------------------------------------------


def run(
    initial: Optional[CockpitState] = None,
    *,
    keys: Optional[Iterable[str]] = None,
    out=None,
    max_iterations: Optional[int] = None,
) -> CockpitState:
    """Drive the cockpit loop until the user quits.

    Parameters
    ----------
    initial:
        Starting state.  Defaults to a fresh :class:`CockpitState`.
    keys:
        **Injected mode** (tests): an iterable of key tokens to consume
        instead of reading from the real terminal.  The loop exits when the
        iterable is exhausted or a quit key is encountered.  No ``termios``
        call is made.
    out:
        Output stream.  Defaults to ``sys.stdout``.  In both modes one frame
        is written per iteration; in live mode a clear-screen escape is
        prepended.
    max_iterations:
        Optional cap on the number of loop iterations (useful in tests with
        infinite iterables).

    Returns
    -------
    CockpitState
        The final state at the moment the loop exits.
    """
    state: CockpitState = initial if initial is not None else CockpitState()
    out = out if out is not None else sys.stdout

    if keys is not None:
        return _injected_loop(state, keys=keys, out=out, max_iterations=max_iterations)
    return _live_loop(state, out=out)


# ---------------------------------------------------------------------------
# Private: injected loop (test-friendly, no termios)
# ---------------------------------------------------------------------------


def _injected_loop(
    state: CockpitState,
    *,
    keys: Iterable[str],
    out,
    max_iterations: Optional[int],
) -> CockpitState:
    """Consume *keys* without touching termios.  Used in tests."""
    iteration = 0
    for key in keys:
        if max_iterations is not None and iteration >= max_iterations:
            break
        # Render current state before processing the key.
        out.write(render(state))
        ev = key_to_event(key)
        if ev is None:
            # Quit: write a final frame and return.
            out.write(render(state))
            return state
        state = reduce(state, ev)
        iteration += 1
    return state


# ---------------------------------------------------------------------------
# Private: live loop (real terminal, termios raw mode)
# ---------------------------------------------------------------------------


def _live_loop(state: CockpitState, *, out) -> CockpitState:
    """Read keys from the real terminal in raw mode.

    The terminal is always restored in the ``finally`` block, even on
    exceptions.  Quit keys (``q``, ESC) exit cleanly.
    """
    fd = sys.stdin.fileno()
    old_attrs = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        while True:
            # Render: clear screen + current frame.
            out.write(_CLEAR + render(state))
            out.flush()

            # Read one byte (raw mode).
            ch = sys.stdin.read(1)
            ev = key_to_event(ch)
            if ev is None:
                # Quit: one final render, then return.
                out.write(_CLEAR + render(state))
                out.flush()
                return state
            state = reduce(state, ev)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_attrs)
