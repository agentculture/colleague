"""Tests for convertible.tui.reducer — pure reduce(state, event) -> state."""

import copy
import inspect

from convertible.tui.events import (
    Dismiss,
    DriveStep,
    KeyPress,
    SkillSuggested,
    Tick,
    UserInput,
)
from convertible.tui.state import CockpitState, Drive

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fresh() -> CockpitState:
    """Return a brand-new default CockpitState."""
    return CockpitState()


def _fresh_with_drive() -> CockpitState:
    state = CockpitState()
    state.drive = Drive(task_id="t1", engine="mock", step_count=0, running=True)
    return state


# ---------------------------------------------------------------------------
# Purity — module must NOT import os / time / random
# ---------------------------------------------------------------------------


def test_reducer_module_no_os_import():
    import convertible.tui.reducer as mod

    src = inspect.getsource(mod)
    assert "import os" not in src, "reducer.py must not import 'os'"
    assert "from os" not in src, "reducer.py must not import from 'os'"


def test_reducer_module_no_time_import():
    import convertible.tui.reducer as mod

    src = inspect.getsource(mod)
    assert "import time" not in src, "reducer.py must not import 'time'"
    assert "from time" not in src, "reducer.py must not import from 'time'"


def test_reducer_module_no_random_import():
    import convertible.tui.reducer as mod

    src = inspect.getsource(mod)
    assert "import random" not in src, "reducer.py must not import 'random'"
    assert "from random" not in src, "reducer.py must not import from 'random'"


def test_reducer_returns_distinct_object():
    """reduce() must not mutate the input; output must be a new object."""
    from convertible.tui.reducer import reduce

    original = _fresh()
    # Take a deep snapshot before calling
    snapshot = copy.deepcopy(original)

    new_state = reduce(original, Tick(delta=3))

    # Input state is unchanged
    assert original.background.frame == snapshot.background.frame
    # Output is a distinct object
    assert new_state is not original


# ---------------------------------------------------------------------------
# Tick
# ---------------------------------------------------------------------------


def test_tick_advances_frame_by_delta():
    from convertible.tui.reducer import reduce

    s0 = _fresh()
    s0.background.frame = 5
    s1 = reduce(s0, Tick(delta=3))
    assert s1.background.frame == 8


def test_tick_default_delta_advances_by_one():
    from convertible.tui.reducer import reduce

    s0 = _fresh()
    s1 = reduce(s0, Tick())
    assert s1.background.frame == 1


def test_tick_does_not_change_other_fields():
    from convertible.tui.reducer import reduce

    s0 = _fresh()
    s1 = reduce(s0, Tick(delta=2))
    # Everything except frame should be unchanged
    assert s1.screen == s0.screen
    assert s1.mode == s0.mode
    assert s1.focused == s0.focused
    assert s1.popups == s0.popups
    assert s1.panels == s0.panels
    assert s1.background.theme == s0.background.theme
    assert s1.background.animation == s0.background.animation
    assert s1.background.semantic == s0.background.semantic


def test_tick_does_not_mutate_input():
    from convertible.tui.reducer import reduce

    s0 = _fresh()
    original_frame = s0.background.frame
    reduce(s0, Tick(delta=10))
    assert s0.background.frame == original_frame


# ---------------------------------------------------------------------------
# SkillSuggested
# ---------------------------------------------------------------------------


def test_skill_suggested_opens_popup():
    from convertible.tui.reducer import reduce

    s0 = _fresh()
    s1 = reduce(s0, SkillSuggested(skill="boost"))
    popup_ids = [p.id for p in s1.popups]
    assert "popup.skill.boost" in popup_ids


def test_skill_suggested_popup_is_visible():
    from convertible.tui.reducer import reduce

    s1 = reduce(_fresh(), SkillSuggested(skill="boost"))
    p = next(p for p in s1.popups if p.id == "popup.skill.boost")
    assert p.visible is True


def test_skill_suggested_popup_kind():
    from convertible.tui.reducer import reduce

    s1 = reduce(_fresh(), SkillSuggested(skill="boost"))
    p = next(p for p in s1.popups if p.id == "popup.skill.boost")
    assert p.kind == "skill_suggestion"


def test_skill_suggested_popup_not_blocking():
    from convertible.tui.reducer import reduce

    s1 = reduce(_fresh(), SkillSuggested(skill="boost"))
    p = next(p for p in s1.popups if p.id == "popup.skill.boost")
    assert p.blocking is False


