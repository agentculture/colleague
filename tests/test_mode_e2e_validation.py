"""End-to-end mode-profile validation on the REAL mock engine (plan t19 / spec c3/h10).

Unlike the seam-level tests (``test_work_mode_wiring.py`` asserts the resolved
config through a recorder engine; ``test_mode_artifact.py`` the recording
paths; ``test_session_cockpit.py`` the Capacity panel), these run the genuine
``cmd_work`` → registry → mock engine → artifact pipeline with ZERO per-run
env tuning — the after-state's own bar: a moded run completes inside its
profile without the operator exporting anything.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import pytest

from colleague.cli._commands.work import cmd_work


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    for key, value in (("user.email", "t@e.c"), ("user.name", "T")):
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


def _namespace(repo: Path, **overrides) -> argparse.Namespace:
    base = dict(
        instruction=["survey", "the", "repo"],
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


def _read_artifacts(repo: Path) -> list[dict]:
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((repo / ".colleague").glob("*.json"))
        if path.name not in {"config.json", "rig.json"}
    ]


def test_mode_explore_end_to_end_on_the_real_mock(git_repo, capsys):
    """Zero env tuning: --mode explore completes and the artifact records it."""
    rc = cmd_work(_namespace(git_repo, mode="explore"))
    assert rc == 0
    artifacts = _read_artifacts(git_repo)
    assert len(artifacts) == 1
    assert artifacts[0]["mode"] == "explore"
    assert artifacts[0]["status"] == "ok"


def test_no_mode_end_to_end_artifact_has_no_mode_key(git_repo, capsys):
    rc = cmd_work(_namespace(git_repo))
    assert rc == 0
    artifacts = _read_artifacts(git_repo)
    assert len(artifacts) == 1
    assert "mode" not in artifacts[0]


def test_goal_and_acceptance_survive_a_real_mock_run(git_repo, capsys, monkeypatch):
    """A goal-bearing task runs the whole pipeline; outcomes stay advisory.

    The mock engine's scripted turns do not answer the self-check with JSON,
    so ``acceptance_outcomes`` is legitimately absent — the honest assertion
    is that the run still completes OK (the check can never wedge or flip a
    run) rather than pretending the mock graded itself.
    """
    from colleague.cli._commands.work import execute_work
    from colleague.config import EngineConfig
    from colleague.contract import Task

    task = Task.new(
        str(git_repo),
        "add a readme note",
        engine="mock",
        goal="the note exists",
        acceptance=["README mentions the note"],
    )
    result, artifact_path = execute_work(
        repo=git_repo,
        engine_name="mock",
        task=task,
        open_pr=False,
        base="main",
        config=EngineConfig.resolve(repo_path=git_repo),
        allow_dirty=True,
    )
    assert result.status == "ok"
    data = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert data["status"] == "ok"  # advisory self-check never flips/wedges a run
