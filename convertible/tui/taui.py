"""Convertible TUI — TAUI semantic mirror.

TAUI (Textual Agentic UI) is the **single derived mirror** of :class:`CockpitState`
that an agent reads.  It is a plain JSON-serialisable dict (only
``dict``/``list``/``str``/``int``/``float``/``bool``/``None``) so an agent can
consume it without any ``convertible`` import.

Key design invariants
---------------------
- Every popup and panel node carries a stable ``id``.
- Every action node carries a ``selector`` (a dotted path into the UI tree).
- Selectors in ``available_actions`` are derived FROM the same state — they
  cannot drift from the actual tree.
- ``available_actions`` is the flat, agent-readable "what can I do right now?"
  list: all visible-popup actions, plus one standing entry for the prompt input.
- ``taui_version`` is always present and equals :data:`SCHEMA_VERSION`.

Usage::

    from convertible.tui.taui import serialize, SCHEMA_VERSION
    mirror = serialize(state)
    import json
    json.dumps(mirror)   # always succeeds

``serialize`` never raises on a valid :class:`CockpitState`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from convertible.tui.state import CockpitState

#: Semantic version of the TAUI mirror schema.  Bump when the shape changes.
SCHEMA_VERSION = "0.1"

#: The standing action always present in ``available_actions``.
_STANDING_ACTION: dict[str, Any] = {
    "selector": "input.prompt",
    "input": "type",
    "description": "Send instruction to current agent",
}


def serialize(state: "CockpitState") -> dict[str, Any]:
    """Return the TAUI mirror of *state* as a plain JSON-serialisable dict.

    Parameters
    ----------
    state:
        The canonical :class:`~convertible.tui.state.CockpitState` snapshot.

    Returns
    -------
    dict
        A JSON-safe dict (no third-party types).  Keys:

        ``taui_version``
            Always equals :data:`SCHEMA_VERSION`.
        ``screen``, ``mode``, ``focused``
            Forwarded verbatim from *state*.
        ``zones``
            ``{name: {"visible": bool}}`` — one entry per zone.
        ``panels``
            List of panel dicts, each with ``id``, ``title``, ``visible``,
            ``content_summary``, ``items``.
        ``popups``
            List of popup dicts, each with ``id``, ``kind``, ``visible``,
            ``blocking``, ``opened_by``, ``reason``, ``message``, ``actions``
            (each with ``selector``, ``input``, ``description``), ``timeout_ms``.
        ``background``
            ``{theme, animation, frame, semantic}``.
        ``status``
            ``{severity, message}``.
        ``drive``
            Drive dict or ``None``.
        ``problems``
            Forwarded verbatim from *state*.
        ``available_actions``
            Flat list of ``{selector, input, description}`` — actions from every
            *visible* popup, plus the standing ``input.prompt`` action.
    """
    raw = state.to_dict()

    zones: dict[str, dict[str, Any]] = {
        name: {"visible": bool(zone_d.get("visible", True))}
        for name, zone_d in raw.get("zones", {}).items()
    }

    panels: list[dict[str, Any]] = raw.get("panels", [])
    popups: list[dict[str, Any]] = raw.get("popups", [])

    available_actions: list[dict[str, Any]] = []
    for popup_d in popups:
        if popup_d.get("visible"):
            for action_d in popup_d.get("actions", []):
                available_actions.append(
                    {
                        "selector": str(action_d["selector"]),
                        "input": str(action_d["input"]),
                        "description": str(action_d.get("description", "")),
                    }
                )
    available_actions.append(dict(_STANDING_ACTION))

    drive: Optional[dict[str, Any]] = raw.get("drive")

    return {
        "taui_version": SCHEMA_VERSION,
        "screen": str(raw.get("screen", "main")),
        "mode": str(raw.get("mode", "planning")),
        "focused": str(raw.get("focused", "input.prompt")),
        "zones": zones,
        "panels": panels,
        "popups": popups,
        "background": raw.get("background", {}),
        "status": raw.get("status", {}),
        "drive": drive,
        "problems": list(raw.get("problems", [])),
        "available_actions": available_actions,
    }
