"""Pure reducer for the TUI cockpit — ``reduce(state, event) -> CockpitState``.

This module is intentionally free of I/O, clocks, and randomness.  It imports
nothing from ``os``, ``time``, or ``random`` — only stdlib ``copy`` and
``dataclasses``, plus the project-local ``state`` and ``events`` modules.

Every public function is a pure function: it returns a new :class:`CockpitState`
and never mutates its argument.
"""

from __future__ import annotations

import copy
import re
from dataclasses import replace
from typing import Any

from colleague.tui.events import Dismiss, KeyPress, SkillSuggested, Tick, UserInput, WorkStep
from colleague.tui.state import Action, CockpitState, Panel, Popup

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def reduce(state: CockpitState, event: Any) -> CockpitState:
    """Return a new :class:`CockpitState` by applying *event* to *state*.

    Parameters
    ----------
    state:
        The current cockpit state.  **Never mutated.**
    event:
        Any event from :mod:`colleague.tui.events`.  Unrecognised event types
        return a deep copy of the input state unchanged.

    Returns
    -------
    CockpitState
        A brand-new state object.
    """
    if isinstance(event, Tick):
        return _reduce_tick(state, event)
    if isinstance(event, SkillSuggested):
        return _reduce_skill_suggested(state, event)
    if isinstance(event, Dismiss):
        return _reduce_dismiss(state, event)
    if isinstance(event, UserInput):
        return _reduce_user_input(state, event)
    if isinstance(event, WorkStep):
        return _reduce_work_step(state, event)
    if isinstance(event, KeyPress):
        # KeyPress handling (focus/navigation) is the driver's concern — return unchanged copy.
        return copy.deepcopy(state)
    # Unknown event — return unchanged copy.
    return copy.deepcopy(state)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _reduce_tick(state: CockpitState, event: Tick) -> CockpitState:
    """Advance ``background.frame`` by ``event.delta``; nothing else changes."""
    new_state = copy.deepcopy(state)
    new_state.background = replace(
        new_state.background, frame=new_state.background.frame + event.delta
    )
    return new_state


def _reduce_skill_suggested(state: CockpitState, event: SkillSuggested) -> CockpitState:
    """Open (or replace) a skill-suggestion popup and update background ambience."""
    new_state = copy.deepcopy(state)
    skill = event.skill
    popup_id = f"popup.skill.{skill}"

    popup = Popup(
        id=popup_id,
        kind="skill_suggestion",
        visible=True,
        blocking=False,
        opened_by="skill",
        reason=event.reason,
        message=f"Stronger agent recommended ({skill})",
        actions=[
            Action(f"popup.skill.{skill}.accept", "enter", f"Activate {skill}"),
            Action(f"popup.skill.{skill}.dismiss", "esc", "Dismiss"),
            Action(f"popup.skill.{skill}.details", "d", "Details"),
        ],
    )

    # Replace existing popup with same id, or append.
    new_popups = [p for p in new_state.popups if p.id != popup_id]
    new_popups.append(popup)
    new_state.popups = new_popups

    new_state.background = replace(
        new_state.background,
        theme=f"{skill}-suggested",
        semantic="stronger_agent_recommended",
    )
    return new_state


def _reduce_dismiss(state: CockpitState, event: Dismiss) -> CockpitState:
    """Set ``visible=False`` on the popup matching ``event.target``."""
    new_state = copy.deepcopy(state)
    new_state.popups = [
        replace(p, visible=False) if p.id == event.target else p for p in new_state.popups
    ]
    return new_state


def _reduce_user_input(state: CockpitState, event: UserInput) -> CockpitState:
    """Focus the prompt and append user text to the conversation panel."""
    new_state = copy.deepcopy(state)
    new_state.focused = "input.prompt"
    new_state.panels = _append_conversation_line(new_state.panels, event.text)
    return new_state


