"""``colleague config`` CLI noun group — show and overview.

Acceptance criteria:
1. ``config show --json`` emits the resolved config with base_url and model.
2. ``config show`` (text) reports key: value lines, exit 0.
3. ``config overview`` (and bare ``config``) describes the noun, exit 0.
4. api_key is NEVER printed in any output.
5. ``explain config`` returns the catalog entry.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from colleague.cli import main

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


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _PROVIDER_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_show_json_reflects_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg_dir = tmp_path / ".colleague"
    cfg_dir.mkdir()
    (cfg_dir / "config.json").write_text(
        json.dumps(
            {
                "base_url": "https://example.test/v1",
                "model": "test-model-xyz",
                "api_key": "sk-secret-NEVER",
            }
        )
    )
    rc = main(["config", "show", "--repo", str(tmp_path), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["base_url"] == "https://example.test/v1"
    assert payload["model"] == "test-model-xyz"
    # api_key must NEVER appear in output
    assert "sk-secret-NEVER" not in json.dumps(payload)


def test_show_json_api_key_never_leaked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg_dir = tmp_path / ".colleague"
    cfg_dir.mkdir()
    (cfg_dir / "config.json").write_text(
        json.dumps(
            {
                "base_url": "https://example.test/v1",
                "model": "test-model-xyz",
                "api_key": "sk-secret-NEVER",
            }
        )
    )
    rc = main(["config", "show", "--repo", str(tmp_path), "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "sk-secret-NEVER" not in out


def test_show_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg_dir = tmp_path / ".colleague"
    cfg_dir.mkdir()
    (cfg_dir / "config.json").write_text(
        json.dumps(
            {
                "base_url": "https://example.test/v1",
                "model": "test-model-xyz",
                "api_key": "sk-secret-NEVER",
            }
        )
    )
    rc = main(["config", "show", "--repo", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "base_url:" in out
    assert "https://example.test/v1" in out
    assert "sk-secret-NEVER" not in out


def test_overview_text(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["config", "overview"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "colleague config" in out


def test_overview_json_shape(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["config", "overview", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["subject"] == "colleague config"
    assert isinstance(payload["sections"], list)
    assert payload["sections"]


def test_bare_noun_prints_overview(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["config"])
    assert rc == 0
    assert capsys.readouterr().out.strip()


def test_explain_config(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["explain", "config"])
    assert rc == 0
    assert "colleague config" in capsys.readouterr().out


def test_show_provenance_multi_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Repo sets 'model', user sets 'base_url'+'model' — both files listed,
    repo wins 'model', user wins 'base_url'."""
    # Repo-level config: only 'model'
    repo_cfg = tmp_path / ".colleague"
    repo_cfg.mkdir()
    (repo_cfg / "config.json").write_text(json.dumps({"model": "repo-model"}))

    # User-level config: 'base_url' and 'model' (model is shadowed by repo)
    user_home = tmp_path / "user-home"
    user_home.mkdir()
    user_cfg = user_home / ".colleague"
    user_cfg.mkdir()
    (user_cfg / "config.json").write_text(
        json.dumps({"base_url": "http://user.test/v1", "model": "shadowed"})
    )
    monkeypatch.setenv("COLLEAGUE_HOME", str(user_home))

    rc = main(["config", "show", "--repo", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out

    # Both files should appear
    assert str(repo_cfg / "config.json") in out
    assert str(user_cfg / "config.json") in out

    # Repo file: sets [model], wins [model]
    assert "model" in out
    repo_line = [line for line in out.splitlines() if str(repo_cfg) in line][0]
    assert "model" in repo_line
    assert "wins:" in repo_line

    # User file: sets [base_url, model], wins [base_url]
    user_line = [line for line in out.splitlines() if str(user_cfg) in line][0]
    assert "base_url" in user_line
    assert "model" in user_line  # listed in keys
    # "wins:" should contain base_url but not model
    assert "base_url" in user_line.split("wins:")[1]
    assert "model" not in user_line.split("wins:")[1]


def test_show_no_config_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """No config files at all — the '(none — ...)' line is byte-identical."""
    rc = main(["config", "show", "--repo", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "config_file: (none — using env vars + built-in defaults)" in out
