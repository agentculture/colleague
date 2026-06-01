"""Tests for convertible.tui.diagnose — pure cross-mirror differ.

These tests prove the headline honesty condition (h6): a captured snapshot
triple (TAUI mirror + ANSI frame + event trail) can be classified into bug
classes WITHOUT any LLM/model/network call.  The differ is pure stdlib
comparison only.
"""

from __future__ import annotations

import inspect

from convertible.tui.diagnose import (
    BugClass,
    Diagnosis,
    Finding,
    diagnose,
    diagnose_snapshot,
)
from convertible.tui.events import Dismiss, SkillSuggested
from convertible.tui.reducer import reduce
from convertible.tui.render.ansi import render
from convertible.tui.snapshot import write_snapshot
from convertible.tui.state import (
    Action,
    Background,
    CockpitState,
    Panel,
    Popup,
    Zone,
)
from convertible.tui.taui import serialize

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _skill_state() -> CockpitState:
    """A correct state with a visible skill-suggestion popup."""
    return reduce(CockpitState(), SkillSuggested("boost"))


# ---------------------------------------------------------------------------
# Criterion 1 — the headline RENDER case (honesty h6)
# ---------------------------------------------------------------------------


class TestHeadlineRenderCase:
    def test_render_finding_for_invisible_popup_text(self):
        state = _skill_state()
        taui = serialize(state)  # correct mirror
        # A broken frame that LACKS the popup message entirely.
        broken_ansi = "empty frame"

        diag = diagnose(taui, broken_ansi, events=[SkillSuggested("boost")])

        # A RENDER finding for the popup must be present.
        render_findings = [f for f in diag.findings if f.bug_class == BugClass.RENDER]
        assert render_findings, "expected a RENDER finding"
        assert any(f.selector == "popup.skill.boost" for f in render_findings)

    def test_headline_does_not_trip_state_or_layout(self):
        state = _skill_state()
        taui = serialize(state)
        broken_ansi = "empty frame"

        diag = diagnose(taui, broken_ansi, events=[SkillSuggested("boost")])

        # The taui is CORRECT (matches replay) and the zone is fine, so neither
        # STATE nor LAYOUT may fire for this case.
        assert BugClass.STATE not in diag.classes
        assert BugClass.LAYOUT not in diag.classes

    def test_consistent_triple_has_no_render_finding(self):
        """Sanity: the same popup with a correct frame yields no RENDER."""
        state = _skill_state()
        taui = serialize(state)
        good_ansi = render(state)

        diag = diagnose(taui, good_ansi, events=[SkillSuggested("boost")])
        assert BugClass.RENDER not in diag.classes


# ---------------------------------------------------------------------------
# Criterion 2 — every one of the 7 bug classes is reachable
# ---------------------------------------------------------------------------


class TestSevenClassesReachable:
    def test_state_bug(self):
        """Event fired but the captured mirror never updated."""
        # The event SAYS a popup opened, but the captured taui is empty.
        empty = serialize(CockpitState())
        diag = diagnose(empty, "empty frame", events=[SkillSuggested("boost")])
        assert BugClass.STATE in diag.classes

    def test_render_bug(self):
        state = _skill_state()
        taui = serialize(state)
        diag = diagnose(taui, "empty frame", events=[SkillSuggested("boost")])
        assert BugClass.RENDER in diag.classes

    def test_layout_bug(self):
        """A visible node lives in a zone that is visible=false.

        The node↔zone mapping is by id prefix: a node id ``left.skills.list``
        belongs to zone ``left.skills``.  When the owning zone is hidden but the
        node claims to be visible, that is a layout contradiction.
        """
        panel_state = CockpitState(
            zones={"left.skills": Zone(visible=False)},
            panels=[
                Panel(
                    id="left.skills.list",
                    title="Skills",
                    visible=True,
                    content_summary="3 skills",
                )
            ],
        )
        ptaui = serialize(panel_state)
        ansi = render(panel_state)
        diag = diagnose(ptaui, ansi)
        assert BugClass.LAYOUT in diag.classes
        assert any(
            f.selector == "left.skills.list"
            for f in diag.findings
            if f.bug_class == BugClass.LAYOUT
        )

    def test_focus_bug(self):
        """focused names a selector that does not resolve in the tree."""
        state = CockpitState(focused="panel.does.not.exist")
        taui = serialize(state)
        diag = diagnose(taui, render(state))
        assert BugClass.FOCUS in diag.classes

    def test_input_routing_bug(self):
        """An available_action selector that does not resolve / cannot route."""
        taui = serialize(CockpitState())
        # Inject a bogus action that resolves to nothing.
        taui["available_actions"].append(
            {
                "selector": "popup.ghost.accept",
                "input": "enter",
                "description": "Ghost action",
            }
        )
        diag = diagnose(taui, "frame")
        assert BugClass.INPUT_ROUTING in diag.classes

    def test_theme_bug(self):
        """semantic implies a suggested theme but theme contradicts it."""
        state = CockpitState(
            background=Background(
                theme="default",
                semantic="stronger_agent_recommended",
            )
        )
        taui = serialize(state)
        diag = diagnose(taui, render(state))
        assert BugClass.THEME in diag.classes

    def test_popup_lifecycle_empty_actions(self):
        """A visible popup with NO actions is a lifecycle bug."""
        state = CockpitState(
            popups=[
                Popup(
                    id="popup.stuck",
                    kind="error",
                    visible=True,
                    message="No way out",
                    actions=[],
                )
            ]
        )
        taui = serialize(state)
        diag = diagnose(taui, render(state))
        assert BugClass.POPUP_LIFECYCLE in diag.classes

    def test_popup_lifecycle_dismissed_but_visible(self):
        """A Dismiss event for a popup that is still visible (stuck-open)."""
        state = CockpitState(
            popups=[
                Popup(
                    id="popup.skill.boost",
                    kind="skill_suggestion",
                    visible=True,
                    message="Stronger agent recommended (boost)",
                    actions=[
                        Action("popup.skill.boost.ok", "enter", "OK"),
                    ],
                )
            ]
        )
        taui = serialize(state)
        diag = diagnose(
            taui,
            render(state),
            events=[Dismiss(target="popup.skill.boost")],
        )
        assert BugClass.POPUP_LIFECYCLE in diag.classes


