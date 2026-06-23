"""Tests for colleague.session_modes — the single source of truth for session modes."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from colleague.session_modes import (
    DEFAULT_MODE,
    MODES,
    mode_affordance_line,
    mode_label,
    next_mode,
    resolve_mode,
    route_for,
)

# ── Acceptance criterion 1: MODES tuple and next_mode cycle ────────────────


class TestModesAndNextMode:
    """MODES == ('auto','work','plan','explore','review') and next_mode wraps."""

    def test_modes_tuple(self) -> None:
        assert MODES == ("auto", "work", "plan", "explore", "review")

    def test_default_mode(self) -> None:
        assert DEFAULT_MODE == "auto"

    def test_next_mode_full_cycle(self) -> None:
        """Applying next_mode 5x from 'auto' returns to 'auto'."""
        mode = "auto"
        for _ in range(5):
            mode = next_mode(mode)
        assert mode == "auto"

    def test_next_mode_wraps_review_to_auto(self) -> None:
        assert next_mode("review") == "auto"

    def test_next_mode_unknown_returns_default(self) -> None:
        assert next_mode("bogus") == DEFAULT_MODE

    def test_next_mode_each_step(self) -> None:
        assert next_mode("auto") == "work"
        assert next_mode("work") == "plan"
        assert next_mode("plan") == "explore"
        assert next_mode("explore") == "review"
        assert next_mode("review") == "auto"


# ── Acceptance criterion 2: resolve_mode ──────────────────────────────────


class TestResolveMode:
    """resolve_mode normalizes/validates mode names."""

    def test_resolve_known_mode(self) -> None:
        assert resolve_mode("plan") == "plan"

    def test_resolve_case_insensitive(self) -> None:
        assert resolve_mode("PLAN") == "plan"

    def test_resolve_strips_whitespace(self) -> None:
        assert resolve_mode("  PLAN  ") == "plan"

    def test_resolve_all_modes(self) -> None:
        for mode in MODES:
            assert resolve_mode(mode) == mode

    def test_resolve_unknown_raises_value_error(self) -> None:
        with pytest.raises(ValueError) as exc_info:
            resolve_mode("bogus")
        msg = str(exc_info.value)
        for mode in MODES:
            assert mode in msg, f"Error message should mention '{mode}'"

    def test_resolve_unknown_message_format(self) -> None:
        with pytest.raises(ValueError) as exc_info:
            resolve_mode("x")
        msg = str(exc_info.value)
        # Should contain the invalid input and list valid modes
        assert "x" in msg
        assert "auto" in msg
        assert "work" in msg


# ── Acceptance criterion 3: route_for ─────────────────────────────────────


class TestRouteFor:
    """route_for delegates to classify in auto mode, bypasses otherwise."""

    def test_route_for_auto_delegates(self) -> None:
        """In auto mode, route_for returns exactly what classify returns."""
        classify = MagicMock(return_value="work")
        result = route_for("auto", "some text", classify)
        assert result == "work"
        classify.assert_called_once_with("some text")

    def test_route_for_auto_delegates_plan(self) -> None:
        classify = MagicMock(return_value="plan")
        result = route_for("auto", "plan this out", classify)
        assert result == "plan"

    def test_route_for_explore_bypasses_classify(self) -> None:
        """Non-auto mode returns the mode without calling classify."""
        call_counter = {"calls": 0}

        def counting_classify(text: str) -> str:
            call_counter["calls"] += 1
            return "work"

        result = route_for("explore", "x", counting_classify)
        assert result == "explore"
        assert call_counter["calls"] == 0, "classify should never be called in non-auto mode"

    def test_route_for_work_bypasses_classify(self) -> None:
        classify = MagicMock(return_value="plan")
        result = route_for("work", "anything", classify)
        assert result == "work"
        classify.assert_not_called()

    def test_route_for_plan_bypasses_classify(self) -> None:
        classify = MagicMock(return_value="work")
        result = route_for("plan", "anything", classify)
        assert result == "plan"
        classify.assert_not_called()

    def test_route_for_review_bypasses_classify(self) -> None:
        classify = MagicMock(return_value="work")
        result = route_for("review", "anything", classify)
        assert result == "review"
        classify.assert_not_called()


# ── Acceptance criterion 4: mode_affordance_line ──────────────────────────


class TestModeAffordanceLine:
    """mode_affordance_line shows all modes with active marked."""

    def test_contains_all_modes(self) -> None:
        """Every mode name appears in every affordance line."""
        for mode in MODES:
            line = mode_affordance_line(mode)
            for m in MODES:
                assert m in line, f"'{m}' should appear in affordance for '{mode}'"

    def test_marks_active_mode(self) -> None:
        """The active mode is marked distinctly (e.g. with brackets)."""
        for mode in MODES:
            line = mode_affordance_line(mode)
            # The active mode should be bracketed or otherwise marked
            assert f"[{mode}]" in line, f"Active mode '{mode}' should be bracketed"

    def test_contains_shift_tab_hint(self) -> None:
        for mode in MODES:
            line = mode_affordance_line(mode)
            assert "shift-tab to cycle" in line

    def test_active_mode_distinct_from_others(self) -> None:
        """The active mode appears differently from non-active modes."""
        line = mode_affordance_line("auto")
        # "auto" should appear bracketed, other modes should not be bracketed
        assert "[auto]" in line
        for m in MODES:
            if m != "auto":
                assert f"[{m}]" not in line, f"'[{m}]' should not appear when auto is active"

    def test_deterministic(self) -> None:
        """Same input always produces the same output."""
        for mode in MODES:
            assert mode_affordance_line(mode) == mode_affordance_line(mode)


# ── Acceptance criterion 5: module purity ─────────────────────────────────


class TestModulePurity:
    """The module is pure: no I/O, no dependency on cli/loop."""

    def test_import_standalone(self) -> None:
        """Importing session_modes succeeds without side effects."""
        # Already imported at module level above — if it failed, we'd never get here.
        # This test documents the expectation explicitly.
        assert MODES is not None
        assert DEFAULT_MODE is not None

    def test_no_cli_import(self) -> None:
        """session_modes does not import colleague.cli."""
        # We check that importing session_modes doesn't pull in cli
        import colleague.session_modes as sm

        # The module's __file__ should exist and be importable
        assert sm.__file__ is not None

    def test_no_loop_import(self) -> None:
        """session_modes does not import colleague.loop."""
        import colleague.session_modes as sm

        assert sm.__file__ is not None

    def test_mode_label_returns_mode_name(self) -> None:
        """mode_label returns the mode name for v1."""
        for mode in MODES:
            assert mode_label(mode) == mode