def test_skill_suggested_popup_opened_by():
    from convertible.tui.reducer import reduce

    s1 = reduce(_fresh(), SkillSuggested(skill="boost"))
    p = next(p for p in s1.popups if p.id == "popup.skill.boost")
    assert p.opened_by == "skill"


def test_skill_suggested_popup_reason():
    from convertible.tui.reducer import reduce

    s1 = reduce(_fresh(), SkillSuggested(skill="boost", reason="speed"))
    p = next(p for p in s1.popups if p.id == "popup.skill.boost")
    assert p.reason == "speed"


def test_skill_suggested_popup_message():
    from convertible.tui.reducer import reduce

    s1 = reduce(_fresh(), SkillSuggested(skill="boost"))
    p = next(p for p in s1.popups if p.id == "popup.skill.boost")
    assert "boost" in p.message


def test_skill_suggested_popup_actions_selectors():
    from convertible.tui.reducer import reduce

    s1 = reduce(_fresh(), SkillSuggested(skill="boost"))
    p = next(p for p in s1.popups if p.id == "popup.skill.boost")
    selectors = [a.selector for a in p.actions]
    assert "popup.skill.boost.accept" in selectors
    assert "popup.skill.boost.dismiss" in selectors
    assert "popup.skill.boost.details" in selectors


def test_skill_suggested_popup_actions_inputs():
    from convertible.tui.reducer import reduce

    s1 = reduce(_fresh(), SkillSuggested(skill="boost"))
    p = next(p for p in s1.popups if p.id == "popup.skill.boost")
    inputs = {a.selector: a.input for a in p.actions}
    assert inputs["popup.skill.boost.accept"] == "enter"
    assert inputs["popup.skill.boost.dismiss"] == "esc"
    assert inputs["popup.skill.boost.details"] == "d"


def test_skill_suggested_sets_background_theme():
    from convertible.tui.reducer import reduce

    s1 = reduce(_fresh(), SkillSuggested(skill="boost"))
    assert s1.background.theme == "boost-suggested"


def test_skill_suggested_sets_background_semantic():
    from convertible.tui.reducer import reduce

    s1 = reduce(_fresh(), SkillSuggested(skill="boost"))
    assert s1.background.semantic == "stronger_agent_recommended"


def test_skill_suggested_replaces_existing_popup():
    """Firing SkillSuggested twice for the same skill must not duplicate the popup."""
    from convertible.tui.reducer import reduce

    s1 = reduce(_fresh(), SkillSuggested(skill="boost", reason="first"))
    s2 = reduce(s1, SkillSuggested(skill="boost", reason="second"))
    boost_popups = [p for p in s2.popups if p.id == "popup.skill.boost"]
    assert len(boost_popups) == 1
    assert boost_popups[0].reason == "second"


def test_skill_suggested_works_for_any_skill():
    """Generic: a skill other than 'boost' should work the same way."""
    from convertible.tui.reducer import reduce

    s1 = reduce(_fresh(), SkillSuggested(skill="deepresearch"))
    popup_ids = [p.id for p in s1.popups]
    assert "popup.skill.deepresearch" in popup_ids
    p = next(p for p in s1.popups if p.id == "popup.skill.deepresearch")
    assert p.visible is True
    assert s1.background.theme == "deepresearch-suggested"


# ---------------------------------------------------------------------------
# Dismiss
# ---------------------------------------------------------------------------


def test_dismiss_hides_popup():
    from convertible.tui.reducer import reduce

    s1 = reduce(_fresh(), SkillSuggested(skill="boost"))
    s2 = reduce(s1, Dismiss(target="popup.skill.boost"))
    p = next(p for p in s2.popups if p.id == "popup.skill.boost")
    assert p.visible is False


def test_dismiss_does_not_remove_popup():
    """Dismiss hides the popup but does not delete it from the list."""
    from convertible.tui.reducer import reduce

    s1 = reduce(_fresh(), SkillSuggested(skill="boost"))
    s2 = reduce(s1, Dismiss(target="popup.skill.boost"))
    assert any(p.id == "popup.skill.boost" for p in s2.popups)


def test_dismiss_unknown_target_is_noop():
    """Dismissing a non-existent popup id should not raise."""
    from convertible.tui.reducer import reduce

    s0 = _fresh()
    s1 = reduce(s0, Dismiss(target="popup.nonexistent"))
    assert len(s1.popups) == 0


