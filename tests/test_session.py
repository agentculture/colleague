"""`convertible session` — interactive palette over the shared drive path (t7/c28/h11).

Tests are written first (TDD) before implementing the feature.  The session loop
is driven through a scripted ``input_fn`` so no real TTY is required.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest

from convertible.cli import main
from convertible.cli._commands.drive import execute_drive
from convertible.cli._commands.session import run_session
from convertible.contract import OK, Task, TaskResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_command_template(repo: Path, name: str, content: str) -> None:
    cmds_dir = repo / ".convertible" / "commands"
    cmds_dir.mkdir(parents=True, exist_ok=True)
    (cmds_dir / f"{name}.md").write_text(content)


def _scripted_input(lines: list[str]) -> Iterator[str]:
    """Yield lines in order; subsequent reads raise StopIteration (treated as quit)."""
    yield from lines


class _CollectingOut:
    """Fake output sink that collects all emitted lines."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, *args: object, **kwargs: object) -> None:
        self.lines.append(" ".join(str(a) for a in args))

    def text(self) -> str:
        return "\n".join(self.lines)


def _make_args(
    tmp_path: Path,
    engine: str = "mock",
    no_pr: bool = True,
    base: str = "main",
) -> "object":
    """Build a minimal Namespace-like args object for run_session."""
    import argparse

    ns = argparse.Namespace(
        repo=str(tmp_path),
        engine=engine,
        no_pr=no_pr,
        base=base,
        base_url=None,
        model=None,
        api_key=None,
        max_steps=None,
        json=False,
    )
    return ns


# ---------------------------------------------------------------------------
# Test 1: listing the palette and quitting with "q"
# ---------------------------------------------------------------------------


def test_session_quit_exits_zero(tmp_path: Path) -> None:
    """Sending 'q' immediately exits with code 0 without driving anything."""
    _make_command_template(tmp_path, "setup", "Set up the project.\n")
    args = _make_args(tmp_path)
    out = _CollectingOut()
    rc = run_session(args, input_fn=iter(["q"]), out=out)
    assert rc == 0


def test_session_quit_empty_line_exits_zero(tmp_path: Path) -> None:
    """An empty line also acts as a quit token."""
    args = _make_args(tmp_path)
    out = _CollectingOut()
    rc = run_session(args, input_fn=iter([""]), out=out)
    assert rc == 0


def test_session_lists_discovered_commands(tmp_path: Path) -> None:
    """The palette renders a numbered list of discovered command templates."""
    _make_command_template(tmp_path, "lint", "---\ndescription: Fix lint errors\n---\nFix lint.\n")
    _make_command_template(tmp_path, "setup", "Set up the project.\n")
    args = _make_args(tmp_path)
    out = _CollectingOut()
    run_session(args, input_fn=iter(["q"]), out=out)
    rendered = out.text()
    # Both commands must appear in the palette output
    assert "lint" in rendered
    assert "setup" in rendered


def test_session_shows_adhoc_option(tmp_path: Path) -> None:
    """The palette always shows a free-text / ad-hoc option."""
    args = _make_args(tmp_path)
    out = _CollectingOut()
    run_session(args, input_fn=iter(["q"]), out=out)
    rendered = out.text()
    # Some indication that free text is accepted
    assert any(kw in rendered.lower() for kw in ("free", "ad-hoc", "adhoc", "instruction", "type"))


# ---------------------------------------------------------------------------
# Test 2: selecting a command by number runs it through the drive path
# ---------------------------------------------------------------------------


def test_session_select_command_by_number_runs_drive(tmp_path: Path) -> None:
    """Selecting a command template by its palette number drives it and prints a result."""
    _make_command_template(tmp_path, "setup", "Set up the project.\n")
    args = _make_args(tmp_path)
    out = _CollectingOut()
    # "1" selects the first command in the list (no args needed for this template)
    rc = run_session(args, input_fn=iter(["1", "q"]), out=out)
    assert rc == 0
    rendered = out.text()
    # The result summary must appear
    assert any(kw in rendered.lower() for kw in ("status", "ok", "summary", "task"))


def test_session_select_command_by_name_runs_drive(tmp_path: Path) -> None:
    """Selecting a command template by name also drives it."""
    _make_command_template(tmp_path, "setup", "Set up the project.\n")
    args = _make_args(tmp_path)
    out = _CollectingOut()
    rc = run_session(args, input_fn=iter(["setup", "q"]), out=out)
    assert rc == 0
    rendered = out.text()
    assert any(kw in rendered.lower() for kw in ("status", "ok", "summary", "task"))


# ---------------------------------------------------------------------------
# Test 3: ad-hoc instruction drives through the drive path
# ---------------------------------------------------------------------------


def test_session_adhoc_instruction_drives(tmp_path: Path) -> None:
    """Typing a free-text instruction drives it as an ad-hoc task."""
    args = _make_args(tmp_path)
    out = _CollectingOut()
    rc = run_session(args, input_fn=iter(["add a CONTRIBUTING.md file", "q"]), out=out)
    assert rc == 0
    rendered = out.text()
    assert any(kw in rendered.lower() for kw in ("status", "ok", "summary", "task"))


