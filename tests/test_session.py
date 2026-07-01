"""`colleague session` — interactive palette over the shared drive path (t7/c28/h11).

Tests are written first (TDD) before implementing the feature.  The session loop
is driven through a scripted ``input_fn`` so no real TTY is required.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Iterator

import pytest

from colleague.cli import main
from colleague.cli._commands.session import run_session
from colleague.cli._commands.work import execute_work
from colleague.contract import OK, Task, TaskResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_command_template(repo: Path, name: str, content: str) -> None:
    cmds_dir = repo / ".colleague" / "commands"
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
    allow_dirty: bool = False,
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
        allow_dirty=allow_dirty,
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

    # --- Drive path via execute_work (the shared helper used by both) ---
    from colleague.commands import expand_command
    from colleague.config import EngineConfig

    task_via_drive = expand_command(tmp_path, "setup", [], engine_default="mock")
    config = EngineConfig.resolve()

    result_drive, _ = execute_work(
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
        allow_dirty: bool = False,
        command_name: str | None = None,
        tui: bool | None = None,
        tui_events: str | None = None,
        progress_sink: object = None,
        mode: str | None = None,
    ) -> tuple[TaskResult, Path]:
        result, art_path = execute_work(
            repo=repo,
            engine_name=engine_name,
            task=task,
            open_pr=open_pr,
            base=base,
            config=config,
            allow_dirty=allow_dirty,
            command_name=command_name,
            tui=tui,
            tui_events=tui_events,
            progress_sink=progress_sink,
            mode=mode,
        )
        captured_results.append(result)
        return result, art_path

    out = _CollectingOut()
    rc = run_session(args, input_fn=iter(["setup", "q"]), out=out, _work_fn=_capturing_drive)
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
# Test 6: execute_work is importable and returns the right types
# ---------------------------------------------------------------------------


def test_execute_work_returns_taskresult_and_path(tmp_path: Path) -> None:
    """execute_work returns (TaskResult, Path) with the expected types."""
    from colleague.config import EngineConfig

    task = Task.new(str(tmp_path), "set up the repo", engine="mock")
    config = EngineConfig.resolve()
    result, art_path = execute_work(
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
# Test 7: CLI wiring — `colleague session --help` exits 0 and mentions flags
# ---------------------------------------------------------------------------


def test_session_cli_help(capsys: pytest.CaptureFixture[str]) -> None:
    """colleague session --help exits 0 and mentions expected flags.

    The rendered CLI (agentfront ``run_cli``) RETURNS 0 for a verb's ``--help``
    rather than raising ``SystemExit`` (argparse's internal exit is caught and
    translated). The shell exit code is identical via ``__main__``'s
    ``sys.exit(main())`` — exit-code-equivalent, not a regression.
    """
    rc = main(["session", "--help"])
    out = capsys.readouterr().out
    assert rc == 0
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


# ---------------------------------------------------------------------------
# #74 A2 — the cockpit session: 3 render tiers + slash commands
# ---------------------------------------------------------------------------


def _ok_drive(tmp_path: Path, recorder: list | None = None):
    """A fake drive that succeeds (recording its kwargs when *recorder* given)."""

    def _fake(**kwargs: object) -> tuple[TaskResult, Path]:
        if recorder is not None:
            recorder.append(kwargs)
        return TaskResult(task_id="x", status=OK, summary="done"), tmp_path / "art.json"

    return _fake


def test_session_markdown_tier_is_the_non_tty_default(tmp_path: Path) -> None:
    """Off a colour TTY the cockpit renders as Markdown menus (the full static
    experience) — command names + the 'colleague session' identity, no escapes."""
    _make_command_template(tmp_path, "setup", "Set up the project.\n")
    out = _CollectingOut()
    rc = run_session(_make_args(tmp_path), input_fn=iter(["q"]), out=out, _color=False)
    assert rc == 0
    text = out.text()
    assert "# colleague" in text  # the Markdown view (header title from Header(title="colleague"))
    assert "colleague session" in text  # identity (status bar)
    assert "setup" in text  # the command palette lists templates
    assert "\x1b" not in text  # static Markdown carries no ANSI escapes


def test_session_ansi_tier_redraws_in_place_on_a_colour_tty(tmp_path: Path) -> None:
    """With colour forced on, the cockpit is the dynamic ANSI frame: one
    clear-home per render, the Work-templates section, and the identity."""
    _make_command_template(tmp_path, "setup", "Set up the project.\n")
    out = _CollectingOut()
    rc = run_session(_make_args(tmp_path), input_fn=iter(["q"]), out=out, _color=True)
    assert rc == 0
    text = out.text()
    assert "\x1b[H\x1b[2J" in text  # clear-home → redraw in place
    assert "Work templates" in text and "setup" in text
    # Each emitted frame carries exactly one clear-home — one render regime, no
    # double-clear/flicker from the palette and an in-drive sink fighting.
    for frame in out.lines:
        assert frame.count("\x1b[H\x1b[2J") == 1


def test_session_slash_help_lists_commands(tmp_path: Path) -> None:
    out = _CollectingOut()
    rc = run_session(_make_args(tmp_path), input_fn=iter(["/help", "q"]), out=out, _color=False)
    assert rc == 0
    assert "slash commands" in out.text()
    assert "/engine" in out.text() and "/skills" in out.text()


def test_session_slash_engines_folds_backends_output(tmp_path: Path) -> None:
    """A read-only slash command runs the real noun in-process and folds its
    output into the cockpit (here `/engines` → `backends list`)."""
    out = _CollectingOut()
    rc = run_session(_make_args(tmp_path), input_fn=iter(["/engines", "q"]), out=out, _color=False)
    assert rc == 0
    assert "mock" in out.text()  # the mock wheel is always discovered


@pytest.mark.parametrize(
    "verb", ["commands", "skills", "agents", "config", "engines", "telemetry", "feedback"]
)
def test_session_introspection_slash_runs_without_crashing(tmp_path: Path, verb: str) -> None:
    """Every introspection slash command runs its noun in-process and folds output
    into the cockpit — proving each fixed argv mapping parses (no SystemExit) and
    no noun crashes the session even in a bare repo."""
    out = _CollectingOut()
    rc = run_session(_make_args(tmp_path), input_fn=iter([f"/{verb}", "q"]), out=out, _color=False)
    assert rc == 0  # a bad argv would SystemExit and never return cleanly
    assert out.text().strip()  # something was folded into the cockpit


def test_session_slash_engine_switches_for_next_drive(tmp_path: Path) -> None:
    """/engine <name> mutates the session so the NEXT drive uses the new engine."""
    calls: list = []
    args = _make_args(tmp_path, engine="vllm-openai")  # start on a different engine
    out = _CollectingOut()
    rc = run_session(
        args,
        input_fn=iter(["/engine mock", "do a thing", "q"]),
        out=out,
        _work_fn=_ok_drive(tmp_path, calls),
        _color=False,
    )
    assert rc == 0
    assert [c["engine_name"] for c in calls] == ["mock"]  # drove with the switched engine
    assert "engine → mock" in out.text()


def test_session_slash_engine_rejects_unknown(tmp_path: Path) -> None:
    """An unknown engine is rejected (to stderr) and does not change the session."""
    calls: list = []
    err = _CollectingOut()
    rc = run_session(
        _make_args(tmp_path),
        input_fn=iter(["/engine nope", "do a thing", "q"]),
        out=_CollectingOut(),
        err=err,
        _work_fn=_ok_drive(tmp_path, calls),
        _color=False,
    )
    assert rc == 0
    assert "unknown engine 'nope'" in err.text()
    assert [c["engine_name"] for c in calls] == ["mock"]  # still the default, not 'nope'


def test_session_slash_pr_toggles_handoff(tmp_path: Path) -> None:
    """/pr flips push+PR for subsequent drives."""
    calls: list = []
    out = _CollectingOut()
    rc = run_session(
        _make_args(tmp_path),
        input_fn=iter(["do one", "/pr", "do two", "q"]),
        out=out,
        _work_fn=_ok_drive(tmp_path, calls),
        _color=False,
    )
    assert rc == 0
    assert [c["open_pr"] for c in calls] == [False, True]  # off, then on after /pr


def test_session_forwards_allow_dirty_to_work(tmp_path: Path) -> None:
    """--allow-dirty threads through the session to the shared work path (#149)."""
    calls: list = []
    rc = run_session(
        _make_args(tmp_path, allow_dirty=True),
        input_fn=iter(["do a thing", "q"]),
        out=_CollectingOut(),
        _work_fn=_ok_drive(tmp_path, calls),
        _color=False,
    )
    assert rc == 0
    assert [c["allow_dirty"] for c in calls] == [True]


def test_session_defaults_allow_dirty_false(tmp_path: Path) -> None:
    """Without --allow-dirty the session asks the shared work path to guard (#149)."""
    calls: list = []
    rc = run_session(
        _make_args(tmp_path),
        input_fn=iter(["do a thing", "q"]),
        out=_CollectingOut(),
        _work_fn=_ok_drive(tmp_path, calls),
        _color=False,
    )
    assert rc == 0
    assert [c["allow_dirty"] for c in calls] == [False]


def test_session_refuses_dirty_tracked_tree_end_to_end(tmp_path: Path) -> None:
    """The real shared work path refuses a dirty tracked tree in-session (#149).

    Proves session inherits the runtime guard (not just the fake seam): the
    CliError surfaces via _run_work as a stderr `error:` line, the loop keeps
    going, and no work branch is created.
    """
    for cmd in (
        ["init", "-q"],
        ["config", "user.email", "t@e.com"],
        ["config", "user.name", "T"],
    ):
        subprocess.run(["git", *cmd], cwd=str(tmp_path), check=True, capture_output=True)
    (tmp_path / "f.txt").write_text("committed\n")
    subprocess.run(["git", "add", "-A"], cwd=str(tmp_path), check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "init"], cwd=str(tmp_path), check=True, capture_output=True
    )
    (tmp_path / "f.txt").write_text("in-progress edit\n")  # dirty TRACKED

    err = _CollectingOut()
    rc = run_session(  # real default work_fn (execute_work)
        _make_args(tmp_path),
        input_fn=iter(["do a thing", "q"]),
        out=_CollectingOut(),
        err=err,
        _color=False,
    )
    assert rc == 0  # the session loop exits cleanly even though the item was refused
    assert "uncommitted changes" in err.text()
    branches = subprocess.run(
        ["git", "branch", "--list", "colleague/*"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert branches.strip() == ""  # nothing committed
    assert (tmp_path / "f.txt").read_text() == "in-progress edit\n"  # edit survives


def test_session_failed_step_surfaces_error_popup(tmp_path: Path) -> None:
    """A failed drive step folds the error popup into the session's cockpit
    (the in-session sink shares the session's state); visible in the ANSI frame."""

    def _failing(**kwargs: object) -> tuple[TaskResult, Path]:
        sink = kwargs["progress_sink"]
        sink(0, "run_command", "pytest -q", False)  # a failed step
        sink.close()
        return TaskResult(task_id="x", status=OK, summary="done"), tmp_path / "art.json"

    out = _CollectingOut()
    rc = run_session(
        _make_args(tmp_path),
        input_fn=iter(["run the tests", "q"]),
        out=out,
        _work_fn=_failing,
        _color=True,
    )
    assert rc == 0
    assert "popup.work-error" in out.text()  # agentfront popup id for a failed work step


def test_session_work_sink_skips_phase_events() -> None:
    """The in-session progress sink ignores empty-tool phase notices (#206) so the
    session cockpit never folds a phantom step — matching the cockpit + events sinks
    in _tui_sink.py (Qodo: the session sink was the one progress consumer left out)."""
    import dataclasses
    from types import SimpleNamespace

    from agentfront.taui.state import TAUIState as CockpitState
    from agentfront.taui.state import WorkItem

    from colleague.cli._commands.session import _WorkSink

    # TAUIState is frozen=True — use dataclasses.replace to set work_item.
    state = CockpitState()
    state = dataclasses.replace(
        state, work_item=WorkItem(task_id="t", engine="mock", step_count=0, running=True)
    )
    sess = SimpleNamespace(state=state, view="markdown")  # not "ansi" → no live redraw
    sink = _WorkSink(sess)

    sink(0, "read_file", "a.py", True)  # a real step advances the count
    assert sess.state.work_item.step_count == 1
    sink(1, "", "synthesizing the final answer…", True)  # a phase notice — must be skipped
    assert sess.state.work_item.step_count == 1  # the phantom step was NOT folded


def test_session_unknown_slash_is_a_stderr_error(tmp_path: Path) -> None:
    err = _CollectingOut()
    rc = run_session(
        _make_args(tmp_path),
        input_fn=iter(["/frobnicate", "q"]),
        out=_CollectingOut(),
        err=err,
        _color=False,
    )
    assert rc == 0
    assert "unknown command: /frobnicate" in err.text()
