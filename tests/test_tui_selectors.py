"""Tests for convertible.tui.selectors — dotted-path selector resolution over TAUI."""

import pytest

from convertible.tui.events import Dismiss, Key
from convertible.tui.selectors import SelectorError, resolve, selector_to_event, selectors
from convertible.tui.state import Action, CockpitState, Panel, PanelItem, Popup
from convertible.tui.taui import serialize

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_skill_boost_state() -> CockpitState:
    """Build a CockpitState with a visible popup.skill.boost popup."""
    popup = Popup(
        id="popup.skill.boost",
        kind="skill_suggestion",
        visible=True,
        blocking=False,
        opened_by="skill",
        reason="boost_recommended",
        message="Boost this skill?",
        actions=[
            Action(
                selector="popup.skill.boost.accept",
                input="enter",
                description="Accept boost",
            ),
            Action(
                selector="popup.skill.boost.dismiss",
                input="esc",
                description="Dismiss",
            ),
        ],
    )
    panel = Panel(
        id="panel.skills",
        title="Skills",
        visible=True,
        content_summary="1 skill",
        items=[
            PanelItem(id="panel.skills.item.one", label="Skill One", status="available"),
        ],
    )
    return CockpitState(popups=[popup], panels=[panel])


# ---------------------------------------------------------------------------
# Criterion 1 — resolve returns the right node; unknown raises SelectorError
# ---------------------------------------------------------------------------


def test_resolve_returns_action_node_by_selector():
    """resolve finds the action dict whose selector matches exactly."""
    state = _make_skill_boost_state()
    taui = serialize(state)
    node = resolve(taui, "popup.skill.boost.accept")
    assert isinstance(node, dict)
    assert node.get("selector") == "popup.skill.boost.accept"
    assert node.get("input") == "enter"


def test_resolve_unknown_raises_selector_error():
    """resolve raises SelectorError (not KeyError) for unknown selectors."""
    taui = serialize(CockpitState())
    with pytest.raises(SelectorError) as exc_info:
        resolve(taui, "does.not.exist")
    assert "no node for selector" in str(exc_info.value)
    assert "does.not.exist" in str(exc_info.value)


def test_selector_error_is_exception_subclass():
    assert issubclass(SelectorError, Exception)


def test_resolve_popup_by_id():
    """resolve returns the popup dict when the selector matches a popup id."""
    state = _make_skill_boost_state()
    taui = serialize(state)
    node = resolve(taui, "popup.skill.boost")
    assert isinstance(node, dict)
    assert node.get("id") == "popup.skill.boost"


def test_resolve_panel_by_id():
    """resolve returns the panel dict when the selector matches a panel id."""
    state = _make_skill_boost_state()
    taui = serialize(state)
    node = resolve(taui, "panel.skills")
    assert isinstance(node, dict)
    assert node.get("id") == "panel.skills"


def test_resolve_panel_item_by_id():
    """resolve returns the panel item dict when the selector matches a panel item id."""
    state = _make_skill_boost_state()
    taui = serialize(state)
    node = resolve(taui, "panel.skills.item.one")
    assert isinstance(node, dict)
    assert node.get("id") == "panel.skills.item.one"


def test_resolve_plain_top_level_key_status():
    """resolve returns the top-level 'status' dict for the 'status' selector."""
    state = _make_skill_boost_state()
    taui = serialize(state)
    node = resolve(taui, "status")
    assert isinstance(node, dict)
    assert "severity" in node


def test_resolve_plain_top_level_key_background():
    """resolve returns the 'background' dict for the 'background' selector."""
    state = _make_skill_boost_state()
    taui = serialize(state)
    node = resolve(taui, "background")
    assert isinstance(node, dict)
    assert "theme" in node


def test_resolve_background_subkey():
    """resolve returns a scalar for a dotted drill like 'background.theme'."""
    state = _make_skill_boost_state()
    taui = serialize(state)
    node = resolve(taui, "background.theme")
    assert node == "default"


def test_resolve_zone_key_with_dot():
    """resolve finds a zone by its key (which itself contains dots)."""
    state = _make_skill_boost_state()
    taui = serialize(state)
    node = resolve(taui, "top.status")
    assert isinstance(node, dict)
    assert "visible" in node


# ---------------------------------------------------------------------------
# Criterion 2 — selectors() derives everything from the tree
# ---------------------------------------------------------------------------


def test_selectors_returns_list_of_strings():
    taui = serialize(CockpitState())
    result = selectors(taui)
    assert isinstance(result, list)
    assert all(isinstance(s, str) for s in result)


