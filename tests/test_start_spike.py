"""``start.first_turn`` — the position-keyed orientation spike (effort-floor-and-decay arc).

The run's FIRST acting completion runs at the table's ``medium`` with tools
on; it is recorded as a spike, stamps a stall mark, and resets the decay clock
at turn 1 — so with decay armed turn 2 is ``low`` and turn 3+ ``off``. Keyed
by position (model-turn count 0 before it), never content. Unarmed: inert.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from colleague import effortspikes
from colleague import loop_gateescalation as ge
from colleague.contract import TaskResult, WorkStats

_ATTR = "reasoning_effort_seat"


class _Config:
    pass


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
        _stall_marks=[],
    )


def _arm(monkeypatch: pytest.MonkeyPatch, *, spikes: bool, decay: bool) -> None:
    for key, on in (("COLLEAGUE_EFFORT_SPIKES", spikes), ("COLLEAGUE_EFFORT_DECAY", decay)):
        monkeypatch.setenv(key, "1" if on else "0")
    monkeypatch.delenv("COLLEAGUE_EFFORT_SPIKE_START_FIRST_TURN", raising=False)


class TestTable:
    def test_point_enumerated_at_medium(self) -> None:
        assert "start.first_turn" in effortspikes.SPIKE_POINTS
        assert effortspikes.SPIKE_TABLE["start.first_turn"] == "medium"


class TestUnarmed:
    def test_nothing_pushed_or_recorded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _arm(monkeypatch, spikes=False, decay=False)
        config = _Config()
        ctx = _ctx(config)
        with ge.acting_turn(ctx) as pushed:
            assert pushed is None
            assert not hasattr(config, _ATTR)
        ge.commit_acting_turn(ctx, pushed)
        assert ctx.result.effort_spikes == []
        assert ctx._stall_marks == []


class TestArmed:
    def test_first_turn_is_medium_then_decays(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _arm(monkeypatch, spikes=True, decay=True)
        config = _Config()
        ctx = _ctx(config, turns=0)
        with ge.acting_turn(ctx) as pushed:  # turn 1
            assert pushed == {"point": "start.first_turn", "rung": "medium"}
            assert getattr(config, _ATTR) == "medium"
        assert not hasattr(config, _ATTR)
        # Nothing recorded until the completion is ACCOUNTED (Qodo #491 t4).
        assert ctx.result.effort_spikes == []
        ctx.result.stats.model_turns = 1  # _account_turn
        ge.commit_acting_turn(ctx, pushed)
        assert ctx.result.effort_spikes == [
            {"point": "start.first_turn", "rung": "medium", "seat": "cortex"}
        ]
        assert ctx._stall_marks == [1]
        assert ctx.effort_decay.resets == [1]
        with ge.acting_turn(ctx) as pushed:  # turn 2 = offset 1
            assert pushed == {"point": None, "rung": "low"}
        ctx.result.stats.model_turns = 2
        ge.commit_acting_turn(ctx, pushed)
        with ge.acting_turn(ctx) as pushed:  # turn 3 = offset 2
            assert pushed["rung"] == "off"
        ctx.result.stats.model_turns = 3
        ge.commit_acting_turn(ctx, pushed)
        assert ctx.effort_decay.to_dict() == {"resets": [1], "turns": {"low": 1, "off": 1}}

    def test_a_retry_without_accounting_does_not_consume_the_start_spike(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _arm(monkeypatch, spikes=True, decay=True)
        config = _Config()
        ctx = _ctx(config, turns=0)
        with ge.acting_turn(ctx) as pushed:
            assert pushed["point"] == "start.first_turn"
        # the loop got None back and retried: no commit, model_turns still 0
        with ge.acting_turn(ctx) as pushed:
            assert pushed["point"] == "start.first_turn"
            assert getattr(config, _ATTR) == "medium"
        assert ctx.result.effort_spikes == []
        assert ctx.effort_decay.resets == []

    def test_fires_once_only_on_turn_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _arm(monkeypatch, spikes=True, decay=False)
        ctx = _ctx(_Config(), turns=3)  # a continuation-like state: already past turn 1
        with ge.acting_turn(ctx) as pushed:
            assert pushed is None
        assert ctx.result.effort_spikes == []

    def test_without_decay_only_turn_one_is_touched(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _arm(monkeypatch, spikes=True, decay=False)
        config = _Config()
        ctx = _ctx(config, turns=0)
        with ge.acting_turn(ctx) as pushed:
            assert pushed["rung"] == "medium"
        ctx.result.stats.model_turns = 1
        ge.commit_acting_turn(ctx, pushed)
        with ge.acting_turn(ctx) as pushed:
            assert pushed is None
            assert not hasattr(config, _ATTR)

    def test_override_pins_the_rung(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _arm(monkeypatch, spikes=True, decay=False)
        monkeypatch.setenv("COLLEAGUE_EFFORT_SPIKE_START_FIRST_TURN", "low")
        ctx = _ctx(_Config(), turns=0)
        with ge.acting_turn(ctx) as pushed:
            assert pushed["rung"] == "low"


class TestFreshDecayPerRun:
    def test_fresh_decay_clones_a_new_clock(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _arm(monkeypatch, spikes=True, decay=True)
        bound = ge.make_decay(object())
        bound.reset(7)
        fresh = ge.fresh_decay(bound)
        assert fresh is not bound
        assert fresh.resets == []
        assert fresh.last_reset is None
        assert ge.fresh_decay(None) is None
