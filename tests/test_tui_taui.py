"""Tests for colleague.tui.taui — the TAUI semantic mirror."""

import json

from colleague.tui.state import (
    Action,
    CockpitState,
    Panel,
    PanelItem,
    Popup,
    Status,
    WorkItem,
)
from colleague.tui.taui import SCHEMA_VERSION, serialize

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state() -> CockpitState:
    """Build a CockpitState with a visible popup (with actions) and a panel."""
    popup = Popup(
        id="popup.confirm",
        kind="confirmation",
        visible=True,
        blocking=True,
        opened_by="system",
        reason="approve_hook",
        message="Approve the hook?",
        actions=[
            Action(selector="button.accept", input="enter", description="Accept"),
            Action(selector="button.reject", input="enter", description="Reject"),
        ],
        timeout_ms=5000,
    )
    panel = Panel(
        id="panel.skills",
        title="Skills",
        visible=True,
        content_summary="2 skills",
        items=[
            PanelItem(id="skill.one", label="Skill One", status="available"),
        ],
    )
    status = Status(severity="error", message="Something went wrong")
    return CockpitState(
        screen="main",
        mode="driving",
        focused="button.accept",
        popups=[popup],
        panels=[panel],
        status=status,
        work_item=WorkItem(task_id="t-123", engine="mock", step_count=3, running=True),
    )