def _reduce_work_step(state: CockpitState, event: WorkStep) -> CockpitState:
    """Increment the work-item step counter (if one is active) and log a conversation line.

    A failed step (``event.ok is False``) additionally opens an ``error`` popup so
    the failure surfaces in the cockpit.  Keeping this in the pure reducer (rather
    than a live-driver side-channel) is what makes the popup appear identically
    live, in ``tui replay``, and in ``tui replay --trace`` of the same step.
    """
    new_state = copy.deepcopy(state)

    if new_state.work_item is not None:
        new_state.work_item = replace(
            new_state.work_item,
            step_count=new_state.work_item.step_count + 1,
        )

    line = f"[{event.tool}] {event.summary}"
    new_state.panels = _append_conversation_line(new_state.panels, line)

    if not event.ok:
        new_state.popups = _open_error_popup(new_state.popups, event)
    return new_state


def _open_error_popup(popups: list[Popup], event: WorkStep) -> list[Popup]:
    """Return a new popups list with an ``error`` popup for a failed work item step.

    Deduped by id (``popup.error.<tool>``) so a tool failing repeatedly refreshes
    one popup rather than stacking.  Non-blocking with a dismiss action — an
    empty-action or stuck blocking popup would trip ``tui diagnose`` lifecycle checks.
    """
    popup_id = f"popup.error.{event.tool}"
    detail = f": {event.summary}" if event.summary else ""
    popup = Popup(
        id=popup_id,
        kind="error",
        visible=True,
        blocking=False,
        opened_by="agent",
        reason="tool_failed",
        message=f"{event.tool} failed{detail}",
        actions=[Action(f"{popup_id}.dismiss", "esc", "Dismiss")],
    )
    kept = [p for p in popups if p.id != popup_id]
    kept.append(popup)
    return kept


# ---------------------------------------------------------------------------
# Conversation panel helper
# ---------------------------------------------------------------------------

_CONVERSATION_PANEL_ID = "panel.conversation"


#: Group-count suffix appended to a collapsed run of identical feed lines, e.g.
#: ``[culture] agtag issues ×4``. Matched/parsed so a repeat bumps the count
#: instead of stacking duplicate lines (issue #233: "no Nx duplicated [culture]").
_GROUP_RE = re.compile(r"^(?P<base>.*) ×(?P<count>\d+)$")


def _collapse_repeat(summary: str, line: str) -> str | None:
    """If *line* repeats the LAST line of *summary*, return *summary* with that line
    bumped to ``<line> ×N`` (incrementing an existing count); else ``None``.

    Only *consecutive* identical lines collapse — an intervening different line
    starts a fresh run. This is what turns the #233 spam (four bare ``[culture]``
    lines) into a single ``[culture] … ×4`` once a feed line repeats.
    """
    if not summary:
        return None
    before, sep, last = summary.rpartition("\n")
    match = _GROUP_RE.match(last)
    base, count = (match.group("base"), int(match.group("count"))) if match else (last, 1)
    if base != line:
        return None
    return f"{before}{sep}{line} ×{count + 1}"


def _append_conversation_line(panels: list[Panel], line: str) -> list[Panel]:
    """Return a new panels list with *line* appended to the conversation panel.

    Consecutive identical lines are *grouped* into ``<line> ×N`` rather than stacked
    (issue #233), so a tool firing repeatedly reads as one legible, counted entry.
    If no panel with id ``panel.conversation`` exists, one is created and appended.
    """
    existing = next((p for p in panels if p.id == _CONVERSATION_PANEL_ID), None)

    if existing is None:
        new_panel = Panel(
            id=_CONVERSATION_PANEL_ID,
            title="Conversation",
            visible=True,
            content_summary=line,
        )
        return list(panels) + [new_panel]

    collapsed = _collapse_repeat(existing.content_summary, line)
    if collapsed is not None:
        content = collapsed
    else:
        # Append to existing summary using newline as separator.
        sep = "\n" if existing.content_summary else ""
        content = f"{existing.content_summary}{sep}{line}"
    updated = replace(existing, content_summary=content)
    return [updated if p.id == _CONVERSATION_PANEL_ID else p for p in panels]
