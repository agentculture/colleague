"""colleague clean — flight file reaping (t5 + the active-flight guard)."""

import argparse
import os
import time
from pathlib import Path

from colleague import flight
from colleague.cli._commands.clean import cmd_clean


def _backdate(tmp: Path, task_id: str, seconds: float) -> None:
    """Age a flight's files so they look stale (past the active window)."""
    old = time.time() - seconds
    for p in (flight.feed_path(tmp, task_id), flight.control_path(tmp, task_id)):
        if p.exists():
            os.utime(p, (old, old))


def _init_git(tmp: Path) -> None:
    """Real git init so handoff.is_git_repo passes."""
    import subprocess

    subprocess.run(["git", "init", str(tmp)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp), "config", "user.email", "test@test.com"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp), "config", "user.name", "Test"],
        check=True,
        capture_output=True,
    )


def _make_ns(tmp: Path, dry_run: bool = False, json: bool = True):
    return argparse.Namespace(
        repo=str(tmp),
        dry_run=dry_run,
        json=json,
        merged=False,
        older_than=None,
        base="main",
    )


def test_clean_reaps_stale_flights_preserves_active_and_sibling(tmp_path: Path) -> None:
    """Stale flight files are reaped; an ACTIVE (recently-written) flight + a sibling survive."""
    _init_git(tmp_path)

    # a crashed/stale flight (aged past the active window) -> should be reaped
    flight.arm(tmp_path, "stale")
    _backdate(tmp_path, "stale", flight.ACTIVE_WINDOW_SECONDS + 60)
    # a running flight (feed just written) -> must be PRESERVED (Bug 5 guard)
    flight.arm(tmp_path, "active")

    # Sibling file OUTSIDE the flight dir (must survive)
    sibling = tmp_path / ".colleague" / "some_data.txt"
    sibling.parent.mkdir(parents=True, exist_ok=True)
    sibling.write_text("keep me")

    assert cmd_clean(_make_ns(tmp_path, dry_run=False)) == 0

    assert not flight.feed_path(tmp_path, "stale").exists(), "stale flight should be reaped"
    assert flight.feed_path(tmp_path, "active").exists(), "active flight must NOT be reaped"
    assert sibling.exists(), "sibling outside flight dir must survive"


def test_dry_run_preserves_stale_flights(tmp_path: Path) -> None:
    """--dry-run never deletes, even a stale flight that a real clean would reap."""
    _init_git(tmp_path)

    flight.arm(tmp_path, "x")
    _backdate(tmp_path, "x", flight.ACTIVE_WINDOW_SECONDS + 60)  # stale → reapable

    assert cmd_clean(_make_ns(tmp_path, dry_run=True, json=True)) == 0

    assert flight.feed_path(tmp_path, "x").exists(), "dry-run must not delete flight files"
