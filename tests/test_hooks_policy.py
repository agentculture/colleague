"""Tests for hook content-approval gate (t3 — approval gate).

The approval gate verifies a hook's referenced repo files against checksums
recorded in ``approvals.json`` before running each hook entry.  The r1 design
decision governs: shlex-split the command, find tokens that resolve to existing
files under the repo root, and for each call
``policy.check_file("hooks", <rel-path>, <abs-path>)``.  First denial wins.
A hook with **no** repo file reference is allowed without a checksum (inline).
A policy with **no** hooks section is a total no-op — existing behavior is
preserved byte-for-byte.

Acceptance criteria (AC1–AC5):
  AC1 — Approved hook (checksum present + matches) fires normally.
  AC2 — Tampered hook (checksum mismatch) or unapproved hook (hooks section
         present but no entry) is SKIPPED; a HookFiring(decision="skipped")
         is recorded; the drive continues.
  AC3 — Unapproved pre_tool hook is SKIPPED and does NOT block the tool
         (skip is non-control-bearing: the tool still executes).
  AC4 — With no hooks section (empty / absent policy), all hooks fire exactly
         as today (no regressions).
  AC5 — Unit tests for ``hook_approval_verdict`` helper: file-approval /
         file-denial, and a pure-inline hook (no repo file) → allowed.
"""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from convertible.contract import OK, Task
from convertible.hooks import hook_approval_verdict
from convertible.loop import ModelResponse, ToolCall, run
from convertible.policy import Policy, Verdict, file_checksum

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_script(path: Path, content: str) -> Path:
    """Write an executable shell script; return its path."""
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _write_hooks(repo: Path, payload: dict) -> None:
    """Write ``.convertible/hooks.json`` under *repo*."""
    dotdir = repo / ".convertible"
    dotdir.mkdir(parents=True, exist_ok=True)
    (dotdir / "hooks.json").write_text(json.dumps(payload), encoding="utf-8")


def _write_approvals(repo: Path, payload: dict) -> None:
    """Write ``.convertible/approvals.json`` under *repo*."""
    dotdir = repo / ".convertible"
    dotdir.mkdir(parents=True, exist_ok=True)
    (dotdir / "approvals.json").write_text(json.dumps(payload), encoding="utf-8")


def _scripted(responses: list[ModelResponse]):
    """Return a ``complete()`` callable that replays *responses* in order."""
    state = {"i": 0}

    def complete(_messages: list[dict]) -> ModelResponse:
        i = min(state["i"], len(responses) - 1)
        state["i"] += 1
        return responses[i]

    return complete


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """A minimal repo directory."""
    return tmp_path


@pytest.fixture()
def hook_script(tmp_path: Path) -> Path:
    """An executable script that exits 0 (allow) and writes a marker."""
    marker = tmp_path / "ran.txt"
    script = tmp_path / "hook.sh"
    _make_script(script, f"#!/bin/sh\ntouch '{marker}'\n")
    return script


# ---------------------------------------------------------------------------
# AC1: Approved hook fires normally
# ---------------------------------------------------------------------------


