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

from colleague.cli._commands.session import (
    _HELP_COMPACT,
    _HELP_TEXT,
    _HELP_VERBOSE,
    _SLASH_COMMANDS,
    _Session,
    build_slash_panels,
    run_session,
)
from colleague.config import EngineConfig
from colleague.tui.render.ansi_flat import _state_glyph, render_flat
from colleague.tui.render.markdown import render_markdown
from colleague.tui.state import CockpitState, Panel, PanelItem, Status, WorkItem
from colleague.tui.taui import serialize

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
        out=lambda *a, **k: None,
        err=lambda *a, **k: None,
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
    assert render_flat(st) == render_flat(st)


def test_state_glyph_moves_with_step_count_while_running() -> None:
    st = _sample_state()
    st.work_item = WorkItem(task_id="t", engine="mock", step_count=1, running=True)
    g1 = _state_glyph(serialize(st))
    st.work_item.step_count = 2
    g2 = _state_glyph(serialize(st))
    assert g1 != g2, "the work glyph must move as steps advance"
    # Idle (not running) → steady severity glyph, not a moon-phase frame.
    st.work_item.running = False
    assert _state_glyph(serialize(st)) == "🟢"


# ── the panels reach the Markdown + TAUI tiers for free ─────────────────────


def test_markdown_tier_carries_policy_and_context(tmp_path: Path) -> None:
    md = render_markdown(_make_session(tmp_path).state)
    assert "### Run policy" in md and "### Context" in md
    assert "push + PR" in md  # the handoff safety line
    assert "/feedback" in md  # AC #5 — feedback availability represented in the UI


def test_taui_mirror_exposes_policy_and_context_panels(tmp_path: Path) -> None:
    ids = {p["id"] for p in serialize(_make_session(tmp_path).state)["panels"]}
    assert {"policy", "context", "commands", "panel.conversation"} <= ids


# ── end-to-end through run_session (Markdown tier) ──────────────────────────


def test_cockpit_shows_repo_policy_branch_feedback(tmp_path: Path) -> None:
    _git_repo(tmp_path)
    out = _CollectingOut()
    rc = run_session(_make_args(tmp_path), input_fn=iter(["q"]), out=out, _color=False)
    assert rc == 0
    text = out.text()
    assert "Run policy" in text and "Context" in text
    assert "off (local commit only)" in text  # push/PR off by default (AC #3)
    assert "telemetry" in text and "/feedback" in text  # AC #4/#5
    assert "branch" in text  # repo + branch resolution status (AC #4)


def test_pr_flips_the_policy_panel(tmp_path: Path) -> None:
    out = _CollectingOut()
    rc = run_session(_make_args(tmp_path), input_fn=iter(["/pr", "q"]), out=out, _color=False)
    assert rc == 0
    text = out.text()
    assert "off (local commit only)" in text  # the initial frame
    assert "on — push + open PR onto 'main'" in text  # after /pr, _refresh_context rebuilt it


def test_suggested_action_clean_tree_points_at_a_template(tmp_path: Path) -> None:
    _git_repo(tmp_path)
    (tmp_path / ".colleague" / "commands").mkdir(parents=True)
    (tmp_path / ".colleague" / "commands" / "setup.md").write_text("Set up.\n")
    out = _CollectingOut()
    run_session(_make_args(tmp_path), input_fn=iter(["q"]), out=out, _color=False)
    assert "Safest next: type 1 to run 'setup'" in out.text()


def test_suggested_action_dirty_tree_says_commit_first(tmp_path: Path) -> None:
    _git_repo(tmp_path)
    (tmp_path / "f.txt").write_text("changed\n")  # dirty a tracked file
    out = _CollectingOut()
    run_session(_make_args(tmp_path), input_fn=iter(["q"]), out=out, _color=False)
    assert "commit or stash first" in out.text()  # AC #1 — safest next action


def _conversation_panel(session: _Session) -> Panel:
    return next(p for p in session.state.panels if p.id == "panel.conversation")


def test_suggested_action_refreshes_after_pr_toggle(tmp_path: Path) -> None:
    """PR #159 finding 2: the Session panel's suggested action must not go stale
    after a config change. Toggling /pr changes the effect text in place."""
    _git_repo(tmp_path)
    (tmp_path / ".colleague" / "commands").mkdir(parents=True)
    (tmp_path / ".colleague" / "commands" / "setup.md").write_text("Set up.\n")
    s = _make_session(tmp_path)
    assert "commits locally, no PR" in _conversation_panel(s).content_summary
    s.open_pr = True
    s._refresh_context()
    summary = _conversation_panel(s).content_summary
    assert "pushes a PR" in summary  # refreshed
    assert "commits locally, no PR" not in summary  # old suggestion replaced, not stacked
    assert summary.count("Safest next:") == 1  # exactly one suggestion line


def test_suggested_action_refresh_preserves_conversation(tmp_path: Path) -> None:
    """The leading suggestion is replaced in place; appended conversation lines survive."""
    _git_repo(tmp_path)
    s = _make_session(tmp_path)
    s._log("a user line")
    s._refresh_context()
    summary = _conversation_panel(s).content_summary
    assert "a user line" in summary
    assert summary.count("Safest next:") == 1


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


# ── grouped compact vs verbose help (AC #6) ─────────────────────────────────


def test_compact_help_is_grouped_and_lists_every_verb() -> None:
    assert "slash commands" in _HELP_TEXT
    assert "Controls" in _HELP_TEXT and "Inspect" in _HELP_TEXT and "Session" in _HELP_TEXT
    for spec in _SLASH_COMMANDS:  # drift: every verb still appears
        assert f"/{spec.name}" in _HELP_TEXT


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
    assert {"slash.controls", "slash.inspect", "slash.session"} <= ids
    # The original cockpit panels are untouched.
    assert {"policy", "context", "commands", "panel.conversation"} <= ids


def test_slash_tree_with_tags_reaches_markdown_tier(tmp_path: Path) -> None:
    md = render_markdown(_make_session(tmp_path).state)
    assert "### 📁 Controls" in md and "### 📁 Inspect" in md
    assert "/pr" in md and "[pr]" in md and "[writes]" in md  # tag badges rendered


def test_slash_tree_tags_are_structured_in_taui(tmp_path: Path) -> None:
    panels = {p["id"]: p for p in serialize(_make_session(tmp_path).state)["panels"]}
    pr = next(i for i in panels["slash.controls"]["items"] if i["id"] == "slash.pr")
    assert pr["tags"] == ["git", "pr", "writes", "human-loop"]  # per-item tag field


def test_live_flat_view_skips_the_slash_panels() -> None:
    # The borderless live session view leaves the slash tree to the `/` popup.
    flat = render_flat(CockpitState(panels=build_slash_panels()), include_prompt=False)
    assert "Controls" not in flat and "/pr" not in flat
