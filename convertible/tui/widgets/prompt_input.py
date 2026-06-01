"""Prompt-input widget — renders the bottom prompt line.

When ``state.focused == "input.prompt"`` the prompt is highlighted with a
focus indicator (``▶``).  Otherwise a plain ``>`` prefix is used.

The spinner character is derived deterministically from
``state.background.frame % 4`` when ``state.background.animation != "none"``
so the output is clock-free and random-free.
"""

from __future__ import annotations

from convertible.tui.state import CockpitState

_SPINNER_CHARS = "|/-\\"
_FOCUSED_PREFIX = "▶ "
_PLAIN_PREFIX = "> "
_RESET = "\x1b[0m"
_DIM = "\x1b[2m"
_BRIGHT = "\x1b[1m"


def render_prompt_input(state: CockpitState) -> str:
    """Return the prompt input line as a string."""
    focused = state.focused == "input.prompt"
    prefix = _FOCUSED_PREFIX if focused else _PLAIN_PREFIX

    # Spinner: only when animation is active
    if state.background.animation != "none":
        spinner = _SPINNER_CHARS[state.background.frame % 4]
        spinner_str = f" {spinner}"
    else:
        spinner_str = ""

    mode = state.mode
    if focused:
        return f"{_BRIGHT}{prefix}{_RESET}[{mode}]{spinner_str} "
    return f"{_DIM}{prefix}{_RESET}[{mode}]{spinner_str} "
