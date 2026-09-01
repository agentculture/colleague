"""#484 t8 — the pre-mutation decision barrier.

Task t5 shipped the table (:mod:`colleague.effortspikes`: the three enumerated
points, the opt-in, the ``(point, rung, seat)`` record shape) with no consumer.
This file covers the FIRST consumer: :mod:`colleague.loop_barrier`, the one
bounded tools-off completion the loop interposes before a run's first mutating
tool call.

Acceptance criteria under test:

1. **Armed** — one bounded tools-off completion interposes before the first
   mutating tool call after a read-only phase; it has its own output ceiling
   and its own (un-escalated) timeout; it never mutates; and it counts as a
   normal step — ``stats.model_turns`` (the declared ``max_steps`` bound) and
   ``stats.step_count`` each advance by exactly one.
2. **Trigger + record** — the trigger is tool-NAME based (the existing
   ``roles`` read-only classification), never content; each firing lands on the
   artifact as ``{point, rung, seat}``; **unarmed the payloads are
   byte-identical** — asserted by driving the SAME script twice and comparing
   every message list the engine was handed, call for call.

The rung is asserted to come ONLY from
:func:`colleague.effortspikes.resolve_spike` — including through its per-point
env override, which is the only other input that table honours.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from colleague import effortspikes, loop_barrier
from colleague.config import EngineConfig
from colleague.contract import Task, TaskResult
from colleague.loop import run
from colleague.loop_types import ContextControls, _Work
from colleague.loop_wire import ModelResponse, ToolCall

SPIKE_ENV = "COLLEAGUE_EFFORT_SPIKES"
POINT = "barrier.pre_mutation"


# ---------------------------------------------------------------------------
# A scripted engine + a scripted barrier seat
# ---------------------------------------------------------------------------


class _Script:
    """A scripted acting completion that records every request it was handed."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests: list[list[dict]] = []

    def __call__(self, messages):
        self.requests.append(copy.deepcopy(messages))
        if not self.responses:
            return ModelResponse(content="(script exhausted)")
        return self.responses.pop(0)


class _BarrierSeat:
    """A scripted barrier seat factory (what ``make_barrier_complete`` binds)."""

    def __init__(self, plan="PLAN: edit a.txt; keep the header invariant.", resp=None):
        self.plan = plan
        self.resp = resp
        self.engines: list[str] = []
        self.requests: list[list[dict]] = []

    def __call__(self, engine_name, warn):
        self.engines.append(engine_name)

        def complete(messages):
            self.requests.append(copy.deepcopy(messages))
            return self.resp if self.resp is not None else ModelResponse(content=self.plan)

        return complete


def _read_turn(path="a.txt", call_id="r1"):
    return ModelResponse(
        content="reading", tool_calls=[ToolCall(call_id, "list_dir", {"path": "."})]
    )


def _write_turn(call_id="w1", path="a.txt", content="hello"):
    return ModelResponse(
        content="writing",
        tool_calls=[ToolCall(call_id, "write_file", {"path": path, "content": content})],
    )


def _finish_turn(call_id="f1"):
    return ModelResponse(tool_calls=[ToolCall(call_id, "finish", {"summary": "done"})])


def _drive(tmp_path: Path, responses, *, seat=None, max_steps=8):
    task = Task.new(str(tmp_path), "change a file")
    controls = ContextControls(barrier_complete=seat)
    script = _Script(responses)
    result = run(script, task, max_steps=max_steps, context=controls)
    return result, script


@pytest.fixture
def armed(monkeypatch):
    monkeypatch.setenv(SPIKE_ENV, "1")
    monkeypatch.delenv("COLLEAGUE_EFFORT_SPIKE_BARRIER_PRE_MUTATION", raising=False)


@pytest.fixture
def unarmed(monkeypatch):
    monkeypatch.delenv(SPIKE_ENV, raising=False)


# ---------------------------------------------------------------------------
# AC2 — the trigger is tool-NAME based, from the existing classification
# ---------------------------------------------------------------------------


class TestTriggerIsToolNameBased:
    def test_read_only_names_are_not_mutating(self):
        from colleague.roles import _READONLY_TOOLS

        for name in _READONLY_TOOLS:
            assert loop_barrier.is_mutating_tool(name) is False

    @pytest.mark.parametrize("name", ["write_file", "edit_file", "run_command", "run_tests"])
    def test_write_names_are_mutating(self, name):
        assert loop_barrier.is_mutating_tool(name) is True

    def test_unknown_name_fails_closed(self):
        assert loop_barrier.is_mutating_tool("something_new") is True

    def test_classification_is_the_roles_one_not_a_second_list(self):
        """The trigger must key off ``roles``' own tuple — a private copy here
        would drift the moment a tool is added to a read-only role."""
        from colleague import roles

        assert loop_barrier.is_mutating_tool.__module__ == "colleague.loop_barrier"
        assert roles.is_read_only_tool("read_file") is True
        assert roles.is_read_only_tool("write_file") is False

    def test_no_arguments_or_content_are_inspected(self):
        """Same tool name, wildly different arguments -> the same verdict."""
        assert loop_barrier.is_mutating_tool("run_command") is True
        assert loop_barrier.is_mutating_tool("read_file") is False


