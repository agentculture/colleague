"""Raw-mode line reader with a live slash-command popup (interactive TTY only).

The confined home for the per-keystroke terminal handling the session's ``/``
autocomplete needs. Uses only stdlib ``termios`` / ``tty`` / ``select`` / ``sys``
— no third-party dependency, no socket, no daemon (it lives outside the tui-core
guard so the raw-mode imports are allowed here, not in ``colleague.tui``).

When raw mode is unavailable — stdin is not a TTY, ``termios`` is missing, or the
platform is Windows — :func:`read_line_with_popup` calls the caller-supplied
*fallback* (the plain :func:`input` path), so piped / agent / ``--json`` callers
stay **byte-identical** to the pre-popup behaviour.

The raw loop itself needs a real terminal and is intentionally thin: each piece
(:func:`supports_raw_mode`, the fallback branch, :func:`reduce_key`, the pure
filter, the popup widget) is unit-tested without a TTY, and the orchestration
shell :func:`_raw_loop` is driven end-to-end over an explicit ``os.openpty()``
pair in ``tests/test_session_autocomplete.py`` (a pty pair passed as the
stream/out sidesteps pytest's stdio capture).
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
    except Exception:  # pragma: no cover - termios is always present on the POSIX target
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
    if supports_raw_mode(stream):
        import termios

        try:
            return _raw_loop(specs, render, filter_fn, stream, out)
        except (OSError, ValueError, AttributeError, termios.error):
            # isatty() said yes but a termios op failed at runtime — fall back to
            # plain line input rather than crashing the session.
            pass
    if fallback is not None:
        return fallback()
    try:
        return input()
    except EOFError:
        return None


def _utf8_continuation_len(lead: int) -> int:
    """Number of continuation bytes that follow a UTF-8 *lead* byte (0 for ASCII)."""
    if lead >= 0xF0:
        return 3
    if lead >= 0xE0:
        return 2
    if lead >= 0xC0:
        return 1
    return 0


def _getch(fd: int) -> str:
    """Read one keystroke from *fd*, unbuffered (``os.read``, not a text stream).

    Raw keystroke reading must bypass the buffered text stream: ``stream.read(1)``
    over-reads to fill its buffer and blocks on an interactive fd. A multi-byte
    UTF-8 keystroke (e.g. ``é`` / ``❯``) arrives as several bytes, so the lead
    byte's continuation bytes are pulled too — otherwise non-ASCII input would be
    silently dropped. Returns ``""`` on EOF.
    """
    data = os.read(fd, 1)
    if not data:
        return ""
    for _ in range(_utf8_continuation_len(data[0])):
        more = os.read(fd, 1)
        if not more:
            break
        data += more
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
    return {"A": "UP", "B": "DOWN", "C": "RIGHT", "D": "LEFT", "Z": "SHIFT_TAB"}.get(
        _getch(fd), "ESC"
    )


def _classify_key(ch: str, fd: int) -> Optional[str]:
    """Normalise a raw keystroke into a token, resolving arrow escape sequences.

    Returns ``"EOF"`` / ``"CTRL_C"`` / ``"CTRL_D"`` / ``"ENTER"`` / ``"TAB"`` /
    ``"UP"`` / ``"DOWN"`` / ``"ESC"`` / ``"BACKSPACE"``, a single printable
    character, or ``None`` for an ignored control char.
    """
    if ch == "":
        return "EOF"
    if ch == _CTRL_C:
        return "CTRL_C"
    if ch == _CTRL_D:
        return "CTRL_D"
    if ch in _ENTER:
        return "ENTER"
    if ch == _TAB:
        return "TAB"
    if ch == _ESC:
        return _read_escape(fd)  # UP / DOWN / ESC / RIGHT / LEFT
    if ch in _BACKSPACE:
        return "BACKSPACE"
    if ch.isprintable():
        return ch
    return None


def _key_quit(buffer: str, selected: int, _matches: list) -> tuple[str, int, str]:
    return buffer, selected, "quit"


def _key_ctrl_d(buffer: str, selected: int, _matches: list) -> tuple[str, int, str]:
    # Ctrl-D quits on an empty line; mid-line it is ignored (redraw).
    return (buffer, selected, "quit") if buffer == "" else (buffer, selected, "redraw")


def _key_enter(buffer: str, selected: int, _matches: list) -> tuple[str, int, str]:
    return buffer, selected, "submit"


def _key_tab(buffer: str, _selected: int, matches: list) -> tuple[str, int, str]:
    if matches:
        chosen = matches[_selected]
        buffer = f"/{chosen.name} " if chosen.arg_hint else f"/{chosen.name}"
    return buffer, 0, "redraw"


def _key_up(buffer: str, selected: int, _matches: list) -> tuple[str, int, str]:
    return buffer, selected - 1, "redraw"


def _key_down(buffer: str, selected: int, _matches: list) -> tuple[str, int, str]:
    return buffer, selected + 1, "redraw"


def _key_esc(_buffer: str, _selected: int, _matches: list) -> tuple[str, int, str]:
    return "", 0, "redraw"  # dismiss the popup (clear the slash buffer)


def _key_backspace(buffer: str, _selected: int, _matches: list) -> tuple[str, int, str]:
    return buffer[:-1], 0, "redraw"


#: Sentinel returned by _raw_loop when the user presses Shift-Tab to cycle mode.
CYCLE_MODE = object()


def _key_shift_tab(buffer: str, selected: int, _matches: list) -> tuple[str, int, str]:
    return buffer, selected, "cycle_mode"


#: Named-key → transition. Printable chars and unknowns are handled in reduce_key.
_KEY_HANDLERS: dict[str, Callable[[str, int, list], tuple[str, int, str]]] = {
    "EOF": _key_quit,
    "CTRL_C": _key_quit,
    "CTRL_D": _key_ctrl_d,
    "ENTER": _key_enter,
    "TAB": _key_tab,
    "UP": _key_up,
    "DOWN": _key_down,
    "ESC": _key_esc,
    "BACKSPACE": _key_backspace,
    "SHIFT_TAB": _key_shift_tab,
}


def reduce_key(
    key: Optional[str], buffer: str, selected: int, matches: list
) -> tuple[str, int, str]:
    """Pure transition for one key token → ``(buffer, selected, action)``.

    *action* is ``"quit"`` (return ``None``), ``"submit"`` (return *buffer*), or
    ``"redraw"`` (keep looping). TTY-free, so the whole key map is unit-testable.
    """
    handler = _KEY_HANDLERS.get(key) if key is not None else None
    if handler is not None:
        return handler(buffer, selected, matches)
    if key is not None and len(key) == 1 and key.isprintable():
        return buffer + key, 0, "redraw"  # a printable character
    return buffer, selected, "redraw"  # ignored key


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
            out.write(render(buffer, matches, selected).replace("\n", "\r\n"))  # type: ignore[attr-defined]  # noqa: E501
            out.flush()  # type: ignore[attr-defined]

            key = _classify_key(_getch(fd), fd)
            buffer, selected, action = reduce_key(key, buffer, selected, matches)
            if action == "quit":
                return None
            if action == "cycle_mode":
                return CYCLE_MODE  # type: ignore[return-value]
            if action == "submit":
                out.write("\r\n")  # type: ignore[attr-defined]
                out.flush()  # type: ignore[attr-defined]
                return buffer
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
