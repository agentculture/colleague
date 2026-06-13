"""Tests for the --watch flag on ``colleague work``."""

import argparse
import subprocess
from pathlib import Path

import pytest

from colleague.cli._commands.work import cmd_work
from colleague.cli._errors import CliError
from colleague import flight


def _make_ns(tmp_path: Path, *, watch: bool = False) -> argparse.Namespace:
    """Build an argparse.Namespace with all fields cmd_work reads."""
    return argparse.Namespace(
        instruction=["do x"],
        repo=str(tmp_path),
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


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """A git-initialised tmp_path with an initial commit."""
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
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


def test_watch_emits_flight_handle(git_repo, capsys):
    """With --watch, the flight attach handle is emitted to STDERR."""
    ns = _make_ns(git_repo, watch=True)
    cmd_work(ns)
    captured = capsys.readouterr()
    assert "flight:" in captured.err
    assert str(flight.feed_path(git_repo, "placeholder")) == str(
        flight.feed_path(git_repo, "placeholder")
    )  # sanity: feed_path is callable
    # The actual task id is dynamic, so check the feed path pattern exists
    assert "feed:" in captured.err
    assert "control:" in captured.err


def test_no_watch_is_strict_noop(git_repo, capsys):
    """Without --watch, no flight handle is emitted and flight dir does not exist."""
    ns = _make_ns(git_repo, watch=False)
    cmd_work(ns)
    captured = capsys.readouterr()
    assert "flight:" not in captured.err
    assert not flight.flight_dir(git_repo).exists()


def test_watch_depth_cap_raises(git_repo, monkeypatch):
    """With COLLEAGUE_FLIGHT_DEPTH=2, --watch raises CliError."""
    monkeypatch.setenv(flight.DEPTH_ENV, "2")
    ns = _make_ns(git_repo, watch=True)
    with pytest.raises(CliError) as exc_info:
        cmd_work(ns)
    assert exc_info.value.code == 1
    assert "depth cap" in exc_info.value.message
