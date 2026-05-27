"""Tests for convertible/hooks.py — hook config loader and runner (t4).

Table-driven tests covering:
1. load_hooks parses hooks.json; hooks_for selects/excludes by matcher.
2. run_hook maps deny (exit 1), rewrite (exit 0 + JSON), allow (exit 0 + empty stdout).
3. JSON payload reaches the hook on stdin with the documented keys.
"""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from convertible.hooks import (
    HookConfig,
    HookDecision,
    HookEntry,
    load_hooks,
    run_hook,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

HOOKS_JSON = {
    "hooks": {
        "pre_tool": [
            {"matcher": "run_command", "command": "echo pre-run"},
            {"matcher": "write_file", "command": "echo pre-write"},
        ],
        "post_tool": [
            {"matcher": "write_file", "command": "echo post-write"},
            {"matcher": "", "command": "echo post-all"},
        ],
        "task_start": [
            {"command": "echo start"},
        ],
        "finish": [
            {"command": "echo done"},
            {"matcher": "irrelevant_matcher", "command": "echo done-matcher"},
        ],
    }
}


@pytest.fixture()
def repo_with_hooks(tmp_path: Path) -> Path:
    """Create a fake repo with a .convertible/hooks.json."""
    dotdir = tmp_path / ".convertible"
    dotdir.mkdir()
    (dotdir / "hooks.json").write_text(json.dumps(HOOKS_JSON), encoding="utf-8")
    return tmp_path


def _make_script(path: Path, content: str) -> Path:
    """Write an executable shell script and return its path."""
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


# ---------------------------------------------------------------------------
# 1. load_hooks + hooks_for
# ---------------------------------------------------------------------------


class TestLoadHooks:
    def test_parses_all_events(self, repo_with_hooks: Path) -> None:
        cfg = load_hooks(repo_with_hooks)
        assert isinstance(cfg, HookConfig)

    def test_pre_tool_run_command_selected(self, repo_with_hooks: Path) -> None:
        cfg = load_hooks(repo_with_hooks)
        entries = cfg.hooks_for("pre_tool", tool="run_command")
        assert len(entries) == 1
        assert entries[0].command == "echo pre-run"
        assert entries[0].matcher == "run_command"

    def test_pre_tool_write_file_selected(self, repo_with_hooks: Path) -> None:
        cfg = load_hooks(repo_with_hooks)
        entries = cfg.hooks_for("pre_tool", tool="write_file")
        assert len(entries) == 1
        assert entries[0].command == "echo pre-write"

    def test_pre_tool_no_match_excluded(self, repo_with_hooks: Path) -> None:
        cfg = load_hooks(repo_with_hooks)
        entries = cfg.hooks_for("pre_tool", tool="read_file")
        assert entries == []

    def test_post_tool_empty_matcher_matches_all(self, repo_with_hooks: Path) -> None:
        """An empty matcher string matches every tool."""
        cfg = load_hooks(repo_with_hooks)
        # write_file matches the specific entry AND the empty-matcher catch-all
        entries = cfg.hooks_for("post_tool", tool="write_file")
        commands = [e.command for e in entries]
        assert "echo post-write" in commands
        assert "echo post-all" in commands

    def test_post_tool_catch_all_for_unknown_tool(self, repo_with_hooks: Path) -> None:
        """Empty matcher catches tools not explicitly listed."""
        cfg = load_hooks(repo_with_hooks)
        entries = cfg.hooks_for("post_tool", tool="list_dir")
        assert len(entries) == 1
        assert entries[0].command == "echo post-all"

    def test_task_start_no_tool(self, repo_with_hooks: Path) -> None:
        """task_start events have no tool; matcher is ignored (always match)."""
        cfg = load_hooks(repo_with_hooks)
        entries = cfg.hooks_for("task_start")
        assert len(entries) == 1
        assert entries[0].command == "echo start"

    def test_finish_matcher_ignored(self, repo_with_hooks: Path) -> None:
        """finish events: matcher present but always matches (non-tool event)."""
        cfg = load_hooks(repo_with_hooks)
        entries = cfg.hooks_for("finish")
        # Both finish entries should be returned regardless of matcher
        assert len(entries) == 2

    def test_missing_hooks_json_returns_empty(self, tmp_path: Path) -> None:
        cfg = load_hooks(tmp_path)
        assert isinstance(cfg, HookConfig)
        assert cfg.hooks_for("pre_tool", tool="run_command") == []
        assert cfg.hooks_for("task_start") == []

    def test_missing_convertible_dir_returns_empty(self, tmp_path: Path) -> None:
        cfg = load_hooks(tmp_path / "nonexistent_repo")
        assert isinstance(cfg, HookConfig)
        assert cfg.hooks_for("finish") == []

    def test_malformed_json_returns_empty(self, tmp_path: Path) -> None:
        dotdir = tmp_path / ".convertible"
        dotdir.mkdir()
        (dotdir / "hooks.json").write_text("not valid json {{", encoding="utf-8")
        cfg = load_hooks(tmp_path)
        assert isinstance(cfg, HookConfig)
        assert cfg.hooks_for("pre_tool", tool="run_command") == []

    def test_entry_order_preserved(self, repo_with_hooks: Path) -> None:
        cfg = load_hooks(repo_with_hooks)
        entries = cfg.hooks_for("post_tool", tool="write_file")
        # post-write must come before post-all (declared order)
        assert entries[0].command == "echo post-write"
        assert entries[1].command == "echo post-all"

    def test_hookentry_fields(self, repo_with_hooks: Path) -> None:
        cfg = load_hooks(repo_with_hooks)
        entry = cfg.hooks_for("pre_tool", tool="run_command")[0]
        assert isinstance(entry, HookEntry)
        assert entry.event == "pre_tool"
        assert entry.matcher == "run_command"
        assert entry.command == "echo pre-run"

    def test_user_level_fallback(self, tmp_path: Path) -> None:
        """User-level hooks.json is picked up when no repo-level file exists."""
        user_home = tmp_path / "home"
        user_dotdir = user_home / ".convertible"
        user_dotdir.mkdir(parents=True)
        user_hooks = {"hooks": {"task_start": [{"command": "echo user-start"}]}}
        (user_dotdir / "hooks.json").write_text(json.dumps(user_hooks), encoding="utf-8")

        repo = tmp_path / "myrepo"
        repo.mkdir()

        cfg = load_hooks(repo, user_home=user_home)
        entries = cfg.hooks_for("task_start")
        assert len(entries) == 1
        assert entries[0].command == "echo user-start"

    def test_repo_level_shadows_user_level(self, tmp_path: Path) -> None:
        """Repo-level hooks.json takes precedence over user-level."""
        user_home = tmp_path / "home"
        user_dotdir = user_home / ".convertible"
        user_dotdir.mkdir(parents=True)
        user_hooks = {"hooks": {"task_start": [{"command": "echo user-start"}]}}
        (user_dotdir / "hooks.json").write_text(json.dumps(user_hooks), encoding="utf-8")

        repo = tmp_path / "myrepo"
        repo_dotdir = repo / ".convertible"
        repo_dotdir.mkdir(parents=True)
        repo_hooks = {"hooks": {"task_start": [{"command": "echo repo-start"}]}}
        (repo_dotdir / "hooks.json").write_text(json.dumps(repo_hooks), encoding="utf-8")

        cfg = load_hooks(repo, user_home=user_home)
        entries = cfg.hooks_for("task_start")
        assert len(entries) == 1
        assert entries[0].command == "echo repo-start"


# ---------------------------------------------------------------------------
# 2. run_hook outcomes
# ---------------------------------------------------------------------------


class TestRunHookOutcomes:
    """Table-driven tests covering deny, rewrite, and allow paths."""

    def test_exit_nonzero_gives_deny_with_stderr(self, tmp_path: Path) -> None:
        entry = HookEntry(
            event="pre_tool", matcher="run_command", command="sh -c 'echo bad >&2; exit 1'"
        )
        payload = {
            "event": "pre_tool",
            "tool": "run_command",
            "arguments": {"command": "rm -rf /"},
            "task_id": "abc123",
            "repo_path": str(tmp_path),
        }
        decision = run_hook(entry, payload, cwd=str(tmp_path))
        assert isinstance(decision, HookDecision)
        assert decision.decision == "deny"
        assert "bad" in decision.reason
        assert decision.exit_code == 1

    def test_exit_nonzero_falls_back_to_stdout_for_reason(self, tmp_path: Path) -> None:
        """When stderr is empty, reason should come from stdout."""
        entry = HookEntry(
            event="pre_tool", matcher="run_command", command="sh -c 'echo stdout-only; exit 2'"
        )
        payload = {
            "event": "pre_tool",
            "tool": "run_command",
            "arguments": {},
            "task_id": "t",
            "repo_path": str(tmp_path),
        }
        decision = run_hook(entry, payload, cwd=str(tmp_path))
        assert decision.decision == "deny"
        assert "stdout-only" in decision.reason
        assert decision.exit_code == 2

    def test_exit_zero_empty_stdout_gives_allow(self, tmp_path: Path) -> None:
        entry = HookEntry(event="post_tool", matcher="write_file", command="sh -c 'exit 0'")
        payload = {
            "event": "post_tool",
            "tool": "write_file",
            "arguments": {},
            "task_id": "t",
            "repo_path": str(tmp_path),
        }
        decision = run_hook(entry, payload, cwd=str(tmp_path))
        assert decision.decision == "allow"
        assert decision.exit_code == 0

    def test_exit_zero_nonjson_stdout_gives_allow(self, tmp_path: Path) -> None:
        entry = HookEntry(
            event="post_tool", matcher="write_file", command="sh -c 'echo just a message'"
        )
        payload = {
            "event": "post_tool",
            "tool": "write_file",
            "arguments": {},
            "task_id": "t",
            "repo_path": str(tmp_path),
        }
        decision = run_hook(entry, payload, cwd=str(tmp_path))
        assert decision.decision == "allow"

    def test_exit_zero_json_deny_gives_deny(self, tmp_path: Path) -> None:
        json_out = json.dumps({"decision": "deny", "reason": "blocked by policy"})
        script = tmp_path / "deny_hook.sh"
        _make_script(script, f"#!/bin/sh\nprintf '%s' '{json_out}'\n")
        entry2 = HookEntry(event="pre_tool", matcher="run_command", command=str(script))
        payload = {
            "event": "pre_tool",
            "tool": "run_command",
            "arguments": {},
            "task_id": "t",
            "repo_path": str(tmp_path),
        }
        decision = run_hook(entry2, payload, cwd=str(tmp_path))
        assert decision.decision == "deny"
        assert decision.reason == "blocked by policy"
        assert decision.exit_code == 0

    def test_exit_zero_json_rewrite_carries_arguments(self, tmp_path: Path) -> None:
        new_args = {"command": "echo safe"}
        json_out = json.dumps({"decision": "rewrite", "arguments": new_args})
        script = tmp_path / "rewrite_hook.sh"
        _make_script(script, f"#!/bin/sh\necho '{json_out}'\n")
        entry = HookEntry(event="pre_tool", matcher="run_command", command=str(script))
        payload = {
            "event": "pre_tool",
            "tool": "run_command",
            "arguments": {"command": "rm -rf /"},
            "task_id": "t",
            "repo_path": str(tmp_path),
        }
        decision = run_hook(entry, payload, cwd=str(tmp_path))
        assert decision.decision == "rewrite"
        assert decision.arguments == new_args
        assert decision.exit_code == 0

    def test_exit_zero_json_allow_explicit(self, tmp_path: Path) -> None:
        json_out = json.dumps({"decision": "allow"})
        script = tmp_path / "allow_hook.sh"
        _make_script(script, f"#!/bin/sh\necho '{json_out}'\n")
        entry = HookEntry(event="pre_tool", matcher="run_command", command=str(script))
        payload = {
            "event": "pre_tool",
            "tool": "run_command",
            "arguments": {},
            "task_id": "t",
            "repo_path": str(tmp_path),
        }
        decision = run_hook(entry, payload, cwd=str(tmp_path))
        assert decision.decision == "allow"

    def test_exit_zero_json_empty_object_gives_allow(self, tmp_path: Path) -> None:
        script = tmp_path / "empty_hook.sh"
        _make_script(script, "#!/bin/sh\necho '{}'\n")
        entry = HookEntry(event="task_start", command=str(script))
        payload = {
            "event": "task_start",
            "tool": None,
            "arguments": {},
            "task_id": "t",
            "repo_path": str(tmp_path),
        }
        decision = run_hook(entry, payload, cwd=str(tmp_path))
        assert decision.decision == "allow"

    def test_additional_context_propagated(self, tmp_path: Path) -> None:
        json_out = json.dumps({"decision": "allow", "additionalContext": "note for the model"})
        script = tmp_path / "ctx_hook.sh"
        _make_script(script, f"#!/bin/sh\necho '{json_out}'\n")
        entry = HookEntry(event="post_tool", command=str(script))
        payload = {
            "event": "post_tool",
            "tool": "write_file",
            "arguments": {},
            "task_id": "t",
            "repo_path": str(tmp_path),
        }
        decision = run_hook(entry, payload, cwd=str(tmp_path))
        assert decision.decision == "allow"
        assert decision.additional_context == "note for the model"

    def test_additional_context_on_deny(self, tmp_path: Path) -> None:
        json_out = json.dumps(
            {"decision": "deny", "reason": "nope", "additionalContext": "context here"}
        )
        script = tmp_path / "deny_ctx_hook.sh"
        _make_script(script, f"#!/bin/sh\necho '{json_out}'\n")
        entry = HookEntry(event="pre_tool", command=str(script))
        payload = {
            "event": "pre_tool",
            "tool": "run_command",
            "arguments": {},
            "task_id": "t",
            "repo_path": str(tmp_path),
        }
        decision = run_hook(entry, payload, cwd=str(tmp_path))
        assert decision.decision == "deny"
        assert decision.additional_context == "context here"


# ---------------------------------------------------------------------------
# 3. JSON payload reaches hook on stdin
# ---------------------------------------------------------------------------


class TestStdinPayload:
    def test_payload_keys_present_on_stdin(self, tmp_path: Path) -> None:
        """A hook that captures stdin must receive all documented keys."""
        received_file = tmp_path / "received.json"
        script = tmp_path / "capture_stdin.sh"
        _make_script(
            script,
            f"#!/bin/sh\ncat > '{received_file}'\n",
        )
        entry = HookEntry(event="pre_tool", matcher="run_command", command=str(script))
        payload = {
            "event": "pre_tool",
            "tool": "run_command",
            "arguments": {"command": "ls"},
            "task_id": "task-abc",
            "repo_path": str(tmp_path),
        }
        decision = run_hook(entry, payload, cwd=str(tmp_path))

        assert received_file.exists(), "hook did not write stdin to file"
        received = json.loads(received_file.read_text())
        for key in ("event", "tool", "arguments", "task_id", "repo_path"):
            assert key in received, f"missing key '{key}' in stdin payload"

        assert received["event"] == "pre_tool"
        assert received["tool"] == "run_command"
        assert received["arguments"] == {"command": "ls"}
        assert received["task_id"] == "task-abc"
        assert received["repo_path"] == str(tmp_path)

        # The hook exited 0 with no stdout → allow
        assert decision.decision == "allow"

    def test_payload_for_task_start_has_null_tool(self, tmp_path: Path) -> None:
        received_file = tmp_path / "received_start.json"
        script = tmp_path / "capture_start.sh"
        _make_script(script, f"#!/bin/sh\ncat > '{received_file}'\n")
        entry = HookEntry(event="task_start", command=str(script))
        payload = {
            "event": "task_start",
            "tool": None,
            "arguments": {},
            "task_id": "task-xyz",
            "repo_path": str(tmp_path),
        }
        run_hook(entry, payload, cwd=str(tmp_path))
        received = json.loads(received_file.read_text())
        assert received["tool"] is None
        assert received["event"] == "task_start"


# ---------------------------------------------------------------------------
# 4. HookEntry / HookDecision dataclass structure
# ---------------------------------------------------------------------------


class TestDataclasses:
    def test_hook_entry_defaults(self) -> None:
        entry = HookEntry(event="pre_tool")
        assert entry.matcher == ""
        assert entry.command == ""

    def test_hook_entry_full(self) -> None:
        entry = HookEntry(event="pre_tool", matcher="run_command", command="echo hi")
        assert entry.event == "pre_tool"
        assert entry.matcher == "run_command"
        assert entry.command == "echo hi"

    def test_hook_decision_defaults(self) -> None:
        d = HookDecision(decision="allow")
        assert d.arguments is None
        assert d.reason == ""
        assert d.additional_context == ""
        assert d.exit_code is None

    def test_hook_decision_full(self) -> None:
        d = HookDecision(
            decision="rewrite",
            arguments={"command": "ls"},
            reason="rewrote it",
            additional_context="ctx",
            exit_code=0,
        )
        assert d.decision == "rewrite"
        assert d.arguments == {"command": "ls"}
        assert d.reason == "rewrote it"
        assert d.additional_context == "ctx"
        assert d.exit_code == 0
