"""The colleague startup banner — decorative chrome on drive/session start (issue #15).

Contract under test: the banner is written to **stderr**, shown **only on an
interactive TTY**, and **suppressed in ``--json`` mode** — in both ``drive`` and
``session``. So it never pollutes the stdout result stream nor the agent-parsed
``error:``/``hint:`` stderr that colleague (an agent harness) emits.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from colleague.cli import main
from colleague.cli._banner import banner, emit_banner


def _force_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the banner think stderr is interactive (capsys/pipes are not)."""
    monkeypatch.setattr("colleague.cli._banner._isatty", lambda: True)


def _art() -> str:
    """The banner as ``emit_banner`` renders it (trailing newlines normalized off)."""
    return banner().rstrip("\n")


class _CollectingOut:
    """Fake output sink that collects all emitted lines (mirrors test_session)."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, *args: object, **kwargs: object) -> None:
        self.lines.append(" ".join(str(a) for a in args))

    def text(self) -> str:
        return "\n".join(self.lines)


def _session_args(tmp_path: Path, *, json_mode: bool) -> argparse.Namespace:
    return argparse.Namespace(
        repo=str(tmp_path),
        engine="mock",
        no_pr=True,
        base="main",
        base_url=None,
        model=None,
        api_key=None,
        max_steps=None,
        json=json_mode,
    )


def _run_session(args: argparse.Namespace) -> tuple[_CollectingOut, _CollectingOut]:
    from colleague.cli._commands.session import run_session

    out, err = _CollectingOut(), _CollectingOut()
    rc = run_session(args, input_fn=iter(["q"]), out=out, err=err)
    assert rc == 0
    return out, err


def test_banner_loads_nonempty_art() -> None:
    """The data file loads and yields the multi-line ASCII art."""
    art = banner()
    assert art.strip(), "banner should not be empty"
    assert art.count("\n") >= 5, "expected a multi-line art block"
    assert banner() is art, "banner() is cached"


def test_drive_banner_on_tty(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _force_tty(monkeypatch)
    rc = main(["drive", "do work", "--repo", str(tmp_path), "--engine", "mock", "--no-pr"])
    assert rc == 0
    captured = capsys.readouterr()
    assert _art() in captured.err, "banner should print to stderr on an interactive drive"
    assert _art() not in captured.out, "banner must never reach the stdout result stream"


def test_drive_no_banner_when_not_a_tty(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Without a TTY (pipes, CI, agents), stderr stays clean for the error rubric."""
    rc = main(["drive", "do work", "--repo", str(tmp_path), "--engine", "mock", "--no-pr"])
    assert rc == 0
    captured = capsys.readouterr()
    assert _art() not in captured.err
    assert _art() not in captured.out


def test_drive_json_suppresses_banner(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _force_tty(monkeypatch)  # even on a TTY, --json suppresses it
    rc = main(
        ["drive", "do work", "--repo", str(tmp_path), "--engine", "mock", "--no-pr", "--json"]
    )
    assert rc == 0
    captured = capsys.readouterr()
    assert _art() not in captured.err, "--json must suppress the banner entirely"
    assert _art() not in captured.out
    assert json.loads(captured.out)["status"] == "ok", "stdout is still pure JSON"


def test_session_banner_on_tty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _force_tty(monkeypatch)
    out, err = _run_session(_session_args(tmp_path, json_mode=False))
    assert _art() in err.text(), "banner should greet the session on stderr"
    assert _art() not in out.text()


def test_session_json_suppresses_banner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _force_tty(monkeypatch)
    out, err = _run_session(_session_args(tmp_path, json_mode=True))
    assert _art() not in err.text(), "--json must suppress the banner in session too"
    assert _art() not in out.text()


def test_drive_and_session_banner_render_identically(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """No trailing-blank-line mismatch between drive (emit_diagnostic) and session (print)."""
    _force_tty(monkeypatch)
    main(["drive", "do work", "--repo", str(tmp_path), "--engine", "mock", "--no-pr"])
    drive_err = capsys.readouterr().err
    # Drive emits the art followed by exactly one newline (no trailing blank line).
    assert _art() + "\n" in drive_err
    assert _art() + "\n\n" not in drive_err


def test_emit_banner_swallows_missing_resource(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing/unreadable resource must never break a drive — the banner is decorative."""
    _force_tty(monkeypatch)

    def _boom() -> str:
        raise FileNotFoundError("_banner.txt")

    monkeypatch.setattr("colleague.cli._banner.banner", _boom)
    emitted: list[str] = []
    emit_banner(emitted.append, json_mode=False)  # must not raise
    assert emitted == [], "no art emitted when the resource is missing"
