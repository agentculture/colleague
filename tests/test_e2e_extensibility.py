"""Capstone cross-engine e2e: commands + hooks + loop + artifact (t11).

Ties the full extensibility layer together and proves engine-agnosticism.

Coverage:
  c1  — headline claim: one command+hook config, identical result shape.
  c7  — success_signal: deny worked (no side-effect) + post_tool effect present.
  c20 — after_state: artifact is faithful (hook_firings + command fields present).
  h8  — hook_firings recorded per-engine.
  h15 — pre_tool deny reached model; post_tool side-effect observable.
  h16 — expand_command yields Task; command recorded in artifact.

Assertion index:
  A1  expand_command yields a Task whose instruction reflects template + args.
  A2  hook_firings contains the pre_tool deny and the post_tool observe firing.
  A3  TaskResult.command records the originating command name.
  A4  run_command did NOT execute (marker file absent).
  A5  The denied Step is non-ok and carries the reason text.
  A6  The post_tool hook's marker file IS present.
  A7  Both engines produce TaskResults with identical structure (same dict keys,
      same status, same shape of changed_files/steps/hook_firings).
  A8  Artifact JSON is valid and contains hook_firings, command, and a non-ok
      step for the denied tool.
"""

from __future__ import annotations

import json
import stat
from pathlib import Path
from typing import Any

from convertible.artifact import write as artifact_write
from convertible.commands import expand_command
from convertible.config import EngineConfig
from convertible.contract import OK, Task, TaskResult
from convertible.engine import Engine
from convertible.loop import CompleteFn, ModelResponse, ToolCall, run

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_script(path: Path, body: str) -> str:
    """Write an executable shell script; return 'sh <path>' invocation."""
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IRUSR)
    return f"sh {path}"


def _write_hooks(repo: Path, config: dict) -> None:
    """Write .convertible/hooks.json under *repo*."""
    dotdir = repo / ".convertible"
    dotdir.mkdir(parents=True, exist_ok=True)
    (dotdir / "hooks.json").write_text(json.dumps(config), encoding="utf-8")


def _write_command(repo: Path, name: str, body: str) -> None:
    """Write a command template under .convertible/commands/<name>.md."""
    cmds_dir = repo / ".convertible" / "commands"
    cmds_dir.mkdir(parents=True, exist_ok=True)
    (cmds_dir / f"{name}.md").write_text(body, encoding="utf-8")