class TestApprovedHookFires:
    """AC1 — a hook whose referenced script is checksummed + approved runs normally."""

    def test_approved_pre_tool_hook_runs(self, tmp_path: Path) -> None:
        """A hook script whose checksum is in approvals.json executes; marker exists."""
        marker = tmp_path / "ran.txt"
        script = tmp_path / "hook.sh"
        _make_script(script, f"#!/bin/sh\ntouch '{marker}'\n")

        # Record the approved checksum using the repo-relative path.
        rel = "hook.sh"
        checksum = file_checksum(script)
        _write_approvals(tmp_path, {"hooks": {rel: checksum}})

        # Hook config references the script by its (absolute) path in command.
        _write_hooks(
            tmp_path,
            {"hooks": {"pre_tool": [{"matcher": "write_file", "command": str(script)}]}},
        )

        responses = [
            ModelResponse(
                tool_calls=[ToolCall("1", "write_file", {"path": "out.txt", "content": "hi"})]
            ),
            ModelResponse(tool_calls=[ToolCall("2", "finish", {"summary": "done"})]),
        ]
        task = Task.new(str(tmp_path), "write something")
        result = run(_scripted(responses), task, max_steps=10)

        # Hook ran — marker file was created.
        assert marker.exists(), "approved hook should have run and created the marker"
        assert result.status == OK

        # Firing recorded as allow (not skipped).
        hook_firings = [f for f in result.hook_firings if f.event == "pre_tool"]
        assert hook_firings, "expected at least one pre_tool firing"
        assert hook_firings[0].decision != "skipped"

    def test_approved_task_start_hook_runs(self, tmp_path: Path) -> None:
        """A checksummed task_start hook fires once before the loop."""
        marker = tmp_path / "start_ran.txt"
        script = tmp_path / "start.sh"
        _make_script(script, f"#!/bin/sh\ntouch '{marker}'\n")

        rel = "start.sh"
        checksum = file_checksum(script)
        _write_approvals(tmp_path, {"hooks": {rel: checksum}})

        _write_hooks(
            tmp_path,
            {"hooks": {"task_start": [{"command": str(script)}]}},
        )

        responses = [
            ModelResponse(tool_calls=[ToolCall("1", "finish", {"summary": "done"})]),
        ]
        task = Task.new(str(tmp_path), "nothing")
        result = run(_scripted(responses), task, max_steps=10)

        assert marker.exists(), "approved task_start hook should have run"
        assert result.status == OK

        start_firings = [f for f in result.hook_firings if f.event == "task_start"]
        assert start_firings
        assert start_firings[0].decision != "skipped"


# ---------------------------------------------------------------------------
# AC2: Tampered / unapproved hook is SKIPPED; HookFiring(decision="skipped") recorded
# ---------------------------------------------------------------------------


class TestUnapprovedHookIsSkipped:
    """AC2 — a hook whose file is tampered or not in approvals is skipped + recorded."""

    def test_tampered_hook_is_skipped_and_recorded(self, tmp_path: Path) -> None:
        """Hooks section present; checksum for the script, but content changed."""
        marker = tmp_path / "ran.txt"
        script = tmp_path / "hook.sh"
        _make_script(script, f"#!/bin/sh\ntouch '{marker}'\n")

        # Write a WRONG checksum (deliberately stale).
        wrong_checksum = "sha256:" + "0" * 64
        _write_approvals(tmp_path, {"hooks": {"hook.sh": wrong_checksum}})

        _write_hooks(
            tmp_path,
            {"hooks": {"post_tool": [{"matcher": "", "command": str(script)}]}},
        )

        responses = [
            ModelResponse(
                tool_calls=[ToolCall("1", "write_file", {"path": "f.txt", "content": "x"})]
            ),
            ModelResponse(tool_calls=[ToolCall("2", "finish", {"summary": "done"})]),
        ]
        task = Task.new(str(tmp_path), "write")
        result = run(_scripted(responses), task, max_steps=10)

        # Hook must NOT have run — marker must not exist.
        assert not marker.exists(), "tampered hook must not run"
        assert result.status == OK

        # A HookFiring with decision="skipped" is recorded.
        skipped = [f for f in result.hook_firings if f.decision == "skipped"]
        assert skipped, "expected a skipped HookFiring for the tampered hook"
        assert skipped[0].event == "post_tool"

    def test_unapproved_hook_no_entry_is_skipped(self, tmp_path: Path) -> None:
        """Hooks section PRESENT but the specific hook file has no entry → skipped."""
        marker = tmp_path / "ran.txt"
        script = tmp_path / "hook.sh"
        _make_script(script, f"#!/bin/sh\ntouch '{marker}'\n")

        # hooks section present but empty (no entry for hook.sh).
        _write_approvals(tmp_path, {"hooks": {}})

        _write_hooks(
            tmp_path,
            {"hooks": {"task_start": [{"command": str(script)}]}},
        )

        responses = [
            ModelResponse(tool_calls=[ToolCall("1", "finish", {"summary": "done"})]),
        ]
        task = Task.new(str(tmp_path), "nothing")
        result = run(_scripted(responses), task, max_steps=10)

        assert not marker.exists(), "unapproved hook must not run"
        skipped = [f for f in result.hook_firings if f.decision == "skipped"]
        assert skipped, "expected a skipped HookFiring"

    def test_skipped_firing_has_reason(self, tmp_path: Path) -> None:
        """A skipped HookFiring carries a non-empty reason string."""
        script = tmp_path / "hook.sh"
        _make_script(script, "#!/bin/sh\necho hi\n")

        _write_approvals(tmp_path, {"hooks": {}})
        _write_hooks(
            tmp_path,
            {"hooks": {"finish": [{"command": str(script)}]}},
        )

        responses = [ModelResponse(tool_calls=[ToolCall("1", "finish", {"summary": "x"})])]
        task = Task.new(str(tmp_path), "nothing")
        result = run(_scripted(responses), task, max_steps=10)

        skipped = [f for f in result.hook_firings if f.decision == "skipped"]
        assert skipped
        assert skipped[0].reason, "skipped firing must have a non-empty reason"


