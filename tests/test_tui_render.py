"""Tests for the stdlib ANSI renderer (convertible/tui/render/ansi.py).

TDD: tests written before implementation, covering:
- render() returns str
- visible popup message/title appears in output
- status.severity == "error" emits red SGR code AND message text
- hidden popup message does NOT appear
- determinism: same state → same output; differing frame → may differ
"""

from convertible.tui.render.ansi import render
from convertible.tui.state import (
    Action,
    Background,
    CockpitState,
    Panel,
    PanelItem,
    Popup,
    Status,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_RED_SGR = "\x1b[31m"
_POPUP_MSG = "Stronger agent recommended (boost)"
_STATUS_MSG = "Boost agent failed to respond"


def _make_state_with_visible_popup() -> CockpitState:
    popup = Popup(
        id="boost-suggestion",
        kind="skill_suggestion",
        visible=True,
        message=_POPUP_MSG,
        actions=[Action(selector="button.ok", input="enter", description="Accept")],
    )
    return CockpitState(
        status=Status(severity="error", message=_STATUS_MSG),
        popups=[popup],
    )


def _make_state_with_hidden_popup() -> CockpitState:
    popup = Popup(
        id="boost-hidden",
        kind="skill_suggestion",
        visible=False,
        message=_POPUP_MSG,
    )
    return CockpitState(
        status=Status(severity="info", message="All good"),
        popups=[popup],
    )


# ---------------------------------------------------------------------------
# Core acceptance tests
# ---------------------------------------------------------------------------


def test_render_returns_str() -> None:
    """render() must return a plain str."""
    state = _make_state_with_visible_popup()
    result = render(state)
    assert isinstance(result, str)


def test_visible_popup_message_in_output() -> None:
    """Visible popup message text must appear verbatim in rendered output."""
    state = _make_state_with_visible_popup()
    result = render(state)
    assert _POPUP_MSG in result


def test_error_severity_emits_red_sgr() -> None:
    """When status.severity == 'error', output must contain the red ANSI SGR code."""
    state = _make_state_with_visible_popup()
    result = render(state)
    assert _RED_SGR in result, "Expected red ANSI code \\x1b[31m for error severity"


def test_error_severity_status_message_present() -> None:
    """When status.severity == 'error', the status message text must still be in output."""
    state = _make_state_with_visible_popup()
    result = render(state)
    assert _STATUS_MSG in result, "Status message text must be present (not colour-only)"


def test_hidden_popup_message_absent() -> None:
    """Hidden popup message must NOT appear in rendered output."""
    state = _make_state_with_hidden_popup()
    result = render(state)
    assert _POPUP_MSG not in result, "Hidden popup message should not be rendered"


# ---------------------------------------------------------------------------
# Determinism tests
# ---------------------------------------------------------------------------


def test_render_deterministic_same_state() -> None:
    """Calling render() twice on the same state object yields identical output."""
    state = _make_state_with_visible_popup()
    assert render(state) == render(state)


def test_render_deterministic_equal_states() -> None:
    """Two freshly-built equal states yield identical output."""
    s1 = _make_state_with_visible_popup()
    s2 = _make_state_with_visible_popup()
    assert render(s1) == render(s2)


def test_render_different_frame_may_differ() -> None:
    """States that differ only in background.frame CAN produce different output.

    This test verifies that the renderer honours ``background.frame`` (e.g. for
    a spinner).  We check that there EXISTS some pair of frames whose outputs
    differ — we don't require every pair to differ (that would be too strong).
    """
    outputs = set()
    for frame in range(4):
        state = CockpitState(background=Background(animation="spinner", frame=frame))
        outputs.add(render(state))
    # At least two distinct frame outputs must exist (spinner chars rotate)
    assert (
        len(outputs) > 1
    ), "Expected spinner to produce at least 2 distinct outputs across frames 0-3"


# ---------------------------------------------------------------------------
# Widget-level smoke tests (via full render)
# ---------------------------------------------------------------------------


def test_skill_panel_items_in_output() -> None:
    """Items from the 'skills' panel should appear in rendered output."""
    panel = Panel(
        id="skills",
        title="Skills",
        visible=True,
        content_summary="2 skills",
        items=[
            PanelItem(id="s1", label="explore", status="active"),
            PanelItem(id="s2", label="review", status="available"),
        ],
    )
    state = CockpitState(panels=[panel])
    result = render(state)
    assert "explore" in result
    assert "review" in result


def test_conversation_panel_summary_in_output() -> None:
    """The conversation panel content_summary should appear in rendered output."""
    panel = Panel(
        id="conversation",
        title="Conversation",
        visible=True,
        content_summary="3 messages exchanged",
    )
    state = CockpitState(panels=[panel])
    result = render(state)
    assert "3 messages exchanged" in result


def test_conversation_panel_reducer_id_renders() -> None:
    """A live drive's conversation (reducer id 'panel.conversation') must render —
    not only the bare 'conversation' id used by hand-built states (#74 A1)."""
    panel = Panel(
        id="panel.conversation",
        title="Conversation",
        visible=True,
        content_summary="[read_file] main.py\n[run_command] pytest -q",
    )
    result = render(CockpitState(panels=[panel]))
    # Each newline-separated step renders on its own row.
    assert "[read_file] main.py" in result
    assert "[run_command] pytest -q" in result


def test_prompt_input_shows_focus_indicator() -> None:
    """When focused == 'input.prompt', the prompt line should include a focus indicator."""
    state = CockpitState(focused="input.prompt")
    result = render(state)
    # We just need SOME indicator of the prompt input; the exact glyph is impl detail
    assert ">" in result or "»" in result or "▶" in result or "│" in result


def test_popup_action_label_in_output() -> None:
    """Visible popup action description should appear in rendered output."""
    popup = Popup(
        id="confirm",
        kind="confirmation",
        visible=True,
        message="Are you sure?",
        actions=[Action(selector="button.ok", input="enter", description="Confirm")],
    )
    state = CockpitState(popups=[popup])
    result = render(state)
    assert "Confirm" in result


def test_warn_severity_emits_yellow_sgr() -> None:
    """When status.severity == 'warn', output must contain yellow ANSI SGR code."""
    state = CockpitState(status=Status(severity="warn", message="Low memory"))
    result = render(state)
    assert "\x1b[33m" in result
    assert "Low memory" in result


def test_success_severity_emits_green_sgr() -> None:
    """When status.severity == 'success', output must contain green ANSI SGR code."""
    state = CockpitState(status=Status(severity="success", message="Drive complete"))
    result = render(state)
    assert "\x1b[32m" in result
    assert "Drive complete" in result


def test_empty_state_renders_without_error() -> None:
    """A minimal default CockpitState must render without raising."""
    state = CockpitState()
    result = render(state)
    assert isinstance(result, str)
