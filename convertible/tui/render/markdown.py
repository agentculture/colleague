"""Stdlib-only Markdown renderer for the convertible TUI cockpit.

Public surface
--------------
:func:`render_markdown` — serialize a :class:`~convertible.tui.state.CockpitState`
into a human- and agent-readable Markdown string.

Design
------
The renderer derives from :func:`convertible.tui.taui.serialize` — the same
single source of truth that the TAUI JSON mirror uses.  Both views are two
renders of one dict, so they cannot drift.

Reading-completeness guarantee
-------------------------------
Every fact that :func:`~convertible.tui.taui.serialize` marks *visible* appears
in the Markdown output, so an agent reading *only* the Markdown misses nothing
the JSON would have told it:

- ``screen`` / ``mode`` / ``focused``
- Visible zones (by name)
- Visible panels: title, content_summary, items (label + status)
- Visible popups: ``"<Kind Label> [<id>]"`` title (verbatim, for the
  ``diagnose._detect_render`` checker) **and** the ``message`` field verbatim
- Status: severity + message
- Drive info (when present): task_id, engine, step_count, running
- All ``available_actions``: selector + description

Hidden zones, panels, and popups are omitted entirely — their ``visible=False``
state is implicit by absence.

Compatibility
-------------
The :func:`diagnose._detect_render` checker looks for each visible popup's
``message`` text (and/or a title of the form ``"<Kind Label> [<id>]"``) in the
rendered frame.  This renderer includes both, so the checker passes cleanly.

Purity
------
The function is **pure** and **deterministic**: same state → identical Markdown;
no clock, no randomness.  Stdlib-only — no third-party imports.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from convertible.tui.state import CockpitState

from convertible.tui.taui import serialize

# ---------------------------------------------------------------------------
# Kind → human-readable label (kept in sync with popup_layer widget and
# diagnose._popup_title — all three must agree on the label mapping).
# ---------------------------------------------------------------------------

_KIND_LABEL: dict[str, str] = {
    "skill_suggestion": "Skill Suggestion",
    "confirmation": "Confirmation",
    "error": "Error",
    "progress": "Progress",
    "diff": "Diff",
    "help": "Help",
}


def _popup_title(popup: dict[str, Any]) -> str:
    """Return the canonical ``"<Kind Label> [<id>]"`` title for *popup*.

    Mirrors :func:`convertible.tui.diagnose._popup_title` and the
    ``_popup_title`` helper in :mod:`convertible.tui.widgets.popup_layer`
    so the ``diagnose._detect_render`` check finds the title verbatim.
    """
    kind = str(popup.get("kind", ""))
    label = _KIND_LABEL.get(kind, kind.replace("_", " ").title())
    return f"{label} [{popup.get('id', '')}]"


# ---------------------------------------------------------------------------
# Section builders — each returns a Markdown string (may be empty)
# ---------------------------------------------------------------------------


def _section_cockpit(taui: dict[str, Any]) -> str:
    """Top-level heading: screen, mode, focused."""
    screen = taui.get("screen", "")
    mode = taui.get("mode", "")
    focused = taui.get("focused", "")
    lines = [
        "# Cockpit",
        "",
        f"- **screen**: {screen}",
        f"- **mode**: {mode}",
        f"- **focused**: {focused}",
    ]
    return "\n".join(lines)


def _section_zones(taui: dict[str, Any]) -> str:
    """Zones section: list visible zone names."""
    zones: dict[str, Any] = taui.get("zones", {})
    visible = [name for name, zd in zones.items() if zd.get("visible")]
    if not visible:
        return ""
    lines = ["## Zones", ""]
    for name in visible:
        lines.append(f"- {name}")
    return "\n".join(lines)


def _section_panels(taui: dict[str, Any]) -> str:
    """Panels section: one sub-heading per visible panel."""
    panels: list[dict[str, Any]] = taui.get("panels", [])
    visible = [p for p in panels if p.get("visible")]
    if not visible:
        return ""
    lines = ["## Panels", ""]
    for panel in visible:
        title = str(panel.get("title", panel.get("id", "")))
        summary = str(panel.get("content_summary", ""))
        items: list[dict[str, Any]] = panel.get("items", [])

        lines.append(f"### {title}")
        if summary:
            lines.append("")
            lines.append(summary)
        if items:
            lines.append("")
            for item in items:
                label = str(item.get("label", item.get("id", "")))
                status = str(item.get("status", ""))
                status_part = f" ({status})" if status else ""
                lines.append(f"- {label}{status_part}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _section_popups(taui: dict[str, Any]) -> str:
    """Popups section: one sub-heading per VISIBLE popup.

    Each visible popup includes:
    - The canonical ``"<Kind Label> [<id>]"`` title (for diagnose compatibility)
    - The ``message`` field verbatim
    - The list of action selectors + descriptions
    """
    popups: list[dict[str, Any]] = taui.get("popups", [])
    visible = [p for p in popups if p.get("visible")]
    if not visible:
        return ""
    lines = ["## Popups", ""]
    for popup in visible:
        title = _popup_title(popup)
        message = str(popup.get("message", ""))
        actions: list[dict[str, Any]] = popup.get("actions", [])

        lines.append(f"### {title}")
        lines.append("")
        if message:
            lines.append(message)
            lines.append("")
        if actions:
            lines.append("**Actions:**")
            lines.append("")
            for action in actions:
                selector = str(action.get("selector", ""))
                description = str(action.get("description", ""))
                inp = str(action.get("input", ""))
                desc_part = f" — {description}" if description else ""
                lines.append(f"- `{selector}` ({inp}){desc_part}")
            lines.append("")
    return "\n".join(lines).rstrip()


def _section_status(taui: dict[str, Any]) -> str:
    """Status bar section: severity and message."""
    status: dict[str, Any] = taui.get("status", {})
    severity = str(status.get("severity", "info"))
    message = str(status.get("message", ""))
    lines = ["## Status", ""]
    lines.append(f"- **severity**: {severity}")
    if message:
        lines.append(f"- **message**: {message}")
    return "\n".join(lines)


def _section_drive(taui: dict[str, Any]) -> str:
    """Drive section: task_id, engine, step_count, running (omitted when None)."""
    drive: dict[str, Any] | None = taui.get("drive")
    if drive is None:
        return ""
    task_id = str(drive.get("task_id", ""))
    engine = str(drive.get("engine", ""))
    step_count = drive.get("step_count", 0)
    running = bool(drive.get("running", False))
    lines = [
        "## Drive",
        "",
        f"- **task_id**: {task_id}",
        f"- **engine**: {engine}",
        f"- **step_count**: {step_count}",
        f"- **running**: {running}",
    ]
    return "\n".join(lines)


def _section_available_actions(taui: dict[str, Any]) -> str:
    """Available actions section: flat bullet list of selector + description."""
    actions: list[dict[str, Any]] = taui.get("available_actions", [])
    lines = ["## Available Actions", ""]
    for action in actions:
        selector = str(action.get("selector", ""))
        description = str(action.get("description", ""))
        inp = str(action.get("input", ""))
        desc_part = f" — {description}" if description else ""
        lines.append(f"- `{selector}` ({inp}){desc_part}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def render_markdown(state: "CockpitState") -> str:
    """Render *state* as a human- and agent-readable Markdown string.

    Parameters
    ----------
    state:
        The current :class:`~convertible.tui.state.CockpitState` snapshot.

    Returns
    -------
    str
        A deterministic Markdown string.  Same *state* → identical output; no
        clock, no randomness.  Every fact that the TAUI mirror marks visible
        appears in the output (reading-completeness guarantee).

    Notes
    -----
    Derives from :func:`convertible.tui.taui.serialize` so the Markdown and
    JSON mirror are two renders of one source and cannot drift.
    """
    taui = serialize(state)

    sections: list[str] = []

    cockpit = _section_cockpit(taui)
    if cockpit:
        sections.append(cockpit)

    zones = _section_zones(taui)
    if zones:
        sections.append(zones)

    panels = _section_panels(taui)
    if panels:
        sections.append(panels)

    popups = _section_popups(taui)
    if popups:
        sections.append(popups)

    status = _section_status(taui)
    if status:
        sections.append(status)

    drive = _section_drive(taui)
    if drive:
        sections.append(drive)

    actions = _section_available_actions(taui)
    if actions:
        sections.append(actions)

    return "\n\n".join(sections) + "\n"
