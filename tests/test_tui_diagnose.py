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
from convertible.tui.render.markdown import render_markdown
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


# ---------------------------------------------------------------------------
# t3 — generalize the RENDER faithfulness check to the Markdown frame
# ---------------------------------------------------------------------------


class TestMarkdownNoAnsiRegression:
    """The new Markdown parameter must NOT change any existing ANSI behavior."""

    def test_markdown_none_matches_no_markdown_arg(self):
        """diagnose(taui, ansi, events) == diagnose(taui, ansi, events, markdown=None)."""
        state = _skill_state()
        taui = serialize(state)
        ansi = "empty frame"  # broken frame -> RENDER fires on the ANSI side
        events = [SkillSuggested("boost")]

        no_md = diagnose(taui, ansi, events)
        md_none = diagnose(taui, ansi, events, markdown=None)

        assert no_md.to_dict() == md_none.to_dict()

    def test_empty_markdown_is_a_no_op(self):
        """An empty-string markdown (the legacy-triple default) adds no findings."""
        state = _skill_state()
        taui = serialize(state)
        ansi = "empty frame"
        events = [SkillSuggested("boost")]

        md_none = diagnose(taui, ansi, events, markdown=None)
        md_empty = diagnose(taui, ansi, events, markdown="")

        assert md_none.to_dict() == md_empty.to_dict()
        # And no RENDER finding may name the MARKDOWN frame (it was skipped).
        for f in md_empty.findings:
            assert "MARKDOWN" not in f.message

    def test_empty_markdown_keeps_clean_triple_clean(self):
        """A faithful triple with empty markdown stays clean (no spurious finding)."""
        events = [SkillSuggested("boost")]
        state = CockpitState()
        for ev in events:
            state = reduce(state, ev)
        taui = serialize(state)
        ansi = render(state)

        diag = diagnose(taui, ansi, events=events, markdown="")
        assert diag.findings == []


class TestMarkdownRoundTrip:
    """A faithful Markdown frame yields ZERO findings."""

    def test_faithful_markdown_has_no_findings(self):
        events = [SkillSuggested("boost")]
        state = CockpitState()
        for ev in events:
            state = reduce(state, ev)

        taui = serialize(state)
        ansi = render(state)
        markdown = render_markdown(state)

        diag = diagnose(taui, ansi, events=events, markdown=markdown)
        assert diag.findings == [], f"expected clean diagnosis, got {diag.classes}"
        assert diag.classes == set()

    def test_faithful_markdown_no_render_finding(self):
        """A correct Markdown frame must not produce ANY RENDER finding."""
        state = _skill_state()
        taui = serialize(state)
        ansi = render(state)
        markdown = render_markdown(state)

        diag = diagnose(taui, ansi, events=[SkillSuggested("boost")], markdown=markdown)
        assert BugClass.RENDER not in diag.classes


class TestMarkdownMutation:
    """Drift between the mirror and the Markdown frame is a RENDER finding."""

    def test_removing_popup_message_from_markdown_yields_render(self):
        state = _skill_state()
        taui = serialize(state)
        ansi = render(state)  # ANSI stays faithful
        markdown = render_markdown(state)

        # Identify the visible popup and the message text the faithful render
        # emitted verbatim.
        popup = next(p for p in taui["popups"] if p.get("visible"))
        message = popup["message"]
        title = f"Skill Suggestion [{popup['id']}]"
        assert message in markdown  # sanity: faithful render had it

        # Mutate: strip BOTH the message and the derived title so the popup is
        # no longer discoverable in the Markdown frame.
        broken_md = markdown.replace(message, "").replace(title, "")

        diag = diagnose(taui, ansi, events=[SkillSuggested("boost")], markdown=broken_md)

        render_findings = [f for f in diag.findings if f.bug_class == BugClass.RENDER]
        assert render_findings, "expected a RENDER finding for the dropped popup"
        # The finding must name THIS popup and indicate the MARKDOWN frame.
        offenders = [f for f in render_findings if f.selector == popup["id"]]
        assert offenders, "RENDER finding must point at the dropped popup"
        assert any(
            "MARKDOWN" in f.message for f in offenders
        ), "the Markdown RENDER finding must name the MARKDOWN frame"

    def test_ansi_stays_faithful_so_only_markdown_render_fires(self):
        """When only the Markdown drifts, the RENDER finding names MARKDOWN, not ANSI."""
        state = _skill_state()
        taui = serialize(state)
        ansi = render(state)  # faithful -> ANSI detector stays silent
        markdown = render_markdown(state)
        popup = next(p for p in taui["popups"] if p.get("visible"))
        message = popup["message"]
        title = f"Skill Suggestion [{popup['id']}]"
        broken_md = markdown.replace(message, "").replace(title, "")

        diag = diagnose(taui, ansi, events=[SkillSuggested("boost")], markdown=broken_md)

        render_findings = [f for f in diag.findings if f.bug_class == BugClass.RENDER]
        assert render_findings
        # Every RENDER finding here is from the MARKDOWN side (ANSI is faithful).
        for f in render_findings:
            assert "MARKDOWN" in f.message
            assert "ANSI" not in f.message