# ---------------------------------------------------------------------------
# Criterion 3 — no LLM/network, and a clean consistent triple
# ---------------------------------------------------------------------------


class TestPurity:
    def test_module_source_imports_no_network_or_model_libs(self):
        import convertible.tui.diagnose as mod

        src = inspect.getsource(mod)
        forbidden = (
            "urllib",
            "http",
            "socket",
            "requests",
            "httpx",
            "openai",
            "subprocess",
        )
        for name in forbidden:
            assert (
                f"import {name}" not in src and f"from {name}" not in src
            ), f"diagnose.py must not import {name!r}"

    def test_clean_triple_end_to_end_has_no_findings(self):
        """events -> replay/reduce -> diagnose end-to-end, no TTY, no network.

        A CONSISTENT triple (taui + matching ansi + matching events) must yield
        a clean, no-findings diagnosis.
        """
        events = [SkillSuggested("boost")]
        # Build state by reducing the SAME events (the consistent path).
        state = CockpitState()
        for ev in events:
            state = reduce(state, ev)

        taui = serialize(state)
        ansi = render(state)

        diag = diagnose(taui, ansi, events=events)
        assert diag.findings == [], f"expected clean diagnosis, got {diag.classes}"
        assert diag.classes == set()

    def test_fresh_default_state_is_clean(self):
        """A bare default CockpitState is healthy from every angle."""
        state = CockpitState()
        diag = diagnose(serialize(state), render(state), events=[])
        assert diag.findings == []


# ---------------------------------------------------------------------------
# diagnose_snapshot + dataclass surface
# ---------------------------------------------------------------------------


class TestDiagnoseSnapshot:
    def test_diagnose_snapshot_reads_triple(self, tmp_path):
        state = _skill_state()
        events = [SkillSuggested("boost")]
        write_snapshot(tmp_path, "bug-x", state, events)

        diag = diagnose_snapshot(tmp_path, "bug-x")
        # A faithfully-written snapshot is consistent -> clean.
        assert isinstance(diag, Diagnosis)
        assert diag.findings == []

    def test_to_dict_shape(self):
        diag = diagnose(serialize(_skill_state()), "empty frame")
        d = diag.to_dict()
        assert "findings" in d and "classes" in d
        assert isinstance(d["findings"], list)
        assert isinstance(d["classes"], list)
        for f in d["findings"]:
            assert set(f.keys()) == {"bug_class", "selector", "message"}

    def test_finding_is_a_dataclass(self):
        f = Finding(bug_class=BugClass.RENDER, selector="x", message="m")
        assert f.bug_class == "render"
        assert f.selector == "x"
        assert f.message == "m"

    def test_diagnose_without_events_skips_state(self):
        """events=None must not raise and must not run the STATE detector."""
        empty = serialize(CockpitState())
        diag = diagnose(empty, "empty frame", events=None)
        assert BugClass.STATE not in diag.classes
