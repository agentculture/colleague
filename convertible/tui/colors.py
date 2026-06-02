"""Color/TTY gating for convertible's terminal output (stdlib only).

The TUI ANSI renderer emits SGR escape sequences unconditionally — right for a
real terminal, noise in a logfile.  This module centralizes the two decisions
that gate color on the *output* side:

* :func:`should_color` — whether to emit color at all (honors ``NO_COLOR`` and
  requires an interactive TTY, mirroring :func:`convertible.cli._banner._isatty`); and
* :func:`strip_ansi` — remove escape sequences from already-colored text, so a
  rendered cockpit frame can be written cleanly to a non-TTY stream.

Used by the live drive cockpit (it strips escapes when ``not should_color``) and
available to any plain status-line emitter that wants to colorize only when a
human is watching.  No network, no third-party deps.
"""

from __future__ import annotations

import os
import re
import sys
from typing import IO, Optional

#: Matches CSI escape sequences (e.g. ``\x1b[31m``, ``\x1b[2J``) — the only kind
#: the stdlib ANSI renderer and widgets emit.
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def should_color(stream: Optional[IO[str]] = None) -> bool:
    """Whether to emit ANSI color on *stream* (default :data:`sys.stderr`).

    Returns ``False`` when the ``NO_COLOR`` environment variable is set to a
    non-empty value (per https://no-color.org) or when *stream* is not an
    interactive terminal.  Mirrors the banner's TTY gate so color and decorative
    chrome agree about when a human is watching.
    """
    if os.environ.get("NO_COLOR"):
        return False
    stream = stream if stream is not None else sys.stderr
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError):
        return False


def strip_ansi(text: str) -> str:
    """Return *text* with all ANSI CSI escape sequences removed."""
    return _ANSI_RE.sub("", text)