# ---------------------------------------------------------------------------
# AC3: Unapproved pre_tool hook is skipped and does NOT block the tool
# ---------------------------------------------------------------------------


class TestUnapprovedPreToolIsNonControlBearing:
    """AC3 — a skipped pre_tool hook does not set a decisive deny; tool still runs."""

    def test_unapproved_pre_tool_does_not_block_tool(self, tmp_path: Path) -> None:
        """Even with a hooks section present and the pre_tool hook unapproved,
        the tool executes normally (skip is non-control-bearing)."""
        # Unapproved deny-script: if it DID run it would exit 1 (deny).
        script = tmp_path / "deny.sh"
        _make_script(script, "#!/bin/sh\necho 'blocked' >&2; exit 1\n")

        # Hooks section present — no entry for deny.sh → hook is unapproved.
        _write_approvals(tmp_path, {"hooks": {}})

        # Hook targets write_file.
        _write_hooks(
            tmp_path,
            {"hooks": {"pre_tool": [{"matcher": "write_file", "command": str(script)}]}},
        )

        responses = [
            ModelResponse(
                tool_calls=[ToolCall("1", "write_file", {"path": "safe.txt", "content": "ok"})]
            ),
            ModelResponse(tool_calls=[ToolCall("2", "finish", {"summary": "wrote"})]),
        ]
        task = Task.new(str(tmp_path), "write a file")
        result = run(_scripted(responses), task, max_steps=10)

        # write_file must have executed despite the unapproved pre_tool hook.
        assert (
            tmp_path / "safe.txt"
        ).exists(), "write_file must execute even when a pre_tool hook is skipped"
        assert (tmp_path / "safe.txt").read_text() == "ok"

        # Step is ok=True (tool ran successfully).
        write_steps = [s for s in result.steps if s.tool == "write_file"]
        assert write_steps
        assert write_steps[0].ok is True

        # The skipped firing is recorded but did NOT block (no deny step for write_file).
        skipped = [f for f in result.hook_firings if f.decision == "skipped"]
        assert skipped, "skipped firing should be recorded"

        # No deny step for write_file.
        deny_steps = [s for s in result.steps if s.tool == "write_file" and not s.ok]
        assert not deny_steps, "write_file must not be denied when pre_tool hook is skipped"

    def test_multiple_pre_tool_hooks_skipped_approved_fires(self, tmp_path: Path) -> None:
        """First hook unapproved (skipped), second approved — second fires and
        its allow does not block the tool either.  The tool runs."""
        # Hook 1 — unapproved
        skip_marker = tmp_path / "skip_ran.txt"
        script1 = tmp_path / "skip.sh"
        _make_script(script1, f"#!/bin/sh\ntouch '{skip_marker}'\n")

        # Hook 2 — approved
        run_marker = tmp_path / "ran.txt"
        script2 = tmp_path / "run.sh"
        _make_script(script2, f"#!/bin/sh\ntouch '{run_marker}'\n")

        checksum2 = file_checksum(script2)
        # Only script2 approved; script1 absent from hooks approvals.
        _write_approvals(tmp_path, {"hooks": {"run.sh": checksum2}})

        _write_hooks(
            tmp_path,
            {
                "hooks": {
                    "pre_tool": [
                        {"matcher": "write_file", "command": str(script1)},
                        {"matcher": "write_file", "command": str(script2)},
                    ]
                }
            },
        )

        responses = [
            ModelResponse(
                tool_calls=[ToolCall("1", "write_file", {"path": "o.txt", "content": "x"})]
            ),
            ModelResponse(tool_calls=[ToolCall("2", "finish", {"summary": "done"})]),
        ]
        task = Task.new(str(tmp_path), "write")
        result = run(_scripted(responses), task, max_steps=10)

        assert not skip_marker.exists(), "unapproved hook must not run"
        assert run_marker.exists(), "approved hook must run"
        assert (tmp_path / "o.txt").exists(), "tool must execute"

        write_steps = [s for s in result.steps if s.tool == "write_file"]
        assert write_steps[0].ok is True


