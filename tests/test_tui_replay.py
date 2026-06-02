"""Tests for colleague.tui.replay — deterministic event-log folding.

Criteria tested:
1. replay() folds events correctly (frame after 3 ticks == 3; skill popup
   present but visible=False after SkillSuggested + Dismiss).
2. Determinism: replaying the same event log twice yields byte-identical ANSI
   output from render().
3. Module source imports no os / time / random.
4. replay_from_jsonl(dumps_events(evts)) reconstructs the same state as
   replay(evts).
"""

from __future__ import annotations

import inspect

import colleague.tui.replay as _replay_mod
from colleague.tui.events import Dismiss, SkillSuggested, Tick, dumps_events
from colleague.tui.render.ansi import render
from colleague.tui.replay import replay, replay_from_jsonl
from colleague.tui.state import CockpitState

# ---------------------------------------------------------------------------
# Criterion 1 — correctness
# ---------------------------------------------------------------------------


class TestReplayCorrectness:
    def test_three_ticks_advance_frame_to_three(self) -> None:
        evts = [Tick(delta=1), Tick(delta=1), Tick(delta=1)]
        state = replay(evts)
        assert state.background.frame == 3

    def test_tick_with_delta_increments_by_delta(self) -> None:
        evts = [Tick(delta=5)]
        state = replay(evts)
        assert state.background.frame == 5

    def test_empty_events_returns_default_state(self) -> None:
        state = replay([])
        default = CockpitState()
        assert state.background.frame == default.background.frame

    def test_custom_initial_state_is_used(self) -> None:
        from dataclasses import replace

        initial = CockpitState()
        initial.background = replace(initial.background, frame=10)
        evts = [Tick(delta=1)]
        state = replay(evts, initial=initial)
        assert state.background.frame == 11

    def test_skill_suggested_then_dismiss_popup_present_but_not_visible(self) -> None:
        evts = [
            SkillSuggested(skill="boost", reason="fast"),
            Dismiss(target="popup.skill.boost"),
        ]
        state = replay(evts)

        # Popup is present in the list
        popup = next((p for p in state.popups if p.id == "popup.skill.boost"), None)
        assert popup is not None, "popup.skill.boost should be present"
        # Popup is NOT visible
        assert popup.visible is False, "popup should be invisible after dismiss"

    def test_skill_suggested_popup_visible_before_dismiss(self) -> None:
        evts = [SkillSuggested(skill="boost", reason="fast")]
        state = replay(evts)

        popup = next((p for p in state.popups if p.id == "popup.skill.boost"), None)
        assert popup is not None
        assert popup.visible is True

    def test_replay_does_not_mutate_initial_state(self) -> None:
        initial = CockpitState()
        initial_frame = initial.background.frame
        replay([Tick(delta=3)], initial=initial)
        # Original untouched
        assert initial.background.frame == initial_frame

    def test_replay_returns_cockpit_state(self) -> None:
        state = replay([Tick(delta=1)])
        assert isinstance(state, CockpitState)


# ---------------------------------------------------------------------------
# Criterion 2 — determinism
# ---------------------------------------------------------------------------


class TestReplayDeterminism:
    def test_two_replays_of_same_events_yield_identical_ansi(self) -> None:
        evts = [
            Tick(delta=2),
            SkillSuggested(skill="boost", reason="test"),
            Dismiss(target="popup.skill.boost"),
            Tick(delta=1),
        ]
        out1 = render(replay(evts))
        out2 = render(replay(evts))
        assert out1 == out2, "render(replay(evts)) must be byte-identical across two calls"

    def test_empty_list_determinism(self) -> None:
        out1 = render(replay([]))
        out2 = render(replay([]))
        assert out1 == out2

    def test_determinism_with_custom_initial(self) -> None:
        from dataclasses import replace

        initial = CockpitState()
        initial.background = replace(initial.background, frame=7)
        evts = [Tick(delta=1)]

        # Each call gets a fresh copy of initial so we must build two separate
        # initial instances with the same values.
        from dataclasses import replace as dc_replace

        initial_a = CockpitState()
        initial_a.background = dc_replace(initial_a.background, frame=7)
        initial_b = CockpitState()
        initial_b.background = dc_replace(initial_b.background, frame=7)

        out1 = render(replay(evts, initial=initial_a))
        out2 = render(replay(evts, initial=initial_b))
        assert out1 == out2


# ---------------------------------------------------------------------------
# Criterion 3 — no os / time / random imports in the module source
# ---------------------------------------------------------------------------


class TestReplayNoForbiddenImports:
    def test_module_source_has_no_os_import(self) -> None:
        src = inspect.getsource(_replay_mod)
        # Very conservative: check there is no "import os" or "from os"
        for line in src.splitlines():
            stripped = line.strip()
            assert not (
                stripped.startswith("import os") or stripped.startswith("from os")
            ), f"Forbidden 'os' import found in replay.py: {line!r}"

    def test_module_source_has_no_time_import(self) -> None:
        src = inspect.getsource(_replay_mod)
        for line in src.splitlines():
            stripped = line.strip()
            assert not (
                stripped.startswith("import time") or stripped.startswith("from time")
            ), f"Forbidden 'time' import found in replay.py: {line!r}"

    def test_module_source_has_no_random_import(self) -> None:
        src = inspect.getsource(_replay_mod)
        for line in src.splitlines():
            stripped = line.strip()
            assert not (
                stripped.startswith("import random") or stripped.startswith("from random")
            ), f"Forbidden 'random' import found in replay.py: {line!r}"


# ---------------------------------------------------------------------------
# Criterion 4 — replay_from_jsonl round-trips with dumps_events
# ---------------------------------------------------------------------------


class TestReplayFromJsonl:
    def test_round_trip_empty(self) -> None:
        evts: list = []
        state_direct = replay(evts)
        state_jsonl = replay_from_jsonl(dumps_events(evts))
        assert state_direct.to_dict() == state_jsonl.to_dict()

    def test_round_trip_ticks(self) -> None:
        evts = [Tick(delta=1), Tick(delta=2), Tick(delta=3)]
        state_direct = replay(evts)
        state_jsonl = replay_from_jsonl(dumps_events(evts))
        assert state_direct.to_dict() == state_jsonl.to_dict()
        assert state_jsonl.background.frame == 6

    def test_round_trip_skill_and_dismiss(self) -> None:
        evts = [
            SkillSuggested(skill="boost", reason="perf"),
            Dismiss(target="popup.skill.boost"),
        ]
        state_direct = replay(evts)
        state_jsonl = replay_from_jsonl(dumps_events(evts))
        assert state_direct.to_dict() == state_jsonl.to_dict()

    def test_round_trip_with_initial_state(self) -> None:
        from dataclasses import replace

        initial_a = CockpitState()
        initial_a.background = replace(initial_a.background, frame=5)
        initial_b = CockpitState()
        initial_b.background = replace(initial_b.background, frame=5)

        evts = [Tick(delta=1)]
        state_direct = replay(evts, initial=initial_a)
        state_jsonl = replay_from_jsonl(dumps_events(evts), initial=initial_b)
        assert state_direct.to_dict() == state_jsonl.to_dict()

    def test_replay_from_jsonl_returns_cockpit_state(self) -> None:
        state = replay_from_jsonl(dumps_events([Tick(delta=1)]))
        assert isinstance(state, CockpitState)
