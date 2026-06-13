"""Flight symmetry tests — caller-agnostic piloting and depth-capped nesting."""

import argparse
import subprocess
import sys

import pytest

from colleague import flight
from colleague.cli._commands.flight import (
    cmd_flight_guide,
    cmd_flight_status,
    cmd_flight_stop,
)
from colleague.cli._commands.work import cmd_work
from colleague.cli._errors import CliError


def test_any_caller_can_pilot_via_the_flight_cli(tmp_path, capsys):
    """A NON-Claude caller (e.g. a colleague work-loop) pilots a sub-flight through
    the SAME colleague flight CLI — no Claude-specific code path."""

    # Arm a flight and write a feed entry
    sess = flight.arm(tmp_path, "sub")
    sess.append_feed(step_index=1, tool="edit_file", intent="editing auth", stats={})

    # Caller can WATCH — status output contains the tool name
    ns_status = argparse.Namespace(task_id="sub", repo=str(tmp_path), json=True)
    cmd_flight_status(ns_status)
    output = capsys.readouterr().out
    assert "edit_file" in output

    # Caller can GUIDE
    ns_guide = argparse.Namespace(
        task_id="sub", message="pivot to plan B", repo=str(tmp_path), json=True
    )
    cmd_flight_guide(ns_guide)

    # Caller can STOP
    ns_stop = argparse.Namespace(task_id="sub", repo=str(tmp_path), json=True)
    cmd_flight_stop(ns_stop)

    # Verify the control file reflects both guidance and stop
    ctrl = flight.FlightSession(tmp_path, "sub").read_control()
    assert "pivot to plan B" in ctrl.guidance
    assert ctrl.stop is True


def test_nested_flight_is_depth_capped(tmp_path, monkeypatch):
    """A colleague flight launching a sub-sub-flight is refused before any work
    (fork-bomb guard), mirroring MAX_SUBAGENT_DEPTH check-before-work."""

    # Init a minimal git repo so cmd_work has a valid target
    subprocess.run([sys.executable, "-c", "pass"], cwd=tmp_path)  # ensure cwd exists
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path,
        check=True,
    )
    (tmp_path / "README.md").write_text("hello\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "init"],
        cwd=tmp_path,
        check=True,
    )

    # Already AT the depth cap
    monkeypatch.setenv(flight.DEPTH_ENV, "2")

    ns = argparse.Namespace(
        instruction=["noop"],
        repo=str(tmp_path),
        engine="mock",
        no_pr=True,
        watch=True,
        base=None,
        model=None,
        base_url=None,
        api_key=None,
        max_steps=3,
        json=False,
        command_name=None,
        allow_dirty=True,
        tui=None,
        tui_events=None,
    )

    with pytest.raises(CliError):
        cmd_work(ns)


def test_detached_child_inherits_incremented_depth(monkeypatch):
    """The supported colleague-as-caller pattern: it launches `colleague work --watch`
    DETACHED via run_command (gated by the approval gate) and polls the feed across its
    own turns — it does NOT block. The mechanism that bounds this is the depth env each
    level passes to its child; assert that incrementing chain here."""

    # Depth 0 → child env is 1
    monkeypatch.setenv(flight.DEPTH_ENV, "0")
    assert flight.child_depth_env() == {flight.DEPTH_ENV: "1"}

    # Depth 1 → child env is 2; still under cap
    monkeypatch.setenv(flight.DEPTH_ENV, "1")
    assert flight.child_depth_env() == {flight.DEPTH_ENV: "2"}
    assert flight.depth_exceeded() is False

    # Depth 2 → at cap; grandchild would be refused
    monkeypatch.setenv(flight.DEPTH_ENV, "2")
    assert flight.depth_exceeded() is True
