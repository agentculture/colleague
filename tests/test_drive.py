"""`colleague drive` — the headline verb wires engine->loop->artifact->handoff (c4)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from colleague import registry
from colleague.cli import main
from colleague.config import EngineConfig
from colleague.contract import Task, TaskResult
from colleague.engine import Engine
from colleague.engines.mock import OUTPUT_FILE
from colleague.loop import ModelResponse, ToolCall, run


class _CommandEngine(Engine):
    """Engine that edits the repo only via run_command (no write_file tracking)."""

    name = "cmd"

    def drive(self, task: Task, config: EngineConfig) -> TaskResult:
        turns = [
            ModelResponse(
                tool_calls=[ToolCall("1", "run_command", {"command": "echo hi > made_by_cmd.txt"})]
            ),
            ModelResponse(tool_calls=[ToolCall("2", "finish", {"summary": "ran a command"})]),
        ]
        state = {"i": 0}

        def complete(_m: list[dict]) -> ModelResponse:
            turn = turns[min(state["i"], len(turns) - 1)]
            state["i"] += 1
            return turn

        return run(complete, task, max_steps=config.max_steps)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True)


def test_drive_mock_writes_artifact_and_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["drive", "set up the repo", "--repo", str(tmp_path), "--engine", "mock", "--no-pr"])
    assert rc == 0
    assert (tmp_path / OUTPUT_FILE).exists()
    artifacts = list((tmp_path / ".colleague").glob("*.json"))
    assert len(artifacts) == 1
    payload = json.loads(artifacts[0].read_text())
    assert payload["status"] == "ok"
    assert OUTPUT_FILE in payload["changed_files"]


def test_drive_json_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(
        ["drive", "do work", "--repo", str(tmp_path), "--engine", "mock", "--no-pr", "--json"]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert payload["pr_url"] is None


def test_drive_text_output_includes_grade_hint(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Every completed drive nudges toward the ROI loop: the result block carries a
    # copy-paste `grade:` line pointing at the native feedback verb (#144).
    rc = main(["drive", "do work", "--repo", str(tmp_path), "--engine", "mock", "--no-pr"])
    assert rc == 0
    out = capsys.readouterr().out
    artifacts = list((tmp_path / ".colleague").glob("*.json"))
    task_id = json.loads(artifacts[0].read_text())["task_id"]
    assert f"grade: colleague feedback record {task_id} --rating <1-5>" in out


def test_drive_json_output_excludes_grade_hint(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The hint is a human nudge — it must never leak into machine (`--json`) output.
    rc = main(
        ["drive", "do work", "--repo", str(tmp_path), "--engine", "mock", "--no-pr", "--json"]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "grade:" not in out
    json.loads(out)  # still clean, parseable JSON


def test_drive_in_git_repo_creates_branch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@e.com")
    _git(tmp_path, "config", "user.name", "T")
    (tmp_path / "seed").write_text("x")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "init")

    rc = main(
        ["drive", "add a file", "--repo", str(tmp_path), "--engine", "mock", "--no-pr", "--json"]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["branch"].startswith("colleague/")
    assert payload["pr_url"] is None  # --no-pr never pushes


def test_drive_hands_off_run_command_edits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Edits via run_command (changed_files empty) must still be committed (Qodo #2)."""
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@e.com")
    _git(tmp_path, "config", "user.name", "T")
    (tmp_path / "seed").write_text("x")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "init")

    monkeypatch.setattr(registry, "load", lambda name: _CommandEngine())

    rc = main(
        [
            "drive",
            "make a file via cmd",
            "--repo",
            str(tmp_path),
            "--engine",
            "cmd",
            "--no-pr",
            "--json",
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["branch"].startswith("colleague/")  # handoff ran despite no write_file
    # C2: the work lands on the drive branch and the operator is returned to their
    # original branch, so the output lives on that branch, not the work tree.
    committed = subprocess.run(
        ["git", "show", "--name-only", "--format=", payload["branch"]],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "made_by_cmd.txt" in committed
    assert "made_by_cmd.txt" in payload["changed_files"]  # backfilled from git status


class _FlakyEngine(Engine):
    """Engine that writes one file then raises mid-loop (a per-request timeout)."""

    name = "flaky"

    def drive(self, task: Task, config: EngineConfig) -> TaskResult:
        first = ModelResponse(
            tool_calls=[ToolCall("1", "write_file", {"path": "partial.txt", "content": "wip"})]
        )
        state = {"i": 0}

        def complete(_m: list[dict]) -> ModelResponse:
            if state["i"] > 0:
                raise TimeoutError("timed out")
            state["i"] += 1
            return first

        return run(complete, task, max_steps=config.max_steps, progress=config.progress)


def test_drive_preserves_partial_artifact_on_engine_raise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A drive that raises mid-loop still writes steps/usage/changed_files + trace (#37)."""
    monkeypatch.setattr(registry, "load", lambda name: _FlakyEngine())

    rc = main(
        ["drive", "write then time out", "--repo", str(tmp_path), "--engine", "flaky", "--no-pr"]
    )
    assert rc == 2  # EXIT_ENV_ERROR — the failure is still surfaced

    artifacts = list((tmp_path / ".colleague").glob("*.json"))
    assert len(artifacts) == 1
    payload = json.loads(artifacts[0].read_text())
    assert payload["status"] == "error"
    assert "TimeoutError" in payload["error"]
    # Partial work is preserved (this is the bug #37 fixes — was [] / 0 before).
    assert payload["changed_files"] == ["partial.txt"]
    assert len(payload["steps"]) == 1
    assert (tmp_path / "partial.txt").read_text() == "wip"

    # The trace is derived from steps -> non-empty (was 0 bytes before).
    trace = artifacts[0].with_name(artifacts[0].stem + ".trace.jsonl")
    assert trace.exists()
    trace_lines = [ln for ln in trace.read_text().splitlines() if ln.strip()]
    assert len(trace_lines) == 1

    err = capsys.readouterr().err
    assert "error:" in err
    assert "flaky" in err
    assert "partial trace" in err  # the hint reflects that a partial trace was written


class _BrokenEngine(Engine):
    """Engine that fails before producing any partial result (e.g. a setup error)."""

    name = "broken"

    def drive(self, task: Task, config: EngineConfig) -> TaskResult:
        raise RuntimeError("kaboom before the loop")


def test_drive_no_partial_hint_omits_partial_trace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A failure with no partial result must not claim a partial trace was written (Qodo)."""
    monkeypatch.setattr(registry, "load", lambda name: _BrokenEngine())

    rc = main(
        ["drive", "refactor the parser", "--repo", str(tmp_path), "--engine", "broken", "--no-pr"]
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "a result artifact was still written" in err
    assert "partial trace" not in err  # there is no partial trace on this path

    artifacts = list((tmp_path / ".colleague").glob("*.json"))
    payload = json.loads(artifacts[0].read_text())
    assert payload["status"] == "error"
    assert payload["steps"] == []  # fresh failed_result, no accumulated steps
    # #139 (qodo): the early-failure artifact still carries the request, so it is
    # discoverable-by-request and sortable in `feedback list` (not a blank row).
    assert payload["stats"]["request"] == "refactor the parser"
    assert payload["stats"]["started_at"]
    assert artifacts[0].name == f"{payload['task_id']}.refactor-the-parser.json"  # slugged
    from colleague.feedback import list_drives

    rows = list_drives(tmp_path)
    assert len(rows) == 1 and rows[0].request == "refactor the parser" and rows[0].status == "error"


def test_drive_emits_step_progress_to_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A drive reports per-step progress on stderr while stdout stays clean JSON (#38)."""
    rc = main(
        [
            "drive",
            "set up the repo",
            "--repo",
            str(tmp_path),
            "--engine",
            "mock",
            "--no-pr",
            "--json",
        ]
    )
    assert rc == 0
    captured = capsys.readouterr()
    # stdout is still the single parseable JSON result.
    payload = json.loads(captured.out)
    assert payload["status"] == "ok"
    # stderr carries a progress line per step.
    assert "step 0:" in captured.err
    assert "[ok]" in captured.err


def test_drive_default_step_line_is_exact(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Lock the default (no-TUI) progress line byte-for-byte (#74 A1): the live
    cockpit must never perturb the plain stderr format agents/CI parse. capsys is
    not a TTY, so the default path is what runs even without --no-tui."""
    rc = main(
        ["drive", "set up", "--repo", str(tmp_path), "--engine", "mock", "--no-pr", "--no-tui"]
    )
    assert rc == 0
    err = capsys.readouterr().err
    assert "step 0: write_file colleague-mock.md [ok]" in err
    assert "\x1b" not in err  # no cockpit escapes on the default path


def test_drive_tui_renders_cockpit_not_step_lines(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """--tui forces the live cockpit even off a TTY (#74 A1): stderr shows the
    cockpit conversation, not the plain `step N:` lines; stdout stays clean JSON."""
    rc = main(
        [
            "drive",
            "set up",
            "--repo",
            str(tmp_path),
            "--engine",
            "mock",
            "--no-pr",
            "--tui",
            "--json",
        ]
    )
    assert rc == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["status"] == "ok"  # stdout still parseable
    assert "Conversation" in captured.err and "write_file" in captured.err
    assert "step 0:" not in captured.err  # the plain sink is replaced, not added
    assert "\x1b" not in captured.err  # non-TTY -> escapes stripped


def test_drive_tui_events_inside_repo_survives_handoff(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A --tui-events stream written into the driven repo is harness telemetry: the
    handoff must not sweep it into the drive branch (after which branch-restore
    would delete it). It survives and round-trips to the same steps (#74 A3)."""
    from colleague.tui.events import loads_events
    from colleague.tui.from_drive import trace_to_drive_steps

    ev = tmp_path / "run.jsonl"
    rc = main(
        [
            "drive",
            "set up",
            "--repo",
            str(tmp_path),
            "--engine",
            "mock",
            "--no-pr",
            "--no-tui",
            "--tui-events",
            str(ev),
            "--json",
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert ev.exists(), "in-repo --tui-events stream was swept away by the handoff"
    live = [e.to_dict() for e in loads_events(ev.read_text())]
    # The artifact is named <task_id>.<slug>.json (#132); the trace shares the
    # stem (.json -> .trace.jsonl). Derive it from artifacts_path, never rebuild it.
    trace_path = Path(payload["artifacts_path"][: -len(".json")] + ".trace.jsonl")
    trace_lines = [json.loads(line) for line in trace_path.read_text().splitlines() if line.strip()]
    assert live == [e.to_dict() for e in trace_to_drive_steps(trace_lines)]


def test_drive_does_not_commit_preexisting_untracked(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Operator work-in-progress present before a drive must not be swept into the commit (#39)."""
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@e.com")
    _git(tmp_path, "config", "user.name", "T")
    (tmp_path / "seed").write_text("x")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "init")
    (tmp_path / "operator_wip.txt").write_text("uncommitted work, not the drive's")  # pre-existing

    rc = main(
        [
            "drive",
            "set up the repo",
            "--repo",
            str(tmp_path),
            "--engine",
            "mock",
            "--no-pr",
            "--json",
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)

    # C2: read the committed set off the drive branch (the operator is restored to
    # their original branch after the commit).
    committed = subprocess.run(
        ["git", "show", "--name-only", "--format=", payload["branch"]],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert OUTPUT_FILE in committed  # the drive's own output landed
    assert "operator_wip.txt" not in committed  # the pre-existing WIP did not
    # The WIP is still in the work tree, untouched (untracked files survive checkout).
    assert (tmp_path / "operator_wip.txt").exists()


def test_drive_unknown_engine_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["drive", "x", "--repo", str(tmp_path), "--engine", "nope"])
    assert rc == 1
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "wheels list" in err


def test_drive_bad_repo_errors(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["drive", "x", "--repo", "/no/such/dir", "--engine", "mock"])
    assert rc == 1
    assert "not a directory" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# drive --command
# ---------------------------------------------------------------------------


def _make_command_template(repo: Path, name: str, content: str) -> None:
    cmds_dir = repo / ".colleague" / "commands"
    cmds_dir.mkdir(parents=True, exist_ok=True)
    (cmds_dir / f"{name}.md").write_text(content)


def test_drive_command_expands_template_and_runs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """drive --command <name> expands the template into a task and runs it."""
    _make_command_template(tmp_path, "setup", "Set up the project.\n")
    rc = main(
        [
            "drive",
            "--command",
            "setup",
            "--repo",
            str(tmp_path),
            "--engine",
            "mock",
            "--no-pr",
            "--json",
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"


def test_drive_command_records_command_name_on_result(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """drive --command sets ``command`` field in the JSON result."""
    _make_command_template(tmp_path, "lint", "---\ndescription: Fix lint\n---\nFix lint.\n")
    rc = main(
        [
            "drive",
            "--command",
            "lint",
            "--repo",
            str(tmp_path),
            "--engine",
            "mock",
            "--no-pr",
            "--json",
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "lint"


def test_drive_command_with_args(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """drive --command <name> [args...] passes args through substitution."""
    _make_command_template(tmp_path, "greet", "Hello $1!\n")
    rc = main(
        [
            "drive",
            "--command",
            "greet",
            "world",
            "--repo",
            str(tmp_path),
            "--engine",
            "mock",
            "--no-pr",
            "--json",
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"


def test_drive_command_unknown_command_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """drive --command with an unknown name surfaces a CliError."""
    rc = main(
        [
            "drive",
            "--command",
            "nonexistent",
            "--repo",
            str(tmp_path),
            "--engine",
            "mock",
            "--no-pr",
        ]
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "hint:" in err


def test_drive_neither_instruction_nor_command_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Omitting both instruction and --command is a user error."""
    rc = main(["drive", "--repo", str(tmp_path), "--engine", "mock", "--no-pr"])
    assert rc == 1
    err = capsys.readouterr().err
    assert err.startswith("error:")


def test_drive_command_with_positional_arg_treated_as_template_arg(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """When --command is set, positional tokens become template args (not an error)."""
    _make_command_template(tmp_path, "build", "Build $1.\n")
    rc = main(
        [
            "drive",
            "--command",
            "build",
            "src/",
            "--repo",
            str(tmp_path),
            "--engine",
            "mock",
            "--no-pr",
            "--json",
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "build"


def test_drive_plain_instruction_still_works(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The existing plain-instruction path is unaffected by --command addition."""
    rc = main(["drive", "set up the repo", "--repo", str(tmp_path), "--engine", "mock", "--no-pr"])
    assert rc == 0


def test_drive_plain_instruction_command_field_is_none(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Plain instruction drive leaves TaskResult.command as None."""
    rc = main(
        [
            "drive",
            "do work",
            "--repo",
            str(tmp_path),
            "--engine",
            "mock",
            "--no-pr",
            "--json",
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] is None