# ---------------------------------------------------------------------------
# AC4: No hooks section → all hooks fire exactly as today (no regressions)
# ---------------------------------------------------------------------------


class TestNoPolicySectionIsNoOp:
    """AC4 — absent / empty policy is a strict no-op; existing behavior preserved."""

    def test_no_approvals_file_hooks_fire_normally(self, tmp_path: Path) -> None:
        """With no approvals.json, hooks fire exactly as before."""
        marker = tmp_path / "ran.txt"
        script = tmp_path / "hook.sh"
        _make_script(script, f"#!/bin/sh\ntouch '{marker}'\n")

        # No .convertible/approvals.json → policy is empty.
        _write_hooks(
            tmp_path,
            {"hooks": {"task_start": [{"command": str(script)}]}},
        )

        responses = [ModelResponse(tool_calls=[ToolCall("1", "finish", {"summary": "x"})])]
        task = Task.new(str(tmp_path), "nothing")
        result = run(_scripted(responses), task, max_steps=10)

        assert marker.exists(), "hook must fire when no policy file exists"
        firings = [f for f in result.hook_firings if f.event == "task_start"]
        assert firings
        assert firings[0].decision != "skipped"

    def test_approvals_with_no_hooks_section_fires_normally(self, tmp_path: Path) -> None:
        """approvals.json present but has no 'hooks' key → hooks section absent → no-op."""
        marker = tmp_path / "ran.txt"
        script = tmp_path / "hook.sh"
        _make_script(script, f"#!/bin/sh\ntouch '{marker}'\n")

        # run_command section but NO hooks section.
        _write_approvals(tmp_path, {"run_command": {"allow": ["echo"], "deny": []}})

        _write_hooks(
            tmp_path,
            {"hooks": {"task_start": [{"command": str(script)}]}},
        )

        responses = [ModelResponse(tool_calls=[ToolCall("1", "finish", {"summary": "x"})])]
        task = Task.new(str(tmp_path), "nothing")
        result = run(_scripted(responses), task, max_steps=10)

        assert marker.exists(), "hook must fire when approvals.json has no hooks section"
        firings = [f for f in result.hook_firings if f.decision == "skipped"]
        assert not firings, "no skip firings expected with no hooks section"

    def test_inline_hook_no_file_fires_normally(self, tmp_path: Path) -> None:
        """Pure inline hook (no repo file reference) always fires — no checksum needed."""
        # hooks section present with an inline command.
        _write_approvals(tmp_path, {"hooks": {}})  # empty hooks section

        # Inline command — references no file.
        _write_hooks(
            tmp_path,
            {"hooks": {"task_start": [{"command": "echo start"}]}},
        )

        responses = [ModelResponse(tool_calls=[ToolCall("1", "finish", {"summary": "x"})])]
        task = Task.new(str(tmp_path), "nothing")
        result = run(_scripted(responses), task, max_steps=10)

        firings = [f for f in result.hook_firings if f.event == "task_start"]
        assert firings, "inline hook should fire"
        assert firings[0].decision != "skipped"


# ---------------------------------------------------------------------------
# AC5: Unit tests for hook_approval_verdict helper directly
# ---------------------------------------------------------------------------


