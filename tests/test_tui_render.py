"""Tests for the stdlib ANSI renderer (colleague/tui/render/ansi.py).

TDD: tests written before implementation, covering:
- render() returns str
- visible popup message/title appears in output
- status.severity == "error" emits red SGR code AND message text
- hidden popup message does NOT appear
- determinism: same state → same output; differing frame → may differ
"""

import re

from colleague.tui.render.ansi import render
from colleague.tui.render.layout import MIN_WIDTH
from colleague.tui.state import (
    Action,
    Background,
    CockpitState,
    Panel,
    PanelItem,
    Popup,
    Status,
)

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _visible_lines(frame: str) -> list[str]:
    """Frame lines with ANSI escapes stripped (so ``len`` is visible width)."""
    return [_ANSI_RE.sub("", line) for line in frame.splitlines()]


def _max_visible_width(frame: str) -> int:
    return max(len(line) for line in _visible_lines(frame))


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
    assert ">" in result or "»" in result or "▶" in result or "❯" in result or "│" in result


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


# ---------------------------------------------------------------------------
# Width / full-width / prompt tests (cockpit full-width fix)
# ---------------------------------------------------------------------------


def _conversation_state(summary: str = "hi") -> CockpitState:
    return CockpitState(
        panels=[Panel(id="panel.conversation", title="Session", content_summary=summary)]
    )


def test_render_width_is_honored() -> None:
    """A wider width produces wider frame separators / boxes than a narrow one."""
    state = _conversation_state()
    wide = _max_visible_width(render(state, width=120))
    narrow = _max_visible_width(render(state, width=40))
    assert wide == 120
    assert narrow == 40
    assert wide > narrow


def test_lone_conversation_gets_full_width() -> None:
    """With no skills panel (the session shape) the conversation fills the width."""
    out = render(_conversation_state("x"), width=100)
    borders = [line for line in _visible_lines(out) if line[:1] in ("╔", "╚")]
    assert borders
    assert all(len(line) == 100 for line in borders)


def test_side_by_side_split_widths() -> None:
    """Skills (fixed 30) + conversation (rest, minus the 2-space gap) tile to width."""
    skills = Panel(id="skills", title="Skills", items=[PanelItem(id="s1", label="explore")])
    conv = Panel(id="panel.conversation", title="Session", content_summary="hello")
    out = render(CockpitState(panels=[skills, conv]), width=100)
    # The top-border row joins a ┌…┐ skills box and a ╔…╗ conversation box.
    joined = [line for line in _visible_lines(out) if line.startswith("┌") and "╔" in line]
    assert joined, "expected a side-by-side top-border row"
    row = joined[0]
    assert len(row) == 100  # 30 (skills) + 2 (gap) + 68 (conversation)
    assert row[:30].startswith("┌")  # skills column is the fixed 30-wide left col
    assert row[32:].startswith("╔")  # conversation starts after the 2-space gap


def test_long_word_not_split_at_full_width() -> None:
    """The /help line that mangled at the old 46-char box stays intact at full width."""
    summary = "  /config             configuration readiness (doctor)"
    out = render(_conversation_state(summary), width=80)
    assert "readiness" in out  # not broken into "readines" + "s"


def test_tiny_width_does_not_raise() -> None:
    """A width below the clamp floor still renders (no negative-pad crash)."""
    out = render(_conversation_state("x"), width=10)
    assert isinstance(out, str) and out


def test_narrow_both_panels_stack_without_overflow() -> None:
    """A terminal too narrow for two columns stacks the panels and never overflows."""
    skills = Panel(id="skills", title="Skills", items=[PanelItem(id="s1", label="explore")])
    conv = Panel(id="panel.conversation", title="Session", content_summary="hello there")
    out = render(CockpitState(panels=[skills, conv]), width=60)  # 60 < 30+2+40
    assert _max_visible_width(out) <= 60  # no row exceeds the requested width
    assert "explore" in out and "hello there" in out  # both panels still visible


def test_pathologically_small_width_does_not_hang_or_raise() -> None:
    """width < 4 must not infinite-loop the wrap or raise on a negative field width."""
    state = _conversation_state("a fairly long conversation line that forces wrapping")
    out = render(state, width=3)
    assert isinstance(out, str) and out


def test_include_prompt_toggles_prompt_line() -> None:
    """include_prompt=False omits the prompt line; the default keeps it."""
    state = CockpitState(focused="input.prompt")
    assert "colleague ❯" in render(state, include_prompt=True)
    assert "colleague ❯" not in render(state, include_prompt=False)


def test_prompt_is_colleague_chevron_without_mode_label() -> None:
    """The prompt is the clean 'colleague ❯' chevron, not the confusing [planning]."""
    out = render(CockpitState())
    assert "colleague ❯" in out
    assert "[planning]" not in out


def test_detect_width_clamps_to_min(monkeypatch) -> None:
    """detect_width never returns below MIN_WIDTH even on a tiny terminal."""
    import os

    from colleague.tui.render import layout

    monkeypatch.setattr(
        layout.shutil,
        "get_terminal_size",
        lambda fallback=(80, 24): os.terminal_size((10, 24)),
    )
    assert layout.detect_width() == MIN_WIDTH
