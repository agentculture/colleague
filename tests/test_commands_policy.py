"""Command-template approval-gate integration tests (t4).

Tests for the policy gate wired into expand_command:

1. An approved command template (checksum recorded in approvals.json under
   ``commands``) expands successfully into a Task.
2. A drifted/unapproved template (commands section present, but checksum
   mismatched or name absent) is refused with CommandError at expand time —
   before any engine runs.
3. With no ``commands`` section (empty/absent policy), templates expand
   exactly as today (strict no-op, byte-identical behaviour).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from convertible.commands import CommandError, expand_command
from convertible.contract import Task
from convertible.policy import file_checksum

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_repo(tmp_path: Path, subpath: str = "repo") -> Path:
    repo = tmp_path / subpath
    repo.mkdir()
    return repo


def _make_commands_dir(base: Path) -> Path:
    cmds_dir = base / ".convertible" / "commands"
    cmds_dir.mkdir(parents=True)
    return cmds_dir


def _write_approvals(repo: Path, data: dict) -> None:
    """Write approvals.json into the repo's .convertible/ directory."""
    approvals_path = repo / ".convertible" / "approvals.json"
    approvals_path.write_text(json.dumps(data), encoding="utf-8")


# ---------------------------------------------------------------------------
# Acceptance criterion 1: approved template expands successfully
# ---------------------------------------------------------------------------


class TestApprovedCommandExpands:
    def test_approved_checksum_expands_into_task(self, tmp_path: Path) -> None:
        """An approved template (correct checksum) expands into a Task."""
        repo = _make_repo(tmp_path)
        cmds_dir = _make_commands_dir(repo)
        cmd_file = cmds_dir / "fix-lint.md"
        cmd_file.write_text("Fix all lint errors under $1.")

        # Record the correct checksum in approvals.json.
        checksum = file_checksum(cmd_file)
        _write_approvals(repo, {"commands": {"fix-lint": checksum}})

        task = expand_command(
            repo,
            "fix-lint",
            ["src/"],
            user_home=tmp_path / "home",
        )

        assert isinstance(task, Task)
        assert "src/" in task.instruction

    def test_approved_template_with_metadata(self, tmp_path: Path) -> None:
        """An approved template with a metadata block still expands correctly."""
        repo = _make_repo(tmp_path)
        cmds_dir = _make_commands_dir(repo)
        content = "---\nengine: mock\nconstraints: keep diffs minimal\n---\nFix $1.\n"
        cmd_file = cmds_dir / "refactor.md"
        cmd_file.write_text(content)

        checksum = file_checksum(cmd_file)
        _write_approvals(repo, {"commands": {"refactor": checksum}})

        task = expand_command(
            repo,
            "refactor",
            ["utils.py"],
            user_home=tmp_path / "home",
        )

        assert task.engine == "mock"
        assert task.constraints == ["keep diffs minimal"]
        assert "utils.py" in task.instruction

    def test_model_parameter_threaded_to_policy(self, tmp_path: Path) -> None:
        """The model= parameter is accepted and the base policy is still consulted."""
        repo = _make_repo(tmp_path)
        cmds_dir = _make_commands_dir(repo)
        cmd_file = cmds_dir / "deploy.md"
        cmd_file.write_text("Deploy $1.")

        checksum = file_checksum(cmd_file)
        _write_approvals(repo, {"commands": {"deploy": checksum}})

        # Passing model= should not break expansion when base policy approves it.
        task = expand_command(
            repo,
            "deploy",
            ["prod"],
            model="mock-model",
            user_home=tmp_path / "home",
        )

        assert isinstance(task, Task)
        assert "prod" in task.instruction


# ---------------------------------------------------------------------------
# Acceptance criterion 2: drifted / unapproved template is refused
# ---------------------------------------------------------------------------


