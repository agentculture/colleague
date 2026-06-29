"""Live cockpit + event-stream progress sinks (#74 A1/A3).

These exercise the sink module directly: cockpit rendering, the events-file
stream, the activation resolver, and — the subtle one — that a fan-out runs every
sink even when one raises (a render glitch must never starve the agent's event
stream).
"""

from __future__ import annotations

import io

from agentfront.taui.events import loads_events

from colleague.cli._commands._tui_sink import (
    CockpitProgressSink,
    build_progress,
    cockpit_active,
    make_events_sink,
    make_fanout,
)


class _Stream(io.StringIO):
    def __init__(self, isatty: bool) -> None:
        super().__init__()
        self._isatty = isatty

    def isatty(self) -> bool:
        return self._isatty


# --- activation resolver -----------------------------------------------------


def test_cockpit_active_explicit_overrides_tty() -> None:
    assert cockpit_active(True, stream=_Stream(isatty=False)) is True
    assert cockpit_active(False, stream=_Stream(isatty=True)) is False


def test_cockpit_active_auto_follows_tty() -> None:
    assert cockpit_active(None, stream=_Stream(isatty=True)) is True
    assert cockpit_active(None, stream=_Stream(isatty=False)) is False


# --- cockpit sink ------------------------------------------------------------


def test_cockpit_sink_renders_conversation_and_error_popup() -> None:
    out = _Stream(isatty=False)
    sink = CockpitProgressSink("t1", "mock", stream=out)
    sink(0, "read_file", "main.py", True)
    sink(1, "run_command", "pytest -q", False)
    sink.close()
    frame = out.getvalue()
    assert "read_file" in frame and "main.py" in frame
    assert "run_command" in frame
    # The failed step creates a work-error popup in the state (agentfront uses
    # "popup.work-error" — one generic popup id, not per-tool). The popup is in
    # the state; the renderer renders the conversation feed, not popup ids as text.
    assert any(p.id == "popup.work-error" and p.visible for p in sink._state.popups)
    # Non-TTY stream -> escapes stripped so a captured log stays clean.
    assert "\x1b" not in frame


def test_cockpit_sink_no_clear_codes_off_tty() -> None:
    out = _Stream(isatty=False)
    sink = CockpitProgressSink("t1", "mock", stream=out)
    sink(0, "read_file", "x", True)
    assert "\x1b[2J" not in out.getvalue()  # in-place clear only on a real TTY


def test_cockpit_sink_no_color_on_tty_emits_zero_escapes(monkeypatch) -> None:
    """Qodo #2: under NO_COLOR the in-place clear-home (itself an escape) must be
    suppressed too — a TTY stream must still produce a fully escape-free frame."""
    monkeypatch.setenv("NO_COLOR", "1")
    out = _Stream(isatty=True)  # a real terminal, but NO_COLOR is set
    sink = CockpitProgressSink("t1", "mock", stream=out)
    sink(0, "read_file", "main.py", True)
    sink.close()
    frame = out.getvalue()
    assert "main.py" in frame  # content still rendered
    assert "\x1b" not in frame  # NO_COLOR == no escape sequences at all


def test_cockpit_sink_separates_frames_when_not_redrawing() -> None:
    """Qodo #3: without in-place redraw (non-TTY / NO_COLOR), successive frames
    must be delimited so box borders don't run together."""
    out = _Stream(isatty=False)
    sink = CockpitProgressSink("t1", "mock", stream=out)
    sink(0, "read_file", "a.py", True)
    sink(1, "write_file", "b.py", True)
    # A blank line separates frames -> the closing border of one frame is never
    # immediately followed by the opening line of the next.
    assert "\n\n" in out.getvalue()


# --- events-file stream (A3) -------------------------------------------------


def test_events_sink_appends_one_jsonl_line_per_step(tmp_path) -> None:
    path = tmp_path / "ev.jsonl"
    sink = make_events_sink(str(path))
    sink(0, "write_file", "a.py", True)
    sink(1, "finish", "done", False)
    events = loads_events(path.read_text())
    # agentfront WorkStep uses label="[tool] summary" (not separate tool+summary fields).
    assert [(e.label, e.ok) for e in events] == [
        ("[write_file] a.py", True),
        ("[finish] done", False),
    ]


