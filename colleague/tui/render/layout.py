"""Shared width contract for the colleague TUI cockpit.

A single source of truth for the box/column widths every widget and the ANSI
renderer use, so the cockpit's boxes and frame separators always *align* (they
all derive from one width) and the clamping rules live in one place.

Two regimes share these constants:

* **Headless / deterministic callers** (snapshot, ``tui render``, ``diagnose``,
  the injected driver loop, and every test) call ``render``/the widgets with the
  default ``DEFAULT_WIDTH`` — so their output is stable and reproducible.
* **Interactive callers** (the foreground ``session`` and the live TTY driver)
  pass :func:`detect_width` so the cockpit fills the real terminal.

Stdlib-only (``shutil``) — zero third-party imports, matching the rest of the
TUI package.
"""

from __future__ import annotations

import shutil

#: Default cockpit width used by every headless / deterministic caller.  Matches
#: the :func:`shutil.get_terminal_size` fallback so detection and the default
#: agree, and stays under the repo's 100-column lint limit.
DEFAULT_WIDTH = 80

#: Clamp floor.  Below this the boxes would produce negative padding / borders;
#: clamping keeps a tiny terminal degraded-but-valid rather than crashing.
MIN_WIDTH = 40

#: Fixed width of the left **skills** column when it is rendered side-by-side
#: with the conversation panel (preserves the historical skill-panel width).
SKILL_COL_WIDTH = 30

#: Number of spaces separating the two side-by-side columns.
GAP_LEN = 2


def detect_width() -> int:
    """Return the current terminal width, clamped to :data:`MIN_WIDTH`.

    Uses stdlib :func:`shutil.get_terminal_size` with a ``DEFAULT_WIDTH``
    fallback (so a non-tty / piped stdout yields the deterministic default).
    """
    cols = shutil.get_terminal_size(fallback=(DEFAULT_WIDTH, 24)).columns
    return max(MIN_WIDTH, cols)
