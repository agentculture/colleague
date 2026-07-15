"""Tests for the --watch flag on ``colleague work``."""

import argparse
import subprocess
from pathlib import Path

import pytest

from colleague import flight
from colleague.cli._commands.work import cmd_work
from colleague.cli._errors import CliError


def _make_ns(tmp_path: Path, *, watch: bool = False, no_watch: bool = False) -> argparse.Namespace:
    """Build an argparse.Namespace with all fields cmd_work reads."""
    return argparse.Namespace(
        instruction=["do x"],
        repo=str(tmp_path),
        engine="mock",
        no_pr=True,
        watch=watch,
        no_watch=no_watch,
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


def test_watch_emits_flight_handle(git_repo, capsys):
    """With --watch, the flight attach handle is emitted to STDERR."""
    ns = _make_ns(git_repo, watch=True)
    cmd_work(ns)
    captured = capsys.readouterr()
    assert "flight:" in captured.err
    first = flight.feed_path(git_repo, "placeholder")
    second = flight.feed_path(git_repo, "placeholder")
    assert first == second  # sanity: feed_path is callable and deterministic
    # The actual task id is dynamic, so check the feed path pattern exists
    assert "feed:" in captured.err
    assert "control:" in captured.err


def test_default_arms_the_flight_plane(git_repo, capsys):
    """#307: a plain `colleague work` (no --watch, no --no-watch) arms the plane by
    default — the flip from opt-in to opt-out."""
    ns = _make_ns(git_repo)  # neither flag
    cmd_work(ns)
    captured = capsys.readouterr()
    assert "flight:" in captured.err
    assert flight.flight_dir(git_repo).exists()


def test_no_watch_opts_out(git_repo, capsys):
    """#307: --no-watch is the opt-out — no flight handle, no flight dir."""
    ns = _make_ns(git_repo, no_watch=True)
    cmd_work(ns)
    captured = capsys.readouterr()
    assert "flight:" not in captured.err
    assert not flight.flight_dir(git_repo).exists()


def test_env_opt_out_disarms_the_default(git_repo, capsys, monkeypatch):
    """#307: COLLEAGUE_WATCH=0 disarms the default (resolved onto config.watch)."""
    monkeypatch.setenv("COLLEAGUE_WATCH", "0")
    ns = _make_ns(git_repo)  # neither flag → falls to config.watch (env says off)
    cmd_work(ns)
    captured = capsys.readouterr()
    assert "flight:" not in captured.err
    assert not flight.flight_dir(git_repo).exists()


def test_watch_depth_cap_raises(git_repo, monkeypatch):
    """With COLLEAGUE_FLIGHT_DEPTH=2, an EXPLICIT --watch raises CliError."""
    monkeypatch.setenv(flight.DEPTH_ENV, "2")
    ns = _make_ns(git_repo, watch=True)
    with pytest.raises(CliError) as exc_info:
        cmd_work(ns)
    assert exc_info.value.code == 1
    assert "depth cap" in exc_info.value.message


def test_default_watch_at_depth_degrades_silently(git_repo, monkeypatch):
    """#307: default-on watch must NEVER break a nested run — at the depth cap it
    degrades to no-watch silently (only an EXPLICIT --watch at depth is an error)."""
    monkeypatch.setenv(flight.DEPTH_ENV, "2")
    ns = _make_ns(git_repo)  # neither flag → defaulted-on watch
    # No raise: the run completes, just without arming a (nesting-forbidden) plane.
    cmd_work(ns)
    assert not flight.flight_dir(git_repo).exists()