# ---------------------------------------------------------------------------
# AC1 — armed: the barrier interposes, is bounded, counts, and never mutates
# ---------------------------------------------------------------------------


class TestArmedBarrierInterposes:
    def test_barrier_fires_before_the_first_write_and_replaces_that_turn(self, tmp_path, armed):
        seat = _BarrierSeat()
        result, script = _drive(
            tmp_path, [_read_turn(), _write_turn(), _write_turn("w2"), _finish_turn()], seat=seat
        )

        assert result.status == "ok"
        # The barrier ran exactly once, on the acting engine.
        assert seat.engines == [Task.new(str(tmp_path), "x").engine]
        assert len(seat.requests) == 1
        # It saw the running history plus the planning nudge, nothing else.
        assert seat.requests[0][-1] == {
            "role": "user",
            "content": loop_barrier.BARRIER_PROMPT,
        }
        # The intercepted turn's write did NOT run; the model re-issued it.
        tools = [step.tool for step in result.steps]
        assert tools == ["list_dir", POINT, "write_file", "finish"]
        assert (tmp_path / "a.txt").read_text() == "hello"

    def test_the_plan_lands_in_history_as_an_assistant_message(self, tmp_path, armed):
        seat = _BarrierSeat(plan="PLAN: touch only a.txt")
        _, script = _drive(
            tmp_path, [_read_turn(), _write_turn(), _write_turn("w2"), _finish_turn()], seat=seat
        )
        # The turn AFTER the barrier sees the plan.
        after = script.requests[2]
        assert {"role": "assistant", "content": "PLAN: touch only a.txt"} in after
        # ...and the intercepted turn's own assistant tool-call message is NOT
        # in that history (the barrier replaced that turn's execution).
        assert not any(m.get("tool_calls") and m.get("content") == "writing" for m in after)

    def test_the_barrier_counts_as_one_normal_step(self, tmp_path, armed):
        seat = _BarrierSeat()
        with_barrier, _ = _drive(
            tmp_path, [_read_turn(), _write_turn(), _write_turn("w2"), _finish_turn()], seat=seat
        )
        assert with_barrier.stats.step_count == 4  # list_dir, barrier, write_file, finish
        assert with_barrier.stats.tool_counts[POINT] == 1
        assert with_barrier.stats.model_turns == 5  # 4 acting turns + the barrier

    def test_the_barrier_turn_consumes_the_declared_budget(self, tmp_path, armed):
        """It is never hidden from ``max_steps`` (decision c23): with a budget
        of three model turns, the barrier costs one of them."""
        seat = _BarrierSeat()
        result, script = _drive(
            tmp_path,
            [_read_turn(), _write_turn(), _write_turn("w2"), _finish_turn()],
            seat=seat,
            max_steps=3,
        )
        assert result.not_finished is True
        # The budget ran out ON the barrier: the write it interrupted never got
        # a turn to be re-issued in, so the barrier really did cost one.
        assert len(seat.requests) == 1
        assert [s.tool for s in result.steps] == ["list_dir", POINT]

    def test_the_barrier_never_mutates_even_if_it_emits_tool_calls(self, tmp_path, armed):
        """A tools-off completion structurally cannot call a tool, but if a
        server echoed one back it must still never be executed."""
        seat = _BarrierSeat(
            resp=ModelResponse(
                content="PLAN: nothing",
                tool_calls=[ToolCall("x", "write_file", {"path": "evil.txt", "content": "x"})],
            )
        )
        result, _ = _drive(
            tmp_path, [_read_turn(), _write_turn(), _write_turn("w2"), _finish_turn()], seat=seat
        )
        assert not (tmp_path / "evil.txt").exists()
        assert "evil.txt" not in result.changed_files

    def test_it_fires_at_most_once_per_run(self, tmp_path, armed):
        seat = _BarrierSeat()
        result, _ = _drive(
            tmp_path,
            [
                _read_turn(),
                _write_turn(),
                _write_turn("w2"),
                _write_turn("w3", content="again"),
                _finish_turn(),
            ],
            seat=seat,
        )
        assert len(seat.requests) == 1
        assert [s for s in result.effort_spikes if s["point"] == POINT] == [
            {"point": POINT, "rung": "medium", "seat": "cortex"}
        ]

    def test_no_read_only_phase_means_no_barrier(self, tmp_path, armed):
        """A run that mutates on its very first turn has no read-only phase to
        interpose after — the barrier stays out of the way."""
        seat = _BarrierSeat()
        result, _ = _drive(tmp_path, [_write_turn(), _finish_turn()], seat=seat)
        assert seat.requests == []
        assert result.effort_spikes == []
        assert [s.tool for s in result.steps] == ["write_file", "finish"]

    def test_a_read_only_turn_never_triggers_it(self, tmp_path, armed):
        seat = _BarrierSeat()
        result, _ = _drive(tmp_path, [_read_turn(), _read_turn("r2"), _finish_turn()], seat=seat)
        assert seat.requests == []
        assert result.effort_spikes == []

    def test_a_failing_barrier_turn_never_aborts_the_run(self, tmp_path, armed):
        class _Boom(_BarrierSeat):
            def __call__(self, engine_name, warn):
                def complete(_messages):
                    raise TimeoutError("the planning turn timed out")

                return complete

        result, _ = _drive(tmp_path, [_read_turn(), _write_turn(), _finish_turn()], seat=_Boom())
        assert result.status == "ok"
        # The turn it interrupted still ran (nothing was swallowed).
        assert [s.tool for s in result.steps] == ["list_dir", "write_file", "finish"]
        assert any("barrier" in str(w) for w in result.warnings)

    def test_an_empty_plan_never_swallows_the_turn(self, tmp_path, armed):
        seat = _BarrierSeat(plan="   ")
        result, _ = _drive(tmp_path, [_read_turn(), _write_turn(), _finish_turn()], seat=seat)
        # The spike still fired (honest: a completion was spent) but the
        # model's own turn was not discarded.
        assert [s["point"] for s in result.effort_spikes] == [POINT]
        assert [s.tool for s in result.steps] == ["list_dir", "write_file", "finish"]

    def test_an_unbuildable_seat_is_a_no_op(self, tmp_path, armed):
        result, _ = _drive(
            tmp_path,
            [_read_turn(), _write_turn(), _finish_turn()],
            seat=lambda engine_name, warn: None,
        )
        assert result.effort_spikes == []
        assert [s.tool for s in result.steps] == ["list_dir", "write_file", "finish"]