# ---------------------------------------------------------------------------
# Test 4: task result shape parity between session and drive (h11)
# ---------------------------------------------------------------------------


def test_session_and_drive_yield_same_result_shape(tmp_path: Path) -> None:
    """h11: driving a command via the palette and via drive --command yields identical shape.

    The task ids differ (each drive generates a fresh id) but the structural
    fields (status, changed_files shape, steps shape) must be identical.
    """
    _make_command_template(tmp_path, "setup", "Set up the project.\n")

    # --- Drive path via execute_drive (the shared helper used by both) ---
    from convertible.commands import expand_command
    from convertible.config import EngineConfig

    task_via_drive = expand_command(tmp_path, "setup", [], engine_default="mock")
    config = EngineConfig.resolve()

    result_drive, _ = execute_drive(
        repo=tmp_path,
        engine_name="mock",
        task=task_via_drive,
        open_pr=False,
        base="main",
        config=config,
    )

    # --- Drive path via the session (scripted) ---
    args = _make_args(tmp_path)
    captured_results: list[TaskResult] = []

    def _capturing_drive(
        *,
        repo: Path,
        engine_name: str,
        task: Task,
        open_pr: bool,
        base: str,
        config: EngineConfig,
        command_name: str | None = None,
        tui: bool | None = None,
        tui_events: str | None = None,
    ) -> tuple[TaskResult, Path]:
        result, art_path = execute_drive(
            repo=repo,
            engine_name=engine_name,
            task=task,
            open_pr=open_pr,
            base=base,
            config=config,
            command_name=command_name,
            tui=tui,
            tui_events=tui_events,
        )
        captured_results.append(result)
        return result, art_path

    out = _CollectingOut()
    rc = run_session(args, input_fn=iter(["setup", "q"]), out=out, _drive_fn=_capturing_drive)
    assert rc == 0
    assert len(captured_results) == 1
    result_session = captured_results[0]

    # Field-by-field shape parity (ids differ)
    assert result_session.status == result_drive.status
    assert isinstance(result_session.changed_files, list)
    assert isinstance(result_drive.changed_files, list)
    assert isinstance(result_session.steps, list)
    assert isinstance(result_drive.steps, list)
    # Both must carry the same top-level keys
    drive_keys = set(result_drive.to_dict().keys())
    session_keys = set(result_session.to_dict().keys())
    assert session_keys == drive_keys


# ---------------------------------------------------------------------------
# Test 5: multiple iterations — the loop continues after a successful drive
# ---------------------------------------------------------------------------


def test_session_loops_multiple_iterations(tmp_path: Path) -> None:
    """The session loop continues after a successful drive until quit is received."""
    _make_command_template(tmp_path, "setup", "Set up the project.\n")
    args = _make_args(tmp_path)
    out = _CollectingOut()
    # Drive twice (by name), then quit
    rc = run_session(args, input_fn=iter(["setup", "setup", "q"]), out=out)
    assert rc == 0
    # At least two result summaries should have been emitted
    rendered = out.text()
    # "status" should appear at least twice
    assert rendered.lower().count("status") >= 2


# ---------------------------------------------------------------------------
# Test 6: execute_drive is importable and returns the right types
# ---------------------------------------------------------------------------


def test_execute_drive_returns_taskresult_and_path(tmp_path: Path) -> None:
    """execute_drive returns (TaskResult, Path) with the expected types."""
    from convertible.config import EngineConfig

    task = Task.new(str(tmp_path), "set up the repo", engine="mock")
    config = EngineConfig.resolve()
    result, art_path = execute_drive(
        repo=tmp_path,
        engine_name="mock",
        task=task,
        open_pr=False,
        base="main",
        config=config,
    )
    assert isinstance(result, TaskResult)
    assert isinstance(art_path, Path)
    assert result.status == OK


# ---------------------------------------------------------------------------
# Test 7: CLI wiring — `convertible session --help` exits 0 and mentions flags
# ---------------------------------------------------------------------------


def test_session_cli_help(capsys: pytest.CaptureFixture[str]) -> None:
    """convertible session --help exits 0 and mentions expected flags."""
    with pytest.raises(SystemExit) as exc_info:
        main(["session", "--help"])
    out = capsys.readouterr().out
    assert exc_info.value.code == 0
    assert "--engine" in out
    assert "--repo" in out
    # Session no longer auto-PRs per line (#53): handoff is opt-in via --pr.
    assert "--pr" in out
    assert "--no-pr" not in out


# ---------------------------------------------------------------------------
# Test 8: StopIteration / EOF on input_fn is treated as quit (graceful)
# ---------------------------------------------------------------------------


def test_session_eof_exits_gracefully(tmp_path: Path) -> None:
    """When input_fn is exhausted (EOF), the session exits with code 0."""
    args = _make_args(tmp_path)
    out = _CollectingOut()
    # An empty iterator immediately raises StopIteration
    rc = run_session(args, input_fn=iter([]), out=out)
    assert rc == 0
