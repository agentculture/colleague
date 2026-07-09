"""At-home arc (task t5): the session talk lane owns its input line on a colour TTY.

The clobber problem this fixes: while a work item runs, the operator keeps typing
into the talk lane. Pre-fix the session read stdin in cooked mode and redrew the
whole cockpit (a full-frame ``\\x1b[H\\x1b[2J`` clear-home) at every progress-sink
boundary — which visually DESTROYS the operator's in-progress tty echo (the
program can't repaint what the terminal driver echoed and it can't see). Post-fix,
when the talk lane arms on a live colour TTY the session takes ownership of the
bottom input line via :class:`~colleague.cli._commands._input_line.OwnedInputLine`:
mid-run output routes through ``print_above`` (scroll ABOVE the input line + repaint
the operator's pending buffer below) instead of a clobbering full-frame redraw.

These exercise the wiring directly over INJECTED io streams (the ``_owned_line_streams``
test seam) — no real TTY, no real work run — mirroring ``test_session_talk_lane.py``.
"""

from __future__ import annotations

import contextlib
import io
import os
import time
from pathlib import Path

from agentfront.taui.widgets.prompt_input import plain_prompt

from colleague.cli._commands import session as session_mod
from colleague.cli._commands.session import SensesSessionOptions, SessionIO, _Session
from colleague.config import EngineConfig, SensesConfig
from colleague.contract import OK, Task, TaskResult


class _CollectingOut:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, *args: object, **kwargs: object) -> None:
        self.lines.append(" ".join(str(a) for a in args))

    def text(self) -> str:
        return "\n".join(self.lines)


def _senses_config() -> EngineConfig:
    config = EngineConfig.resolve(model="cortex-model")
    config.senses = SensesConfig(
        model="senses-model", base_url="http://senses", api_key="k", context_budget=24000
    )
    return config


def _session(tmp_path: Path, *, view: str = "ansi", config=None, cortex_only: bool = False):
    out, err = _CollectingOut(), _CollectingOut()
    result = TaskResult(task_id="t", status=OK, summary="s")

    def _fake_work(**kwargs: object):
        return result, Path(str(tmp_path)) / ".colleague" / "art.json"

    sess = _Session(
        repo=tmp_path,
        engine_name="mock",
        open_pr=False,
        base="main",
        config=config if config is not None else _senses_config(),
        json_mode=False,
        view=view,
        io=SessionIO(out=out, err=err),
        work_fn=_fake_work,
        senses_options=SensesSessionOptions(cortex_only=cortex_only),
    )
    return sess, out, err