def _is_json_safe(obj, path="root") -> None:
    """Recursively assert that obj contains only JSON-safe types."""
    allowed = (dict, list, str, int, float, bool, type(None))
    assert isinstance(obj, allowed), f"Non-JSON type {type(obj)} at {path}: {obj!r}"
    if isinstance(obj, dict):
        for k, v in obj.items():
            assert isinstance(k, str), f"Non-str dict key {k!r} at {path}"
            _is_json_safe(v, path=f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _is_json_safe(v, path=f"{path}[{i}]")


# ---------------------------------------------------------------------------
# Basic shape / schema version
# ---------------------------------------------------------------------------


def test_serialize_returns_dict():
    state = _make_state()
    result = serialize(state)
    assert isinstance(result, dict)


def test_taui_version_matches_schema_version():
    assert SCHEMA_VERSION == "0.2"
    state = _make_state()
    result = serialize(state)
    assert result["taui_version"] == SCHEMA_VERSION


def test_json_dumps_succeeds():
    state = _make_state()
    result = serialize(state)
    dumped = json.dumps(result)
    assert isinstance(dumped, str)
    assert len(dumped) > 0


def test_no_non_json_types():
    state = _make_state()
    result = serialize(state)
    _is_json_safe(result)


# ---------------------------------------------------------------------------
# Top-level fields
# ---------------------------------------------------------------------------


def test_top_level_fields_present():
    state = _make_state()
    result = serialize(state)
    for key in (
        "taui_version",
        "screen",
        "mode",
        "focused",
        "zones",
        "panels",
        "popups",
        "background",
        "status",
        "work",
        "problems",
        "available_actions",
    ):
        assert key in result, f"Missing top-level key: {key}"


def test_screen_mode_focused_forwarded():
    state = _make_state()
    result = serialize(state)
    assert result["screen"] == "main"
    assert result["mode"] == "driving"
    assert result["focused"] == "button.accept"


# ---------------------------------------------------------------------------
# Zones
# ---------------------------------------------------------------------------


def test_zones_are_dict_of_visible():
    state = _make_state()
    result = serialize(state)
    zones = result["zones"]
    assert isinstance(zones, dict)
    for name, zone_dict in zones.items():
        assert isinstance(name, str)
        assert "visible" in zone_dict
        assert isinstance(zone_dict["visible"], bool)


# ---------------------------------------------------------------------------
# Panels — id present
# ---------------------------------------------------------------------------


def test_panels_list():
    state = _make_state()
    result = serialize(state)
    panels = result["panels"]
    assert isinstance(panels, list)
    assert len(panels) == 1


def test_panel_has_id():
    state = _make_state()
    result = serialize(state)
    panel = result["panels"][0]
    assert "id" in panel
    assert panel["id"] == "panel.skills"


def test_panel_has_required_fields():
    state = _make_state()
    result = serialize(state)
    panel = result["panels"][0]
    for key in ("id", "title", "visible", "content_summary", "items"):
        assert key in panel, f"Panel missing key: {key}"


# ---------------------------------------------------------------------------
# Popups — id + actions with selector present
# ---------------------------------------------------------------------------


def test_popups_list():
    state = _make_state()
    result = serialize(state)
    popups = result["popups"]
    assert isinstance(popups, list)
    assert len(popups) == 1


def test_popup_has_id():
    state = _make_state()
    result = serialize(state)
    popup = result["popups"][0]
    assert "id" in popup
    assert popup["id"] == "popup.confirm"


def test_popup_has_required_fields():
    state = _make_state()
    result = serialize(state)
    popup = result["popups"][0]
    for key in (
        "id",
        "kind",
        "visible",
        "blocking",
        "opened_by",
        "reason",
        "message",
        "actions",
        "timeout_ms",
    ):
        assert key in popup, f"Popup missing key: {key}"


def test_popup_actions_have_selector():
    state = _make_state()
    result = serialize(state)
    actions = result["popups"][0]["actions"]
    assert isinstance(actions, list)
    assert len(actions) == 2
    for action in actions:
        assert "selector" in action
        assert "input" in action
        assert "description" in action


# ---------------------------------------------------------------------------
# Status — severity + message
# ---------------------------------------------------------------------------


def test_status_has_severity_and_message():
    state = _make_state()
    result = serialize(state)
    status = result["status"]
    assert "severity" in status
    assert "message" in status
    assert status["severity"] == "error"
    assert status["message"] == "Something went wrong"


# ---------------------------------------------------------------------------
# WorkItem
# ---------------------------------------------------------------------------


def test_drive_present_when_set():
    state = _make_state()
    result = serialize(state)
    drive = result["work"]
    assert drive is not None
    assert drive["task_id"] == "t-123"
    assert drive["running"] is True


def test_drive_none_when_not_set():
    state = CockpitState()
    result = serialize(state)
    assert result["work"] is None


# ---------------------------------------------------------------------------
# available_actions — flattened derived list
# ---------------------------------------------------------------------------


def test_available_actions_is_list():
    state = _make_state()
    result = serialize(state)
    assert isinstance(result["available_actions"], list)


def test_available_actions_includes_popup_accept_selector():
    state = _make_state()
    result = serialize(state)
    selectors = {a["selector"] for a in result["available_actions"]}
    assert (
        "button.accept" in selectors
    ), f"Expected 'button.accept' in available_actions, got: {selectors}"


def test_available_actions_includes_standing_input_prompt():
    state = _make_state()
    result = serialize(state)
    selectors = {a["selector"] for a in result["available_actions"]}
    assert "input.prompt" in selectors, f"Expected 'input.prompt' standing action, got: {selectors}"


def test_available_actions_each_have_selector_input_description():
    state = _make_state()
    result = serialize(state)
    for action in result["available_actions"]:
        assert "selector" in action
        assert "input" in action
        assert "description" in action


def test_available_actions_invisible_popup_excluded():
    """Actions from non-visible popups must NOT appear in available_actions."""
    popup_hidden = Popup(
        id="popup.hidden",
        kind="help",
        visible=False,
        actions=[Action(selector="button.hidden", input="enter", description="Hidden")],
    )
    state = CockpitState(popups=[popup_hidden])
    result = serialize(state)
    selectors = {a["selector"] for a in result["available_actions"]}
    assert "button.hidden" not in selectors


def test_available_actions_no_popup_still_has_standing_action():
    state = CockpitState()
    result = serialize(state)
    selectors = {a["selector"] for a in result["available_actions"]}
    assert "input.prompt" in selectors


# ---------------------------------------------------------------------------
# Background
# ---------------------------------------------------------------------------


def test_background_fields():
    state = _make_state()
    result = serialize(state)
    bg = result["background"]
    for key in ("theme", "animation", "frame", "semantic"):
        assert key in bg, f"Background missing key: {key}"


# ---------------------------------------------------------------------------
# Problems
# ---------------------------------------------------------------------------


def test_problems_forwarded():
    state = CockpitState(problems=[{"code": "E001", "msg": "bad"}])
    result = serialize(state)
    assert result["problems"] == [{"code": "E001", "msg": "bad"}]


# ---------------------------------------------------------------------------
# Empty state — safe defaults
# ---------------------------------------------------------------------------


def test_empty_state_serializes_cleanly():
    state = CockpitState()
    result = serialize(state)
    _is_json_safe(result)
    assert result["taui_version"] == "0.2"
    assert result["panels"] == []
    assert result["popups"] == []
    assert result["work"] is None
    assert result["problems"] == []
