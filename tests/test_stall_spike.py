"""``stall.no_write`` — the count-keyed stall decision turn (effort-floor-and-decay arc).

Rows 74-75: an ``off``-floor run surveyed its whole budget away without ever
requesting a file write, so the pre-mutation barrier (which waits for that
request) could never help it. This point fires on a COUNT — acting turns with
no ``write_file``/``edit_file`` call since the run start, the last spike, or
the last file write — never on content. Bounded: at most
``STALL_MAX_FIRES`` per run. Same tools-off seat and mechanism as the barrier.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from colleague import effortspikes, loop_barrier
from colleague.contract import Step, TaskResult, WorkStats
from colleague.loop_wire import ModelResponse

K = effortspikes.STALL_TURNS


def _ctx(steps: list[str], *, turns: int, marks: list[int] | None = None) -> SimpleNamespace:
    result = TaskResult(task_id="t", status="ok", summary="")
    result.stats = WorkStats()
    result.stats.model_turns = turns
    for i, tool in enumerate(steps):
        result.steps.append(Step(i, tool, {}, "", ok=True))
    return SimpleNamespace(
        result=result, barrier_complete=object(), seat="cortex", _stall_marks=list(marks or [])
    )


def _calls(*names: str) -> list[SimpleNamespace]:
    return [SimpleNamespace(name=n) for n in names]


@pytest.fixture(autouse=True)
def _armed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_EFFORT_SPIKES", "1")
    monkeypatch.delenv("COLLEAGUE_EFFORT_SPIKE_STALL_NO_WRITE", raising=False)


class TestTable:
    def test_point_is_enumerated_at_medium(self) -> None:
        assert "stall.no_write" in effortspikes.SPIKE_POINTS
        assert effortspikes.SPIKE_TABLE["stall.no_write"] == "medium"
        assert effortspikes.resolve_spike("stall.no_write") == "medium"

    def test_constants_are_the_confirmed_decision(self) -> None:
        assert effortspikes.STALL_TURNS == 10
        assert effortspikes.STALL_MAX_FIRES == 3


class TestCount:
    def test_below_k_does_not_fire(self) -> None:
        ctx = _ctx(["run_command"] * (K - 1), turns=K - 1)
        assert loop_barrier.should_fire_stall(ctx, _calls("run_command")) is False

    def test_at_k_fires(self) -> None:
        ctx = _ctx(["run_command"] * K, turns=K)
        assert loop_barrier.should_fire_stall(ctx, _calls("grep_search")) is True

    def test_a_write_request_this_turn_is_not_a_stall(self) -> None:
        ctx = _ctx(["read_file"] * K, turns=K)
        assert loop_barrier.should_fire_stall(ctx, _calls("write_file")) is False

    def test_a_recent_file_write_step_resets_the_count(self) -> None:
        steps = ["read_file"] * K + ["edit_file"] + ["read_file"] * 3
        ctx = _ctx(steps, turns=K + 4)
        assert loop_barrier.turns_since_last_mark(ctx) <= 3
        assert loop_barrier.should_fire_stall(ctx, _calls("read_file")) is False

    def test_a_spike_mark_resets_the_count(self) -> None:
        ctx = _ctx(["read_file"] * (2 * K), turns=2 * K, marks=[2 * K - 2])
        assert loop_barrier.turns_since_last_mark(ctx) == 2
        assert loop_barrier.should_fire_stall(ctx, _calls("read_file")) is False

    def test_fires_again_after_k_more_turns(self) -> None:
        ctx = _ctx(["read_file"] * (2 * K), turns=2 * K, marks=[K])
        assert loop_barrier.should_fire_stall(ctx, _calls("read_file")) is True


class TestBounds:
    def test_capped_per_run(self) -> None:
        ctx = _ctx(["read_file"] * (5 * K), turns=5 * K)
        for _ in range(effortspikes.STALL_MAX_FIRES):
            ctx.result.effort_spikes.append(
                {"point": loop_barrier.STALL_POINT, "rung": "medium", "seat": "cortex"}
            )
        assert loop_barrier.stall_fires(ctx.result) == effortspikes.STALL_MAX_FIRES
        assert loop_barrier.should_fire_stall(ctx, _calls("read_file")) is False

    def test_unarmed_never_fires(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("COLLEAGUE_EFFORT_SPIKES", raising=False)
        ctx = _ctx(["read_file"] * (3 * K), turns=3 * K)
        assert loop_barrier.should_fire_stall(ctx, _calls("read_file")) is False

    def test_no_seat_factory_never_fires(self) -> None:
        ctx = _ctx(["read_file"] * (3 * K), turns=3 * K)
        ctx.barrier_complete = None
        assert loop_barrier.should_fire_stall(ctx, _calls("read_file")) is False


class TestSeatFactoryAcceptsThePoint:
    def test_factory_bound_when_only_stall_resolves(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Pin the barrier point to 'off' via its override so only stall carries a rung
        # above the floor; the factory must still bind (it serves both points).
        factory = loop_barrier.make_barrier_complete(SimpleNamespace(max_output_chars=68000))
        assert factory is not None


class TestInterposeRecordsAndMarks:
    def test_fires_records_marks_and_replaces_the_turn(self, tmp_path, monkeypatch) -> None:
        from colleague.contract import Task
        from colleague.loop_types import _Work

        # Accounting is the loop's concern (test_barrier_pre_mutation drives it
        # end to end); this test pins the interpose bookkeeping only.
        monkeypatch.setattr(loop_barrier, "_account_turn", lambda ctx, resp: None)

        task = Task.new(str(tmp_path), "x")
        result = TaskResult(task_id=task.id, status="ok")
        for i in range(K):
            result.steps.append(Step(i, "read_file", {}, "", ok=True))
        result.stats.model_turns = K
        resp = ModelResponse(content="Plan: edit loop.py")

        def factory(engine_name: str, warn, point: str = "barrier.pre_mutation"):
            assert point == loop_barrier.STALL_POINT
            return lambda messages: resp

        ctx = _Work(
            executor=None,
            hooks=None,
            telemetry=None,
            task=task,
            result=result,
            messages=[{"role": "user", "content": "go"}],
            max_steps=90,
            barrier_complete=factory,
        )
        consumed = loop_barrier.intercept_stall(ctx, _calls("read_file"))
        assert consumed is True
        assert ctx.result.effort_spikes == [
            {"point": "stall.no_write", "rung": "medium", "seat": "cortex"}
        ]
        assert ctx.result.steps[-1].tool == "stall.no_write"
        assert ctx.messages[-1] == {"role": "assistant", "content": "Plan: edit loop.py"}
        assert ctx._stall_marks  # the firing is itself a mark
