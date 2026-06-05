"""Tests for colleague/autosplit.py — pure autosplit helpers.

Covers:
- estimate_instruction_tokens: empty → 0; non-empty → >0; custom counter honored.
- child_count: delegates to config.autosplit_children with clamping.
- build_split_recommendation: contains required literals (subagents, budget, children).
- build_upfront_hint: contains required literals, framed as advisory.
"""

from __future__ import annotations

from colleague.autosplit import (
    build_split_recommendation,
    build_upfront_hint,
    child_count,
    estimate_instruction_tokens,
)
from colleague.config import MAX_SUBAGENT_FANOUT

# ---------------------------------------------------------------------------
# estimate_instruction_tokens
# ---------------------------------------------------------------------------


def test_estimate_instruction_tokens_empty_string() -> None:
    """Empty instruction returns 0."""
    assert estimate_instruction_tokens("") == 0


def test_estimate_instruction_tokens_none() -> None:
    """None instruction returns 0."""
    assert estimate_instruction_tokens(None) == 0  # type: ignore[arg-type]


def test_estimate_instruction_tokens_nonempty_returns_positive() -> None:
    """A non-empty instruction returns a positive token count."""
    result = estimate_instruction_tokens("Fix all the lint errors in src/")
    assert result > 0


def test_estimate_instruction_tokens_uses_custom_counter() -> None:
    """A custom count_tokens callable is used when provided."""
    sentinel = 9999

    def _fixed_counter(messages: list) -> int:
        return sentinel

    result = estimate_instruction_tokens("some instruction", count_tokens=_fixed_counter)
    assert result == sentinel


def test_estimate_instruction_tokens_custom_counter_receives_message_list() -> None:
    """The custom counter is called with a list[dict] wrapping the instruction."""
    received: list = []

    def _capturing_counter(messages: list) -> int:
        received.extend(messages)
        return 42

    estimate_instruction_tokens("hello world", count_tokens=_capturing_counter)

    assert len(received) == 1, "Expected exactly one message passed to the counter"
    msg = received[0]
    assert isinstance(msg, dict), "Message must be a dict"
    assert "hello world" in msg.get(
        "content", ""
    ), "Instruction text must appear in the message content"


# ---------------------------------------------------------------------------
# child_count
# ---------------------------------------------------------------------------


def test_child_count_clamped_to_fanout_minus_one() -> None:
    """1_000_000 / 192_000 = ceil(5.2) = 6, clamped to MAX_SUBAGENT_FANOUT-1 = 3."""
    result = child_count(1_000_000, 192_000)
    assert result == MAX_SUBAGENT_FANOUT - 1


def test_child_count_two_children() -> None:
    """500_000 / 250_000 = 2, within [1, 3] => 2."""
    result = child_count(500_000, 250_000)
    assert result == 2


def test_child_count_minimum_one() -> None:
    """Even a tiny target always gives at least 1 child."""
    result = child_count(1, 192_000)
    assert result >= 1


def test_child_count_non_positive_budget_returns_max() -> None:
    """Non-positive per_child_budget_tokens returns MAX_SUBAGENT_FANOUT - 1."""
    result = child_count(500_000, 0)
    assert result == MAX_SUBAGENT_FANOUT - 1


# ---------------------------------------------------------------------------
# build_split_recommendation
# ---------------------------------------------------------------------------


def test_build_split_recommendation_is_string() -> None:
    """Returns a non-empty string."""
    msg = build_split_recommendation(per_child_budget_tokens=250_000, max_children=3)
    assert isinstance(msg, str)
    assert len(msg) > 0


def test_build_split_recommendation_mentions_subagents_tool() -> None:
    """Must reference the literal tool name 'subagents'."""
    msg = build_split_recommendation(per_child_budget_tokens=250_000, max_children=3)
    assert "subagents" in msg


