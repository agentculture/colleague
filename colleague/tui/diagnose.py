"""Colleague TUI — pure cross-mirror differ (the ``diagnose`` engine).

This is the module that makes the TUI **agent-debuggable**.  Given a captured
snapshot triple — the TAUI semantic mirror, the rendered ANSI frame, and the
event trail — :func:`diagnose` classifies disagreements between the three views
into one of seven **bug classes**, WITHOUT any LLM, model, or network call.

The whole module is a pure, stdlib-only comparison.  It imports only
``dataclasses`` / ``typing`` and its sibling ``colleague.tui`` modules.  It
opens no socket, spawns no subprocess, and reads nothing from the network —
honesty condition h6: the disagreement is *derivable* from the captured state
alone.

The seven bug classes
----------------------
``STATE``
    An event occurred but the mirror never updated.  Replaying the event trail
    yields an EXPECTED mirror whose popups disagree with the captured mirror
    (e.g. a ``SkillSuggested`` fired but the captured taui has no/invisible
    popup for it).
``RENDER``
    The mirror is correct but a rendered frame is wrong/missing — a popup with
    ``visible=true`` whose (non-empty) ``message`` text is ABSENT from the
    captured frame.  Checked against the ANSI frame always, and — when a
    Markdown frame is supplied (the snapshot quad) — against the Markdown frame
    too.  Markdown and JSON are both pure functions of one ``CockpitState``, so a
    Markdown disagreement is a render-fidelity bug, never a data-source
    divergence.  The Markdown check runs only when a non-empty Markdown frame is
    present; an absent/empty frame (the legacy triple) is skipped entirely.
``LAYOUT``
    A node exists & is marked visible, but its owning zone (matched by id
    prefix) is ``visible=false`` — the node can never actually paint.
``FOCUS``
    ``taui.focused`` names a selector that does not resolve in the tree.
``INPUT_ROUTING``
    An ``available_actions`` entry whose ``selector`` does not resolve to any
    node in the tree — the action is advertised but addresses nothing. (Whether
    an action is *operable headlessly* is a v0 scope choice, not a routing bug.)
``THEME``
    ``background.semantic`` implies a "stronger agent" theme but
    ``background.theme`` contradicts it (semantic mode and visual theme
    disagree).
``POPUP_LIFECYCLE``
    A visible popup with EMPTY ``actions``; OR a blocking popup with no actions;
    OR a popup the event trail dismissed (a ``Dismiss(target=id)`` event is
    present) that nonetheless remains ``visible=true`` (stuck-open).

Public API
----------
- :class:`BugClass` — the seven string constants.
- :class:`Finding` — one classified disagreement.
- :class:`Diagnosis` — the collected findings (+ ``classes`` / ``to_dict``).
- :func:`diagnose` — run every detector over ``(taui, ansi, events, markdown)``.
- :func:`diagnose_snapshot` — read a snapshot quad and diagnose it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional

from colleague.tui.replay import replay
from colleague.tui.selectors import SelectorError, resolve
from colleague.tui.taui import serialize

#: Standing selectors that are addressable by design but do not drill through
#: :func:`colleague.tui.selectors.resolve` (they have no node in the tree).
#: Kept in sync with the standing entries added by
#: :func:`colleague.tui.selectors.selectors`.
_STANDING_SELECTORS = frozenset({"input.prompt", "status", "background"})

# ---------------------------------------------------------------------------
# Bug-class constants
# ---------------------------------------------------------------------------


class BugClass:
    """The seven cross-mirror bug classes, as plain string constants.

    Using a class of ``str`` constants (rather than an ``Enum``) keeps every
    ``Finding.bug_class`` value a plain ``str`` — JSON-serialisable with no
    coercion and directly comparable to the literal class names a caller might
    pass.
    """

    STATE = "state"
    RENDER = "render"
    LAYOUT = "layout"
    FOCUS = "focus"
    INPUT_ROUTING = "input_routing"
    THEME = "theme"
    POPUP_LIFECYCLE = "popup_lifecycle"


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class Finding:
    """One classified disagreement between the mirror, the frame, or the trail.

    Fields
    ------
    bug_class:
        One of the :class:`BugClass` constants (a plain ``str``).
    selector:
        The offending node's selector / id, or ``""`` when no single node owns
        the disagreement (e.g. a theme contradiction).
    message:
        A human- and agent-readable explanation in the style
        ``"TAUI says popup visible=true; ANSI lacks title 'X' -> likely render bug"``.
    """

    bug_class: str
    selector: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "bug_class": self.bug_class,
            "selector": self.selector,
            "message": self.message,
        }


@dataclass
class Diagnosis:
    """The collected findings from running every detector over a triple."""

    findings: List[Finding] = field(default_factory=list)

    @property
    def classes(self) -> set[str]:
        """The set of distinct ``bug_class`` values present in ``findings``."""
        return {f.bug_class for f in self.findings}

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable view of the diagnosis."""
        return {
            "findings": [f.to_dict() for f in self.findings],
            "classes": sorted(self.classes),
        }


# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------


def _visible_popups(taui: dict[str, Any]) -> List[dict[str, Any]]:
    """Return the list of popup dicts whose ``visible`` flag is truthy."""
    return [p for p in taui.get("popups", []) if p.get("visible")]


def _popup_title(popup: dict[str, Any]) -> str:
    """Mirror the title the popup_layer widget paints: ``Kind [id]``.

    Kept in sync with :mod:`colleague.tui.widgets.popup_layer`: the widget
    titles a popup ``"<Kind Label> [<id>]"``.  We derive the same label so a
    RENDER check can look for the title (not just the message) in the frame.
    """
    kind = str(popup.get("kind", ""))
    label = {
        "skill_suggestion": "Skill Suggestion",
        "confirmation": "Confirmation",
        "error": "Error",
        "progress": "Progress",
        "diff": "Diff",
        "help": "Help",
    }.get(kind, kind.replace("_", " ").title())
    return f"{label} [{popup.get('id', '')}]"


def _zone_keys(taui: dict[str, Any]) -> List[str]:
    """Return zone keys longest-first (so the most specific prefix wins)."""
    return sorted(taui.get("zones", {}).keys(), key=len, reverse=True)


def _owning_zone(node_id: str, zone_keys: List[str]) -> Optional[str]:
    """Return the zone key whose dotted prefix owns ``node_id``, else ``None``.

    A node ``"left.skills.list"`` is owned by zone ``"left.skills"`` (the zone
    key followed by a ``"."``).  An exact match (``node_id == zone_key``) also
    counts.  ``zone_keys`` must be longest-first so the most specific zone wins.
    """
    for key in zone_keys:
        if node_id == key or node_id.startswith(key + "."):
            return key
    return None


# ---------------------------------------------------------------------------
# Detectors — each is a pure function returning a list of Finding
# ---------------------------------------------------------------------------


def _detect_state(taui: dict[str, Any], events: Optional[list]) -> List[Finding]:
    """STATE: replay the trail and compare popup ``(id, visible)`` + focus.

    Only the popups' ``(id, visible)`` and the ``focused`` selector are compared
    — never the whole dict, because frame counters and other ambient fields
    legitimately differ.  A finding fires when the replayed (expected) mirror
    has a popup visible that the captured mirror lacks or has hidden, or when
    the focused selector disagrees.
    """
    if events is None:
        return []

    findings: List[Finding] = []
    try:
        expected = serialize(replay(list(events)))
    except Exception:  # pragma: no cover - replay over odd events
        return []

    captured_vis = {p.get("id"): bool(p.get("visible")) for p in taui.get("popups", [])}
    for ep in expected.get("popups", []):
        if not ep.get("visible"):
            continue
        pid = ep.get("id")
        if not captured_vis.get(pid, False):
            findings.append(
                Finding(
                    bug_class=BugClass.STATE,
                    selector=str(pid),
                    message=(
                        f"Replaying events expects popup {pid!r} visible=true, "
                        "but the captured TAUI has it missing/hidden -> the "
                        "mirror did not update for the event -> likely state bug"
                    ),
                )
            )

    exp_focus = expected.get("focused")
    cap_focus = taui.get("focused")
    if exp_focus and exp_focus != cap_focus:
        findings.append(
            Finding(
                bug_class=BugClass.STATE,
                selector=str(cap_focus or ""),
                message=(
                    f"Replaying events expects focus {exp_focus!r}, but the "
                    f"captured TAUI focus is {cap_focus!r} -> likely state bug"
                ),
            )
        )
    return findings


