"""Tests for colleague.cockpit_run — pure run-state + ledger module."""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Optional

import pytest

from colleague.cockpit_run import (
    ACTIVITY_CAP,
    Activity,
    RunState,
    fold,
    observed_ledger,
    reconcile,
    status_line,
)

# ── fold: immutability ──────────────────────────────────────────────


class TestFoldImmutability:
    def test_fold_does_not_mutate_input(self) -> None:
        original = RunState(
            activities=(Activity("read_file", "a.py", True),),
            files_touched=frozenset({"a.py"}),
            command_count=1,
            last_action="[read_file] a.py",
            step_count=1,
        )
        snapshot = (
            original.activities,
            original.files_touched,
            original.command_count,
            original.last_action,
            original.step_count,
            original.phase,
        )
        new_state = fold(original, "write_file", "b.py", True)
        assert (
            original.activities,
            original.files_touched,
            original.command_count,
            original.last_action,
            original.step_count,
            original.phase,
        ) == snapshot
        assert new_state is not original

    def test_activity_is_frozen(self) -> None:
        a = Activity("read_file", "x.py", True)
        with pytest.raises(Exception):
            a.tool = "other"  # type: ignore


# ── fold: real steps ───────────────────────────────────────────────


class TestFoldRealSteps:
    def test_fold_write_file(self) -> None:
        s = fold(RunState(), "write_file", "src/main.py", True)
        assert s.step_count == 1
        assert "src/main.py" in s.files_touched
        assert s.last_action == "[write_file] src/main.py"
        assert len(s.activities) == 1
        assert s.activities[0].tool == "write_file"
        assert s.activities[0].ok is True

    def test_fold_edit_file(self) -> None:
        s = fold(RunState(), "edit_file", "src/lib.py", True)
        assert s.step_count == 1
        assert "src/lib.py" in s.files_touched
        assert s.command_count == 0

    def test_fold_run_command(self) -> None:
        s = fold(RunState(), "run_command", "make test", True)
        assert s.step_count == 1
        assert s.command_count == 1
        assert s.files_touched == frozenset()

    def test_fold_read_file(self) -> None:
        s = fold(RunState(), "read_file", "README.md", True)
        assert s.step_count == 1
        assert s.command_count == 0
        assert s.files_touched == frozenset()
        assert s.last_action == "[read_file] README.md"

    def test_fold_multiple_steps(self) -> None:
        s = RunState()
        s = fold(s, "write_file", "a.py", True)
        s = fold(s, "run_command", "pytest", True)
        s = fold(s, "edit_file", "b.py", True)
        assert s.step_count == 3
        assert s.command_count == 1
        assert s.files_touched == frozenset({"a.py", "b.py"})
        assert s.last_action == "[edit_file] b.py"
        assert len(s.activities) == 3

    def test_fold_empty_target(self) -> None:
        s = fold(RunState(), "run_command", "", True)
        assert s.last_action == "[run_command]"

    def test_fold_ok_false(self) -> None:
        s = fold(RunState(), "run_command", "failing cmd", False)
        assert s.activities[0].ok is False


# ── fold: phase notices ────────────────────────────────────────────


class TestFoldPhaseNotices:
    def test_phase_notice_updates_phase_only(self) -> None:
        s = fold(RunState(), "", "thinking…", True)
        assert s.phase == "thinking…"
        assert s.step_count == 0
        assert s.activities == ()
        assert s.last_action == ""
        assert s.command_count == 0
        assert s.files_touched == frozenset()

    def test_phase_notice_after_real_step(self) -> None:
        s = fold(RunState(), "write_file", "a.py", True)
        s = fold(s, "", "synthesizing…", True)
        assert s.step_count == 1
        assert s.phase == "synthesizing…"
        assert s.last_action == "[write_file] a.py"

    def test_phase_notice_does_not_advance_counters(self) -> None:
        s = RunState()
        for phase_text in ["thinking…", "synthesizing…", "compacting…"]:
            s = fold(s, "", phase_text, True)
        assert s.step_count == 0
        assert s.phase == "compacting…"


# ── fold: activity cap ────────────────────────────────────────────


class TestFoldActivityCap:
    def test_activity_cap_default(self) -> None:
        assert ACTIVITY_CAP == 50

    def test_activities_capped_at_default(self) -> None:
        s = RunState()
        for i in range(60):
            s = fold(s, "read_file", f"file_{i}.py", True)
        assert len(s.activities) == 50
        assert s.step_count == 60
        # Most recent 50 retained
        assert s.activities[0].target == "file_10.py"
        assert s.activities[-1].target == "file_59.py"

    def test_activities_capped_custom(self) -> None:
        s = RunState()
        for i in range(10):
            s = fold(s, "read_file", f"f{i}.py", True, cap=3)
        assert len(s.activities) == 3
        assert s.step_count == 10
        assert s.activities[0].target == "f7.py"
        assert s.activities[-1].target == "f9.py"


# ── observed_ledger ───────────────────────────────────────────────


class TestObservedLedger:
    def test_observed_ledger_mid_run(self) -> None:
        s = RunState()
        s = fold(s, "write_file", "a.py", True)
        s = fold(s, "run_command", "test", True)
        s = fold(s, "edit_file", "b.py", True)

        ledger = observed_ledger(s)
        assert ledger.files_changed == 2
        assert ledger.commands_run == 1
        assert ledger.commits is None
        assert ledger.publish_state == ""

    def test_observed_ledger_empty(self) -> None:
        ledger = observed_ledger(RunState())
        assert ledger.files_changed == 0
        assert ledger.commands_run == 0
        assert ledger.commits is None
        assert ledger.publish_state == ""