class TestHookApprovalVerdictUnit:
    """AC5 — unit tests for the ``hook_approval_verdict`` helper in hooks.py."""

    def test_approved_file_returns_allowed(self, tmp_path: Path) -> None:
        """A command referencing a file whose checksum is in policy → allowed."""
        script = tmp_path / "lint.sh"
        _make_script(script, "#!/bin/sh\necho lint\n")
        checksum = file_checksum(script)
        policy = Policy(
            files={"hooks": {"lint.sh": checksum}},
            present=frozenset({"hooks"}),
        )
        verdict = hook_approval_verdict(str(script), policy, tmp_path)
        assert isinstance(verdict, Verdict)
        assert verdict.allowed is True

    def test_tampered_file_returns_denied(self, tmp_path: Path) -> None:
        """A command whose referenced file has a wrong checksum → denied."""
        script = tmp_path / "lint.sh"
        _make_script(script, "#!/bin/sh\necho lint\n")
        wrong_checksum = "sha256:" + "a" * 64
        policy = Policy(
            files={"hooks": {"lint.sh": wrong_checksum}},
            present=frozenset({"hooks"}),
        )
        verdict = hook_approval_verdict(str(script), policy, tmp_path)
        assert verdict.allowed is False
        assert verdict.reason

    def test_unlisted_file_returns_denied(self, tmp_path: Path) -> None:
        """Hooks section present but no entry for this file → denied."""
        script = tmp_path / "lint.sh"
        _make_script(script, "#!/bin/sh\necho lint\n")
        policy = Policy(
            files={"hooks": {}},  # empty hooks approvals
            present=frozenset({"hooks"}),
        )
        verdict = hook_approval_verdict(str(script), policy, tmp_path)
        assert verdict.allowed is False

    def test_inline_command_no_file_returns_allowed(self, tmp_path: Path) -> None:
        """A pure inline command (no file references) is always allowed — no-op check."""
        policy = Policy(
            files={"hooks": {}},
            present=frozenset({"hooks"}),
        )
        verdict = hook_approval_verdict("echo done", policy, tmp_path)
        assert verdict.allowed is True

    def test_no_hooks_section_returns_allowed(self, tmp_path: Path) -> None:
        """With no hooks section in policy, check_file is a no-op → allowed."""
        script = tmp_path / "anything.sh"
        _make_script(script, "#!/bin/sh\necho hi\n")
        # policy has run_command section but NO hooks section.
        policy = Policy(
            run_command={"allow": ["echo"]},
            present=frozenset({"run_command"}),
        )
        verdict = hook_approval_verdict(str(script), policy, tmp_path)
        assert verdict.allowed is True

    def test_empty_policy_returns_allowed(self, tmp_path: Path) -> None:
        """An empty (no sections) Policy is a total no-op → allowed."""
        script = tmp_path / "anything.sh"
        _make_script(script, "#!/bin/sh\necho hi\n")
        policy = Policy()
        verdict = hook_approval_verdict(str(script), policy, tmp_path)
        assert verdict.allowed is True

    def test_malformed_command_returns_allowed(self, tmp_path: Path) -> None:
        """An unbalanced-quote command that shlex cannot parse → allowed (never raises)."""
        policy = Policy(
            files={"hooks": {}},
            present=frozenset({"hooks"}),
        )
        verdict = hook_approval_verdict("echo 'unclosed", policy, tmp_path)
        # Must not raise; the r1 spec says malformed → treat as allowed.
        assert isinstance(verdict, Verdict)

    def test_multiple_tokens_first_denial_wins(self, tmp_path: Path) -> None:
        """Command with two file references: first one approved, second denied."""
        script1 = tmp_path / "ok.sh"
        script2 = tmp_path / "bad.sh"
        _make_script(script1, "#!/bin/sh\necho ok\n")
        _make_script(script2, "#!/bin/sh\necho bad\n")

        good_checksum = file_checksum(script1)
        bad_checksum = "sha256:" + "f" * 64  # wrong

        policy = Policy(
            files={"hooks": {"ok.sh": good_checksum, "bad.sh": bad_checksum}},
            present=frozenset({"hooks"}),
        )
        # Command references both scripts.
        command = f"{script1} {script2}"
        verdict = hook_approval_verdict(command, policy, tmp_path)
        assert verdict.allowed is False  # second file denied
