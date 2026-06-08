"""Tests for provider repo_path threading (TDD, written before implementation).

Scenarios:
* provider.checks(repo_path=tmp) with a .colleague/config.json containing
  base_url and model → provider_config message contains those values.
* provider.checks() with no repo_path → default rig (no custom values).
* diagnose(repo_path=tmp) → provider_config reflects the config file.
* diagnose() with no repo_path → default rig.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from colleague.oilcheck import diagnose
from colleague.oilcheck.provider import checks

_PROVIDER_ENV_KEYS = (
    "COLLEAGUE_BASE_URL",
    "COLLEAGUE_API_KEY",
    "COLLEAGUE_MODEL",
    "CONVERTIBLE_BASE_URL",
    "CONVERTIBLE_API_KEY",
    "CONVERTIBLE_MODEL",
    "OPENAI_BASE_URL",
    "OPENAI_API_KEY",
)


def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _PROVIDER_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def _find(results: list[dict], check_id: str) -> dict | None:
    for c in results:
        if c["id"] == check_id:
            return c
    return None


class TestProviderRepoPath:
    def test_checks_with_repo_path_reflects_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clean_env(monkeypatch)
        cfg_dir = tmp_path / ".colleague"
        cfg_dir.mkdir()
        (cfg_dir / "config.json").write_text(
            json.dumps({"base_url": "https://example.test/v1", "model": "test-model-xyz"})
        )
        result = checks(repo_path=str(tmp_path))
        c = _find(result, "provider_config")
        assert c is not None
        assert "https://example.test/v1" in c["message"]
        assert "test-model-xyz" in c["message"]

    def test_checks_without_repo_path_is_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clean_env(monkeypatch)
        # Create a config file but don't pass repo_path — it should be ignored.
        cfg_dir = tmp_path / ".colleague"
        cfg_dir.mkdir()
        (cfg_dir / "config.json").write_text(
            json.dumps({"base_url": "https://example.test/v1", "model": "test-model-xyz"})
        )
        result = checks()
        c = _find(result, "provider_config")
        assert c is not None
        assert "https://example.test/v1" not in c["message"]
        assert "test-model-xyz" not in c["message"]


class TestDiagnoseRepoPath:
    def test_diagnose_with_repo_path_reflects_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clean_env(monkeypatch)
        cfg_dir = tmp_path / ".colleague"
        cfg_dir.mkdir()
        (cfg_dir / "config.json").write_text(
            json.dumps({"base_url": "https://example.test/v1", "model": "test-model-xyz"})
        )
        report = diagnose(repo_path=str(tmp_path))
        c = _find(report["checks"], "provider_config")
        assert c is not None
        assert "https://example.test/v1" in c["message"]
        assert "test-model-xyz" in c["message"]

    def test_diagnose_without_repo_path_is_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clean_env(monkeypatch)
        cfg_dir = tmp_path / ".colleague"
        cfg_dir.mkdir()
        (cfg_dir / "config.json").write_text(
            json.dumps({"base_url": "https://example.test/v1", "model": "test-model-xyz"})
        )
        report = diagnose()
        c = _find(report["checks"], "provider_config")
        assert c is not None
        assert "https://example.test/v1" not in c["message"]
        assert "test-model-xyz" not in c["message"]
