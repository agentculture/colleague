"""delegation-follow-ups-a7-p3-hire plan task t4 (covers c42/h26): the
``COLLEAGUE_HIRE`` flag (env > config.json ``hire`` > OFF) and the acting
add-set (``COLLEAGUE_ACTING_ADD_TOOLS``) are RESOLVED onto EngineConfig,
omitted from the snapshot when unset, and always listed by ``config show``."""

from __future__ import annotations

import json
from pathlib import Path

from colleague.config import EngineConfig

_WORKTREE = Path(__file__).resolve().parent.parent


def _repo(tmp_path: Path, cfg: dict | None = None) -> str:
    repo = tmp_path / "repo"
    (repo / ".colleague").mkdir(parents=True, exist_ok=True)
    (repo / ".colleague" / "config.json").unlink(missing_ok=True)
    if cfg is not None:
        (repo / ".colleague" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    return str(repo)


def _resolve(tmp_path, monkeypatch, cfg=None, **env):
    for key in ("COLLEAGUE_HIRE", "COLLEAGUE_ACTING_ADD_TOOLS"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return EngineConfig.resolve(repo_path=_repo(tmp_path, cfg), discover_lobes=False)


def test_default_is_off_and_both_keys_omitted(tmp_path, monkeypatch):
    cfg = _resolve(tmp_path, monkeypatch)
    assert cfg.hire is False
    assert cfg.acting_add_tools == ()
    snap = cfg.to_dict()
    assert "hire" not in snap
    assert "acting_add_tools" not in snap


def test_env_wins_over_config_file(tmp_path, monkeypatch):
    assert _resolve(tmp_path, monkeypatch, {"hire": True}, COLLEAGUE_HIRE="0").hire is False
    assert _resolve(tmp_path, monkeypatch, {"hire": False}, COLLEAGUE_HIRE="1").hire is True


def test_config_file_bool_arms_and_snapshot_carries_it(tmp_path, monkeypatch):
    cfg = _resolve(tmp_path, monkeypatch, {"hire": True})
    assert cfg.hire is True
    assert cfg.to_dict()["hire"] is True


def test_add_set_is_parsed_like_the_drop_knob_and_snapshotted(tmp_path, monkeypatch):
    cfg = _resolve(
        tmp_path, monkeypatch, COLLEAGUE_ACTING_ADD_TOOLS=" subagent, subagents ,subagent,"
    )
    assert cfg.acting_add_tools == ("subagent", "subagents")
    assert cfg.to_dict()["acting_add_tools"] == ["subagent", "subagents"]
    assert _resolve(tmp_path, monkeypatch, COLLEAGUE_ACTING_ADD_TOOLS="  ").acting_add_tools == ()


def test_snapshots_differ_only_by_the_knob(tmp_path, monkeypatch):
    off = _resolve(tmp_path, monkeypatch).to_dict()
    on = _resolve(tmp_path, monkeypatch, COLLEAGUE_HIRE="1").to_dict()
    on.pop("hire")
    assert on == off


def test_hire_does_not_conflict_with_execution_modes(tmp_path, monkeypatch):
    cfg = _resolve(tmp_path, monkeypatch, COLLEAGUE_HIRE="1", COLLEAGUE_AGENTS="1")
    assert cfg.hire is True
    assert cfg.agents is True


def test_config_show_json_lists_both_knobs(tmp_path, monkeypatch):
    import subprocess
    import sys

    repo = _repo(tmp_path)
    env = {k: v for k, v in __import__("os").environ.items() if not k.startswith("COLLEAGUE_")}
    env["COLLEAGUE_LOBES_URL"] = ""
    out = subprocess.run(
        [sys.executable, "-m", "colleague", "config", "show", "--repo", repo, "--json"],
        capture_output=True,
        text=True,
        cwd=_WORKTREE,
        env=env,
        check=False,
    )
    data = json.loads(out.stdout)
    assert data["hire"] is False
    assert data["acting_add_tools"] == []
    env["COLLEAGUE_HIRE"] = "1"
    env["COLLEAGUE_ACTING_ADD_TOOLS"] = "subagent"
    out = subprocess.run(
        [sys.executable, "-m", "colleague", "config", "show", "--repo", repo, "--json"],
        capture_output=True,
        text=True,
        cwd=_WORKTREE,
        env=env,
        check=False,
    )
    data = json.loads(out.stdout)
    assert data["hire"] is True
    assert data["acting_add_tools"] == ["subagent"]


# ---------------------------------------------------------------------------
# Review findings (colleague second opinion, 2026-08-30, task 8e658025caa2):
# the nested config.json form silently ARMED (str(dict) -> _parse_bool True)
# and the non-JSON config show lines were unasserted.
# ---------------------------------------------------------------------------


def test_nested_config_form_reads_enabled_like_agents(tmp_path, monkeypatch):
    assert _resolve(tmp_path, monkeypatch, {"hire": {"enabled": False}}).hire is False
    assert _resolve(tmp_path, monkeypatch, {"hire": {"enabled": True}}).hire is True
    # the object's own presence, absent an explicit enabled=false, arms (the
    # agents / three_tier tolerance)
    assert _resolve(tmp_path, monkeypatch, {"hire": {}}).hire is True
    assert _resolve(tmp_path, monkeypatch, {"hire": "off"}).hire is False


def test_config_show_text_lines_list_both_knobs(tmp_path, monkeypatch):
    import subprocess
    import sys

    repo = _repo(tmp_path)
    env = {k: v for k, v in __import__("os").environ.items() if not k.startswith("COLLEAGUE_")}
    env["COLLEAGUE_LOBES_URL"] = ""
    out = subprocess.run(
        [sys.executable, "-m", "colleague", "config", "show", "--repo", repo],
        capture_output=True,
        text=True,
        cwd=_WORKTREE,
        env=env,
        check=False,
    )
    assert "hire: off" in out.stdout
    assert "acting_add_tools: unset" in out.stdout
    env["COLLEAGUE_HIRE"] = "1"
    env["COLLEAGUE_ACTING_ADD_TOOLS"] = "subagent,subagents"
    out = subprocess.run(
        [sys.executable, "-m", "colleague", "config", "show", "--repo", repo],
        capture_output=True,
        text=True,
        cwd=_WORKTREE,
        env=env,
        check=False,
    )
    assert "hire: armed" in out.stdout
    assert "acting_add_tools: subagent,subagents" in out.stdout