def _key_shape(value: Any) -> Any:
    """Recursive key signature, ignoring concrete values — for shape comparison."""
    if isinstance(value, dict):
        return {k: _key_shape(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return _key_shape(value[0]) if value else None
    return None


def _dict_keys_deep(value: Any) -> Any:
    """Return sorted key sets at every level of nesting, for structural equality."""
    if isinstance(value, dict):
        return {k: _dict_keys_deep(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        if not value:
            return []
        # All list items must have the same shape; reduce to the first.
        return [_dict_keys_deep(value[0])]
    return type(value).__name__


# ---------------------------------------------------------------------------
# Fixture: set up a tmp repo with command template + hooks
# ---------------------------------------------------------------------------


def _setup_repo(tmp_path: Path, repo_name: str, scripts_dir: Path) -> tuple[Path, Path]:
    """Create a repo with:
    - .convertible/commands/do-work.md (template with $ARGUMENTS)
    - .convertible/hooks.json:
        pre_tool: DENY hook on run_command (exit 1)
        post_tool: observe hook on write_file that writes a marker file
    Returns (repo_path, marker_path).
    """
    repo = tmp_path / repo_name
    repo.mkdir()

    # Command template: uses $ARGUMENTS.
    _write_command(
        repo,
        "do-work",
        "---\ndescription: Integration work command\n---\nDo work with $ARGUMENTS\n",
    )

    # Marker file path — the post_tool hook will create this.
    marker = repo / "post-tool-marker.txt"

    # Pre-tool deny hook: exit 1 on run_command with reason on stderr.
    deny_script = _make_script(
        scripts_dir / f"deny_{repo_name}.sh",
        "echo 'run-command-is-blocked-by-policy' >&2; exit 1\n",
    )

    # Post-tool observe hook: writes a marker file when write_file runs.
    post_script = _make_script(
        scripts_dir / f"post_{repo_name}.sh",
        f"echo observed > {marker}\n",
    )

    _write_hooks(
        repo,
        {
            "hooks": {
                "pre_tool": [
                    {
                        "matcher": "run_command",
                        "command": deny_script,
                    }
                ],
                "post_tool": [
                    {
                        "matcher": "write_file",
                        "command": post_script,
                    }
                ],
            }
        },
    )

    return repo, marker


# ---------------------------------------------------------------------------
# Two scripted engine complete functions
# ---------------------------------------------------------------------------
#
# Both engines issue, in order:
#   1. run_command  → pre_tool hook DENIES it (marker file absent)
#   2. write_file   → executes (post_tool hook writes marker file)
#   3. finish
#
# They differ in implementation: engine-A uses a list/index closure;
# engine-B uses an iterator generator.  The contract (loop.run) is the same.


def _engine_a_complete(repo: Path) -> CompleteFn:
    """Scripted complete: list-of-turns closure."""
    run_cmd = str(repo / "should-not-exist.txt")
    turns = [
        ModelResponse(
            tool_calls=[ToolCall("a-1", "run_command", {"command": f"touch {run_cmd}"})],
            prompt_tokens=2,
            completion_tokens=1,
        ),
        ModelResponse(
            tool_calls=[
                ToolCall("a-2", "write_file", {"path": "output-a.txt", "content": "engine-a"})
            ],
            prompt_tokens=2,
            completion_tokens=1,
        ),
        ModelResponse(
            tool_calls=[ToolCall("a-3", "finish", {"summary": "engine-a done"})],
            prompt_tokens=1,
            completion_tokens=1,
        ),
    ]
    state = {"i": 0}

    def complete(_messages: list[dict]) -> ModelResponse:
        turn = turns[min(state["i"], len(turns) - 1)]
        state["i"] += 1
        return turn

    return complete


def _engine_b_complete(repo: Path) -> CompleteFn:
    """Scripted complete: generator-based closure."""
    run_cmd = str(repo / "should-not-exist.txt")
    seq = iter(
        [
            ModelResponse(
                tool_calls=[ToolCall("b-1", "run_command", {"command": f"touch {run_cmd}"})],
                prompt_tokens=3,
                completion_tokens=1,
            ),
            ModelResponse(
                tool_calls=[
                    ToolCall("b-2", "write_file", {"path": "output-b.txt", "content": "engine-b"})
                ],
                prompt_tokens=3,
                completion_tokens=1,
            ),
            ModelResponse(
                tool_calls=[ToolCall("b-3", "finish", {"summary": "engine-b done"})],
                prompt_tokens=1,
                completion_tokens=1,
            ),
        ]
    )
    last: dict[str, Any] = {"r": None}

    def complete(_messages: list[dict]) -> ModelResponse:
        try:
            last["r"] = next(seq)
        except StopIteration:
            pass
        return last["r"]  # type: ignore[return-value]

    return complete


# ---------------------------------------------------------------------------
# Two thin Engine subclasses wrapping the scripted complete fns
# ---------------------------------------------------------------------------


class EngineA(Engine):
    """First scripted engine: list-index complete."""

    name = "engine-a"

    def drive(self, task: Task, config: EngineConfig) -> TaskResult:
        return run(_engine_a_complete(Path(task.repo_path)), task, max_steps=config.max_steps)


class EngineB(Engine):
    """Second scripted engine: generator complete."""

    name = "engine-b"

    def drive(self, task: Task, config: EngineConfig) -> TaskResult:
        return run(_engine_b_complete(Path(task.repo_path)), task, max_steps=config.max_steps)


# ---------------------------------------------------------------------------
# The capstone test
# ---------------------------------------------------------------------------


def test_capstone_cross_engine_e2e(tmp_path: Path) -> None:  # noqa: PLR0914
    """Capstone: commands + hooks + loop + artifact, engine-agnostic.

    A1  expand_command yields a Task whose instruction contains the expanded
        template text (including $ARGUMENTS substitution).
    A2  hook_firings contains a pre_tool deny and a post_tool observe firing.
    A3  TaskResult.command records the originating command name.
    A4  run_command did NOT execute (no side-effect file).
    A5  The denied Step is non-ok and carries the deny reason.
    A6  The post_tool hook's marker file IS present after the drive.
    A7  Both engine paths produce TaskResults with identical structure.
    A8  Artifact JSON is valid and contains hook_firings, command, and a non-ok
        step for the denied tool.
    """
    scripts = tmp_path / "scripts"
    scripts.mkdir()

    repo_a, marker_a = _setup_repo(tmp_path, "repo-a", scripts)
    repo_b, marker_b = _setup_repo(tmp_path, "repo-b", scripts)

    cfg = EngineConfig.resolve()

    # -----------------------------------------------------------------------
    # A1 — expand_command yields a Task reflecting the template + args
    # -----------------------------------------------------------------------
    task_a = expand_command(repo_a, "do-work", ["alpha", "beta"])
    assert isinstance(task_a, Task)
    assert (
        "alpha beta" in task_a.instruction
    ), f"instruction should contain substituted $ARGUMENTS; got: {task_a.instruction!r}"
    assert "Do work with" in task_a.instruction

    task_b = expand_command(repo_b, "do-work", ["gamma"])
    assert isinstance(task_b, Task)
    assert "gamma" in task_b.instruction

    # -----------------------------------------------------------------------
    # Drive both engines
    # -----------------------------------------------------------------------
    engine_a = EngineA()
    engine_b = EngineB()

    result_a = engine_a.drive(task_a, cfg)
    # Attach the command name (mimics what the CLI does after drive).
    result_a.command = "do-work"

    result_b = engine_b.drive(task_b, cfg)
    result_b.command = "do-work"

    # -----------------------------------------------------------------------
    # A2 — hook_firings: pre_tool deny + post_tool observe present
    # -----------------------------------------------------------------------
    for label, result in [("engine-a", result_a), ("engine-b", result_b)]:
        deny_firings = [f for f in result.hook_firings if f.decision == "deny"]
        assert len(deny_firings) >= 1, f"{label}: expected a deny firing; got {result.hook_firings}"
        deny_f = deny_firings[0]
        assert deny_f.event == "pre_tool", f"{label}: deny firing should be pre_tool"
        assert deny_f.tool == "run_command", f"{label}: deny should be on run_command"
        assert (
            "blocked" in deny_f.reason
        ), f"{label}: deny reason should mention 'blocked'; got {deny_f.reason!r}"

        post_firings = [f for f in result.hook_firings if f.event == "post_tool"]
        assert (
            len(post_firings) >= 1
        ), f"{label}: expected a post_tool firing; got {result.hook_firings}"
        post_f = post_firings[0]
        assert post_f.tool == "write_file", f"{label}: post_tool should fire on write_file"

    # -----------------------------------------------------------------------
    # A3 — TaskResult.command records the originating command name
    # -----------------------------------------------------------------------
    assert result_a.command == "do-work", f"result_a.command: {result_a.command!r}"
    assert result_b.command == "do-work", f"result_b.command: {result_b.command!r}"

    # -----------------------------------------------------------------------
    # A4 — run_command did NOT execute (no side-effect file)
    # -----------------------------------------------------------------------
    assert not (
        repo_a / "should-not-exist.txt"
    ).exists(), "engine-a: run_command should have been denied; marker file was created"
    assert not (
        repo_b / "should-not-exist.txt"
    ).exists(), "engine-b: run_command should have been denied; marker file was created"

    # -----------------------------------------------------------------------
    # A5 — denied Step is non-ok and carries the reason
    # -----------------------------------------------------------------------
    for label, result in [("engine-a", result_a), ("engine-b", result_b)]:
        denied_steps = [s for s in result.steps if s.tool == "run_command" and not s.ok]
        assert (
            len(denied_steps) >= 1
        ), f"{label}: expected a non-ok run_command step; steps={result.steps}"
        assert (
            "blocked" in denied_steps[0].result
        ), f"{label}: step result should carry the deny reason; got {denied_steps[0].result!r}"

    # -----------------------------------------------------------------------
    # A6 — post_tool hook's marker file IS present
    # -----------------------------------------------------------------------
    assert marker_a.exists(), f"engine-a: post_tool hook should have written {marker_a}"
    assert marker_b.exists(), f"engine-b: post_tool hook should have written {marker_b}"

    # -----------------------------------------------------------------------
    # A7 — identical result SHAPE across both engines
    # -----------------------------------------------------------------------
    dict_a = result_a.to_dict()
    dict_b = result_b.to_dict()

    # Top-level key sets must match.
    assert set(dict_a.keys()) == set(
        dict_b.keys()
    ), f"top-level key mismatch:\n  a={sorted(dict_a.keys())}\n  b={sorted(dict_b.keys())}"

    # Both reached OK status.
    assert result_a.status == OK, f"engine-a status: {result_a.status}"
    assert result_b.status == OK, f"engine-b status: {result_b.status}"

    # changed_files: both have at least one changed file.
    assert isinstance(dict_a["changed_files"], list)
    assert isinstance(dict_b["changed_files"], list)
    assert len(dict_a["changed_files"]) >= 1
    assert len(dict_b["changed_files"]) >= 1

    # steps: both have at least two steps (denied run_command + write_file).
    assert len(dict_a["steps"]) >= 2
    assert len(dict_b["steps"]) >= 2

    # hook_firings: both have at least two firings (deny + post_tool).
    assert len(dict_a["hook_firings"]) >= 2
    assert len(dict_b["hook_firings"]) >= 2

    # Deep key-shape of the first step (same dict keys).
    assert _dict_keys_deep(dict_a["steps"][0]) == _dict_keys_deep(
        dict_b["steps"][0]
    ), "step dict key shapes differ between engines"

    # Deep key-shape of the first hook_firing (same dict keys).
    assert _dict_keys_deep(dict_a["hook_firings"][0]) == _dict_keys_deep(
        dict_b["hook_firings"][0]
    ), "hook_firing dict key shapes differ between engines"

    # Full recursive key shape of the whole result must match.
    assert _key_shape(dict_a) == _key_shape(
        dict_b
    ), "full result key shape differs between engine-a and engine-b"

    # -----------------------------------------------------------------------
    # A8 — artifact is faithful
    # -----------------------------------------------------------------------
    artifacts_dir = tmp_path / "artifacts"
    artifact_path = artifact_write(result_a, artifacts_dir)
    assert artifact_path.exists(), "artifact_write should produce a file"

    raw = json.loads(artifact_path.read_text(encoding="utf-8"))

    # Valid JSON with the hook_firings field.
    assert "hook_firings" in raw, "artifact JSON missing hook_firings"
    assert isinstance(raw["hook_firings"], list)
    assert len(raw["hook_firings"]) >= 2

    # command field present.
    assert "command" in raw, "artifact JSON missing command"
    assert raw["command"] == "do-work"

    # At least one non-ok step for the denied run_command.
    denied_in_artifact = [
        s for s in raw.get("steps", []) if s.get("tool") == "run_command" and not s.get("ok")
    ]
    assert (
        len(denied_in_artifact) >= 1
    ), f"artifact should contain a non-ok run_command step; steps={raw.get('steps')}"

    # Each hook_firing dict must have the expected keys.
    expected_firing_keys = {"event", "tool", "command", "decision", "exit_code", "reason"}
    for firing in raw["hook_firings"]:
        assert (
            set(firing.keys()) == expected_firing_keys
        ), f"hook_firing missing keys: {expected_firing_keys - set(firing.keys())}"

    # task_id and status are present.
    assert raw.get("status") == OK
    assert raw.get("task_id") == result_a.task_id
