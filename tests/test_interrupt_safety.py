"""Tests for #222 — an interrupted colleague work item never strands your work.

Covers the three code requirements:
- t1 (worktrees primitives): commit_iso_worktree_wip commits WIP onto the iso
  worktree's checked-out branch (empty diff = no-op); list_iso_worktrees /
  reap_orphaned_iso_worktrees are scoped STRICTLY to .colleague/worktrees/iso-*.
- t2 (interrupt commit): _arm_interrupt_commit installs a SIGTERM/SIGINT handler
  that commits the iso worktree to colleague/<id> then re-raises KeyboardInterrupt,
  and restores the prior disposition.
- t3 (clean reap): `colleague clean` reaps orphaned iso-* worktrees (honoring
  --dry-run) and never touches a sub/* child or an unrelated worktree.
"""

from __future__ import annotations

import argparse
import signal
import subprocess
from pathlib import Path

import pytest

from colleague import worktrees
from colleague.cli._commands.clean import cmd_clean
from colleague.cli._commands.work import _arm_interrupt_commit


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, check=True)


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@colleague.test")
    _git(repo, "config", "user.name", "Colleague Test")
    (repo / "README.md").write_text("# test repo\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "initial commit")
    return repo


def _branch_log(repo: Path, branch: str) -> str:
    proc = subprocess.run(
        ["git", "log", "--oneline", branch], cwd=str(repo), capture_output=True, text=True
    )
    return proc.stdout


# ---------------------------------------------------------------------------
# t1 — worktrees primitives
# ---------------------------------------------------------------------------


def test_commit_iso_worktree_wip_commits_then_noop(git_repo: Path) -> None:
    wt = worktrees.isolation_worktree_add(str(git_repo), "task1", "colleague/task1")
    (Path(wt) / "new.py").write_text("print('wip')\n", encoding="utf-8")

    assert worktrees.commit_iso_worktree_wip(wt, reason="SIGTERM") is True
    assert "WIP committed on SIGTERM" in _branch_log(git_repo, "colleague/task1")
    # idempotent: a clean worktree (empty diff) is a no-op, never an error
    assert worktrees.commit_iso_worktree_wip(wt, reason="SIGTERM") is False


def test_list_and_reap_scoped_to_iso_only(git_repo: Path) -> None:
    iso = worktrees.isolation_worktree_add(str(git_repo), "abc", "colleague/abc")
    # decoys that must NEVER be reaped by the iso path:
    sub = worktrees.worktree_add(str(git_repo), "child1")  # .colleague/worktrees/child1 (sub/*)
    outside = git_repo.parent / "unrelated-wt"
    _git(git_repo, "worktree", "add", str(outside), "-b", "feature/x")

    listed = worktrees.list_iso_worktrees(str(git_repo))
    assert listed == [iso]  # only the iso-* worktree, not the sub/* child or the unrelated one
    assert sub not in listed and str(outside) not in listed

    reaped = worktrees.reap_orphaned_iso_worktrees(str(git_repo))
    assert reaped == [iso]
    assert not Path(iso).exists()
    # decoys survive
    assert Path(sub).exists()
    assert outside.exists()


def test_reap_dry_run_reports_without_removing(git_repo: Path) -> None:
    iso = worktrees.isolation_worktree_add(str(git_repo), "dry", "colleague/dry")
    reported = worktrees.reap_orphaned_iso_worktrees(str(git_repo), dry_run=True)
    assert reported == [iso]
    assert Path(iso).exists()  # dry-run changed nothing


def test_reap_spares_active_task_ids(git_repo: Path) -> None:
    """A still-running work item (active flight id) is never reaped (review of #228)."""
    live = worktrees.isolation_worktree_add(str(git_repo), "live1", "colleague/live1")
    dead = worktrees.isolation_worktree_add(str(git_repo), "dead1", "colleague/dead1")

    reaped = worktrees.reap_orphaned_iso_worktrees(str(git_repo), active_task_ids={"live1"})
    assert reaped == [dead]  # only the non-active one
    assert Path(live).exists()  # the active run's worktree is spared
    assert not Path(dead).exists()


# ---------------------------------------------------------------------------
# t2 — interrupt-commit handler
# ---------------------------------------------------------------------------


def test_arm_interrupt_commit_commits_and_restores(git_repo: Path) -> None:
    wt = worktrees.isolation_worktree_add(str(git_repo), "sig", "colleague/sig")
    (Path(wt) / "wip.py").write_text("x = 1\n", encoding="utf-8")

    prior = signal.getsignal(signal.SIGTERM)
    restore = _arm_interrupt_commit(wt)
    try:
        handler = signal.getsignal(signal.SIGTERM)
        assert callable(handler) and handler is not prior
        # Simulate the SIGTERM: the handler commits WIP, restores, and raises
        # SystemExit(128+signum) — NOT KeyboardInterrupt — so the CLI exits cleanly
        # with the conventional signal code and no traceback (review of #228).
        with pytest.raises(SystemExit) as exc_info:
            handler(signal.SIGTERM, None)
        assert exc_info.value.code == 128 + signal.SIGTERM  # 143 for SIGTERM
        assert "WIP committed on SIGTERM" in _branch_log(git_repo, "colleague/sig")
        # the handler restored the prior disposition before exiting
        assert signal.getsignal(signal.SIGTERM) is prior
    finally:
        restore()
    assert signal.getsignal(signal.SIGTERM) is prior


def test_arm_interrupt_commit_restore_is_idempotent(git_repo: Path) -> None:
    wt = worktrees.isolation_worktree_add(str(git_repo), "r", "colleague/r")
    prior = signal.getsignal(signal.SIGINT)
    restore = _arm_interrupt_commit(wt)
    restore()
    restore()  # second call must not raise
    assert signal.getsignal(signal.SIGINT) is prior


# ---------------------------------------------------------------------------
# t3 — clean reaps iso worktrees (before the branch reap), scoped, --dry-run honored
# ---------------------------------------------------------------------------


def _clean_args(repo: Path, *, dry_run: bool) -> argparse.Namespace:
    return argparse.Namespace(
        repo=str(repo), dry_run=dry_run, merged=False, older_than=None, base="main", json=True
    )


def test_clean_reaps_orphan_iso_worktree(git_repo: Path, capsys: pytest.CaptureFixture) -> None:
    iso = worktrees.isolation_worktree_add(str(git_repo), "crash", "colleague/crash")
    sub = worktrees.worktree_add(str(git_repo), "child9")

    assert cmd_clean(_clean_args(git_repo, dry_run=False)) == 0
    assert not Path(iso).exists()  # iso reaped
    assert Path(sub).exists()  # sub/* child untouched


def test_clean_dry_run_keeps_iso_worktree(git_repo: Path) -> None:
    iso = worktrees.isolation_worktree_add(str(git_repo), "keep", "colleague/keep")
    assert cmd_clean(_clean_args(git_repo, dry_run=True)) == 0
    assert Path(iso).exists()  # dry-run removed nothing
