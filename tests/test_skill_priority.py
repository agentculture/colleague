"""Skill-priority marker parsing (t11, spec R4 / honesty condition h4).

``<!-- skill-priority: N -->`` is an optional HTML-comment marker in a skill
doc's markdown — the same idiom as learn-from's ``<!-- learned-from: ... -->``
provenance marker. Lower ``N`` = higher priority (survives longest when the
composed catalog must be capped). Absent or malformed markers default to
``SKILL_PRIORITY_DEFAULT`` (100).

Acceptance (TDD list item a):
- present: parses the integer value (including negative values).
- absent: defaults to 100.
- malformed (non-integer): defaults to 100.
- the marker may appear anywhere in the doc, not just the first line.
- it never leaks into the composed summary line (the "first descriptive line"
  picker skips single-line HTML comments generically).
"""

from __future__ import annotations

from pathlib import Path

from colleague import layers


def test_priority_marker_present_parses_value() -> None:
    text = "<!-- skill-priority: 5 -->\n# skill\nBody text."
    assert layers.parse_skill_priority(text) == 5


def test_priority_marker_absent_defaults_to_100() -> None:
    text = "# skill\nNo marker here at all."
    assert layers.parse_skill_priority(text) == 100
    assert layers.SKILL_PRIORITY_DEFAULT == 100


def test_priority_marker_malformed_value_defaults_to_100() -> None:
    # Non-integer value does not match the marker regex → default.
    text = "<!-- skill-priority: abc -->\n# skill\nBody."
    assert layers.parse_skill_priority(text) == layers.SKILL_PRIORITY_DEFAULT


def test_priority_marker_missing_value_defaults_to_100() -> None:
    text = "<!-- skill-priority: -->\n# skill\nBody."
    assert layers.parse_skill_priority(text) == layers.SKILL_PRIORITY_DEFAULT


def test_priority_marker_negative_value_parses() -> None:
    text = "<!-- skill-priority: -3 -->\n# skill\nBody."
    assert layers.parse_skill_priority(text) == -3


def test_priority_marker_anywhere_in_text_not_only_first_line() -> None:
    text = "# skill\nSome summary line.\n\nMore body.\n<!-- skill-priority: 1 -->\ntail."
    assert layers.parse_skill_priority(text) == 1


def test_empty_text_defaults_to_100() -> None:
    assert layers.parse_skill_priority("") == 100


# --- skill_priority(): the Skill-object convenience wrapper -----------------


def test_skill_priority_reads_file_and_parses_marker(tmp_path: Path) -> None:
    path = tmp_path / "s.md"
    path.write_text("<!-- skill-priority: 7 -->\n# s\nBody.", encoding="utf-8")
    skill = layers.Skill(name="s", path=path, scope=layers.SKILL_BASE)
    assert layers.skill_priority(skill) == 7


def test_skill_priority_degrades_to_default_on_unreadable_file(tmp_path: Path) -> None:
    missing = tmp_path / "missing.md"  # never created
    skill = layers.Skill(name="missing", path=missing, scope=layers.SKILL_BASE)
    assert layers.skill_priority(skill) == layers.SKILL_PRIORITY_DEFAULT


def test_skill_priority_defaults_when_no_marker(tmp_path: Path) -> None:
    path = tmp_path / "plain.md"
    path.write_text("# plain\nJust a plain skill, no marker.", encoding="utf-8")
    skill = layers.Skill(name="plain", path=path, scope=layers.SKILL_BASE)
    assert layers.skill_priority(skill) == layers.SKILL_PRIORITY_DEFAULT


# --- the marker never leaks into the composed summary line ------------------


def test_priority_marker_as_first_line_does_not_leak_into_summary() -> None:
    """A skill-priority marker placed before the heading must never itself
    become the composed catalog's one-line summary (it is metadata, not
    content) — this is the same guarantee learn-from's provenance marker
    relies on, generalized to any single-line HTML comment."""
    text = "<!-- skill-priority: 5 -->\n# beta\nBeta's real summary line."
    assert layers._first_summary_line(text) == "Beta's real summary line."


def test_priority_marker_mid_body_does_not_leak_into_summary() -> None:
    text = "# beta\nBeta's real summary line.\n<!-- skill-priority: 5 -->\nMore body."
    assert layers._first_summary_line(text) == "Beta's real summary line."
