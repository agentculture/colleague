"""Affected-tests gate config resolution (#213).

The affected-tests gate is default-ON with an opt-out. These tests pin the
resolution precedence for the affected-tests EngineConfig fields:

    explicit-arg > COLLEAGUE_AFFECTED_TESTS_* env > .colleague/config.json >
    default-on.

Mirrors :mod:`tests.test_config_lint` (lint-gate config tests).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from colleague.config import EngineConfig

# Env vars that influence affected-tests resolution — cleared per test.
_AT_ENV = (
    "COLLEAGUE_AFFECTED_TESTS",
    "COLLEAGUE_AFFECTED_TESTS_FIX_RETRIES",
    "COLLEAGUE_AFFECTED_TESTS_DEPTH",
    "COLLEAGUE_AFFECTED_TESTS_MAX_FILES",
)


@pytest.fixture(autouse=True)
def _clear_at_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _AT_ENV:
        monkeypatch.delenv(key, raising=False)


def _write_config(repo: Path, payload: dict) -> None:
    cfg_dir = repo / ".colleague"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.json").write_text(json.dumps(payload), encoding="utf-8")


def test_affected_tests_defaults() -> None:
    """With nothing configured, affected-tests is enabled with default knobs."""
    cfg = EngineConfig.resolve()
    assert cfg.affected_tests is True
    assert cfg.affected_tests_fix_retries == 1
    assert cfg.affected_tests_depth == 3
    assert cfg.affected_tests_max_files == 20
    assert cfg.affected_tests_override is None


def test_env_disables_affected_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    """COLLEAGUE_AFFECTED_TESTS=0 disables the gate."""
    monkeypatch.setenv("COLLEAGUE_AFFECTED_TESTS", "0")
    assert EngineConfig.resolve().affected_tests is False


@pytest.mark.parametrize("value", ["0", "false", "False", "no", "off", "OFF"])
def test_env_falsey_values_disable(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("COLLEAGUE_AFFECTED_TESTS", value)
    assert EngineConfig.resolve().affected_tests is False


def test_env_empty_is_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty COLLEAGUE_AFFECTED_TESTS is treated as unset → falls through to default-on."""
    monkeypatch.setenv("COLLEAGUE_AFFECTED_TESTS", "")
    assert EngineConfig.resolve().affected_tests is True


@pytest.mark.parametrize("value", ["1", "true", "yes", "on"])
def test_env_truthy_values_enable(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("COLLEAGUE_AFFECTED_TESTS", value)
    assert EngineConfig.resolve().affected_tests is True


def test_env_depth_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """COLLEAGUE_AFFECTED_TESTS_DEPTH=5 wins over the default (3)."""
    monkeypatch.setenv("COLLEAGUE_AFFECTED_TESTS_DEPTH", "5")
    assert EngineConfig.resolve().affected_tests_depth == 5


def test_env_max_files_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """COLLEAGUE_AFFECTED_TESTS_MAX_FILES overrides the default (20)."""
    monkeypatch.setenv("COLLEAGUE_AFFECTED_TESTS_MAX_FILES", "50")
    assert EngineConfig.resolve().affected_tests_max_files == 50


def test_env_fix_retries_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """COLLEAGUE_AFFECTED_TESTS_FIX_RETRIES overrides the default (1)."""
    monkeypatch.setenv("COLLEAGUE_AFFECTED_TESTS_FIX_RETRIES", "3")
    assert EngineConfig.resolve().affected_tests_fix_retries == 3


def test_config_file_disables_affected_tests(tmp_path: Path) -> None:
    _write_config(tmp_path, {"affected_tests": False})
    assert EngineConfig.resolve(repo_path=tmp_path).affected_tests is False


def test_env_overrides_config_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Env beats the config file (precedence env > config)."""
    _write_config(tmp_path, {"affected_tests": False})
    monkeypatch.setenv("COLLEAGUE_AFFECTED_TESTS", "1")
    assert EngineConfig.resolve(repo_path=tmp_path).affected_tests is True


def test_config_file_depth(tmp_path: Path) -> None:
    _write_config(tmp_path, {"affected_tests_depth": 5})
    assert EngineConfig.resolve(repo_path=tmp_path).affected_tests_depth == 5


def test_config_file_max_files(tmp_path: Path) -> None:
    _write_config(tmp_path, {"affected_tests_max_files": 10})
    assert EngineConfig.resolve(repo_path=tmp_path).affected_tests_max_files == 10


def test_config_file_fix_retries(tmp_path: Path) -> None:
    _write_config(tmp_path, {"affected_tests_fix_retries": 0})
    assert EngineConfig.resolve(repo_path=tmp_path).affected_tests_fix_retries == 0


def test_affected_tests_keys_in_to_dict() -> None:
    d = EngineConfig.resolve().to_dict()
    assert d["affected_tests"] is True
    assert d["affected_tests_fix_retries"] == 1
    assert d["affected_tests_depth"] == 3
    assert d["affected_tests_max_files"] == 20
