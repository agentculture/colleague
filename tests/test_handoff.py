"""Git/PR handoff: gating, local-only commit, no-change short-circuit (R7, h7)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from convertible import handoff as ho
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


def test_handoff_reports_changed_files(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "new.txt").write_text("hi\n")

    result = handoff(repo, "abc", open_pr=False)
    assert "new.txt" in result.changed_files


def _commit_subject(repo: Path) -> str:
    proc = subprocess.run(
        ["git", "log", "-1", "--format=%s"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


def _commit_body(repo: Path) -> str:
    proc = subprocess.run(
        ["git", "log", "-1", "--format=%b"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


def _committed_files(repo: Path) -> list[str]:
    proc = subprocess.run(
        ["git", "show", "--name-only", "--format=", "HEAD"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    )
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def test_handoff_excludes_convertible_bookkeeping_dir(tmp_path: Path) -> None:
    """A prior run's untracked .convertible/* artifacts must not be swept in (#39)."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / ".convertible").mkdir()
    (repo / ".convertible" / "old.json").write_text("{}\n")  # leftover from a prior run
    (repo / ".convertible" / "old.trace.jsonl").write_text("\n")
    (repo / "feature.txt").write_text("real work\n")

    result = handoff(repo, "abc123", instruction="add feature", open_pr=False)

    committed = _committed_files(repo)
    assert "feature.txt" in committed
    assert not any(p.startswith(".convertible/") for p in committed)
    # changed_files reflects the committed set, not the swept tree.
    assert result.changed_files == ["feature.txt"]


def test_handoff_only_bookkeeping_output_is_a_no_op(tmp_path: Path) -> None:
    """If the only untracked output is .convertible/*, there is nothing to commit (#39)."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / ".convertible").mkdir()
    (repo / ".convertible" / "x.json").write_text("{}\n")

    result = handoff(repo, "abc123", open_pr=False)
    assert result.committed is False
    assert result.branch is None
    assert "no changes to hand off" in result.note


def test_handoff_commit_subject_is_short_with_full_body(tmp_path: Path) -> None:
    """Long instruction -> short subject + full instruction in the body (#40)."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "feature.txt").write_text("work\n")
    instruction = (
        "Build a static site with a read-only file list, inline car-metaphor content, "
        "and a strict length cap so the page never grows unbounded across runs"
    )

    handoff(repo, "deadbeef", instruction=instruction, open_pr=False)

    subject = _commit_subject(repo)
    assert "\n" not in subject
    assert len(subject) <= len("convertible: ") + 64
    assert subject.startswith("convertible: Build a static site")
    assert subject.endswith("...")
    # Full instruction preserved in the body.
    assert instruction in _commit_body(repo)


def test_handoff_short_instruction_needs_no_body(tmp_path: Path) -> None:
    """A short single-line instruction lives entirely in the subject (no redundant body)."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "feature.txt").write_text("work\n")

    handoff(repo, "t1", instruction="tidy up", open_pr=False)
    assert _commit_subject(repo) == "convertible: tidy up"
    assert _commit_body(repo) == ""


def test_handoff_empty_instruction_falls_back_to_task_id(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "feature.txt").write_text("work\n")

    handoff(repo, "fallback-id", open_pr=False)
    assert _commit_subject(repo) == "convertible: fallback-id"


def test_handoff_surfaces_gitignored_output(tmp_path: Path) -> None:
    """Reported changed_files that are gitignored are surfaced, not dropped (#39)."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / ".gitignore").write_text("site/\n")
    (repo / "site").mkdir()
    (repo / "site" / "index.html").write_text("<html></html>\n")
    (repo / "feature.txt").write_text("work\n")

    result = handoff(
        repo,
        "ignored1",
        changed_files=["site/index.html", "feature.txt"],
        open_pr=False,
    )

    assert result.committed is True
    assert "site/index.html" not in _committed_files(repo)
    assert "gitignored" in result.note
    assert "site/index.html" in result.note


def test_handoff_pr_title_is_short_subject(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The PR title is the concise subject, not the full instruction (#40)."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "feature.txt").write_text("work\n")
    long_instruction = "x" * 200

    monkeypatch.setattr(ho, "should_open_pr", lambda repo, open_pr: True)
    captured: dict[str, str] = {}

    def fake_pr(repo: Path, base: str, title: str) -> str:
        captured["title"] = title
        return "https://example.com/pr/1"

    monkeypatch.setattr(ho, "_gh_pr_create", fake_pr)

    real_git = ho._git

    def fake_git(repo: Path, *args: str, check: bool = True):  # type: ignore[no-untyped-def]
        if args and args[0] == "push":
            return subprocess.CompletedProcess(list(args), 0, "", "")
        return real_git(repo, *args, check=check)

    monkeypatch.setattr(ho, "_git", fake_git)

    handoff(repo, "task1", instruction=long_instruction, open_pr=True)

    assert "\n" not in captured["title"]
    assert len(captured["title"]) <= len("convertible: ") + 64
    assert captured["title"].endswith("...")


def test_pushed_but_pr_failed_note_is_not_misleading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Push lands but gh pr create fails: the note must not say 'local commit only' (Qodo #4)."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "feature.txt").write_text("work\n")

    monkeypatch.setattr(ho, "should_open_pr", lambda repo, open_pr: True)

    def boom(repo: Path, base: str, title: str) -> str:
        raise ho.HandoffError("gh exploded")

    monkeypatch.setattr(ho, "_gh_pr_create", boom)

    real_git = ho._git

    def fake_git(repo: Path, *args: str, check: bool = True):  # type: ignore[no-untyped-def]
        if args and args[0] == "push":  # pretend the push succeeded (no real remote)
            return subprocess.CompletedProcess(list(args), 0, "", "")
        return real_git(repo, *args, check=check)

    monkeypatch.setattr(ho, "_git", fake_git)

    result = handoff(repo, "task1", open_pr=True)
    assert result.pushed is True
    assert "PR creation failed" in result.note
    assert "local commit only" not in result.note
