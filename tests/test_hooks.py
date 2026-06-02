"""Tests for colleague/hooks.py — hook config loader and runner (t4).

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

from colleague.hooks import (
    HookConfig,
    HookDecision,
    HookEntry,
    load_hooks,
    run_hook,
)
from colleague.layers import sanitize_model

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
    """Create a fake repo with a .colleague/hooks.json."""
    dotdir = tmp_path / ".colleague"
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

    def test_missing_colleague_dir_returns_empty(self, tmp_path: Path) -> None:
        cfg = load_hooks(tmp_path / "nonexistent_repo")
        assert isinstance(cfg, HookConfig)
        assert cfg.hooks_for("finish") == []

    def test_malformed_json_returns_empty(self, tmp_path: Path) -> None:
        dotdir = tmp_path / ".colleague"
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
        user_dotdir = user_home / ".colleague"
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
        user_dotdir = user_home / ".colleague"
        user_dotdir.mkdir(parents=True)
        user_hooks = {"hooks": {"task_start": [{"command": "echo user-start"}]}}
        (user_dotdir / "hooks.json").write_text(json.dumps(user_hooks), encoding="utf-8")

        repo = tmp_path / "myrepo"
        repo_dotdir = repo / ".colleague"
        repo_dotdir.mkdir(parents=True)
        repo_hooks = {"hooks": {"task_start": [{"command": "echo repo-start"}]}}
        (repo_dotdir / "hooks.json").write_text(json.dumps(repo_hooks), encoding="utf-8")

        cfg = load_hooks(repo, user_home=user_home)
        entries = cfg.hooks_for("task_start")
        assert len(entries) == 1
        assert entries[0].command == "echo repo-start"


# ---------------------------------------------------------------------------
# 1b. Per-model hooks overlay (t1)
# ---------------------------------------------------------------------------


def _write_hooks(dotdir: Path, relative: str, payload: dict) -> Path:
    """Write a hooks.json under *dotdir*/*relative* and return its path."""
    path = dotdir / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class TestPerModelHooksOverlay:
    """Per-model overlay composition for ``load_hooks(repo, model=...)`` (t1).

    Before-state baseline (the gap t1 closes): pre-change ``load_hooks`` had no
    ``model`` parameter — its signature was ``load_hooks(repo_path, *,
    user_home=None)``. There was no way to layer a model-specific
    ``.colleague/<model>/hooks.json`` ahead of the base ``.colleague/
    hooks.json``. t1 adds the keyword-only ``model`` parameter and the
    per-model-first composition exercised below.
    """

    # --- Criterion 1: per-model entries merge BEFORE base entries -----------

    def test_per_model_entries_prepended_before_base(self, repo_with_hooks: Path) -> None:
        """`.colleague/<model>/hooks.json` entries come before base entries.

        The base fixture has one ``pre_tool`` ``run_command`` entry
        (``echo pre-run``). A per-model overlay adds another ``run_command``
        entry; ``hooks_for`` must return the per-model entry first so the
        loop's "first deny/rewrite wins" gives the per-model fix priority.
        """
        model = "Qwen/Qwen3-32B"
        safe = sanitize_model(model)
        overlay = {
            "hooks": {
                "pre_tool": [
                    {"matcher": "run_command", "command": "echo model-run"},
                ],
            }
        }
        _write_hooks(repo_with_hooks / ".colleague", f"{safe}/hooks.json", overlay)

        cfg = load_hooks(repo_with_hooks, model=model)
        entries = cfg.hooks_for("pre_tool", tool="run_command")
        assert [e.command for e in entries] == ["echo model-run", "echo pre-run"]
        # The per-model match is first.
        assert entries[0].command == "echo model-run"

    def test_per_model_first_across_events(self, repo_with_hooks: Path) -> None:
        """Per-model-first holds for every event, not just pre_tool."""
        model = "myco/Model-X"
        safe = sanitize_model(model)
        overlay = {
            "hooks": {
                "task_start": [{"command": "echo model-start"}],
                "finish": [{"command": "echo model-done"}],
            }
        }
        _write_hooks(repo_with_hooks / ".colleague", f"{safe}/hooks.json", overlay)

        cfg = load_hooks(repo_with_hooks, model=model)

        start = cfg.hooks_for("task_start")
        assert start[0].command == "echo model-start"
        assert start[-1].command == "echo start"  # base entry still present, after

        finish = cfg.hooks_for("finish")
        assert finish[0].command == "echo model-done"
        # Base finish entries (2) still follow the per-model one.
        assert [e.command for e in finish[1:]] == ["echo done", "echo done-matcher"]

    def test_per_model_only_event_present(self, repo_with_hooks: Path) -> None:
        """An event present only in the overlay is exposed too."""
        model = "solo"
        overlay = {"hooks": {"post_tool": [{"matcher": "", "command": "echo model-post"}]}}
        _write_hooks(repo_with_hooks / ".colleague", f"{sanitize_model(model)}/hooks.json", overlay)

        cfg = load_hooks(repo_with_hooks, model=model)
        entries = cfg.hooks_for("post_tool", tool="read_file")
        # Per-model catch-all first, then base catch-all (echo post-all).
        assert entries[0].command == "echo model-post"
        assert "echo post-all" in [e.command for e in entries]

    # --- Criterion 2: exact-construction via sanitize_model, no sibling glob -

    def test_sibling_model_overlay_never_loaded(self, repo_with_hooks: Path) -> None:
        """A fix under `.colleague/Y/hooks.json` is invisible when model='X'.

        The per-model path is exact-constructed via ``sanitize_model`` — sibling
        ``.colleague/*/`` directories are never globbed. We place an overlay
        under model ``Y`` and drive with model ``X``; the overlay must NOT load.
        """
        # Overlay belongs to a *different* model "other-model".
        _write_hooks(
            repo_with_hooks / ".colleague",
            f"{sanitize_model('other-model')}/hooks.json",
            {"hooks": {"pre_tool": [{"matcher": "run_command", "command": "echo SIBLING"}]}},
        )

        cfg = load_hooks(repo_with_hooks, model="my-model")
        entries = cfg.hooks_for("pre_tool", tool="run_command")
        # Only the base entry — the sibling overlay must never leak in.
        assert [e.command for e in entries] == ["echo pre-run"]
        assert "echo SIBLING" not in [e.command for e in entries]

    def test_model_path_uses_sanitize_model(self, repo_with_hooks: Path) -> None:
        """The overlay dir name is the sanitized token, not the raw model id."""
        model = "Qwen/Qwen3-32B"
        safe = sanitize_model(model)
        assert safe == "Qwen-Qwen3-32B"  # constructed token, slash collapsed
        # Write at the sanitized path — this is the only path that should load.
        _write_hooks(
            repo_with_hooks / ".colleague",
            f"{safe}/hooks.json",
            {"hooks": {"finish": [{"command": "echo model-done"}]}},
        )
        cfg = load_hooks(repo_with_hooks, model=model)
        assert cfg.hooks_for("finish")[0].command == "echo model-done"

    # --- Criterion 3: strict no-op (model=None or no overlay file) ----------

    def test_model_none_is_byte_identical_to_base(self, repo_with_hooks: Path) -> None:
        """`load_hooks(repo)` and `load_hooks(repo, model=None)` are identical."""
        base = load_hooks(repo_with_hooks)
        with_none = load_hooks(repo_with_hooks, model=None)
        assert with_none == base

    def test_model_with_no_overlay_is_byte_identical_to_base(self, repo_with_hooks: Path) -> None:
        """A model whose overlay file is absent yields the base-only config."""
        base = load_hooks(repo_with_hooks)
        # No `.colleague/<model>/hooks.json` exists for this model.
        with_model = load_hooks(repo_with_hooks, model="model-without-overlay")
        assert with_model == base

    def test_default_signature_unchanged_for_existing_callers(self, repo_with_hooks: Path) -> None:
        """Existing positional/keyword call shape still works (no behavior change)."""
        cfg = load_hooks(repo_with_hooks)
        # Same selection an existing caller would observe today.
        entries = cfg.hooks_for("pre_tool", tool="run_command")
        assert [e.command for e in entries] == ["echo pre-run"]

    def test_per_model_overlay_respects_repo_over_user_precedence(self, tmp_path: Path) -> None:
        """Per-model overlay resolves repo-over-user via the same configdir path."""
        model = "my-model"
        safe = sanitize_model(model)

        user_home = tmp_path / "home"
        user_dotdir = user_home / ".colleague"
        _write_hooks(
            user_dotdir,
            f"{safe}/hooks.json",
            {"hooks": {"pre_tool": [{"matcher": "run_command", "command": "echo user-model"}]}},
        )

        repo = tmp_path / "myrepo"
        repo_dotdir = repo / ".colleague"
        # Base repo hooks present so we can observe ordering.
        _write_hooks(
            repo_dotdir,
            "hooks.json",
            {"hooks": {"pre_tool": [{"matcher": "run_command", "command": "echo base"}]}},
        )
        _write_hooks(
            repo_dotdir,
            f"{safe}/hooks.json",
            {"hooks": {"pre_tool": [{"matcher": "run_command", "command": "echo repo-model"}]}},
        )

        cfg = load_hooks(repo, model=model, user_home=user_home)
        entries = cfg.hooks_for("pre_tool", tool="run_command")
        # Repo overlay shadows the user overlay (resolve_file precedence), and
        # the per-model overlay is prepended before the base repo entry.
        assert [e.command for e in entries] == ["echo repo-model", "echo base"]
        assert "echo user-model" not in [e.command for e in entries]

    def test_per_model_user_level_fallback(self, tmp_path: Path) -> None:
        """When no repo overlay exists, the user-level per-model overlay loads."""
        model = "my-model"
        safe = sanitize_model(model)

        user_home = tmp_path / "home"
        _write_hooks(
            user_home / ".colleague",
            f"{safe}/hooks.json",
            {"hooks": {"task_start": [{"command": "echo user-model-start"}]}},
        )

        repo = tmp_path / "myrepo"
        repo.mkdir()

        cfg = load_hooks(repo, model=model, user_home=user_home)
        entries = cfg.hooks_for("task_start")
        assert [e.command for e in entries] == ["echo user-model-start"]

    # --- Criterion 4: malformed per-model hooks.json is skipped -------------

    def test_malformed_per_model_json_is_skipped(self, repo_with_hooks: Path) -> None:
        """A malformed per-model hooks.json is skipped, never raises.

        The result must degrade to the base-only config (the broken overlay
        contributes nothing), mirroring the base loader's try/except resilience.
        """
        model = "broken-model"
        safe = sanitize_model(model)
        path = repo_with_hooks / ".colleague" / safe / "hooks.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not valid json {{", encoding="utf-8")

        base = load_hooks(repo_with_hooks)
        cfg = load_hooks(repo_with_hooks, model=model)  # must not raise
        assert cfg == base

    def test_malformed_per_model_json_with_no_base_returns_empty(self, tmp_path: Path) -> None:
        """Malformed overlay + no base → empty config, no raise."""
        model = "broken-model"
        safe = sanitize_model(model)
        repo = tmp_path / "myrepo"
        path = repo / ".colleague" / safe / "hooks.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ broken", encoding="utf-8")

        cfg = load_hooks(repo, model=model)
        assert isinstance(cfg, HookConfig)
        assert cfg.hooks_for("pre_tool", tool="run_command") == []


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