class TestRefusedOnDriftOrMissing:
    def test_unapproved_name_raises_command_error(self, tmp_path: Path) -> None:
        """A commands section present but the name missing → CommandError."""
        repo = _make_repo(tmp_path)
        cmds_dir = _make_commands_dir(repo)
        cmd_file = cmds_dir / "secret.md"
        cmd_file.write_text("Run something sensitive.")

        # commands section exists but does NOT list "secret".
        _write_approvals(repo, {"commands": {"other-cmd": "sha256:aabbcc"}})

        with pytest.raises(CommandError, match="refused by approval policy"):
            expand_command(
                repo,
                "secret",
                [],
                user_home=tmp_path / "home",
            )

    def test_drifted_checksum_raises_command_error(self, tmp_path: Path) -> None:
        """A drifted template (content changed after approval) → CommandError."""
        repo = _make_repo(tmp_path)
        cmds_dir = _make_commands_dir(repo)
        cmd_file = cmds_dir / "lint.md"
        cmd_file.write_text("Fix all lint errors under $1.")

        # Compute checksum of the original content and record it.
        checksum = file_checksum(cmd_file)
        _write_approvals(repo, {"commands": {"lint": checksum}})

        # Now mutate the file (simulate drift / tamper).
        cmd_file.write_text("Fix all lint errors under $1. # TAMPERED")

        with pytest.raises(CommandError, match="refused by approval policy"):
            expand_command(
                repo,
                "lint",
                ["src/"],
                user_home=tmp_path / "home",
            )

    def test_wrong_checksum_recorded_raises_command_error(self, tmp_path: Path) -> None:
        """A recorded checksum that never matched the file → CommandError."""
        repo = _make_repo(tmp_path)
        cmds_dir = _make_commands_dir(repo)
        cmd_file = cmds_dir / "build.md"
        cmd_file.write_text("Build the project.")

        # Record a plausible-looking but wrong checksum.
        _write_approvals(repo, {"commands": {"build": "sha256:deadbeef" + "0" * 56}})

        with pytest.raises(CommandError, match="refused by approval policy"):
            expand_command(
                repo,
                "build",
                [],
                user_home=tmp_path / "home",
            )

    def test_error_raised_before_engine_runs(self, tmp_path: Path) -> None:
        """CommandError is raised at expand time, not at engine-run time.

        Because expand_command is purely synchronous (no engine is invoked),
        the raise at expand time is verified by the CommandError propagating
        directly from expand_command — confirming the gate fires before any
        engine starts.
        """
        repo = _make_repo(tmp_path)
        cmds_dir = _make_commands_dir(repo)
        cmd_file = cmds_dir / "run.md"
        cmd_file.write_text("Run the suite.")

        _write_approvals(repo, {"commands": {"run": "sha256:" + "0" * 64}})

        with pytest.raises(CommandError):
            # expand_command never calls an engine — if it raises, the gate
            # fired before any engine work began.
            expand_command(
                repo,
                "run",
                [],
                user_home=tmp_path / "home",
            )

    def test_error_message_contains_command_name(self, tmp_path: Path) -> None:
        """The CommandError message names the refused command."""
        repo = _make_repo(tmp_path)
        cmds_dir = _make_commands_dir(repo)
        cmd_file = cmds_dir / "my-cmd.md"
        cmd_file.write_text("Do something.")

        _write_approvals(repo, {"commands": {}})

        with pytest.raises(CommandError, match="my-cmd"):
            expand_command(
                repo,
                "my-cmd",
                [],
                user_home=tmp_path / "home",
            )


# ---------------------------------------------------------------------------
# Acceptance criterion 3: no commands section → strict no-op
# ---------------------------------------------------------------------------


class TestNoPolicyNoOp:
    def test_no_approvals_file_expands_as_before(self, tmp_path: Path) -> None:
        """With no approvals.json at all, expand_command behaves as before."""
        repo = _make_repo(tmp_path)
        cmds_dir = _make_commands_dir(repo)
        (cmds_dir / "greet.md").write_text("Hello $ARGUMENTS!")

        task = expand_command(repo, "greet", ["world"], user_home=tmp_path / "home")

        assert isinstance(task, Task)
        assert "world" in task.instruction

    def test_approvals_file_without_commands_section_is_no_op(self, tmp_path: Path) -> None:
        """approvals.json with only run_command section leaves commands ungated."""
        repo = _make_repo(tmp_path)
        cmds_dir = _make_commands_dir(repo)
        (cmds_dir / "deploy.md").write_text("Deploy to $1.")

        # Only run_command section — no commands section.
        _write_approvals(repo, {"run_command": {"allow": ["git"], "deny": []}})

        task = expand_command(repo, "deploy", ["staging"], user_home=tmp_path / "home")

        assert isinstance(task, Task)
        assert "staging" in task.instruction

    def test_empty_approvals_file_is_no_op(self, tmp_path: Path) -> None:
        """An empty approvals.json ({}) leaves commands ungated."""
        repo = _make_repo(tmp_path)
        cmds_dir = _make_commands_dir(repo)
        (cmds_dir / "lint.md").write_text("Fix lint under $1.")

        _write_approvals(repo, {})

        task = expand_command(repo, "lint", ["src/"], user_home=tmp_path / "home")

        assert isinstance(task, Task)
        assert "src/" in task.instruction

    def test_no_approvals_byte_identical_task_to_no_model(self, tmp_path: Path) -> None:
        """Passing model= with no approvals.json still gives the same Task fields."""
        repo = _make_repo(tmp_path)
        cmds_dir = _make_commands_dir(repo)
        (cmds_dir / "check.md").write_text("Check $1.")

        task_no_model = expand_command(repo, "check", ["a.py"], user_home=tmp_path / "home")
        task_with_model = expand_command(
            repo, "check", ["a.py"], model="any-model", user_home=tmp_path / "home"
        )

        # All fields except the random id must be identical.
        assert task_no_model.repo_path == task_with_model.repo_path
        assert task_no_model.instruction == task_with_model.instruction
        assert task_no_model.engine == task_with_model.engine
        assert task_no_model.constraints == task_with_model.constraints
        assert task_no_model.context == task_with_model.context
