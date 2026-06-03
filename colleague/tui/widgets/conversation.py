"""Conversation widget — renders the conversation panel from ``CockpitState``.

Shows the panel title and ``content_summary`` (one box row per logical line, so a
live drive's per-step lines stack). Returns an empty string when no conversation
panel is present or it is not visible.

The reducer writes the conversation under id ``"panel.conversation"``; older
states and direct callers use the bare ``"conversation"``. Both are accepted so a
real drive (reducer-produced) renders identically to a hand-built state.
"""

from __future__ import annotations

from typing import Optional

from colleague.tui.render.layout import DEFAULT_WIDTH
from colleague.tui.state import CockpitState, Panel

_BORDER = "─"
#: Panel ids that hold the conversation, in lookup priority order.
_CONVERSATION_IDS = ("panel.conversation", "conversation")


def _hline(width: int, title: str = "") -> str:
    if title:
        inner = f" {title} "
        pad = max(0, width - len(inner) - 2)
        return "╔" + inner + _BORDER * pad + "╗"
    return "╚" + _BORDER * (width - 2) + "╝"


def _find_conversation(state: CockpitState) -> Optional[Panel]:
    for pid in _CONVERSATION_IDS:
        panel = next((p for p in state.panels if p.id == pid), None)
        if panel is not None:
            return panel
    return None


def render_conversation(state: CockpitState, *, width: int = DEFAULT_WIDTH) -> str:
    """Return a box-drawn conversation panel string, or ``""`` if absent/hidden.

    *width* is the full box width; the wrap point is ``width - 4`` inner chars, so
    a wider box wraps later (a narrow box is what mangled multi-line slash output).
    """
    panel = _find_conversation(state)
    if panel is None or not panel.visible:
        return ""

    max_inner = width - 4
    lines: list[str] = [_hline(width, panel.title or "Conversation")]

    rows = panel.content_summary.split("\n") if panel.content_summary else []
    if not rows:
        lines.append(f"║ {'(empty)':<{max_inner}} ║")
    for row in rows:
        # Wrap each logical line at the panel width; pad the tail for clean edges.
        while len(row) > max_inner:
            lines.append(f"║ {row[:max_inner]} ║")
            row = row[max_inner:]
        lines.append(f"║ {row:<{max_inner}} ║")

    lines.append(_hline(width))
    return "\n".join(lines)