class TestMarkdownIff:
    """IFF property: findings iff the Markdown disagrees with the mirror."""

    def test_iff_faithful_is_empty_and_drift_is_nonempty(self):
        state = _skill_state()
        taui = serialize(state)
        ansi = render(state)
        events = [SkillSuggested("boost")]

        faithful_md = render_markdown(state)
        faithful = diagnose(taui, ansi, events=events, markdown=faithful_md)
        md_render = [
            f
            for f in faithful.findings
            if f.bug_class == BugClass.RENDER and "MARKDOWN" in f.message
        ]
        assert md_render == [], "faithful Markdown must yield NO markdown RENDER finding"

        popup = next(p for p in taui["popups"] if p.get("visible"))
        message = popup["message"]
        title = f"Skill Suggestion [{popup['id']}]"
        broken_md = faithful_md.replace(message, "").replace(title, "")
        drift = diagnose(taui, ansi, events=events, markdown=broken_md)
        md_render_drift = [
            f for f in drift.findings if f.bug_class == BugClass.RENDER and "MARKDOWN" in f.message
        ]
        assert md_render_drift, "drifting Markdown must yield a markdown RENDER finding"


class TestDiagnoseSnapshotQuad:
    """diagnose_snapshot forwards the snapshot's markdown (quad-aware)."""

    def test_faithful_quad_is_clean(self, tmp_path):
        state = _skill_state()
        events = [SkillSuggested("boost")]
        write_snapshot(tmp_path, "quad-x", state, events)

        diag = diagnose_snapshot(tmp_path, "quad-x")
        assert isinstance(diag, Diagnosis)
        assert diag.findings == [], f"faithful quad should be clean, got {diag.classes}"

    def test_legacy_triple_has_no_markdown_findings(self, tmp_path):
        """A legacy triple (no .md) diagnoses exactly as before — no markdown findings."""
        import json

        from convertible.tui.events import dumps_events

        state = _skill_state()
        events = [SkillSuggested("boost")]
        out = tmp_path
        out.mkdir(parents=True, exist_ok=True)
        (out / "legacy.taui.json").write_text(
            json.dumps(serialize(state), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        (out / "legacy.ansi").write_text(render(state), encoding="utf-8")
        (out / "legacy.events.jsonl").write_text(dumps_events(events), encoding="utf-8")
        # NO .md file -> snapshot.markdown == "" -> markdown detector skipped.

        diag = diagnose_snapshot(out, "legacy")
        # Faithful ANSI -> clean; and no finding may name the MARKDOWN frame.
        assert diag.findings == []
        for f in diag.findings:
            assert "MARKDOWN" not in f.message

    def test_quad_with_broken_markdown_file_yields_markdown_render(self, tmp_path):
        """Hand-corrupt the .md file -> diagnose_snapshot surfaces a markdown RENDER."""
        state = _skill_state()
        events = [SkillSuggested("boost")]
        write_snapshot(tmp_path, "broken-md", state, events)

        taui = serialize(state)
        popup = next(p for p in taui["popups"] if p.get("visible"))
        message = popup["message"]
        title = f"Skill Suggestion [{popup['id']}]"
        md_path = tmp_path / "broken-md.md"
        corrupted = md_path.read_text(encoding="utf-8").replace(message, "").replace(title, "")
        md_path.write_text(corrupted, encoding="utf-8")

        diag = diagnose_snapshot(tmp_path, "broken-md")
        md_render = [
            f for f in diag.findings if f.bug_class == BugClass.RENDER and "MARKDOWN" in f.message
        ]
        assert md_render, "a corrupted .md frame must surface a markdown RENDER finding"
