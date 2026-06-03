"""Popup-layer widget — renders all VISIBLE popups in ``CockpitState.popups``.

Hidden popups (``visible=False``) are silently skipped.  Each visible popup
renders as a simple box with its kind/id as title, its ``message``, and a
list of action labels.
"""

from __future__ import annotations

from colleague.tui.render.layout import DEFAULT_WIDTH
from colleague.tui.state import CockpitState, Popup

_BORDER_H = "─"
_RESET = "\x1b[0m"
_YELLOW = "\x1b[33m"
_CYAN = "\x1b[36m"
_BOLD = "\x1b[1m"

# Map kind to a human-readable title prefix
_KIND_TITLE: dict[str, str] = {
    "skill_suggestion": "Skill Suggestion",
    "confirmation": "Confirmation",
    "error": "Error",
    "progress": "Progress",
    "diff": "Diff",
    "help": "Help",
}


def _popup_title(popup: Popup) -> str:
    kind_label = _KIND_TITLE.get(popup.kind, popup.kind.replace("_", " ").title())
    return f"{kind_label} [{popup.id}]"


def _box_top(width: int, title: str) -> str:
    inner = f" {title} "
    pad = max(0, width - len(inner) - 2)
    return f"╔{inner}{_BORDER_H * pad}╗"


def _box_bottom(width: int) -> str:
    return "╚" + _BORDER_H * (width - 2) + "╝"


def _box_line(width: int, text: str) -> str:
    max_inner = max(1, width - 4)
    if len(text) > max_inner:
        text = text[: max_inner - 1] + "…"
    return f"║ {text:<{max_inner}} ║"


def _render_popup(popup: Popup, width: int) -> str:
    lines: list[str] = []
    title = _popup_title(popup)
    lines.append(f"{_YELLOW}{_BOLD}{_box_top(width, title)}{_RESET}")

    # Message — may be multi-line; split on newlines first
    max_inner = max(1, width - 4)
    for raw_line in (popup.message or "").splitlines() or [""]:
        while len(raw_line) > max_inner:
            lines.append(_box_line(width, raw_line[:max_inner]))
            raw_line = raw_line[max_inner:]
        lines.append(_box_line(width, raw_line))

    # Actions
    if popup.actions:
        lines.append(_box_line(width, ""))  # blank separator
        action_labels = "  ".join(
            f"[{a.description}]" if a.description else f"[{a.input}]" for a in popup.actions
        )
        lines.append(_box_line(width, action_labels))

    lines.append(f"{_YELLOW}{_box_bottom(width)}{_RESET}")
    return "\n".join(lines)


def render_popup_layer(state: CockpitState, *, width: int = DEFAULT_WIDTH) -> str:
    """Return rendered string for all visible popups, separated by blank lines.

    Returns an empty string if there are no visible popups.
    """
    parts: list[str] = []
    for popup in state.popups:
        if popup.visible:
            parts.append(_render_popup(popup, width))
    return "\n\n".join(parts)
