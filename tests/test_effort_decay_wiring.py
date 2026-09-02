"""Effort decay — the loop wiring (spec 2026-09-02-effort-floor-and-decay-arms, c3/h3/c4/h4).

Drives ``loop_gateescalation.decayed_turn`` / ``note_reset`` over a fake
``_Work`` carrying a LIVE config object, exactly the way the loop does, and
asserts:

* unarmed (either opt-in unset): no attribute is ever written and the record
  stays empty (byte-identical);
* armed: after a reset the next acting completion carries ``low``, the one
  after ``off``, and the attribute is restored the moment the completion
  returns; a second reset restarts the offsets;
* every spike record site is a reset — the barrier's, the gate's and the
  fill-line's;
* ``TaskResult.effort_decay`` round-trips and is omitted when empty.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from colleague import loop_gateescalation as ge
from colleague.contract import TaskResult, WorkStats
from colleague.loop_types import ContextControls

_ATTR = "reasoning_effort_seat"


class _Config:
    """A plain live config object; ``reasoning_effort_seat`` absent unless pushed."""


def _ctx(config: _Config, *, turns: int = 0) -> SimpleNamespace:
    result = TaskResult(task_id="t", status="ok", summary="")
    result.stats = WorkStats()
    result.stats.model_turns = turns
    return SimpleNamespace(
        result=result,
        seat="cortex",
        gate_escalation=ge.make_escalator(config),
        effort_decay=ge.make_decay(config),
        _effort_spikes_fired=[],
        _fillline_escalated=[],
    )


def _arm(monkeypatch: pytest.MonkeyPatch, *, spikes: bool, decay: bool) -> None:
    for key, on in (("COLLEAGUE_EFFORT_SPIKES", spikes), ("COLLEAGUE_EFFORT_DECAY", decay)):
        monkeypatch.setenv(key, "1" if on else "0")


class TestUnarmed:
    @pytest.mark.parametrize("spikes,decay", [(False, False), (True, False), (False, True)])
    def test_no_attribute_write_and_empty_record(
        self, monkeypatch: pytest.MonkeyPatch, spikes: bool, decay: bool
    ) -> None:
        _arm(monkeypatch, spikes=spikes, decay=decay)
        config = _Config()
        ctx = _ctx(config, turns=3)
        assert ctx.effort_decay is None
        ge.note_reset(ctx)
        with ge.decayed_turn(ctx) as rung:
            assert rung is None
            assert not hasattr(config, _ATTR)
        assert not hasattr(config, _ATTR)
        assert ctx.result.effort_decay == {}
        assert "effort_decay" not in ctx.result.to_dict()

    def test_context_controls_binds_none_when_unarmed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _arm(monkeypatch, spikes=True, decay=False)
        assert ge.make_decay(object()) is None


class TestArmed:
    def test_offsets_after_a_reset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _arm(monkeypatch, spikes=True, decay=True)
        config = _Config()
        ctx = _ctx(config, turns=4)
        # Nothing before the first reset: the seat's own floor applies.
        with ge.decayed_turn(ctx) as rung:
            assert rung is None
            assert not hasattr(config, _ATTR)
        # A spike fired as model turn 4 (accounted already).
        ge.note_reset(ctx)
        with ge.decayed_turn(ctx) as rung:  # this completion = turn 5 = offset 1
            assert rung == "low"
            assert getattr(config, _ATTR) == "low"
        assert not hasattr(config, _ATTR)  # popped: absent again, never a None row
        ctx.result.stats.model_turns = 5
        ge.commit_acting_turn(ctx, {"point": None, "rung": rung})
        with ge.decayed_turn(ctx) as rung:  # turn 6 = offset 2
            assert rung == "off"
            assert getattr(config, _ATTR) == "off"
        assert not hasattr(config, _ATTR)
        ctx.result.stats.model_turns = 6
        ge.commit_acting_turn(ctx, {"point": None, "rung": rung})
        with ge.decayed_turn(ctx) as rung:  # turn 7 = offset 3
            assert rung == "off"
        ctx.result.stats.model_turns = 7
        ge.commit_acting_turn(ctx, {"point": None, "rung": rung})
        assert ctx.effort_decay.to_dict() == {"resets": [4], "turns": {"low": 1, "off": 2}}
        assert ctx.result.effort_decay == ctx.effort_decay.to_dict()

    def test_a_retry_without_accounting_does_not_inflate_counts(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _arm(monkeypatch, spikes=True, decay=True)
        ctx = _ctx(_Config(), turns=4)
        ge.note_reset(ctx)
        with ge.decayed_turn(ctx) as rung:
            assert rung == "low"
        # the loop got None back: no commit
        with ge.decayed_turn(ctx) as rung:
            assert rung == "low"
        assert ctx.effort_decay.turns == {}
        assert ctx.result.effort_decay == {"resets": [4], "turns": {}}

    def test_a_second_reset_restarts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _arm(monkeypatch, spikes=True, decay=True)
        ctx = _ctx(_Config(), turns=2)
        ge.note_reset(ctx)  # a spike fired as model turn 2
        with ge.decayed_turn(ctx) as rung:  # turn 3 = offset 1
            assert rung == "low"
        ctx.result.stats.model_turns = 3
        with ge.decayed_turn(ctx) as rung:  # turn 4 = offset 2
            assert rung == "off"
        ctx.result.stats.model_turns = 4
        ge.note_reset(ctx)  # e.g. a repeated-gate escalation at turn 4
        with ge.decayed_turn(ctx) as rung:  # turn 5 = offset 1 again
            assert rung == "low"
        assert ctx.effort_decay.resets == [2, 4]

    def test_restores_a_pre_existing_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _arm(monkeypatch, spikes=True, decay=True)
        config = _Config()
        setattr(config, _ATTR, "medium")  # a seat builder already pinned this config
        ctx = _ctx(config, turns=1)
        ge.note_reset(ctx)
        with ge.decayed_turn(ctx):
            assert getattr(config, _ATTR) == "low"
        assert getattr(config, _ATTR) == "medium"


class TestEverySpikeSiteResets:
    def test_gate_record_resets(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _arm(monkeypatch, spikes=True, decay=True)
        ctx = _ctx(_Config(), turns=7)
        with ge.escalated_gate_turn(ctx, "affected_tests", attempt=2) as fired:
            assert fired is True
        assert ctx.effort_decay.resets == [7]

    def test_fillline_arm_resets(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _arm(monkeypatch, spikes=True, decay=True)
        monkeypatch.setattr(ge.SeatEscalator, "fillline_rung", lambda self: "xhigh")
        ctx = _ctx(_Config(), turns=9)
        assert ge.arm_fillline_decision(ctx) is True
        ge.disarm_fillline_decision(ctx)
        assert ctx.effort_decay.resets == [9]

    def test_barrier_reset_hook_delegates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from colleague import loop_barrier

        _arm(monkeypatch, spikes=True, decay=True)
        ctx = _ctx(_Config(), turns=11)
        loop_barrier._note_decay_reset(ctx)
        assert ctx.effort_decay.resets == [11]


class TestArtifactField:
    def test_round_trip_and_omit_when_empty(self) -> None:
        result = TaskResult(task_id="t", status="ok", summary="")
        assert "effort_decay" not in result.to_dict()
        result.effort_decay = {"resets": [4], "turns": {"low": 1, "off": 2}}
        data = result.to_dict()
        assert data["effort_decay"] == {"resets": [4], "turns": {"low": 1, "off": 2}}
        back = TaskResult.from_dict(data)
        assert back.effort_decay == result.effort_decay

    def test_from_dict_tolerates_garbage(self) -> None:
        back = TaskResult.from_dict({"task_id": "t", "status": "ok", "effort_decay": "nope"})
        assert back.effort_decay == {}

    def test_context_controls_carries_the_field(self) -> None:
        assert "effort_decay" in ContextControls.__dataclass_fields__
