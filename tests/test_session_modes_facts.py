"""Tests for session_modes mode-facts helpers (task t3).

Verifies that mode_facts, ModeFacts, and mode_facts_fragment derive their
values exclusively from session_modes.MODES + profiles.MODE_PROFILES.
"""

from __future__ import annotations

import pytest

from colleague.profiles import MODE_PROFILES
from colleague.session_modes import MODES, ModeFacts, mode_facts, mode_facts_fragment

# ── Acceptance criterion 1: mode_facts for every mode ──────────────────────


class TestModeFactsDataclass:
    """mode_facts builds ModeFacts for every mode in MODES."""

    def test_mode_facts_for_all_modes(self) -> None:
        """Every mode in MODES produces a ModeFacts without error."""
        for mode in MODES:
            facts = mode_facts(mode)
            assert isinstance(facts, ModeFacts)
            assert facts.behavior == mode

    def test_pinned_modes_have_pinned_source(self) -> None:
        """Non-auto modes have source == 'pinned'."""
        for mode in MODES:
            if mode == "auto":
                continue
            facts = mode_facts(mode)
            assert facts.source == "pinned"

    def test_pinned_modes_have_empty_resolved_from(self) -> None:
        """Non-auto modes have resolved_from == ''."""
        for mode in MODES:
            if mode == "auto":
                continue
            facts = mode_facts(mode)
            assert facts.resolved_from == ""

    def test_auto_mode_has_auto_source(self) -> None:
        """auto mode has source == 'auto'."""
        facts = mode_facts("auto")
        assert facts.source == "auto"

    def test_auto_mode_empty_resolved_from(self) -> None:
        """auto mode with no resolved_from has resolved_from == ''."""
        facts = mode_facts("auto")
        assert facts.resolved_from == ""

    def test_auto_mode_empty_profile_rows(self) -> None:
        """auto mode with no resolved_from has empty profile_rows."""
        facts = mode_facts("auto")
        assert facts.profile_rows == ()


# ── Acceptance criterion 3: auto with resolved_from ────────────────────────


class TestAutoWithResolvedFrom:
    """mode_facts('auto', resolved_from='work') uses the work profile."""

    def test_auto_resolved_from_behavior_stays_auto(self) -> None:
        facts = mode_facts("auto", resolved_from="work")
        assert facts.behavior == "auto"

    def test_auto_resolved_from_source_is_auto(self) -> None:
        facts = mode_facts("auto", resolved_from="work")
        assert facts.source == "auto"

    def test_auto_resolved_from_field(self) -> None:
        facts = mode_facts("auto", resolved_from="work")
        assert facts.resolved_from == "work"

    def test_auto_resolved_from_profile_rows_match_work(self) -> None:
        """profile_rows for auto→work reflect the work profile (steps 40)."""
        facts = mode_facts("auto", resolved_from="work")
        # Find the steps row
        steps_row = [r for r in facts.profile_rows if r[0] == "steps"]
        assert len(steps_row) == 1
        assert steps_row[0][1] == "40"

    def test_auto_resolved_from_all_profile_fields(self) -> None:
        """All profile fields appear in profile_rows for auto→work."""
        facts = mode_facts("auto", resolved_from="work")
        labels = {r[0] for r in facts.profile_rows}
        expected_labels = {"steps", "timeout", "context budget", "fill-line", "synthesis reserve"}
        assert labels == expected_labels

    def test_auto_resolved_from_values_match_profile(self) -> None:
        """Values in profile_rows match the work ModeProfile exactly."""
        facts = mode_facts("auto", resolved_from="work")
        work_profile = MODE_PROFILES["work"]
        assert work_profile is not None
        rows_dict = dict(facts.profile_rows)
        assert rows_dict["steps"] == str(work_profile.max_steps)
        assert rows_dict["timeout"] == f"{work_profile.timeout:g}s"
        assert rows_dict["context budget"] == f"{int(work_profile.context_budget_fraction * 100)}%"
        assert rows_dict["fill-line"] == f"{int(work_profile.fillline_threshold * 100)}%"
        assert rows_dict["synthesis reserve"] == str(work_profile.synthesis_reserve_steps)


# ── Drift test: MODES and MODE_PROFILES stay in sync ────────────────────────


