"""Colleague ASCII banner shown at drive/session start (decorative chrome).

The art lives in ``_banner.txt`` next to this module so the wide, trailing-
whitespace-laden lines never have to satisfy ``black``/``flake8``. It is loaded
once (``lru_cache``) via :mod:`importlib.resources`, which resolves correctly for
both editable installs and built wheels — and uses only the standard library, so
the ``dependencies = []`` rule is preserved.

The banner is purely decorative, so :func:`emit_banner` shows it **only on an
interactive terminal** and **never in ``--json`` mode**. colleague is itself an
agent harness: agents (and CI) parse stderr for the ``error:``/``hint:`` rubric,
so the art must never prepend to machine-read output — only a human at a TTY sees
it.
"""

from __future__ import annotations

import sys
from functools import lru_cache
from importlib import resources
from typing import Callable


@lru_cache(maxsize=1)
def banner() -> str:
    """Return the colleague ASCII banner, loaded once from the data file."""
    return resources.files(__package__).joinpath("_banner.txt").read_text(encoding="utf-8")


def _isatty() -> bool:
    """Whether the diagnostics stream (stderr) is an interactive terminal.

    Isolated as a module function so tests can force the interactive branch
    without a real TTY (``monkeypatch.setattr`` this name).
    """
    return sys.stderr.isatty()


def emit_banner(emit: Callable[[str], None], *, json_mode: bool) -> None:
    """Emit the banner via ``emit`` — only on an interactive TTY, never in ``--json``.

    The banner is decorative, so two robustness rules apply:

    * A missing/unreadable resource is swallowed — a packaging glitch must never
      break a real drive (only the art is lost, the task still runs).
    * Trailing newlines are stripped and each sink adds its own, so rendering is
      identical whether ``emit`` always appends a newline (``print`` in
      ``session``) or only when absent (``emit_diagnostic`` in ``drive``).
    """
    if json_mode or not _isatty():
        return
    try:
        art = banner()
    except OSError:
        return
    emit(art.rstrip("\n"))
