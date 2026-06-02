"""Live cockpit + event-stream progress sinks for a drive (#74 A1/A3).

`execute_drive` wires exactly one progress callback onto `EngineConfig.progress`.
This module builds the richer callbacks that one can be:

* :class:`CockpitProgressSink` — folds each drive step into a live `CockpitState`
  and redraws the ANSI cockpit frame on stderr (A1); and
* :func:`make_events_sink` — appends one `DriveStep` JSONL line per step so an
  agent can follow the drive turn-by-turn and `tui replay` it (A3).

:func:`build_progress` chooses between these and the plain stderr sink based on
the `--tui`/`--no-tui` flag (or, by default, whether stderr is a TTY) plus an
optional events path, and composes several sinks with **per-sink failure
isolation** — one raising sink never starves the others (the loop's outer
`suppress` is only a backstop).

Stdlib only.  Lives in the CLI layer (not tui-core), so it may import the loop's
plain `_step_progress` sink and the ANSI renderer.
"""

from __future__ import annotations

import sys
from contextlib import suppress
from dataclasses import replace
from typing import Callable, Optional, TextIO

from convertible.tui.colors import should_color, strip_ansi
from convertible.tui.events import dumps_events
from convertible.tui.from_drive import drive_step
from convertible.tui.reducer import reduce
from convertible.tui.render.ansi import render
from convertible.tui.state import CockpitState, Drive

#: A progress callback: ``(step_index, tool, target, ok) -> None``.
ProgressSink = Callable[[int, str, str, bool], None]

#: CSI clear-screen + cursor-home, so each frame redraws in place (TTY only).
_CLEAR_HOME = "\x1b[H\x1b[2J"


def _isatty(stream: TextIO) -> bool:
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError):
        return False


def cockpit_active(tui: Optional[bool], *, stream: Optional[TextIO] = None) -> bool:
    """Resolve whether the live cockpit is on.

    Explicit ``--tui`` / ``--no-tui`` (``True`` / ``False``) wins; otherwise it is
    auto: on when the diagnostics stream (stderr) is an interactive terminal.
    """
    if tui is not None:
        return tui
    return _isatty(stream if stream is not None else sys.stderr)


class CockpitProgressSink:
    """A progress sink that renders a live ANSI cockpit frame per drive step.

    Owns its `CockpitState` (seeded with a running :class:`Drive`); each call
    folds a `DriveStep` through the pure reducer (so a failed step opens the same
    error popup as `tui replay`) and redraws the frame.  Escapes are stripped when
    the stream should not be colored (`NO_COLOR` / non-TTY), and the in-place clear
    is only emitted on a real TTY so a captured log stays readable.
    """

    def __init__(self, task_id: str, engine: str, *, stream: Optional[TextIO] = None) -> None:
        self._stream = stream if stream is not None else sys.stderr
        self._state = CockpitState()
        self._state.drive = Drive(task_id=task_id, engine=engine, step_count=0, running=True)
        self._tty = _isatty(self._stream)
        self._color = should_color(self._stream)

    def __call__(self, step_index: int, tool: str, target: str, ok: bool) -> None:
        self._state = reduce(self._state, drive_step(tool, target, ok))
        self._write_frame()

    def close(self) -> None:
        """Mark the drive finished and render a final frame (with a trailing newline)."""
        if self._state.drive is not None:
            self._state.drive = replace(self._state.drive, running=False)
        self._write_frame(final=True)

    def _write_frame(self, *, final: bool = False) -> None:
        frame = render(self._state)
        if not self._color:
            frame = strip_ansi(frame)
        prefix = _CLEAR_HOME if self._tty else ""
        suffix = "\n" if final else ""
        self._stream.write(prefix + frame + suffix)
        with suppress(Exception):
            self._stream.flush()


def make_events_sink(path: str, *, diag: Optional[Callable[[str], None]] = None) -> ProgressSink:
    """Return a sink that appends one `DriveStep` JSONL line per step to *path* (A3).

    The line format is exactly what `tui replay` / `tui snapshot` consume, so a
    live stream and a post-hoc `tui replay --trace` agree.  Write failures are
    best-effort (observability is never control): the first failure emits a single
    diagnostic via *diag* (default: stderr) and subsequent ones are silent.
    """
    state = {"warned": False}

    def _sink(step_index: int, tool: str, target: str, ok: bool) -> None:
        line = dumps_events([drive_step(tool, target, ok)])
        try:
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(line)
        except OSError as exc:
            if not state["warned"]:
                state["warned"] = True
                emit = diag if diag is not None else (lambda m: print(m, file=sys.stderr))
                emit(f"tui-events: cannot write {path}: {exc} (event stream disabled)")

    return _sink


def make_fanout(sinks: list[ProgressSink]) -> ProgressSink:
    """Compose *sinks* so each runs under its own `suppress` — a raising sink never
    starves the others (the loop's outer suppress is only a last-resort backstop)."""

    def _fanout(step_index: int, tool: str, target: str, ok: bool) -> None:
        for sink in sinks:
            with suppress(Exception):
                sink(step_index, tool, target, ok)

    return _fanout


def build_progress(
    *,
    default_sink: ProgressSink,
    task_id: str,
    engine: str,
    tui: Optional[bool] = None,
    tui_events: Optional[str] = None,
    stream: Optional[TextIO] = None,
    diag: Optional[Callable[[str], None]] = None,
) -> tuple[ProgressSink, Optional[CockpitProgressSink]]:
    """Resolve the drive's progress callback and (if any) the live cockpit sink.

    Returns ``(progress, cockpit)``.  When neither TUI surface is requested the
    *default_sink* is returned **verbatim** (so the plain `step N:` path stays
    byte-identical); otherwise the active sinks are composed with per-sink failure
    isolation.  *cockpit* is non-None only when the live cockpit is active, so the
    caller can `close()` it after the drive.
    """
    cockpit: Optional[CockpitProgressSink] = None
    sinks: list[ProgressSink] = []
    if cockpit_active(tui, stream=stream):
        cockpit = CockpitProgressSink(task_id, engine, stream=stream)
        sinks.append(cockpit)
    else:
        sinks.append(default_sink)
    if tui_events:
        sinks.append(make_events_sink(tui_events, diag=diag))

    if sinks == [default_sink]:
        return default_sink, None  # byte-identical default path
    return make_fanout(sinks), cockpit
