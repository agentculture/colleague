"""Persistent config-file override for engine endpoint (config.json).

Tests that .colleague/config.json is picked up by EngineConfig.resolve when
repo_path is provided, and that the full precedence chain works:

    explicit argument > COLLEAGUE_/OPENAI_ env > config.json > built-in default.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from colleague.config import EngineConfig, load_config_file


@pytest.fixture(autouse=True)
def _isolate_user_home(tmp_path_factory, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path_factory.mktemp("home"))


def _write_config(tmp_path: Path, payload: dict) -> None:
    """Write a .colleague/config.json inside *tmp_path*."""
    cfg_dir = tmp_path / ".colleague"
    cfg_dir.mkdir()
    (cfg_dir / "config.json").write_text(json.dumps(payload), encoding="utf-8")


# ── load_config_file ────────────────────────────────────────────────────────


def test_load_config_file_missing(tmp_path: Path) -> None:
    """No config file → empty dict."""
    assert load_config_file(tmp_path) == {}


def test_load_config_file_valid(tmp_path: Path) -> None:
    """Valid config.json → dict with recognised keys."""
    _write_config(tmp_path, {"base_url": "http://example/v1", "model": "my-model"})
    result = load_config_file(tmp_path)
    assert result == {"base_url": "http://example/v1", "model": "my-model"}


def test_load_config_file_malformed_json(tmp_path: Path) -> None:
    """Malformed JSON → empty dict, never raises."""
    cfg_dir = tmp_path / ".colleague"
    cfg_dir.mkdir()
    (cfg_dir / "config.json").write_text("not json at all", encoding="utf-8")
    assert load_config_file(tmp_path) == {}


def test_load_config_file_unrecognised_keys(tmp_path: Path) -> None:
    """Only recognised keys (base_url, api_key, model) are returned."""
    _write_config(
        tmp_path,
        {
            "base_url": "http://example/v1",
            "unknown_key": "value",
            "model": "my-model",
        },
    )
    result = load_config_file(tmp_path)
    assert result == {"base_url": "http://example/v1", "model": "my-model"}


# ── EngineConfig.resolve with repo_path ─────────────────────────────────────


def test_config_file_base_url_picked_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A .colleague/config.json base_url is picked up by resolve(repo_path=...)."""
    monkeypatch.delenv("COLLEAGUE_BASE_URL", raising=False)
    monkeypatch.delenv("CONVERTIBLE_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    _write_config(tmp_path, {"base_url": "http://config-file/v1"})
    cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.base_url == "http://config-file/v1"


def test_env_overrides_config_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """COLLEAGUE_BASE_URL env var overrides the config file."""
    _write_config(tmp_path, {"base_url": "http://config-file/v1"})
    monkeypatch.setenv("COLLEAGUE_BASE_URL", "http://env-var/v1")
    cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.base_url == "http://env-var/v1"


def test_explicit_overrides_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An explicit base_url argument overrides the env var."""
    _write_config(tmp_path, {"base_url": "http://config-file/v1"})
    monkeypatch.setenv("COLLEAGUE_BASE_URL", "http://env-var/v1")
    cfg = EngineConfig.resolve(
        base_url="http://explicit/v1",
        repo_path=tmp_path,
    )
    assert cfg.base_url == "http://explicit/v1"


def test_absent_config_file_uses_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When no config file exists, defaults are unchanged."""
    monkeypatch.delenv("COLLEAGUE_BASE_URL", raising=False)
    monkeypatch.delenv("CONVERTIBLE_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("COLLEAGUE_MODEL", raising=False)
    monkeypatch.delenv("CONVERTIBLE_MODEL", raising=False)
    monkeypatch.delenv("COLLEAGUE_API_KEY", raising=False)
    monkeypatch.delenv("CONVERTIBLE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.base_url == "http://localhost:8001/v1"
    assert cfg.model == "unsloth/Qwen3.6-27B-NVFP4"
    assert cfg.api_key == "EMPTY"


def test_malformed_json_ignored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Malformed JSON is ignored without raising; defaults are used."""
    monkeypatch.delenv("COLLEAGUE_BASE_URL", raising=False)
    monkeypatch.delenv("CONVERTIBLE_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    cfg_dir = tmp_path / ".colleague"
    cfg_dir.mkdir()
    (cfg_dir / "config.json").write_text("{broken", encoding="utf-8")
    cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.base_url == "http://localhost:8001/v1"


def test_config_file_model_picked_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A .colleague/config.json model is picked up by resolve(repo_path=...)."""
    monkeypatch.delenv("COLLEAGUE_MODEL", raising=False)
    monkeypatch.delenv("CONVERTIBLE_MODEL", raising=False)
    _write_config(tmp_path, {"model": "custom-model"})
    cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.model == "custom-model"


def test_config_file_api_key_picked_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A .colleague/config.json api_key is picked up by resolve(repo_path=...)."""
    monkeypatch.delenv("COLLEAGUE_API_KEY", raising=False)
    monkeypatch.delenv("CONVERTIBLE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    _write_config(tmp_path, {"api_key": "sk-from-file"})
    cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.api_key == "sk-from-file"


def test_none_repo_path_is_noop() -> None:
    """When repo_path is None, behaviour is byte-identical to no config-file support."""
    cfg = EngineConfig.resolve()
    assert cfg.base_url == "http://localhost:8001/v1"
