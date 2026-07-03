"""Context budget token limit: explicit > CONVERTIBLE_CONTEXT_BUDGET > default."""

from __future__ import annotations

import pytest

from colleague.config import EngineConfig, ResolveOverrides


def test_context_budget_default() -> None:
    """Default context_budget_tokens fits the reference rig's SERVED window.

    The lobes rig serves the default 27B at 64K (65536 tokens, probed live
    2026-07-02), so the default keeps the ~0.73 fill fraction: 48000. The old
    192000 assumed the retired 256K serving and drove long runs into
    overflow/latency churn.
    """
    cfg = EngineConfig.resolve()
    assert cfg.context_budget_tokens == 48000


def test_context_budget_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """CONVERTIBLE_CONTEXT_BUDGET env var overrides default."""
    monkeypatch.setenv("CONVERTIBLE_CONTEXT_BUDGET", "12345")
    cfg = EngineConfig.resolve()
    assert cfg.context_budget_tokens == 12345


def test_context_budget_explicit_wins_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit context_budget_tokens arg beats env var."""
    monkeypatch.setenv("CONVERTIBLE_CONTEXT_BUDGET", "12345")
    cfg = EngineConfig.resolve(overrides=ResolveOverrides(context_budget_tokens=999))
    assert cfg.context_budget_tokens == 999


def test_context_budget_in_to_dict() -> None:
    """to_dict() includes context_budget_tokens."""
    cfg = EngineConfig.resolve(overrides=ResolveOverrides(context_budget_tokens=8000))
    snapshot = cfg.to_dict()
    assert "context_budget_tokens" in snapshot
    assert snapshot["context_budget_tokens"] == 8000


def test_context_budget_to_dict_default() -> None:
    """to_dict() with default context_budget_tokens."""
    cfg = EngineConfig.resolve()
    snapshot = cfg.to_dict()
    assert snapshot["context_budget_tokens"] == 48000


# ---------------------------------------------------------------------------
# Tool-output cap: explicit > COLLEAGUE_MAX_OUTPUT_CHARS > default. Mirrors the
# context-budget knob — scaled with the budget (~13% of window) so one large
# read can't evict half the working history; still above the old hardcoded
# 20000 chars.
# ---------------------------------------------------------------------------


def test_max_output_chars_default() -> None:
    """Default max_output_chars scales with the budget, above the old 20000."""
    cfg = EngineConfig.resolve()
    assert cfg.max_output_chars == 25000


def test_max_output_chars_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """COLLEAGUE_MAX_OUTPUT_CHARS env var overrides the default."""
    monkeypatch.setenv("COLLEAGUE_MAX_OUTPUT_CHARS", "54321")
    cfg = EngineConfig.resolve()
    assert cfg.max_output_chars == 54321


def test_max_output_chars_explicit_wins_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit max_output_chars arg beats the env var."""
    monkeypatch.setenv("COLLEAGUE_MAX_OUTPUT_CHARS", "54321")
    cfg = EngineConfig.resolve(overrides=ResolveOverrides(max_output_chars=777))
    assert cfg.max_output_chars == 777


def test_max_output_chars_in_to_dict() -> None:
    """to_dict() includes max_output_chars."""
    cfg = EngineConfig.resolve(overrides=ResolveOverrides(max_output_chars=8000))
    snapshot = cfg.to_dict()
    assert snapshot["max_output_chars"] == 8000
