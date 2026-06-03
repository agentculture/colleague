"""Context budget token limit: explicit > CONVERTIBLE_CONTEXT_BUDGET > default."""

from __future__ import annotations

import pytest

from colleague.config import EngineConfig


def test_context_budget_default() -> None:
    """Default context_budget_tokens is sized for the 256k reference rig."""
    cfg = EngineConfig.resolve()
    assert cfg.context_budget_tokens == 192000


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
    assert snapshot["context_budget_tokens"] == 192000


# ---------------------------------------------------------------------------
# Tool-output cap: explicit > COLLEAGUE_MAX_OUTPUT_CHARS > default. Mirrors the
# context-budget knob — sized for the 256k window so a large file read isn't
# truncated at the old hardcoded 20000 chars.
# ---------------------------------------------------------------------------


def test_max_output_chars_default() -> None:
    """Default max_output_chars is raised from the old hardcoded 20000."""
    cfg = EngineConfig.resolve()
    assert cfg.max_output_chars == 100000


def test_max_output_chars_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """COLLEAGUE_MAX_OUTPUT_CHARS env var overrides the default."""
    monkeypatch.setenv("COLLEAGUE_MAX_OUTPUT_CHARS", "54321")
    cfg = EngineConfig.resolve()
    assert cfg.max_output_chars == 54321


def test_max_output_chars_explicit_wins_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit max_output_chars arg beats the env var."""
    monkeypatch.setenv("COLLEAGUE_MAX_OUTPUT_CHARS", "54321")
    cfg = EngineConfig.resolve(max_output_chars=777)
    assert cfg.max_output_chars == 777


def test_max_output_chars_in_to_dict() -> None:
    """to_dict() includes max_output_chars."""
    cfg = EngineConfig.resolve(max_output_chars=8000)
    snapshot = cfg.to_dict()
    assert snapshot["max_output_chars"] == 8000
