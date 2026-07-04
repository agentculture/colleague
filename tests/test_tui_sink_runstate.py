"""CockpitProgressSink adopts the shared run-state helpers (task t8).

Verifies that CockpitProgressSink accumulates a parallel cockpit_run.RunState
via fold(), renders status_line on real steps, and preserves the #206 invariant
(phase notices do not advance step_count).  Also confirms the events sink
remains byte-identical.
"""

from __future__ import annotations

import io
from typing import Any

from agentfront.taui.events import dumps_events, loads_events

from colleague.cli._commands._tui_sink import CockpitProgressSink, make_events_sink
from colleague.cockpit_run import (
    Ledger,
    RunState,
    fold,
    observed_ledger,
    status_line,
)
from colleague.tui.from_work import work_step


class _Stream(io.StringIO):
    def __init__(self, isatty: bool = False) -> None:
        super().__init__()
        self._isatty = isatty

    def isatty(self) -> bool:
        return self._isatty


# ── run-state accumulator ─────────────────────────────────────────


class TestRunStateAccumulator:
    """CockpitProgressSink._run mirrors cockpit_run.fold exactly."""

    def test_run_state_initialized(self) -> None:
        sink = CockpitProgressSink("t1", "mock", stream=_Stream())
        assert isinstance(sink._run, RunState)
        assert sink._run.step_count == 0
        assert sink._run.activities == ()

    def test_run_state_folds_identically_to_standalone_fold(self) -> None:
        """sink._run after a sequence of calls == fold(..., fold(...)) from empty."""
        sink = CockpitProgressSink("t1", "mock", stream=_Stream())
        events: list[tuple[str, str, bool]] = [
            ("", "thinking…", True),
            ("read_file", "main.py", True),
            ("write_file", "src/lib.py", True),
            ("run_command", "pytest -q", True),
            ("", "synthesizing…", True),
            ("edit_file", "src/lib.py", True),
        ]
        # Drive the sink.
        for idx, (tool, target, ok) in enumerate(events):
            sink(idx, tool, target, ok)

        # Fold the same events independently.
        expected = RunState()
        for tool, target, ok in events:
            expected = fold(expected, tool, target, ok)

        assert sink._run == expected

    def test_run_state_tracks_activities(self) -> None:
        sink = CockpitProgressSink("t1", "mock", stream=_Stream())
        sink(0, "write_file", "a.py", True)
        sink(1, "run_command", "pytest", True)
        assert sink._run.step_count == 2
        assert len(sink._run.activities) == 2
        assert sink._run.command_count == 1
        assert "a.py" in sink._run.files_touched

    def test_run_state_phase_updates(self) -> None:
        sink = CockpitProgressSink("t1", "mock", stream=_Stream())
        sink(0, "", "thinking…", True)
        assert sink._run.phase == "thinking…"
        assert sink._run.step_count == 0

    def test_run_state_phase_after_real_step(self) -> None:
        sink = CockpitProgressSink("t1", "mock", stream=_Stream())
        sink(0, "write_file", "a.py", True)
        sink(1, "", "synthesizing…", True)
        assert sink._run.step_count == 1
        assert sink._run.phase == "synthesizing…"
        assert sink._run.last_action == "[write_file] a.py"


# ── #206 invariant: phase notices do not advance step_count ────────


class TestPhaseNoticeInvariant:
    """A phase notice must never advance sink._run.step_count."""

    def test_phase_notice_does_not_advance_run_step_count(self) -> None:
        sink = CockpitProgressSink("t1", "mock", stream=_Stream())
        sink(0, "", "thinking…", True)
        assert sink._run.step_count == 0

    def test_multiple_phase_notices_do_not_advance(self) -> None:
        sink = CockpitProgressSink("t1", "mock", stream=_Stream())
        for phase_text in ["thinking…", "synthesizing…", "compacting…"]:
            sink(0, "", phase_text, True)
        assert sink._run.step_count == 0
        assert sink._run.phase == "compacting…"

    def test_phase_notice_preserves_existing_step_count(self) -> None:
        sink = CockpitProgressSink("t1", "mock", stream=_Stream())
        sink(0, "write_file", "a.py", True)
        assert sink._run.step_count == 1
        sink(1, "", "thinking…", True)
        assert sink._run.step_count == 1  # unchanged


# ── status_line on real steps ─────────────────────────────────────


