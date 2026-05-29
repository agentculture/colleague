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