def _detect_render(taui: dict[str, Any], ansi: str) -> List[Finding]:
    """RENDER: a visible popup whose non-empty message is absent from the frame."""
    findings: List[Finding] = []
    for popup in _visible_popups(taui):
        message = str(popup.get("message", ""))
        if not message:
            continue
        title = _popup_title(popup)
        # The mirror says this popup is visible; if neither its message nor its
        # derived title text appears in the captured frame, the renderer dropped
        # it -> render bug.
        if message not in ansi and title not in ansi:
            findings.append(
                Finding(
                    bug_class=BugClass.RENDER,
                    selector=str(popup.get("id", "")),
                    message=(
                        f"TAUI says popup {popup.get('id')!r} visible=true; "
                        f"ANSI lacks message {message!r} -> likely render bug"
                    ),
                )
            )
    return findings


def _detect_render_markdown(taui: dict[str, Any], markdown: str) -> List[Finding]:
    """RENDER (Markdown frame): a visible popup absent from the Markdown render.

    Mirrors :func:`_detect_render` faithfully — same ``_visible_popups`` and
    ``_popup_title`` helpers, so it stays in lock-step with how the renderer
    titles popups — but checks the Markdown string instead of the ANSI frame and
    names the **MARKDOWN** frame in its message.  Markdown and JSON are both pure
    functions of one ``CockpitState``, so any disagreement here is a
    render-fidelity bug, never a data-source divergence.

    The caller (:func:`diagnose`) only invokes this when ``markdown`` is a
    non-empty string, so a legacy triple (no ``.md``, ``markdown == ""``) is
    never checked and behaves exactly as before.

    Unlike the ANSI :func:`_detect_render` (which treats a popup as rendered
    when *either* its title or its message survives — it only guards against a
    popup vanishing entirely), the Markdown check requires the popup's
    **message** itself, because Markdown is the agent-facing *reading-complete*
    view: dropping the message while keeping the title is a fidelity loss the
    agent would feel, so it must be flagged (matching this finding's own
    "MARKDOWN lacks message" wording).
    """
    findings: List[Finding] = []
    for popup in _visible_popups(taui):
        message = str(popup.get("message", ""))
        if not message:
            continue
        # The mirror says this popup is visible with a non-empty message; if that
        # message text is absent from the Markdown frame, the agent-facing render
        # dropped visible content -> render bug.
        if message not in markdown:
            findings.append(
                Finding(
                    bug_class=BugClass.RENDER,
                    selector=str(popup.get("id", "")),
                    message=(
                        f"TAUI says popup {popup.get('id')!r} visible=true; "
                        f"MARKDOWN lacks message {message!r} -> likely render bug"
                    ),
                )
            )
    return findings


def _detect_layout(taui: dict[str, Any]) -> List[Finding]:
    """LAYOUT: a visible node whose owning zone is visible=false.

    Node↔zone ownership is by id prefix (``left.skills.list`` → ``left.skills``).
    A panel marked ``visible=true`` inside a zone marked ``visible=false`` can
    never paint — the mirror contradicts its own layout.
    """
    findings: List[Finding] = []
    zones = taui.get("zones", {})
    zone_keys = _zone_keys(taui)

    def _check(node_id: str, node_visible: bool, kind: str) -> None:
        if not node_visible:
            return
        zone_key = _owning_zone(node_id, zone_keys)
        if zone_key is None:
            return
        if not bool(zones.get(zone_key, {}).get("visible", True)):
            findings.append(
                Finding(
                    bug_class=BugClass.LAYOUT,
                    selector=node_id,
                    message=(
                        f"{kind} {node_id!r} is visible=true but its owning "
                        f"zone {zone_key!r} is visible=false -> it cannot "
                        "paint -> likely layout bug"
                    ),
                )
            )

    for panel in taui.get("panels", []):
        _check(str(panel.get("id", "")), bool(panel.get("visible")), "Panel")
    return findings


