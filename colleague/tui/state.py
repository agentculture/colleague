"""Colleague TUI state — canonical CockpitState and its nested dataclasses.

``CockpitState`` is the **single source of truth** for the TUI cockpit.  It is a
plain :mod:`dataclasses` tree with explicit ``to_dict`` / ``from_dict`` so the
state round-trips through JSON unchanged — the same convention as
:mod:`colleague.contract`.  ``json.dumps(state.to_dict())`` must always succeed.

All types are stdlib-only (``dataclasses``, ``typing``).  Zero third-party
imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Leaf dataclasses
# ---------------------------------------------------------------------------


@dataclass
class Action:
    """A UI action that can be associated with a popup button or control.

    Fields
    ------
    selector:
        CSS-like selector string identifying the target element (e.g. ``"button.ok"``).
    input:
        The input type to send — e.g. ``"enter"``, ``"type"``, ``"click"``.
    description:
        Human-readable label shown alongside the action; defaults to ``""``.
    """

    selector: str
    input: str
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "selector": self.selector,
            "input": self.input,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Action":
        return cls(
            selector=str(d["selector"]),
            input=str(d["input"]),
            description=str(d.get("description", "")),
        )


@dataclass
class PanelItem:
    """One entry inside a :class:`Panel`.

    Fields
    ------
    id:
        Stable identifier for the item (used for focus + selection).
    label:
        Display label shown to the user.
    status:
        Availability status; conventional values: ``"available"``, ``"active"``,
        ``"disabled"``.  Defaults to ``"available"``.
    tags:
        Optional capability/risk badges (e.g. ``["read-only", "config"]``,
        issue #160) rendered next to the label by the Markdown + ANSI tiers.
        Defaults to ``[]`` — absent for every pre-#160 item, so the field is
        backward-compatible.
    """

    id: str
    label: str
    status: str = "available"
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "status": self.status,
            "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PanelItem":
        return cls(
            id=str(d["id"]),
            label=str(d["label"]),
            status=str(d.get("status", "available")),
            tags=[str(t) for t in d.get("tags", [])],
        )


@dataclass
class Panel:
    """A side-panel section (e.g. the skills list, the conversation history).

    Fields
    ------
    id:
        Stable identifier for the panel.
    title:
        Display title; defaults to ``""``.
    visible:
        Whether the panel is currently shown; defaults to ``True``.
    content_summary:
        A one-line text summary of the panel's content (e.g. ``"3 skills"``).
    items:
        Ordered list of :class:`PanelItem` entries.
    """

    id: str
    title: str = ""
    visible: bool = True
    content_summary: str = ""
    items: list[PanelItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "visible": self.visible,
            "content_summary": self.content_summary,
            "items": [item.to_dict() for item in self.items],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Panel":
        return cls(
            id=str(d["id"]),
            title=str(d.get("title", "")),
            visible=bool(d.get("visible", True)),
            content_summary=str(d.get("content_summary", "")),
            items=[PanelItem.from_dict(i) for i in d.get("items", [])],
        )


@dataclass
class Popup:
    """A transient overlay shown above the main cockpit layout.

    Fields
    ------
    id:
        Stable identifier for the popup (used to dismiss/update it).
    kind:
        Category of popup; conventional values: ``"skill_suggestion"``,
        ``"confirmation"``, ``"error"``, ``"progress"``, ``"diff"``, ``"help"``.
    visible:
        Whether the popup is currently rendered; defaults to ``False``.
    blocking:
        When ``True`` the popup captures all keyboard input until dismissed;
        defaults to ``False``.
    opened_by:
        Who opened the popup; conventional values: ``"system"``, ``"user"``,
        ``"skill"``, ``"agent"``; defaults to ``"system"``.
    reason:
        Machine-readable reason code or slug; defaults to ``""``.
    message:
        Human-readable message to display; defaults to ``""``.
    actions:
        Ordered list of :class:`Action` objects the user can invoke.
    timeout_ms:
        Auto-dismiss timeout in milliseconds; ``None`` means no auto-dismiss.
    """

    id: str
    kind: str
    visible: bool = False
    blocking: bool = False
    opened_by: str = "system"
    reason: str = ""
    message: str = ""
    actions: list[Action] = field(default_factory=list)
    timeout_ms: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "visible": self.visible,
            "blocking": self.blocking,
            "opened_by": self.opened_by,
            "reason": self.reason,
            "message": self.message,
            "actions": [a.to_dict() for a in self.actions],
            "timeout_ms": self.timeout_ms,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Popup":
        raw_timeout = d.get("timeout_ms")
        return cls(
            id=str(d["id"]),
            kind=str(d["kind"]),
            visible=bool(d.get("visible", False)),
            blocking=bool(d.get("blocking", False)),
            opened_by=str(d.get("opened_by", "system")),
            reason=str(d.get("reason", "")),
            message=str(d.get("message", "")),
            actions=[Action.from_dict(a) for a in d.get("actions", [])],
            timeout_ms=int(raw_timeout) if raw_timeout is not None else None,
        )


@dataclass
class Zone:
    """A named layout region of the cockpit (e.g. ``"top.status"``).

    Fields
    ------
    visible:
        Whether the zone is currently displayed; defaults to ``True``.
    """

    visible: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {"visible": self.visible}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Zone":
        return cls(visible=bool(d.get("visible", True)))


@dataclass
class Background:
    """The cockpit background / ambience state.

    Fields
    ------
    theme:
        Visual theme name; defaults to ``"default"``.
    animation:
        Animation name or ``"none"``; defaults to ``"none"``.
    frame:
        Current animation frame index (integer); defaults to ``0``.
    semantic:
        Semantic label describing the current activity
        (e.g. ``"idle"``, ``"busy"``, ``"error"``); defaults to ``""``.
    """

    theme: str = "default"
    animation: str = "none"
    frame: int = 0
    semantic: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "theme": self.theme,
            "animation": self.animation,
            "frame": self.frame,
            "semantic": self.semantic,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Background":
        return cls(
            theme=str(d.get("theme", "default")),
            animation=str(d.get("animation", "none")),
            frame=int(d.get("frame", 0)),
            semantic=str(d.get("semantic", "")),
        )


@dataclass
class Status:
    """A one-line status / notification shown in the status bar.

    Fields
    ------
    severity:
        Severity level; conventional values: ``"info"``, ``"warn"``, ``"error"``,
        ``"success"``; defaults to ``"info"``.
    message:
        Human-readable status text; defaults to ``""``.
    """

    severity: str = "info"
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "message": self.message,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Status":
        return cls(
            severity=str(d.get("severity", "info")),
            message=str(d.get("message", "")),
        )


@dataclass
class WorkItem:
    """Snapshot of the currently-running (or last-run) colleague work item.

    Fields
    ------
    task_id:
        The task identifier from :class:`colleague.contract.Task`.
    engine:
        The engine name used for this work item (e.g. ``"mock"``, ``"vllm-openai"``).
    step_count:
        Number of tool-call steps completed so far.
    running:
        ``True`` while the work loop is active; ``False`` once it finishes.
    """

    task_id: str = ""
    engine: str = ""
    step_count: int = 0
    running: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "engine": self.engine,
            "step_count": self.step_count,
            "running": self.running,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "WorkItem":
        return cls(
            task_id=str(d.get("task_id", "")),
            engine=str(d.get("engine", "")),
            step_count=int(d.get("step_count", 0)),
            running=bool(d.get("running", False)),
        )


# ---------------------------------------------------------------------------
# Default zones factory
# ---------------------------------------------------------------------------

_DEFAULT_ZONE_KEYS = (
    "top.status",
    "left.skills",
    "main.conversation",
    "bottom.input",
)


def _default_zones() -> dict[str, Zone]:
    """Return the four default cockpit zones, all visible."""
    return {key: Zone(visible=True) for key in _DEFAULT_ZONE_KEYS}


# ---------------------------------------------------------------------------
# Top-level CockpitState
# ---------------------------------------------------------------------------


@dataclass
class CockpitState:
    """The single source of truth for the TUI cockpit.

    All mutable fields use ``field(default_factory=...)`` to ensure that each
    :class:`CockpitState` instance owns its own collections — never shared.

    ``to_dict()`` recursively serializes the entire tree to plain JSON-able dicts
    and lists so ``json.dumps(state.to_dict())`` always succeeds.
    ``from_dict()`` reconstructs an equal object from that dict.

    Fields
    ------
    screen:
        Active screen name; defaults to ``"main"``.
    mode:
        Current interaction mode. ``colleague session`` sets this to the active
        session mode (``auto`` | ``work`` | ``plan`` | ``explore`` | ``review``),
        so every render tier surfaces it; a non-session cockpit keeps the
        ``"planning"`` default.
    focused:
        Selector string of the focused element; defaults to ``"input.prompt"``.
    zones:
        Mapping of zone-key → :class:`Zone`.  Defaults to the four standard
        zones (``"top.status"``, ``"left.skills"``, ``"main.conversation"``,
        ``"bottom.input"``), all visible.
    panels:
        Ordered list of :class:`Panel` objects; defaults to ``[]``.
    popups:
        Ordered list of :class:`Popup` objects; defaults to ``[]``.
    background:
        Background / ambience state; defaults to :class:`Background()`.
    status:
        Status-bar state; defaults to :class:`Status()`.
    drive:
        Active or last-completed drive snapshot; ``None`` when no drive has
        been started.
    problems:
        List of raw problem dicts (e.g. lint / Sonar findings); defaults to
        ``[]``.  Stored as plain dicts so they serialize directly.
    """

    screen: str = "main"
    mode: str = "planning"
    focused: str = "input.prompt"
    zones: dict[str, Zone] = field(default_factory=_default_zones)
    panels: list[Panel] = field(default_factory=list)
    popups: list[Popup] = field(default_factory=list)
    background: Background = field(default_factory=Background)
    status: Status = field(default_factory=Status)
    work_item: Optional[WorkItem] = None
    problems: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "screen": self.screen,
            "mode": self.mode,
            "focused": self.focused,
            "zones": {k: v.to_dict() for k, v in self.zones.items()},
            "panels": [p.to_dict() for p in self.panels],
            "popups": [p.to_dict() for p in self.popups],
            "background": self.background.to_dict(),
            "status": self.status.to_dict(),
            "work": self.work_item.to_dict() if self.work_item is not None else None,
            "problems": list(self.problems),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CockpitState":
        raw_zones = d.get("zones") or {}
        # Back-compat: pre-rename snapshots carried the work item under "drive".
        raw_work = d.get("work", d.get("drive"))
        return cls(
            screen=str(d.get("screen", "main")),
            mode=str(d.get("mode", "planning")),
            focused=str(d.get("focused", "input.prompt")),
            zones={k: Zone.from_dict(v) for k, v in raw_zones.items()},
            panels=[Panel.from_dict(p) for p in d.get("panels", [])],
            popups=[Popup.from_dict(p) for p in d.get("popups", [])],
            background=Background.from_dict(d.get("background") or {}),
            status=Status.from_dict(d.get("status") or {}),
            work_item=WorkItem.from_dict(raw_work) if raw_work is not None else None,
            problems=list(d.get("problems", [])),
        )
