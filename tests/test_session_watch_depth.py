"""Qodo #312 fix — session default-arm must respect the flight depth cap.

PR #312's decision-c18 block default-arms the flight plane in
``_dispatch_work`` when ``task.watch`` was never explicitly set. That default
must degrade to no-watch when the process is already nested inside a flight
past ``flight.DEFAULT_DEPTH_CAP`` (``flight.depth_exceeded()`` is True) —
mirroring ``colleague work``'s ``_arm_watch`` DEFAULTED path (see
``test_watch_default.py`` for the base c18 coverage; this file is the
nesting-safety sibling).
"""

import argparse
import subprocess
from pathlib import Path

from colleague import flight
from colleague.cli._commands.session import run_session
from colleague.cli._commands.work import execute_work


class _Out:
    def __call__(self, *a, **k):
        pass


def _git_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@e.com"], cwd=tmp_path, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.name", "T"], cwd=tmp_path, check=True, capture_output=True
    )
    (tmp_path / "README.md").write_text("hi\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)
    return tmp_path


def _session_args(repo: Path) -> argparse.Namespace:
    return argparse.Namespace(
        repo=str(repo),
        engine="mock",
        no_pr=True,
        base="main",
        base_url=None,
        model=None,
        api_key=None,
        max_steps=None,
        json=False,
        allow_dirty=True,
    )


def _run_session_capturing_watch(repo: Path) -> bool:
    """Run one session dispatch, returning the ``task.watch`` value seen by
    ``work_fn`` (the same ``_capture`` seam used by test_watch_default.py)."""
    seen = {}

    def _capture(*, task, **kw):
        seen["watch"] = task.watch
        return execute_work(
            repo=kw["repo"],
            engine_name=kw["engine_name"],
            task=task,
            open_pr=kw["open_pr"],
            base=kw["base"],
            config=kw["config"],
            allow_dirty=kw.get("allow_dirty", False),
            command_name=kw.get("command_name"),
            tui=kw.get("tui"),
            tui_events=kw.get("tui_events"),
            progress_sink=kw.get("progress_sink"),
            mode=kw.get("mode"),
        )

    rc = run_session(
        _session_args(repo),
        input_fn=iter(["make a small change", "q"]),
        out=_Out(),
        _work_fn=_capture,
    )
    assert rc == 0
    return seen.get("watch")


def test_session_at_flight_depth_cap_does_not_arm_watch(tmp_path, monkeypatch):
    """Qodo #312: a session launched INSIDE a flight already at the depth cap
    must degrade to no-watch, never nest another plane past the cap."""
    repo = _git_repo(tmp_path)
    monkeypatch.setenv(flight.DEPTH_ENV, str(flight.DEFAULT_DEPTH_CAP))
    assert flight.depth_exceeded() is True

    assert _run_session_capturing_watch(repo) is False


def test_session_below_flight_depth_cap_still_default_arms_watch(tmp_path, monkeypatch):
    """Contrast: with no flight-depth env set, the session still default-arms
    the plane (c18 behavior is unchanged outside the nested-depth case)."""
    repo = _git_repo(tmp_path)
    monkeypatch.delenv(flight.DEPTH_ENV, raising=False)
    assert flight.depth_exceeded() is False

    assert _run_session_capturing_watch(repo) is True
