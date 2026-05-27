"""Regression tests for the PR #14 review findings (Qodo).

One test per finding so a future regression points straight at the cause:

#1 ``session`` honors ``--json`` (machine-readable stdout, chrome to stderr).
#2 ``session`` routes errors/diagnostics to stderr, never stdout.
#3 (covered structurally by the boundary/lint gates) — ``hooks list`` uses the
   public ``HookConfig.all_entries`` accessor; exercised here too.
#4 hook execution/matching failures become structured decisions, never crash.
#5 the originating command is persisted in the artifact on the failure path and
   for session-run templates.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from convertible import registry
from convertible.cli._commands import drive as drive_mod
from convertible.cli._commands.session import run_session
from convertible.cli._errors import CliError
from convertible.config import EngineConfig
from convertible.contract import OK, Task, TaskResult
from convertible.hooks import HookConfig, HookEntry, load_hooks, run_hook
from convertible.loop import ModelResponse, ToolCall
from convertible.loop import run as loop_run


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _session_args(repo: Path, *, json_mode: bool = False) -> argparse.Namespace:
    return argparse.Namespace(
        repo=str(repo),
        engine="mock",
        no_pr=True,
        base="main",
        base_url=None,
        model=None,
        api_key=None,
        max_steps=None,
        json=json_mode,
    )


def _sink() -> tuple[list[str], object]:
    lines: list[str] = []

    def write(*args: object, **_kwargs: object) -> None:
        lines.append(" ".join(str(a) for a in args))

    return lines, write


# --------------------------------------------------------------------------- #
# #4 — hook failures never crash the drive
# --------------------------------------------------------------------------- #
def test_run_hook_timeout_maps_to_deny(tmp_path: Path) -> None:
    entry = HookEntry(event="pre_tool", matcher="", command="sleep 5")
    decision = run_hook(entry, {"event": "pre_tool"}, cwd=tmp_path, timeout=1)
    assert decision.decision == "deny"
    assert "timed out" in decision.reason
    assert decision.exit_code is None


def test_hooks_for_invalid_regex_is_non_matching(tmp_path: Path) -> None:
    (tmp_path / ".convertible").mkdir()
    (tmp_path / ".convertible" / "hooks.json").write_text(
        json.dumps({"hooks": {"pre_tool": [{"matcher": "[", "command": "echo x"}]}}),
        encoding="utf-8",
    )
    cfg = load_hooks(tmp_path)
    # An invalid matcher regex must not raise — the entry is simply skipped.
    assert cfg.hooks_for("pre_tool", tool="run_command") == []


def test_loop_contains_a_crashing_hook(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".convertible").mkdir()
    (tmp_path / ".convertible" / "hooks.json").write_text(
        json.dumps({"hooks": {"pre_tool": [{"matcher": "write_file", "command": "echo x"}]}}),
        encoding="utf-8",
    )

    import convertible.loop as loop_module

    def _boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("kaboom")

    monkeypatch.setattr(loop_module, "run_hook", _boom)

    turns = [
        ModelResponse(
            tool_calls=[ToolCall("c1", "write_file", {"path": "out.txt", "content": "hi"})]
        ),
        ModelResponse(tool_calls=[ToolCall("c2", "finish", {"summary": "done"})]),
    ]
    state = {"i": 0}

    def complete(_messages: list[dict]) -> ModelResponse:
        turn = turns[min(state["i"], len(turns) - 1)]
        state["i"] += 1
        return turn

    task = Task.new(str(tmp_path), "write a file", engine="mock")
    result = loop_run(complete, task, max_steps=5)

    # The crash was contained: recorded as a fail-closed deny, drive completed.
    assert any(f.decision == "deny" and "hook error" in f.reason for f in result.hook_firings)
    # A fail-closed pre_tool deny means write_file never ran.
    assert not (tmp_path / "out.txt").exists()


# --------------------------------------------------------------------------- #
# #3 — public accessor for hook entries
# --------------------------------------------------------------------------- #
def test_hookconfig_all_entries_is_public(tmp_path: Path) -> None:
    (tmp_path / ".convertible").mkdir()
    (tmp_path / ".convertible" / "hooks.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "task_start": [{"command": "echo a"}],
                    "pre_tool": [{"matcher": "run_command", "command": "echo b"}],
                }
            }
        ),
        encoding="utf-8",
    )
    cfg = load_hooks(tmp_path)
    entries = cfg.all_entries()
    assert {e.command for e in entries} == {"echo a", "echo b"}
    assert isinstance(cfg, HookConfig)


# --------------------------------------------------------------------------- #
# #1 / #2 — session --json + stream separation
# --------------------------------------------------------------------------- #
def test_session_json_mode_stdout_is_pure_json(tmp_path: Path) -> None:
    (tmp_path / ".convertible" / "commands").mkdir(parents=True)
    (tmp_path / ".convertible" / "commands" / "greet.md").write_text("Say hi\n", encoding="utf-8")

    out_lines, out = _sink()
    err_lines, err = _sink()

    def fake_drive(**kwargs: object) -> tuple[TaskResult, Path]:
        return TaskResult(task_id="x", status=OK, summary="done"), tmp_path / "art.json"

    args = _session_args(tmp_path, json_mode=True)
    rc = run_session(args, input_fn=iter(["greet", "q"]), out=out, err=err, _drive_fn=fake_drive)
    assert rc == 0

    # stdout carries exactly one JSON object — the drive result — and no chrome.
    payloads = [json.loads(line) for line in out_lines if line.strip()]
    assert len(payloads) == 1
    assert payloads[0]["status"] == OK
    # The palette chrome and prompts went to stderr instead.
    assert any("convertible session" in line for line in err_lines)


def test_session_errors_go_to_stderr(tmp_path: Path) -> None:
    out_lines, out = _sink()
    err_lines, err = _sink()

    def fake_drive(**kwargs: object) -> tuple[TaskResult, Path]:  # pragma: no cover
        raise AssertionError("drive must not run for an invalid selection")

    args = _session_args(tmp_path, json_mode=False)
    # No commands discovered → '99' is an out-of-range palette index.
    rc = run_session(args, input_fn=iter(["99", "q"]), out=out, err=err, _drive_fn=fake_drive)
    assert rc == 0
    assert any("no entry 99" in line for line in err_lines)
    assert not any("no entry" in line for line in out_lines)


# --------------------------------------------------------------------------- #
# #5 — originating command persisted on the failure path
# --------------------------------------------------------------------------- #
def test_command_persisted_on_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class _BoomEngine:
        def drive(self, task: Task, config: EngineConfig) -> TaskResult:
            raise RuntimeError("engine exploded")

    monkeypatch.setattr(registry, "load", lambda _name: _BoomEngine())

    task = Task.new(str(tmp_path), "do it", engine="mock")
    with pytest.raises(CliError):
        drive_mod.execute_drive(
            repo=tmp_path,
            engine_name="mock",
            task=task,
            open_pr=False,
            base="main",
            config=EngineConfig.resolve(),
            command_name="greet",
        )

    artifact = json.loads((tmp_path / ".convertible" / f"{task.id}.json").read_text())
    assert artifact["status"] == "error"
    assert artifact["command"] == "greet"
