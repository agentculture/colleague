"""Tests for colleague.plan.pushback — pushback on too-small tasks."""

from colleague.plan.pushback import build_pushback_message, is_too_small

# ── is_too_small ────────────────────────────────────────────────────────


def test_is_too_small_returns_true_for_small_instruction():
    """A short instruction below the threshold should be flagged as too small."""
    small = "Fix typo"
    assert is_too_small(small, threshold_tokens=100) is True


def test_is_too_small_returns_false_for_large_instruction():
    """A large/complex instruction above the threshold should not be flagged."""
    large = (
        "Implement a full REST API with authentication, pagination, and error handling. "
        "Include database migrations, unit tests, integration tests, and documentation. "
        "Support multiple database backends and provide a CLI for administration."
    )
    assert is_too_small(large, threshold_tokens=50) is False


# ── build_pushback_message ──────────────────────────────────────────────


def test_build_pushback_message_is_non_empty():
    """The pushback message must be a non-empty string."""
    result = build_pushback_message()
    assert isinstance(result, str)
    assert len(result) > 0


def test_build_pushback_message_recommends_plain_work():
    """The message should recommend a plain `colleague work`, not the full pipeline."""
    result = build_pushback_message()
    lower = result.lower()
    assert "colleague work" in lower
    assert "work" in lower
