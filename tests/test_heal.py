"""Tests for colleague.heal — pure heal-choice module.

Covers the heal choice model: three choices (commit-onto-work-branch, stash,
abort) with consequence + undo copy, prompt rendering, and input parsing.
No session wiring, no git calls — copy + parsing only.
"""

from __future__ import annotations

import dataclasses

import pytest

from colleague.heal import (
    ABORT,
    COMMIT,
    STASH,
    HealChoice,
    heal_choices,
    parse_heal_choice,
    render_heal_prompt,
)

# ── HealChoice dataclass ──────────────────────────────────────────


class TestHealChoiceDataclass:
    """HealChoice is a frozen dataclass with key, label, consequence, undo."""

    def test_fields(self) -> None:
        c = HealChoice(key="test", label="Test", consequence="does thing", undo="undo thing")
        assert c.key == "test"
        assert c.label == "Test"
        assert c.consequence == "does thing"
        assert c.undo == "undo thing"

    def test_frozen(self) -> None:
        c = HealChoice(key="test", label="Test", consequence="x", undo="y")
        with pytest.raises(dataclasses.FrozenInstanceError):
            c.key = "other"  # type: ignore


# ── Module constants ──────────────────────────────────────────────


class TestModuleConstants:
    """COMMIT, STASH, ABORT are HealChoice instances."""

    def test_commit_is_heal_choice(self) -> None:
        assert isinstance(COMMIT, HealChoice)

    def test_stash_is_heal_choice(self) -> None:
        assert isinstance(STASH, HealChoice)

    def test_abort_is_heal_choice(self) -> None:
        assert isinstance(ABORT, HealChoice)

    def test_commit_key(self) -> None:
        assert COMMIT.key == "commit-onto-work-branch"

    def test_stash_key(self) -> None:
        assert STASH.key == "stash"

    def test_abort_key(self) -> None:
        assert ABORT.key == "abort"


# ── heal_choices list ─────────────────────────────────────────────


class TestHealChoices:
    """heal_choices is the ordered list of three HealChoice constants."""

    def test_length(self) -> None:
        assert len(heal_choices) == 3

    def test_contains_constants(self) -> None:
        assert COMMIT in heal_choices
        assert STASH in heal_choices
        assert ABORT in heal_choices

    def test_order(self) -> None:
        assert heal_choices[0] is COMMIT
        assert heal_choices[1] is STASH
        assert heal_choices[2] is ABORT


# ── render_heal_prompt ────────────────────────────────────────────


class TestRenderHealPrompt:
    """render_heal_prompt() returns prompt text with consequence AND undo verbatim."""

    def test_returns_string(self) -> None:
        prompt = render_heal_prompt()
        assert isinstance(prompt, str)

    def test_contains_commit_consequence(self) -> None:
        prompt = render_heal_prompt()
        assert "commits your uncommitted tracked edits onto the work branch" in prompt

    def test_contains_stash_undo(self) -> None:
        prompt = render_heal_prompt()
        assert "git stash pop" in prompt

    def test_contains_all_labels(self) -> None:
        prompt = render_heal_prompt()
        assert COMMIT.label in prompt
        assert STASH.label in prompt
        assert ABORT.label in prompt

    def test_contains_all_keys(self) -> None:
        prompt = render_heal_prompt()
        assert COMMIT.key in prompt
        assert STASH.key in prompt
        assert ABORT.key in prompt

    def test_contains_commit_undo(self) -> None:
        prompt = render_heal_prompt()
        assert COMMIT.undo in prompt

    def test_contains_stash_consequence(self) -> None:
        prompt = render_heal_prompt()
        assert STASH.consequence in prompt

    def test_contains_abort_consequence(self) -> None:
        prompt = render_heal_prompt()
        assert ABORT.consequence in prompt

    def test_contains_abort_undo(self) -> None:
        prompt = render_heal_prompt()
        assert ABORT.undo in prompt

    def test_numbered_choices(self) -> None:
        prompt = render_heal_prompt()
        assert "1." in prompt
        assert "2." in prompt
        assert "3." in prompt


# ── parse_heal_choice ────────────────────────────────────────────


class TestParseHealChoice:
    """parse_heal_choice accepts '1'/'2'/'3' and key strings; defaults to ABORT."""

    def test_empty_aborts(self) -> None:
        assert parse_heal_choice("") is ABORT

    def test_unknown_aborts(self) -> None:
        assert parse_heal_choice("unknown") is ABORT

    def test_number_1_is_commit(self) -> None:
        assert parse_heal_choice("1") is COMMIT

    def test_number_2_is_stash(self) -> None:
        assert parse_heal_choice("2") is STASH

    def test_number_3_is_abort(self) -> None:
        assert parse_heal_choice("3") is ABORT

    def test_key_commit(self) -> None:
        assert parse_heal_choice("commit-onto-work-branch") is COMMIT

    def test_key_stash(self) -> None:
        assert parse_heal_choice("stash") is STASH

    def test_key_abort(self) -> None:
        assert parse_heal_choice("abort") is ABORT

    def test_whitespace_only_aborts(self) -> None:
        assert parse_heal_choice("  ") is ABORT

    def test_out_of_range_number_aborts(self) -> None:
        assert parse_heal_choice("4") is ABORT
        assert parse_heal_choice("0") is ABORT
