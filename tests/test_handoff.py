"""Git/PR handoff: gating, local-only commit, no-change short-circuit (R7, h7)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from convertible.handoff import handoff, has_remote, should_open_pr


def _run(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True)


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _run(repo, "init", "-q")
    _run(repo, "config", "user.email", "test@example.com")
    _run(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("seed\n")
    _run(repo, "add", "-A")
    _run(repo, "commit", "-q", "-m", "init")


def _current_branch(repo: Path) -> str:
    proc = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


def test_local_only_repo_has_no_remote(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    assert has_remote(repo) is False
    assert should_open_pr(repo, open_pr=True) is False  # no remote -> never pushes


def test_handoff_commits_locally_without_pushing(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "feature.txt").write_text("new work\n")

    result = handoff(repo, "abc123", instruction="add feature", open_pr=True)

    assert result.branch == "convertible/abc123"
    assert result.committed is True
    assert result.pushed is False
    assert result.pr_url is None
    assert _current_branch(repo) == "convertible/abc123"


def test_handoff_respects_no_pr_flag(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "feature.txt").write_text("work\n")

    result = handoff(repo, "deadbeef", open_pr=False)
    assert result.committed is True
    assert result.pr_url is None


def test_handoff_no_changes_short_circuits(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)

    result = handoff(repo, "nochange", open_pr=True)
    assert result.committed is False
    assert result.branch is None
    assert "no changes" in result.note
