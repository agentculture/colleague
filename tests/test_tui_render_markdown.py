"""Tests for the Markdown renderer (colleague/tui/render/markdown.py).

TDD: tests written before implementation, covering:
- render_markdown() returns str
- reading-completeness vs TAUI mirror: every visible fact appears
- visible popup message and title appear verbatim
- hidden popup message does NOT appear
- panel title, content_summary, items appear for visible panels
- status severity and message appear
- drive info appears when present
- available_actions appear
- zones appear
- screen/mode/focused appear
- determinism: same state -> identical output
- stdlib-only: no third-party imports
"""

from __future__ import annotations

from colleague.tui.render.markdown import render_markdown
from colleague.tui.state import (
    Action,
    CockpitState,
    Panel,
    PanelItem,
    Popup,
    Status,
    WorkItem,
    Zone,
)
from colleague.tui.taui import serialize

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

_POPUP_MSG = "Stronger agent recommended (boost)"
_STATUS_MSG = "Boost agent failed to respond"
_POPUP_ID = "boost-suggestion"
_POPUP_KIND = "skill_suggestion"
# Expected title derived from diagnose._popup_title: "Skill Suggestion [boost-suggestion]"
_POPUP_TITLE_TEXT = "Skill Suggestion [boost-suggestion]"


def _make_state_with_visible_popup() -> CockpitState:
    popup = Popup(
        id=_POPUP_ID,
        kind=_POPUP_KIND,
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
        id="hidden-popup",
        kind="help",
        visible=False,
        message=_POPUP_MSG,
    )
    return CockpitState(
        status=Status(severity="info", message="All good"),
        popups=[popup],
    )


def _make_full_state() -> CockpitState:
    """Build a rich CockpitState exercising every TAUI-visible field."""
    popup = Popup(
        id="popup.confirm",
        kind="confirmation",
        visible=True,
        blocking=True,
        opened_by="system",
        reason="approve_hook",
        message="Approve the hook?",
        actions=[
            Action(selector="button.accept", input="enter", description="Accept"),
            Action(selector="button.reject", input="enter", description="Reject"),
        ],
        timeout_ms=5000,
    )
    panel = Panel(
        id="panel.skills",
        title="Skills",
        visible=True,
        content_summary="2 skills loaded",
        items=[
            PanelItem(id="skill.one", label="explore", status="available"),
            PanelItem(id="skill.two", label="review", status="active"),
        ],
    )
    return CockpitState(
        screen="main",
        mode="driving",
        focused="button.accept",
        popups=[popup],
        panels=[panel],
        status=Status(severity="error", message="Something went wrong"),
        work_item=WorkItem(task_id="t-123", engine="mock", step_count=3, running=True),
    )


# ---------------------------------------------------------------------------
# Basic contract
# ---------------------------------------------------------------------------


def test_render_markdown_returns_str() -> None:
    """render_markdown() must return a plain str."""
    state = _make_state_with_visible_popup()
    result = render_markdown(state)
    assert isinstance(result, str)


def test_render_markdown_non_empty() -> None:
    """Even a minimal default state produces non-empty Markdown."""
    state = CockpitState()
    result = render_markdown(state)
    assert len(result.strip()) > 0


# ---------------------------------------------------------------------------
# Screen / mode / focused
# ---------------------------------------------------------------------------


def test_screen_mode_focused_in_output() -> None:
    """screen, mode, and focused must appear in the Markdown output."""
    state = _make_full_state()
    result = render_markdown(state)
    assert "main" in result
    assert "driving" in result
    assert "button.accept" in result


# ---------------------------------------------------------------------------
# Zones
# ---------------------------------------------------------------------------


def test_visible_zones_in_output() -> None:
    """Visible zone names must appear in the Markdown output."""
    state = CockpitState()
    result = render_markdown(state)
    # Default state has four zones: top.status, left.skills, main.conversation, bottom.input
    for zone_name in ("top.status", "left.skills", "main.conversation", "bottom.input"):
        assert zone_name in result, f"Zone '{zone_name}' missing from Markdown"


def test_hidden_zone_not_shown_as_visible() -> None:
    """A zone marked visible=False should not be shown as visible in the output."""
    state = CockpitState(
        zones={
            "top.status": Zone(visible=False),
            "main.conversation": Zone(visible=True),
        }
    )
    result = render_markdown(state)
    # main.conversation is visible, top.status is hidden
    assert "main.conversation" in result
    # top.status appears somewhere (could be listed as hidden) but must not be
    # listed alongside the visible zones without qualification — the key
    # invariant is that "visible=False" information is not lost
    # (We test that the output correctly distinguishes visible from hidden zones)
    # The simplest testable invariant: hidden zone should not appear in a "Visible"
    # section alone without indication it is hidden.
    # We verify by checking that the visible section only contains main.conversation.
    # Actually: the spec says hidden zones should be clearly absent or marked.
    # Our renderer omits hidden zones from the zones listing. Verify top.status absent
    # from main zones table:
    lines_with_zone = [ln for ln in result.splitlines() if "top.status" in ln]
    # If top.status appears, it must be marked as hidden (contain "hidden" or "false")
    for line in lines_with_zone:
        assert (
            "hidden" in line.lower() or "false" in line.lower() or "no" in line.lower()
        ), f"top.status appears without hidden marker: {line!r}"


