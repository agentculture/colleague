"""Slash-autocomplete widget — a live, filtered, **grouped** popup of slash commands.

Rendered below the ``session`` frame while a human is typing a ``/…`` command on
a colour TTY. The popup lays the matching slash commands out as a small **tree**:
one icon per top-level group (``📁 Controls`` / ``📁 Inspect`` / ``📁 Session``)
with each command shown under its group as ``/name <arg>  <tag badges>`` (issue
#160). The **selected** row is shown in reverse video with a ``›`` marker and its
one-line summary on a dim sub-line. An empty match list renders nothing — the
popup "disappears" (the vanish case).

This module also owns the shared **tag vocabulary** + group display constants so
the popup, the ``/help`` text, and the cockpit Markdown/JSON tiers all format
tags identically and cannot drift. By invariant this widget **never imports the
session module** — ``session.py`` imports *from* here (no cycle).

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
_BOLD = "\x1b[1m"
_DIM = "\x1b[2m"

# ---------------------------------------------------------------------------
# Shared tag vocabulary + group display (issue #160)
# ---------------------------------------------------------------------------

#: Display order + heading for each intent group. The popup tree, the ``/help``
#: text, and the cockpit slash panels all iterate this so a command always lands
#: under the same group label. ``session.py`` imports it for ``/help``.
SLASH_GROUPS: list[tuple[str, str]] = [
    ("controls", "Controls"),
    ("inspect", "Inspect"),
    ("session", "Session"),
]

#: One visual anchor per top-level group (design rule: group = one icon).
GROUP_ICON = "📁"

#: Tag → compact text badge. Only the sanctioned tags the catalog uses
#: (a stable subset of issue #160's vocabulary).
TAG_TEXT: dict[str, str] = {
    "read-only": "[read-only]",
    "writes": "[writes]",
    "git": "[git]",
    "pr": "[pr]",
    "audit": "[audit]",
    "human-loop": "[human-loop]",
    "interactive": "[interactive]",
    "memory": "[memory]",
    "config": "[config]",
    "telemetry": "[telemetry]",
    "model": "[model]",
    "safe": "[safe]",
}

#: Tag → emoji badge for the optional compact display mode.
TAG_ICON: dict[str, str] = {
    "read-only": "👁",
    "writes": "✍",
    "git": "🌿",
    "pr": "🚀",
    "audit": "🔎",
    "human-loop": "🧑",
    "interactive": "💬",
    "memory": "🧠",
    "config": "⚙",
    "telemetry": "📡",
    "model": "🧬",
    "safe": "🛡",
}


def format_tags(tags: Sequence[str], style: str = "text") -> str:
    """Render *tags* as a space-joined badge string. Never raises.

    ``style="text"`` (default) yields ``[read-only] [config]``; ``style="icons"``
    yields the emoji compact form. An unknown tag falls back to ``[tag]`` (text)
    or the bare word (icons), so a new catalog tag is shown, not dropped.
    """
    if not tags:
        return ""
    if style == "icons":
        return " ".join(TAG_ICON.get(t, t) for t in tags)
    return " ".join(TAG_TEXT.get(t, f"[{t}]") for t in tags)


def _hline(width: int, title: str = "") -> str:
    if title:
        inner = f" {title} "
        pad = max(0, width - len(inner) - 2)
        return "┌" + inner + _BORDER * pad + "┐"
    return "└" + _BORDER * (width - 2) + "┘"


def _row(inner: str, max_inner: int, *, sgr: str = "") -> str:
    """One bordered popup row: *inner* fitted to *max_inner*, optionally wrapped
    in an SGR code (reverse for the selection, bold for a header, dim for a
    summary). Truncation matches the legacy widget (``…`` suffix)."""
    if len(inner) > max_inner:
        inner = inner[: max_inner - 1] + "…"
    if sgr:
        return f"│ {sgr}{inner:<{max_inner}}{_RESET} │"
    return f"│ {inner:<{max_inner}} │"


def _group_order(matches: Sequence[object]) -> list[str]:
    """Group keys in display order: the known groups first, then any unexpected
    group seen in *matches* (so a mis-tagged command is still shown, last)."""
    order = [key for key, _ in SLASH_GROUPS]
    for spec in matches:
        key = getattr(spec, "group", "") or "session"
        if key not in order:
            order.append(key)
    return order


def render_slash_autocomplete(
    matches: Sequence[object],
    selected: int = 0,
    *,
    width: int = DEFAULT_WIDTH,
    style: str = "text",
) -> str:
    """Return a box-drawn **grouped** popup of *matches*, or ``""`` when empty.

    *matches* is the flat, catalog-ordered filter result; it is bucketed by
    ``spec.group`` into ``📁`` group sections (filtering preserves group
    context). Each command renders as ``/<name> <arg_hint>  <tags>``; the row at
    *selected* (a flat index into *matches*, clamped) is highlighted in reverse
    video with a ``›`` and gains a dim summary sub-line. *style* selects the tag
    badge form (``"text"`` default | ``"icons"``). *matches* items are
    duck-typed ``SlashSpec`` (``.name`` / ``.arg_hint`` / ``.description`` /
    ``.group`` / ``.tags``), so this widget never imports the session module.
    """
    if not matches:
        return ""
    sel = max(0, min(selected, len(matches) - 1))
    max_inner = max(1, width - 4)

    # Bucket the flat matches by group, remembering each match's flat index so
    # the selection highlight maps back to the (group-agnostic) navigation model.
    buckets: dict[str, list[tuple[int, object]]] = {}
    for i, spec in enumerate(matches):
        key = getattr(spec, "group", "") or "session"
        buckets.setdefault(key, []).append((i, spec))
    titles = dict(SLASH_GROUPS)

    lines: list[str] = [_hline(width, "Slash commands")]
    for key in _group_order(matches):
        members = buckets.get(key)
        if not members:
            continue
        lines.append(_row(f"{GROUP_ICON} {titles.get(key, key.title())}", max_inner, sgr=_BOLD))
        for i, spec in members:
            left = f"/{spec.name}" + (f" {spec.arg_hint}" if spec.arg_hint else "")
            tags = format_tags(getattr(spec, "tags", ()), style)
            text = f"{left}  {tags}".rstrip()
            if i == sel:
                lines.append(_row(f"› {text}", max_inner, sgr=_REVERSE))
                summary = str(getattr(spec, "description", "") or "")
                if summary:
                    lines.append(_row(f"    {summary}", max_inner, sgr=_DIM))
            else:
                lines.append(_row(f"  {text}", max_inner))
    lines.append(_hline(width))
    return "\n".join(lines)
