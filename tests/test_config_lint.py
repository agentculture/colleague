"""Lint-gate config resolution (#200, task t2).

The lint gate is default-ON with an opt-out. These tests pin the resolution
precedence for ``EngineConfig.lint`` and ``EngineConfig.lint_fix_retries``:

    --no-lint flag (applied post-resolve by the CLI) > COLLEAGUE_LINT env >
    .colleague/config.json {"lint": ...} > default-on.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from colleague.config import EngineConfig

# Env vars that influence lint resolution — cleared per test for isolation.
_LINT_ENV = (
    "COLLEAGUE_LINT",
    "CONVERTIBLE_LINT",
    "COLLEAGUE_LINT_FIX_RETRIES",
    "CONVERTIBLE_LINT_FIX_RETRIES",
)


@pytest.fixture(autouse=True)
def _clear_lint_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _LINT_ENV:
        monkeypatch.delenv(key, raising=False)


def _write_config(repo: Path, payload: dict) -> None:
    cfg_dir = repo / ".colleague"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.json").write_text(json.dumps(payload), encoding="utf-8")


def test_lint_default_on() -> None:
    """With nothing configured, lint is enabled by default (operator intent)."""
    cfg = EngineConfig.resolve()
    assert cfg.lint is True
    assert cfg.lint_fix_retries == 1


def test_env_disables_lint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_LINT", "0")
    assert EngineConfig.resolve().lint is False


@pytest.mark.parametrize("value", ["0", "false", "False", "no", "off", "OFF"])
def test_env_falsey_values_disable(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("COLLEAGUE_LINT", value)
    assert EngineConfig.resolve().lint is False


def test_env_empty_is_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty COLLEAGUE_LINT is treated as unset → falls through to default-on."""
    monkeypatch.setenv("COLLEAGUE_LINT", "")
    assert EngineConfig.resolve().lint is True


@pytest.mark.parametrize("value", ["1", "true", "yes", "on"])
def test_env_truthy_values_enable(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("COLLEAGUE_LINT", value)
    assert EngineConfig.resolve().lint is True


def test_config_file_disables_lint(tmp_path: Path) -> None:
    _write_config(tmp_path, {"lint": False})
    assert EngineConfig.resolve(repo_path=tmp_path).lint is False


def test_env_overrides_config_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Env beats the config file (precedence env > config)."""
    _write_config(tmp_path, {"lint": False})
    monkeypatch.setenv("COLLEAGUE_LINT", "1")
    assert EngineConfig.resolve(repo_path=tmp_path).lint is True


def test_lint_fix_retries_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_LINT_FIX_RETRIES", "3")
    assert EngineConfig.resolve().lint_fix_retries == 3


def test_lint_fix_retries_config_file(tmp_path: Path) -> None:
    _write_config(tmp_path, {"lint_fix_retries": 0})
    assert EngineConfig.resolve(repo_path=tmp_path).lint_fix_retries == 0


def test_lint_keys_in_to_dict() -> None:
    d = EngineConfig.resolve().to_dict()
    assert d["lint"] is True
    assert d["lint_fix_retries"] == 1
