"""#310 — the flight plane is armed at the OPERATOR repo, not the isolation worktree.

Before #310, ``colleague work --watch`` (a write run, so it isolates) armed the
flight plane at ``task.repo_path`` — which ``_setup_isolation`` had reassigned to
the throwaway ``iso-<id>/`` worktree. So ``colleague talk`` / ``colleague flight``
(which resolve against the operator repo) saw "no active flight", and the feed
was destroyed with the worktree on cleanup.

The fix threads the operator repo through ``Task.flight_repo_path`` and resolves
the plane location via ``loop._flight_repo_path`` (``flight_repo_path or
repo_path``), so the plane the loop writes is the plane the operator reads.
"""

import argparse
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from colleague import flight
from colleague.cli._commands.work import _setup_isolation, cmd_work
from colleague.contract import Task
from colleague.loop import _arm_flight, _flight_repo_path


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """A git-initialised tmp_path with an initial commit (isolation needs a HEAD)."""
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=tmp_path, check=True, capture_output=True
    )
    (tmp_path / "README.md").write_text("hello\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)
    return tmp_path


def _make_ns(repo: Path, *, watch: bool = False) -> argparse.Namespace:
    return argparse.Namespace(
        instruction=["do x"],
        repo=str(repo),
        engine="mock",
        no_pr=True,
        watch=watch,
        base=None,
        model=None,
        base_url=None,
        api_key=None,
        max_steps=5,
        json=False,
        command_name=None,
        allow_dirty=True,
        tui=None,
        tui_events=None,
    )


# ── _flight_repo_path resolution (the single source of truth) ──────────────


def test_flight_repo_path_prefers_operator_repo_when_set():
    task = Task.new("/repo/iso-abc", "x", watch=True)
    task = replace(task, flight_repo_path="/operator/repo")
    assert _flight_repo_path(task) == "/operator/repo"


def test_flight_repo_path_falls_back_to_repo_path_when_none():
    """The in-place session path (flight_repo_path None) is byte-identical:
    arm at repo_path, the pre-#310 behaviour."""
    task = Task.new("/operator/repo", "x", watch=True)
    assert task.flight_repo_path is None
    assert _flight_repo_path(task) == "/operator/repo"


# ── _arm_flight arms at the operator repo, and operator guidance drains ─────


def test_arm_flight_arms_at_operator_repo_not_worktree(tmp_path):
    """The exact #310 bug: an isolated task must arm the FlightSession at the
    operator repo, not the worktree at repo_path."""
    operator = tmp_path / "op"
    operator.mkdir()
    worktree = tmp_path / "iso-xyz"
    worktree.mkdir()
    task = replace(Task.new(str(worktree), "x", watch=True), flight_repo_path=str(operator))
    session = _arm_flight(task)
    assert session is not None
    assert session.repo_path == Path(str(operator))  # operator, NOT worktree
    # The feed file was created in the operator repo (repro #5).
    assert flight.feed_path(operator, task.id).exists()
    assert not flight.flight_dir(worktree).exists()


def test_operator_repo_guidance_drains_into_the_armed_session(tmp_path):
    """Repro #4: guidance written to the operator-repo control.json drains into
    the loop's FlightSession (armed at the operator repo)."""
    operator = tmp_path / "op"
    operator.mkdir()
    worktree = tmp_path / "iso-xyz"
    worktree.mkdir()
    task = replace(Task.new(str(worktree), "x", watch=True), flight_repo_path=str(operator))
    session = _arm_flight(task)
    flight.append_guidance(str(operator), task.id, "focus only on colleague/cli")
    control = session.read_control()
    assert "focus only on colleague/cli" in control.guidance


def test_arm_flight_unwatched_is_none(tmp_path):
    task = replace(Task.new(str(tmp_path), "x", watch=False), flight_repo_path=str(tmp_path))
    assert _arm_flight(task) is None


# ── _setup_isolation stamps flight_repo_path with the operator repo ────────


def test_setup_isolation_stamps_operator_repo_as_flight_repo_path(git_repo):
    task = Task.new(str(git_repo), "write a file", watch=True)
    work_repo, base_sha, worktree_path, iso_task = _setup_isolation(git_repo, task, isolate=True)
    try:
        assert worktree_path is not None  # it isolated
        assert iso_task.repo_path == str(work_repo)  # loop runs in the worktree
        assert iso_task.flight_repo_path == str(git_repo)  # plane lives in operator repo
        assert iso_task.repo_path != iso_task.flight_repo_path
    finally:
        if worktree_path is not None:
            from colleague import worktrees

            worktrees.isolation_worktree_remove(str(git_repo), worktree_path)


def test_setup_isolation_inplace_leaves_flight_repo_path_none(git_repo):
    """The in-place path (isolate=False) leaves flight_repo_path None — byte-identical."""
    task = Task.new(str(git_repo), "x", watch=True)
    _, _, worktree_path, out_task = _setup_isolation(git_repo, task, isolate=False)
    assert worktree_path is None
    assert out_task.flight_repo_path is None
    assert out_task.repo_path == str(git_repo)


# ── end-to-end repro #5: the flight dir lands in the operator repo ─────────


def test_310_isolated_watched_run_creates_flight_dir_in_operator_repo(git_repo):
    """An isolated ``colleague work --watch`` (mock) leaves ``.colleague/flight/``
    in the OPERATOR repo — it survives worktree cleanup. Pre-#310 the dir was in
    the worktree and vanished with it ("no active flight")."""
    cmd_work(_make_ns(git_repo, watch=True))
    assert flight.flight_dir(git_repo).exists()