def test_dismiss_leaves_other_popups_unchanged():
    """Dismissing one popup must not affect other popups."""
    from convertible.tui.reducer import reduce

    s1 = reduce(_fresh(), SkillSuggested(skill="boost"))
    s2 = reduce(s1, SkillSuggested(skill="other"))
    s3 = reduce(s2, Dismiss(target="popup.skill.boost"))
    other = next(p for p in s3.popups if p.id == "popup.skill.other")
    assert other.visible is True


# ---------------------------------------------------------------------------
# UserInput
# ---------------------------------------------------------------------------


def test_user_input_focuses_prompt():
    from convertible.tui.reducer import reduce

    s1 = reduce(_fresh(), UserInput(text="hello"))
    assert s1.focused == "input.prompt"


def test_user_input_creates_conversation_panel():
    from convertible.tui.reducer import reduce

    s1 = reduce(_fresh(), UserInput(text="hello"))
    panel_ids = [p.id for p in s1.panels]
    assert "panel.conversation" in panel_ids


def test_user_input_appends_text_to_conversation():
    from convertible.tui.reducer import reduce

    s1 = reduce(_fresh(), UserInput(text="hello"))
    panel = next(p for p in s1.panels if p.id == "panel.conversation")
    assert "hello" in panel.content_summary


def test_user_input_second_message_appends():
    from convertible.tui.reducer import reduce

    s1 = reduce(_fresh(), UserInput(text="first"))
    s2 = reduce(s1, UserInput(text="second"))
    panel = next(p for p in s2.panels if p.id == "panel.conversation")
    assert "first" in panel.content_summary
    assert "second" in panel.content_summary


def test_user_input_conversation_panel_title():
    from convertible.tui.reducer import reduce

    s1 = reduce(_fresh(), UserInput(text="hi"))
    panel = next(p for p in s1.panels if p.id == "panel.conversation")
    assert panel.title == "Conversation"


# ---------------------------------------------------------------------------
# Key
# ---------------------------------------------------------------------------


def test_key_does_not_crash():
    from convertible.tui.reducer import reduce

    s0 = _fresh()
    s1 = reduce(s0, KeyPress(key="up"))
    assert s1 is not None


def test_key_returns_new_object():
    from convertible.tui.reducer import reduce

    s0 = _fresh()
    s1 = reduce(s0, KeyPress(key="tab"))
    assert s1 is not s0


# ---------------------------------------------------------------------------
# DriveStep
# ---------------------------------------------------------------------------


def test_drive_step_increments_step_count_when_drive_active():
    from convertible.tui.reducer import reduce

    s0 = _fresh_with_drive()
    s1 = reduce(s0, DriveStep(tool="read_file", summary="read main.py"))
    assert s1.drive is not None
    assert s1.drive.step_count == 1


def test_drive_step_appends_conversation_line():
    from convertible.tui.reducer import reduce

    s1 = reduce(_fresh_with_drive(), DriveStep(tool="write_file", summary="wrote x.py"))
    panel = next((p for p in s1.panels if p.id == "panel.conversation"), None)
    assert panel is not None
    assert "write_file" in panel.content_summary
    assert "wrote x.py" in panel.content_summary


def test_drive_step_no_drive_still_appends_conversation():
    from convertible.tui.reducer import reduce

    s0 = _fresh()  # drive is None
    s1 = reduce(s0, DriveStep(tool="run_command", summary="ran tests"))
    panel = next((p for p in s1.panels if p.id == "panel.conversation"), None)
    assert panel is not None
    assert "run_command" in panel.content_summary


def test_drive_step_no_drive_does_not_create_drive():
    from convertible.tui.reducer import reduce

    s0 = _fresh()
    s1 = reduce(s0, DriveStep(tool="finish", summary="done"))
    assert s1.drive is None


def test_drive_step_does_not_mutate_input_drive():
    from convertible.tui.reducer import reduce

    s0 = _fresh_with_drive()
    original_count = s0.drive.step_count  # type: ignore[union-attr]
    reduce(s0, DriveStep(tool="read_file", summary="x"))
    assert s0.drive.step_count == original_count  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Unknown event
# ---------------------------------------------------------------------------


def test_unknown_event_returns_new_copy():
    from convertible.tui.reducer import reduce

    class _Weird:
        pass

    s0 = _fresh()
    s1 = reduce(s0, _Weird())
    assert s1 is not s0
    # Content is unchanged
    assert s1.screen == s0.screen
    assert s1.background.frame == s0.background.frame
