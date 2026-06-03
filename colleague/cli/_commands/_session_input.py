"""Raw-mode line reader with a live slash-command popup (interactive TTY only).

The confined home for the per-keystroke terminal handling the session's ``/``
autocomplete needs. Uses only stdlib ``termios`` / ``tty`` / ``select`` / ``sys``
— no third-party dependency, no socket, no daemon (it lives outside the tui-core
guard so the raw-mode imports are allowed here, not in ``colleague.tui``).

When raw mode is unavailable — stdin is not a TTY, ``termios`` is missing, or the
platform is Windows — :func:`read_line_with_popup` calls the caller-supplied
*fallback* (the plain :func:`input` path), so piped / agent / ``--json`` callers
stay **byte-identical** to the pre-popup behaviour.

The raw loop itself needs a real terminal and is intentionally thin; the testable
surface is :func:`supports_raw_mode` (the gate) plus the fallback branch. The
pure filter and the popup widget are tested independently.
"""

from __future__ import annotations

import os
import select
import sys
from typing import Callable, Optional, Sequence

# Key bytes (raw mode delivers one char at a time, untranslated).
_ENTER = ("\r", "\n")
_BACKSPACE = ("\x7f", "\b")
_TAB = "\t"
_ESC = "\x1b"
_CTRL_C = "\x03"
_CTRL_D = "\x04"

#: render(buffer, matches, selected) -> the full screen to draw.
RenderFn = Callable[[str, list, int], str]
#: filter(prefix, specs) -> the matching specs.
FilterFn = Callable[[str, Sequence[object]], list]


def supports_raw_mode(stream: object = None) -> bool:
    """Return ``True`` only when *stream* is a POSIX TTY with ``termios``.

    Any of: a non-TTY stream, a stream without ``isatty``, Windows, or a missing
    ``termios``/``tty`` import → ``False`` (the caller falls back to ``input``).
    """
    stream = sys.stdin if stream is None else stream
    try:
        if not stream.isatty():  # type: ignore[attr-defined]
            return False
    except Exception:
        return False
    if sys.platform.startswith("win"):
        return False
    try:
        import termios  # noqa: F401
        import tty  # noqa: F401
    except Exception:
        return False
    return True


def read_line_with_popup(
    specs: Sequence[object],
    render: RenderFn,
    filter_fn: FilterFn,
    *,
    stream: object = None,
    out: object = None,
    fallback: Optional[Callable[[], Optional[str]]] = None,
) -> Optional[str]:
    """Read one line, drawing a live slash-command popup as the user types.

    On a POSIX colour TTY this runs the raw per-keystroke loop; otherwise it
    delegates to *fallback* (or a plain :func:`input` when none is given),
    returning that verbatim. Returns the typed line, or ``None`` on EOF / quit.
    """
    stream = sys.stdin if stream is None else stream
    out = sys.stdout if out is None else out
    if not supports_raw_mode(stream):
        if fallback is not None:
            return fallback()
        try:
            return input()
        except EOFError:
            return None
    return _raw_loop(specs, render, filter_fn, stream, out)


def _getch(fd: int) -> str:
    """Read one keystroke from *fd*, unbuffered (``os.read``, not a text stream).

    Raw keystroke reading must bypass the buffered text stream: ``stream.read(1)``
    over-reads to fill its buffer and blocks on an interactive fd. Returns ``""``
    on EOF.
    """
    data = os.read(fd, 1)
    if not data:
        return ""
    return data.decode("utf-8", errors="ignore")


def _read_escape(fd: int) -> str:
    """Disambiguate an ESC: an arrow sends ``[A``/``[B``; a bare ESC sends nothing.

    Uses a short ``select`` timeout so a lone ESC does not block waiting for a
    follow-up byte.
    """
    ready, _, _ = select.select([fd], [], [], 0.05)
    if not ready:
        return "ESC"
    if _getch(fd) != "[":
        return "ESC"
    return {"A": "UP", "B": "DOWN", "C": "RIGHT", "D": "LEFT"}.get(_getch(fd), "ESC")


def _raw_loop(
    specs: Sequence[object], render: RenderFn, filter_fn: FilterFn, stream: object, out: object
) -> Optional[str]:
    import termios
    import tty

    fd = stream.fileno()  # type: ignore[attr-defined]
    saved = termios.tcgetattr(fd)
    buffer = ""
    selected = 0
    try:
        tty.setraw(fd)
        while True:
            matches = filter_fn(buffer[1:], specs) if buffer.startswith("/") else []
            selected = max(0, min(selected, len(matches) - 1)) if matches else 0
            # Raw mode disables NL->CRNL translation, so emit CRLF for clean redraw.
            screen = render(buffer, matches, selected).replace("\n", "\r\n")
            out.write(screen)  # type: ignore[attr-defined]
            out.flush()  # type: ignore[attr-defined]

            ch = _getch(fd)
            if ch == "" or ch == _CTRL_D:
                if buffer == "":
                    return None  # EOF / Ctrl-D on an empty line → quit
                continue
            if ch == _CTRL_C:
                return None  # clean exit, no traceback
            if ch in _ENTER:
                out.write("\r\n")  # type: ignore[attr-defined]
                out.flush()  # type: ignore[attr-defined]
                return buffer
            if ch == _TAB:
                if matches:
                    sel = matches[selected]
                    buffer = f"/{sel.name} " if sel.arg_hint else f"/{sel.name}"
                    selected = 0
                continue
            if ch == _ESC:
                seq = _read_escape(fd)
                if seq == "UP":
                    selected -= 1
                elif seq == "DOWN":
                    selected += 1
                else:  # bare ESC → dismiss the popup (clear the slash buffer)
                    buffer = ""
                    selected = 0
                continue
            if ch in _BACKSPACE:
                buffer = buffer[:-1]
                selected = 0
                continue
            if ch.isprintable():
                buffer += ch
                selected = 0
            # other control chars are ignored
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
