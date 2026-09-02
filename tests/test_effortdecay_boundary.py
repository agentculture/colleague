"""Effort decay — the boundary + state tests (spec 2026-09-02-effort-floor-and-decay-arms).

Mirrors ``tests/test_effortspikes_boundary.py``'s descriptor-list style:

1. **Pinned table** -- ``DECAY_TABLE`` / ``DECAY_FLOOR`` hold exactly the
   spec's shape (``1 -> low``, everything past it ``off``); a drift fails here.
2. **Reset vocabulary** -- ``RESET_POINTS`` IS ``effortspikes.SPIKE_POINTS``
   (identity, not a copy), so the three enumerated spike points are the only
   resets.
3. **No model-reachable parameter** -- no function accepts an ``effort`` /
   ``rung`` / ``reasoning_effort`` keyword; ``rung_for_offset`` is keyed by an
   int offset only.
4. **Unarmed = inert** -- with either opt-in unset, ``decay_enabled`` is
   ``False`` and ``make_decay`` returns ``None``.
5. **The clock** -- offsets after a reset resolve ``1 -> low``, ``2+ -> off``;
   a second reset restarts the count; the record omits when nothing fired.
"""

from __future__ import annotations

import inspect

import pytest

from colleague import effortdecay, effortspikes

_FORBIDDEN_KEYWORDS = {"effort", "rung", "reasoning_effort", "reasoning_effort_seat"}


class TestPinnedTable:
    def test_table_is_exactly_offset_one_low(self) -> None:
        assert effortdecay.DECAY_TABLE == {1: "low"}

    def test_floor_is_off(self) -> None:
        assert effortdecay.DECAY_FLOOR == "off"

    @pytest.mark.parametrize("offset,expected", [(1, "low"), (2, "off"), (3, "off"), (40, "off")])
    def test_rung_for_offset_follows_the_table(self, offset: int, expected: str) -> None:
        assert effortdecay.rung_for_offset(offset) == expected

    @pytest.mark.parametrize("offset", [0, -1])
    def test_non_positive_offset_pushes_nothing(self, offset: int) -> None:
        assert effortdecay.rung_for_offset(offset) is None


class TestResetVocabulary:
    def test_reset_points_is_the_spike_points_object(self) -> None:
        assert effortdecay.RESET_POINTS is effortspikes.SPIKE_POINTS

    def test_exactly_five_reset_points(self) -> None:
        assert len(effortdecay.RESET_POINTS) == 5


class TestNoModelReachableParameter:
    def test_no_function_accepts_an_effort_or_rung_keyword(self) -> None:
        offenders = []
        for name, obj in inspect.getmembers(effortdecay, inspect.isfunction):
            if obj.__module__ != effortdecay.__name__:
                continue
            params = set(inspect.signature(obj).parameters)
            if params & _FORBIDDEN_KEYWORDS:
                offenders.append(name)
        for name, obj in inspect.getmembers(effortdecay.DecayState, inspect.isfunction):
            params = set(inspect.signature(obj).parameters) - {"self"}
            if params & _FORBIDDEN_KEYWORDS:
                offenders.append(f"DecayState.{name}")
        assert not offenders, offenders

    def test_rung_for_offset_takes_an_int_offset_only(self) -> None:
        assert list(inspect.signature(effortdecay.rung_for_offset).parameters) == ["offset"]


class TestUnarmedIsInert:
    def test_both_unset_is_the_armed_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Default ON since row 77 (deviation d1): both keys deleted = armed."""
        monkeypatch.delenv(effortdecay.DECAY_ENV, raising=False)
        monkeypatch.delenv("COLLEAGUE_EFFORT_SPIKES", raising=False)
        assert effortdecay.decay_enabled() is True
        assert isinstance(effortdecay.make_decay(), effortdecay.DecayState)

    def test_both_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(effortdecay.DECAY_ENV, "0")
        monkeypatch.setenv("COLLEAGUE_EFFORT_SPIKES", "0")
        assert effortdecay.decay_enabled() is False
        assert effortdecay.make_decay() is None

    def test_decay_without_spikes_is_inert(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(effortdecay.DECAY_ENV, "1")
        monkeypatch.setenv("COLLEAGUE_EFFORT_SPIKES", "0")
        assert effortdecay.decay_enabled() is False
        assert effortdecay.make_decay() is None

    def test_spikes_without_decay_is_inert(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(effortdecay.DECAY_ENV, "0")
        monkeypatch.setenv("COLLEAGUE_EFFORT_SPIKES", "1")
        assert effortdecay.decay_enabled() is False

    def test_disabling_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("COLLEAGUE_EFFORT_SPIKES", "1")
        for value in sorted(effortdecay.DECAY_DISABLING_VALUES):
            monkeypatch.setenv(effortdecay.DECAY_ENV, value)
            assert effortdecay.decay_enabled() is False, value


class TestClock:
    def test_no_reset_means_no_rung(self) -> None:
        state = effortdecay.DecayState()
        assert state.rung_for(1) is None
        assert state.rung_for(10) is None
        assert state.to_dict() == {}

    def test_offsets_after_a_reset(self) -> None:
        state = effortdecay.DecayState()
        state.reset(5)  # the spike fired as model turn 5
        assert state.rung_for(6) == "low"
        assert state.rung_for(7) == "off"
        assert state.rung_for(30) == "off"

    def test_a_second_reset_restarts_the_count(self) -> None:
        state = effortdecay.DecayState()
        state.reset(5)
        assert state.rung_for(9) == "off"
        state.reset(9)
        assert state.rung_for(10) == "low"
        assert state.rung_for(11) == "off"
        assert state.resets == [5, 9]

    def test_record_counts_turns_per_rung(self) -> None:
        state = effortdecay.DecayState()
        state.reset(2)
        for turn in (3, 4, 5):
            state.note(state.rung_for(turn))
        assert state.to_dict() == {"resets": [2], "turns": {"low": 1, "off": 2}}
