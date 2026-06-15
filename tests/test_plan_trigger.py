"""Tests for colleague.plan.trigger — auto-trigger advisory for plan mode."""

from colleague.plan.trigger import build_plan_recommendation, should_offer_plan_mode

# ── should_offer_plan_mode ──────────────────────────────────────────────


def test_should_offer_plan_mode_returns_true_for_large_instruction():
    """A large/complex instruction that exceeds the threshold should trigger."""
    large = (
        "Implement a full REST API with authentication, pagination, and error handling. "
        "Include database migrations, unit tests, integration tests, and documentation. "
        "Support multiple database backends and provide a CLI for administration."
    )
    assert should_offer_plan_mode(large, already_offered=False, threshold_tokens=50) is True


def test_should_offer_plan_mode_returns_false_when_already_offered():
    """Once offered, should_offer_plan_mode must never offer again."""
    assert (
        should_offer_plan_mode("any instruction", already_offered=True, threshold_tokens=1) is False
    )


def test_should_offer_plan_mode_returns_false_for_small_instruction():
    """A short instruction below the threshold should not trigger."""
    small = "Fix typo"
    assert should_offer_plan_mode(small, already_offered=False, threshold_tokens=100) is False


# ── build_plan_recommendation ──────────────────────────────────────────


def test_build_plan_recommendation_is_non_empty():
    """The recommendation must be a non-empty string."""
    result = build_plan_recommendation()
    assert isinstance(result, str)
    assert len(result) > 0


def test_build_plan_recommendation_is_advisory_not_forced():
    """The message must be advisory — no imperative 'you must' language."""
    result = build_plan_recommendation()
    lower = result.lower()
    assert "you must" not in lower
    # Must mention plan mode / colleague plan
    assert "plan" in lower
    assert "colleague plan" in lower or "plan mode" in lower