def _wait_for(predicate, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


# --- THE clobber reproduction: armed → route above the pending line ----------


def test_armed_line_routes_mid_run_output_above_pending(tmp_path: Path) -> None:
    """Post-fix: an update line printed while input is pending leaves the pending
    line intact — the mid-run print routes through OwnedInputLine.print_above, so
    the repaint sequence (erase-line · the text · newline · prompt+pending) appears
    in the owned line's output stream, NOT a full-frame clobber."""
    sess, out, _err = _session(tmp_path, view="ansi")
    fake_out = io.StringIO()
    # The test seam forces arming over injected streams (no real TTY needed);
    # an empty stream_in makes the reader thread EOF-exit immediately.
    sess._owned_line_streams = (io.StringIO(""), fake_out)
    sess._arm_owned_line()
    assert sess._owned_line is not None  # armed on the (fake) colour TTY

    # The operator has typed a partial line into the owned bottom line.
    sess._owned_line._pending = "wip typing"
    fake_out.seek(0)
    fake_out.truncate(0)  # isolate the mid-run write from the arm-time prompt

    # A mid-run update line is logged + emitted (the _WorkSink / senses path).
    sess._log("senses: on it")
    sess.emit()

    written = fake_out.getvalue()
    prompt = plain_prompt(context="colleague")
    # print_above lifted the line ABOVE the input and repainted prompt+pending.
    assert f"\r\x1b[Ksenses: on it\n{prompt}wip typing" in written
    # Nothing hit the plain chrome sink — no full-frame clear-home clobber.
    assert out.text() == ""


def test_unarmed_line_full_frame_redraw_has_no_repaint(tmp_path: Path) -> None:
    """Pre-fix contrast (today's broken behavior): with no owned line the mid-run
    emit is a full-frame clear-home redraw straight to the chrome sink — the
    print_above repaint sequence is ABSENT (this frame is what clobbers a cooked
    operator's in-progress typing, and is exactly what the armed path replaces)."""
    sess, out, _err = _session(tmp_path, view="ansi")
    assert sess._owned_line is None  # today's path: no owned line

    sess._log("senses: on it")
    sess.emit()

    written = out.text()
    assert "\x1b[2J" in written  # a full-frame clear-home redraw
    assert "\r\x1b[Ksenses: on it" not in written  # no print_above repaint shape


# --- gating: byte-identical when not on a live colour TTY --------------------


def test_arm_owned_line_noop_when_not_live_and_no_seam(tmp_path: Path) -> None:
    """Without the test seam AND outside the live loop, arming is a strict no-op
    (the cooked _poll_talk_lane path stays) — so the existing direct-construction
    talk-lane tests are byte-identical."""
    sess, _o, _e = _session(tmp_path, view="ansi")
    assert sess._live is False
    sess._arm_owned_line()
    assert sess._owned_line is None


def test_begin_talk_lane_does_not_arm_owned_line_when_not_live(tmp_path: Path) -> None:
    """`_begin_talk_lane` arms the talk lane but NOT the owned input line when the
    session isn't in the live interactive loop — byte-identical to pre-t5."""
    sess, _o, _e = _session(tmp_path, view="ansi")
    task = Task.new(str(tmp_path), "scan")
    sess._begin_talk_lane(task)
    assert sess._talk_active is True  # talk lane still arms (existing behavior)
    assert task.watch is True
    assert sess._owned_line is None  # but the owned line does not (not live)


# --- poll: drains the queue (never stdin) when the owned line is armed --------


def test_poll_drains_queue_not_stdin_when_owned(tmp_path: Path, monkeypatch) -> None:
    """When the owned line is armed, _poll_talk_lane never touches stdin (the
    reader thread owns it) — it only drains the thread's queue into
    _handle_talk_input, on the main thread, each line VERBATIM."""
    sess, _o, _e = _session(tmp_path, view="ansi")
    sess._owned_line_streams = (io.StringIO(""), io.StringIO())
    sess._arm_owned_line()
    assert sess._owned_line is not None
    sess._talk_active = True

    # select must NEVER be consulted while the owned line reads stdin for us.
    monkeypatch.setattr(
        session_mod.select,
        "select",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("polled stdin")),
    )
    recorded: list[str] = []
    monkeypatch.setattr(sess, "_handle_talk_input", lambda t: recorded.append(t))

    sess._enqueue_talk("cortex: focus on tests")
    sess._poll_talk_lane()

    assert recorded == ["cortex: focus on tests"]  # verbatim, via the queue drain


def test_on_line_callback_is_the_enqueue_seam(tmp_path: Path) -> None:
    """The owned line's on_line callback only enqueues (thread-safe hand-off);
    it is NOT _handle_talk_input directly (that runs on the main thread)."""
    sess, _o, _e = _session(tmp_path, view="ansi")
    sess._owned_line_streams = (io.StringIO(""), io.StringIO())
    sess._arm_owned_line()
    assert sess._owned_line is not None
    assert sess._owned_line._on_line == sess._enqueue_talk


# --- reader-thread end-to-end: a submitted line reaches the queue verbatim ----


def test_reader_thread_enqueues_submitted_line_verbatim(tmp_path: Path) -> None:
    r, w = os.pipe()
    stream_in = os.fdopen(r, "rb", buffering=0)  # unbuffered → no read-ahead block
    sess, _o, _e = _session(tmp_path, view="ansi")
    sess._owned_line_streams = (stream_in, io.StringIO())
    sess._arm_owned_line()
    assert sess._owned_line is not None
    try:
        os.write(w, b"cortex: focus\n")
        assert _wait_for(lambda: len(sess._owned_talk_queue) >= 1)
        assert list(sess._owned_talk_queue) == ["cortex: focus"]
    finally:
        os.close(w)
        sess._disarm_owned_line()  # bounded, idempotent — joins the reader thread
        with contextlib.suppress(Exception):
            stream_in.close()


# --- stop() on work-item exit + session exit ---------------------------------


def test_end_talk_lane_stops_and_clears_owned_line(tmp_path: Path) -> None:
    sess, _o, _e = _session(tmp_path, view="ansi")
    sess._talk_active = True
    sess._owned_line_streams = (io.StringIO(""), io.StringIO())
    sess._arm_owned_line()
    line = sess._owned_line
    assert line is not None

    sess._end_talk_lane()
    assert sess._owned_line is None  # cleared back to the cooked path
    assert line._armed is False  # the underlying line was stopped (disarmed)


def test_disarm_owned_line_is_idempotent(tmp_path: Path) -> None:
    sess, _o, _e = _session(tmp_path, view="ansi")
    # No owned line ever armed — disarm is a strict no-op.
    sess._disarm_owned_line()
    assert sess._owned_line is None
    # Arm, then disarm twice — the second call must not raise.
    sess._owned_line_streams = (io.StringIO(""), io.StringIO())
    sess._arm_owned_line()
    sess._disarm_owned_line()
    sess._disarm_owned_line()
    assert sess._owned_line is None
