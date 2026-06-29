"""Live cockpit + event-stream progress sinks for a work item (#74 A1/A3).

`execute_work` wires exactly one progress callback onto `EngineConfig.progress`.
This module builds the richer callbacks that one can be:

* :class:`CockpitProgressSink` — folds each work item step into a live `CockpitState`
  and redraws the ANSI cockpit frame on stderr (A1); and
* :func:`make_events_sink` — appends one `WorkStep` JSONL line per step so an
  agent can follow the work item turn-by-turn and `tui replay` it (A3).

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

from agentfront.taui.colors import should_color, strip_ansi
from agentfront.taui.events import dumps_events
from agentfront.taui.reducer import reduce
from agentfront.taui.render.ansi import render_ansi as render
from agentfront.taui.state import TAUIState as CockpitState
from agentfront.taui.state import WorkItem

from colleague.tui.from_work import work_step

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


class FrameWriter:
    """Render a :class:`CockpitState` to a stream with one clear-home regime.

    Holds the resolved ``(stream, tty, color)`` so the live work sink **and** the
    interactive session can share a single writer — the palette frame and the
    in-work frames then never fight over the screen (one owner, one clear).

    Two output modes:

    * **in-place redraw** (``dynamic`` — a colored TTY): each frame is preceded by
      a clear-screen/cursor-home so the cockpit updates in place.
    * **append** (otherwise — non-TTY or ``NO_COLOR``): escapes are stripped and
      successive frames are separated by a blank line so box borders never run
      together. Under ``NO_COLOR`` this leaves **no** escape sequences at all (the
      clear-home is itself an escape, so it is suppressed too).
    """

    def __init__(self, stream: Optional[TextIO] = None) -> None:
        self._stream = stream if stream is not None else sys.stderr
        self._tty = _isatty(self._stream)
        self._color = should_color(self._stream)

    @property
    def dynamic(self) -> bool:
        """Whether frames redraw in place (colored TTY) vs. append (static)."""
        return self._tty and self._color

    def write(self, state: CockpitState, *, final: bool = False) -> None:
        frame = render(state)
        if self.dynamic:
            text = _CLEAR_HOME + frame + ("\n" if final else "")
        else:
            text = strip_ansi(frame) + "\n\n"
        self._stream.write(text)
        with suppress(Exception):
            self._stream.flush()


class CockpitProgressSink:
    """A progress sink that renders a live ANSI cockpit frame per work step.

    Holds a :class:`CockpitState` (seeded with a running :class:`WorkItem`); each call
    folds a `WorkStep` through the pure reducer (so a failed step opens the same
    error popup as `tui replay`) and redraws via a :class:`FrameWriter`.
    """

    def __init__(self, task_id: str, engine: str, *, stream: Optional[TextIO] = None) -> None:
        self._state = CockpitState(
            work_item=WorkItem(task_id=task_id, engine=engine, step_count=0, running=True)
        )
        self._writer = FrameWriter(stream)

    def __call__(self, step_index: int, tool: str, target: str, ok: bool) -> None:
        # A phase notice (#206) carries an EMPTY tool name and is NOT a step — skip it
        # so the cockpit never folds a phantom step or bumps the step count (a live
        # "synthesizing…" status line in the cockpit is a documented follow-up).
        if not tool:
            return
        self._state = reduce(self._state, work_step(tool, target, ok))
        self._writer.write(self._state)

    def close(self) -> None:
        """Mark the work item finished and render a final frame (with a trailing newline)."""
        if self._state.work_item is not None:
            self._state = replace(
                self._state, work_item=replace(self._state.work_item, running=False)
            )
        self._writer.write(self._state, final=True)


def make_events_sink(path: str, *, diag: Optional[Callable[[str], None]] = None) -> ProgressSink:
    """Return a sink that appends one `WorkStep` JSONL line per step to *path* (A3).

    The line format is exactly what `tui replay` / `tui snapshot` consume, so a
    live stream and a post-hoc `tui replay --trace` agree.  Write failures are
    best-effort (observability is never control): the first failure emits a single
    diagnostic via *diag* (default: stderr) and subsequent ones are silent.
    """
    state = {"warned": False}

    def _sink(step_index: int, tool: str, target: str, ok: bool) -> None:
        # Phase notices (#206) carry an EMPTY tool name and are not steps — keep them
        # out of the structured replay stream so `tui replay`/`snapshot` stay step-only
        # (byte-identical to before).
        if not tool:
            return
        line = dumps_events([work_step(tool, target, ok)])
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
    external_sink: Optional["CockpitProgressSink"] = None,
) -> tuple[ProgressSink, Optional[CockpitProgressSink]]:
    """Resolve the work item's progress callback and (if any) the live cockpit sink.

    Returns ``(progress, cockpit)``.  When neither TUI surface is requested the
    *default_sink* is returned **verbatim** (so the plain `step N:` path stays
    byte-identical); otherwise the active sinks are composed with per-sink failure
    isolation.  *cockpit* is non-None only when a live cockpit is active, so the
    caller can `close()` it (and read back its accumulated ``state``) after the work item.

    *external_sink* lets a caller supply its **own** cockpit sink (e.g. the
    interactive session, bound to the session's `CockpitState` + frame-writer). When
    given it replaces the auto-constructed cockpit and bypasses ``tui``
    auto-activation — so a work item launched from the session renders into the session's
    one shared screen.
    """
    cockpit: Optional[CockpitProgressSink] = None
    sinks: list[ProgressSink] = []
    if external_sink is not None:
        cockpit = external_sink
        sinks.append(external_sink)
    elif cockpit_active(tui, stream=stream):
        cockpit = CockpitProgressSink(task_id, engine, stream=stream)
        sinks.append(cockpit)
    else:
        sinks.append(default_sink)
    if tui_events:
        sinks.append(make_events_sink(tui_events, diag=diag))

    if sinks == [default_sink]:
        return default_sink, None  # byte-identical default path
    return make_fanout(sinks), cockpit
