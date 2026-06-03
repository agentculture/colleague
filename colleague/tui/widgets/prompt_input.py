"""Prompt-input widget — renders the bottom prompt line.

The prompt is a clean ``colleague ❯`` chevron — the ``colleague`` prefix is the
context (which tool you're talking to) and ``❯`` signals "type here". When
``state.focused == "input.prompt"`` it renders bright; otherwise dim.

The spinner character is derived deterministically from
``state.background.frame % 4`` when ``state.background.animation != "none"``
so the output is clock-free and random-free.

:func:`plain_prompt` returns the same prompt text *without* ANSI escapes — the
interactive session passes it to :func:`input` so the typing cursor anchors right
after ``colleague ❯`` (escapes in an ``input`` prompt confuse readline's cursor
math, so the plain form is used there).
"""

from __future__ import annotations

from colleague.tui.state import CockpitState

_SPINNER_CHARS = "|/-\\"
#: The bare prompt text (no ANSI) — context word + chevron + trailing space.
_PROMPT = "colleague ❯ "
_RESET = "\x1b[0m"
_DIM = "\x1b[2m"
_BRIGHT = "\x1b[1m"


def plain_prompt() -> str:
    """Return the prompt text with no ANSI escapes (for :func:`input`)."""
    return _PROMPT


def render_prompt_input(state: CockpitState) -> str:
    """Return the prompt input line as a string."""
    focused = state.focused == "input.prompt"

    # Spinner: only when animation is active
    if state.background.animation != "none":
        spinner = _SPINNER_CHARS[state.background.frame % 4]
        spinner_str = f"{spinner} "
    else:
        spinner_str = ""

    weight = _BRIGHT if focused else _DIM
    return f"{weight}colleague ❯{_RESET} {spinner_str}".rstrip() + " "
