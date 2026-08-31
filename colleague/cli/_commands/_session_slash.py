"""The session's slash-command catalog, ``/help`` rendering and popup geometry.

Split out of ``colleague/cli/_commands/session.py`` (the 1000-line hard limit,
plan ``hard-1000-line-file-limit`` t17). Pure data + formatting with zero
``_Session`` coupling — :class:`SlashSpec`, the ``_SLASH_COMMANDS`` catalog,
the grouped/verbose/compact ``/help`` renderings, ``build_slash_panels`` and
the ``_INTROSPECT`` verb→argv table. ``session.py`` re-exports every public
name, so ``session_mod._SLASH_COMMANDS`` / ``session_mod._HELP_TEXT`` and the
tests importing them from ``session`` resolve unchanged.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Optional, Sequence

from agentfront.taui.state import Panel, PanelItem
from agentfront.taui.widgets.slash_autocomplete import GROUP_ICON, format_tags

if TYPE_CHECKING:  # pragma: no cover - annotation-only
    from colleague.cli._commands.session import _Session


# ---------------------------------------------------------------------------
# Slash-command tables
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SlashSpec:
    """One slash command: its name, an optional arg hint, a one-line help, the
    intent ``group`` it belongs to (one of the five keys in ``_SLASH_GROUPS`` —
    ``runtime`` / ``workspace`` / ``git-publish`` / ``inspect`` / ``session``)
    so ``/help`` and the popup can present a grouped tree, and ``tags`` — small
    capability/risk badges (``read-only`` / ``writes`` / ``git`` / ``pr`` …,
    issue #160) shown next to the command."""

    name: str
    arg_hint: str
    description: str
    group: str = "session"
    tags: tuple[str, ...] = ()


#: colleague's slash-command intent groups (#285 t9) — display order + heading.
#: A LOCAL taxonomy (not agentfront's generic controls/inspect/session): the
#: agentfront widget accepts a consumer group list via `groups=` / `default_group=`
#: (no fork — the #249 rule). Every derived surface (/help, the popup, the slash
#: panels) iterates THIS list, so they cannot drift.
_SLASH_GROUPS: list[tuple[str, str]] = [
    ("runtime", "Runtime"),
    ("workspace", "Workspace"),
    ("git-publish", "Git / publish"),
    ("inspect", "Inspect"),
    ("session", "Session"),
]


#: The single source of truth for every slash command — the ``/help`` text, the
#: live autocomplete popup, AND the cockpit slash panels are all derived from
#: this list, so they cannot drift (a drift test pins that every dispatch verb
#: appears here).
_SLASH_COMMANDS: list[SlashSpec] = [
    SlashSpec("help", "", "this list (/help verbose|compact for more)", "session"),
    SlashSpec("commands", "", "list command templates", "inspect", ("read-only", "config")),
    SlashSpec("skills", "", "resolved skill docs", "inspect", ("read-only", "config")),
    SlashSpec("agents", "", "resolved AGENTS layers", "inspect", ("read-only", "config")),
    SlashSpec(
        "config",
        "",
        "configuration readiness (doctor)",
        "inspect",
        ("read-only", "config", "audit"),
    ),
    SlashSpec("engines", "", "discovered backend plugins", "inspect", ("read-only", "model")),
    SlashSpec(
        "telemetry", "", "telemetry configuration", "inspect", ("read-only", "telemetry", "config")
    ),
    SlashSpec(
        "feedback",
        "",
        "feedback for the last work item",
        "inspect",
        ("human-loop", "memory", "interactive"),
    ),
    SlashSpec(
        "engine",
        "<name>",
        "switch the engine for the next work item",
        "runtime",
        ("model", "config"),
    ),
    SlashSpec(
        "model",
        "[name]",
        "switch the model (no arg lists served models + roles; re-derives the budget)",
        "runtime",
        ("model", "config"),
    ),
    SlashSpec(
        "effort",
        "[rung] [seat]",
        "per-seat thinking effort (no arg lists every seat; session-only)",
        "runtime",
        ("model", "config"),
    ),
    SlashSpec(
        "mode",
        "[name]",
        "show/cycle the session mode (auto|work|plan|explore|review) — shift-tab equivalent",
        "runtime",
        ("interactive",),
    ),
    SlashSpec(
        "continue",
        "[id|last]",
        "resume a cut work item from its persisted artifact",
        "runtime",
        ("writes", "git"),
    ),
    SlashSpec("base", "<branch>", "set the PR base branch", "workspace", ("git", "config")),
    SlashSpec(
        "pr",
        "",
        "toggle push + open PR on each work item",
        "git-publish",
        ("git", "pr", "writes", "human-loop"),
    ),
    SlashSpec(
        "attach",
        "[path]",
        "stage a media attachment for the next work line (no arg lists staged)",
        "workspace",
        ("media", "config"),
    ),
    SlashSpec(
        "voice",
        "",
        "toggle the realtime voice lane (opt in / mute) — needs realtime + senses",
        "runtime",
        ("voice", "interactive"),
    ),
    SlashSpec(
        "speak",
        "",
        "toggle speak-only playback of senses replies (no mic) — needs tts",
        "runtime",
        ("voice", "interactive"),
    ),
    SlashSpec(
        "learn-from",
        "<source> [name…]",
        "learn skills from a peer (e.g. claude) into .colleague/skills/",
        "workspace",
        ("writes", "config"),
    ),
    SlashSpec("quit", "", "end the session", "session", ("safe",)),
]


def filter_slash(prefix: str, specs: Optional[Sequence[SlashSpec]] = None) -> list[SlashSpec]:
    """Return the slash commands whose name starts with *prefix* (case-insensitive).

    An empty prefix returns the full list (popup just opened); a non-matching
    prefix returns ``[]`` (the popup vanishes). This is the pure, TTY-free core
    of the autofilter.
    """
    pool = _SLASH_COMMANDS if specs is None else list(specs)
    needle = prefix.strip().lower()
    return [s for s in pool if s.name.lower().startswith(needle)]


def _grouped(specs: Sequence[SlashSpec]) -> dict[str, list[SlashSpec]]:
    """Bucket *specs* by their ``group``, preserving catalog order within a group."""
    groups: dict[str, list[SlashSpec]] = {}
    for s in specs:
        groups.setdefault(s.group or "session", []).append(s)
    return groups


def _format_help(specs: Sequence[SlashSpec], style: str = "text") -> str:
    """Compact, grouped ``/help`` — one ``📁`` heading per intent group, each
    command on its own line with its tag badges (issue #160). Every ``/<name>``
    still appears (the drift test pins that), and the literal token ``slash
    commands`` is kept. *style* selects the tag form (``text`` | ``icons``)."""
    groups = _grouped(specs)
    rows = ["slash commands  (/help verbose for descriptions · /help compact for icons)"]
    for key, title in _SLASH_GROUPS:
        members = groups.get(key, [])
        if not members:
            continue
        rows.append("")
        rows.append(f"{GROUP_ICON} {title}")
        for s in members:
            left = f"/{s.name}" + (f" {s.arg_hint}" if s.arg_hint else "")
            rows.append(f"  {left:<18} {format_tags(s.tags, style)}".rstrip())
    rows.append("")
    rows.append(
        "plain text (a number / template name / free-text task) runs a work item; "
        "free text routes by the active mode (auto classifies each input; shift-tab "
        "or /mode pins work|plan|explore|review)."
    )
    return "\n".join(rows)


def _format_help_verbose(specs: Sequence[SlashSpec], style: str = "text") -> str:
    """Verbose ``/help`` — every command grouped, with arg hints, descriptions,
    and tag badges."""
    groups = _grouped(specs)
    rows = ["slash commands (verbose)"]
    for key, title in _SLASH_GROUPS:
        members = groups.get(key, [])
        if not members:
            continue
        rows.append("")
        rows.append(f"{GROUP_ICON} {title}")
        for s in members:
            left = f"/{s.name}" + (f" {s.arg_hint}" if s.arg_hint else "")
            tags = format_tags(s.tags, style)
            suffix = f"  {tags}" if tags else ""
            rows.append(f"  {left:<18} {s.description}{suffix}")
    rows.append("")
    rows.append("Work: type a number to run a template, or free text for an ad-hoc task.")
    rows.append(
        "      Free text routes by the active mode — auto (classify each input), or a "
        "pinned work | plan | explore | review."
    )
    rows.append("      shift-tab cycles the mode (or /mode [name]); explore/review are read-only.")
    rows.append("      /pr before a task to push + open a PR; /base sets the PR base branch.")
    return "\n".join(rows)


def build_slash_panels() -> list[Panel]:
    """The slash catalog as cockpit panels — one ``Panel`` per intent group, each
    item carrying the command's ``tags`` — so the grouped tree + tag badges reach
    the agent-facing Markdown/TAUI tiers (issue #160). The live ANSI session
    surfaces the same commands through the ``/`` popup, so ``render_flat`` skips
    these ``slash.*`` panels."""
    groups = _grouped(_SLASH_COMMANDS)
    panels: list[Panel] = []
    for key, title in _SLASH_GROUPS:
        members = groups.get(key, [])
        if not members:
            continue
        items = [
            PanelItem(
                id=f"slash.{s.name}",
                label=f"/{s.name}" + (f" {s.arg_hint}" if s.arg_hint else ""),
                tags=list(s.tags),
            )
            for s in members
        ]
        panels.append(Panel(id=f"slash.{key}", title=f"{GROUP_ICON} {title}", items=items))
    return panels


def _slash_tag_style() -> str:
    """Tag badge style for the live ``/`` popup: ``icons`` when
    ``COLLEAGUE_SLASH_TAG_STYLE=icons``, else the default ``text``."""
    return "icons" if os.environ.get("COLLEAGUE_SLASH_TAG_STYLE", "").lower() == "icons" else "text"


def _cursor_back_to_input(popup: str, prompt: str, buffer: str) -> str:
    """ANSI to move the cursor from the end of a *below-input* popup back onto the
    input line — so the slash popup can render under ``colleague ❯`` while the
    cursor still sits where the user is typing.

    Returns ``""`` when there is no popup (cursor is already at the input line).
    The popup occupies ``popup.count("\\n") + 1`` rows below the input line, so we
    move the cursor up that many rows and across to just after the typed buffer
    (1-based column ``len(prompt) + len(buffer) + 1``). The sequence carries no
    ``\\n``, so it survives ``_raw_loop``'s ``"\\n" -> "\\r\\n"`` rewrite unchanged.

    Pure / TTY-free → unit-testable without a terminal. Column math assumes
    single-width glyphs and no line-wrap (true for the prompt + a typed slash
    command); a wrapped buffer would land the cursor approximately, never crash.
    """
    if not popup:
        return ""
    rows = popup.count("\n") + 1
    col = len(prompt) + len(buffer) + 1  # 1-based column just past the buffer
    return f"\x1b[{rows}A\x1b[{col}G"


_HELP_TEXT = _format_help(_SLASH_COMMANDS)
_HELP_VERBOSE = _format_help_verbose(_SLASH_COMMANDS)
_HELP_COMPACT = _format_help(_SLASH_COMMANDS, style="icons")

# Read-only introspection: map a verb to the argv passed to the real CLI parser.
_INTROSPECT: dict[str, Callable[["_Session"], list[str]]] = {
    "commands": lambda s: ["commands", "list", "--repo", str(s.repo)],
    "skills": lambda s: ["skills", "list", "--repo", str(s.repo), "--model", s.config.model],
    "agents": lambda s: ["agents", "list", "--repo", str(s.repo), "--model", s.config.model],
    "config": lambda s: ["doctor"],
    "engines": lambda s: ["backends", "list"],
    "telemetry": lambda s: ["telemetry", "status"],
    "feedback": lambda s: ["feedback", "show", "last", "--repo", str(s.repo)],
}
