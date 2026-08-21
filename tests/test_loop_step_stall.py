"""#400 — the step-stall watchdog: a PROGRESS bound, not a duration one.

Streaming (#393) removed the request timeout's accidental no-progress ceiling; a
turn can now stream healthily for hours while ``step_index`` never advances.
These tests pin the loop's bound on time-since-last-completed-step: crossing it
ends the episode with a preserved partial + an honest warning; the clock
restarts whenever a step completes; unset knob + fast steps = byte-identical;
and the exit is NOT continuable (``chain.CONTINUABLE_REASONS`` untouched).
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from colleague import chain, loop, stallguard
from colleague.contract import INCOMPLETE, OK, Task
from colleague.loop import ModelResponse, ToolCall


def _finish(summary: str = "done") -> ModelResponse:
    return ModelResponse(tool_calls=[ToolCall("f", "finish", {"summary": summary})])


def _list_dir() -> ModelResponse:
    return ModelResponse(tool_calls=[ToolCall("l", "list_dir", {"path": "."})])


@pytest.fixture()
def task(tmp_path: Path) -> Task:
    repo = tmp_path / "repo"
    repo.mkdir()
    return Task.new(str(repo), "watch the clock")


def test_streaming_turn_that_never_progresses_trips_the_bound(task: Task, monkeypatch) -> None:
    monkeypatch.setenv("COLLEAGUE_MAX_STEP_STALL", "0.3")

    def streaming_forever(_messages):
        # the shape of a live SSE reader: frames keep arriving, the loop's
        # stallguard is consulted per frame (as vllm_openai's reader does)
        while True:
            time.sleep(0.02)
            stallguard.check()

    result = loop.run(streaming_forever, task, max_steps=5)
    assert result.status == INCOMPLETE
    assert result.not_finished is True
    stalls = [w for w in result.warnings if w.get("kind") == "step-stall"]
    assert len(stalls) == 1 and stalls[0]["seconds"] >= 0.3 and stalls[0]["step_index"] == 0
    assert result.incompletion is not None and result.incompletion.reason == "step-stall"
    # not continuable: the #400 exit is NOT in the pinned allow-list
    assert chain.exit_reason(result) == "step-stall"
    assert "step-stall" not in chain.CONTINUABLE_REASONS
    # nothing leaks into the caller's context
    assert stallguard.armed() is None


def test_blocking_turn_detected_between_turns(task: Task, monkeypatch) -> None:
    """A transport that cannot consult stallguard mid-turn is still bounded between turns."""
    monkeypatch.setenv("COLLEAGUE_MAX_STEP_STALL", "0.3")
    calls = []

    def slow_no_tool(_messages):
        calls.append(1)
        time.sleep(0.4)
        return ModelResponse(content="still thinking")

    result = loop.run(slow_no_tool, task, max_steps=5)
    assert result.status == INCOMPLETE and result.not_finished
    assert [w["kind"] for w in result.warnings] == ["step-stall"]
    assert len(calls) == 1  # the stall is seen before a second turn is spent


def test_completed_steps_restart_the_clock(task: Task, monkeypatch) -> None:
    monkeypatch.setenv("COLLEAGUE_MAX_STEP_STALL", "0.5")
    script = iter([_list_dir(), _list_dir(), _finish()])

    def steady(_messages):
        time.sleep(0.3)  # each turn is under the bound SINCE THE LAST STEP
        stallguard.check()
        return next(script)

    result = loop.run(steady, task, max_steps=6)
    assert result.status == OK
    assert not [w for w in result.warnings if w.get("kind") == "step-stall"]
    assert result.stats.step_count == 3


def test_unset_knob_and_fast_steps_are_byte_identical(task: Task, monkeypatch) -> None:
    monkeypatch.delenv("COLLEAGUE_MAX_STEP_STALL", raising=False)
    script = iter([_list_dir(), _finish("ok")])
    result = loop.run(lambda _m: next(script), task, max_steps=4)
    assert result.status == OK
    assert result.warnings == []
    assert result.incompletion is None


def test_knob_zero_disables_the_watchdog(task: Task, monkeypatch) -> None:
    monkeypatch.setenv("COLLEAGUE_MAX_STEP_STALL", "0")
    script = iter([_finish("ok")])

    def complete(_messages):
        assert stallguard.armed() is None  # nothing armed when disabled
        return next(script)

    result = loop.run(complete, task, max_steps=2)
    assert result.status == OK and result.warnings == []


def test_default_bound_policy_floor_and_latency_scaling() -> None:
    """The default never drops below the floor and scales to 6x the mean turn latency."""
    assert loop._STALL_FLOOR_SECONDS == 3600.0

    class _Ctx:  # the two fields _stall_bound reads
        _turn_latencies: list[float]

    ctx = _Ctx()
    ctx._turn_latencies = []
    assert loop._stall_bound(ctx) == 3600.0  # type: ignore[arg-type]
    ctx._turn_latencies = [100.0, 100.0, 100.0]
    assert loop._stall_bound(ctx) == 3600.0  # 6x100 < floor -> floor
    ctx._turn_latencies = [1000.0, 1000.0, 1000.0]
    assert loop._stall_bound(ctx) == 6000.0  # 6x mean once >= 3 samples


def test_stallguard_check_is_a_noop_when_unarmed_and_raises_past_deadline() -> None:
    stallguard.check()  # nothing armed -> no-op
    token = stallguard.arm(since=100.0, bound=5.0)
    try:
        stallguard.check(now=104.0)
        with pytest.raises(stallguard.TurnStalled) as excinfo:
            stallguard.check(now=106.0)
        assert excinfo.value.seconds == pytest.approx(6.0)
        assert excinfo.value.bound == pytest.approx(5.0)
    finally:
        stallguard.disarm(token)
    assert stallguard.armed() is None
