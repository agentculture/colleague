"""Stdlib-only ANSI renderer for the colleague TUI cockpit.

Public surface
--------------
:func:`render` — compose all five widget functions into one complete cockpit
frame string.  The function is **pure** and **deterministic**: same state →
same output; no clock, no randomness; spinner animation derives from
``state.background.frame`` only.

Layout
------
::

    ┌ status bar (top) ──────────────────────────────────────────┐
    │ skills panel (left)  │  conversation panel (main)          │
    └────────────────────────────────────────────────────────────┘
    > prompt input (bottom)

    ╔ popup overlay (appended below frame) ╗
    ║ …                                    ║
    ╚══════════════════════════════════════╝

All ANSI SGR helpers are defined locally — no third-party rendering library.
"""

from __future__ import annotations

from colleague.tui.state import CockpitState
from colleague.tui.widgets.command_palette import render_command_palette
from colleague.tui.widgets.conversation import render_conversation
from colleague.tui.widgets.popup_layer import render_popup_layer
from colleague.tui.widgets.prompt_input import render_prompt_input
from colleague.tui.widgets.skill_panel import render_skill_panel
from colleague.tui.widgets.status_bar import render_status_bar

_RESET = "\x1b[0m"
_DIM = "\x1b[2m"
_FRAME_SEP = "─" * 60


def _section(label: str, body: str) -> str:
    """Wrap *body* in a labelled section if *body* is non-empty."""
    if not body:
        return ""
    return f"{_DIM}{label}{_RESET}\n{body}"


def render(state: CockpitState) -> str:
    """Render *state* into a complete cockpit frame string.

    Parameters
    ----------
    state:
        The current :class:`~colleague.tui.state.CockpitState` snapshot.

    Returns
    -------
    str
        A multi-line ANSI-coloured string ready for ``sys.stdout.write``.
        The string is deterministic: the same *state* always produces the same
        output.
    """
    parts: list[str] = []

    # ── top: status bar ──────────────────────────────────────────────────────
    parts.append(render_status_bar(state))
    parts.append(_FRAME_SEP)

    # ── command palette (interactive session menu; empty when no palette) ─────
    palette = render_command_palette(state)
    if palette:
        parts.append(palette)
        parts.append(_FRAME_SEP)

    # ── middle: skills panel + conversation panel (side-by-side via text) ────
    skills = render_skill_panel(state)
    conv = render_conversation(state)

    if skills and conv:
        # Simple side-by-side: skills on left, conversation on right, separated
        skills_lines = skills.splitlines()
        conv_lines = conv.splitlines()
        # Pad shorter column to match heights
        height = max(len(skills_lines), len(conv_lines))
        skills_lines += [""] * (height - len(skills_lines))
        conv_lines += [""] * (height - len(conv_lines))
        middle_lines = [f"{s}  {c}" for s, c in zip(skills_lines, conv_lines)]
        parts.append("\n".join(middle_lines))
    elif skills:
        parts.append(skills)
    elif conv:
        parts.append(conv)

    parts.append(_FRAME_SEP)

    # ── bottom: prompt input ──────────────────────────────────────────────────
    parts.append(render_prompt_input(state))

    # ── overlay: popup layer (appended after main frame) ─────────────────────
    popup_str = render_popup_layer(state)
    if popup_str:
        parts.append("")  # blank line before overlays
        parts.append(popup_str)

    # Join with newlines, stripping trailing whitespace per line for cleanliness
    return "\n".join(line.rstrip() for line in parts)