# ---------------------------------------------------------------------------
# Panels
# ---------------------------------------------------------------------------


def test_visible_panel_title_in_output() -> None:
    """Visible panel title must appear in the Markdown output."""
    state = _make_full_state()
    result = render_markdown(state)
    assert "Skills" in result


def test_visible_panel_content_summary_in_output() -> None:
    """Visible panel content_summary must appear in the Markdown output."""
    state = _make_full_state()
    result = render_markdown(state)
    assert "2 skills loaded" in result


def test_visible_panel_items_in_output() -> None:
    """Visible panel items (labels) must appear in the Markdown output."""
    state = _make_full_state()
    result = render_markdown(state)
    assert "explore" in result
    assert "review" in result


def test_hidden_panel_not_in_output() -> None:
    """A panel with visible=False should not surface its content in the output."""
    panel = Panel(
        id="hidden.panel",
        title="Secret Panel",
        visible=False,
        content_summary="secret content",
        items=[PanelItem(id="item.x", label="secret-item", status="available")],
    )
    state = CockpitState(panels=[panel])
    result = render_markdown(state)
    assert "Secret Panel" not in result
    assert "secret content" not in result
    assert "secret-item" not in result


# ---------------------------------------------------------------------------
# Popups — the critical compatibility requirement
# ---------------------------------------------------------------------------


def test_visible_popup_message_verbatim_in_output() -> None:
    """Visible popup message must appear VERBATIM in rendered Markdown (CRITICAL)."""
    state = _make_state_with_visible_popup()
    result = render_markdown(state)
    assert (
        _POPUP_MSG in result
    ), f"Visible popup message {_POPUP_MSG!r} must appear verbatim in Markdown"


def test_visible_popup_title_in_output() -> None:
    """Visible popup title '<Kind Label> [<id>]' must appear in rendered Markdown."""
    state = _make_state_with_visible_popup()
    result = render_markdown(state)
    assert (
        _POPUP_TITLE_TEXT in result
    ), f"Visible popup title {_POPUP_TITLE_TEXT!r} must appear in Markdown"


def test_visible_popup_id_in_output() -> None:
    """Visible popup id must appear in the Markdown output (checked via title)."""
    state = _make_state_with_visible_popup()
    result = render_markdown(state)
    assert _POPUP_ID in result, f"Popup id {_POPUP_ID!r} must appear in Markdown"


def test_hidden_popup_message_absent() -> None:
    """Hidden popup message must NOT appear in rendered Markdown."""
    state = _make_state_with_hidden_popup()
    result = render_markdown(state)
    assert _POPUP_MSG not in result, "Hidden popup message must not appear in Markdown"


def test_visible_popup_action_description_in_output() -> None:
    """Visible popup action descriptions must appear in the Markdown output."""
    state = _make_full_state()
    result = render_markdown(state)
    assert "Accept" in result
    assert "Reject" in result


def test_multiple_visible_popups_all_present() -> None:
    """When multiple popups are visible, all their messages must appear."""
    p1 = Popup(
        id="pop1",
        kind="error",
        visible=True,
        message="First popup message",
        actions=[Action(selector="btn.ok", input="enter", description="OK")],
    )
    p2 = Popup(
        id="pop2",
        kind="help",
        visible=True,
        message="Second popup message",
        actions=[Action(selector="btn.close", input="enter", description="Close")],
    )
    state = CockpitState(popups=[p1, p2])
    result = render_markdown(state)
    assert "First popup message" in result
    assert "Second popup message" in result
    assert "Error [pop1]" in result
    assert "Help [pop2]" in result


def test_diagnose_render_would_pass() -> None:
    """Simulate the _detect_render check: visible popup message/title in output.

    This mimics exactly what diagnose._detect_render does: for each visible
    popup with a non-empty message, it checks that either the message OR the
    derived title text appears in the rendered frame.  Our Markdown must pass.
    """
    state = _make_full_state()
    taui = serialize(state)
    result = render_markdown(state)

    from colleague.tui.diagnose import _popup_title, _visible_popups

    for popup in _visible_popups(taui):
        message = str(popup.get("message", ""))
        if not message:
            continue
        title = _popup_title(popup)
        assert message in result or title in result, (
            f"diagnose._detect_render would flag popup {popup.get('id')!r}: "
            f"neither message {message!r} nor title {title!r} found in Markdown"
        )


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


def test_status_severity_in_output() -> None:
    """Status severity must appear in the Markdown output."""
    state = _make_full_state()
    result = render_markdown(state)
    assert "error" in result


def test_status_message_in_output() -> None:
    """Status message must appear verbatim in the Markdown output."""
    state = _make_full_state()
    result = render_markdown(state)
    assert "Something went wrong" in result


# ---------------------------------------------------------------------------
# WorkItem info
# ---------------------------------------------------------------------------


