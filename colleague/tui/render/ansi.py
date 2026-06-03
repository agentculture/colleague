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

from colleague.tui.render.layout import DEFAULT_WIDTH, GAP_LEN, MIN_WIDTH, SKILL_COL_WIDTH
from colleague.tui.state import CockpitState
from colleague.tui.widgets.command_palette import render_command_palette
from colleague.tui.widgets.conversation import render_conversation
from colleague.tui.widgets.popup_layer import render_popup_layer
from colleague.tui.widgets.prompt_input import render_prompt_input
from colleague.tui.widgets.skill_panel import render_skill_panel
from colleague.tui.widgets.status_bar import render_status_bar

_RESET = "\x1b[0m"
_DIM = "\x1b[2m"


def _section(label: str, body: str) -> str:
    """Wrap *body* in a labelled section if *body* is non-empty."""
    if not body:
        return ""
    return f"{_DIM}{label}{_RESET}\n{body}"


def render(
    state: CockpitState,
    *,
    width: int = DEFAULT_WIDTH,
    include_prompt: bool = True,
) -> str:
    """Render *state* into a complete cockpit frame string.

    Parameters
    ----------
    state:
        The current :class:`~colleague.tui.state.CockpitState` snapshot.
    width:
        Total cockpit width.  Every box and the frame separators derive from it
        so they align.  Defaults to :data:`~colleague.tui.render.layout.DEFAULT_WIDTH`
        (deterministic) — interactive callers pass the detected terminal width.
    include_prompt:
        When ``False`` the bottom prompt-input line is omitted — the interactive
        session uses this so it can print the prompt via :func:`input` and anchor
        the typing cursor on it.  Defaults to ``True`` (full self-contained frame).

    Returns
    -------
    str
        A multi-line ANSI-coloured string ready for ``sys.stdout.write``.
        The string is deterministic: the same *state* and *width* always produce
        the same output.
    """
    frame_sep = "─" * width
    parts: list[str] = []

    # ── top: status bar ──────────────────────────────────────────────────────
    parts.append(render_status_bar(state))
    parts.append(frame_sep)

    # ── command palette (interactive session menu; empty when no palette) ─────
    palette = render_command_palette(state, width=width)
    if palette:
        parts.append(palette)
        parts.append(frame_sep)

    # ── middle: skills panel + conversation panel (side-by-side via text) ────
    # Decide column widths *before* rendering so each box is drawn at its target
    # width: the skills column is fixed, the conversation takes the rest (minus
    # the inter-column gap); a lone conversation gets the full width.
    has_skills = any(p.id == "skills" and p.visible for p in state.panels)
    has_conv = any(
        p.id in ("panel.conversation", "conversation") and p.visible for p in state.panels
    )

    if has_skills and has_conv:
        conv_width = max(MIN_WIDTH, width - SKILL_COL_WIDTH - GAP_LEN)
        skills = render_skill_panel(state, width=SKILL_COL_WIDTH)
        conv = render_conversation(state, width=conv_width)
        skills_lines = skills.splitlines()
        conv_lines = conv.splitlines()
        # Pad shorter column to match heights
        height = max(len(skills_lines), len(conv_lines))
        skills_lines += [""] * (height - len(skills_lines))
        conv_lines += [""] * (height - len(conv_lines))
        gap = " " * GAP_LEN
        middle_lines = [f"{s}{gap}{c}" for s, c in zip(skills_lines, conv_lines)]
        parts.append("\n".join(middle_lines))
        parts.append(frame_sep)
    elif has_skills:
        parts.append(render_skill_panel(state, width=SKILL_COL_WIDTH))
        parts.append(frame_sep)
    elif has_conv:
        parts.append(render_conversation(state, width=width))
        parts.append(frame_sep)
    else:
        parts.append(frame_sep)

    # ── bottom: prompt input ──────────────────────────────────────────────────
    if include_prompt:
        parts.append(render_prompt_input(state))

    # ── overlay: popup layer (appended after main frame) ─────────────────────
    popup_str = render_popup_layer(state, width=width)
    if popup_str:
        parts.append("")  # blank line before overlays
        parts.append(popup_str)

    # Join with newlines, stripping trailing whitespace per line for cleanliness
    return "\n".join(line.rstrip() for line in parts)
