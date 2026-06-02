"""Context budget token limit: explicit > CONVERTIBLE_CONTEXT_BUDGET > default."""

from __future__ import annotations

import pytest

from colleague.config import EngineConfig


def test_context_budget_default() -> None:
    """Default context_budget_tokens should be 24000."""
    cfg = EngineConfig.resolve()
    assert cfg.context_budget_tokens == 24000


def test_context_budget_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """CONVERTIBLE_CONTEXT_BUDGET env var overrides default."""
    monkeypatch.setenv("CONVERTIBLE_CONTEXT_BUDGET", "12345")
    cfg = EngineConfig.resolve()
    assert cfg.context_budget_tokens == 12345


def test_context_budget_explicit_wins_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit context_budget_tokens arg beats env var."""
    monkeypatch.setenv("CONVERTIBLE_CONTEXT_BUDGET", "12345")
    cfg = EngineConfig.resolve(context_budget_tokens=999)
    assert cfg.context_budget_tokens == 999


def test_context_budget_in_to_dict() -> None:
    """to_dict() includes context_budget_tokens."""
    cfg = EngineConfig.resolve(context_budget_tokens=8000)
    snapshot = cfg.to_dict()
    assert "context_budget_tokens" in snapshot
    assert snapshot["context_budget_tokens"] == 8000


def test_context_budget_to_dict_default() -> None:
    """to_dict() with default context_budget_tokens."""
    cfg = EngineConfig.resolve()
    snapshot = cfg.to_dict()
    assert snapshot["context_budget_tokens"] == 24000
