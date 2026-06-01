"""Convertible TUI — dotted-path selector resolution over the TAUI mirror.

Selectors are DERIVED from the tree's own ``id``/``selector`` fields (the KEY
invariant, honesty condition h3) — there is no separate registry that could
drift from state.  Renaming a node changes its derived selector automatically.

Public API
----------
- :class:`SelectorError` — raised when a selector cannot be resolved.
- :func:`selectors` — walk the TAUI mirror and return every addressable selector.
- :func:`resolve` — return the node dict (or scalar) identified by a selector.
- :func:`selector_to_event` — map an action selector to a :class:`~convertible.tui.events.Event`.
"""

from __future__ import annotations

from typing import Any, Callable

from convertible.tui.events import Dismiss, Event

# ---------------------------------------------------------------------------
# Error type
# ---------------------------------------------------------------------------


class SelectorError(Exception):
    """Raised when a selector cannot be resolved in the TAUI tree."""


# Sentinel distinguishing "not found" from a legitimately falsy resolved value
# (e.g. an empty status message or a zero frame counter).
_MISSING = object()


# ---------------------------------------------------------------------------
# selectors() — derive every addressable path from the tree
# ---------------------------------------------------------------------------


def _collect_popup_selectors(taui: dict[str, Any], add: Callable[[str], None]) -> None:
    """Add every popup ``id`` and its action ``selector``s."""
    for popup in taui.get("popups", []):
        popup_id = popup.get("id")
        if popup_id:
            add(str(popup_id))
        for action in popup.get("actions", []):
            action_sel = action.get("selector")
            if action_sel:
                add(str(action_sel))


def _collect_panel_selectors(taui: dict[str, Any], add: Callable[[str], None]) -> None:
    """Add every panel ``id`` and its item ``id``s."""
    for panel in taui.get("panels", []):
        panel_id = panel.get("id")
        if panel_id:
            add(str(panel_id))
        for item in panel.get("items", []):
            item_id = item.get("id")
            if item_id:
                add(str(item_id))


def _collect_zone_and_action_selectors(taui: dict[str, Any], add: Callable[[str], None]) -> None:
    """Add every zone key and every ``available_actions`` selector."""
    for zone_key in taui.get("zones", {}):
        add(str(zone_key))
    for action in taui.get("available_actions", []):
        action_sel = action.get("selector")
        if action_sel:
            add(str(action_sel))


def selectors(taui: dict[str, Any]) -> list[str]:
    """Return a de-duplicated list of every addressable selector in *taui*.

    The list is DERIVED by reading the tree — not hardcoded.  Renaming any
    node's ``id`` or ``selector`` field changes what this function returns.
    Order: popups → panels → zones → available_actions → standing selectors
    (``"input.prompt"``, ``"status"``, ``"background"``).
    """
    seen: set[str] = set()
    result: list[str] = []

    def _add(s: str) -> None:
        if s not in seen:
            seen.add(s)
            result.append(s)

    _collect_popup_selectors(taui, _add)
    _collect_panel_selectors(taui, _add)
    _collect_zone_and_action_selectors(taui, _add)

    _add("input.prompt")
    _add("status")
    _add("background")

    return result


# ---------------------------------------------------------------------------
# resolve() — look up a node by selector
# ---------------------------------------------------------------------------


def _resolve_popup(taui: dict[str, Any], selector: str) -> Any:
    """Match a popup ``id`` (then a popup action ``selector``) or ``_MISSING``."""
    for popup in taui.get("popups", []):
        if popup.get("id") == selector:
            return popup
    for popup in taui.get("popups", []):
        for action in popup.get("actions", []):
            if action.get("selector") == selector:
                return action
    return _MISSING


def _resolve_panel(taui: dict[str, Any], selector: str) -> Any:
    """Match a panel ``id`` (then a panel item ``id``) or ``_MISSING``."""
    for panel in taui.get("panels", []):
        if panel.get("id") == selector:
            return panel
    for panel in taui.get("panels", []):
        for item in panel.get("items", []):
            if item.get("id") == selector:
                return item
    return _MISSING


def _resolve_zone(taui: dict[str, Any], selector: str) -> Any:
    """Match a zone key exactly (zone keys may contain dots) or ``_MISSING``."""
    zones = taui.get("zones", {})
    if selector in zones:
        return zones[selector]
    return _MISSING


def _resolve_dotted(taui: dict[str, Any], selector: str) -> Any:
    """Drill the top-level dict by dotted path (e.g. ``background.theme``)."""
    node: Any = taui
    for part in selector.split("."):
        if not isinstance(node, dict) or part not in node:
            return _MISSING
        node = node[part]
    return node


def resolve(taui: dict[str, Any], selector: str) -> Any:
    """Return the node (or scalar) identified by *selector*.

    Resolution order: popup id → popup action selector → panel id → panel item
    id → zone key (exact) → dotted-dict drill on the top-level taui dict.

    Raises
    ------
    SelectorError
        If no node matches the selector.
    """
    for finder in (_resolve_popup, _resolve_panel, _resolve_zone, _resolve_dotted):
        result = finder(taui, selector)
        if result is not _MISSING:
            return result
    raise SelectorError(f"no node for selector: {selector!r}")


# ---------------------------------------------------------------------------
# selector_to_event() — map an action selector to an Event
# ---------------------------------------------------------------------------


def selector_to_event(taui: dict[str, Any], selector: str) -> Event:
    """Map a popup-action *selector* to an :class:`~convertible.tui.events.Event`.

    Only ``.dismiss`` actions have a defined headless state effect in v0 — they
    close the popup. Every other popup action (``accept``, ``details``, …) and
    all key navigation/activation are the **live driver's** concern (a parked
    follow-up), so they are NOT operable via the headless ``tui action`` verb
    yet. Rather than silently returning an unchanged mirror (a misleading
    no-op), such selectors — and any non-action selector — raise
    :class:`SelectorError`.

    Raises
    ------
    SelectorError
        If the selector is unknown, is not a popup action, or is an action that
        has no defined headless effect in v0 (anything other than ``.dismiss``).
    """
    for popup in taui.get("popups", []):
        for action in popup.get("actions", []):
            if action.get("selector") == selector:
                if selector.endswith(".dismiss"):
                    return Dismiss(target=str(popup.get("id", "")))
                raise SelectorError(
                    f"action {selector!r} is not operable headlessly in v0 — only "
                    "'.dismiss' actions change state; activation/navigation is the "
                    "live driver's concern (a parked follow-up)"
                )

    # Not a popup action. resolve() raises a clear SelectorError for unknowns;
    # if it resolves, the selector names a non-action node.
    resolve(taui, selector)
    raise SelectorError(f"selector {selector!r} is not an actionable popup action")
