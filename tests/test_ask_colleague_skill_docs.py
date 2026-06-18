"""Tests for .claude/skills/ask-colleague/SKILL.md documentation content.

Validates issues #218 (provenance paragraph) and #219 (monitor description).
"""

import pathlib

SKILL_MD = (
    pathlib.Path(__file__).resolve().parent.parent
    / ".claude"
    / "skills"
    / "ask-colleague"
    / "SKILL.md"
)


def _read_skill_md() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


def test_provenance_no_guildmaster():
    """Issue #218: SKILL.md must not mention 'guildmaster'."""
    text = _read_skill_md()
    assert "guildmaster" not in text, "SKILL.md should not reference 'guildmaster'"


def test_provenance_mentions_first_party():
    """Issue #218: provenance paragraph must state ask-colleague is first-party."""
    text = _read_skill_md()
    assert "first-party" in text, "SKILL.md should state ask-colleague is first-party"


def test_monitor_describes_live_feed():
    """Issue #219: monitor line must describe a streaming / live feed, not a one-shot read."""
    text = _read_skill_md()
    # The monitor bullet should mention watching/streaming a live feed.
    # We check for the presence of "live feed" in the monitor line.
    monitor_line = None
    for line in text.splitlines():
        if "monitor" in line and "ask-colleague" in line:
            monitor_line = line
            break

    assert monitor_line is not None, "SKILL.md should contain a monitor line"
    assert (
        "live feed" in monitor_line
    ), f"Monitor line should describe a live/streaming feed, got: {monitor_line!r}"
