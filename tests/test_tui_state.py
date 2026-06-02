"""Tests for colleague.tui.state — CockpitState round-trip and field presence."""

import json

from colleague.tui.state import (
    Action,
    Background,
    CockpitState,
    Drive,
    Panel,
    PanelItem,
    Popup,
    Status,
    Zone,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def minimal_state() -> CockpitState:
    """Return a CockpitState with all defaults (no nested objects set)."""
    return CockpitState()


def rich_state() -> CockpitState:
    """Return a CockpitState with all nested objects populated for round-trip."""
    action = Action(selector="button.ok", input="enter", description="Confirm")
    item = PanelItem(id="skill-1", label="My Skill", status="active")
    panel = Panel(
        id="skills",
        title="Skills Panel",
        visible=True,
        content_summary="1 skill",
        items=[item],
    )
    popup = Popup(
        id="popup-1",
        kind="confirmation",
        visible=True,
        blocking=True,
        opened_by="user",
        reason="test reason",
        message="Are you sure?",
        actions=[action],
        timeout_ms=5000,
    )
    zone = Zone(visible=True)
    bg = Background(theme="dark", animation="pulse", frame=42, semantic="busy")
    status = Status(severity="warn", message="Heads up")
    drive = Drive(task_id="abc123", engine="vllm-openai", step_count=3, running=True)
    return CockpitState(
        screen="drive",
        mode="executing",
        focused="main.conversation",
        zones={"top.status": zone, "left.skills": Zone(visible=False)},
        panels=[panel],
        popups=[popup],
        background=bg,
        status=status,
        drive=drive,
        problems=[{"code": "E001", "message": "Something went wrong"}],
    )


# ---------------------------------------------------------------------------
# Acceptance criterion 1: round-trip equality
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_minimal_state_round_trip(self) -> None:
        s = minimal_state()
        assert CockpitState.from_dict(s.to_dict()) == s

    def test_rich_state_round_trip(self) -> None:
        s = rich_state()
        assert CockpitState.from_dict(s.to_dict()) == s

    def test_round_trip_is_json_serializable(self) -> None:
        """to_dict() must produce a dict that json.dumps() accepts."""
        s = rich_state()
        d = s.to_dict()
        dumped = json.dumps(d)
        assert isinstance(dumped, str)

    def test_nested_popup_with_actions_round_trip(self) -> None:
        action = Action(selector="btn.yes", input="enter", description="Yes")
        popup = Popup(
            id="p1",
            kind="error",
            visible=True,
            blocking=False,
            opened_by="agent",
            reason="oops",
            message="Error occurred",
            actions=[action],
            timeout_ms=None,
        )
        s = CockpitState(popups=[popup])
        assert CockpitState.from_dict(s.to_dict()) == s

    def test_nested_panel_with_items_round_trip(self) -> None:
        item = PanelItem(id="i1", label="Item One", status="available")
        panel = Panel(id="p1", title="Panel One", visible=False, items=[item])
        s = CockpitState(panels=[panel])
        assert CockpitState.from_dict(s.to_dict()) == s

    def test_drive_none_round_trip(self) -> None:
        s = CockpitState(drive=None)
        assert CockpitState.from_dict(s.to_dict()) == s

    def test_drive_present_round_trip(self) -> None:
        s = CockpitState(drive=Drive(task_id="t1", engine="mock", step_count=0, running=False))
        assert CockpitState.from_dict(s.to_dict()) == s

    def test_problems_list_round_trip(self) -> None:
        s = CockpitState(problems=[{"code": "W1", "message": "a warning"}])
        assert CockpitState.from_dict(s.to_dict()) == s

    def test_zones_dict_round_trip(self) -> None:
        zones = {
            "top.status": Zone(visible=True),
            "left.skills": Zone(visible=False),
        }
        s = CockpitState(zones=zones)
        assert CockpitState.from_dict(s.to_dict()) == s


# ---------------------------------------------------------------------------
# Acceptance criterion 2: field presence (structure check)
# ---------------------------------------------------------------------------


class TestFieldPresence:
    def test_screen_field(self) -> None:
        s = CockpitState()
        assert s.screen == "main"

    def test_mode_field(self) -> None:
        s = CockpitState()
        assert s.mode == "planning"

    def test_focused_field(self) -> None:
        s = CockpitState()
        assert s.focused == "input.prompt"

    def test_zones_field_has_four_defaults(self) -> None:
        s = CockpitState()
        assert "top.status" in s.zones
        assert "left.skills" in s.zones
        assert "main.conversation" in s.zones
        assert "bottom.input" in s.zones

    def test_all_default_zones_visible(self) -> None:
        s = CockpitState()
        for zone in s.zones.values():
            assert zone.visible is True

    def test_panels_field_is_list(self) -> None:
        s = CockpitState()
        assert isinstance(s.panels, list)

    def test_popups_field_is_list(self) -> None:
        s = CockpitState()
        assert isinstance(s.popups, list)

    def test_background_field_has_frame(self) -> None:
        s = CockpitState()
        assert hasattr(s.background, "frame")
        assert isinstance(s.background.frame, int)

    def test_background_frame_default_zero(self) -> None:
        bg = Background()
        assert bg.frame == 0

    def test_background_frame_survives_round_trip(self) -> None:
        s = CockpitState(background=Background(frame=7))
        s2 = CockpitState.from_dict(s.to_dict())
        assert s2.background.frame == 7

    def test_status_field_has_severity(self) -> None:
        s = CockpitState()
        assert hasattr(s.status, "severity")
        assert isinstance(s.status.severity, str)

    def test_status_field_has_message(self) -> None:
        s = CockpitState()
        assert hasattr(s.status, "message")
        assert isinstance(s.status.message, str)

    def test_status_defaults(self) -> None:
        st = Status()
        assert st.severity == "info"
        assert st.message == ""

    def test_drive_field_default_none(self) -> None:
        s = CockpitState()
        assert s.drive is None

    def test_problems_field_default_empty(self) -> None:
        s = CockpitState()
        assert s.problems == []

    def test_to_dict_contains_all_top_level_keys(self) -> None:
        d = CockpitState().to_dict()
        for key in (
            "screen",
            "mode",
            "focused",
            "zones",
            "panels",
            "popups",
            "background",
            "status",
            "drive",
            "problems",
        ):
            assert key in d, f"Missing key: {key}"

    def test_mutable_defaults_are_independent(self) -> None:
        """Two CockpitState instances must not share mutable defaults."""
        a = CockpitState()
        b = CockpitState()
        a.panels.append(Panel(id="x", title="X"))
        assert b.panels == []

    def test_mutable_popup_actions_independent(self) -> None:
        a = Popup(id="p1", kind="info")
        b = Popup(id="p2", kind="info")
        a.actions.append(Action(selector="x", input="enter"))
        assert b.actions == []

    def test_popup_timeout_ms_none_round_trip(self) -> None:
        p = Popup(id="p1", kind="progress", timeout_ms=None)
        s = CockpitState(popups=[p])
        s2 = CockpitState.from_dict(s.to_dict())
        assert s2.popups[0].timeout_ms is None

    def test_popup_timeout_ms_int_round_trip(self) -> None:
        p = Popup(id="p1", kind="progress", timeout_ms=3000)
        s = CockpitState(popups=[p])
        s2 = CockpitState.from_dict(s.to_dict())
        assert s2.popups[0].timeout_ms == 3000

    def test_action_description_default_empty(self) -> None:
        a = Action(selector="btn", input="enter")
        assert a.description == ""

    def test_panel_item_status_default(self) -> None:
        item = PanelItem(id="i1", label="Label")
        assert item.status == "available"

    def test_drive_dataclass_fields(self) -> None:
        d = Drive(task_id="t1", engine="mock", step_count=2, running=True)
        assert d.task_id == "t1"
        assert d.engine == "mock"
        assert d.step_count == 2
        assert d.running is True
