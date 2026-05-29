"""Engine config resolution: explicit > CONVERTIBLE_* > OPENAI_* > default."""

from __future__ import annotations

import pytest

from convertible.config import EngineConfig, resolve_engine


def test_defaults_point_at_vllm_reference() -> None:
    cfg = EngineConfig.resolve()
    assert cfg.base_url == "http://localhost:8001/v1"
    assert "Qwen3" in cfg.model
    assert cfg.api_key == "EMPTY"
    assert cfg.max_steps == 25


def test_explicit_args_win_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONVERTIBLE_BASE_URL", "http://env:9/v1")
    cfg = EngineConfig.resolve(base_url="http://explicit:1/v1")
    assert cfg.base_url == "http://explicit:1/v1"


def test_convertible_env_wins_over_openai_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_BASE_URL", "http://openai/v1")
    monkeypatch.setenv("CONVERTIBLE_BASE_URL", "http://convertible/v1")
    assert EngineConfig.resolve().base_url == "http://convertible/v1"


def test_openai_env_used_as_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CONVERTIBLE_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fallback")
    assert EngineConfig.resolve().api_key == "sk-fallback"


def test_numeric_env_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONVERTIBLE_MAX_STEPS", "7")
    assert EngineConfig.resolve().max_steps == 7


def test_to_dict_redacts_api_key() -> None:
    cfg = EngineConfig.resolve(api_key="sk-secret")
    snapshot = cfg.to_dict()
    assert "api_key" not in snapshot
    assert "sk-secret" not in str(snapshot)


# ---------------------------------------------------------------------------
# Engine selection: explicit > CONVERTIBLE_ENGINE > vllm-openai (never mock).
# ---------------------------------------------------------------------------


def test_resolve_engine_default_is_real_not_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    """A bare invocation must NOT silently fall back to the no-op mock (#53)."""
    monkeypatch.delenv("CONVERTIBLE_ENGINE", raising=False)
    engine = resolve_engine(None)
    assert engine == "vllm-openai"
    assert engine != "mock"


def test_resolve_engine_explicit_wins_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONVERTIBLE_ENGINE", "vllm-openai")
    assert resolve_engine("mock") == "mock"


def test_resolve_engine_env_wins_over_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONVERTIBLE_ENGINE", "mock")
    assert resolve_engine(None) == "mock"


def test_resolve_engine_blank_env_falls_through_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty env var must not win — it falls through to the built-in default."""
    monkeypatch.setenv("CONVERTIBLE_ENGINE", "")
    assert resolve_engine(None) == "vllm-openai"


@pytest.mark.parametrize("blank", ["", "   ", "\t", "\n"])
def test_resolve_engine_blank_explicit_falls_through_to_env(
    monkeypatch: pytest.MonkeyPatch, blank: str
) -> None:
    """An explicit but blank --engine (e.g. --engine '' or --engine "$UNSET") must
    fall through to CONVERTIBLE_ENGINE, not resolve to an invalid engine name."""
    monkeypatch.setenv("CONVERTIBLE_ENGINE", "mock")
    assert resolve_engine(blank) == "mock"


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_resolve_engine_blank_explicit_and_env_falls_through_to_default(
    monkeypatch: pytest.MonkeyPatch, blank: str
) -> None:
    """Blank explicit AND blank/unset env → the built-in default, never ''."""
    monkeypatch.setenv("CONVERTIBLE_ENGINE", blank)
    assert resolve_engine(blank) == "vllm-openai"


def test_resolve_engine_strips_surrounding_whitespace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CONVERTIBLE_ENGINE", raising=False)
    assert resolve_engine("  mock  ") == "mock"
