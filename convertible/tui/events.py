"""Event types for the TUI reducer — a discriminated union with JSONL helpers.

Events represent discrete interactions (user input, key presses, ticks) and
drive progress (drive steps, skill suggestions). The reducer folds these into
state, and the render function displays the resulting UI. Each event type
carries an explicit string discriminator (`type` class attribute) so the union
round-trips through JSON cleanly.
"""

import json
from dataclasses import dataclass
from typing import Any, ClassVar


@dataclass
class UserInput:
    """User text input — e.g. a command or response."""

    type: ClassVar[str] = "user_input"
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "text": self.text}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UserInput":
        return cls(text=str(data["text"]))


@dataclass
class KeyPress:
    """A keyboard event — key name like 'enter', 'tab', 'esc', 'up', 'down'."""

    type: ClassVar[str] = "key"
    key: str

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "key": self.key}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "KeyPress":
        return cls(key=str(data["key"]))


@dataclass
class Tick:
    """Animation frame tick — advances the frame counter by delta."""

    type: ClassVar[str] = "tick"
    delta: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "delta": self.delta}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Tick":
        return cls(delta=int(data.get("delta", 1)))


@dataclass
class SkillSuggested:
    """A skill suggestion — the name and reason it was recommended."""

    type: ClassVar[str] = "skill_suggested"
    skill: str
    reason: str = ""
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "skill": self.skill,
            "reason": self.reason,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SkillSuggested":
        return cls(
            skill=str(data["skill"]),
            reason=str(data.get("reason", "")),
            confidence=float(data.get("confidence", 0.0)),
        )


@dataclass
class Dismiss:
    """Dismiss a popup or overlay — target is the id/selector."""

    type: ClassVar[str] = "dismiss"
    target: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "target": self.target}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Dismiss":
        return cls(target=str(data.get("target", "")))


@dataclass
class DriveStep:
    """A step in the drive — a tool call, its summary, and success status."""

    type: ClassVar[str] = "drive_step"
    tool: str
    summary: str = ""
    ok: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "tool": self.tool,
            "summary": self.summary,
            "ok": self.ok,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DriveStep":
        return cls(
            tool=str(data["tool"]),
            summary=str(data.get("summary", "")),
            ok=bool(data.get("ok", True)),
        )


# Discriminated union type alias for type hints.
Event = UserInput | KeyPress | Tick | SkillSuggested | Dismiss | DriveStep

# Registry mapping type discriminator to event class.
_EVENT_REGISTRY: dict[str, type] = {
    UserInput.type: UserInput,
    KeyPress.type: KeyPress,
    Tick.type: Tick,
    SkillSuggested.type: SkillSuggested,
    Dismiss.type: Dismiss,
    DriveStep.type: DriveStep,
}


def event_from_dict(data: dict[str, Any]) -> Event:
    """Dispatch on the 'type' field to reconstruct the right event class.

    Parameters
    ----------
    data : dict
        A dict with a 'type' field naming the event class.

    Returns
    -------
    Event
        The reconstructed event object.

    Raises
    ------
    ValueError
        If the 'type' field is missing or unknown.
    """
    event_type = data.get("type")
    if event_type not in _EVENT_REGISTRY:
        raise ValueError(f"Unknown event type: {event_type!r}")

    cls = _EVENT_REGISTRY[event_type]
    return cls.from_dict(data)


def dumps_events(events: list[Event]) -> str:
    """Serialize a list of events to JSONL (one JSON object per line).

    Parameters
    ----------
    events : list
        List of Event objects.

    Returns
    -------
    str
        JSONL-formatted string (one json.dumps per line, newline-separated).
        Empty list yields an empty string.
    """
    if not events:
        return ""
    lines = [json.dumps(evt.to_dict()) for evt in events]
    return "\n".join(lines) + "\n"


def loads_events(text: str) -> list[Event]:
    """Parse JSONL text back into event objects, skipping blank lines.

    Parameters
    ----------
    text : str
        JSONL-formatted string (one JSON object per line).

    Returns
    -------
    list
        List of reconstructed Event objects.
    """
    events: list[Event] = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        data = json.loads(line)
        events.append(event_from_dict(data))
    return events
