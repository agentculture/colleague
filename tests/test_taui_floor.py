"""Floor tests for the ``agentfront.taui`` surface colleague renders its cockpit from.

After issue #249 colleague no longer ships its own ``colleague/tui`` cockpit
modules — it imports ``agentfront.taui`` (the "import, don't duplicate" migration,
unblocked by agentfront#43 + agentfront#45, which brought up the work-loop cockpit
*and* the live-cockpit UI layer: the flat renderer, widgets, colors, and layout).

These assert the TAUI surface colleague depends on is present and shaped as
expected on the installed agentfront package.  They do NOT import colleague
internals — the point is to gate the *external* contract (so an agentfront
release that drops or reshapes a surface colleague uses fails here, loudly,
rather than deep inside a cockpit render).  agentfront owns the behavioural
tests for these modules; this is colleague's thin contract gate.
"""

import agentfront.taui.colors as taui_colors
import agentfront.taui.diagnose as taui_diagnose
import agentfront.taui.events as taui_events
import agentfront.taui.mirror as taui_mirror
import agentfront.taui.reducer as taui_reducer
import agentfront.taui.selectors as taui_selectors
import agentfront.taui.snapshot as taui_snapshot
import agentfront.taui.state as taui_state
from agentfront.taui.render import ansi as taui_ansi
from agentfront.taui.render import ansi_flat as taui_ansi_flat
from agentfront.taui.render import layout as taui_layout
from agentfront.taui.render import markdown as taui_markdown
from agentfront.taui.widgets import prompt_input as taui_prompt_input
from agentfront.taui.widgets import slash_autocomplete as taui_slash


class TestTauiMirror:
    def test_schema_version_is_0_2(self) -> None:
        assert taui_mirror.SCHEMA_VERSION == "0.2"

    def test_serialize_present(self) -> None:
        assert callable(taui_mirror.serialize)

    def test_mirror_carries_conversation_and_header(self) -> None:
        # The migration relies on the mirror exposing a top-level ``conversation``
        # list and a ``header`` block (vs colleague's old conversation-in-a-panel).
        mirror = taui_mirror.serialize(taui_state.TAUIState())
        assert "conversation" in mirror
        assert "header" in mirror
        assert mirror["taui_version"] == "0.2"


class TestTauiState:
    def test_state_has_background_field(self) -> None:
        state = taui_state.TAUIState()
        assert hasattr(state, "background")

    def test_state_is_frozen(self) -> None:
        # GAP 11: colleague's consumer code rewrote in-place mutation to
        # dataclasses.replace because the agentfront state is frozen.
        import dataclasses

        assert getattr(taui_state.TAUIState, "__dataclass_params__").frozen is True
        state = taui_state.TAUIState()
        try:
            state.mode = "x"  # type: ignore[misc]
        except dataclasses.FrozenInstanceError:
            pass
        else:  # pragma: no cover - the assert above guards this
            raise AssertionError("TAUIState should be frozen")

    def test_conversation_field_and_round_trip(self) -> None:
        state = taui_state.TAUIState()
        assert hasattr(state, "conversation")
        # from_dict tolerates the extra mirror keys (taui_version, available_actions)
        # — colleague's ``tui`` verbs load a serialized mirror back into a state.
        restored = taui_state.TAUIState.from_dict(taui_mirror.serialize(state))
        assert isinstance(restored, taui_state.TAUIState)

    def test_core_dataclasses_present(self) -> None:
        for name in ("Panel", "PanelItem", "Status", "WorkItem", "Header"):
            assert hasattr(taui_state, name), name


class TestTauiEvents:
    def test_work_step_carries_label(self) -> None:
        step = taui_events.WorkStep(label="[culture] agtag issues", ok=True)
        assert step.label == "[culture] agtag issues"

    def test_event_helpers_present(self) -> None:
        for name in ("UserInput", "SelectorAction", "SkillSuggested", "KeyPress"):
            assert hasattr(taui_events, name), name
        for fn in ("event_from_dict", "dumps_events", "loads_events"):
            assert callable(getattr(taui_events, fn)), fn


