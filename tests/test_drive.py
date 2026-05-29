"""`convertible drive` — the headline verb wires engine->loop->artifact->handoff (c4)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from convertible import registry
from convertible.cli import main
from convertible.config import EngineConfig
from convertible.contract import Task, TaskResult
from convertible.engine import Engine
from convertible.engines.mock import OUTPUT_FILE
from convertible.loop import ModelResponse, ToolCall, run


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
    artifacts = list((tmp_path / ".convertible").glob("*.json"))
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
    assert payload["branch"].startswith("convertible/")
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
    assert (tmp_path / "made_by_cmd.txt").exists()
    assert payload["branch"].startswith("convertible/")  # handoff ran despite no write_file
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

    artifacts = list((tmp_path / ".convertible").glob("*.json"))
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

    rc = main(["drive", "x", "--repo", str(tmp_path), "--engine", "broken", "--no-pr"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "a result artifact was still written" in err
    assert "partial trace" not in err  # there is no partial trace on this path

    artifacts = list((tmp_path / ".convertible").glob("*.json"))
    payload = json.loads(artifacts[0].read_text())
    assert payload["status"] == "error"
    assert payload["steps"] == []  # fresh failed_result, no accumulated steps


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

    committed = subprocess.run(
        ["git", "show", "--name-only", "--format=", "HEAD"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert OUTPUT_FILE in committed  # the drive's own output landed
    assert "operator_wip.txt" not in committed  # the pre-existing WIP did not
    # The WIP is still in the work tree, untouched.
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
    cmds_dir = repo / ".convertible" / "commands"
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