def test_events_sink_warns_once_on_write_failure(tmp_path) -> None:
    # Point at a path whose parent is a file -> open() raises; the sink must not
    # propagate (observability is never control) and warns exactly once.
    not_a_dir = tmp_path / "blocker"
    not_a_dir.write_text("x")
    warnings: list[str] = []
    sink = make_events_sink(str(not_a_dir / "ev.jsonl"), diag=warnings.append)
    sink(0, "t", "a", True)
    sink(1, "t", "b", True)
    assert len(warnings) == 1 and "tui-events" in warnings[0]


# --- phase notices (#206): empty-tool events are not steps --------------------


def test_cockpit_sink_skips_phase_events() -> None:
    """A phase notice (#206) carries an EMPTY tool name — the cockpit must not fold it
    as a step (no phantom step, the step count tracks real tool calls only)."""
    sink = CockpitProgressSink("t1", "mock", stream=_Stream(isatty=False))
    sink(0, "read_file", "a.py", True)
    sink(1, "", "synthesizing the final answer…", True)  # a phase notice, not a step
    assert sink._state.work_item.step_count == 1  # the phase event did not advance it


def test_events_sink_skips_phase_events(tmp_path) -> None:
    """A phase notice (#206) must stay out of the structured replay stream (step-only)."""
    path = tmp_path / "ev.jsonl"
    sink = make_events_sink(str(path))
    sink(0, "write_file", "a.py", True)
    sink(1, "", "thinking…", True)  # phase notice — not a step
    sink(2, "finish", "done", True)
    events = loads_events(path.read_text())
    # agentfront WorkStep uses label="[tool] summary"; phase notices are skipped.
    assert [(e.label, e.ok) for e in events] == [
        ("[write_file] a.py", True),
        ("[finish] done", True),
    ]


def test_step_progress_renders_phase_as_standalone_line(capsys) -> None:
    """The plain stderr sink renders a phase notice (#206) as a bare line, a step as
    a `step N:` line — so a slow synthesis turn is visibly working, not a silent gap."""
    from colleague.cli._commands.work import _step_progress

    _step_progress(3, "", "synthesizing the final answer…", True)  # phase notice
    _step_progress(3, "read_file", "a.py", True)  # a real step
    err = capsys.readouterr().err
    assert "synthesizing the final answer…" in err
    assert "step 3: synthesizing" not in err  # the phase line is NOT shaped like a step
    assert "step 3: read_file a.py [ok]" in err  # a real step keeps its shape


# --- fan-out isolation -------------------------------------------------------


def test_fanout_runs_every_sink_even_when_one_raises() -> None:
    recorded: list[tuple] = []

    def boom(*_a: object) -> None:
        raise RuntimeError("render glitch")

    def recorder(i: int, tool: str, target: str, ok: bool) -> None:
        recorded.append((i, tool, ok))

    fan = make_fanout([boom, recorder])
    fan(0, "read_file", "x", True)
    fan(1, "run_command", "y", False)
    # The raising sink never starves the recorder — every step still lands.
    assert recorded == [(0, "read_file", True), (1, "run_command", False)]


# --- build_progress composition ----------------------------------------------


def test_build_progress_default_path_is_verbatim() -> None:
    default = lambda *_a: None  # noqa: E731
    progress, cockpit = build_progress(
        default_sink=default,
        task_id="t",
        engine="mock",
        tui=False,
        tui_events=None,
        stream=_Stream(isatty=False),
    )
    # No TUI surface requested -> the plain sink is returned unchanged (byte-identical).
    assert progress is default
    assert cockpit is None


def test_build_progress_composes_when_a_surface_is_requested(tmp_path) -> None:
    default = lambda *_a: None  # noqa: E731
    progress, cockpit = build_progress(
        default_sink=default,
        task_id="t",
        engine="mock",
        tui=True,
        tui_events=str(tmp_path / "ev.jsonl"),
        stream=_Stream(isatty=False),
    )
    assert progress is not default  # composed fan-out
    assert isinstance(cockpit, CockpitProgressSink)
