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

from typing import Any

from convertible.tui.events import Dismiss, Event, Key

# ---------------------------------------------------------------------------
# Error type
# ---------------------------------------------------------------------------


class SelectorError(Exception):
    """Raised when a selector cannot be resolved in the TAUI tree."""


# ---------------------------------------------------------------------------
# selectors() — derive every addressable path from the tree
# ---------------------------------------------------------------------------


def selectors(taui: dict[str, Any]) -> list[str]:
    """Return a de-duplicated list of every addressable selector in *taui*.

    The list is DERIVED by reading the tree — not hardcoded.  Renaming any
    node's ``id`` or ``selector`` field changes what this function returns.

    Collected items
    ---------------
    - Every popup ``id``.
    - Every action ``selector`` inside each popup.
    - Every panel ``id``.
    - Every panel item ``id``.
    - Every zone key (the zone name itself, e.g. ``"top.status"``).
    - Every ``selector`` present in ``available_actions``.
    - The standing top-level selectors: ``"input.prompt"``, ``"status"``,
      ``"background"``.

    Parameters
    ----------
    taui:
        A TAUI mirror dict as produced by :func:`convertible.tui.taui.serialize`.

    Returns
    -------
    list[str]
        De-duplicated list of selector strings (order: popups → panels →
        zones → available_actions → standing).
    """
    seen: set[str] = set()
    result: list[str] = []

    def _add(s: str) -> None:
        if s not in seen:
            seen.add(s)
            result.append(s)

    # Popups: popup id + each action's selector
    for popup in taui.get("popups", []):
        popup_id = popup.get("id")
        if popup_id:
            _add(str(popup_id))
        for action in popup.get("actions", []):
            action_sel = action.get("selector")
            if action_sel:
                _add(str(action_sel))

    # Panels: panel id + each item's id
    for panel in taui.get("panels", []):
        panel_id = panel.get("id")
        if panel_id:
            _add(str(panel_id))
        for item in panel.get("items", []):
            item_id = item.get("id")
            if item_id:
                _add(str(item_id))

    # Zones: the zone key itself (e.g. "top.status")
    for zone_key in taui.get("zones", {}):
        _add(str(zone_key))

    # available_actions selectors (catches anything we may have missed above,
    # e.g. the standing "input.prompt")
    for action in taui.get("available_actions", []):
        action_sel = action.get("selector")
        if action_sel:
            _add(str(action_sel))

    # Standing top-level selectors always present
    _add("input.prompt")
    _add("status")
    _add("background")

    return result


# ---------------------------------------------------------------------------
# resolve() — look up a node by selector
# ---------------------------------------------------------------------------


def resolve(taui: dict[str, Any], selector: str) -> Any:
    """Return the node (or scalar) identified by *selector*.

    Resolution order
    ----------------
    1. Search popups: match popup ``id`` → return popup dict.
    2. Search popup actions: match action ``selector`` → return action dict.
    3. Search panels: match panel ``id`` → return panel dict.
    4. Search panel items: match item ``id`` → return item dict.
    5. Match zone keys exactly (zone keys can contain dots, so this must be an
       exact-key lookup, not a dotted drill).
    6. Dotted-dict drilling on the top-level taui dict
       (e.g. ``"status"`` → ``taui["status"]``,
       ``"background.theme"`` → ``taui["background"]["theme"]``).

    Parameters
    ----------
    taui:
        A TAUI mirror dict as produced by :func:`convertible.tui.taui.serialize`.
    selector:
        The selector string to look up.

    Returns
    -------
    Any
        The matching node or scalar value.

    Raises
    ------
    SelectorError
        If no node matches the selector.
    """
    # 1. Popup id match
    for popup in taui.get("popups", []):
        if popup.get("id") == selector:
            return popup

    # 2. Popup action selector match
    for popup in taui.get("popups", []):
        for action in popup.get("actions", []):
            if action.get("selector") == selector:
                return action

    # 3. Panel id match
    for panel in taui.get("panels", []):
        if panel.get("id") == selector:
            return panel

    # 4. Panel item id match
    for panel in taui.get("panels", []):
        for item in panel.get("items", []):
            if item.get("id") == selector:
                return item

    # 5. Zone key exact match (zone keys themselves may contain dots)
    zones = taui.get("zones", {})
    if selector in zones:
        return zones[selector]

    # 6. Dotted-dict drill on top-level taui
    parts = selector.split(".")
    node: Any = taui
    try:
        for part in parts:
            if not isinstance(node, dict):
                raise KeyError(part)
            node = node[part]
        return node
    except (KeyError, TypeError):
        pass

    raise SelectorError(f"no node for selector: {selector!r}")


# ---------------------------------------------------------------------------
# selector_to_event() — map an action selector to an Event
# ---------------------------------------------------------------------------


def selector_to_event(taui: dict[str, Any], selector: str) -> Event:
    """Map an action *selector* to an :class:`~convertible.tui.events.Event`.

    The selector must identify a popup ACTION node (an entry in a popup's
    ``actions`` list).  Non-action selectors (popup ids, panel ids, …) raise
    :class:`SelectorError`.

    Mapping rules
    -------------
    - If the action's ``selector`` ends with ``".dismiss"``, return
      ``Dismiss(target=<parent popup id>)``.
    - Otherwise return ``Key(key=<action "input">)``.

    Parameters
    ----------
    taui:
        A TAUI mirror dict.
    selector:
        The selector string to resolve.

    Returns
    -------
    Event
        A :class:`~convertible.tui.events.Dismiss` or
        :class:`~convertible.tui.events.Key` instance.

    Raises
    ------
    SelectorError
        If the selector is not found or does not identify an actionable node.
    """
    # Search popup actions, tracking the parent popup id
    for popup in taui.get("popups", []):
        for action in popup.get("actions", []):
            if action.get("selector") == selector:
                # Found the action — now decide which event to emit
                if selector.endswith(".dismiss"):
                    parent_id = popup.get("id", "")
                    return Dismiss(target=str(parent_id))
                return Key(key=str(action.get("input", "")))

    # Also check available_actions for the standing input.prompt action
    for action in taui.get("available_actions", []):
        if action.get("selector") == selector:
            # The standing action is not a dismiss
            return Key(key=str(action.get("input", "")))

    # resolve() first to give a clear SelectorError for unknowns; if it does
    # not raise, the selector exists but is not an actionable action node.
    resolve(taui, selector)

    raise SelectorError(
        f"selector {selector!r} is not an actionable node (resolved to a non-action node)"
    )
