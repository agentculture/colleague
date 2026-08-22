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


class TestThinkingEffortAndResume:
    """#416: the wrapper exposes per-seat thinking effort + a resume verb (PR #419)."""

    def _script(self) -> str:
        return (SKILL_MD.parent / "scripts" / "ask-colleague.sh").read_text(encoding="utf-8")

    def test_usage_documents_resume_and_effort(self) -> None:
        text = self._script()
        assert "ask-colleague resume  <task-id|last>" in text
        assert "--effort RUNG" in text
        assert "--seat-effort S=R" in text

    def test_resume_uses_continue_and_setsid_for_detach(self) -> None:
        text = self._script()
        assert 'work --continue "$fid"' in text
        assert "setsid nohup" in text  # colleague#418: --background drops the continue id

    def test_effort_is_validated_and_exported(self) -> None:
        text = self._script()
        assert "off | low | medium | high | xhigh | default) : ;;" in text
        assert 'export COLLEAGUE_CORTEX_REASONING_EFFORT="$EFFORT"' in text
        assert "_REASONING_EFFORT=$_rung" in text

    def test_skill_md_documents_the_surface(self) -> None:
        text = SKILL_MD.read_text(encoding="utf-8")
        for needle in (
            "`resume <task-id\\|last> [--detach]`",
            "`--effort RUNG`",
            "`--seat-effort S=R[,S=R]`",
            "## Thinking effort and resuming (#416)",
        ):
            assert needle in text, needle
