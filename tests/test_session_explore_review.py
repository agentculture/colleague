"""Read-only proof for session explore/review (t4 — covers c13/h7).

Proves the R6 guarantee three ways:
 1. the explorer/reviewer roles the session dispatches under are structurally
    read-only (their curated tool surface withholds write_file/edit_file/
    run_command);
 2. a real session explore AND review run (through the real ``execute_work`` on
    the no-op ``mock`` engine) leaves ``git status`` + branch + HEAD byte-identical
    — no commit, branch, or PR handoff;
 3. the reviewer's diff is sourced operator-side via ``handoff.diff_range``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from colleague import handoff
from colleague.cli._commands.session import run_session
from colleague.roles import _WRITE_TOOLS
from colleague.tools import curate_schemas

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(  # nosec B603 B607 - fixed git argv in a test
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout


def _init_git_repo(repo: Path) -> None:
    """A real git repo with one commit on ``main`` (cwd-scoped identity so CI
    never hits a global-config exit-128)."""
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("# test\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "init")


def _assert_repo_unmutated(repo: Path, before: tuple[str, str]) -> None:
    """Assert R6: no new commit, no branch switch, no ``colleague/*`` work branch,
    and no change to TRACKED files. The only thing a read-only verb may leave is
    the untracked ``.colleague/`` run artifact (its preserved findings, #132) —
    that is colleague's own bookkeeping, not a mutation of the operator's repo."""
    before_branch, before_head = before
    assert _git(repo, "rev-parse", "HEAD").strip() == before_head  # no commit
    assert _git(repo, "branch", "--show-current").strip() == before_branch  # no switch
    assert "colleague/" not in _git(repo, "branch", "--list")  # no work branch made
    # No staged/unstaged change to any TRACKED file (ignore the .colleague/ artifact).
    porcelain = _git(repo, "status", "--porcelain")
    tracked = [ln for ln in porcelain.splitlines() if ln.strip() and ".colleague/" not in ln]
    assert tracked == [], f"unexpected tracked-tree change: {tracked}"


def _git_head_branch(repo: Path) -> tuple[str, str]:
    return _git(repo, "branch", "--show-current").strip(), _git(repo, "rev-parse", "HEAD").strip()


def _make_args(tmp_path: Path) -> Any:
    import argparse

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


# ---------------------------------------------------------------------------
# 1. The dispatched roles are structurally read-only
# ---------------------------------------------------------------------------


def test_explorer_reviewer_roles_withhold_write_tools() -> None:
    for role in ("explorer", "reviewer"):
        names = {s["function"]["name"] for s in curate_schemas(role)}
        assert names.isdisjoint(_WRITE_TOOLS), f"{role} must withhold {_WRITE_TOOLS}"
        # ...and still offer reading, so the probe can do real work.
        assert "read_file" in names


# ---------------------------------------------------------------------------
# 2. A session explore / review leaves git byte-identical
# ---------------------------------------------------------------------------


def test_session_explore_leaves_git_unchanged(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    before = _git_head_branch(tmp_path)
    run_session(
        _make_args(tmp_path),
        input_fn=iter(["/mode explore", "what lives in this repo", "q"]),
        out=lambda *a, **k: None,
        _color=False,
    )
    _assert_repo_unmutated(tmp_path, before)


def test_session_review_leaves_git_unchanged(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    # Add a committed change so there is a real <base>...HEAD diff to review.
    (tmp_path / "feature.py").write_text("x = 1\n")
    _git(tmp_path, "checkout", "-b", "feat")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "add feature")
    before = _git_head_branch(tmp_path)
    run_session(
        _make_args(tmp_path),
        input_fn=iter(["/mode review", "check the feature", "q"]),
        out=lambda *a, **k: None,
        _color=False,
    )
    _assert_repo_unmutated(tmp_path, before)  # still on 'feat', no new commit/branch


# ---------------------------------------------------------------------------
# 3. The reviewer diff is sourced operator-side
# ---------------------------------------------------------------------------


def test_diff_range_returns_committed_changes(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    (tmp_path / "feature.py").write_text("def added():\n    return 42\n")
    _git(tmp_path, "checkout", "-b", "feat")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "add feature")
    diff = handoff.diff_range(tmp_path, "main")
    assert "feature.py" in diff
    assert "def added" in diff


def test_diff_range_invalid_base_returns_empty_not_crash(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    assert handoff.diff_range(tmp_path, "no-such-ref") == ""


# ---------------------------------------------------------------------------
# 4. Read-only modes work on a DIRTY tree without sweeping the operator's WIP
# ---------------------------------------------------------------------------
#
# explore/review run under a read-only role with open_pr=False. The runtime
# (execute_work) detects the read-only role and both bypasses the dirty-tree
# guard (#149) AND skips the write handoff — so a read-only run starts even with
# operator WIP present and the handoff's `git add -u` never sweeps that WIP onto
# colleague/<id> (which would then restore HEAD over it = silent data loss).
# Regression for the Qodo finding on PR #245.


def test_session_explore_runs_on_dirty_tree_no_guard_error(tmp_path: Path) -> None:
    """End-to-end on the no-op ``mock`` engine: with an uncommitted *tracked* edit
    present, an explore must actually run (no dirty-tree CliError) and must leave
    the operator's WIP untouched (read-only — never swept onto a work branch)."""
    _init_git_repo(tmp_path)
    (tmp_path / "README.md").write_text("# test\nuncommitted WIP edit\n")  # dirty tracked file
    before = _git_head_branch(tmp_path)
    errors: list[str] = []
    run_session(
        _make_args(tmp_path),
        input_fn=iter(["/mode explore", "what lives in this repo", "q"]),
        out=lambda *a, **k: None,
        err=lambda *a, **k: errors.append(" ".join(str(x) for x in a)),
        _color=False,
    )
    assert not any("uncommitted changes" in e for e in errors), errors
    # The WIP edit survives (read-only never reverted or swept it) and no commit/
    # branch handoff happened.
    assert "uncommitted WIP edit" in (tmp_path / "README.md").read_text()
    assert _git(tmp_path, "rev-parse", "HEAD").strip() == before[1]
    assert "colleague/" not in _git(tmp_path, "branch", "--list")
