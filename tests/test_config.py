"""Engine config resolution: explicit > CONVERTIBLE_* > OPENAI_* > default."""

from __future__ import annotations

import pytest

from convertible.config import EngineConfig


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
