"""#487 — the pre-mutation barrier fires on the first FILE-WRITING tool, not the first shell-out.

Rows 72-73 (docs/live-testing.md): three of five dispatches opened their
survey with ``run_command`` (``git status``, ``wc -l``), and the v0
precondition ("every prior step read-only") latched shut on that step, so the
barrier could never fire. The fix narrows BOTH the precondition and the
trigger to :data:`colleague.loop_barrier.FILE_WRITE_TOOLS` — still a tool-NAME
lookup, never content — and leaves ``run_command`` a mutating tool everywhere
else (roles, policy).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from colleague import loop_barrier, roles
from colleague.contract import Step, TaskResult

_PINNED_WRITE_TOOLS = frozenset({"write_file", "edit_file"})


def _ctx(steps: list[str]) -> SimpleNamespace:
    result = TaskResult(task_id="t", status="ok", summary="")
    for i, tool in enumerate(steps):
        result.steps.append(Step(i, tool, {}, "", ok=True))
    return SimpleNamespace(result=result, barrier_complete=object(), seat="cortex")


def _calls(*names: str) -> list[SimpleNamespace]:
    return [SimpleNamespace(name=n) for n in names]


@pytest.fixture(autouse=True)
def _armed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_EFFORT_SPIKES", "1")
    monkeypatch.delenv("COLLEAGUE_EFFORT_SPIKE_BARRIER_PRE_MUTATION", raising=False)


class TestPinnedNameSet:
    def test_file_write_tools_is_exactly_write_and_edit(self) -> None:
        assert loop_barrier.FILE_WRITE_TOOLS == _PINNED_WRITE_TOOLS

    def test_run_command_is_still_mutating_for_roles(self) -> None:
        assert roles.is_read_only_tool("run_command") is False
        assert loop_barrier.is_mutating_tool("run_command") is True
        assert loop_barrier.is_file_write_tool("run_command") is False


class TestShellFirstSurveyStillReachesTheBarrier:
    def test_shell_first_then_write_file_fires(self) -> None:
        ctx = _ctx(["run_command", "read_file", "grep_search", "run_command"])
        assert loop_barrier.should_fire(ctx, _calls("write_file")) is True

    def test_shell_first_then_edit_file_fires(self) -> None:
        ctx = _ctx(["run_command", "read_file"])
        assert loop_barrier.should_fire(ctx, _calls("read_file", "edit_file")) is True

    def test_read_first_still_fires(self) -> None:
        ctx = _ctx(["read_file", "grep_search"])
        assert loop_barrier.should_fire(ctx, _calls("write_file")) is True


class TestStillNeverFiresWhenItShouldNot:
    def test_a_prior_edit_file_blocks(self) -> None:
        ctx = _ctx(["read_file", "edit_file", "read_file"])
        assert loop_barrier.should_fire(ctx, _calls("write_file")) is False

    def test_a_prior_write_file_blocks(self) -> None:
        ctx = _ctx(["write_file"])
        assert loop_barrier.should_fire(ctx, _calls("edit_file")) is False

    def test_a_run_command_turn_is_not_the_trigger(self) -> None:
        ctx = _ctx(["read_file"])
        assert loop_barrier.should_fire(ctx, _calls("run_command")) is False

    def test_no_steps_yet_never_fires(self) -> None:
        ctx = _ctx([])
        assert loop_barrier.should_fire(ctx, _calls("write_file")) is False

    def test_unarmed_never_fires(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("COLLEAGUE_EFFORT_SPIKES", "0")
        ctx = _ctx(["run_command", "read_file"])
        assert loop_barrier.should_fire(ctx, _calls("write_file")) is False

    def test_already_fired_never_fires_again(self) -> None:
        ctx = _ctx(["read_file"])
        ctx.result.effort_spikes.append(
            {"point": loop_barrier.BARRIER_POINT, "rung": "medium", "seat": "cortex"}
        )
        assert loop_barrier.should_fire(ctx, _calls("write_file")) is False
