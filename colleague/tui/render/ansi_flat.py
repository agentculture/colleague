"""Borderless, Markdown-feel ANSI renderer for the ``colleague session`` cockpit.

Why a second ANSI renderer
--------------------------
:mod:`colleague.tui.render.ansi` draws the *boxed* cockpit (used by ``tui
render`` / ``snapshot`` / ``diagnose``).  The interactive ``session`` wants a
lighter, delegation-cockpit look (issue #158): **no box borders**, hierarchy
from spacing + headings (a Markdown feel), colour, and a **moving emoji state
glyph** that animates while a work item runs.  This module is that view.

Single source of truth
----------------------
Like :func:`colleague.tui.render.markdown.render_markdown`, :func:`render_flat`
derives from :func:`colleague.tui.taui.serialize` — so the borderless ANSI view
and the Markdown view are two renders of one dict and cannot drift.  Any new
panel the session adds (``policy`` / ``context``) appears here for free.

Purity
------
:func:`render_flat` is **pure** and **deterministic**: same state → identical
output.  The "moving" glyph derives only from ``work.step_count`` (advanced by
real :class:`~colleague.tui.events.WorkStep` events) and ``status.severity`` —
no clock, no randomness, no animation thread.  Stdlib-only.
"""

from __future__ import annotations

from typing import Any

from colleague.tui.render.layout import DEFAULT_WIDTH
from colleague.tui.state import CockpitState
from colleague.tui.taui import serialize
from colleague.tui.widgets.prompt_input import render_prompt_input

# ── local SGR helpers (no third-party rendering lib) ────────────────────────
_RESET = "\x1b[0m"
_BOLD = "\x1b[1m"
_DIM = "\x1b[2m"
_CYAN = "\x1b[36m"

#: Moon-phase frames — the work-in-progress glyph cycles through these per step,
#: so the emoji visibly *moves* while a work item runs.
_WORK_FRAMES = ("🌑", "🌒", "🌓", "🌔", "🌕", "🌖", "🌗", "🌘")

#: Steady idle glyph by status severity (motion only happens while working).
_IDLE_GLYPH = {"error": "🔴", "warn": "🟡", "success": "🟢", "info": "🟢"}


def _state_glyph(taui: dict[str, Any]) -> str:
    """The state emoji: a cycling work glyph while running, else a steady idle one."""
    work = taui.get("work") or {}
    if work.get("running"):
        return _WORK_FRAMES[int(work.get("step_count", 0)) % len(_WORK_FRAMES)]
    severity = str(taui.get("status", {}).get("severity", "info"))
    return _IDLE_GLYPH.get(severity, "🟢")


def _clip(text: str, width: int) -> str:
    """Truncate *text* to *width* display columns (approximate; borderless)."""
    if width > 0 and len(text) > width:
        return text[: max(1, width - 1)] + "…"
    return text


def _heading(title: str) -> str:
    return f"{_BOLD}{_CYAN}{title}{_RESET}"


def _state_line(taui: dict[str, Any]) -> str:
    """Top line: the moving state glyph + the status message (no box)."""
    message = str(taui.get("status", {}).get("message", ""))
    return f"{_state_glyph(taui)}  {_BOLD}{message}{_RESET}"


def _panel_block(panel: dict[str, Any], width: int) -> list[str]:
    """Render one visible panel as a borderless heading + summary + items.

    Summary lines (the operational strip / the running conversation log / the
    suggested action) are kept verbatim — the terminal soft-wraps them, the
    Markdown feel. Only item text (which includes long template descriptions) is
    truncated to keep each item on one line."""
    title = str(panel.get("title", panel.get("id", "")))
    summary = str(panel.get("content_summary", ""))
    items: list[dict[str, Any]] = panel.get("items", [])
    numbered = panel.get("id") == "commands"  # Work templates keep "type N" affordance

    lines: list[str] = [_heading(title)]
    if summary:
        for raw in summary.splitlines() or [summary]:
            lines.append(f"  {_DIM}{raw}{_RESET}")
    for num, item in enumerate(items, start=1):
        label = str(item.get("label", item.get("id", "")))
        status = str(item.get("status", ""))
        bullet = f"{num}." if numbered else "•"
        text = f"{label} — {status}" if status and status != "available" else label
        lines.append(f"  {_DIM}{bullet}{_RESET} {_clip(text, max(1, width - 4))}")
    return lines


def _popup_block(popup: dict[str, Any], width: int) -> list[str]:
    """Render a visible popup (e.g. a failed-step error) as a flagged block."""
    message = str(popup.get("message", ""))
    lines = [f"⚠️  {_BOLD}{_clip(message, width)}{_RESET}"]
    for action in popup.get("actions", []):
        desc = str(action.get("description", "")) or str(action.get("input", ""))
        lines.append(f"  {_DIM}↳ {action.get('selector', '')} — {desc}{_RESET}")
    return lines


def render_flat(
    state: CockpitState, *, width: int = DEFAULT_WIDTH, include_prompt: bool = True
) -> str:
    """Render *state* as a borderless, colorized, Markdown-feel cockpit frame.

    Parameters mirror :func:`colleague.tui.render.ansi.render`: *width* is used
    only for truncation (there is no right border to align to), and
    *include_prompt* omits the bottom prompt line so the interactive session can
    anchor the typing cursor via :func:`input`.

    Returns a deterministic multi-line ANSI string — same *state* → same output.
    """
    taui = serialize(state)
    blocks: list[list[str]] = [[_state_line(taui)]]

    for panel in taui.get("panels", []):
        if panel.get("visible"):
            blocks.append(_panel_block(panel, width))

    for popup in taui.get("popups", []):
        if popup.get("visible"):
            blocks.append(_popup_block(popup, width))

    # Sections separated by a blank line — hierarchy from spacing, not borders.
    parts = ["\n".join(block) for block in blocks]
    body = "\n\n".join(parts)

    if include_prompt:
        body += "\n\n" + render_prompt_input(state)
    return body
