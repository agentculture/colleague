"""Command-palette widget — renders the ``"commands"`` panel from ``CockpitState``.

The interactive ``session`` lists its command templates as a panel with
``id == "commands"`` whose items are the templates (one
:class:`~convertible.tui.state.PanelItem` each). This widget renders them as a
**numbered** menu — the number is what the operator types to run a template (line
input; see the ``session`` command).

Returns ``""`` when no ``"commands"`` panel is present or it is not visible
(mirroring the other widgets, so a cockpit without a palette renders unchanged and
the existing render/snapshot tests are untouched).
"""

from __future__ import annotations

from convertible.tui.state import CockpitState

_BORDER = "─"
_PANEL_WIDTH = 56


def _hline(title: str = "") -> str:
    if title:
        inner = f" {title} "
        pad = max(0, _PANEL_WIDTH - len(inner) - 2)
        return "┌" + inner + _BORDER * pad + "┐"
    return "└" + _BORDER * (_PANEL_WIDTH - 2) + "┘"


def render_command_palette(state: CockpitState) -> str:
    """Return a box-drawn, numbered command palette, or ``""`` if absent/hidden."""
    panel = next((p for p in state.panels if p.id == "commands"), None)
    if panel is None or not panel.visible:
        return ""

    max_inner = _PANEL_WIDTH - 4
    lines: list[str] = [_hline(panel.title or "Commands")]
    if panel.content_summary:
        lines.append(f"│ {panel.content_summary[:max_inner]:<{max_inner}} │")

    # "│ NN. <label> │" — leave room for the 2-wide number, dot, and the borders.
    max_label = _PANEL_WIDTH - 8
    for num, item in enumerate(panel.items, start=1):
        label = item.label
        if len(label) > max_label:
            label = label[: max_label - 1] + "…"
        lines.append(f"│ {num:>2}. {label:<{max_label}} │")

    lines.append(_hline())
    return "\n".join(lines)
