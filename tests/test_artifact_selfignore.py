"""The bookkeeping dir self-ignores so consumer repos never stage run traces (#322).

``colleague work`` in a repo that never gitignored ``.colleague/`` used to leave
the whole run trace (artifact JSON, step trace, ``last_work``) stageable by a
routine ``git add -A``. Every ``.colleague/`` write choke point now drops an
idempotent self-ignoring ``.gitignore`` (the ``uv``/``.venv`` pattern — git
honors an ignore file that ignores itself), keeping the operator-committable
``commands/`` and ``skills/`` overlays visible.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from colleague import flight
from colleague.artifact import ensure_self_ignored, failed_result, write
from colleague.feedback import set_last_work, write_feedback


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """A git-initialised tmp_path with an initial commit."""
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    (tmp_path / "README.md").write_text("hello\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    return tmp_path


def _status_paths(repo: Path) -> list[str]:
    proc = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain", "-uall"],
        check=True,
        capture_output=True,
        text=True,
    )
    return [line[3:] for line in proc.stdout.splitlines()]


def test_write_drops_self_ignoring_gitignore(tmp_path: Path) -> None:
    out = tmp_path / ".colleague"
    write(failed_result("t1", "boom"), out)
    content = (out / ".gitignore").read_text(encoding="utf-8")
    assert "*" in content.splitlines()
    assert "!commands/" in content.splitlines()
    assert "!skills/" in content.splitlines()


def test_existing_gitignore_is_never_overwritten(tmp_path: Path) -> None:
    out = tmp_path / ".colleague"
    out.mkdir()
    (out / ".gitignore").write_text("# operator-owned\n", encoding="utf-8")
    write(failed_result("t1", "boom"), out)
    assert (out / ".gitignore").read_text(encoding="utf-8") == "# operator-owned\n"


def test_ensure_self_ignored_creates_missing_dir(tmp_path: Path) -> None:
    target = tmp_path / ".colleague"
    ensure_self_ignored(target)
    assert (target / ".gitignore").exists()


def test_consumer_git_status_stays_clean_after_artifact_write(git_repo: Path) -> None:
    write(failed_result("t1", "boom", request="do a thing"), git_repo / ".colleague")
    set_last_work(git_repo, "t1")
    write_feedback(git_repo, "t1", rating=3, notes="n", by="tester")
    assert _status_paths(git_repo) == []


def test_flight_arm_self_ignores(git_repo: Path) -> None:
    flight.arm(git_repo, "t1")
    assert (git_repo / ".colleague" / ".gitignore").exists()
    assert _status_paths(git_repo) == []


def test_committable_overlays_stay_visible(git_repo: Path) -> None:
    write(failed_result("t1", "boom"), git_repo / ".colleague")
    commands = git_repo / ".colleague" / "commands"
    commands.mkdir()
    (commands / "recipe.md").write_text("# recipe\n", encoding="utf-8")
    skills = git_repo / ".colleague" / "skills"
    skills.mkdir()
    (skills / "style.md").write_text("# style\n", encoding="utf-8")
    assert _status_paths(git_repo) == [
        ".colleague/commands/recipe.md",
        ".colleague/skills/style.md",
    ]
