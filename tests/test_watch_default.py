"""#307 — the flight plane is armed by default; opt-out precedence flag>env>config.

The config-resolution and precedence half of #307 (the CLI half lives in
test_work_watch.py). ``EngineConfig.watch`` defaults ON; ``COLLEAGUE_WATCH`` env
and ``.colleague/config.json`` ``{"watch": false}`` disarm it, env beating config.
"""

import argparse
import json
import subprocess
from pathlib import Path

import pytest

from colleague.cli._commands.session import run_session
from colleague.cli._commands.work import execute_work
from colleague.config import EngineConfig


def test_watch_defaults_on():
    assert EngineConfig.resolve().watch is True


def test_env_disables_watch(monkeypatch):
    monkeypatch.setenv("COLLEAGUE_WATCH", "0")
    assert EngineConfig.resolve().watch is False


def test_env_false_word_disables_watch(monkeypatch):
    monkeypatch.setenv("COLLEAGUE_WATCH", "false")
    assert EngineConfig.resolve().watch is False


def test_config_json_disables_watch(tmp_path):
    (tmp_path / ".colleague").mkdir()
    (tmp_path / ".colleague" / "config.json").write_text(json.dumps({"watch": False}))
    assert EngineConfig.resolve(repo_path=tmp_path).watch is False


def test_env_beats_config_json(tmp_path, monkeypatch):
    """Precedence: env COLLEAGUE_WATCH > config.json {watch}."""
    (tmp_path / ".colleague").mkdir()
    (tmp_path / ".colleague" / "config.json").write_text(json.dumps({"watch": False}))
    monkeypatch.setenv("COLLEAGUE_WATCH", "1")
    assert EngineConfig.resolve(repo_path=tmp_path).watch is True


def test_absent_config_is_default_on(tmp_path):
    """A repo with no config.json (and no env) keeps the default-on."""
    assert EngineConfig.resolve(repo_path=tmp_path).watch is True


# ── session default-arms the file plane (decision c18) ─────────────────────


class _Out:
    def __call__(self, *a, **k):
        pass


def _git_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@e.com"], cwd=tmp_path, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.name", "T"], cwd=tmp_path, check=True, capture_output=True
    )
    (tmp_path / "README.md").write_text("hi\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)
    return tmp_path


def _session_args(repo: Path) -> argparse.Namespace:
    return argparse.Namespace(
        repo=str(repo),
        engine="mock",
        no_pr=True,
        base="main",
        base_url=None,
        model=None,
        api_key=None,
        max_steps=None,
        json=False,
        allow_dirty=True,
    )


@pytest.mark.parametrize("watch_env,expected", [(None, True), ("0", False)])
def test_session_default_arms_the_file_plane(tmp_path, monkeypatch, watch_env, expected):
    """c18: a session work item default-arms task.watch (from config.watch), so a
    second terminal can `colleague talk` in — and COLLEAGUE_WATCH=0 opts out."""
    repo = _git_repo(tmp_path)
    if watch_env is not None:
        monkeypatch.setenv("COLLEAGUE_WATCH", watch_env)
    seen = {}

    def _capture(*, task, **kw):
        seen["watch"] = task.watch
        return execute_work(
            repo=kw["repo"],
            engine_name=kw["engine_name"],
            task=task,
            open_pr=kw["open_pr"],
            base=kw["base"],
            config=kw["config"],
            allow_dirty=kw.get("allow_dirty", False),
            command_name=kw.get("command_name"),
            tui=kw.get("tui"),
            tui_events=kw.get("tui_events"),
            progress_sink=kw.get("progress_sink"),
            mode=kw.get("mode"),
        )

    rc = run_session(
        _session_args(repo),
        input_fn=iter(["make a small change", "q"]),
        out=_Out(),
        _work_fn=_capture,
    )
    assert rc == 0
    assert seen.get("watch") is expected
