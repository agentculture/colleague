"""Clone lifecycle wiring + never-execute confinement (t4).

AC1 — Clone/cleanup lifecycle:
  - clone_all() is called at task_start (before the loop) so clones are available
    during the drive.
  - cleanup() is called on the ``finish`` lifecycle event so clones are removed
    after the drive, on EVERY loop exit path: model finish, empty turn, AND
    step-budget exhaustion.
  - With an empty allow-list, clone_all() is a safe no-op.

AC2 — Never-execute confinement:
  - run_command must NOT execute anything whose target/execution path falls under
    the .colleague/neighbours/ clone dir. A best-effort guard in _run_command
    returns a ToolError-style message instead of running the command.
  - read_file MUST still succeed for files inside a clone dir (the clone files are
    within the repo root, so _safe_path already allows them).

Tests here are hermetic (no network). Fake neighbours are created by writing files
directly under a tmp repo's .colleague/neighbours/<name>/ tree — no real git
clone required.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from colleague.contract import Task
from colleague.hooks import HookConfig
from colleague.loop import ModelResponse, ToolCall, run
from colleague.tools import ToolError, ToolExecutor

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def scripted(responses: list[ModelResponse]):
    """A complete() that returns each canned response in turn (then repeats last)."""
    state = {"i": 0}

    def complete(_messages):
        i = min(state["i"], len(responses) - 1)
        state["i"] += 1
        return responses[i]

    return complete


def _make_fake_clone(repo: Path, name: str, filename: str, content: str) -> Path:
    """Create a fake neighbour clone directory with one file (no git needed)."""
    clone_dir = repo / ".colleague" / "neighbours" / name
    clone_dir.mkdir(parents=True, exist_ok=True)
    file_path = clone_dir / filename
    file_path.write_text(content, encoding="utf-8")
    return clone_dir


def _write_neighbours_config(repo: Path, entries: list[dict]) -> None:
    """Write .colleague/neighbours.json with the given allow-list entries."""
    import json

    dotdir = repo / ".colleague"
    dotdir.mkdir(parents=True, exist_ok=True)
    (dotdir / "neighbours.json").write_text(json.dumps(entries), encoding="utf-8")


# ---------------------------------------------------------------------------
# AC1 — Cleanup at finish: loop wiring
# ---------------------------------------------------------------------------


class TestCleanupAtFinish:
    """clone_all is called before the loop; cleanup() is called on every loop exit."""

    def test_cleanup_fires_after_model_finish(self, tmp_path: Path) -> None:
        """After a normal model-finish run, the neighbours clone dir is removed."""
        # Pre-plant a fake clone that would exist before the drive.
        _make_fake_clone(tmp_path, "sibling", "README.md", "hello")
        clone_root = tmp_path / ".colleague" / "neighbours"
        assert clone_root.exists(), "pre-condition: clone dir exists before drive"

        responses = [
            ModelResponse(tool_calls=[ToolCall("1", "finish", {"summary": "done"})]),
        ]
        task = Task.new(str(tmp_path), "just finish")
        result = run(scripted(responses), task, max_steps=10, hooks=HookConfig())

        assert result.status == "ok"
        assert (
            not clone_root.exists()
        ), "cleanup() must remove .colleague/neighbours/ after a model-finish drive"

    def test_cleanup_fires_after_budget_exhaustion(self, tmp_path: Path) -> None:
        """cleanup() fires even when the loop hits max_steps (budget exit path)."""
        _make_fake_clone(tmp_path, "sibling", "README.md", "hello")
        clone_root = tmp_path / ".colleague" / "neighbours"
        assert clone_root.exists()

        def never_finish(_messages):
            return ModelResponse(tool_calls=[ToolCall("x", "list_dir", {"path": "."})])

        task = Task.new(str(tmp_path), "loop forever")
        result = run(never_finish, task, max_steps=2, hooks=HookConfig())

        assert "budget" in result.summary
        assert (
            not clone_root.exists()
        ), "cleanup() must fire on budget exhaustion — clones must be gone after drive"

    def test_cleanup_fires_after_empty_tool_turn(self, tmp_path: Path) -> None:
        """cleanup() fires when the model answers without requesting any tool."""
        _make_fake_clone(tmp_path, "sibling", "README.md", "hello")
        clone_root = tmp_path / ".colleague" / "neighbours"
        assert clone_root.exists()

        task = Task.new(str(tmp_path), "just answer")
        result = run(
            scripted([ModelResponse(content="nothing to do")]),
            task,
            max_steps=5,
            hooks=HookConfig(),
        )

        assert result.summary == "nothing to do"
        assert (
            not clone_root.exists()
        ), "cleanup() must fire on empty-tool-call exit — clones must be gone after drive"

    def test_empty_allowlist_noop(self, tmp_path: Path) -> None:
        """With no neighbours.json, clone_all() is a safe no-op (nothing cloned)."""
        # No neighbours.json, no pre-existing clones.
        clone_root = tmp_path / ".colleague" / "neighbours"
        assert not clone_root.exists()

        responses = [
            ModelResponse(tool_calls=[ToolCall("1", "finish", {"summary": "done"})]),
        ]
        task = Task.new(str(tmp_path), "just finish")
        result = run(scripted(responses), task, max_steps=10, hooks=HookConfig())

        assert result.status == "ok"
        # clone_all() was called but did nothing — neighbours dir should not exist.
        assert not clone_root.exists()

    def test_cleanup_safe_when_no_clones_exist(self, tmp_path: Path) -> None:
        """cleanup() doesn't crash when .colleague/neighbours/ was never created."""
        clone_root = tmp_path / ".colleague" / "neighbours"
        assert not clone_root.exists()

        responses = [
            ModelResponse(tool_calls=[ToolCall("1", "finish", {"summary": "done"})]),
        ]
        task = Task.new(str(tmp_path), "just finish")
        # Must not raise even though there is nothing to clean up.
        result = run(scripted(responses), task, max_steps=10, hooks=HookConfig())

        assert result.status == "ok"

    def test_clones_available_during_drive_read(self, tmp_path: Path) -> None:
        """Files in a clone dir are readable via read_file during the drive.

        This proves that clone_all() runs BEFORE the loop — the drive can read
        neighbour files. We simulate this by pre-creating the clone dir (the
        clone_all() no-op path for an allow-listed but already-cloned neighbour).
        Since we don't want to hit a real git remote we instead verify that if a
        clone already exists, read_file can access it and it's still cleaned up.
        """
        _make_fake_clone(tmp_path, "lib", "util.py", "def helper(): pass\n")
        clone_root = tmp_path / ".colleague" / "neighbours"

        read_succeeded = []

        def drive_and_read(_messages):
            if not read_succeeded:
                # First turn: try to read the clone file.
                return ModelResponse(
                    tool_calls=[
                        ToolCall(
                            "r1",
                            "read_file",
                            {"path": ".colleague/neighbours/lib/util.py"},
                        )
                    ]
                )
            # Second turn: finish.
            return ModelResponse(tool_calls=[ToolCall("f1", "finish", {"summary": "read ok"})])

        # Track the read result via a custom executor wrapper.
        real_executor = ToolExecutor(tmp_path)
        original_execute = real_executor.execute

        def patched_execute(name, arguments):
            outcome = original_execute(name, arguments)
            if name == "read_file":
                read_succeeded.append(outcome.result)
            return outcome

        real_executor.execute = patched_execute

        task = Task.new(str(tmp_path), "read a clone file")
        result = run(
            drive_and_read,
            task,
            max_steps=5,
            executor=real_executor,
            hooks=HookConfig(),
        )

        assert result.status == "ok"
        assert read_succeeded, "read_file of a clone-dir file must succeed during the drive"
        assert "def helper" in read_succeeded[0]
        # After the drive, clones are cleaned up.
        assert not clone_root.exists()


