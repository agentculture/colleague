"""Tests for --attach flag on ``colleague work``."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import pytest

from colleague.cli._commands.work import _build_task
from colleague.cli._errors import CliError
from colleague.config import EngineConfig


def _make_ns(
    tmp_path: Path,
    *,
    instruction: list[str] | None = None,
    attach: list[str] | None = None,
) -> argparse.Namespace:
    """Build an argparse.Namespace with all fields cmd_work reads."""
    return argparse.Namespace(
        instruction=instruction or ["do x"],
        repo=str(tmp_path),
        engine="mock",
        no_pr=True,
        watch=False,
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
        attach=attach or [],
    )


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


class TestAttachTwoFiles:
    """work --attach with two image files produces a Task with both attachments in order."""

    def test_two_attachments_in_order(self, git_repo, tmp_path):
        img1 = tmp_path / "photo1.png"
        img1.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 10)
        img2 = tmp_path / "photo2.png"
        img2.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 10)

        ns = _make_ns(git_repo, attach=[str(img1), str(img2)])
        task = _build_task(ns, git_repo, "mock", None)

        assert task.attachments is not None
        assert len(task.attachments) == 2
        assert task.attachments[0]["path"] == str(img1)
        assert task.attachments[0]["media_type"] == "image/png"
        assert task.attachments[1]["path"] == str(img2)
        assert task.attachments[1]["media_type"] == "image/png"

    def test_attachments_passed_to_task(self, git_repo, tmp_path):
        """Verify the attachments list is actually threaded through Task.new."""
        img = tmp_path / "diagram.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 10)

        ns = _make_ns(git_repo, attach=[str(img)])
        task = _build_task(ns, git_repo, "mock", None)

        assert task.attachments is not None
        assert len(task.attachments) == 1
        assert task.attachments[0]["media_type"] == "image/png"


class TestAttachMissingFile:
    """work --attach missing.png produces a clean error naming the path."""

    def test_missing_file_raises_cli_error(self, git_repo, tmp_path):
        missing = tmp_path / "missing.png"
        ns = _make_ns(git_repo, attach=[str(missing)])

        with pytest.raises(CliError) as exc_info:
            _build_task(ns, git_repo, "mock", None)

        assert exc_info.value.code == 1
        assert "missing.png" in exc_info.value.message or str(missing) in exc_info.value.message


class TestBareWorkNoAttach:
    """Bare work without --attach yields attachments None."""

    def test_no_attach_yields_none(self, git_repo):
        ns = _make_ns(git_repo)
        task = _build_task(ns, git_repo, "mock", None)
        assert task.attachments is None

    def test_empty_attach_list_yields_none(self, git_repo):
        ns = _make_ns(git_repo, attach=[])
        task = _build_task(ns, git_repo, "mock", None)
        assert task.attachments is None


class TestAttachWithCommandTemplate:
    """--attach composes with --command: expand_command has no attachments
    parameter, so the flag is applied to the expanded task post-construction
    (the regression that slipped the first delivery: the kwarg was passed
    unconditionally and every --command run raised TypeError)."""

    def _template_repo(self, git_repo):
        cmd_dir = git_repo / ".colleague" / "commands"
        cmd_dir.mkdir(parents=True, exist_ok=True)
        (cmd_dir / "hello.md").write_text("Say hello to the repo.\n")
        return git_repo

    def test_command_without_attach_builds(self, git_repo):
        self._template_repo(git_repo)
        ns = _make_ns(git_repo, instruction=[])
        ns.command_name = "hello"
        task = _build_task(ns, git_repo, "mock", EngineConfig())
        assert task.attachments is None

    def test_command_with_attach_lands_on_task(self, git_repo, tmp_path):
        self._template_repo(git_repo)
        img = tmp_path / "shot.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 10)
        ns = _make_ns(git_repo, instruction=[])
        ns.command_name = "hello"
        task = _build_task(ns, git_repo, "mock", EngineConfig())
        # ns built without the attach kwarg above so the two cases share a
        # template; re-run with the attachment present.
        ns = _make_ns(git_repo, instruction=[], attach=[str(img)])
        ns.command_name = "hello"
        task = _build_task(ns, git_repo, "mock", EngineConfig())
        assert task.attachments == [{"path": str(img), "media_type": "image/png"}]
