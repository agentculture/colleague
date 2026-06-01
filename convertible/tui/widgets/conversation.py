"""Conversation widget — renders the ``"conversation"`` panel from ``CockpitState``.

Shows the panel title and ``content_summary``.  If no ``"conversation"`` panel
is present or it is not visible, returns an empty string.
"""

from __future__ import annotations

from convertible.tui.state import CockpitState

_BORDER = "─"
_PANEL_WIDTH = 50


def _hline(title: str = "") -> str:
    if title:
        inner = f" {title} "
        pad = max(0, _PANEL_WIDTH - len(inner) - 2)
        return "╔" + inner + _BORDER * pad + "╗"
    return "╚" + _BORDER * (_PANEL_WIDTH - 2) + "╝"


def render_conversation(state: CockpitState) -> str:
    """Return a box-drawn conversation panel string, or ``""`` if absent/hidden."""
    panel = next((p for p in state.panels if p.id == "conversation"), None)
    if panel is None or not panel.visible:
        return ""

    lines: list[str] = []
    title = panel.title or "Conversation"
    lines.append(_hline(title))

    summary = panel.content_summary
    if summary:
        # Wrap long summaries at panel width
        max_inner = _PANEL_WIDTH - 4
        while len(summary) > max_inner:
            lines.append(f"║ {summary[:max_inner]} ║")
            summary = summary[max_inner:]
        lines.append(f"║ {summary:<{max_inner}} ║")
    else:
        lines.append(f"║ {'(empty)':<{_PANEL_WIDTH - 4}} ║")

    lines.append(_hline())
    return "\n".join(lines)
