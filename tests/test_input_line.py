"""Tests for :class:`colleague.cli._commands._input_line.OwnedInputLine`.

The sanctioned reader-thread that owns raw stdin during a live ``colleague
session`` run (the 4th recorded thread-confinement sanction — operator-decided
q1, at-home arc). Every test drives the object with in-memory ``io`` streams or
an ``os.pipe`` pair — **no real TTY is needed** — and every blocking read is
bounded either by a writer that closes the pipe or by a ``stop(timeout=...)``,
so the suite can never hang.
"""

from __future__ import annotations

import io
import os
import time
from typing import Callable

from colleague.cli._commands._input_line import OwnedInputLine

# ---------------------------------------------------------------------------
# Helpers — bounded polling so a race never turns into a hang.
# ---------------------------------------------------------------------------


def _wait_for(pred: Callable[[], bool], *, timeout: float = 2.0, interval: float = 0.005) -> bool:
    """Poll *pred* until it is truthy or *timeout* elapses; return its final value."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(interval)
    return bool(pred())


class _Pipe:
    """A blocking ``os.pipe`` presented as a readable byte stream + a write fd.

    The read end is a non-TTY unbuffered binary stream (``isatty()`` → ``False``),
    so ``OwnedInputLine`` takes its non-termios per-character path; the reader
    thread blocks on an empty pipe exactly like a real fd would.
    """

    def __init__(self) -> None:
        self._r_fd, self._w_fd = os.pipe()
        self.reader = os.fdopen(self._r_fd, "rb", buffering=0)

    def feed(self, data: bytes) -> None:
        os.write(self._w_fd, data)

    def close(self) -> None:
        # Close the write end first so a blocked reader unblocks at EOF, then
        # drop the read stream. Both are best-effort — the reader thread is a
        # daemon and never blocks interpreter shutdown.
        for closer in (lambda: os.close(self._w_fd), self.reader.close):
            try:
                closer()
            except OSError:
                pass


# ---------------------------------------------------------------------------
# print_above — output appears ABOVE a repainted input line (patch_stdout).
# ---------------------------------------------------------------------------


def test_print_above_repaints_pending_input_below_the_printed_line() -> None:
    """A mid-run print erases the input line, writes text, then repaints prompt+buffer."""
    pipe = _Pipe()
    out = io.StringIO()
    line = OwnedInputLine(pipe.reader, out, prompt="> ", on_line=lambda _s: None)
    try:
        assert line.start() is True
        pipe.feed(b"tell it to")
        assert _wait_for(lambda: line._pending == "tell it to")

        line.print_above("update!")
        got = out.getvalue()
        # \r + EL erase, the printed text, a newline, then prompt + repainted buffer.
        expected = "\r\x1b[K" + "update!" + "\n" + "> tell it to"
        assert expected in got, repr(got)
    finally:
        line.stop(timeout=1.0)
        pipe.close()


# ---------------------------------------------------------------------------
# Echo — typed characters appear instantly, without any print_above call.
# ---------------------------------------------------------------------------


def test_typed_chars_echo_immediately() -> None:
    """Each typed char is echoed to the output stream as it is read."""
    pipe = _Pipe()
    out = io.StringIO()
    line = OwnedInputLine(pipe.reader, out, on_line=lambda _s: None)
    try:
        assert line.start() is True
        pipe.feed(b"abc")
        assert _wait_for(lambda: line._pending == "abc")
        assert "abc" in out.getvalue()
    finally:
        line.stop(timeout=1.0)
        pipe.close()


# ---------------------------------------------------------------------------
# Enter — the completed line is delivered verbatim and the buffer resets.
# ---------------------------------------------------------------------------


def test_enter_delivers_full_line_verbatim_and_resets_buffer() -> None:
    """Pressing Enter hands the whole buffer to on_line verbatim and clears it."""
    delivered: list[str] = []
    pipe = _Pipe()
    out = io.StringIO()
    line = OwnedInputLine(pipe.reader, out, on_line=delivered.append)
    try:
        assert line.start() is True
        pipe.feed(b"  hello world  \n")
        assert _wait_for(lambda: delivered == ["  hello world  "])
        assert delivered == ["  hello world  "]  # verbatim — no strip
        assert line._pending == ""  # buffer reset after delivery
    finally:
        line.stop(timeout=1.0)
        pipe.close()


def test_backspace_edits_the_pending_buffer() -> None:
    """0x7f removes the last buffered character before delivery."""
    delivered: list[str] = []
    pipe = _Pipe()
    out = io.StringIO()
    line = OwnedInputLine(pipe.reader, out, on_line=delivered.append)
    try:
        assert line.start() is True
        pipe.feed(b"abX\x7fc\n")  # a, b, X, <bs>, c, Enter  => "abc"
        assert _wait_for(lambda: delivered == ["abc"])
        assert delivered == ["abc"]
    finally:
        line.stop(timeout=1.0)
        pipe.close()


# ---------------------------------------------------------------------------
# stop() — bounded join even against a blocked reader, and idempotent.
# ---------------------------------------------------------------------------


def test_stop_joins_within_timeout_and_is_idempotent() -> None:
    """stop() returns within its timeout on a blocked reader and is safe to call twice."""
    pipe = _Pipe()  # never fed => the reader blocks on read
    out = io.StringIO()
    line = OwnedInputLine(pipe.reader, out, on_line=lambda _s: None)
    try:
        assert line.start() is True
        started = time.monotonic()
        line.stop(timeout=0.3)
        elapsed = time.monotonic() - started
        assert elapsed < 2.0, f"stop() was not bounded: {elapsed:.2f}s"
        assert line._armed is False
        # Second call is a no-op — must not raise.
        line.stop(timeout=0.3)
    finally:
        pipe.close()


# ---------------------------------------------------------------------------
# Ctrl-C — 0x03 is forwarded to the injectable on_interrupt callback.
# ---------------------------------------------------------------------------


def test_ctrl_c_calls_the_injected_interrupt_callback() -> None:
    """A 0x03 byte invokes on_interrupt (never the default self-SIGINT in tests)."""
    interrupts: list[int] = []
    pipe = _Pipe()
    out = io.StringIO()
    line = OwnedInputLine(
        pipe.reader,
        out,
        on_line=lambda _s: None,
        on_interrupt=lambda: interrupts.append(1),
    )
    try:
        assert line.start() is True
        pipe.feed(b"\x03")
        assert _wait_for(lambda: interrupts == [1])
    finally:
        line.stop(timeout=1.0)
        pipe.close()


# ---------------------------------------------------------------------------
# Degrade — a stream whose read raises disarms; print_above falls back to a
# plain write and start() reports failure.
# ---------------------------------------------------------------------------


class _RaisingStream:
    """A non-TTY stream whose read raises — models a broken/unusable stdin."""

    def isatty(self) -> bool:
        return False

    def read(self, _n: int = 1) -> bytes:
        raise RuntimeError("boom")


def test_start_disarms_when_the_stream_read_raises() -> None:
    """A reader that cannot read disarms; print_above degrades to a plain write."""
    out = io.StringIO()
    line = OwnedInputLine(_RaisingStream(), out, on_line=lambda _s: None)
    try:
        ok = line.start()
        # Either start() reports failure synchronously, or the reader crash
        # disarms the object moments later — both leave it disarmed.
        _wait_for(lambda: line._armed is False)
        assert line._armed is False
        assert ok is False

        out.truncate(0)
        out.seek(0)
        line.print_above("degraded-line")
        assert out.getvalue() == "degraded-line\n"
    finally:
        line.stop(timeout=1.0)


def test_print_above_before_start_is_a_plain_write() -> None:
    """Never-armed object: print_above is a plain write (today's cooked-mode behavior)."""
    out = io.StringIO()
    line = OwnedInputLine(io.BytesIO(b""), out, on_line=lambda _s: None)
    line.print_above("plain")
    assert out.getvalue() == "plain\n"
    # stop() on a never-started object is safe.
    line.stop(timeout=0.2)
