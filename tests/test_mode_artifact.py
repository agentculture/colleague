"""``TaskResult.mode`` recorded in the artifact, omit-when-None (plan t7 / spec R3 / #256).

``execute_work`` (``colleague/cli/_commands/work.py``) records the driving mode
onto ``result.mode`` before every artifact write — on the success path AND the
failure path (an engine that raises) — mirroring how ``command_name`` is
already recorded on both paths. A work item run with no mode selected must
serialize byte-identically to today (no ``"mode"`` key in the artifact JSON) —
the e2e mock shape test (``tests/test_e2e_mock.py``) pins this by calling
``registry.load("mock").work(...)`` directly, a path that never touches
``execute_work`` and therefore never sets ``result.mode``.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Optional

import pytest

from colleague.cli._commands.work import execute_work
from colleague.config import EngineConfig
from colleague.contract import OK, Task, TaskResult


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
    """Engine stub that finishes cleanly (mirrors the idiom in test_work_mode_wiring.py)."""

    def __init__(self, seen: list) -> None:
        self.seen = seen

    def work(self, task, config) -> TaskResult:
        self.seen.append(config)
        return TaskResult(task_id=task.id, status=OK, summary="done")


class _BrokenEngine:
    """Engine stub that fails before producing any partial result."""

    def work(self, task, config) -> TaskResult:
        raise RuntimeError("kaboom before the loop")


def _run_execute(git_repo: Path, *, mode: Optional[str], **kwargs):
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


# ---------------------------------------------------------------------------
# success path
# ---------------------------------------------------------------------------


def test_execute_work_with_mode_records_mode_in_artifact(git_repo, monkeypatch):
    seen: list = []
    monkeypatch.setattr("colleague.registry.load", lambda name: _RecorderEngine(seen))

    result, artifact_path = _run_execute(git_repo, mode="explore")

    assert result.mode == "explore"
    payload = json.loads(artifact_path.read_text())
    assert payload["mode"] == "explore"


def test_execute_work_without_mode_omits_mode_key_in_artifact(git_repo, monkeypatch):
    seen: list = []
    monkeypatch.setattr("colleague.registry.load", lambda name: _RecorderEngine(seen))

    result, artifact_path = _run_execute(git_repo, mode=None)

    assert result.mode is None
    payload = json.loads(artifact_path.read_text())
    assert "mode" not in payload


# ---------------------------------------------------------------------------
# failure path — the engine raises before any partial result
# ---------------------------------------------------------------------------


def test_execute_work_failure_path_still_records_mode(git_repo, monkeypatch):
    from colleague.artifact import artifact_dir
    from colleague.cli._errors import CliError

    monkeypatch.setattr("colleague.registry.load", lambda name: _BrokenEngine())

    with pytest.raises(CliError) as exc_info:
        _run_execute(git_repo, mode="review")

    # The artifact was still written (h5) — locate it and check its mode key.
    artifacts = list(artifact_dir(git_repo).glob("*.json"))
    assert len(artifacts) == 1
    payload = json.loads(artifacts[0].read_text())
    assert payload["status"] == "error"
    assert payload["mode"] == "review"
    # The CliError also carries the failed result when it's a fresh failed_result
    # (no partial) — but the artifact-on-disk check above is the authoritative one.
    assert exc_info.value is not None


def test_execute_work_failure_path_without_mode_omits_mode_key(git_repo, monkeypatch):
    from colleague.artifact import artifact_dir
    from colleague.cli._errors import CliError

    monkeypatch.setattr("colleague.registry.load", lambda name: _BrokenEngine())

    with pytest.raises(CliError):
        _run_execute(git_repo, mode=None)

    artifacts = list(artifact_dir(git_repo).glob("*.json"))
    assert len(artifacts) == 1
    payload = json.loads(artifacts[0].read_text())
    assert payload["status"] == "error"
    assert "mode" not in payload