class TestStatusLineOnRealSteps:
    """After a real step, the frame's status message equals status_line(sink._run, ...)."""

    def test_real_step_status_matches_status_line(self) -> None:
        sink = CockpitProgressSink("t1", "mock", stream=_Stream())
        sink(0, "write_file", "src/main.py", True)

        # The message is the composed run line + an event-stamped elapsed segment
        # appended last (` · <elapsed>`), so match the deterministic prefix; the
        # elapsed itself is a monotonic-clock read and not asserted exactly.
        expected_prefix = status_line(
            sink._run,
            step=sink._state.work_item.step_count,
            max_steps=None,
            elapsed_seconds=None,
        )
        assert sink._state.status.message.startswith(expected_prefix)
        assert sink._state.status.severity == "info"

    def test_real_step_status_includes_elapsed_for_cockpit_parity(self) -> None:
        """`work --tui` shows elapsed just like the session cockpit (Qodo PR #288)."""
        sink = CockpitProgressSink("t1", "mock", stream=_Stream())
        sink(0, "read_file", "a.py", True)
        # elapsed renders as a compact human string ending in 's' (e.g. '0s').
        assert sink._state.status.message.rstrip().endswith("s")

    def test_status_line_contains_last_action(self) -> None:
        sink = CockpitProgressSink("t1", "mock", stream=_Stream())
        sink(0, "run_command", "make test", True)
        assert "[run_command] make test" in sink._state.status.message

    def test_status_line_contains_step_count(self) -> None:
        sink = CockpitProgressSink("t1", "mock", stream=_Stream())
        sink(0, "read_file", "a.py", True)
        sink(1, "write_file", "b.py", True)
        assert "step 2" in sink._state.status.message

    def test_status_line_after_phase_then_real_step_clears_the_phase(self) -> None:
        """Phase notice sets the phase text; a subsequent real step REPLACES it
        with the composed run status line (``phase=""`` — the step/op replaces
        the phase, it never lingers), matching the session's ``_WorkSink``."""
        sink = CockpitProgressSink("t1", "mock", stream=_Stream())
        sink(0, "", "thinking…", True)
        sink(1, "write_file", "a.py", True)
        msg = sink._state.status.message
        assert "thinking" not in msg  # the phase text is cleared on the real step
        assert "step 1" in msg
        assert "[write_file] a.py" in msg


# ── observed_ledger property ──────────────────────────────────────


class TestObservedLedger:
    """CockpitProgressSink exposes observed_ledger via a ledger property."""

    def test_ledger_property_exists(self) -> None:
        sink = CockpitProgressSink("t1", "mock", stream=_Stream())
        assert hasattr(sink, "ledger")

    def test_ledger_matches_observed_ledger(self) -> None:
        sink = CockpitProgressSink("t1", "mock", stream=_Stream())
        sink(0, "write_file", "a.py", True)
        sink(1, "run_command", "pytest", True)
        sink(2, "edit_file", "b.py", True)

        ledger = sink.ledger
        expected = observed_ledger(sink._run)
        assert ledger == expected
        assert isinstance(ledger, Ledger)
        assert ledger.files_changed == 2
        assert ledger.commands_run == 1
        assert ledger.commits is None
        assert ledger.publish_state == ""

    def test_ledger_empty_initially(self) -> None:
        sink = CockpitProgressSink("t1", "mock", stream=_Stream())
        ledger = sink.ledger
        assert ledger.files_changed == 0
        assert ledger.commands_run == 0


# ── events sink byte-identity ─────────────────────────────────────


class TestEventsSinkByteIdentity:
    """make_events_sink output is byte-identical to pre-change behaviour."""

    def test_events_sink_writes_work_step_lines(self, tmp_path: Any) -> None:
        path = tmp_path / "ev.jsonl"
        sink = make_events_sink(str(path))
        sink(0, "write_file", "a.py", True)
        sink(1, "run_command", "pytest", True)

        lines = path.read_text().splitlines()
        assert len(lines) == 2

        # Each line must be valid JSON matching work_step output.
        events = loads_events(path.read_text())
        assert [(e.label, e.ok) for e in events] == [
            ("[write_file] a.py", True),
            ("[run_command] pytest", True),
        ]

    def test_events_sink_skips_phase_notices(self, tmp_path: Any) -> None:
        path = tmp_path / "ev.jsonl"
        sink = make_events_sink(str(path))
        sink(0, "write_file", "a.py", True)
        sink(1, "", "thinking…", True)  # phase notice
        sink(2, "finish", "done", True)

        events = loads_events(path.read_text())
        # Phase notice produces NO line.
        assert len(events) == 2
        assert [(e.label, e.ok) for e in events] == [
            ("[write_file] a.py", True),
            ("[finish] done", True),
        ]

    def test_events_sink_byte_identical_to_dumps_events(self, tmp_path: Any) -> None:
        """The JSONL written by make_events_sink must be byte-identical to
        dumps_events([work_step(...)]) for each real step."""
        path = tmp_path / "ev.jsonl"
        sink = make_events_sink(str(path))
        steps = [
            ("write_file", "a.py", True),
            ("run_command", "pytest", True),
            ("edit_file", "b.py", False),
        ]
        for idx, (tool, target, ok) in enumerate(steps):
            sink(idx, tool, target, ok)

        written = path.read_text()
        # Reconstruct expected lines from work_step + dumps_events.
        expected_lines: list[str] = []
        for tool, target, ok in steps:
            expected_lines.append(dumps_events([work_step(tool, target, ok)]))
        expected = "".join(expected_lines)
        assert written == expected

    def test_events_sink_only_real_steps_no_phase(self, tmp_path: Any) -> None:
        """Mixed phase + real steps: only real steps appear in JSONL."""
        path = tmp_path / "ev.jsonl"
        sink = make_events_sink(str(path))
        sink(0, "", "thinking…", True)
        sink(1, "read_file", "main.py", True)
        sink(2, "", "synthesizing…", True)
        sink(3, "write_file", "out.py", True)

        events = loads_events(path.read_text())
        assert len(events) == 2
        assert events[0].label == "[read_file] main.py"
        assert events[1].label == "[write_file] out.py"