def test_build_split_recommendation_mentions_per_child_budget() -> None:
    """Must include the per-child budget number in the output."""
    msg = build_split_recommendation(per_child_budget_tokens=250_000, max_children=3)
    # Accept either plain integer or comma-formatted
    assert "250000" in msg or "250,000" in msg


def test_build_split_recommendation_mentions_max_children() -> None:
    """Must include the max_children number in the output."""
    msg = build_split_recommendation(per_child_budget_tokens=250_000, max_children=3)
    assert "3" in msg


def test_build_split_recommendation_mentions_context_window_problem() -> None:
    """Must communicate that the assignment is too large for one context window."""
    msg = build_split_recommendation(per_child_budget_tokens=250_000, max_children=3).lower()
    # Flexible — accept several phrasings
    assert any(
        phrase in msg
        for phrase in ("too large", "context window", "does not fit", "exceeds", "overflow")
    ), f"Message does not mention the too-large problem: {msg!r}"


def test_build_split_recommendation_mentions_coherent_sub_assignments() -> None:
    """Must mention that each child must be independently scoped."""
    msg = build_split_recommendation(per_child_budget_tokens=250_000, max_children=3).lower()
    assert any(
        phrase in msg for phrase in ("coherent", "scoped", "independent", "self-contained", "fits")
    ), f"Message does not mention coherent sub-assignments: {msg!r}"


def test_build_split_recommendation_is_deterministic() -> None:
    """Two calls with same args produce identical output."""
    a = build_split_recommendation(per_child_budget_tokens=192_000, max_children=3)
    b = build_split_recommendation(per_child_budget_tokens=192_000, max_children=3)
    assert a == b


# ---------------------------------------------------------------------------
# build_upfront_hint
# ---------------------------------------------------------------------------


def test_build_upfront_hint_is_string() -> None:
    """Returns a non-empty string."""
    msg = build_upfront_hint(
        estimate_tokens=1_200_000, per_child_budget_tokens=192_000, max_children=3
    )
    assert isinstance(msg, str)
    assert len(msg) > 0


def test_build_upfront_hint_mentions_subagents_tool() -> None:
    """Must reference the literal tool name 'subagents'."""
    msg = build_upfront_hint(
        estimate_tokens=1_200_000, per_child_budget_tokens=192_000, max_children=3
    )
    assert "subagents" in msg


def test_build_upfront_hint_mentions_estimate() -> None:
    """Must include the estimated token count."""
    msg = build_upfront_hint(
        estimate_tokens=1_200_000, per_child_budget_tokens=192_000, max_children=3
    )
    assert "1200000" in msg or "1,200,000" in msg


def test_build_upfront_hint_mentions_per_child_budget() -> None:
    """Must include the per-child budget number."""
    msg = build_upfront_hint(
        estimate_tokens=1_200_000, per_child_budget_tokens=192_000, max_children=3
    )
    assert "192000" in msg or "192,000" in msg


def test_build_upfront_hint_mentions_max_children() -> None:
    """Must include the max_children number."""
    msg = build_upfront_hint(
        estimate_tokens=1_200_000, per_child_budget_tokens=192_000, max_children=3
    )
    assert "3" in msg


def test_build_upfront_hint_is_advisory() -> None:
    """Must be framed as an optional/early suggestion, not a hard post-overflow message."""
    msg = build_upfront_hint(
        estimate_tokens=1_200_000, per_child_budget_tokens=192_000, max_children=3
    ).lower()
    assert any(
        word in msg for word in ("consider", "optional", "early", "suggest", "may", "might")
    ), f"Message does not appear advisory: {msg!r}"


def test_build_upfront_hint_is_deterministic() -> None:
    """Two calls with same args produce identical output."""
    a = build_upfront_hint(estimate_tokens=800_000, per_child_budget_tokens=192_000, max_children=2)
    b = build_upfront_hint(estimate_tokens=800_000, per_child_budget_tokens=192_000, max_children=2)
    assert a == b