# ── reconcile ─────────────────────────────────────────────────────


@dataclass
class _MockWorkStats:
    files_changed: int = 0
    tool_counts: dict[str, int] = field(default_factory=dict)


@dataclass
class _MockTaskResult:
    stats: _MockWorkStats
    branch: Optional[str] = None
    pr_url: Optional[str] = None


class TestReconcile:
    def _make_result(
        self,
        files_changed: int = 0,
        tool_counts: Optional[dict[str, int]] = None,
        branch: Optional[str] = None,
        pr_url: Optional[str] = None,
    ) -> _MockTaskResult:
        return _MockTaskResult(
            stats=_MockWorkStats(
                files_changed=files_changed,
                tool_counts=tool_counts or {},
            ),
            branch=branch,
            pr_url=pr_url,
        )

    def test_reconcile_files_changed(self) -> None:
        result = self._make_result(files_changed=5)
        ledger = reconcile(result)
        assert ledger.files_changed == 5

    def test_reconcile_commands_run(self) -> None:
        result = self._make_result(tool_counts={"run_command": 3, "read_file": 2})
        ledger = reconcile(result)
        assert ledger.commands_run == 3

    def test_reconcile_no_run_command(self) -> None:
        result = self._make_result(tool_counts={"read_file": 1})
        ledger = reconcile(result)
        assert ledger.commands_run == 0

    def test_reconcile_no_stats(self) -> None:
        result = self._make_result()
        result.stats = None  # type: ignore[assignment]
        ledger = reconcile(result)
        assert ledger.files_changed == 0
        assert ledger.commands_run == 0

    def test_reconcile_commits_from_branch(self) -> None:
        result = self._make_result(branch="feature/x")
        ledger = reconcile(result)
        assert ledger.commits == 1

    def test_reconcile_no_commits(self) -> None:
        result = self._make_result()
        ledger = reconcile(result)
        assert ledger.commits == 0

    def test_reconcile_publish_state_pr(self) -> None:
        result = self._make_result(pr_url="https://github.com/x/y/pull/1")
        ledger = reconcile(result)
        assert ledger.publish_state == "pr"

    def test_reconcile_publish_state_local(self) -> None:
        result = self._make_result(branch="feature/x")
        ledger = reconcile(result)
        assert ledger.publish_state == "local"

    def test_reconcile_publish_state_none(self) -> None:
        result = self._make_result()
        ledger = reconcile(result)
        assert ledger.publish_state == "none"


# ── status_line ───────────────────────────────────────────────────


class TestStatusLine:
    def test_basic(self) -> None:
        s = RunState(last_action="[write_file] a.py")
        line = status_line(s, step=3, max_steps=10, elapsed_seconds=5.0)
        assert "step 3/10" in line
        assert "[write_file] a.py" in line
        assert "5s" in line

    def test_with_phase(self) -> None:
        s = RunState(phase="thinking…")
        line = status_line(s, step=1, max_steps=5, elapsed_seconds=2.0)
        assert "thinking…" in line

    def test_phase_arg_overrides_state(self) -> None:
        s = RunState(phase="old phase")
        line = status_line(s, step=1, max_steps=5, elapsed_seconds=1.0, phase="new phase")
        assert "new phase" in line
        assert "old phase" not in line

    def test_no_max_steps(self) -> None:
        s = RunState(last_action="[read_file] x.py")
        line = status_line(s, step=7, max_steps=None, elapsed_seconds=3.0)
        assert "step 7" in line
        assert "/None" not in line

    def test_no_elapsed(self) -> None:
        s = RunState(last_action="[edit_file] y.py")
        line = status_line(s, step=2, max_steps=5, elapsed_seconds=None)
        assert "y.py" in line
        assert "s" not in line.split("·")[-1].strip() if "·" in line else True

    def test_elapsed_formatting_seconds(self) -> None:
        s = RunState()
        line = status_line(s, step=1, max_steps=1, elapsed_seconds=3.0)
        assert "3s" in line

    def test_elapsed_formatting_minutes(self) -> None:
        s = RunState()
        line = status_line(s, step=1, max_steps=1, elapsed_seconds=64.0)
        assert "1m04s" in line

    def test_elapsed_formatting_large(self) -> None:
        s = RunState()
        line = status_line(s, step=1, max_steps=1, elapsed_seconds=3661.0)
        assert "1h01m01s" in line

    def test_empty_state_no_segments(self) -> None:
        s = RunState()
        line = status_line(s, step=0, max_steps=10, elapsed_seconds=0.0)
        # Should have step and elapsed segments
        assert "step 0/10" in line
        assert "0s" in line

    def test_segments_joined_with_bullet(self) -> None:
        s = RunState(phase="building", last_action="[write_file] z.py")
        line = status_line(s, step=5, max_steps=20, elapsed_seconds=10.0)
        assert "·" in line


# ── module boundary ───────────────────────────────────────────────


class TestModuleBoundary:
    def test_not_under_tui(self) -> None:
        import colleague.cockpit_run as mod

        path = inspect.getfile(mod)
        assert "/tui/" not in path

    def test_no_agentfront_import(self) -> None:
        import colleague.cockpit_run as mod

        source = inspect.getsource(mod)
        assert "import agentfront" not in source
        assert "from agentfront" not in source

    def test_no_stdlib_forbidden(self) -> None:
        import colleague.cockpit_run as mod

        source = inspect.getsource(mod)
        assert "import subprocess" not in source
        assert "import threading" not in source
        assert "import concurrent" not in source
