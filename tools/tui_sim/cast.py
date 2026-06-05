"""Pure-stdlib asciinema **v2** cast writer + an SGR stripper.

An asciinema ``.cast`` file is just a JSON header line followed by one
``[time, "o", data]`` output event per line (see the `asciinema file format v2
<https://docs.asciinema.org/manual/asciicast/v2/>`_). No third-party library is
needed — :mod:`json` is enough.

Timestamps are derived from each frame's *hold duration*, never from a wall
clock, and the header omits the optional ``timestamp`` field. A regenerated cast
is therefore byte-identical to the committed one, so the recordings are safe to
check in and a determinism guard test can pin them.
"""

from __future__ import annotations

import json
import re
from typing import Sequence

#: Cursor-home + clear-screen — prepended to every frame so each fully repaints.
#: Matches the live loops (``session._CLEAR_HOME`` / ``driver._CLEAR``).
CLEAR = "\x1b[H\x1b[2J"

#: A frame is ``(body, hold_ms)`` — the ANSI body and how long it stays on screen.
Frame = "tuple[str, int]"

_CSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def strip_sgr(text: str) -> str:
    """Return *text* with every CSI escape (colour, clear, cursor move) removed."""
    return _CSI_RE.sub("", text)


def to_cast(
    frames: Sequence["tuple[str, int]"],
    *,
    width: int,
    height: int,
    title: str = "",
) -> str:
    """Serialize ``(body, hold_ms)`` *frames* into an asciinema v2 cast string.

    Each frame becomes one output event ``[t, "o", CLEAR + body]`` where ``t`` is
    the cumulative hold (in seconds) of all preceding frames — so a player shows
    frame *i* for exactly ``hold_ms`` before painting frame *i+1*. The header
    carries ``width`` / ``height`` (and an optional ``title``) but no
    ``timestamp``, keeping the output reproducible.
    """
    header: dict = {"version": 2, "width": width, "height": height}
    if title:
        header["title"] = title
    lines = [json.dumps(header, ensure_ascii=False)]
    elapsed = 0.0
    for body, hold_ms in frames:
        lines.append(json.dumps([round(elapsed, 3), "o", CLEAR + body], ensure_ascii=False))
        elapsed += max(0, int(hold_ms)) / 1000.0
    return "\n".join(lines) + "\n"
