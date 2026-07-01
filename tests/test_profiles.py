"""Tests for colleague.profiles — the mode-profile catalog (t1, R1).

Covers the two t1 acceptance criteria from
docs/plans/2026-07-01-colleague-s-work-modes-explore-plan-review-work-no.md:

1. ``resolve_profile`` returns a complete profile for each of
   work/plan/explore/review and ``None`` for absent/unknown/``auto``.
2. A drift test pins exactly one profile per ``session_modes.MODES`` entry so
   a new mode can never ship without a profile decision.

Also pins that the ``work`` profile is exactly today's ``EngineConfig``
built-in defaults (byte-identical / behavior-neutral selection), per the R1
honesty condition.
"""

from __future__ import annotations

from colleague.config import EngineConfig
from colleague.profiles import MODE_PROFILES, ModeProfile, resolve_profile
from colleague.session_modes import MODES

# ---------------------------------------------------------------------------
# Acceptance criterion 1: resolve_profile
# ---------------------------------------------------------------------------


class TestResolveProfile:
    """resolve_profile returns a complete profile for a known mode, else None."""

    def test_resolve_work(self) -> None:
        profile = resolve_profile("work")
        assert isinstance(profile, ModeProfile)

    def test_resolve_plan(self) -> None:
        profile = resolve_profile("plan")
        assert isinstance(profile, ModeProfile)

    def test_resolve_explore(self) -> None:
        profile = resolve_profile("explore")
        assert isinstance(profile, ModeProfile)

    def test_resolve_review(self) -> None:
        profile = resolve_profile("review")
        assert isinstance(profile, ModeProfile)

    def test_profile_is_complete(self) -> None:
        """Every concrete-mode profile carries all five constraint fields."""
        for mode in ("work", "plan", "explore", "review"):
            profile = resolve_profile(mode)
            assert profile is not None, f"{mode!r} should resolve to a profile"
            assert isinstance(profile.max_steps, int)
            assert isinstance(profile.context_budget_fraction, float)
            assert isinstance(profile.synthesis_reserve_steps, int)
            assert isinstance(profile.timeout, float)
            assert isinstance(profile.fillline_threshold, float)

    def test_resolve_none_returns_none(self) -> None:
        assert resolve_profile(None) is None

    def test_resolve_auto_returns_none(self) -> None:
        """'auto' routes to a concrete mode before profile lookup matters —
        an explicit no-profile decision, not an oversight."""
        assert resolve_profile("auto") is None

    def test_resolve_unknown_returns_none(self) -> None:
        assert resolve_profile("bogus-mode") is None

    def test_resolve_empty_string_returns_none(self) -> None:
        assert resolve_profile("") is None


# ---------------------------------------------------------------------------
# Acceptance criterion 2: drift test — one profile decision per session mode
# ---------------------------------------------------------------------------


class TestModeProfilesDriftGuard:
    """MODE_PROFILES carries exactly one explicit entry per session_modes.MODES.

    This is the guard: a new mode added to session_modes.MODES without a
    corresponding MODE_PROFILES entry fails this test, so a mode can never
    ship without an explicit profile decision (even 'no profile' == None).
    """

    def test_every_session_mode_has_an_explicit_entry(self) -> None:
        missing = [m for m in MODES if m not in MODE_PROFILES]
        assert not missing, f"MODE_PROFILES is missing an entry for modes: {missing}"

    def test_no_extra_entries_beyond_session_modes(self) -> None:
        """MODE_PROFILES should not carry stale/unknown mode keys either."""
        extra = [m for m in MODE_PROFILES if m not in MODES]
        assert not extra, f"MODE_PROFILES has entries for unknown modes: {extra}"

    def test_catalog_keys_exactly_match_modes(self) -> None:
        assert set(MODE_PROFILES) == set(MODES)

    def test_auto_is_explicitly_none(self) -> None:
        """'auto' must be an explicit key (not merely absent) mapping to None."""
        assert "auto" in MODE_PROFILES
        assert MODE_PROFILES["auto"] is None


# ---------------------------------------------------------------------------
# Additional acceptance: 'work' profile == EngineConfig built-in defaults
# ---------------------------------------------------------------------------


class TestWorkProfileMatchesEngineConfigDefaults:
    """Selecting work-mode must be behavior-neutral: its profile mirrors
    EngineConfig's built-in defaults exactly, so drift between the two is
    caught here rather than discovered at runtime."""

    def test_work_profile_matches_engine_config_defaults(self) -> None:
        defaults = EngineConfig()
        profile = resolve_profile("work")
        assert profile is not None

        assert profile.max_steps == defaults.max_steps
        assert profile.synthesis_reserve_steps == defaults.synthesis_reserve_steps
        assert profile.timeout == defaults.timeout
        assert profile.fillline_threshold == defaults.fillline_threshold
        # context_budget_fraction has no direct EngineConfig counterpart (it is
        # a *fraction* of context_budget_tokens, introduced by this module) —
        # 1.0 encodes "no scaling", i.e. the full resolved budget, unchanged.
        assert profile.context_budget_fraction == 1.0


# ---------------------------------------------------------------------------
# Purity: ModeProfile is frozen, and resolve_profile has no side effects.
# ---------------------------------------------------------------------------


class TestModeProfileIsFrozen:
    def test_mode_profile_is_immutable(self) -> None:
        profile = resolve_profile("work")
        assert profile is not None
        try:
            profile.max_steps = 999  # type: ignore[misc]
        except Exception as exc:  # dataclasses.FrozenInstanceError
            assert "frozen" in str(exc).lower() or "FrozenInstance" in type(exc).__name__
        else:
            raise AssertionError("ModeProfile should be frozen (immutable)")

    def test_resolve_profile_is_pure(self) -> None:
        """Calling resolve_profile repeatedly returns the same values (no
        hidden state / no I/O)."""
        first = resolve_profile("explore")
        second = resolve_profile("explore")
        assert first == second