def _is_addressable(taui: dict[str, Any], selector: str) -> bool:
    """True if *selector* names a real node in the TAUI tree.

    Addressable means the selector resolves against the tree's *structure*
    (popups/panels/zones, or a top-level dotted path) via
    :func:`colleague.tui.selectors.resolve`, or it is one of the standing
    selectors that are addressable by design (``input.prompt`` /
    ``status`` / ``background``) but carry no node to drill into.

    We deliberately do NOT consult
    :func:`colleague.tui.selectors.selectors`: that function harvests
    selectors out of ``available_actions`` itself, so a bogus action would
    appear "addressable" purely because it was offered — which is exactly the
    INPUT_ROUTING bug we want to catch.
    """
    if selector in _STANDING_SELECTORS:
        return True
    try:
        resolve(taui, selector)
        return True
    except SelectorError:
        return False


def _detect_focus(taui: dict[str, Any]) -> List[Finding]:
    """FOCUS: ``taui.focused`` names a selector that does not resolve."""
    focused = taui.get("focused")
    if not focused:
        return []
    if _is_addressable(taui, str(focused)):
        return []
    return [
        Finding(
            bug_class=BugClass.FOCUS,
            selector=str(focused),
            message=(
                f"TAUI focus {focused!r} does not resolve to any node in "
                "the tree -> focus points at nothing -> likely focus bug"
            ),
        )
    ]


def _detect_input_routing(taui: dict[str, Any]) -> List[Finding]:
    """INPUT_ROUTING: an available action that does not resolve or cannot route."""
    findings: List[Finding] = []
    for action in taui.get("available_actions", []):
        selector = str(action.get("selector", ""))
        if not selector:
            continue
        if not _is_addressable(taui, selector):
            findings.append(
                Finding(
                    bug_class=BugClass.INPUT_ROUTING,
                    selector=selector,
                    message=(
                        f"available_actions offers {selector!r} but it does not "
                        "resolve to any node -> the action cannot route -> "
                        "likely input-routing bug"
                    ),
                )
            )
    return findings


def _detect_theme(taui: dict[str, Any]) -> List[Finding]:
    """THEME: semantic implies a suggested theme but the theme disagrees."""
    bg = taui.get("background", {})
    semantic = str(bg.get("semantic", ""))
    theme = str(bg.get("theme", ""))
    if semantic == "stronger_agent_recommended" and not theme.endswith("-suggested"):
        return [
            Finding(
                bug_class=BugClass.THEME,
                selector="background",
                message=(
                    f"background.semantic is {semantic!r} (implies a "
                    f"'-suggested' theme) but background.theme is {theme!r} -> "
                    "semantic mode and visual theme disagree -> likely theme bug"
                ),
            )
        ]
    return []


