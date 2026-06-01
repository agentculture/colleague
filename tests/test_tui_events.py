"""Tests for convertible.tui.events — Event union + JSONL (de)serialize."""

import pytest

from convertible.tui.events import (
    Dismiss,
    DriveStep,
    Key,
    SkillSuggested,
    Tick,
    UserInput,
    dumps_events,
    event_from_dict,
    loads_events,
)


class TestEventTypes:
    """Each event type round-trips through to_dict/from_dict."""

    def test_user_input(self):
        evt = UserInput(text="hello world")
        assert evt.to_dict() == {"type": "user_input", "text": "hello world"}
        assert event_from_dict(evt.to_dict()) == evt

    def test_key(self):
        evt = Key(key="enter")
        assert evt.to_dict() == {"type": "key", "key": "enter"}
        assert event_from_dict(evt.to_dict()) == evt

    def test_key_variants(self):
        for key_name in ["tab", "esc", "up", "down"]:
            evt = Key(key=key_name)
            assert event_from_dict(evt.to_dict()) == evt

    def test_tick_default(self):
        evt = Tick()
        assert evt.to_dict() == {"type": "tick", "delta": 1}
        assert event_from_dict(evt.to_dict()) == evt

    def test_tick_custom(self):
        evt = Tick(delta=5)
        assert evt.to_dict() == {"type": "tick", "delta": 5}
        assert event_from_dict(evt.to_dict()) == evt

    def test_skill_suggested_defaults(self):
        evt = SkillSuggested(skill="review")
        assert evt.to_dict() == {
            "type": "skill_suggested",
            "skill": "review",
            "reason": "",
            "confidence": 0.0,
        }
        assert event_from_dict(evt.to_dict()) == evt

    def test_skill_suggested_full(self):
        evt = SkillSuggested(skill="review", reason="found a bug", confidence=0.95)
        assert evt.to_dict() == {
            "type": "skill_suggested",
            "skill": "review",
            "reason": "found a bug",
            "confidence": 0.95,
        }
        assert event_from_dict(evt.to_dict()) == evt

    def test_dismiss_default(self):
        evt = Dismiss()
        assert evt.to_dict() == {"type": "dismiss", "target": ""}
        assert event_from_dict(evt.to_dict()) == evt

    def test_dismiss_custom(self):
        evt = Dismiss(target="error-popup")
        assert evt.to_dict() == {"type": "dismiss", "target": "error-popup"}
        assert event_from_dict(evt.to_dict()) == evt

    def test_drive_step_defaults(self):
        evt = DriveStep(tool="read_file")
        assert evt.to_dict() == {
            "type": "drive_step",
            "tool": "read_file",
            "summary": "",
            "ok": True,
        }
        assert event_from_dict(evt.to_dict()) == evt

    def test_drive_step_full(self):
        evt = DriveStep(tool="run_command", summary="compiled ok", ok=True)
        assert evt.to_dict() == {
            "type": "drive_step",
            "tool": "run_command",
            "summary": "compiled ok",
            "ok": True,
        }
        assert event_from_dict(evt.to_dict()) == evt

    def test_drive_step_failed(self):
        evt = DriveStep(tool="run_command", summary="build failed", ok=False)
        assert evt.to_dict() == {
            "type": "drive_step",
            "tool": "run_command",
            "summary": "build failed",
            "ok": False,
        }
        assert event_from_dict(evt.to_dict()) == evt


class TestEventFromDict:
    """event_from_dict dispatches on type and raises ValueError for unknown types."""

    def test_unknown_type_raises(self):
        with pytest.raises(ValueError, match="Unknown event type"):
            event_from_dict({"type": "nope"})

    def test_missing_type_raises(self):
        with pytest.raises(ValueError, match="Unknown event type"):
            event_from_dict({})


class TestJSONL:
    """JSONL (de)serialize round-trips."""

    def test_single_event(self):
        evt = UserInput(text="test")
        serialized = dumps_events([evt])
        deserialized = loads_events(serialized)
        assert deserialized == [evt]

    def test_mixed_events(self):
        events = [
            UserInput(text="hello"),
            Key(key="enter"),
            Tick(delta=2),
            SkillSuggested(skill="review", reason="bug", confidence=0.8),
            Dismiss(target="popup"),
            DriveStep(tool="read_file", summary="ok", ok=True),
        ]
        serialized = dumps_events(events)
        deserialized = loads_events(serialized)
        assert deserialized == events

    def test_empty_list(self):
        serialized = dumps_events([])
        deserialized = loads_events(serialized)
        assert deserialized == []

    def test_blank_lines_ignored(self):
        text = (
            '{"type": "user_input", "text": "hi"}\n'
            "\n"
            '{"type": "key", "key": "enter"}\n'
            "   \n"
            '{"type": "tick", "delta": 1}\n'
        )
        deserialized = loads_events(text)
        assert len(deserialized) == 3
        assert deserialized[0] == UserInput(text="hi")
        assert deserialized[1] == Key(key="enter")
        assert deserialized[2] == Tick(delta=1)

    def test_roundtrip_preserves_equality(self):
        """Complete roundtrip through JSONL preserves object equality."""
        original = [
            UserInput(text="start"),
            Key(key="up"),
            Tick(delta=3),
            SkillSuggested(skill="write", reason="new feature", confidence=0.9),
            Dismiss(target="error"),
            DriveStep(tool="run_command", summary="tests pass", ok=True),
        ]
        serialized = dumps_events(original)
        deserialized = loads_events(serialized)
        assert deserialized == original