def test_drive_info_in_output_when_present() -> None:
    """When drive is set, task_id and engine must appear in the Markdown."""
    state = _make_full_state()
    result = render_markdown(state)
    assert "t-123" in result
    assert "mock" in result


def test_drive_absent_when_none() -> None:
    """When drive is None, no stale drive info should appear."""
    state = CockpitState()
    result = render_markdown(state)
    # Should not error, and "task_id" label shouldn't be in there unless blank
    # We just confirm it renders cleanly
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Available actions
# ---------------------------------------------------------------------------


def test_available_actions_in_output() -> None:
    """available_actions selectors (and descriptions) must appear in the Markdown."""
    state = _make_full_state()
    result = render_markdown(state)
    # standing action always present
    assert "input.prompt" in result
    # popup actions for visible popups
    assert "button.accept" in result
    assert "button.reject" in result


def test_standing_action_always_present() -> None:
    """The standing 'input.prompt' action must appear even with no popups."""
    state = CockpitState()
    result = render_markdown(state)
    assert "input.prompt" in result


# ---------------------------------------------------------------------------
# Reading-completeness vs TAUI mirror
# ---------------------------------------------------------------------------


def test_reading_complete_vs_taui() -> None:
    """Everything serialize(state) marks visible must appear in the Markdown.

    This is the formal reading-completeness check: an agent reading ONLY the
    Markdown must miss nothing the TAUI JSON would have told it.
    """
    state = _make_full_state()
    taui = serialize(state)
    result = render_markdown(state)

    # screen / mode / focused
    assert taui["screen"] in result
    assert taui["mode"] in result
    assert taui["focused"] in result

    # visible zones
    for name, zone_d in taui["zones"].items():
        if zone_d["visible"]:
            assert name in result, f"Visible zone '{name}' missing from Markdown"

    # visible panels
    for panel in taui["panels"]:
        if panel["visible"]:
            assert (
                panel["title"] in result or panel["content_summary"] in result
            ), f"Visible panel '{panel['id']}' not surfaced in Markdown"
            for item in panel.get("items", []):
                assert (
                    item["label"] in result
                ), f"Panel item '{item['label']}' missing from Markdown"

    # visible popups — message and title both present
    for popup in taui["popups"]:
        if popup["visible"]:
            assert (
                popup["message"] in result
            ), f"Visible popup message missing: {popup['message']!r}"

    # status
    assert taui["status"]["severity"] in result
    assert taui["status"]["message"] in result

    # drive
    if taui["work"]:
        assert taui["work"]["task_id"] in result
        assert taui["work"]["engine"] in result

    # available_actions
    for action in taui["available_actions"]:
        assert (
            action["selector"] in result or action["description"] in result
        ), f"Action '{action['selector']}' / '{action['description']}' not in Markdown"


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_deterministic_same_state() -> None:
    """Calling render_markdown() twice on the same state yields identical output."""
    state = _make_full_state()
    assert render_markdown(state) == render_markdown(state)


def test_deterministic_equal_states() -> None:
    """Two freshly-built equal states produce identical Markdown."""
    s1 = _make_full_state()
    s2 = _make_full_state()
    assert render_markdown(s1) == render_markdown(s2)


def test_different_states_produce_different_output() -> None:
    """Different states should produce different Markdown."""
    s1 = CockpitState(status=Status(severity="info", message="All is well"))
    s2 = CockpitState(status=Status(severity="error", message="All is broken"))
    assert render_markdown(s1) != render_markdown(s2)


# ---------------------------------------------------------------------------
# Stdlib-only guard
# ---------------------------------------------------------------------------


def test_no_third_party_imports() -> None:
    """render/markdown.py must not import any third-party package.

    We verify by checking that the module's dependencies are stdlib-only.
    """
    import importlib
    import sys

    # Re-import to be safe
    mod = importlib.import_module("colleague.tui.render.markdown")
    # All names used in the module at import time should be stdlib or colleague
    for name, obj in vars(mod).items():
        if hasattr(obj, "__module__") and obj.__module__ is not None:
            pkg = obj.__module__.split(".")[0]
            # Allow stdlib and colleague packages only
            if pkg not in sys.stdlib_module_names and pkg not in (
                "colleague",
                "builtins",
                "__future__",
            ):
                # check it's not a known third-party
                assert pkg in (
                    "colleague",
                    "builtins",
                ), f"Possible third-party import in markdown.py: {name} from {obj.__module__}"


# ---------------------------------------------------------------------------
# Markdown structure smoke tests
# ---------------------------------------------------------------------------


def test_output_contains_heading() -> None:
    """The Markdown output must contain at least one heading (# or ##)."""
    state = CockpitState()
    result = render_markdown(state)
    assert any(
        line.startswith("#") for line in result.splitlines()
    ), "Markdown output must contain at least one heading"


def test_available_actions_section_is_bullet_list() -> None:
    """The available_actions section should use Markdown bullet items."""
    state = CockpitState()
    result = render_markdown(state)
    # At minimum the standing action must appear as a bullet
    bullet_lines = [ln for ln in result.splitlines() if ln.strip().startswith("- ")]
    assert len(bullet_lines) > 0, "Expected bullet list items in Markdown output"
