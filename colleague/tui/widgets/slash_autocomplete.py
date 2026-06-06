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


def _clip(text: str, width: int) -> str:
    """Truncate *text* to *width* display columns (approximate; borderless)."""
    if width > 0 and len(text) > width:
        return text[: max(1, width - 1)] + "…"
    return text


def _line(text: str, width: int, *, sgr: str = "") -> str:
    """One borderless popup line: *text* clipped to *width*, optionally wrapped in
    an SGR code (reverse for the selection, bold for a header, dim for a summary)."""
    clipped = _clip(text, width)
    return f"{sgr}{clipped}{_RESET}" if sgr else clipped


def _group_order(matches: Sequence[object]) -> list[str]:
    """Group keys in display order: the known groups first, then any unexpected
    group seen in *matches* (so a mis-tagged command is still shown, last)."""
    order = [key for key, _ in SLASH_GROUPS]
    for spec in matches:
        key = getattr(spec, "group", "") or "session"
        if key not in order:
            order.append(key)
    return order


def _command_lines(index: int, spec: object, *, selected: int, width: int, style: str) -> list[str]:
    """The borderless line(s) for one command: an indented ``/name <arg>  <tags>``
    row, reverse-highlighted with a ``›`` (plus a dim summary sub-line) when it is
    the *selected* row."""
    left = f"/{spec.name}" + (f" {spec.arg_hint}" if spec.arg_hint else "")  # type: ignore[attr-defined]  # noqa: E501
    text = f"{left}  {format_tags(getattr(spec, 'tags', ()), style)}".rstrip()
    if index != selected:
        return [_line(f"  {text}", width)]
    rows = [_line(f"› {text}", width, sgr=_REVERSE)]
    summary = str(getattr(spec, "description", "") or "")
    if summary:
        rows.append(_line(f"    {summary}", width, sgr=_DIM))
    return rows


def render_slash_autocomplete(
    matches: Sequence[object],
    selected: int = 0,
    *,
    width: int = DEFAULT_WIDTH,
    style: str = "text",
) -> str:
    """Return a **borderless, grouped** popup of *matches*, or ``""`` when empty.

    No box frame — hierarchy comes from a ``📁`` heading per group and indented
    command rows (the Markdown-feel of the session cockpit, #158). *matches* is
    the flat, catalog-ordered filter result, bucketed by ``spec.group`` so
    filtering preserves group context. Each command renders as
    ``/<name> <arg_hint>  <tags>``; the row at *selected* (a flat index into
    *matches*, clamped) is reverse-highlighted with a ``›`` and gains a dim
    summary sub-line. *style* selects the tag badge form (``"text"`` default |
    ``"icons"``). *matches* items are duck-typed ``SlashSpec`` (``.name`` /
    ``.arg_hint`` / ``.description`` / ``.group`` / ``.tags``), so this widget
    never imports the session module.
    """
    if not matches:
        return ""
    sel = max(0, min(selected, len(matches) - 1))

    # Bucket the flat matches by group, remembering each match's flat index so
    # the selection highlight maps back to the (group-agnostic) navigation model.
    buckets: dict[str, list[tuple[int, object]]] = {}
    for i, spec in enumerate(matches):
        key = getattr(spec, "group", "") or "session"
        buckets.setdefault(key, []).append((i, spec))
    titles = dict(SLASH_GROUPS)

    lines: list[str] = []
    for key in _group_order(matches):
        members = buckets.get(key)
        if not members:
            continue
        lines.append(_line(f"{GROUP_ICON} {titles.get(key, key.title())}", width, sgr=_BOLD))
        for i, spec in members:
            lines.extend(_command_lines(i, spec, selected=sel, width=width, style=style))
    return "\n".join(lines)
