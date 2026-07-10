"""Owned mid-run input line for ``colleague session`` — a sanctioned reader thread.

While cortex works, the operator keeps typing into the talk lane. Today the lane
reads stdin in cooked mode (``session._poll_talk_lane``), so any update line the
cockpit prints mid-run visually destroys the operator's in-progress typing. This
module owns the bottom input line instead: a single daemon reader thread reads
raw stdin per-character into a private *pending* buffer, and :meth:`print_above`
lifts any cockpit output ABOVE that line and repaints it — a hand-rolled
``patch_stdout`` so typing is never lost.

The reader thread is the **4th recorded thread-confinement sanction** in this
repo (previously ``threading`` was confined to ``colleague/subagents.py``). It is
an operator-decided q1 sanction (the at-home arc): scoped to the colour-TTY
session path only, its :meth:`stop` join is bounded (never hangs), and it
degrades to today's cooked-mode behavior on any setup failure or reader crash.
The corresponding allow-list entry lives in ``tests/test_boundary.py``.

Stdlib only — ``threading`` / ``termios`` / ``tty`` / ``select`` / ``io`` / ``os``
/ ``signal``. No curses, no new dependency, no socket, no daemon.

Design notes
------------
* **Injected streams.** The constructor takes explicit ``stream_in`` /
  ``stream_out`` objects, so the whole class is testable over ``io`` objects or
  an ``os.pipe`` pair with no real terminal.
* **Raw mode only for a real TTY.** When ``stream_in`` is a TTY we save its
  termios settings and switch to cbreak, additionally clearing ``ISIG`` so a
  ``Ctrl-C`` (``0x03``) arrives to us as a byte and is forwarded to
  ``on_interrupt`` instead of being swallowed by the terminal driver. A non-TTY
  stream (tests) is read per-character with no termios at all.
* **The reader never parks in a blocking read.** When the stream exposes a
  pollable fd, each character is preceded by a short ``select`` wait, so the
  reader wakes every ``_READ_POLL_SECONDS`` to re-check the stop event. Without
  this, :meth:`stop` could only take effect on the operator's *next keystroke*:
  its bounded join would time out and return while the thread still held stdin,
  leaving a ghost reader to race the session's cooked reads for the next key.
* **One lock.** The reader's echo path and :meth:`print_above` share a single
  lock, so a repaint can never interleave with an echo.
* **Degrade, never raise.** Any failure arming the line (termios setup, thread
  spawn, or a reader that cannot read) leaves the object disarmed; :meth:`start`
  returns ``False`` and :meth:`print_above` falls back to a plain write, so
  callers keep today's cooked-mode behavior. A reader-thread crash mid-run
  disarms the object rather than propagating.
"""

from __future__ import annotations

import contextlib
import os
import select
import signal
import threading
from typing import Callable, Optional

# Terminal control sequences for the hand-rolled patch_stdout.
_CR = "\r"
_ERASE_LINE = "\x1b[K"  # EL: erase from the cursor to the end of the line.

_ENTER = ("\r", "\n")
_BACKSPACE = ("\x7f", "\x08")
_CTRL_C = "\x03"

# Longest we let :meth:`start` wait to notice an immediate reader crash (a stream
# whose read raises) so it can report a failed arm. A healthy stream blocks on an
# empty fd for far longer than this, so the happy path costs at most this once.
_START_SETTLE_SECONDS = 0.1

# How long the reader waits for a readable fd before looping back to re-check the
# stop event. Bounds how long :meth:`stop` can take on an idle stream; small
# enough to be imperceptible, large enough that an idle line costs ~nothing.
_READ_POLL_SECONDS = 0.05


def _default_interrupt() -> None:
    """Default Ctrl-C handler: raise SIGINT in this process (the main thread)."""
    os.kill(os.getpid(), signal.SIGINT)


def _utf8_continuation_len(lead: int) -> int:
    """Number of continuation bytes that follow a UTF-8 *lead* byte (0 for ASCII)."""
    if lead >= 0xF0:
        return 3
    if lead >= 0xE0:
        return 2
    if lead >= 0xC0:
        return 1
    return 0


