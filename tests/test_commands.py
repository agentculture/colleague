"""Command template discovery and expansion (t3).

Tests for colleague.commands:
- discover_commands(repo_path, *, user_home=None) -> dict[str, Path]
- load_command(path) -> Command
- expand_command(repo_path, name, args, *, engine_default="mock", user_home=None) -> Task
- CommandError raised on unknown command name

Acceptance criteria:
1. discover_commands finds fixture files under .colleague/commands/; a fixture command
   expands with $ARGUMENTS AND $1/$2 substitution working.
2. expand_command(repo, name, args) returns a Task whose dict keys exactly match
   Task.new(repo, "x").to_dict() keys, and whose repo_path/engine/constraints/instruction
   match expectations (id differs — it's random). Proven field-by-field.
3. Unknown command name raises CommandError.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from colleague.commands import (
    Command,
    CommandError,
    discover_commands,
    expand_command,
    load_command,
)
from colleague.contract import Task

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_repo(tmp_path: Path, subpath: str = "repo") -> Path:
    """Create a minimal repo directory under tmp_path."""
    repo = tmp_path / subpath
    repo.mkdir()
    return repo


def _make_commands_dir(base: Path) -> Path:
    """Create .colleague/commands/ directory tree under base."""
    cmds_dir = base / ".colleague" / "commands"
    cmds_dir.mkdir(parents=True)
    return cmds_dir


# ---------------------------------------------------------------------------
# discover_commands
# ---------------------------------------------------------------------------


class TestDiscoverCommands:
    def test_finds_md_files_in_repo_commands_dir(self, tmp_path: Path) -> None:
        """discover_commands returns stems mapped to paths for .md files."""
        repo = _make_repo(tmp_path)
        cmds_dir = _make_commands_dir(repo)
        (cmds_dir / "lint.md").write_text("Fix lint errors under $1.")
        (cmds_dir / "format.md").write_text("Run the formatter.")

        result = discover_commands(repo, user_home=tmp_path / "home")

        assert set(result.keys()) == {"lint", "format"}
        assert result["lint"] == cmds_dir / "lint.md"
        assert result["format"] == cmds_dir / "format.md"

    def test_ignores_non_md_files(self, tmp_path: Path) -> None:
        """discover_commands ignores files that are not .md."""
        repo = _make_repo(tmp_path)
        cmds_dir = _make_commands_dir(repo)
        (cmds_dir / "lint.md").write_text("Fix lint errors.")
        (cmds_dir / "notes.txt").write_text("ignored")
        (cmds_dir / "script.sh").write_text("#!/bin/bash")

        result = discover_commands(repo, user_home=tmp_path / "home")

        assert set(result.keys()) == {"lint"}

    def test_repo_shadows_user(self, tmp_path: Path) -> None:
        """Repo-level commands shadow user-level commands by stem."""
        repo = _make_repo(tmp_path)
        repo_cmds = _make_commands_dir(repo)
        (repo_cmds / "shared.md").write_text("repo version")

        user_home = tmp_path / "home"
        user_home.mkdir()
        user_cmds = user_home / ".colleague" / "commands"
        user_cmds.mkdir(parents=True)
        (user_cmds / "shared.md").write_text("user version")
        (user_cmds / "user-only.md").write_text("user only")

        result = discover_commands(repo, user_home=user_home)

        assert set(result.keys()) == {"shared", "user-only"}
        assert result["shared"].read_text() == "repo version"
        assert result["user-only"].read_text() == "user only"

    def test_empty_when_no_commands_dir(self, tmp_path: Path) -> None:
        """discover_commands returns {} when no .colleague/commands/ exists."""
        repo = _make_repo(tmp_path)
        user_home = tmp_path / "home"
        user_home.mkdir()

        result = discover_commands(repo, user_home=user_home)

        assert result == {}

    def test_empty_when_commands_dir_absent_but_colleague_present(self, tmp_path: Path) -> None:
        """Returns {} when .colleague/ exists but commands/ subdir does not."""
        repo = _make_repo(tmp_path)
        (repo / ".colleague").mkdir()
        user_home = tmp_path / "home"
        user_home.mkdir()

        result = discover_commands(repo, user_home=user_home)

        assert result == {}


# ---------------------------------------------------------------------------
# load_command
# ---------------------------------------------------------------------------


class TestLoadCommand:
    def test_load_body_only_no_metadata(self, tmp_path: Path) -> None:
        """A file with no --- block is loaded as plain body."""
        f = tmp_path / "simple.md"
        f.write_text("Fix lint errors under $1.")

        cmd = load_command(f)

        assert isinstance(cmd, Command)
        assert cmd.name == "simple"
        assert cmd.body == "Fix lint errors under $1."
        assert cmd.description == ""
        assert cmd.engine is None
        assert cmd.constraints == []
        assert cmd.arg_hint == ""

    def test_load_with_full_metadata(self, tmp_path: Path) -> None:
        """Parses all supported metadata keys from a --- block."""
        content = (
            "---\n"
            "description: Fix lint errors in a path\n"
            "engine: mock\n"
            "constraints: keep diffs minimal, run the formatter\n"
            "arg-hint: <path>\n"
            "---\n"
            "Fix all lint errors under $1. Then run the formatter. $ARGUMENTS\n"
        )
        f = tmp_path / "lint.md"
        f.write_text(content)

        cmd = load_command(f)

        assert cmd.name == "lint"
        assert cmd.description == "Fix lint errors in a path"
        assert cmd.engine == "mock"
        assert cmd.constraints == ["keep diffs minimal", "run the formatter"]
        assert cmd.arg_hint == "<path>"
        assert cmd.body == "Fix all lint errors under $1. Then run the formatter. $ARGUMENTS\n"

    def test_load_with_partial_metadata(self, tmp_path: Path) -> None:
        """Only provided keys are filled; unset keys stay at defaults."""
        content = "---\ndescription: A simple command\n---\nDo something useful.\n"
        f = tmp_path / "cmd.md"
        f.write_text(content)

        cmd = load_command(f)

        assert cmd.description == "A simple command"
        assert cmd.engine is None
        assert cmd.constraints == []
        assert cmd.arg_hint == ""
        assert cmd.body == "Do something useful.\n"

    def test_load_ignores_unknown_metadata_keys(self, tmp_path: Path) -> None:
        """Unknown metadata keys in the --- block are silently ignored."""
        content = "---\nunknown-key: some value\ndescription: Known\n---\nBody text.\n"
        f = tmp_path / "cmd.md"
        f.write_text(content)

        cmd = load_command(f)

        assert cmd.description == "Known"
        assert cmd.body == "Body text.\n"

    def test_load_constraints_single_item(self, tmp_path: Path) -> None:
        """A single constraint is returned as a one-element list."""
        content = "---\nconstraints: keep it simple\n---\nBody.\n"
        f = tmp_path / "cmd.md"
        f.write_text(content)

        cmd = load_command(f)

        assert cmd.constraints == ["keep it simple"]

    def test_load_empty_file(self, tmp_path: Path) -> None:
        """An empty file has empty body and no metadata."""
        f = tmp_path / "empty.md"
        f.write_text("")

        cmd = load_command(f)

        assert cmd.body == ""
        assert cmd.description == ""

    def test_load_metadata_block_with_empty_body(self, tmp_path: Path) -> None:
        """Metadata block with nothing after closing --- yields empty body."""
        content = "---\ndescription: No body\n---\n"
        f = tmp_path / "cmd.md"
        f.write_text(content)

        cmd = load_command(f)

        assert cmd.description == "No body"
        assert cmd.body == ""


# ---------------------------------------------------------------------------
# Argument substitution
# ---------------------------------------------------------------------------


class TestArgumentSubstitution:
    def test_arguments_placeholder_replaced(self, tmp_path: Path) -> None:
        """$ARGUMENTS is replaced with all args joined by a space."""
        repo = _make_repo(tmp_path)
        cmds_dir = _make_commands_dir(repo)
        (cmds_dir / "greet.md").write_text("Hello $ARGUMENTS!")

        task = expand_command(repo, "greet", ["world", "everyone"], user_home=tmp_path / "home")

        assert "world everyone" in task.instruction

    def test_positional_substitution(self, tmp_path: Path) -> None:
        """$1 and $2 are replaced with the 1st and 2nd positional args."""
        repo = _make_repo(tmp_path)
        cmds_dir = _make_commands_dir(repo)
        (cmds_dir / "move.md").write_text("Move $1 to $2 and log $ARGUMENTS")

        task = expand_command(repo, "move", ["src/a.py", "src/b.py"], user_home=tmp_path / "home")

        assert task.instruction == "Move src/a.py to src/b.py and log src/a.py src/b.py"

    def test_missing_positional_arg_becomes_empty(self, tmp_path: Path) -> None:
        """$2 with only one arg provided is replaced with an empty string."""
        repo = _make_repo(tmp_path)
        cmds_dir = _make_commands_dir(repo)
        (cmds_dir / "cmd.md").write_text("Do $1 and $2 done")

        task = expand_command(repo, "cmd", ["only"], user_home=tmp_path / "home")

        assert task.instruction == "Do only and  done"

    def test_no_args_arguments_becomes_empty(self, tmp_path: Path) -> None:
        """$ARGUMENTS with empty args list becomes empty string."""
        repo = _make_repo(tmp_path)
        cmds_dir = _make_commands_dir(repo)
        (cmds_dir / "cmd.md").write_text("Run with $ARGUMENTS and done")

        task = expand_command(repo, "cmd", [], user_home=tmp_path / "home")

        assert task.instruction == "Run with  and done"

    def test_arguments_placeholder_and_positional_both_work(self, tmp_path: Path) -> None:
        """Both $ARGUMENTS and $1/$2 substitution work in the same body."""
        repo = _make_repo(tmp_path)
        cmds_dir = _make_commands_dir(repo)
        (cmds_dir / "lint.md").write_text(
            "---\n"
            "description: Fix lint errors in a path\n"
            "engine: mock\n"
            "constraints: keep diffs minimal, run the formatter\n"
            "arg-hint: <path>\n"
            "---\n"
            "Fix all lint errors under $1. Then run the formatter. $ARGUMENTS"
        )

        task = expand_command(repo, "lint", ["src/"], user_home=tmp_path / "home")

        assert task.instruction == "Fix all lint errors under src/. Then run the formatter. src/"


# ---------------------------------------------------------------------------
# expand_command — Task shape and fields
# ---------------------------------------------------------------------------


class TestExpandCommand:
    def test_task_dict_keys_match_task_new(self, tmp_path: Path) -> None:
        """expand_command returns a Task whose to_dict() keys match Task.new(...).to_dict() keys."""
        repo = _make_repo(tmp_path)
        cmds_dir = _make_commands_dir(repo)
        (cmds_dir / "cmd.md").write_text("Do the thing with $ARGUMENTS")

        task = expand_command(repo, "cmd", ["arg1"], user_home=tmp_path / "home")
        reference = Task.new(str(repo), "x")

        assert set(task.to_dict().keys()) == set(reference.to_dict().keys())

    def test_repo_path_matches(self, tmp_path: Path) -> None:
        """task.repo_path matches the repo_path passed to expand_command."""
        repo = _make_repo(tmp_path)
        cmds_dir = _make_commands_dir(repo)
        (cmds_dir / "cmd.md").write_text("Do the thing")

        task = expand_command(repo, "cmd", [], user_home=tmp_path / "home")

        assert task.repo_path == str(repo)

    def test_engine_from_metadata(self, tmp_path: Path) -> None:
        """task.engine comes from the command's metadata when present."""
        repo = _make_repo(tmp_path)
        cmds_dir = _make_commands_dir(repo)
        content = "---\nengine: vllm-openai\n---\nDo the thing"
        (cmds_dir / "cmd.md").write_text(content)

        task = expand_command(repo, "cmd", [], user_home=tmp_path / "home")

        assert task.engine == "vllm-openai"

    def test_engine_default_used_when_no_metadata_engine(self, tmp_path: Path) -> None:
        """engine_default is used when the command has no engine metadata."""
        repo = _make_repo(tmp_path)
        cmds_dir = _make_commands_dir(repo)
        (cmds_dir / "cmd.md").write_text("Do the thing")

        task = expand_command(
            repo, "cmd", [], engine_default="vllm-openai", user_home=tmp_path / "home"
        )

        assert task.engine == "vllm-openai"

    def test_engine_default_is_mock_by_default(self, tmp_path: Path) -> None:
        """engine_default defaults to 'mock' when not specified."""
        repo = _make_repo(tmp_path)
        cmds_dir = _make_commands_dir(repo)
        (cmds_dir / "cmd.md").write_text("Do the thing")

        task = expand_command(repo, "cmd", [], user_home=tmp_path / "home")

        assert task.engine == "mock"

    def test_constraints_from_metadata(self, tmp_path: Path) -> None:
        """task.constraints comes from the command's metadata."""
        repo = _make_repo(tmp_path)
        cmds_dir = _make_commands_dir(repo)
        content = "---\nconstraints: keep diffs minimal, run the formatter\n---\nDo the thing"
        (cmds_dir / "cmd.md").write_text(content)

        task = expand_command(repo, "cmd", [], user_home=tmp_path / "home")

        assert task.constraints == ["keep diffs minimal", "run the formatter"]

    def test_constraints_empty_when_not_in_metadata(self, tmp_path: Path) -> None:
        """task.constraints is [] when no constraints metadata provided."""
        repo = _make_repo(tmp_path)
        cmds_dir = _make_commands_dir(repo)
        (cmds_dir / "cmd.md").write_text("Do the thing")

        task = expand_command(repo, "cmd", [], user_home=tmp_path / "home")

        assert task.constraints == []

    def test_instruction_is_substituted_body(self, tmp_path: Path) -> None:
        """task.instruction is the body with args substituted."""
        repo = _make_repo(tmp_path)
        cmds_dir = _make_commands_dir(repo)
        (cmds_dir / "cmd.md").write_text("Fix $1 and then $ARGUMENTS")

        task = expand_command(repo, "cmd", ["a.py", "b.py"], user_home=tmp_path / "home")

        assert task.instruction == "Fix a.py and then a.py b.py"

    def test_task_id_is_random_12_hex_chars(self, tmp_path: Path) -> None:
        """task.id is a 12-char hex string (random, so two calls differ)."""
        repo = _make_repo(tmp_path)
        cmds_dir = _make_commands_dir(repo)
        (cmds_dir / "cmd.md").write_text("Do the thing")

        task1 = expand_command(repo, "cmd", [], user_home=tmp_path / "home")
        task2 = expand_command(repo, "cmd", [], user_home=tmp_path / "home")

        assert len(task1.id) == 12
        assert all(c in "0123456789abcdef" for c in task1.id)
        assert task1.id != task2.id  # almost certainly different

    def test_context_is_empty_string(self, tmp_path: Path) -> None:
        """task.context is empty string (not set by expand_command)."""
        repo = _make_repo(tmp_path)
        cmds_dir = _make_commands_dir(repo)
        (cmds_dir / "cmd.md").write_text("Do the thing")

        task = expand_command(repo, "cmd", [], user_home=tmp_path / "home")

        assert task.context == ""

    def test_field_by_field_matches_task_new(self, tmp_path: Path) -> None:
        """All fields except id match the expected Task.new(...) values."""
        repo = _make_repo(tmp_path)
        cmds_dir = _make_commands_dir(repo)
        content = (
            "---\n"
            "engine: mock\n"
            "constraints: no side effects, log changes\n"
            "---\n"
            "Refactor $1 for clarity. $ARGUMENTS"
        )
        (cmds_dir / "refactor.md").write_text(content)

        task = expand_command(repo, "refactor", ["utils.py"], user_home=tmp_path / "home")

        # Build the expected task using Task.new to prove shape equivalence
        expected = Task.new(
            str(repo),
            "Refactor utils.py for clarity. utils.py",
            engine="mock",
            constraints=["no side effects", "log changes"],
        )

        assert task.repo_path == expected.repo_path
        assert task.instruction == expected.instruction
        assert task.engine == expected.engine
        assert task.constraints == expected.constraints
        assert task.context == expected.context
        # id is random; verify shape only
        assert isinstance(task.id, str)
        assert len(task.id) == 12


