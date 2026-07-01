"""Tests for the --mode → profile wiring (plan t3 / spec R1 / #254).

``colleague work --mode <m>`` and the session's mode selection resolve the
mode's constraint profile through ONE code path — ``execute_work`` applies
:func:`colleague.config.apply_mode_profile` — so the two entry doors cannot
drift. Explicit flags still win (h1); an unknown mode fails loudly with the
valid choices; no mode is byte-identical.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from typing import Optional

import pytest

from colleague.cli._commands.session import run_session
from colleague.cli._commands.work import _validated_mode, cmd_work, execute_work
from colleague.cli._errors import CliError
from colleague.config import EngineConfig
from colleague.contract import OK, TaskResult
from colleague.profiles import MODE_PROFILES
from colleague.session_modes import MODES


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """A git-initialised tmp_path with an initial commit (cwd-scoped identity)."""
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    for key, value in (("user.email", "test@example.com"), ("user.name", "Test")):
        subprocess.run(
            ["git", "config", key, value],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
    (tmp_path / "README.md").write_text("hello\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)
    return tmp_path


class _RecorderEngine:
    """Engine stub recording the config each work call receives."""

    def __init__(self, seen: list) -> None:
        self.seen = seen

    def work(self, task, config) -> TaskResult:
        self.seen.append(config)
        return TaskResult(task_id=task.id, status=OK, summary="done")


@pytest.fixture
def recorded_configs(monkeypatch) -> list:
    seen: list = []
    monkeypatch.setattr("colleague.registry.load", lambda name: _RecorderEngine(seen))
    return seen


# ---------------------------------------------------------------------------
# _validated_mode
# ---------------------------------------------------------------------------


def test_validated_mode_none_passes_through():
    assert _validated_mode(None) is None


@pytest.mark.parametrize("mode", sorted(MODES))
def test_validated_mode_accepts_catalog_modes(mode):
    assert _validated_mode(mode) == mode


def test_validated_mode_unknown_raises_with_choices():
    with pytest.raises(CliError) as exc_info:
        _validated_mode("warp")
    assert "warp" in str(exc_info.value.message)
    assert "explore" in str(exc_info.value.remediation)


# ---------------------------------------------------------------------------
# execute_work — the one code path
# ---------------------------------------------------------------------------


def _run_execute(git_repo: Path, *, mode: Optional[str], **kwargs):
    from colleague.contract import Task

    config = EngineConfig.resolve(repo_path=git_repo)
    task = Task.new(str(git_repo), "map the loop", engine="mock")
    return execute_work(
        repo=git_repo,
        engine_name="mock",
        task=task,
        open_pr=False,
        base="main",
        config=config,
        allow_dirty=True,
        mode=mode,
        **kwargs,
    )


def test_execute_work_applies_explore_profile(git_repo, recorded_configs):
    _run_execute(git_repo, mode="explore")
    config = recorded_configs[0]
    profile = MODE_PROFILES["explore"]
    assert config.max_steps == profile.max_steps
    assert config.synthesis_reserve_steps == profile.synthesis_reserve_steps
    assert config.fillline_threshold == profile.fillline_threshold
    assert config.context_budget_tokens == int(
        EngineConfig().context_budget_tokens * profile.context_budget_fraction
    )


def test_execute_work_without_mode_is_byte_identical(git_repo, recorded_configs):
    _run_execute(git_repo, mode=None)
    config = recorded_configs[0]
    defaults = EngineConfig.resolve(repo_path=git_repo)
    assert config.max_steps == defaults.max_steps
    assert config.context_budget_tokens == defaults.context_budget_tokens
    assert config.synthesis_reserve_steps == defaults.synthesis_reserve_steps


def test_execute_work_explicit_knobs_win(git_repo, recorded_configs):
    from colleague.contract import Task

    config = EngineConfig.resolve(max_steps=50, repo_path=git_repo)
    task = Task.new(str(git_repo), "map the loop", engine="mock")
    execute_work(
        repo=git_repo,
        engine_name="mock",
        task=task,
        open_pr=False,
        base="main",
        config=config,
        allow_dirty=True,
        mode="explore",
        explicit_knobs=frozenset({"max_steps"}),
    )
    seen = recorded_configs[0]
    assert seen.max_steps == 50  # the flag wins
    assert seen.synthesis_reserve_steps == 3  # untouched knobs still fill


# ---------------------------------------------------------------------------
# cmd_work — flag + validation
# ---------------------------------------------------------------------------


def _namespace(repo: Path, **overrides) -> argparse.Namespace:
    base = dict(
        instruction=["do", "x"],
        repo=str(repo),
        engine="mock",
        no_pr=True,
        watch=False,
        base="main",
        model=None,
        base_url=None,
        api_key=None,
        max_steps=None,
        json=True,
        command_name=None,
        allow_dirty=True,
        tui=None,
        tui_events=None,
        mode=None,
        role=None,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


def test_cmd_work_mode_flag_applies_profile(git_repo, recorded_configs, capsys):
    rc = cmd_work(_namespace(git_repo, mode="explore"))
    assert rc == 0
    assert recorded_configs[0].max_steps == MODE_PROFILES["explore"].max_steps


def test_cmd_work_explicit_max_steps_beats_profile(git_repo, recorded_configs, capsys):
    rc = cmd_work(_namespace(git_repo, mode="explore", max_steps=50))
    assert rc == 0
    assert recorded_configs[0].max_steps == 50
    assert recorded_configs[0].synthesis_reserve_steps == 3


def test_cmd_work_unknown_mode_fails_loudly(git_repo, recorded_configs):
    with pytest.raises(CliError):
        cmd_work(_namespace(git_repo, mode="warp"))
    assert recorded_configs == []  # refused before any work


# ---------------------------------------------------------------------------
# session — the same code path, mode threaded through work_fn
# ---------------------------------------------------------------------------


class _CollectingOut:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, *args: object, **kwargs: object) -> None:
        self.lines.append(" ".join(str(a) for a in args))


def _silent(*args: object, **kwargs: object) -> None:
    """Discard all output (err sink)."""


def _session_args(tmp_path: Path) -> argparse.Namespace:
    return argparse.Namespace(
        repo=str(tmp_path),
        engine="mock",
        no_pr=True,
        base="main",
        base_url=None,
        model=None,
        api_key=None,
        max_steps=None,
        json=False,
        allow_dirty=False,
    )


def _capture_work_fn(capture: dict):
    def _work_fn(**kwargs: object):
        capture["mode"] = kwargs.get("mode")
        capture["config"] = kwargs.get("config")
        task = kwargs.get("task")
        return (
            TaskResult(task_id=getattr(task, "id", "x"), status=OK, summary="done"),
            Path("art.json"),
        )

    return _work_fn


def test_session_explore_mode_threads_to_execute_work(tmp_path):
    capture: dict = {}
    run_session(
        _session_args(tmp_path),
        input_fn=iter(["/mode explore", "how does the loop work", "q"]),
        out=_CollectingOut(),
        err=_silent,
        _work_fn=_capture_work_fn(capture),
        _color=False,
    )
    assert capture["mode"] == "explore"
    assert capture["config"].role == "explorer"


def test_session_work_route_passes_neutral_work_mode(tmp_path):
    capture: dict = {}
    run_session(
        _session_args(tmp_path),
        input_fn=iter(["fix the readme typo", "q"]),
        out=_CollectingOut(),
        err=_silent,
        _work_fn=_capture_work_fn(capture),
        _color=False,
    )
    assert capture["mode"] == "work"