def _detect_popup_lifecycle(taui: dict[str, Any], events: Optional[list]) -> List[Finding]:
    """POPUP_LIFECYCLE: empty-action popups, blocking-no-action, or stuck-open."""
    findings: List[Finding] = []

    dismissed: set[str] = set()
    for ev in events or []:
        # Match a Dismiss event without importing the event class: a Dismiss
        # carries a ``target`` attribute naming the popup id.  Guard on type
        # name so an unrelated object that happens to carry ``target`` is
        # ignored.
        if type(ev).__name__ == "Dismiss":
            tgt = getattr(ev, "target", "")
            if tgt:
                dismissed.add(str(tgt))

    for popup in _visible_popups(taui):
        pid = str(popup.get("id", ""))
        actions = popup.get("actions", [])
        if not actions:
            blocking = bool(popup.get("blocking"))
            reason = "blocking with no actions" if blocking else "no actions"
            findings.append(
                Finding(
                    bug_class=BugClass.POPUP_LIFECYCLE,
                    selector=pid,
                    message=(
                        f"Popup {pid!r} is visible=true but has {reason} -> "
                        "the user/agent cannot escape it -> likely "
                        "popup-lifecycle bug"
                    ),
                )
            )
        if pid in dismissed:
            findings.append(
                Finding(
                    bug_class=BugClass.POPUP_LIFECYCLE,
                    selector=pid,
                    message=(
                        f"A Dismiss(target={pid!r}) event was recorded but the "
                        "captured TAUI still has the popup visible=true "
                        "(stuck-open) -> likely popup-lifecycle bug"
                    ),
                )
            )
    return findings


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def diagnose(
    taui: dict[str, Any],
    ansi: str,
    events: Optional[list] = None,
    markdown: Optional[str] = None,
) -> Diagnosis:
    """Run every detector over a captured frame set and collect the findings.

    Parameters
    ----------
    taui:
        The captured TAUI mirror dict (output of
        :func:`colleague.tui.taui.serialize`).
    ansi:
        The captured ANSI frame string (output of
        :func:`colleague.tui.render.ansi.render`).
    events:
        The captured event trail.  When ``None`` the STATE detector (which needs
        the trail to compute the expected mirror) is skipped; every other
        detector still runs.
    markdown:
        The captured Markdown frame string (output of
        :func:`colleague.tui.render.markdown.render_markdown`).  When ``None``
        or empty — the legacy-triple default — the Markdown RENDER detector is
        skipped entirely, so behavior is byte-identical to the pre-quad differ.
        When a non-empty frame is supplied, the same RENDER faithfulness check
        the ANSI frame gets is applied to the Markdown frame too.

    Returns
    -------
    Diagnosis
        The collected :class:`Finding` objects (empty when the frames agree).
    """
    findings: List[Finding] = []
    findings.extend(_detect_state(taui, events))
    findings.extend(_detect_render(taui, ansi))
    # The Markdown RENDER check is additive and runs ONLY when a Markdown frame
    # is actually present.  A legacy triple (markdown None/"") skips it, so the
    # ANSI path is preserved exactly.
    if markdown:
        findings.extend(_detect_render_markdown(taui, markdown))
    findings.extend(_detect_layout(taui))
    findings.extend(_detect_focus(taui))
    findings.extend(_detect_input_routing(taui))
    findings.extend(_detect_theme(taui))
    findings.extend(_detect_popup_lifecycle(taui, events))
    return Diagnosis(findings=findings)


def diagnose_snapshot(directory: "str | Any", name: str) -> Diagnosis:
    """Read the snapshot quad ``<name>`` from *directory* and diagnose it.

    Convenience wrapper that loads the captured ``taui`` / ``ansi`` / ``events`` /
    ``markdown`` via :func:`colleague.tui.snapshot.read_snapshot` and forwards
    them to :func:`diagnose`.

    Because :func:`diagnose` skips the Markdown RENDER check when the frame is
    empty, a legacy triple (no ``.md`` → ``snap.markdown == ""``) keeps its exact
    current behavior; a quad gets the extra Markdown faithfulness check for free.

    Parameters
    ----------
    directory:
        The directory containing the snapshot files.
    name:
        The base name used when the snapshot was written.

    Returns
    -------
    Diagnosis
        The diagnosis of the read frame set.
    """
    # Imported lazily so the core differ has zero dependency on the filesystem
    # snapshot layer (and to keep the import graph shallow).
    from colleague.tui.snapshot import read_snapshot

    snap = read_snapshot(directory, name)
    return diagnose(snap.taui, snap.ansi, snap.events, markdown=snap.markdown)
