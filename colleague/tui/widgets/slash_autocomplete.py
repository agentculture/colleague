"""Slash-autocomplete widget — a live, filtered popup of slash commands.

Rendered below the ``session`` frame while a human is typing a ``/…`` command on
a colour TTY. The popup lists the slash commands whose name still matches what's
been typed; the **selected** row is shown in reverse video with a ``›`` marker.
An empty match list renders nothing — the popup "disappears" (the vanish case).

Pure ANSI, no ``termios`` — so this stays inside the tui-core import guard
(``tests/test_zero_deps.py``) exactly like the sibling widgets
(``command_palette.py`` / ``popup_layer.py``).
"""

from __future__ import annotations

from typing import Sequence

from colleague.tui.render.layout import DEFAULT_WIDTH

_BORDER = "─"
_RESET = "\x1b[0m"
_REVERSE = "\x1b[7m"


def _hline(width: int, title: str = "") -> str:
    if title:
        inner = f" {title} "
        pad = max(0, width - len(inner) - 2)
        return "┌" + inner + _BORDER * pad + "┐"
    return "└" + _BORDER * (width - 2) + "┘"


def render_slash_autocomplete(
    matches: Sequence[object], selected: int = 0, *, width: int = DEFAULT_WIDTH
) -> str:
    """Return a box-drawn popup of *matches*, or ``""`` when there are none.

    Each match is rendered as ``/<name> <arg_hint> — <description>``; the row at
    *selected* (clamped to range) is highlighted in reverse video with a ``›``.
    *matches* items are duck-typed ``SlashSpec`` (``.name`` / ``.arg_hint`` /
    ``.description``), so this widget never imports the session module.
    """
    if not matches:
        return ""
    sel = max(0, min(selected, len(matches) - 1))
    max_inner = max(1, width - 4)
    lines: list[str] = [_hline(width, "Slash commands")]
    for i, spec in enumerate(matches):
        left = f"/{spec.name}" + (f" {spec.arg_hint}" if spec.arg_hint else "")
        text = f"{left} — {spec.description}" if spec.description else left
        if len(text) > max_inner:
            text = text[: max_inner - 1] + "…"
        if i == sel:
            body = f"›{text}"[:max_inner]
            lines.append(f"│ {_REVERSE}{body:<{max_inner}}{_RESET} │")
        else:
            lines.append(f"│ {text:<{max_inner}} │")
    lines.append(_hline(width))
    return "\n".join(lines)
