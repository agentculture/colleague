"""Skill-panel widget — renders the ``"skills"`` panel from ``CockpitState.panels``.

If no panel with ``id == "skills"`` is present, or the panel is not visible,
an empty string is returned.  Each :class:`~colleague.tui.state.PanelItem`
is rendered on its own line with a status glyph prefix.
"""

from __future__ import annotations

from colleague.tui.render.layout import SKILL_COL_WIDTH
from colleague.tui.state import CockpitState

# Status glyph map
_STATUS_GLYPH: dict[str, str] = {
    "active": "●",
    "available": "○",
    "disabled": "–",
}
_DEFAULT_GLYPH = "○"

_BORDER = "─"


def _hline(width: int, title: str = "") -> str:
    if title:
        inner = f" {title} "
        pad = max(0, width - len(inner) - 2)
        return "┌" + inner + _BORDER * pad + "┐"
    return "└" + _BORDER * (width - 2) + "┘"


def render_skill_panel(state: CockpitState, *, width: int = SKILL_COL_WIDTH) -> str:
    """Return a box-drawn skills panel string, or ``""`` if absent/hidden.

    *width* defaults to the fixed left-column width so a skills-only render is
    unchanged; the side-by-side layout in :mod:`~colleague.tui.render.ansi`
    passes this column width explicitly.
    """
    panel = next((p for p in state.panels if p.id == "skills"), None)
    if panel is None or not panel.visible:
        return ""

    lines: list[str] = []
    lines.append(_hline(width, panel.title or "Skills"))
    if panel.content_summary:
        lines.append(f"│ {panel.content_summary:<{width - 4}} │")

    for item in panel.items:
        glyph = _STATUS_GLYPH.get(item.status, _DEFAULT_GLYPH)
        label = item.label
        # Truncate if too wide
        max_label = width - 7
        if len(label) > max_label:
            label = label[: max_label - 1] + "…"
        lines.append(f"│ {glyph} {label:<{max_label}} │")

    lines.append(_hline(width))
    return "\n".join(lines)