class OwnedInputLine:
    """A bottom input line owned by one daemon reader thread; see the module docstring.

    Parameters
    ----------
    stream_in:
        The input stream. A real TTY takes the termios/cbreak raw path; any other
        readable stream (``io`` object, ``os.pipe`` read end) is read per-character.
    stream_out:
        Where echoes, repaints, and :meth:`print_above` output are written.
    prompt:
        The prompt drawn at the start of the input line (default ``"> "``).
    on_line:
        Called with the completed line (verbatim, without the trailing newline)
        each time the operator presses Enter.
    on_interrupt:
        Called when the operator presses Ctrl-C in raw mode. Defaults to raising
        SIGINT in this process; tests inject their own to avoid killing the run.
    """

    def __init__(
        self,
        stream_in: object,
        stream_out: object,
        *,
        prompt: str = "> ",
        on_line: Optional[Callable[[str], None]] = None,
        on_interrupt: Optional[Callable[[], None]] = None,
    ) -> None:
        self._stream_in = stream_in
        self._stream_out = stream_out
        self._prompt = prompt
        self._on_line: Callable[[str], None] = on_line or (lambda _s: None)
        self._on_interrupt: Callable[[], None] = on_interrupt or _default_interrupt

        self._pending = ""  # the in-progress typed line (owned; the bottom line).
        self._last_cr = False  # swallow the "\n" half of a "\r\n" Enter.

        self._lock = threading.Lock()  # shared by the echo path and print_above.
        self._stop_event = threading.Event()
        self._crash_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._armed = False

        # Terminal restore state (real TTY only).
        self._use_fd = False
        self._fd = -1
        self._saved_termios: Optional[list] = None
        self._restored = False

        # The fd the reader polls for readability (None for in-memory streams).
        self._poll_fd: Optional[int] = None

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> bool:
        """Arm the line: set raw mode (TTY only) and spawn the reader thread.

        Returns ``True`` when armed, ``False`` when it degraded (the caller then
        keeps its cooked-mode path). Never raises.
        """
        try:
            self._setup_terminal()
        except Exception:
            self._disarm()
            return False

        self._stop_event.clear()
        self._crash_event.clear()
        try:
            thread = threading.Thread(target=self._reader, name="owned-input-line", daemon=True)
            thread.start()
        except Exception:
            self._disarm()
            return False
        self._thread = thread

        # Settle: give an immediate reader crash (a stream whose read raises) a
        # chance to register so we can report a failed arm. A healthy stream is
        # blocked on its fd and never sets the crash event.
        if self._crash_event.wait(timeout=_START_SETTLE_SECONDS):
            self.stop(timeout=_START_SETTLE_SECONDS)
            return False

        self._armed = True
        with self._lock:
            self._write(self._prompt)
            self._flush()
        return True

    def stop(self, *, timeout: float = 1.0) -> None:
        """Signal the reader to stop and join it bounded; restore the terminal.

        Bounded (``join(timeout=...)``) so it never hangs, and idempotent — safe
        to call more than once. The reader polls for readability rather than
        parking in a blocking read, so it observes the stop event within
        ``_READ_POLL_SECONDS`` and the join returns promptly without needing a
        keystroke to unblock it.

        A thread that somehow outlived the bounded join keeps its handle, so a
        later :meth:`stop` re-joins it instead of silently forgetting a thread
        that may still hold stdin.
        """
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        if thread is None or not thread.is_alive():
            self._thread = None
        self._restore_terminal()
        self._armed = False

    # -- output ------------------------------------------------------------

    def print_above(self, text: str) -> None:
        """Print *text* on its own line ABOVE the input line, then repaint it.

        Thread-safe against the reader's echo path (one shared lock). When the
        line is disarmed this degrades to a plain write, so callers keep today's
        behavior.
        """
        if not self._armed:
            self._plain_write(text)
            return
        with self._lock:
            # Erase the current input line, print the text + newline, then repaint
            # the prompt and the operator's in-progress buffer below it.
            self._write(f"{_CR}{_ERASE_LINE}{text}\n{self._prompt}{self._pending}")
            self._flush()

    def _plain_write(self, text: str) -> None:
        with contextlib.suppress(Exception):
            self._write(f"{text}\n")
            self._flush()

    # -- reader thread -----------------------------------------------------

    def _reader(self) -> None:
        """Reader-thread body: read per-character until stop / EOF; crash disarms."""
        try:
            while not self._stop_event.is_set():
                ch = self._read_one()
                if ch is None:  # Poll tick with no input — re-check the stop event.
                    continue
                if ch == "":  # EOF — the input stream closed.
                    break
                self._handle_char(ch)
        except Exception:
            # A reader-thread crash must never propagate; it disarms the line.
            self._crash_event.set()
            self._armed = False
        finally:
            self._restore_terminal()

    def _handle_char(self, ch: str) -> None:
        if ch == "\r":
            self._last_cr = True
            self._submit()
            return
        if ch == "\n":
            if self._last_cr:  # swallow the "\n" that trails a "\r".
                self._last_cr = False
                return
            self._submit()
            return
        self._last_cr = False
        if ch == _CTRL_C:
            self._interrupt()
            return
        if ch in _BACKSPACE:
            self._backspace()
            return
        if ch.isprintable():
            self._echo(ch)
        # Any other control byte is ignored.

    def _echo(self, ch: str) -> None:
        with self._lock:
            self._pending += ch
            self._write(ch)
            self._flush()

    def _backspace(self) -> None:
        with self._lock:
            if self._pending:
                self._pending = self._pending[:-1]
                self._write("\b \b")  # move back, erase the glyph, move back.
                self._flush()

    def _submit(self) -> None:
        with self._lock:
            line = self._pending
            self._pending = ""
            self._write("\r\n")
            self._flush()
        # Deliver OUTSIDE the lock (on_line may call print_above) and suppress a
        # callback error so it never disarms the reader.
        with contextlib.suppress(Exception):
            self._on_line(line)

    def _interrupt(self) -> None:
        with contextlib.suppress(Exception):
            self._on_interrupt()

    # -- stream + terminal plumbing ---------------------------------------

    def _read_one(self) -> Optional[str]:
        """Read one character (a full UTF-8 codepoint on a real fd).

        Returns ``None`` when the poll tick elapsed with no input waiting (the
        caller loops back to re-check the stop event), ``""`` on EOF, else the
        character.
        """
        if self._poll_fd is not None and not self._wait_readable():
            return None
        if self._use_fd:
            data = os.read(self._fd, 1)
            if not data:
                return ""
            for _ in range(_utf8_continuation_len(data[0])):
                more = os.read(self._fd, 1)
                if not more:
                    break
                data += more
            return data.decode("utf-8", errors="ignore")
        ch = self._stream_in.read(1)  # type: ignore[attr-defined]
        if not ch:
            return ""
        if isinstance(ch, (bytes, bytearray)):
            return bytes(ch).decode("utf-8", errors="ignore")
        return ch

    def _wait_readable(self) -> bool:
        """Wait one poll tick for ``self._poll_fd`` to become readable.

        A ``select`` failure (the fd was closed under us) propagates to the
        reader's crash handler, which disarms the line — the same degrade path as
        any other unreadable stream.
        """
        ready, _, _ = select.select([self._poll_fd], [], [], _READ_POLL_SECONDS)
        return bool(ready)

    def _pollable_fd(self) -> Optional[int]:
        """The input stream's fd when ``select`` can poll it, else ``None``.

        In-memory streams (``io.StringIO``) raise on ``fileno()``; they never
        block, so they need no poll and read straight through to EOF.
        """
        fileno = getattr(self._stream_in, "fileno", None)
        if not callable(fileno):
            return None
        try:
            fd = fileno()
        except Exception:
            return None
        return fd if isinstance(fd, int) and fd >= 0 else None

    def _write(self, text: str) -> None:
        try:
            self._stream_out.write(text)  # type: ignore[attr-defined]
        except TypeError:
            # A binary output stream — encode.
            self._stream_out.write(text.encode("utf-8"))  # type: ignore[attr-defined]

    def _flush(self) -> None:
        flush = getattr(self._stream_out, "flush", None)
        if callable(flush):
            with contextlib.suppress(Exception):
                flush()

    def _setup_terminal(self) -> None:
        """Switch a real TTY to cbreak (ISIG cleared); no-op for a non-TTY stream."""
        is_tty = False
        try:
            is_tty = bool(self._stream_in.isatty())  # type: ignore[attr-defined]
        except Exception:
            is_tty = False
        if not is_tty:
            self._use_fd = False
            # A pipe or socket still blocks, so still poll it; an in-memory
            # stream has no fd and reads straight through.
            self._poll_fd = self._pollable_fd()
            return

        import termios
        import tty

        fd = self._stream_in.fileno()  # type: ignore[attr-defined]
        self._saved_termios = termios.tcgetattr(fd)
        tty.setcbreak(fd)
        # cbreak disables ECHO + ICANON but leaves ISIG on; clear ISIG too so a
        # Ctrl-C reaches us as a 0x03 byte to forward, not a driver-generated
        # signal we can't see.
        mode = termios.tcgetattr(fd)
        mode[3] &= ~termios.ISIG  # index 3 == lflag.
        termios.tcsetattr(fd, termios.TCSADRAIN, mode)
        self._fd = fd
        self._poll_fd = fd
        self._use_fd = True
        self._restored = False

    def _restore_terminal(self) -> None:
        """Restore saved termios settings once (guarded; errors suppressed)."""
        with self._lock:
            if self._restored:
                return
            self._restored = True
            if self._use_fd and self._saved_termios is not None:
                with contextlib.suppress(Exception):
                    import termios

                    termios.tcsetattr(self._fd, termios.TCSADRAIN, self._saved_termios)

    def _disarm(self) -> None:
        self._armed = False
        self._restore_terminal()