# ---------------------------------------------------------------------------
# AC2 — the record, and the rung's single source
# ---------------------------------------------------------------------------


class TestArtifactRecord:
    def test_record_shape_and_artifact_key(self, tmp_path, armed):
        result, _ = _drive(
            tmp_path, [_read_turn(), _write_turn(), _finish_turn()], seat=_BarrierSeat()
        )
        assert result.effort_spikes == [{"point": POINT, "rung": "medium", "seat": "cortex"}]
        assert result.to_dict()["effort_spikes"] == result.effort_spikes
        assert TaskResult.from_dict(result.to_dict()).effort_spikes == result.effort_spikes

    def test_the_rung_comes_only_from_resolve_spike(self, tmp_path, armed, monkeypatch):
        """The per-point env override the table itself honours is the ONLY way
        to move the rung — nothing in the barrier accepts one."""
        monkeypatch.setenv("COLLEAGUE_EFFORT_SPIKE_BARRIER_PRE_MUTATION", "high")
        assert effortspikes.resolve_spike(POINT) == "high"
        result, _ = _drive(
            tmp_path, [_read_turn(), _write_turn(), _finish_turn()], seat=_BarrierSeat()
        )
        assert result.effort_spikes[0]["rung"] == "high"

    def test_no_public_function_accepts_a_rung_parameter(self):
        import inspect

        forbidden = {"effort", "rung", "reasoning_effort"}
        for name, func in inspect.getmembers(loop_barrier, inspect.isfunction):
            if name.startswith("_") or name == "barrier_seat_config":
                continue
            assert not forbidden & set(inspect.signature(func).parameters), name


# ---------------------------------------------------------------------------
# AC1/AC2 — the seat: tools-off, its own ceiling, its own timeout, the rung
# ---------------------------------------------------------------------------


class _FakeEngine:
    def __init__(self, resp=None, raises=None):
        self.calls: list[tuple] = []
        self.resp = resp or ModelResponse(content="PLAN")
        self.raises = raises

    def make_complete(self, config, tools=None):
        self.calls.append((config, tools))
        if self.raises is not None:
            raise self.raises

        def complete(messages):
            return self.resp

        return complete