# ---------------------------------------------------------------------------
# AC2 — Never-execute confinement in _run_command
# ---------------------------------------------------------------------------


class TestNeverExecuteConfinement:
    """run_command must refuse commands that target/execute a clone path."""

    def test_run_command_refused_for_clone_path(self, tmp_path: Path) -> None:
        """run_command raises ToolError when the command targets the clone dir."""
        clone_dir = _make_fake_clone(tmp_path, "sibling", "script.sh", "echo hi\n")
        executor = ToolExecutor(tmp_path)

        with pytest.raises(ToolError, match="clone"):
            executor.execute(
                "run_command",
                {"command": f"sh {clone_dir}/script.sh"},
            )

    def test_run_command_refused_for_neighbours_subpath(self, tmp_path: Path) -> None:
        """run_command is refused for any path under .colleague/neighbours/."""
        _make_fake_clone(tmp_path, "lib", "tool.py", "print('x')\n")
        executor = ToolExecutor(tmp_path)
        clone_path = str(tmp_path / ".colleague" / "neighbours" / "lib" / "tool.py")

        with pytest.raises(ToolError, match="clone"):
            executor.execute(
                "run_command",
                {"command": f"python3 {clone_path}"},
            )

    def test_run_command_refused_relative_clone_path(self, tmp_path: Path) -> None:
        """run_command is refused when the command contains a relative clone path."""
        _make_fake_clone(tmp_path, "ext", "run.sh", "echo run\n")
        executor = ToolExecutor(tmp_path)

        with pytest.raises(ToolError, match="clone"):
            executor.execute(
                "run_command",
                {"command": "sh .colleague/neighbours/ext/run.sh"},
            )

    def test_run_command_allowed_outside_clone_dir(self, tmp_path: Path) -> None:
        """run_command works normally for commands that don't mention the clone dir."""
        _make_fake_clone(tmp_path, "sibling", "README.md", "# hi")
        executor = ToolExecutor(tmp_path)

        # A normal command unrelated to clones must succeed.
        outcome = executor.execute("run_command", {"command": "echo hello"})
        assert "hello" in outcome.result

    def test_read_file_clone_path_still_works(self, tmp_path: Path) -> None:
        """read_file of a file inside a clone dir must still succeed.

        Clone files are under the repo root, so _safe_path already permits them.
        The never-execute guard must NOT affect read_file.
        """
        _make_fake_clone(tmp_path, "peer", "constants.py", "X = 42\n")
        executor = ToolExecutor(tmp_path)

        outcome = executor.execute(
            "read_file",
            {"path": ".colleague/neighbours/peer/constants.py"},
        )
        assert "X = 42" in outcome.result

    def test_run_command_refuses_cd_into_clone_then_execute(self, tmp_path: Path) -> None:
        """run_command is refused when the command contains a cd into the clone dir."""
        _make_fake_clone(tmp_path, "lib", "build.sh", "make\n")
        executor = ToolExecutor(tmp_path)

        with pytest.raises(ToolError, match="clone"):
            executor.execute(
                "run_command",
                {"command": "cd .colleague/neighbours/lib && sh build.sh"},
            )

    def test_run_command_confinement_via_loop(self, tmp_path: Path) -> None:
        """The never-execute guard is visible through the full loop path.

        A model that requests run_command targeting a clone file gets a ToolError
        fed back as a non-ok Step; the loop continues and the command never runs.
        """
        _make_fake_clone(tmp_path, "ext", "script.sh", "touch /tmp/pwned\n")
        responses = [
            ModelResponse(
                tool_calls=[
                    ToolCall(
                        "c1",
                        "run_command",
                        {"command": "sh .colleague/neighbours/ext/script.sh"},
                    )
                ]
            ),
            ModelResponse(tool_calls=[ToolCall("f1", "finish", {"summary": "tried it"})]),
        ]
        task = Task.new(str(tmp_path), "run neighbour script")
        result = run(scripted(responses), task, max_steps=10, hooks=HookConfig())

        assert result.status == "ok"
        run_steps = [s for s in result.steps if s.tool == "run_command"]
        assert run_steps, "a run_command step must be recorded"
        assert run_steps[0].ok is False
        assert "clone" in run_steps[0].result


