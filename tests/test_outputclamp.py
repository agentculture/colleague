"""Tests for :mod:`colleague.outputclamp` (t3).

Proves the three acceptance criteria verbatim from the plan:

- ``clamp_output_tokens`` == ``min(ceiling, window - prompt - margin)``,
  margin ``max(10_000, 5% of window)``, floored at 4000 — ported unchanged
  from qwen-code's ``clampOutputTokensToWindow``/``outputClampMargin`` and
  checked against qwen-code's own ``tokenLimits.test.ts`` fixtures.
- ``resolve_window`` applies the precedence lobes context -> ``/tokenize``
  ``max_model_len`` -> budget, and reports which source won.
- ``seat_ceiling`` returns 64000 for acting seats, the design ceiling
  (default 131072, or ``COLLEAGUE_MAX_OUTPUT_TOKENS_DESIGN``) for
  deepthink/design seats, and ``COLLEAGUE_MAX_OUTPUT_TOKENS=0`` disables
  clamping entirely (``None``) for any seat.
"""

from __future__ import annotations

import pytest

from colleague import outputclamp
from colleague.effort import SEAT_TABLE
from colleague.outputclamp import (
    DEFAULT_DESIGN_OUTPUT_CEILING,
    DESIGN_SEATS,
    MIN_CLAMPED_OUTPUT_TOKENS,
    OUTPUT_TOKEN_CEILING,
    clamp_output_tokens,
    output_clamp_margin,
    resolve_window,
    room_is_short,
    seat_ceiling,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Every test starts with neither output-clamp env var set."""
    monkeypatch.delenv("COLLEAGUE_MAX_OUTPUT_TOKENS", raising=False)
    monkeypatch.delenv("COLLEAGUE_MAX_OUTPUT_TOKENS_DESIGN", raising=False)


# ---------------------------------------------------------------------------
# output_clamp_margin — ported qwen-code fixtures (tokenLimits.test.ts:549-552)
# ---------------------------------------------------------------------------


def test_output_clamp_margin_default_floor():
    """Below the 5%-crossover point, the 10_000 floor wins."""
    assert output_clamp_margin(200_000) == 10_000
    assert output_clamp_margin(40_000) == 10_000


def test_output_clamp_margin_scales_with_window():
    """Above the crossover, margin is 5% of the window, rounded."""
    assert output_clamp_margin(1_000_000) == 50_000


# ---------------------------------------------------------------------------
# clamp_output_tokens — ported qwen-code fixtures (tokenLimits.test.ts:515-566)
# ---------------------------------------------------------------------------


def test_clamp_returns_ceiling_when_room_is_ample():
    assert clamp_output_tokens(32_000, 200_000, 50_000) == 32_000


def test_clamp_returns_room_when_room_is_the_binding_constraint():
    # room = 200_000 - 170_000 - 10_000 = 20_000 < ceiling 32_000
    assert clamp_output_tokens(32_000, 200_000, 170_000) == 20_000


def test_clamp_floors_at_min_clamped_output_tokens_when_room_is_small():
    # room = 40_000 - 39_000 - 10_000 = -9_000 -> floored at 4_000
    assert clamp_output_tokens(32_000, 40_000, 39_000) == MIN_CLAMPED_OUTPUT_TOKENS


def test_clamp_floors_even_when_prompt_exceeds_window():
    # room = 40_000 - 60_000 - 10_000, deeply negative -> still floored at 4_000
    assert clamp_output_tokens(32_000, 40_000, 60_000) == MIN_CLAMPED_OUTPUT_TOKENS


def test_clamp_respects_an_explicit_ceiling_below_the_floor():
    """An explicit ceiling under MIN_CLAMPED_OUTPUT_TOKENS is honored, not
    inflated to the floor — the floor bounds the room, not the ceiling."""
    assert clamp_output_tokens(2_000, 200_000, 50_000) == 2_000
    assert clamp_output_tokens(2_000, 40_000, 39_000) == 2_000


def test_clamp_at_large_window_hits_the_ceiling_not_the_room():
    # room = 1_000_000 - 500_000 - 50_000 = 450_000, way above ceiling 64_000
    assert clamp_output_tokens(64_000, 1_000_000, 500_000) == 64_000


def test_clamp_small_ceiling_under_ample_room():
    assert clamp_output_tokens(8_000, 40_000, 10_000) == 8_000


def test_clamp_qwen_code_window_worked_example():
    """The plan's worked example (window 262144, prompt 200000, ceiling
    64000) computed against THIS module's ported formula.

    Deviation from the plan text: the acceptance criteria states this combo
    clamps to 48934, but the formula it also states (``min(ceiling, window -
    prompt - margin)``, margin ``max(10_000, round(0.05 * window))``) is
    internally verified against qwen-code's own tokenLimits.test.ts fixtures
    above (every one of which matches this module bit-for-bit) and computes
    to 49037 for this exact input, not 48934:

        margin = max(10_000, round(0.05 * 262144)) = max(10_000, 13107) = 13107
        room = 262144 - 200000 - 13107 = 49037
        min(64000, max(4000, 49037)) = 49037

    Trusting the formula (independently verified) over the one-off number
    (unreproducible from that same formula, and not found anywhere in the
    qwen-code source or test tree) per this task's deviation-reporting
    instruction.
    """
    margin = output_clamp_margin(262_144)
    assert margin == 13_107
    assert clamp_output_tokens(64_000, 262_144, 200_000) == 49_037


# ---------------------------------------------------------------------------
# resolve_window
# ---------------------------------------------------------------------------


def test_resolve_window_prefers_lobes_context():
    window, source = resolve_window(131_072, 65_536, 32_000)
    assert (window, source) == (131_072, "lobes_context")


def test_resolve_window_falls_back_to_tokenize_max_model_len():
    window, source = resolve_window(None, 65_536, 32_000)
    assert (window, source) == (65_536, "tokenize_max_model_len")


def test_resolve_window_falls_back_to_budget():
    window, source = resolve_window(None, None, 131_072)
    assert (window, source) == (131_072, "context_budget")


def test_resolve_window_ignores_non_positive_candidates():
    """A zero/negative lobes/tokenize value is treated as absent, not as a
    literal (degenerate) window."""
    window, source = resolve_window(0, -1, 32_000)
    assert (window, source) == (32_000, "context_budget")


def test_resolve_window_lobes_context_beats_tokenize_when_both_present():
    window, source = resolve_window(200_000, 65_536, 32_000)
    assert (window, source) == (200_000, "lobes_context")


# ---------------------------------------------------------------------------
# seat_ceiling
# ---------------------------------------------------------------------------


def test_seat_ceiling_acting_seat_default():
    for seat in SEAT_TABLE:
        if seat in DESIGN_SEATS:
            continue
        assert seat_ceiling(seat) == OUTPUT_TOKEN_CEILING == 64_000


def test_seat_ceiling_design_seats_default():
    for seat in ("deepthink", "design"):
        assert seat_ceiling(seat) == DEFAULT_DESIGN_OUTPUT_CEILING == 131_072


def test_seat_ceiling_design_env_override(monkeypatch):
    monkeypatch.setenv("COLLEAGUE_MAX_OUTPUT_TOKENS_DESIGN", "200000")
    assert seat_ceiling("deepthink") == 200_000
    assert seat_ceiling("design") == 200_000
    # Acting seats are untouched by the design-only knob.
    assert seat_ceiling("cortex") == OUTPUT_TOKEN_CEILING


def test_seat_ceiling_acting_env_override(monkeypatch):
    monkeypatch.setenv("COLLEAGUE_MAX_OUTPUT_TOKENS", "48000")
    assert seat_ceiling("cortex") == 48_000
    assert seat_ceiling("worker") == 48_000
    # Design seats keep their own dedicated ceiling, unaffected.
    assert seat_ceiling("deepthink") == DEFAULT_DESIGN_OUTPUT_CEILING


def test_seat_ceiling_zero_is_global_kill_switch(monkeypatch):
    """COLLEAGUE_MAX_OUTPUT_TOKENS=0 disables clamping for every seat,
    including the design seats."""
    monkeypatch.setenv("COLLEAGUE_MAX_OUTPUT_TOKENS", "0")
    for seat in SEAT_TABLE:
        assert seat_ceiling(seat) is None


def test_seat_ceiling_zero_kill_switch_beats_design_override(monkeypatch):
    monkeypatch.setenv("COLLEAGUE_MAX_OUTPUT_TOKENS", "0")
    monkeypatch.setenv("COLLEAGUE_MAX_OUTPUT_TOKENS_DESIGN", "999999")
    assert seat_ceiling("deepthink") is None


@pytest.mark.parametrize("bad", ["-5", "0", "abc"])
def test_seat_ceiling_design_override_ignored_when_not_positive_int(monkeypatch, bad):
    """A design override replaces the default ONLY when it parses as a positive
    int — negative, zero, or unparseable values are ignored and the default
    131072 stands (a negative max_tokens must never reach the API)."""
    monkeypatch.setenv("COLLEAGUE_MAX_OUTPUT_TOKENS_DESIGN", bad)
    for seat in ("deepthink", "design"):
        assert seat_ceiling(seat) == DEFAULT_DESIGN_OUTPUT_CEILING


def test_room_is_short_true_when_room_is_below_the_floor():
    # room = 40_000 - 39_000 - 10_000 = -9_000 < 4_000
    assert room_is_short(40_000, 39_000) is True
    # room = 40_000 - 60_000 - 10_000, deeply negative
    assert room_is_short(40_000, 60_000) is True


def test_room_is_short_false_when_room_meets_or_beats_the_floor():
    # room = 200_000 - 170_000 - 10_000 = 20_000 >= 4_000
    assert room_is_short(200_000, 170_000) is False
    # room = 200_000 - 186_000 - 10_000 = 4_000 == floor -> not short
    assert room_is_short(200_000, 186_000) is False


def test_clamp_still_returns_the_floor_when_room_is_short():
    """Upstream parity: clamp_output_tokens keeps returning the 4000 floor when
    the room is short; room_is_short is the caller's signal, not a change to
    the clamped value."""
    assert clamp_output_tokens(32_000, 40_000, 39_000) == MIN_CLAMPED_OUTPUT_TOKENS
    assert room_is_short(40_000, 39_000) is True


def test_seat_ceiling_unknown_seat_raises():
    with pytest.raises(ValueError, match="unknown seat"):
        seat_ceiling("not-a-real-seat")


def test_seat_ceiling_recognises_every_seat_table_key():
    """Every seat from colleague.effort.SEAT_TABLE resolves without error —
    the seat vocabulary this module recognises is exactly that table's
    keys, never a second drifting list."""
    for seat in SEAT_TABLE:
        assert seat_ceiling(seat) is not None


def test_module_docstring_carries_the_adapted_from_marker():
    assert "adapted-from: qwen-code packages/core/src/core/tokenLimits.ts:36-77" in (
        outputclamp.__doc__ or ""
    )
