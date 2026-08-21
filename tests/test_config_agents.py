"""#411 t7 — the ``agents`` opt-in: env > config.json > OFF, mutual exclusion, omit-when-unarmed."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from colleague.cli._errors import CliError
from colleague.config import (
    EngineConfig,
    _load_agents_override,
    _refuse_conflicting_execution_modes,
    _resolve_agents_enabled,
)

_WORKTREE = Path(__file__).resolve().parent.parent


def _repo(tmp_path: Path, cfg: dict | None = None) -> Path:
    repo = tmp_path / "repo"
    (repo / ".colleague").mkdir(parents=True)
    if cfg is not None:
        (repo / ".colleague" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    return repo


def test_default_is_off_and_omitted_from_to_dict(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("COLLEAGUE_AGENTS", raising=False)
    cfg = EngineConfig.resolve(repo_path=_repo(tmp_path), discover_lobes=False)
    assert cfg.agents is False
    assert "agents" not in cfg.to_dict()


def test_env_wins_over_config_file(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path, {"agents": False})
    monkeypatch.setenv("COLLEAGUE_AGENTS", "1")
    cfg = EngineConfig.resolve(repo_path=repo, discover_lobes=False)
    assert cfg.agents is True
    assert cfg.to_dict()["agents"] is True
    monkeypatch.setenv("COLLEAGUE_AGENTS", "0")
    assert EngineConfig.resolve(repo_path=repo, discover_lobes=False).agents is False


def test_config_file_bool_and_object_forms(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("COLLEAGUE_AGENTS", raising=False)
    assert EngineConfig.resolve(
        repo_path=_repo(tmp_path, {"agents": True}), discover_lobes=False
    ).agents
    assert _load_agents_override(_repo(tmp_path / "b", {"agents": {"enabled": "false"}})) == "false"
    assert _resolve_agents_enabled("false") is False
    assert _resolve_agents_enabled(None) is False
    obj = EngineConfig.resolve(
        repo_path=_repo(tmp_path / "c", {"agents": {}}), discover_lobes=False
    )
    assert obj.agents is True  # object presence = armed (the three_tier precedent)


def test_arming_agents_never_arms_the_siblings(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("COLLEAGUE_AGENTS", "1")
    cfg = EngineConfig.resolve(repo_path=_repo(tmp_path), discover_lobes=False)
    assert cfg.agents and not cfg.three_tier and not cfg.thought_action_evaluation


def test_refusal_names_both_modes() -> None:
    with pytest.raises(CliError) as excinfo:
        _refuse_conflicting_execution_modes(True, False, True)
    assert "three_tier and agents" in str(excinfo.value)
    assert "COLLEAGUE_THREE_TIER / COLLEAGUE_AGENTS" in excinfo.value.remediation
    with pytest.raises(CliError) as excinfo:
        _refuse_conflicting_execution_modes(False, True, True)
    assert "thought_action_evaluation and agents" in str(excinfo.value)
    _refuse_conflicting_execution_modes(False, False, True)  # one mode: no-op
    _refuse_conflicting_execution_modes(False, False, False)


def test_agents_plus_tae_refuses_end_to_end(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("COLLEAGUE_AGENTS", "1")
    monkeypatch.setenv("COLLEAGUE_THOUGHT_ACTION_EVALUATION", "1")
    with pytest.raises(CliError) as excinfo:
        EngineConfig.resolve(repo_path=_repo(tmp_path), discover_lobes=False)
    assert "agents" in str(excinfo.value) and "thought_action_evaluation" in str(excinfo.value)


def test_config_show_prints_the_mode(tmp_path: Path, monkeypatch) -> None:
    env = {k: v for k, v in os.environ.items() if not k.startswith("COLLEAGUE_")}
    env["PYTHONPATH"] = str(_WORKTREE)
    cli = Path(sys.executable).parent / "colleague"
    repo = _repo(tmp_path)
    off = subprocess.run(
        [str(cli), "config", "show", "--repo", str(repo)], capture_output=True, text=True, env=env
    )
    assert "agents: off" in off.stdout, off.stdout + off.stderr
    env["COLLEAGUE_AGENTS"] = "1"
    on = subprocess.run(
        [str(cli), "config", "show", "--repo", str(repo)], capture_output=True, text=True, env=env
    )
    assert "agents: armed" in on.stdout, on.stdout + on.stderr
