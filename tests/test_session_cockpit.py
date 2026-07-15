"""Tests for the ``colleague session`` *delegation cockpit* (issue #158).

Covers the new cockpit surface: the borderless emoji-state flat ANSI renderer,
the ``policy`` + ``context`` panels (carried for free into the Markdown + TAUI
tiers), the suggested-next-action empty state, the ``/pr`` policy flip, and the
grouped-compact vs ``/help verbose`` help.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from agentfront.taui.mirror import serialize
from agentfront.taui.render.ansi_flat import _state_glyph, render_flat
from agentfront.taui.render.markdown import render_markdown
from agentfront.taui.state import Panel, PanelItem, Status
from agentfront.taui.state import TAUIState as CockpitState
from agentfront.taui.state import WorkItem

from colleague import icons
from colleague.cli._commands.session import (
    _ACTIVE_RUN_PANEL_ID,
    _HELP_COMPACT,
    _HELP_TEXT,
    _HELP_VERBOSE,
    _LAST_RUN_PANEL_ID,
    _NEXT_PANEL_ID,
    _SLASH_COMMANDS,
    _SLASH_GROUPS,
    SessionIO,
    _Session,
    build_slash_panels,
    run_session,
)
from colleague.config import EngineConfig

_BOX_CHARS = "┌┐└┘├┤┬┴┼╔╗╚╝║│─━"


# ── helpers ─────────────────────────────────────────────────────────────────


class _CollectingOut:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, *args: object, **kwargs: object) -> None:
        self.lines.append(" ".join(str(a) for a in args))

    def text(self) -> str:
        return "\n".join(self.lines)


def _make_args(tmp_path: Path, **over: object) -> argparse.Namespace:
    base = dict(
        repo=str(tmp_path),
        engine="mock",
        no_pr=True,
        base="main",
        base_url=None,
        model=None,
        api_key=None,
        max_steps=None,
        json=False,
        allow_dirty=False,
    )
    base.update(over)
    return argparse.Namespace(**base)


def _make_session(repo: Path, *, open_pr: bool = False) -> _Session:
    return _Session(
        repo=repo,
        engine_name="mock",
        open_pr=open_pr,
        base="main",
        config=EngineConfig.resolve(model="m"),
        json_mode=False,
        view="markdown",
        io=SessionIO(out=lambda *a, **k: None, err=lambda *a, **k: None),
        work_fn=lambda **k: None,
    )


def _git_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.dev"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True)
    (path / "f.txt").write_text("hello\n")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True)


def _sample_state(*, open_pr: bool = False) -> CockpitState:
    return CockpitState(
        panels=[
            Panel(
                id="policy",
                title="Run policy",
                content_summary="run_command: ungated · push/PR: off",
                items=[
                    PanelItem(id="pol.run", label="⚠️ run_command", status="ungated (any command)"),
                    PanelItem(
                        id="pol.handoff", label="🔒 push + PR", status="off (local commit only)"
                    ),
                ],
            ),
            Panel(
                id="context",
                title="Context",
                items=[
                    PanelItem(id="ctx.repo", label="📁 repo", status="colleague"),
                    PanelItem(id="ctx.branch", label="🌿 branch", status="main"),
                    PanelItem(
                        id="ctx.feedback", label="⭐ /feedback", status="no work recorded yet"
                    ),
                ],
            ),
            Panel(
                id="commands", title="Work templates", items=[PanelItem(id="c.s", label="setup")]
            ),
            Panel(id="panel.conversation", title="Session", content_summary="Safest next: type 1."),
        ],
        status=Status(severity="info", message="colleague session · mock · local"),
    )


# ── flat (borderless, emoji) renderer ───────────────────────────────────────


def test_flat_renderer_is_borderless_with_emoji_and_color() -> None:
    out = render_flat(_sample_state(), width=80)
    assert not any(c in out for c in _BOX_CHARS), "flat cockpit must have no box borders"
    assert "🟢" in out  # the idle state glyph
    assert "Run policy" in out and "Context" in out and "Work templates" in out
    assert "\x1b[" in out  # it is the colour tier


def test_flat_renderer_is_deterministic() -> None:
    st = _sample_state()
    first = render_flat(st)
    second = render_flat(st)
    assert first == second


def test_state_glyph_moves_with_step_count_while_running() -> None:
    import dataclasses

    st = _sample_state()
    # TAUIState and WorkItem are frozen=True — use dataclasses.replace for mutations.
    st = dataclasses.replace(
        st, work_item=WorkItem(task_id="t", engine="mock", step_count=1, running=True)
    )
    g1 = _state_glyph(serialize(st))
    st = dataclasses.replace(st, work_item=dataclasses.replace(st.work_item, step_count=2))
    g2 = _state_glyph(serialize(st))
    assert g1 != g2, "the work glyph must move as steps advance"
    # Idle (not running) → steady severity glyph, not a moon-phase frame.
    st = dataclasses.replace(st, work_item=dataclasses.replace(st.work_item, running=False))
    assert _state_glyph(serialize(st)) == "🟢"


# ── the panels reach the Markdown + TAUI tiers for free ─────────────────────


def test_markdown_tier_carries_policy_and_context(tmp_path: Path) -> None:
    md = render_markdown(_make_session(tmp_path).state)
    # agentfront.taui.render.markdown uses H2 (##) for panels, not H3 (###).
    # Panel titles carry the icons-vocabulary glyph (#285 t6) under the default
    # emoji mode, so match through `icons.label` rather than the bare string.
    policy_title = icons.label("Run policy", "policy", "emoji")
    context_title = icons.label("Context", "context", "emoji")
    assert f"## {policy_title}" in md and f"## {context_title}" in md
    assert "push + PR" in md  # the handoff safety line
    assert "/feedback" in md  # AC #5 — feedback availability represented in the UI


def test_taui_mirror_exposes_policy_and_context_panels(tmp_path: Path) -> None:
    ids = {p["id"] for p in serialize(_make_session(tmp_path).state)["panels"]}
    assert {"policy", "context", "commands", "panel.conversation"} <= ids


# ── Next panel + disambiguated mode facts (#285 t6 acceptance) ──────────────
# The idle frame renders the safest-next-move as its OWN panel (not status
# text buried in the Session panel), and shows three DISTINCT mode facts
# (behavior / source / execution profile) rather than one conflated line.
# Asserted through BOTH the rendered flat-ANSI frame and the TAUI mirror dict,
# per the #285 acceptance criteria.


def test_idle_frame_renders_next_as_its_own_panel(tmp_path: Path) -> None:
    _git_repo(tmp_path)
    (tmp_path / ".colleague" / "commands").mkdir(parents=True)
    (tmp_path / ".colleague" / "commands" / "setup.md").write_text("Set up.\n")
    s = _make_session(tmp_path)

    # Rendered flat-ANSI frame: the Next panel's heading + its suggestion text.
    frame = render_flat(s.state, include_prompt=False)
    assert icons.label("Next", "next", "emoji") in frame
    assert "Safest next: type 1 to run 'setup'" in frame

    # TAUI mirror dict: a distinct "next" panel with an id-carrying item.
    mirrored = {p["id"]: p for p in serialize(s.state)["panels"]}
    assert "next" in mirrored
    next_items = mirrored["next"]["items"]
    assert len(next_items) == 1
    assert next_items[0]["id"] == "next.action"
    assert "Safest next: type 1 to run 'setup'" in next_items[0]["label"]
    # It is NOT smuggled into the Session panel's content_summary anymore.
    assert mirrored["panel.conversation"]["content_summary"] == ""


def test_idle_frame_shows_disambiguated_mode_facts(tmp_path: Path) -> None:
    s = _make_session(tmp_path)
    s.mode = "explore"
    s._refresh_status()  # mirrors a shift-tab / `/mode explore` cycle

    # Rendered flat-ANSI frame: behavior+source and the execution profile show
    # as two distinct rows, not one blurred "explore — steps≤.." line.
    frame = render_flat(s.state, include_prompt=False)
    assert "explore (pinned)" in frame  # behavior + source, disambiguated
    assert "steps" in frame  # the execution profile is present too

    # TAUI mirror dict: the same three facts as three separate items.
    mirrored = next(p for p in serialize(s.state)["panels"] if p["id"] == "capacity")
    by_id = {i["id"]: i for i in mirrored["items"]}
    assert by_id["cap.mode"]["status"] == "explore (pinned)"
    assert "explore" not in by_id["cap.mode_profile"]["status"]  # profile names no mode
    assert "steps" in by_id["cap.mode_profile"]["status"]


# ── Capacity panel + phase status + goal line (spec R3 / plan t9 / #256) ────
# Rides the existing generic panel walk — no agentfront schema bump. The
# upstream TAUIState `capacity`/`phase`/`goal` fields are a separate ask
# (agentfront#48); this is the "lands independently" half (see
# docs/features/tier-visibility.md).


def _capacity_panel(session: _Session) -> Panel:
    return next(p for p in session.state.panels if p.id == "capacity")


def test_capacity_panel_present_after_startup_with_budget_row(tmp_path: Path) -> None:
    s = _make_session(tmp_path)
    panel = _capacity_panel(s)
    budget = next(i for i in panel.items if i.id == "cap.budget")
    assert "tokens" in budget.status
    assert str(s.config.context_budget_tokens) in budget.status.replace(",", "")
    # No work item has run yet — the signal row says so honestly.
    signal = next(i for i in panel.items if i.id == "cap.signal")
    assert signal.status == "none yet"


def test_capacity_panel_neutral_signal_carries_no_warning_glyph(tmp_path: Path) -> None:
    """#285 t6: a neutral 'nothing has happened yet' fact must not look like a
    warning — the warning glyph is reserved for a genuine capacity signal."""
    s = _make_session(tmp_path)
    signal = next(i for i in _capacity_panel(s).items if i.id == "cap.signal")
    assert signal.status == "none yet"
    assert "⚠" not in signal.label


def test_capacity_panel_real_warning_carries_the_warning_glyph(tmp_path: Path) -> None:
    """The flip side: once a real fill-line/backpressure signal lands, the
    warning glyph IS shown — the neutral case is the only one that suppresses it."""
    from colleague.contract import OK, Task, TaskResult

    def _work_fn(**kwargs: object) -> tuple[TaskResult, Path]:
        return (
            TaskResult(task_id="x", status=OK, summary="done", capacity_warning="fill-line hit"),
            tmp_path / "art.json",
        )

    s = _make_session(tmp_path)
    s.work_fn = _work_fn
    s._run_work(Task.new(str(tmp_path), "do something"), None)
    signal = next(i for i in _capacity_panel(s).items if i.id == "cap.signal")
    assert "⚠" in signal.label


def test_capacity_panel_shows_disambiguated_mode_behavior_and_source(tmp_path: Path) -> None:
    """#285 t6: behavior (which mode) and source (auto vs pinned) are one
    disambiguated fact (`cap.mode`), separate from the execution profile
    (`cap.mode_profile`) — never blurred into a single conflated line."""
    s = _make_session(tmp_path)
    s.mode = "explore"
    s._refresh_status()  # mirrors a shift-tab / `/mode explore` cycle
    mode_row = next(i for i in _capacity_panel(s).items if i.id == "cap.mode")
    assert "explore" in mode_row.status
    assert "pinned" in mode_row.status  # cycling pins the mode — never re-classified
    profile_row = next(i for i in _capacity_panel(s).items if i.id == "cap.mode_profile")
    assert "explore" not in profile_row.status  # the profile row names no mode
    assert "steps" in profile_row.status  # a concrete profile, not "no fixed profile"


def test_capacity_panel_auto_mode_says_no_fixed_profile(tmp_path: Path) -> None:
    s = _make_session(tmp_path)
    assert s.mode == "auto"
    mode_row = next(i for i in _capacity_panel(s).items if i.id == "cap.mode")
    assert mode_row.status == "auto (auto)"  # behavior=auto, source=auto (not yet classified)
    profile_row = next(i for i in _capacity_panel(s).items if i.id == "cap.mode_profile")
    assert "no fixed profile" in profile_row.status


def test_capacity_panel_shows_capacity_warning_after_work_item(tmp_path: Path) -> None:
    """The latest fill-line/backpressure signal surfaced on a finished
    TaskResult (`capacity_warning`) renders in the refreshed Capacity panel."""
    from colleague.contract import OK, Task, TaskResult

    def _work_fn(**kwargs: object) -> tuple[TaskResult, Path]:
        return (
            TaskResult(
                task_id="x",
                status=OK,
                summary="done",
                capacity_warning="backpressure escalated: model turns are averaging slow",
            ),
            tmp_path / "art.json",
        )

    s = _make_session(tmp_path)
    s.work_fn = _work_fn
    s._run_work(Task.new(str(tmp_path), "do something"), None)
    signal = next(i for i in _capacity_panel(s).items if i.id == "cap.signal")
    assert "backpressure escalated" in signal.status


def test_markdown_and_mirror_carry_capacity_panel(tmp_path: Path) -> None:
    """The generic panel walk carries the Capacity panel to both agent-facing
    tiers with no per-renderer code (AC e)."""
    s = _make_session(tmp_path)
    md = render_markdown(s.state)
    capacity_title = icons.label("Capacity", "capacity", "emoji")
    assert f"## {capacity_title}" in md
    ids = {p["id"] for p in serialize(s.state)["panels"]}
    assert "capacity" in ids
    mirrored = next(p for p in serialize(s.state)["panels"] if p["id"] == "capacity")
    item_ids = {i["id"] for i in mirrored["items"]}
    assert {"cap.budget", "cap.mode", "cap.mode_profile", "cap.signal"} <= item_ids


def _session_panel(session: _Session) -> Panel:
    return next(p for p in session.state.panels if p.id == "panel.conversation")


def test_goal_line_appears_while_work_item_runs_and_clears_after(tmp_path: Path) -> None:
    from colleague.contract import OK, Task, TaskResult

    captured: dict = {}

    def _work_fn(**kwargs: object) -> tuple[TaskResult, Path]:
        sink = kwargs["display"].sink
        goal_item = next((i for i in _session_panel(sink._session).items), None)
        captured["status"] = goal_item.status if goal_item else None
        return TaskResult(task_id="x", status=OK, summary="done"), tmp_path / "art.json"

    s = _make_session(tmp_path)
    s.work_fn = _work_fn
    task = Task.new(str(tmp_path), "fix the flaky auth test at login.py line 42")
    s._run_work(task, None)
    assert captured["status"] == "fix the flaky auth test at login.py line 42"
    # Cleared once the work item ends — no lingering goal item.
    assert _session_panel(s).items == []


def test_goal_line_truncates_to_first_line_around_80_chars(tmp_path: Path) -> None:
    from colleague.cli._commands.session import _goal_text

    long_instruction = "x" * 120
    goal = _goal_text(f"{long_instruction}\nsecond line ignored")
    assert goal.endswith("…")
    assert len(goal) <= 80
    assert "second line" not in goal


# ── end-to-end through run_session (Markdown tier) ──────────────────────────


def test_cockpit_shows_repo_policy_branch_feedback(tmp_path: Path) -> None:
    _git_repo(tmp_path)
    out = _CollectingOut()
    rc = run_session(_make_args(tmp_path), input_fn=iter(["q"]), out=out, _color=False)
    assert rc == 0
    text = out.text()
    assert "Run policy" in text and "Context" in text
    # push/PR off by default (AC #3) — the honest label · state · consequence
    # grammar (#285 t6): state "off", consequence names what actually happens.
    assert "commits locally only — nothing leaves this machine" in text
    assert "telemetry" in text and "/feedback" in text  # AC #4/#5
    assert "branch" in text  # repo + branch resolution status (AC #4)


def test_pr_flips_the_policy_panel(tmp_path: Path) -> None:
    out = _CollectingOut()
    rc = run_session(_make_args(tmp_path), input_fn=iter(["/pr", "q"]), out=out, _color=False)
    assert rc == 0
    text = out.text()
    assert "commits locally only — nothing leaves this machine" in text  # the initial frame
    # after /pr, _refresh_context rebuilt it with the push+PR consequence:
    assert "pushes a branch + opens a PR onto 'main'" in text


def _next_panel_of(session: _Session) -> Panel:
    """The first-class *Next* panel (#285 t6) — the promoted safest-next-move,
    no longer buried in the Session panel's ``content_summary``."""
    return next(p for p in session.state.panels if p.id == "next")


def _next_label(session: _Session) -> str:
    return _next_panel_of(session).items[0].label


def test_suggested_action_clean_tree_points_at_a_template(tmp_path: Path) -> None:
    _git_repo(tmp_path)
    (tmp_path / ".colleague" / "commands").mkdir(parents=True)
    (tmp_path / ".colleague" / "commands" / "setup.md").write_text("Set up.\n")
    # #285 t6: the suggested action is a first-class Next panel item, not
    # status text stuffed into the Session panel's content_summary.
    s = _make_session(tmp_path)
    assert "Safest next: type 1 to run 'setup'" in _next_label(s)


def test_suggested_action_dirty_tree_says_commit_first(tmp_path: Path) -> None:
    _git_repo(tmp_path)
    (tmp_path / "f.txt").write_text("changed\n")  # dirty a tracked file
    s = _make_session(tmp_path)
    assert "commit or stash first" in _next_label(s)  # AC #1
    assert "⚠" in _next_label(s)  # a genuine caution earns the warning glyph


def test_suggested_action_refreshes_after_pr_toggle(tmp_path: Path) -> None:
    """PR #159 finding 2: the Next panel's suggested action must not go stale
    after a config change. Toggling /pr changes the effect text in place."""
    _git_repo(tmp_path)
    (tmp_path / ".colleague" / "commands").mkdir(parents=True)
    (tmp_path / ".colleague" / "commands" / "setup.md").write_text("Set up.\n")
    s = _make_session(tmp_path)
    assert "commits locally, no PR" in _next_label(s)
    s.open_pr = True
    s._refresh_context()
    label = _next_label(s)
    assert "pushes a PR" in label  # refreshed
    assert "commits locally, no PR" not in label  # old suggestion replaced, not stacked
    assert label.count("Safest next:") == 1  # exactly one suggestion line
    # Exactly one item — the panel never stacks a second suggestion on refresh.
    assert len(_next_panel_of(s).items) == 1


def test_suggested_action_refresh_preserves_conversation(tmp_path: Path) -> None:
    """The Next panel is rebuilt in place; appended conversation lines survive.

    In the agentfront TAUI model, conversation lines live in ``state.conversation``
    (appended by the reducer on every ``UserInput``), separate from the Next
    panel entirely. Refresh must not clobber the conversation list.
    """
    _git_repo(tmp_path)
    s = _make_session(tmp_path)
    s._log("a user line")
    s._refresh_context()
    # The conversation lines are in state.conversation (top-level), untouched
    # by the Next-panel rebuild.
    conv_texts = [line.text for line in s.state.conversation]
    assert any("a user line" in t for t in conv_texts)
    # The Next panel still carries exactly one suggested-action item.
    assert len(_next_panel_of(s).items) == 1
    assert _next_label(s).count("Safest next:") == 1


def test_policy_panel_deny_only_is_not_labelled_deny_unlisted(tmp_path: Path) -> None:
    """PR #159 finding 3: an empty allow-list with a deny-list is deny-only, not
    'deny unlisted' (which would imply allow-list semantics that aren't active)."""
    cfgdir = tmp_path / ".colleague"
    cfgdir.mkdir()
    (cfgdir / "approvals.json").write_text('{"run_command": {"allow": [], "deny": ["rm", "curl"]}}')
    s = _make_session(tmp_path)
    panel = s._policy_panel(s._facts())
    run = next(i for i in panel.items if i.id == "pol.run_command")
    assert "deny unlisted" not in run.status
    assert run.status.startswith("deny-list:")
    assert "rm" in run.status
    assert "gated" in panel.content_summary  # a deny-list IS a gate


def test_policy_panel_empty_section_is_effectively_ungated(tmp_path: Path) -> None:
    """A present run_command section with no allow/deny rules gates nothing."""
    cfgdir = tmp_path / ".colleague"
    cfgdir.mkdir()
    (cfgdir / "approvals.json").write_text('{"run_command": {"allow": [], "deny": []}}')
    s = _make_session(tmp_path)
    panel = s._policy_panel(s._facts())
    run = next(i for i in panel.items if i.id == "pol.run_command")
    assert "deny unlisted" not in run.status
    assert "ungated" in panel.content_summary


def test_policy_panel_survives_malformed_allow_list(tmp_path: Path) -> None:
    """PR #159 finding 4: a malformed approvals.json (allow as a dict, or a list
    of non-strings) must not crash the cockpit's policy panel."""
    cfgdir = tmp_path / ".colleague"
    cfgdir.mkdir()
    (cfgdir / "approvals.json").write_text(
        '{"run_command": {"allow": {"oops": 1}, "deny": [1, 2, "rm"]}}'
    )
    s = _make_session(tmp_path)
    panel = s._policy_panel(s._facts())  # must not raise
    run = next(i for i in panel.items if i.id == "pol.run_command")
    # allow coerces to empty (a dict isn't a list); deny keeps only the string "rm".
    assert run.status.startswith("deny-list:") and "rm" in run.status


def test_policy_panel_claims_only_enforced_gates(tmp_path: Path) -> None:
    """#285 t6 CRITICAL pushback rule: the Run policy panel must claim only
    gates the harness actually enforces — push/PR on/off, and the approvals
    checksum gate when configured. It must NEVER invent a 'requires
    confirmation' escalation boundary, and must never call the tool
    'sandboxed' — the harness enforces neither."""
    s = _make_session(tmp_path)
    panel = s._policy_panel(s._facts())
    blob = " ".join(f"{i.label} {i.status}" for i in panel.items) + " " + panel.content_summary
    assert "requires confirmation" not in blob.lower()
    assert "sandbox" not in blob.lower()
    # The real, enforced gates are still named honestly.
    handoff = next(i for i in panel.items if i.id == "pol.handoff")
    assert "off" in handoff.status  # push/PR state
    assert "commits locally only" in handoff.status  # its real consequence


def test_policy_panel_names_the_approvals_gate_when_configured(tmp_path: Path) -> None:
    """When an approvals.json hooks/commands section is present, the file-edits
    row names the real checksum gate — still never a 'requires confirmation'
    claim."""
    cfgdir = tmp_path / ".colleague"
    cfgdir.mkdir()
    (cfgdir / "approvals.json").write_text('{"hooks": {}}')
    s = _make_session(tmp_path)
    panel = s._policy_panel(s._facts())
    files = next(i for i in panel.items if i.id == "pol.files")
    assert "checksum-gated" in files.status
    assert "requires confirmation" not in files.status.lower()


# ── grouped compact vs verbose help (AC #6) ─────────────────────────────────


def test_compact_help_is_grouped_and_lists_every_verb() -> None:
    assert "slash commands" in _HELP_TEXT
    assert "Runtime" in _HELP_TEXT
    assert "Workspace" in _HELP_TEXT
    assert "Git / publish" in _HELP_TEXT
    assert "Inspect" in _HELP_TEXT
    assert "Session" in _HELP_TEXT
    for spec in _SLASH_COMMANDS:  # drift: every verb still appears
        assert f"/{spec.name}" in _HELP_TEXT


def test_every_command_group_is_one_of_the_five_declared_groups() -> None:
    """No stray/typo'd group value — every spec's group is a real _SLASH_GROUPS key."""
    valid = {key for key, _ in _SLASH_GROUPS}
    assert {s.group for s in _SLASH_COMMANDS} <= valid


def test_pr_renders_under_the_publish_boundary_heading() -> None:
    """/pr is the git-publish boundary command — it must render under its own
    'Git / publish' heading, distinct from the other runtime/workspace controls."""
    groups = {s.name: s.group for s in _SLASH_COMMANDS}
    assert groups["pr"] == "git-publish"
    pr_idx = _HELP_TEXT.index("/pr")
    heading_idx = _HELP_TEXT.rindex("📁 Git / publish", 0, pr_idx)
    assert heading_idx < pr_idx  # /pr appears after (under) its own group heading


def test_engine_model_mode_are_under_runtime() -> None:
    groups = {s.name: s.group for s in _SLASH_COMMANDS}
    assert groups["engine"] == "runtime"
    assert groups["model"] == "runtime"
    assert groups["mode"] == "runtime"


def test_verbose_help_differs_and_is_richer() -> None:
    assert _HELP_VERBOSE != _HELP_TEXT
    assert "verbose" in _HELP_VERBOSE
    # Verbose carries every command's description; e.g. the engine-switch help.
    assert "switch the engine for the next work item" in _HELP_VERBOSE
    for spec in _SLASH_COMMANDS:
        assert f"/{spec.name}" in _HELP_VERBOSE


def test_help_verbose_dispatch(tmp_path: Path) -> None:
    out = _CollectingOut()
    run_session(_make_args(tmp_path), input_fn=iter(["/help verbose", "q"]), out=out, _color=False)
    assert "slash commands (verbose)" in out.text()


def test_compact_help_carries_tag_badges() -> None:
    # Default compact help shows text tag badges next to commands (issue #160).
    assert "[read-only]" in _HELP_TEXT and "[pr]" in _HELP_TEXT and "[writes]" in _HELP_TEXT


def test_help_compact_is_icon_mode_and_dispatches(tmp_path: Path) -> None:
    # /help compact renders the emoji badge form, distinct from the text help.
    assert _HELP_COMPACT != _HELP_TEXT
    assert "🚀" in _HELP_COMPACT and "[pr]" not in _HELP_COMPACT
    for spec in _SLASH_COMMANDS:  # drift: every verb still appears
        assert f"/{spec.name}" in _HELP_COMPACT
    out = _CollectingOut()
    run_session(_make_args(tmp_path), input_fn=iter(["/help compact", "q"]), out=out, _color=False)
    assert "🚀" in out.text()


# ── slash-command tree reaches the agent-facing cockpit tiers (issue #160) ──


def test_slash_panels_present_in_session_state(tmp_path: Path) -> None:
    ids = {p.id for p in _make_session(tmp_path).state.panels}
    assert {
        "slash.runtime",
        "slash.workspace",
        "slash.git-publish",
        "slash.inspect",
        "slash.session",
    } <= ids
    # The original cockpit panels are untouched.
    assert {"policy", "context", "commands", "panel.conversation"} <= ids


def test_slash_tree_with_tags_reaches_markdown_tier(tmp_path: Path) -> None:
    md = render_markdown(_make_session(tmp_path).state)
    # agentfront.taui.render.markdown uses H2 (##) for panels, not H3 (###).
    assert "## 📁 Runtime" in md
    assert "## 📁 Git / publish" in md
    assert "## 📁 Inspect" in md
    assert "/pr" in md  # the /pr command is listed in the Markdown
    # Tag badges are structured in the TAUI JSON mirror (see
    # test_slash_tree_tags_are_structured_in_taui) but not rendered inline in
    # Markdown text — a faithful agentfront.taui.render.markdown behavior.


def test_slash_tree_tags_are_structured_in_taui(tmp_path: Path) -> None:
    panels = {p["id"]: p for p in serialize(_make_session(tmp_path).state)["panels"]}
    pr = next(i for i in panels["slash.git-publish"]["items"] if i["id"] == "slash.pr")
    assert pr["tags"] == ["git", "pr", "writes", "human-loop"]  # per-item tag field


def test_live_flat_view_skips_the_slash_panels() -> None:
    # The borderless live session view leaves the slash tree to the `/` popup.
    flat = render_flat(CockpitState(panels=build_slash_panels()), include_prompt=False)
    assert "Runtime" not in flat and "/pr" not in flat


def test_live_ansi_render_uses_colleague_prompt(tmp_path: Path, monkeypatch) -> None:
    """The live slash-autocomplete render path prompts ``colleague ❯``, not ``agent ❯``.

    Regression guard (#249 review). ``_read_live_ansi``'s ``_render`` closure must
    pass ``context="colleague"`` to ``plain_prompt`` exactly like the ``_fallback``
    path; agentfront's ``plain_prompt`` defaults to ``"agent ❯ "``, and
    ``_cursor_back_to_input`` measures ``len(prompt)`` — so a missing context would
    show ``agent ❯`` and mis-place the cursor by 4 columns. This path only runs on a
    real colour TTY, so the ``input_fn`` seam tests never reach it.
    """
    sess = _make_session(tmp_path)
    sess.view = "ansi"
    captured: dict = {}

    def _fake_read_line_with_popup(commands, render, filt, fallback=None):  # noqa: ANN001
        captured["render"] = render
        return "q"  # end the read immediately

    monkeypatch.setattr(
        "colleague.cli._commands._session_input.read_line_with_popup",
        _fake_read_line_with_popup,
    )
    sess._read_live_ansi()
    frame = captured["render"]("hi", [], 0)  # buffer "hi", no popup matches
    assert "colleague ❯" in frame
    assert "agent ❯" not in frame


# ── #285 t7: running-state switch (Active-run panel + last-run ledger) ────────


def test_running_frame_differs_from_idle_and_restores_on_finish(tmp_path: Path) -> None:
    """#285 t7: while a work item runs the cockpit visibly changes — the
    'suggested work' templates panel collapses, the idle Next block is replaced
    by a live Active-run panel, and the status line shows step N. On finish the
    idle layout is restored (templates back, Active-run gone, Next back) plus a
    Last-run ledger panel."""
    from colleague.contract import OK, Task, TaskResult, WorkStats

    captured: dict = {}

    def _work_fn(*, display, **kwargs: object) -> tuple[TaskResult, Path]:
        progress_sink = display.sink
        # Mid-run: drive real steps through the live sink, then snapshot the frame.
        progress_sink(0, "write_file", "foo.py", True)
        progress_sink(1, "run_command", "pytest", True)
        captured["panels"] = {p.id: p for p in s.state.panels}
        captured["status"] = s.state.status.message
        return (
            TaskResult(
                task_id="x",
                status=OK,
                summary="done",
                branch="colleague/x",
                stats=WorkStats(files_changed=1, tool_counts={"run_command": 1, "write_file": 1}),
            ),
            tmp_path / "art.json",
        )

    s = _make_session(tmp_path)
    s.work_fn = _work_fn
    s._run_work(Task.new(str(tmp_path), "build the thing"), None)

    # DURING the run — the running frame differs from idle.
    run_panels = captured["panels"]
    assert run_panels["commands"].visible is False  # templates collapsed
    assert _ACTIVE_RUN_PANEL_ID in run_panels  # Active-run present
    assert _NEXT_PANEL_ID not in run_panels  # idle Next replaced
    assert "step 2" in captured["status"]  # status shows step N
    assert "[run_command] pytest" in captured["status"]  # + current op
    # Active-run panel shows the observed changes-so-far (commits omitted mid-run).
    active = run_panels[_ACTIVE_RUN_PANEL_ID]
    changes = next(i for i in active.items if i.id == "run.changes")
    assert changes.status == "1 files · 1 commands"  # write_file → 1 file, run_command → 1 cmd

    # AFTER finish — idle restored + a Last-run ledger.
    idle = {p.id: p for p in s.state.panels}
    assert idle["commands"].visible is True  # templates re-expanded
    assert _ACTIVE_RUN_PANEL_ID not in idle  # Active-run removed
    assert _NEXT_PANEL_ID in idle  # idle Next restored (refreshed suggestion)
    assert _LAST_RUN_PANEL_ID in idle  # last-run ledger present


def test_last_run_ledger_equals_taskresult_stats_verbatim(tmp_path: Path) -> None:
    """#285 t7: the Last-run ledger is reconciled from ``TaskResult.stats`` +
    handoff, so its files/commands equal the stats verbatim, commits reflects the
    committed branch, and publish state is honest (local when no PR)."""
    from colleague.cockpit_run import reconcile
    from colleague.contract import OK, TaskResult, WorkStats

    result = TaskResult(
        task_id="x",
        status=OK,
        summary="done",
        branch="colleague/x",
        stats=WorkStats(files_changed=3, tool_counts={"run_command": 4, "edit_file": 2}),
    )
    s = _make_session(tmp_path)
    s._restore_idle_view(result)
    panel = next(p for p in s.state.panels if p.id == _LAST_RUN_PANEL_ID)
    items = {i.id: i.status for i in panel.items}
    led = reconcile(result)
    assert items["last.files"] == str(led.files_changed) == "3"  # verbatim from stats
    assert items["last.commands"] == str(led.commands_run) == "4"  # run_command count
    assert items["last.commits"] == "1"  # a committed branch → 1
    assert items["last.publish"] == "local"  # branch committed, no PR


def test_running_frame_mirror_and_markdown_carry_active_run_panel(tmp_path: Path) -> None:
    """#285 t7: the Active-run panel reaches the agent-facing tiers (TAUI mirror
    + Markdown) through the generic panel walk — zero per-renderer code."""
    s = _make_session(tmp_path)
    s._arm_run_view("ship the cockpit")
    ids = {p["id"] for p in serialize(s.state)["panels"]}
    assert _ACTIVE_RUN_PANEL_ID in ids
    active_title = icons.label("Active run", "run", "emoji")
    assert f"## {active_title}" in render_markdown(s.state)