# ---------------------------------------------------------------------------
# CommandError
# ---------------------------------------------------------------------------


class TestCommandError:
    def test_raises_on_unknown_command_name(self, tmp_path: Path) -> None:
        """expand_command raises CommandError when the command name is unknown."""
        repo = _make_repo(tmp_path)
        # no commands dir at all
        user_home = tmp_path / "home"
        user_home.mkdir()

        with pytest.raises(CommandError):
            expand_command(repo, "nonexistent", [], user_home=user_home)

    def test_raises_on_unknown_name_even_with_other_commands(self, tmp_path: Path) -> None:
        """CommandError is raised for a name not in the discovered set."""
        repo = _make_repo(tmp_path)
        cmds_dir = _make_commands_dir(repo)
        (cmds_dir / "lint.md").write_text("Fix lint under $1")

        with pytest.raises(CommandError):
            expand_command(repo, "unknown", ["arg"], user_home=tmp_path / "home")

    def test_command_error_is_exception(self) -> None:
        """CommandError is a subclass of Exception."""
        assert issubclass(CommandError, Exception)

    def test_command_error_message_contains_name(self, tmp_path: Path) -> None:
        """CommandError message includes the unknown command name."""
        repo = _make_repo(tmp_path)
        user_home = tmp_path / "home"
        user_home.mkdir()

        with pytest.raises(CommandError, match="badname"):
            expand_command(repo, "badname", [], user_home=user_home)