class TestDrift:
    """Ensure MODES and MODE_PROFILES stay in sync — no mode ships without a profile."""

    def test_modes_and_profiles_keys_match(self) -> None:
        """set(MODE_PROFILES) == set(MODES) — no drift between catalogs."""
        assert set(MODE_PROFILES.keys()) == set(MODES)

    def test_every_mode_produces_facts(self) -> None:
        """mode_facts succeeds for every mode in MODES."""
        for mode in MODES:
            facts = mode_facts(mode)
            assert isinstance(facts, ModeFacts)

    def test_non_none_profiles_reflected_in_facts(self) -> None:
        """For every mode with a non-None profile, facts.profile_rows is non-empty."""
        for mode, profile in MODE_PROFILES.items():
            if profile is not None:
                facts = mode_facts(mode)
                assert len(facts.profile_rows) > 0, f"Mode '{mode}' has a profile but empty rows"

    def test_none_profiles_yield_empty_rows(self) -> None:
        """For every mode with a None profile, facts.profile_rows is empty."""
        for mode, profile in MODE_PROFILES.items():
            if profile is None:
                facts = mode_facts(mode)
                assert (
                    facts.profile_rows == ()
                ), f"Mode '{mode}' has None profile but non-empty rows"

    def test_profile_values_match_catalog(self) -> None:
        """Every mode's profile_rows values match MODE_PROFILES exactly."""
        for mode, profile in MODE_PROFILES.items():
            if profile is None:
                continue
            facts = mode_facts(mode)
            rows_dict = dict(facts.profile_rows)
            assert rows_dict["steps"] == str(profile.max_steps)
            assert rows_dict["timeout"] == f"{profile.timeout:g}s"
            assert rows_dict["context budget"] == (f"{int(profile.context_budget_fraction * 100)}%")
            assert rows_dict["fill-line"] == (f"{int(profile.fillline_threshold * 100)}%")
            assert rows_dict["synthesis reserve"] == str(profile.synthesis_reserve_steps)


# ── mode_facts_fragment ─────────────────────────────────────────────────────


class TestModeFactsFragment:
    """mode_facts_fragment produces a one-line status string."""

    def test_fragment_for_pinned_mode(self) -> None:
        """Fragment for a pinned mode includes behavior, source, and profile rows."""
        facts = mode_facts("explore")
        fragment = mode_facts_fragment(facts)
        assert "explore" in fragment
        assert "pinned" in fragment

    def test_fragment_for_auto_no_resolved(self) -> None:
        """Fragment for auto with no resolved_from mentions resolves-per-input."""
        facts = mode_facts("auto")
        fragment = mode_facts_fragment(facts)
        assert "auto" in fragment
        assert "resolves per input" in fragment

    def test_fragment_for_auto_with_resolved(self) -> None:
        """Fragment for auto→work shows the arrow notation."""
        facts = mode_facts("auto", resolved_from="work")
        fragment = mode_facts_fragment(facts)
        assert "auto" in fragment
        assert "work" in fragment
        # Should contain profile data (steps)
        assert "steps" in fragment

    def test_fragment_contains_all_three_facts(self) -> None:
        """Fragment for a pinned mode contains behavior, source, and profile data."""
        facts = mode_facts("work")
        fragment = mode_facts_fragment(facts)
        # behavior
        assert "work" in fragment
        # source
        assert "pinned" in fragment
        # profile (at least one profile row)
        assert "steps" in fragment

    def test_fragment_is_deterministic(self) -> None:
        """Same facts produce the same fragment."""
        facts = mode_facts("plan")
        assert mode_facts_fragment(facts) == mode_facts_fragment(facts)

    def test_fragment_is_non_empty(self) -> None:
        """Fragment is never empty."""
        for mode in MODES:
            facts = mode_facts(mode)
            assert len(mode_facts_fragment(facts)) > 0

    def test_fragment_for_auto_resolved_from_shows_arrow(self) -> None:
        """auto→work fragment uses arrow notation for resolved_from."""
        facts = mode_facts("auto", resolved_from="work")
        fragment = mode_facts_fragment(facts)
        assert "auto→work" in fragment


# ── ModeFacts immutability ──────────────────────────────────────────────────


class TestModeFactsImmutability:
    """ModeFacts is frozen (immutable)."""

    def test_mode_facts_is_frozen(self) -> None:
        """ModeFacts cannot be mutated after creation."""
        facts = mode_facts("work")
        with pytest.raises(AttributeError):  # frozen dataclass → FrozenInstanceError
            facts.behavior = "plan"  # type: ignore-unable-to-set-attribute