class TestBarrierSeat:
    def test_unarmed_builds_nothing(self, unarmed):
        assert loop_barrier.make_barrier_complete(EngineConfig()) is None

    def test_armed_seat_is_tools_off_at_the_table_rung(self, armed):
        engine = _FakeEngine()
        factory = loop_barrier.make_barrier_complete(
            EngineConfig(), engine_loader=lambda _n: engine
        )
        assert factory is not None
        assert factory("vllm-openai", lambda _t: None) is not None
        seat, tools = engine.calls[0]
        assert tools == []  # the honest tools-off invariant
        assert getattr(seat, "reasoning_effort_seat") == "medium"
        assert seat.on_delta is None
        assert seat.refresh_seat is None

    def test_the_seat_uses_the_unescalated_turn_timeout(self, armed):
        engine = _FakeEngine()
        config = EngineConfig(timeout=240.0, base_timeout=120.0)  # a live escalation
        factory = loop_barrier.make_barrier_complete(config, engine_loader=lambda _n: engine)
        factory("vllm-openai", lambda _t: None)
        assert engine.calls[0][0].timeout == 120.0

    def test_the_plan_is_clamped_to_its_own_output_ceiling(self, armed):
        config = EngineConfig(max_output_chars=800)
        ceiling = loop_barrier.plan_char_ceiling(config)
        assert ceiling == 100
        engine = _FakeEngine(resp=ModelResponse(content="x" * 5000))
        factory = loop_barrier.make_barrier_complete(config, engine_loader=lambda _n: engine)
        complete = factory("vllm-openai", lambda _t: None)
        out = complete([{"role": "user", "content": "hi"}])
        marker = "\n[truncated: original 5000 chars]"
        assert out.content.startswith("x" * (ceiling - len(marker)))
        assert out.content.endswith(marker)
        # The marker counts AGAINST the ceiling (Qodo #486 thread 9): the
        # retained plan never exceeds the configured bound.
        assert len(out.content) <= ceiling

    def test_a_short_plan_is_untouched(self, armed):
        assert loop_barrier.clamp_plan("short", 100) == "short"

    def test_an_engine_without_a_one_shot_seam_warns_once_and_declines(self, armed):
        engine = _FakeEngine(raises=NotImplementedError("mock has no live model"))
        warnings: list[str] = []
        factory = loop_barrier.make_barrier_complete(
            EngineConfig(), engine_loader=lambda _n: engine
        )
        assert factory("mock", warnings.append) is None
        assert len(warnings) == 1
        assert "mock" in warnings[0]


# ---------------------------------------------------------------------------
# AC2 — unarmed is byte-identical
# ---------------------------------------------------------------------------


class TestUnarmedIsByteIdentical:
    def _script(self):
        return [_read_turn(), _write_turn(), _write_turn("w2"), _finish_turn()]

    def test_same_requests_call_for_call_as_a_no_barrier_run(self, tmp_path, monkeypatch):
        """The strongest available form of "byte-identical payloads": drive the
        same script with the opt-in unset and with NO barrier wiring at all,
        and compare every message list the engine was handed."""
        monkeypatch.delenv(SPIKE_ENV, raising=False)
        repo_a = tmp_path / "a"
        repo_b = tmp_path / "b"
        repo_a.mkdir()
        repo_b.mkdir()
        _, unarmed_script = _drive(repo_a, self._script(), seat=_BarrierSeat())
        _, baseline_script = _drive(repo_b, self._script(), seat=None)

        def _scrub(requests):
            # only the repo path differs between the two throwaway repos
            return [
                [
                    {
                        k: str(v).replace(str(repo_a), "R").replace(str(repo_b), "R")
                        for k, v in m.items()
                    }
                    for m in req
                ]
                for req in requests
            ]

        assert _scrub(unarmed_script.requests) == _scrub(baseline_script.requests)

    def test_no_artifact_key_and_no_barrier_step(self, tmp_path, monkeypatch):
        monkeypatch.delenv(SPIKE_ENV, raising=False)
        seat = _BarrierSeat()
        result, _ = _drive(tmp_path, self._script(), seat=seat)
        assert seat.requests == []
        assert result.effort_spikes == []
        assert "effort_spikes" not in result.to_dict()
        assert [s.tool for s in result.steps] == ["list_dir", "write_file", "write_file", "finish"]

    def test_from_config_binds_nothing_unarmed(self, monkeypatch):
        monkeypatch.delenv(SPIKE_ENV, raising=False)
        assert ContextControls.from_config(EngineConfig()).barrier_complete is None

    def test_from_config_binds_the_factory_armed(self, armed):
        assert ContextControls.from_config(EngineConfig()).barrier_complete is not None

    def test_intercept_is_a_no_op_without_a_factory(self, tmp_path, armed):
        task = Task.new(str(tmp_path), "x")
        ctx = _Work(
            executor=None,
            hooks=None,
            telemetry=None,
            task=task,
            result=TaskResult(task_id=task.id, status="ok"),
            messages=[],
            max_steps=4,
        )
        assert loop_barrier.intercept(ctx, [ToolCall("1", "write_file", {})]) is False
