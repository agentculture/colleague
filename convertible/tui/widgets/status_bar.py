"""Status-bar widget — renders ``CockpitState.status`` as a coloured line.

Severity → SGR colour mapping
------------------------------
- ``"error"``   → 31 (red)
- ``"warn"``    → 33 (yellow)
- ``"success"`` → 32 (green)
- ``"info"``    → 36 (cyan)
- anything else → 36 (cyan, same as info)

The message text is ALWAYS present verbatim regardless of colour support;
colour is a *reflection* of the severity data, never the sole carrier of
meaning.
"""

from __future__ import annotations

from convertible.tui.state import CockpitState

# ANSI SGR helpers
_RESET = "\x1b[0m"
_BOLD = "\x1b[1m"

_SEVERITY_COLOUR: dict[str, str] = {
    "error": "\x1b[31m",
    "warn": "\x1b[33m",
    "success": "\x1b[32m",
    "info": "\x1b[36m",
}
_DEFAULT_COLOUR = "\x1b[36m"

# Severity labels shown in the bar
_SEVERITY_LABEL: dict[str, str] = {
    "error": "ERR",
    "warn": "WRN",
    "success": "OK ",
    "info": "INF",
}
_DEFAULT_LABEL = "INF"


def render_status_bar(state: CockpitState) -> str:
    """Return a one-line status bar string for *state*.

    Format::

        [ERR] <message>

    The severity prefix and the text that follows are wrapped in the
    appropriate SGR colour sequence; the reset code follows.
    """
    sev = state.status.severity
    colour = _SEVERITY_COLOUR.get(sev, _DEFAULT_COLOUR)
    label = _SEVERITY_LABEL.get(sev, _DEFAULT_LABEL)
    msg = state.status.message
    return f"{colour}{_BOLD}[{label}]{_RESET} {colour}{msg}{_RESET}"
