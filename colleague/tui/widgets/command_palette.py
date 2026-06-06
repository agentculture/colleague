"""Command-palette widget — renders the ``"commands"`` panel from ``CockpitState``.

The interactive ``session`` lists its command templates as a panel with
``id == "commands"`` whose items are the templates (one
:class:`~colleague.tui.state.PanelItem` each). This widget renders them as a
**numbered** menu — the number is what the operator types to run a template (line
input; see the ``session`` command).

Returns ``""`` when no ``"commands"`` panel is present or it is not visible
(mirroring the other widgets, so a cockpit without a palette renders unchanged and
the existing render/snapshot tests are untouched).
"""

from __future__ import annotations

from colleague.tui.render.layout import DEFAULT_WIDTH
from colleague.tui.state import CockpitState

_BORDER = "─"


def _hline(width: int, title: str = "") -> str:
    if title:
        inner = f" {title} "
        pad = max(0, width - len(inner) - 2)
        return "┌" + inner + _BORDER * pad + "┐"
    return "└" + _BORDER * (width - 2) + "┘"


def render_command_palette(state: CockpitState, *, width: int = DEFAULT_WIDTH) -> str:
    """Return a box-drawn, numbered command palette, or ``""`` if absent/hidden."""
    panel = next((p for p in state.panels if p.id == "commands"), None)
    if panel is None or not panel.visible:
        return ""

    max_inner = max(1, width - 4)
    lines: list[str] = [_hline(width, panel.title or "Work templates")]
    if panel.content_summary:
        lines.append(f"│ {panel.content_summary[:max_inner]:<{max_inner}} │")

    # "│ NN. <label> │" — leave room for the 2-wide number, dot, and the borders.
    max_label = max(1, width - 8)
    for num, item in enumerate(panel.items, start=1):
        label = item.label
        if len(label) > max_label:
            label = label[: max_label - 1] + "…"
        lines.append(f"│ {num:>2}. {label:<{max_label}} │")

    lines.append(_hline(width))
    return "\n".join(lines)
