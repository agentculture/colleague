"""Floor tests for agentfront.taui v0.2 (agentfront 0.18.0, agentfront#43).

These assert the TAUI work-loop cockpit surface is present on the installed
agentfront package.  They do NOT import colleague internals — the point is to
gate the external contract, not our own assumptions.
"""

import agentfront.taui.events as taui_events
import agentfront.taui.mirror as taui_mirror
import agentfront.taui.snapshot as taui_snapshot
import agentfront.taui.state as taui_state


class TestTauiMirror:
    def test_schema_version_is_0_2(self) -> None:
        assert taui_mirror.SCHEMA_VERSION == "0.2"


class TestTauiState:
    def test_state_has_background_field(self) -> None:
        state = taui_state.TAUIState()
        assert hasattr(state, "background")


class TestTauiEvents:
    def test_work_step_exists(self) -> None:
        assert hasattr(taui_events, "WorkStep")

    def test_skill_suggested_exists(self) -> None:
        assert hasattr(taui_events, "SkillSuggested")


class TestTauiSnapshot:
    def test_write_snapshot_exists(self) -> None:
        assert hasattr(taui_snapshot, "write_snapshot")

    def test_read_snapshot_exists(self) -> None:
        assert hasattr(taui_snapshot, "read_snapshot")

    def test_replay_exists(self) -> None:
        assert hasattr(taui_snapshot, "replay")