class TestTauiReducer:
    def test_reduce_and_replay_present(self) -> None:
        assert callable(taui_reducer.reduce)
        assert callable(taui_reducer.replay)

    def test_work_step_collapses_consecutive_runs(self) -> None:
        # The #233 ``×N`` feed collapse is agentfront's now (ConversationLine.count);
        # colleague's adapter composes the ``[tool] summary`` label this groups on.
        state = taui_state.TAUIState(work_item=taui_state.WorkItem(running=True))
        for _ in range(3):
            state = taui_reducer.reduce(state, taui_events.WorkStep(label="[culture] x"))
        assert len(state.conversation) == 1
        assert state.conversation[0].count == 3
        assert state.work_item.step_count == 3


class TestTauiSelectors:
    def test_state_based_selector_api(self) -> None:
        # GAP 6: resolve() takes the state dataclass (not the serialized dict).
        assert callable(taui_selectors.resolve)
        assert callable(taui_selectors.advertised_selectors)
        state = taui_state.TAUIState(
            panels=[
                taui_state.Panel(
                    id="commands",
                    title="C",
                    items=[taui_state.PanelItem(id="c.1", label="one")],
                )
            ]
        )
        assert "c.1" in taui_selectors.advertised_selectors(state)
        node = taui_selectors.resolve(state, "c.1")
        assert node.to_dict()["label"] == "one"


class TestTauiDiagnose:
    def test_structured_diagnose_seven_classes(self) -> None:
        assert callable(taui_diagnose.diagnose_structured)
        # 7-class diagnose surface (agentfront#43 uplift).
        assert len(taui_diagnose.BUG_CLASSES) == 7
        diag = taui_diagnose.diagnose_structured(taui_state.TAUIState())
        assert hasattr(diag, "findings") and hasattr(diag, "ok")


class TestTauiSnapshot:
    def test_quad_round_trip(self, tmp_path) -> None:
        assert callable(taui_snapshot.write_snapshot)
        assert callable(taui_snapshot.read_snapshot)
        assert callable(taui_snapshot.replay)  # re-exported from reducer
        stem = tmp_path / "snap"
        paths = taui_snapshot.write_snapshot(stem, taui_state.TAUIState(), [])
        assert set(paths) == {"json", "ansi", "events", "md"}
        snap = taui_snapshot.read_snapshot(stem)
        assert isinstance(snap.state, taui_state.TAUIState)


class TestTauiColors:
    def test_color_helpers_present(self) -> None:
        assert callable(taui_colors.should_color)
        assert taui_colors.strip_ansi("\x1b[31mx\x1b[0m") == "x"


class TestTauiRenderAndWidgets:
    """The live-cockpit UI layer agentfront#45 brought up (colleague's session
    renders the flat frame + slash popup through these)."""

    def test_renderers_present(self) -> None:
        assert callable(taui_ansi.render_ansi)
        assert callable(taui_ansi_flat.render_flat)
        assert callable(taui_markdown.render_markdown)
        assert callable(taui_layout.detect_width)

    def test_flat_render_prompt_and_feed(self) -> None:
        state = taui_state.TAUIState(header=taui_state.Header(title="colleague"))
        state = taui_reducer.reduce(state, taui_events.WorkStep(label="[read_file] a.py"))
        frame = taui_colors.strip_ansi(taui_ansi_flat.render_flat(state, width=80))
        # Header title drives the prompt word — colleague sets it to "colleague".
        assert "colleague ❯" in frame
        assert "[read_file] a.py" in frame

    def test_widgets_present(self) -> None:
        assert taui_prompt_input.plain_prompt(context="colleague") == "colleague ❯ "
        assert callable(taui_slash.render_slash_autocomplete)
        assert taui_slash.GROUP_ICON == "📁"
        assert taui_slash.SLASH_GROUPS == [
            ("controls", "Controls"),
            ("inspect", "Inspect"),
            ("session", "Session"),
        ]