def test_selectors_contains_popup_id():
    state = _make_skill_boost_state()
    taui = serialize(state)
    result = selectors(taui)
    assert "popup.skill.boost" in result


def test_selectors_contains_action_selector():
    state = _make_skill_boost_state()
    taui = serialize(state)
    result = selectors(taui)
    assert "popup.skill.boost.accept" in result
    assert "popup.skill.boost.dismiss" in result


def test_selectors_contains_panel_id():
    state = _make_skill_boost_state()
    taui = serialize(state)
    result = selectors(taui)
    assert "panel.skills" in result


def test_selectors_contains_panel_item_id():
    state = _make_skill_boost_state()
    taui = serialize(state)
    result = selectors(taui)
    assert "panel.skills.item.one" in result


def test_selectors_contains_zone_keys():
    state = _make_skill_boost_state()
    taui = serialize(state)
    result = selectors(taui)
    # default zones include "top.status"
    assert "top.status" in result


def test_selectors_contains_standing_selectors():
    taui = serialize(CockpitState())
    result = selectors(taui)
    assert "input.prompt" in result
    assert "status" in result
    assert "background" in result


def test_selectors_no_duplicates():
    state = _make_skill_boost_state()
    taui = serialize(state)
    result = selectors(taui)
    assert len(result) == len(set(result)), "selectors() returned duplicates"


def test_selectors_rename_popup_changes_derived_list():
    """KEY invariant (h3): renaming a popup id changes what selectors() returns.

    There is no separate registry — the list is DERIVED from the tree.
    """
    state_orig = _make_skill_boost_state()
    taui_orig = serialize(state_orig)

    # Build a second state with the popup renamed
    popup_renamed = Popup(
        id="popup.skill.turbo",  # renamed
        kind="skill_suggestion",
        visible=True,
        blocking=False,
        opened_by="skill",
        reason="turbo_recommended",
        message="Turbo this skill?",
        actions=[
            Action(
                selector="popup.skill.turbo.accept",
                input="enter",
                description="Accept turbo",
            ),
            Action(
                selector="popup.skill.turbo.dismiss",
                input="esc",
                description="Dismiss",
            ),
        ],
    )
    state_renamed = CockpitState(popups=[popup_renamed])
    taui_renamed = serialize(state_renamed)

    result_orig = selectors(taui_orig)
    result_renamed = selectors(taui_renamed)

    # Old selectors gone from renamed tree
    assert "popup.skill.boost" not in result_renamed
    assert "popup.skill.boost.accept" not in result_renamed
    assert "popup.skill.boost.dismiss" not in result_renamed

    # New selectors present in renamed tree
    assert "popup.skill.turbo" in result_renamed
    assert "popup.skill.turbo.accept" in result_renamed
    assert "popup.skill.turbo.dismiss" in result_renamed

    # Original tree unchanged
    assert "popup.skill.boost" in result_orig
    assert "popup.skill.turbo" not in result_orig


# ---------------------------------------------------------------------------
# selector_to_event — dismiss action -> Dismiss; other -> Key
# ---------------------------------------------------------------------------


def test_selector_to_event_dismiss_action_returns_dismiss():
    """A .dismiss action selector yields Dismiss(target=<parent popup id>)."""
    state = _make_skill_boost_state()
    taui = serialize(state)
    event = selector_to_event(taui, "popup.skill.boost.dismiss")
    assert isinstance(event, Dismiss)
    assert event.target == "popup.skill.boost"


def test_selector_to_event_non_dismiss_returns_key():
    """A non-dismiss action selector yields Key(key=<action input>)."""
    state = _make_skill_boost_state()
    taui = serialize(state)
    event = selector_to_event(taui, "popup.skill.boost.accept")
    assert isinstance(event, Key)
    assert event.key == "enter"


def test_selector_to_event_unknown_raises_selector_error():
    taui = serialize(CockpitState())
    with pytest.raises(SelectorError):
        selector_to_event(taui, "does.not.exist")


def test_selector_to_event_non_action_raises_selector_error():
    """Passing a non-action node selector (e.g. a popup id) raises SelectorError."""
    state = _make_skill_boost_state()
    taui = serialize(state)
    with pytest.raises(SelectorError):
        selector_to_event(taui, "popup.skill.boost")


def test_selector_to_event_panel_raises_selector_error():
    """Panel ids are not actionable — must raise SelectorError."""
    state = _make_skill_boost_state()
    taui = serialize(state)
    with pytest.raises(SelectorError):
        selector_to_event(taui, "panel.skills")