# ---------------------------------------------------------------------------
# run_command subprocess-failure mapping: a hung or unlaunchable command must
# become a recoverable ToolError fed back to the model, never an uncaught
# exception that aborts the whole drive (mirrors culture/devague/hooks).
# ---------------------------------------------------------------------------


class TestRunCommandSubprocessErrors:
    """subprocess failures in run_command map to ToolError, not a drive abort."""

    def test_run_command_timeout_maps_to_tool_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom(*_args: object, **_kwargs: object) -> object:
            raise subprocess.TimeoutExpired(cmd="sleep 999", timeout=300)

        monkeypatch.setattr("colleague.tools.subprocess.run", boom)
        executor = ToolExecutor(tmp_path)

        with pytest.raises(ToolError, match="timed out"):
            executor.execute("run_command", {"command": "sleep 999"})

    def test_run_command_oserror_maps_to_tool_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom(*_args: object, **_kwargs: object) -> object:
            raise OSError("Too many open files")

        monkeypatch.setattr("colleague.tools.subprocess.run", boom)
        executor = ToolExecutor(tmp_path)

        with pytest.raises(ToolError, match="failed to launch"):
            executor.execute("run_command", {"command": "echo hi"})

    def test_run_command_timeout_continues_drive_via_loop(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A timed-out command yields a non-ok Step; the drive CONTINUES.

        Regression lock: before the fix, subprocess.TimeoutExpired escaped the
        executor and aborted the whole drive via DriveAborted.
        """

        def boom(*_args: object, **_kwargs: object) -> object:
            raise subprocess.TimeoutExpired(cmd="sleep 999", timeout=300)

        monkeypatch.setattr("colleague.tools.subprocess.run", boom)
        responses = [
            ModelResponse(tool_calls=[ToolCall("c1", "run_command", {"command": "sleep 999"})]),
            ModelResponse(tool_calls=[ToolCall("f1", "finish", {"summary": "done"})]),
        ]
        task = Task.new(str(tmp_path), "run a slow command")
        result = run(scripted(responses), task, max_steps=10, hooks=HookConfig())

        assert result.status == "ok"
        run_steps = [s for s in result.steps if s.tool == "run_command"]
        assert run_steps, "a run_command step must be recorded"
        assert run_steps[0].ok is False
        assert "timed out" in run_steps[0].result
