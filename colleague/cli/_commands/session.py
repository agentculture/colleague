"""``colleague session`` — the agent-native interactive cockpit over the work path.

Opens a foreground interactive **cockpit**: it renders one
:class:`agentfront.taui.state.TAUIState` (a command palette + a running
conversation + popups; imported since #249), reads a line of input, and dispatches it through the
**same** work path used by ``colleague work``
(:func:`~colleague.cli._commands.work.execute_work`). The loop runs until a
quit token (``q`` / ``/quit`` / empty line / EOF).

Three render tiers of the one state (#74 A2), chosen automatically:

* **interactive (a colour TTY, not ``--json``)** — the dynamic ANSI cockpit
  (popups, redraw-in-place during a work item);
* **non-interactive (piped / captured)** — **Markdown** menus (the static but
  *full* agent-readable view), the default off a TTY;
* **``--json``** — stdout carries only the work ``TaskResult`` (one JSON object
  each, preserving the machine contract); the Markdown cockpit renders to stderr
  as chrome. (The TAUI JSON mirror lives under ``colleague tui state``.)

Input is **line-based**. Plain text (a number / template name / free-text task)
runs a work item.  Free text is **intent-routed**: :func:`classify_intent` maps it
to ``work`` (the default) or ``plan`` without the operator typing a subcommand, and
a ``→ work:`` / ``→ plan:`` routing line is logged so the dispatch is always
visible.  A line starting with ``/`` is a **slash command** — the meta/system
namespace (introspection of existing nouns + live config actions).

The backend for the session resolves via :func:`~colleague.config.resolve_session_engine`:
explicit ``--engine`` flag > ``COLLEAGUE_SESSION_ENGINE`` env (a session-only
override) > ``COLLEAGUE_ENGINE`` env > built-in default (``vllm-openai``).

The session is entirely foreground (no sockets, no daemons) and stdlib-only.

Testability
-----------
:func:`run_session` keeps the injectable ``input_fn`` / ``out`` / ``err`` /
``_work_fn`` seams. ``_color`` forces the interactive-vs-static tier without a
real TTY.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Iterator, Optional, Sequence, TypeVar, cast

from agentfront.taui.colors import should_color
from agentfront.taui.events import UserInput
from agentfront.taui.reducer import reduce
from agentfront.taui.render.ansi_flat import render_flat as _render_flat
from agentfront.taui.render.layout import detect_width
from agentfront.taui.render.markdown import render_markdown as _render_markdown
from agentfront.taui.state import Header, Panel, PanelItem, Status
from agentfront.taui.state import TAUIState as CockpitState
from agentfront.taui.state import WorkItem
from agentfront.taui.widgets.prompt_input import plain_prompt
from agentfront.taui.widgets.slash_autocomplete import GROUP_ICON, SLASH_GROUPS, format_tags

from colleague import cockpit, feedback, handoff, layers, registry
from colleague.artifact import artifact_dir
from colleague.artifact import write as _write_artifact
from colleague.cli._banner import emit_banner
from colleague.cli._commands._session_input import CYCLE_MODE
from colleague.cli._commands._tui_sink import fold_phase
from colleague.cli._commands.work import execute_work as _default_work
from colleague.cli._errors import CliError
from colleague.commands import CommandError, discover_commands, expand_command, load_command
from colleague.config import EngineConfig, resolve_session_engine
from colleague.contract import SensesBlock, Task, TaskResult
from colleague.media import validate_attachment
from colleague.policy import load_policy
from colleague.profiles import resolve_profile
from colleague.senses import run_senses_intake, run_senses_speakback, senses_engine_config
from colleague.session_intent import PLAN, classify_intent
from colleague.session_modes import (
    DEFAULT_MODE,
    mode_affordance_line,
    next_mode,
    resolve_mode,
    route_for,
)
from colleague.telemetry import TelemetryConfig
from colleague.tui.from_work import work_step

# ---------------------------------------------------------------------------
# Types for the injectable seams
# ---------------------------------------------------------------------------

_WorkFn = Callable[..., tuple[TaskResult, Path]]
#: A session "plan" runner: takes a free-text request and returns a summary
#: string to fold into the feed. Injectable as a test seam (mirrors ``_WorkFn``).
_PlanFn = Callable[..., str]

#: Return type of a tracked dispatch thunk (a work-fn pair or a plan summary).
_T = TypeVar("_T")

_QUIT_TOKENS = frozenset({"q", "quit", "exit", "bye"})
_CONVERSATION_PANEL_ID = "panel.conversation"
#: CSI clear-screen + cursor-home, so the dynamic ANSI view redraws in place.
_CLEAR_HOME = "\x1b[H\x1b[2J"
#: Leading-line markers identifying a previously-rendered suggested action, so a
#: refresh replaces it in place rather than stacking duplicates in the Session panel.
_SUGGESTION_PREFIXES = ("Safest next:", "⚠ Safest next:")

#: The Session panel's goal item id (spec R3 / plan t9 / #256) — the running
#: work item's instruction, so the operator always sees WHAT is being driven.
_GOAL_ITEM_ID = "session.goal"
#: Goal line truncation — a first-line, at-a-glance hint, not the full instruction.
_GOAL_MAX_CHARS = 80

#: Capacity panel item ids (spec R3 / plan t9 / #256).
_CAPACITY_PANEL_ID = "capacity"
_CAPACITY_BUDGET_ID = "cap.budget"
_CAPACITY_PROFILE_ID = "cap.mode_profile"
_CAPACITY_SIGNAL_ID = "cap.signal"


def _goal_text(instruction: str) -> str:
    """The goal line: *instruction*'s first line, truncated to ``_GOAL_MAX_CHARS``.

    Returns ``""`` for blank/whitespace-only instructions (e.g. a synthetic plan
    task) so the caller can treat an empty result as "no goal to show".
    """
    first_line = instruction.strip().splitlines()[0] if instruction.strip() else ""
    if len(first_line) > _GOAL_MAX_CHARS:
        return first_line[: _GOAL_MAX_CHARS - 1].rstrip() + "…"
    return first_line


def _mode_profile_status(mode: str) -> str:
    """Human status for *mode*'s constraint profile (spec R1's mode-profile
    catalog, ``colleague.profiles``), or an honest 'no fixed profile' note when
    the mode has none (``auto``, or an unprofiled/unknown name) — never a crash
    or a stale-looking blank row."""
    profile = resolve_profile(mode)
    if profile is None:
        return f"{mode} — no fixed profile (resolves per input)"
    return (
        f"{mode} — steps≤{profile.max_steps} · timeout {profile.timeout:.0f}s · "
        f"budget×{profile.context_budget_fraction:g} · "
        f"fill-line {profile.fillline_threshold:.0%} · "
        f"synth-reserve {profile.synthesis_reserve_steps}"
    )


def _coerce_strs(value: object) -> list[str]:
    """Coerce a policy config value to a list of strings, tolerating bad shapes.

    Mirrors :func:`colleague.policy._str_list` so the cockpit presents exactly
    what the gate enforces: a non-list (or a list with non-string members)
    degrades to the surviving string members, never raising on a malformed
    ``approvals.json``.
    """
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _eprint(*args: object, **kwargs: object) -> None:
    """Default diagnostics sink — writes to stderr (kept off stdout)."""
    print(*args, file=sys.stderr, **kwargs)  # type: ignore[arg-type]


def _read_line(input_fn: Optional[Iterator[str]]) -> Optional[str]:
    """Return the next input line, or None on EOF / StopIteration.

    With ``input_fn`` (test seam) the next item is pulled from the iterator;
    otherwise the real :func:`input` builtin reads from stdin.
    """
    if input_fn is not None:
        try:
            return next(input_fn)  # type: ignore[call-overload]
        except StopIteration:
            return None
    try:
        return input()
    except EOFError:
        return None


def _resolve_selection(
    line: str,
    palette: list[tuple[str, str]],
    discovered: dict[str, Path],
    repo: Path,
    engine_name: str,
    note: Callable[[str], None],
    model: str | None = None,
) -> Optional[tuple[Task, Optional[str]]]:
    """Resolve a palette input line to a ``(task, command_name)`` pair.

    A bare number selects a palette entry; an exact name selects a command
    template; anything else is a free-text ad-hoc instruction (``command_name``
    is ``None``). Returns ``None`` when the line cannot be resolved (out-of-range
    number, or an unknown/erroring command) — the reason is passed to *note* and
    the caller should simply prompt again.
    """
    command_name: Optional[str] = None

    if line.isdigit():
        idx = int(line)
        if not 1 <= idx <= len(palette):
            note(f"no entry {idx} in the palette; type a number 1–{len(palette)}")
            return None
        command_name = palette[idx - 1][0]
    elif line in discovered:
        command_name = line
    else:
        # Free-text ad-hoc instruction — no originating command.
        return Task.new(str(repo), line, engine=engine_name), None

    try:
        task = expand_command(repo, command_name, [], engine_default=engine_name, model=model)
    except CommandError as exc:
        note(f"error: {exc}")
        return None
    return task, command_name


class _WorkSink:
    """Progress sink for an in-session work item: fold each step into the session's
    one shared :class:`CockpitState` and (on the dynamic ANSI tier) redraw live.

    Resolves the #206 "live cockpit synthesizing status" follow-up: a phase
    notice (empty ``tool``) is folded into the cockpit's STATUS surface
    (``state.status.message``) instead of being dropped — so a long single
    completion (``thinking…`` / ``synthesizing…`` / ``compacting…``, or a t6
    backpressure advisory, all fired the same way via ``loop._emit_phase``) is
    visibly *working, not stalled* in the live session cockpit. The #206
    invariant still holds: a phase notice never becomes a work step
    (``work_item.step_count`` does not advance, no conversation/feed line is
    added, so `tui replay`/`snapshot` — which never see this sink — stay
    step-only regardless). A subsequent REAL step always clears the phase text
    back to the session's baseline status line.
    """

    def __init__(self, session: "_Session") -> None:
        self._session = session
        # Snapshot the status line active when this work item starts (the
        # mode/engine summary from `_status()`) so a transient phase notice can
        # be cleared back to it once real progress resumes. Captured once here
        # (a plain attribute read, not a call back into the session) so this
        # sink stays usable against a bare state-holder in tests.
        self._base_status = session.state.status

    def __call__(self, step_index: int, tool: str, target: str, ok: bool) -> None:
        sess = self._session
        if not tool:
            # A phase notice (#206) — fold it into the STATUS surface only;
            # never a step (work_item.step_count untouched, no feed line). Shares
            # `fold_phase` with `_tui_sink.CockpitProgressSink` (the standalone
            # `colleague work --tui` cockpit) so both live cockpits resolve the
            # follow-up identically.
            sess.state = fold_phase(sess.state, target)
            if sess.view == "ansi":
                sess.emit()
            return
        sess.state = reduce(sess.state, work_step(tool, target, ok))
        # A real step clears any phase text left showing — it must never
        # linger once the model resumes making tool calls.
        sess.state = replace(sess.state, status=self._base_status)
        if sess.view == "ansi":
            sess.emit()  # live redraw per step

    def close(self) -> None:  # called by execute_work on every exit path
        return None


def _default_plan(*, repo: Path, engine_name: str, request: str, config: EngineConfig) -> str:
    """Default session ``plan`` runner: a quick, non-interactive spec→plan.

    Runs colleague plan mode in *quick* + *no-workforce* + auto-confirm mode so a
    conversational session yields a plan without an interactive per-item gate or a
    subagent fan-out (use ``colleague plan run`` for the full gated arc). Reuses the
    engine seams via :func:`~colleague.cli._commands.plan.run_plan_request`; raises
    :class:`CliError` (handled by the caller) on a non-live backend such as ``mock``.
    Imported lazily so a session that never plans doesn't load the plan package.
    """
    from colleague.cli._commands.plan import _auto_decide, _render_run, run_plan_request

    result = run_plan_request(
        repo=repo,
        request=request,
        engine_name=engine_name,
        config=config,
        decide=_auto_decide,
        quick=True,
        workforce=False,
    )
    return _render_run(result)


class _Session:
    """Holds the interactive session's mutable state and renders one cockpit."""

    def __init__(
        self,
        *,
        repo: Path,
        engine_name: str,
        open_pr: bool,
        base: str,
        config: EngineConfig,
        json_mode: bool,
        allow_dirty: bool = False,
        view: str,
        out: Callable[..., None],
        err: Callable[..., None],
        work_fn: _WorkFn,
        plan_fn: _PlanFn = _default_plan,
        user_home: Optional[Path] = None,
        cortex_only: bool = False,
        debug_senses: bool = False,
    ) -> None:
        self.repo = repo
        self.engine_name = engine_name  # mutable via /engine
        self.open_pr = open_pr  # mutable via /pr
        self.allow_dirty = allow_dirty  # dirty-tree guard opt-out (#149)
        self.base = base  # mutable via /base
        self.config = config  # .model mutable via /model
        # Cortex/senses (t8): bypass the senses front door for the whole session
        # (--cortex-only) and echo the perceived packet to stderr (--debug-senses).
        # Both default off; with no senses model resolved the session is
        # byte-identical either way.
        self.cortex_only = cortex_only
        self.debug_senses = debug_senses
        # Session mode — auto|work|plan|explore|review — cycled by shift-tab (live
        # ANSI) or the keyboard-free /mode slash. 'auto' is byte-identical to the
        # pre-mode behaviour (free text is classified per input); a pinned mode
        # overrides the classifier. Mutated only via _cycle_mode / _act_mode.
        self.mode = DEFAULT_MODE
        self.json_mode = json_mode
        self.view = view  # "ansi" (dynamic) | "markdown" (static)
        self.out = out
        self.err = err
        # The rendered cockpit is interactive chrome: stdout normally, but stderr
        # in --json mode so stdout carries only the work TaskResult(s).
        self.chrome = err if json_mode else out
        self.work_fn = work_fn
        self.plan_fn = plan_fn
        # The latest fill-line/backpressure signal a completed work item surfaced
        # on `TaskResult.capacity_warning` (spec R3 / plan t9 / #256), or `None`
        # before any work item has run. Read by `_capacity_panel`; set in
        # `_dispatch_work` right after a result is obtained, before the caller's
        # `_refresh_context()` rebuilds the panel — never on the render path.
        self._last_capacity_warning: Optional[str] = None
        # Media attachments staged by `/attach` (task t11), in staged order —
        # consumed (and cleared, one-shot) the next time a work line builds a
        # Task in `_work_line`. Empty by default, so a session that never
        # attaches anything is byte-identical to today.
        self._staged_attachments: list[dict] = []

        # ``user_home`` overrides the home dir command discovery scans (default
        # ``Path.home()``). Real sessions leave it ``None`` (scan the user's home);
        # hermetic callers (e.g. tools.tui_sim) pin it so personal
        # ``~/.colleague/commands`` can't leak into a reproducible run.
        self.discovered = discover_commands(repo, user_home=user_home)
        self.palette: list[tuple[str, str]] = [
            (name, load_command(self.discovered[name]).description)
            for name in sorted(self.discovered)
        ]
        self.state = self._initial_state()

    # ── state construction / mutation ────────────────────────────────────────

    def _initial_state(self) -> CockpitState:
        facts = self._facts()
        items = [
            PanelItem(
                id=f"command.{name}",
                label=(f"{name} — {desc}" if desc else name),
                status="available",
            )
            for name, desc in self.palette
        ]
        return CockpitState(
            mode=self.mode,
            header=Header(title="colleague"),
            panels=[
                self._policy_panel(facts),
                self._context_panel(facts),
                self._capacity_panel(),
                Panel(id="commands", title="Work templates", visible=True, items=items),
                Panel(
                    id=_CONVERSATION_PANEL_ID,
                    title="Session",
                    visible=True,
                    content_summary=self._suggested_action(facts),
                    items=[],
                ),
                *build_slash_panels(),
            ],
            status=self._status(),
        )

    def _status(self) -> Status:
        pr = "push+PR" if self.open_pr else "local"
        message = (
            f"colleague session · {self.engine_name} · {pr}  ·  "
            f"{mode_affordance_line(self.mode)}"
        )
        return Status(severity="info", message=message)

    # ── cockpit facts (resolved once at startup / on a config change) ────────

    def _facts(self) -> dict:
        """Resolve the cockpit's context + policy facts from existing read-only
        helpers, in one guarded pass.

        Every value degrades to a safe default (``"unknown"`` / ``"none"`` /
        ``False``) rather than raising — a cockpit that can't resolve a fact must
        still open. Called at construction and after each context-mutating slash
        action / completed work item — **never** on the per-frame render path
        (which runs per keystroke + per work step).
        """
        facts: dict = {
            "branch": "unknown",
            "dirty": False,
            "agents": 0,
            "skills": [],
            "telemetry": False,
            "runcfg": None,
            "hooks_gated": False,
            "ident": self.repo.name,
            "last": None,
            "feedback": None,
        }
        try:
            # repo/branch/tree/ident resolve through the shared cockpit builder so
            # the interactive session and the headless `tui --repo` surfaces show
            # identical values (single source of truth).
            repo_ctx = cockpit.resolve_repo_context(self.repo)
            facts["branch"] = repo_ctx["branch"]
            facts["dirty"] = repo_ctx["dirty"]
            facts["ident"] = repo_ctx["ident"]
            facts["agents"] = len(layers.resolve_agents(self.repo, self.config.model))
            facts["skills"] = sorted(layers.resolve_skills(self.repo, self.config.model))
            facts["telemetry"] = TelemetryConfig.resolve().enabled
            pol = load_policy(self.repo, model=self.config.model)
            facts["runcfg"] = pol.run_command_config()
            facts["hooks_gated"] = pol.section_present("hooks") or pol.section_present("commands")
            last = feedback.get_last_work(self.repo)
            facts["last"] = last
            if last:
                try:
                    facts["feedback"] = feedback.read_feedback(self.repo, last)
                except feedback.FeedbackError:
                    facts["feedback"] = None
        except Exception:  # nosec B110 - the cockpit must open even if a fact won't resolve
            pass
        return facts

    @staticmethod
    def _run_command_status(runcfg: dict | None) -> tuple[str, str, bool]:
        """``(status text, emoji, gated?)`` for the run_command line.

        Honest labels mirror :meth:`~colleague.policy.Policy.check_run_command`:
        an allow-list only gates when non-empty; an empty allow-list with a
        deny-list is deny-only (all others allowed); both empty is effectively
        ungated. Both lists are coerced so a malformed ``approvals.json`` can't
        crash render."""
        if runcfg is None:
            return "ungated (any command)", "⚠️", False
        allow = _coerce_strs(runcfg.get("allow"))
        deny = _coerce_strs(runcfg.get("deny"))
        if allow:
            shown = ", ".join(allow[:3]) + ("…" if len(allow) > 3 else "")
            return f"allow-list: {shown}", "🛡️", True
        if deny:
            shown = ", ".join(deny[:3]) + ("…" if len(deny) > 3 else "")
            return f"deny-list: {shown} (all others allowed)", "🛡️", True
        return "present, no rules (effectively ungated)", "⚠️", False

    def _policy_panel(self, facts: dict) -> Panel:
        """The *Run policy* panel — the safety surface (AC #3). Honest labels: the
        loop can write any repo file and run any command unless ``run_command`` is
        gated; the only real outward gate is push/PR. No sandbox is claimed."""
        run_status, run_emoji, gated = self._run_command_status(facts["runcfg"])
        edits = "read + write within repo"
        if facts["hooks_gated"]:
            edits += " · hooks/commands checksum-gated"
        if self.open_pr:
            handoff_status, handoff_emoji = f"on — push + open PR onto '{self.base}'", "🚀"
        else:
            handoff_status, handoff_emoji = "off (local commit only)", "🔒"
        summary = (
            f"run_command: {'gated' if gated else 'ungated'} · "
            f"edits: repo-local · push/PR: {'on' if self.open_pr else 'off'}"
        )
        return Panel(
            id="policy",
            title="Run policy",
            visible=True,
            content_summary=summary,
            items=[
                PanelItem(
                    id="pol.run_command", label=f"{run_emoji} run_command", status=run_status
                ),
                PanelItem(id="pol.files", label="✏️ file edits", status=edits),
                PanelItem(
                    id="pol.handoff", label=f"{handoff_emoji} push + PR", status=handoff_status
                ),
            ],
        )

    def _context_panel(self, facts: dict) -> Panel:
        """The *Context* panel — what world this colleague inhabits (AC #4/#5)."""
        skills = facts["skills"]
        if skills:
            shown = ", ".join(skills[:3]) + ("…" if len(skills) > 3 else "")
            skills_status = f"{shown} ({len(skills)})"
        else:
            skills_status = "none"
        agents_status = f"{facts['agents']} resolved" if facts["agents"] else "none"
        tree_status = "dirty (tracked changes)" if facts["dirty"] else "clean"
        fb, last = facts["feedback"], facts["last"]
        if last and fb is not None:
            fb_status = f"last graded ★{fb.rating}" + (f" by {fb.by}" if fb.by else "")
        elif last:
            fb_status = "last work ungraded — /feedback to grade"
        else:
            fb_status = "no work recorded yet"
        summary = (
            f"engine {self.engine_name} · model {self.config.model} · "
            f"{'PR' if self.open_pr else 'local'} · base {self.base}"
        )
        return Panel(
            id="context",
            title="Context",
            visible=True,
            content_summary=summary,
            items=[
                PanelItem(id="ctx.repo", label="📁 repo", status=facts["ident"]),
                PanelItem(id="ctx.branch", label="🌿 branch", status=facts["branch"]),
                PanelItem(id="ctx.tree", label="🧭 working tree", status=tree_status),
                PanelItem(id="ctx.agents", label="📋 AGENTS layers", status=agents_status),
                PanelItem(id="ctx.skills", label="🧩 skills", status=skills_status),
                PanelItem(
                    id="ctx.telemetry",
                    label="📡 telemetry",
                    status="on" if facts["telemetry"] else "off",
                ),
                PanelItem(id="ctx.feedback", label="⭐ /feedback", status=fb_status),
            ],
        )

    def _capacity_panel(self) -> Panel:
        """The *Capacity* panel (spec R3 / plan t9 / #256): context budget, the
        active session mode's constraint profile, and the latest fill-line /
        backpressure signal a completed work item surfaced. Built from cheap
        in-memory state only (``self.config`` / ``self.mode`` /
        ``self._last_capacity_warning``) — no I/O, so it renders across every
        tier via the generic panel walk (Markdown + TAUI JSON) with no
        per-renderer code, exactly like Policy/Context. No agentfront schema
        change: this rides the existing ``Panel``/``PanelItem`` shape (the
        TAUIState `capacity` block itself is the separate, agentfront-side
        upstream ask, agentfront#48 — out of scope here)."""
        tokens = self.config.context_budget_tokens
        signal = self._last_capacity_warning or "none yet"
        return Panel(
            id=_CAPACITY_PANEL_ID,
            title="Capacity",
            visible=True,
            content_summary=f"budget {tokens:,} tokens · mode {self.mode}",
            items=[
                PanelItem(
                    id=_CAPACITY_BUDGET_ID,
                    label="🧮 context budget",
                    status=f"{tokens:,} tokens",
                ),
                PanelItem(
                    id=_CAPACITY_PROFILE_ID,
                    label="📐 mode profile",
                    status=_mode_profile_status(self.mode),
                ),
                PanelItem(id=_CAPACITY_SIGNAL_ID, label="⚠️ capacity signal", status=signal),
            ],
        )

    def _suggested_action(self, facts: dict) -> str:
        """The safest/most-useful next move (AC #1) — always answers 'what now?'."""
        if facts["dirty"] and not self.allow_dirty:
            return (
                "⚠ Safest next: commit or stash first (working tree is dirty), then "
                "type a number to run a template — or /help."
            )
        if self.palette:
            first = self.palette[0][0]
            effect = "pushes a PR" if self.open_pr else "commits locally, no PR"
            return (
                f"Safest next: type 1 to run '{first}' ({effect}). "
                "/pr toggles push · /help for commands."
            )
        return (
            "Safest next: type a free-text task (runs locally, no PR until /pr). "
            "/help for commands."
        )

    def _refresh_context(self) -> None:
        """Rebuild the policy + context panels in place (preserving the running
        conversation + work-templates panels) and refresh the Session panel's
        suggested-action line. Called after a config change or a completed work
        item — both can shift branch / dirty / policy / feedback, and the
        suggested action depends on dirty-state + push/PR, so it must not go
        stale (the cockpit promises to always answer 'what now?')."""
        facts = self._facts()
        suggested = self._suggested_action(facts)
        rebuilt = {
            "policy": self._policy_panel(facts),
            "context": self._context_panel(facts),
            _CAPACITY_PANEL_ID: self._capacity_panel(),
        }
        self.state = replace(
            self.state,
            panels=[
                (
                    self._with_suggestion(p, suggested)
                    if p.id == _CONVERSATION_PANEL_ID
                    else rebuilt.get(p.id, p)
                )
                for p in self.state.panels
            ],
        )

    @staticmethod
    def _with_suggestion(panel: Panel, suggested: str) -> Panel:
        """Return the Session panel with its suggested-action line refreshed.

        In the agentfront TAUI model the running conversation feed lives in
        ``state.conversation`` (appended by the reducer on every ``UserInput`` /
        ``WorkStep``); the Session panel now carries ONLY the suggested-action
        line in ``content_summary``. Use ``dataclasses.replace`` so every other
        Panel field is preserved verbatim (future-proof against a new agentfront
        Panel field); the ``cast`` keeps the static type a concrete ``Panel``
        rather than the generic ``DataclassInstance`` ``replace`` infers (the
        same S5655 pattern used in ``_run_readonly``)."""
        return cast(Panel, replace(panel, content_summary=suggested))

    def _with_goal(self, goal: str) -> None:
        """Set (or clear, with ``goal=""``) the Session panel's goal item —
        the running work item's instruction, so the operator always sees WHAT
        is being driven (spec R3 / plan t9 / #256). Mutates ``self.state`` via
        the frozen ``dataclasses.replace`` idiom, mirroring ``_with_suggestion``.
        """
        goal_items = [PanelItem(id=_GOAL_ITEM_ID, label="🎯 goal", status=goal)] if goal else []
        self.state = replace(
            self.state,
            panels=[
                cast(Panel, replace(p, items=goal_items)) if p.id == _CONVERSATION_PANEL_ID else p
                for p in self.state.panels
            ],
        )

    def _log(self, text: str) -> None:
        """Append a line (or block) to the conversation via the pure reducer."""
        self.state = reduce(self.state, UserInput(text=text))

    def _error(self, text: str) -> None:
        """Report a diagnostic to stderr (agent-first convention); also fold it into
        the conversation in the dynamic ANSI tier so a redraw doesn't hide it."""
        self.err(text)
        if self.view == "ansi":
            self._log(text)

    def _refresh_status(self) -> None:
        self.state = replace(self.state, mode=self.mode, status=self._status())
        # The Capacity panel's mode-profile row depends on `self.mode`; refresh
        # it here too (cheap, no I/O) so cycling the mode (shift-tab / `/mode`)
        # never leaves a stale profile row showing until the next work item or
        # config-change refresh.
        self.state = replace(
            self.state,
            panels=[
                self._capacity_panel() if p.id == _CAPACITY_PANEL_ID else p
                for p in self.state.panels
            ],
        )

    # ── rendering (one path; three views) ────────────────────────────────────

    def _frame(self, *, include_prompt: bool = True) -> str:
        if self.view == "ansi":
            return _CLEAR_HOME + _render_flat(
                self.state, width=detect_width(), include_prompt=include_prompt
            )
        return _render_markdown(self.state)

    def emit(self) -> None:
        self.chrome(self._frame())

    def _read_live_ansi(self) -> Optional[str]:
        """Live ANSI read with a slash-command autocomplete popup.

        On a POSIX colour TTY this runs the raw per-keystroke reader: typing
        ``/`` opens a filtered popup of slash commands (Tab/Enter completes,
        arrows select, Esc dismisses). When raw mode is unavailable (non-TTY,
        ``termios`` missing, Windows) it falls back to the plain ``input`` path —
        byte-identical to before — so piped / ``--json`` / agent callers are
        unaffected. Tests and the static Markdown view never reach here; they go
        through :meth:`emit` + :func:`_read_line`.
        """
        from agentfront.taui.widgets.slash_autocomplete import render_slash_autocomplete

        from colleague.cli._commands._session_input import read_line_with_popup

        def _fallback() -> Optional[str]:
            sys.stdout.write(self._frame(include_prompt=False) + "\n")
            sys.stdout.flush()
            try:
                return input(plain_prompt(context="colleague"))
            except EOFError:
                return None

        def _render(buffer: str, matches: list, selected: int) -> str:
            # The slash ("skills") popup renders BELOW the input line — the cockpit
            # frame, then the prompt+buffer, then the popup — after which the cursor
            # is restored onto the input line. The whole-screen clear in `_frame`
            # (`_CLEAR_HOME` = ``\x1b[H\x1b[2J``) wipes any longer prior popup each
            # keystroke, so no explicit clear-to-end is needed here.
            # context="colleague" matches the `_fallback` path + render_flat's
            # header-derived prompt; without it the popup frame would show
            # "agent ❯" and `_cursor_back_to_input` (which measures len(prompt))
            # would land the cursor 4 columns left of the typed text.
            prompt = plain_prompt(context="colleague")
            parts = [self._frame(include_prompt=False), prompt + buffer]
            popup = ""
            if matches:
                popup = render_slash_autocomplete(
                    matches, selected, width=detect_width(), style=_slash_tag_style()
                )
                parts.append(popup)
            return "\n".join(parts) + _cursor_back_to_input(popup, prompt, buffer)

        return read_line_with_popup(_SLASH_COMMANDS, _render, filter_slash, fallback=_fallback)

    # ── the loop ─────────────────────────────────────────────────────────────

    def run(self, input_fn: Optional[Iterator[str]]) -> int:
        emit_banner(self.err, json_mode=self.json_mode)
        live_ansi = input_fn is None and self.view == "ansi"
        while True:
            if live_ansi:
                raw = self._read_live_ansi()
            else:
                self.emit()
                raw = _read_line(input_fn)
            if raw is CYCLE_MODE:
                # Shift-tab at the prompt: cycle the mode and re-prompt — never a
                # submitted line, never a quit (the sentinel is distinct from a
                # string / None / EOF).
                self._cycle_mode()
                continue
            if raw is None:
                break
            line = raw.strip()
            if line == "" or line.lower() in _QUIT_TOKENS:
                break
            if not self._handle(line):
                break
        self.err("(session ended)")
        return 0

    def _handle(self, line: str) -> bool:
        """Process one input line; return ``False`` to quit the session."""
        self._log(line)  # echo the input into the conversation
        if line.startswith("/"):
            return self._slash(line)
        self._work_line(line)
        return True

    def _cycle_mode(self) -> None:
        """Advance the session mode (shift-tab). The active mode is shown **in
        place** by the status-line affordance (``mode: … [work] …``, refreshed
        here) — the cockpit's one *changeable* mode line — so we deliberately do
        NOT also append a ``mode → …`` line to the conversation feed: rapid
        shift-tab cycling would otherwise stack one feed line per press, leaving
        every prior mode on screen (issue #251). The next free-text input routes
        under the new mode. (``/mode`` keeps its one-shot feed confirmation — a
        deliberate, non-repeated slash command, like ``/engine`` / ``/pr``.)"""
        self.mode = next_mode(self.mode)
        self._refresh_status()

    # ── slash commands ───────────────────────────────────────────────────────

    def _slash(self, line: str) -> bool:
        parts = line[1:].split()
        verb = parts[0].lower() if parts else ""
        rest = parts[1:]

        if verb in ("quit", "exit", "q"):
            return False
        if verb in ("help", ""):
            arg = rest[0].lower() if rest else ""
            self._log({"verbose": _HELP_VERBOSE, "compact": _HELP_COMPACT}.get(arg, _HELP_TEXT))
            return True

        introspect = _INTROSPECT.get(verb)
        if introspect is not None:
            self._log(self._run_cli(*introspect(self)))
            return True

        action = _CONFIG_ACTIONS.get(verb)
        if action is not None:
            try:
                confirmation = action(self, rest)
            except ValueError as exc:
                self._error(str(exc))
                return True
            self._log(confirmation)
            self._refresh_status()
            self._refresh_context()
            return True

        self._error(f"unknown command: /{verb} — try /help")
        return True

    def _run_cli(self, *argv: str) -> str:
        """Run a colleague CLI noun in-process and capture its stdout.

        Reuses the real parser (so every noun's args/defaults are correct) and
        folds the output into the cockpit. No subprocess; errors are reported, not
        raised. ``argv`` is built from the fixed slash table (never user input), so
        ``parse_args`` does not error — a regression in a mapping is caught by the
        slash-command tests, not at runtime.
        """
        from colleague.cli import _build_parser

        parser = _build_parser()
        ns = parser.parse_args(list(argv))
        sink = io.StringIO()
        try:
            with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(io.StringIO()):
                ns.func(ns)
        except CliError as exc:
            return f"error: {exc.message}"
        # Slash output is advisory — report any noun failure, never crash the session.
        except Exception as exc:  # noqa: BLE001
            return f"error: {type(exc).__name__}: {exc}"
        return sink.getvalue().rstrip() or "(no output)"

    # ── work ────────────────────────────────────────────────────────────────

    def _consume_staged_attachments(self, task: Task) -> None:
        """Move any ``/attach``-staged entries onto *task*, in staged order, and
        clear the staging list — one-shot semantics (task t11): the work line
        that follows carries none. A no-op when nothing is staged, so a task
        built with no ``/attach`` in play keeps its constructed default
        (``attachments=None``), byte-identical to before this feature.
        """
        if not self._staged_attachments:
            return
        task.attachments = self._staged_attachments
        self._staged_attachments = []

    def _work_line(self, line: str) -> None:
        # Agent-native intent routing (#234), now mode-aware: a free-text goal
        # reaches colleague's own verb WITHOUT the user typing the subcommand. The
        # active mode decides the verb via ``route_for`` — ``auto`` classifies each
        # input (byte-identical to the pre-mode behaviour: same classify_intent call,
        # same ``→ work:``/``→ plan:`` log), while ``work``/``plan``/``explore``/
        # ``review`` pin the route. A bare number / known template name is always a
        # work-template selection regardless of mode (a palette pick is never
        # reclassified) — only genuinely free text is routed.
        stripped = line.strip()
        is_free_text = bool(stripped) and not stripped.isdigit() and stripped not in self.discovered
        if is_free_text:
            verb = route_for(self.mode, stripped, classify_intent)
            if verb == PLAN:
                self._log(f"→ plan: {stripped}")
                self._run_plan(stripped)
                return
            if verb == "explore":
                self._log(f"→ explore: {stripped}")
                self._run_explore(stripped)
                return
            if verb == "review":
                self._log(f"→ review: {stripped}")
                self._run_review(stripped)
                return
            # verb == "work" → fall through to the work-template / ad-hoc path.
        resolved = _resolve_selection(
            line,
            self.palette,
            self.discovered,
            self.repo,
            self.engine_name,
            self._error,
            model=self.config.model,
        )
        if resolved is None:
            return
        task, command_name = resolved
        # Any /attach-staged media rides THIS work item (staged order), then the
        # staging list clears (t11 one-shot semantics) — only a genuine work-line
        # dispatch consumes it; a plan/explore/review route above never reaches here.
        self._consume_staged_attachments(task)
        if is_free_text:
            self._log(f"→ work: {stripped}")
        # Cortex/senses (t8): with a senses model resolved, a free-text work line
        # runs senses intake first (perceives the request → ContextPacket on the
        # task) unless --cortex-only. classify_intent already picked the VERB above;
        # this only perceives the CONTENT — the two compose, never compete.
        senses_mode, intake_record = self._prepare_senses(task, is_free_text)
        self._run_work(task, command_name, senses_mode=senses_mode, intake_record=intake_record)

    def _run_tracked(
        self, task_id: str, thunk: Callable[[], _T], *, goal: str = ""
    ) -> Optional[_T]:
        """Run *thunk* with the cockpit work-item marked running, uniform error
        handling, and a guaranteed running-flag reset; return its value, or ``None``
        if it raised. A :class:`CliError` (with its remediation hint) or any
        unexpected exception is surfaced via ``_error`` and swallowed, so one failed
        dispatch never tears down the session. The single home for the running-state
        + error scaffold shared by ``_run_plan`` and ``_dispatch_work``.

        ``goal`` (spec R3 / plan t9 / #256) is the running item's instruction
        text; it is shown in the Session panel's goal line for the duration of
        *thunk* and cleared unconditionally in the ``finally`` — so a goal
        never lingers after the work item ends, on either the success or the
        error path.
        """
        self.state = replace(
            self.state,
            work_item=WorkItem(task_id=task_id, engine=self.engine_name, running=True),
        )
        self._with_goal(goal)
        try:
            return thunk()
        except CliError as exc:
            hint = f" (hint: {exc.remediation})" if exc.remediation else ""
            self._error(f"error: {exc.message}{hint}")
            return None
        except Exception as exc:  # noqa: BLE001
            self._error(f"error: {type(exc).__name__}: {exc}")
            return None
        finally:
            if self.state.work_item is not None:
                self.state = replace(
                    self.state, work_item=replace(self.state.work_item, running=False)
                )
            self._with_goal("")

    def _dispatch_work(
        self,
        task: Task,
        *,
        open_pr: bool,
        config: EngineConfig,
        command_name: Optional[str],
        mode: Optional[str] = None,
    ) -> Optional[TaskResult]:
        """Run one work item through the shared work path (cockpit running-state +
        error handling via ``_run_tracked``, then the json-mode result echo); return
        the :class:`TaskResult`, or ``None`` if the dispatch surfaced an error. The
        single home for the ``work_fn`` call shared by ``_run_work`` and
        ``_run_readonly`` — the caller owns the feed rendering of the result.
        ``mode`` (t3/R1) names the constraint profile; it resolves inside
        ``execute_work`` — the same code path the ``work --mode`` flag uses."""
        pair = self._run_tracked(
            task.id,
            lambda: self.work_fn(
                repo=self.repo,
                engine_name=self.engine_name,
                task=task,
                open_pr=open_pr,
                allow_dirty=self.allow_dirty,
                base=self.base,
                config=config,
                command_name=command_name,
                progress_sink=_WorkSink(self),
                mode=mode,
            ),
            goal=task.instruction,
        )
        if pair is None:
            return None
        result, _artifact = pair
        # The Capacity panel's signal row (spec R3 / plan t9 / #256) surfaces the
        # latest fill-line/backpressure warning; captured here, BEFORE the
        # caller's `_refresh_context()` rebuilds the panel, so it is never stale.
        self._last_capacity_warning = result.capacity_warning
        if self.json_mode:
            self.out(json.dumps(result.to_dict(), ensure_ascii=False))
        return result

    def _run_plan(self, request: str) -> None:
        """Route a planning-intent free-text goal to colleague's ``plan`` verb.

        Runs the injected ``plan_fn`` (default: a quick non-interactive spec→plan)
        and folds its summary into the feed. A non-live backend (e.g. ``mock``)
        raises :class:`CliError`, surfaced cleanly — never a crash, never a handoff.
        """
        # A synthetic work item keeps the cockpit "running" glyph alive; ``Task.new``
        # only mints an id here (the plan path does not run the work loop).
        summary = self._run_tracked(
            Task.new(str(self.repo), request).id,
            lambda: self.plan_fn(
                repo=self.repo,
                engine_name=self.engine_name,
                request=request,
                config=self.config,
            ),
            goal=request,
        )
        if summary is None:
            return
        self._log(summary)
        self._refresh_context()

    # ── cortex/senses split (t8) ─────────────────────────────────────────────

    def _senses_engine(self):
        """Return ``(senses_config, engine)`` for a senses call, or ``None``.

        ``None`` when no senses model is resolved (byte-identical) or the engine
        cannot be loaded — the caller then proceeds cortex-only. Both intake and
        speak-back go through this one seam."""
        senses_config = senses_engine_config(self.config)
        if senses_config is None:
            return None
        try:
            engine = registry.load(self.engine_name)
        except Exception:  # noqa: BLE001 - an unloadable engine → proceed cortex-only
            return None
        return senses_config, engine

    def _prepare_senses(self, task: Task, is_free_text: bool):
        """Run senses intake for a free-text work line; return ``(mode, record)``.

        ``mode`` is ``None`` (no senses resolved → byte-identical),
        ``"cortex-only"`` (resolved but bypassed via ``--cortex-only`` or a
        non-free-text template pick), or ``"split"`` (intake ran). On ``split``
        the perceived :class:`~colleague.contract.ContextPacket` is attached to
        *task* so the loop (t6) injects it + records mode=split; a degraded intake
        attaches nothing and the raw request proceeds — the run never fails
        (spec q1 / acceptance 3)."""
        if self.config.senses is None:
            return None, None
        if self.cortex_only or not is_free_text:
            return "cortex-only", None
        pair = self._senses_engine()
        if pair is None:
            return "cortex-only", None
        senses_config, engine = pair
        packet, record = run_senses_intake(task.instruction, senses_config, engine)
        if packet is None:
            self._log("senses: intake degraded — using the raw request")
        else:
            task.context_packet = packet
            self._log(
                f"senses: perceived {packet.task_type or 'request'} "
                f"(confidence {packet.confidence:.2f})"
            )
            if self.debug_senses:
                self.err(f"[debug-senses] {packet.to_dict()}")
        return "split", record

    def _resave_artifact(self, result: TaskResult) -> None:
        """Re-write the work item's artifact after folding session-side senses
        records in. ``write`` is deterministic on task_id + request, so this
        overwrites the same file execute_work wrote — never a second artifact."""
        try:
            _write_artifact(result, artifact_dir(self.repo))
        except Exception:  # nosec B110 - a re-save failure must never fail the run
            pass

    def _finalize_split_run(self, result: TaskResult, intake_record) -> Optional[str]:
        """Fold the session-side intake + speak-back records onto ``result.senses``
        and re-save the artifact; return the shaped DISPLAY summary (or ``None`` to
        fall back to the raw one).

        The raw cortex summary on ``result.summary`` is never mutated (the artifact
        keeps it, acceptance 1); only the displayed line is shaped."""
        shaped, speakback_record = None, None
        pair = self._senses_engine()
        if pair is not None:
            senses_config, engine = pair
            shaped, speakback_record = run_senses_speakback(result.summary, senses_config, engine)
        if result.senses is None:
            result.senses = SensesBlock(mode="split", packet=None, records=[])
        pre = [intake_record] if intake_record is not None else []
        post = [speakback_record] if speakback_record is not None else []
        result.senses.records = pre + list(result.senses.records) + post
        self._resave_artifact(result)
        return shaped

    def _run_work(
        self,
        task: Task,
        command_name: Optional[str],
        *,
        senses_mode: Optional[str] = None,
        intake_record=None,
    ) -> None:
        # The cockpit's state glyph animates per step while the work item runs
        # (the sink's WorkStep reductions advance ``work_item.step_count``).
        # Cortex/senses (t8): a cortex-only run suppresses the loop's senses media
        # bridge too (config.senses=None); split/None leave the config untouched.
        config = replace(self.config, senses=None) if senses_mode == "cortex-only" else self.config
        result = self._dispatch_work(
            task,
            open_pr=self.open_pr,
            config=config,
            command_name=command_name,
            # The work verb's profile is behaviour-neutral by construction (it
            # equals the built-in defaults) but keeps the one-code-path claim
            # honest and lets an operator overlay tune session work runs.
            mode="work",
        )
        if result is None:
            return
        display = result.summary
        if senses_mode == "split":
            display = self._finalize_split_run(result, intake_record) or result.summary
        elif senses_mode == "cortex-only":
            # Senses was resolved but bypassed — record it honestly on the artifact.
            result.senses = SensesBlock(mode="cortex-only", packet=None, records=[])
            self._resave_artifact(result)
        changed = ", ".join(result.changed_files) or "(none)"
        branch = f" → {result.branch}" if result.branch else ""
        self._log(f"{result.status}: {display} [{changed}]{branch}")
        # A completed work item can change branch / dirty / last-feedback state.
        self._refresh_context()

    def _run_explore(self, request: str) -> None:
        """Read-only investigation (explorer role): inspect the repo to answer a
        free-text question. Never writes, never pushes/PRs — the read-only role
        structurally withholds write_file/edit_file/run_command, so it cannot
        touch the operator's tree even if the model attempts a write."""
        self._run_readonly(request, role="explorer", mode="explore")

    def _run_review(self, request: str) -> None:
        """Read-only diverse second opinion on the committed ``<base>...HEAD`` diff
        (reviewer role). The diff is sourced operator-side and injected because the
        read-only reviewer role withholds ``run_command`` and so cannot run git
        itself; the reviewer critiques the provided diff and reads files as needed."""
        diff = handoff.diff_range(self.repo, self.base)
        focus = request.strip()
        task_text = (
            f"Give a candid, specific second opinion on the committed changes on "
            f"this branch versus '{self.base}' (the diff below is `git diff "
            f"{self.base}...HEAD`). "
            + (f"Focus on: {focus}. " if focus else "")
            + "Call out correctness bugs, risks, and concrete improvements, citing "
            "file:line. Do not modify any files.\n\n"
            f"--- diff {self.base}...HEAD ---\n" + (diff or "(no committed changes vs base)")
        )
        self._run_readonly(request, role="reviewer", mode="review", task_text=task_text)

    def _run_readonly(
        self,
        request: str,
        *,
        role: str,
        mode: str | None = None,
        task_text: str | None = None,
    ) -> None:
        """Shared read-only dispatch for explore/review: run the work loop under a
        read-only *role* with NO push/PR handoff (``open_pr=False``), so the
        operator's tree + branch are never touched. ``task_text`` overrides the
        model-facing instruction (review injects the diff); explore uses *request*
        verbatim. The role is set on a COPY of the config so ``self.config`` (the
        session's writer-surface default) is left untouched.

        DECISION (resolves the parked frame unknown): session explore/review run
        **in-place** under the read-only role, NOT in a throwaway worktree like the
        ask-colleague verbs. The explorer/reviewer role structurally withholds
        write_file/edit_file/run_command (``roles._WRITE_TOOLS``), so the run
        provably cannot mutate the tree even if the model attempts a write — making
        worktree isolation unnecessary here. (A future read role that needs a
        write-capable tool would revisit this; tracked as a follow-up risk.)

        Dirty-tree safety is owned by the runtime, not here: ``execute_work``
        detects the read-only role and both bypasses the dirty-tree guard (#149)
        AND skips the write handoff, so an explore/review runs even with operator
        WIP present and never sweeps it (the handoff's ``git add -u`` would
        otherwise commit the WIP onto ``colleague/<id>`` and restore HEAD over it —
        silent data loss; Qodo, PR #245). So we forward ``self.allow_dirty``
        unchanged (via ``_dispatch_work``) — the read-only role is what makes it
        moot. ``open_pr=False`` keeps the push/PR off regardless."""
        # The cast is purely for the static analyser: Sonar models replace()'s
        # return as a generic DataclassInstance, not EngineConfig, which trips S5655
        # at the _dispatch_work call below (same cast in colleague/subagents.py).
        config = cast(EngineConfig, replace(self.config, role=role))
        task = Task.new(
            str(self.repo),
            task_text if task_text is not None else request,
            engine=self.engine_name,
        )
        result = self._dispatch_work(
            task, open_pr=False, config=config, command_name=None, mode=mode
        )
        if result is None:
            return
        self._log(f"{result.status}: {result.summary}")
        self._refresh_context()


# ---------------------------------------------------------------------------
# Slash-command tables
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SlashSpec:
    """One slash command: its name, an optional arg hint, a one-line help, the
    intent ``group`` it belongs to (``controls`` / ``inspect`` / ``session``) so
    ``/help`` and the popup can present a grouped tree, and ``tags`` — small
    capability/risk badges (``read-only`` / ``writes`` / ``git`` / ``pr`` …,
    issue #160) shown next to the command."""

    name: str
    arg_hint: str
    description: str
    group: str = "session"
    tags: tuple[str, ...] = ()


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
        "controls",
        ("model", "config"),
    ),
    SlashSpec("model", "<name>", "switch the model", "controls", ("model", "config")),
    SlashSpec(
        "mode",
        "[name]",
        "show/cycle the session mode (auto|work|plan|explore|review) — shift-tab equivalent",
        "controls",
        ("interactive",),
    ),
    SlashSpec("base", "<branch>", "set the PR base branch", "controls", ("git", "config")),
    SlashSpec(
        "pr",
        "",
        "toggle push + open PR on each work item",
        "controls",
        ("git", "pr", "writes", "human-loop"),
    ),
    SlashSpec(
        "attach",
        "[path]",
        "stage a media attachment for the next work line (no arg lists staged)",
        "controls",
        ("media", "config"),
    ),
    SlashSpec(
        "learn-from",
        "<source> [name…]",
        "learn skills from a peer (e.g. claude) into .colleague/skills/",
        "controls",
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
    for key, title in SLASH_GROUPS:
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
    for key, title in SLASH_GROUPS:
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
    for key, title in SLASH_GROUPS:
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


def _act_engine(s: "_Session", rest: list[str]) -> str:
    if not rest:
        raise ValueError("usage: /engine <name>")
    name = rest[0]
    if name not in registry.names():
        raise ValueError(
            f"unknown engine '{name}'; available: {', '.join(registry.names()) or '(none)'}"
        )
    s.engine_name = name
    return f"engine → {name}"


def _act_model(s: "_Session", rest: list[str]) -> str:
    if not rest:
        raise ValueError("usage: /model <name>")
    s.config.model = rest[0]
    return f"model → {rest[0]}"


def _act_mode(s: "_Session", rest: list[str]) -> str:
    """``/mode`` — the keyboard-free shift-tab. No arg cycles to the next mode;
    ``/mode <name>`` sets it explicitly; an unknown name raises ``ValueError``
    (surfaced by the slash dispatcher as an error + the valid-modes hint), leaving
    the mode unchanged (``resolve_mode`` raises before the assignment)."""
    # Single return (resolve_mode still raises before the assignment on a bad
    # name, so the mode is left unchanged): the prior two-branch form returned the
    # syntactically identical f-string from both arms, which Sonar reads as S3516
    # "always returns the same value".
    s.mode = next_mode(s.mode) if not rest else resolve_mode(rest[0])
    return f"mode → {s.mode}"


def _act_base(s: "_Session", rest: list[str]) -> str:
    if not rest:
        raise ValueError("usage: /base <branch>")
    s.base = rest[0]
    return f"base branch → {rest[0]}"


def _act_pr(s: "_Session", rest: list[str]) -> str:
    s.open_pr = not s.open_pr
    return f"push + PR on each work item → {'on' if s.open_pr else 'off'}"


def _act_attach(s: "_Session", rest: list[str]) -> str:
    """``/attach <path>`` validates *path* (:func:`colleague.media.validate_attachment`)
    and stages it for the NEXT work line — repeatable, staged in order, one-shot
    (task t11: the following work item's ``Task.attachments`` clears the staging
    list). ``/attach`` with no argument lists what is currently staged, or reports
    none staged — a read, not a mutation, so it never (re)raises.

    A validation failure (missing file / unknown extension) raises ``ValueError``,
    which the ``_slash`` dispatcher reports via the session's normal error style
    (``_error``) and stages nothing — mirroring every other ``_CONFIG_ACTIONS``
    usage error.
    """
    if not rest:
        if not s._staged_attachments:
            return "no attachments staged"
        listed = ", ".join(a["path"] for a in s._staged_attachments)
        return f"staged attachments ({len(s._staged_attachments)}): {listed}"
    attachment = validate_attachment(rest[0])  # raises ValueError -> caught by _slash
    s._staged_attachments.append(attachment)
    return (
        f"attached: {attachment['path']} ({attachment['media_type']}) "
        "— staged for the next work line"
    )


def _act_learn_from(s: "_Session", rest: list[str]) -> str:
    """Learn skills from a peer in-session via the real ``learn-from`` verb.

    Always runs the deterministic stage-1 copy (``--copy-only``) so an
    interactive invocation never blocks on a model call; the full LLM adapt pass
    is left to ``colleague learn-from`` / a work item. Source defaults to
    ``claude``; extra tokens (skill names, ``--dry-run``) pass straight through.
    """
    rest = list(rest)
    if not rest or rest[0].startswith("-"):
        rest = ["claude", *rest]
    return s._run_cli("learn-from", *rest, "--repo", str(s.repo), "--copy-only")


# Live config actions: map a verb to a mutating handler returning a confirmation.
_CONFIG_ACTIONS: dict[str, Callable[["_Session", list[str]], str]] = {
    "engine": _act_engine,
    "model": _act_model,
    "mode": _act_mode,
    "base": _act_base,
    "pr": _act_pr,
    "attach": _act_attach,
    "learn-from": _act_learn_from,
}


def _resolve_view(args: argparse.Namespace, *, color: bool) -> str:
    """Pick the render tier.

    ``--json`` renders the static Markdown cockpit as chrome (to stderr; stdout
    stays pure result JSON). Otherwise ``--tui``/``--no-tui`` force the dynamic
    ANSI vs. static Markdown view, defaulting to ANSI only on a colour TTY.
    """
    if bool(getattr(args, "json", False)):
        return "markdown"
    tui = getattr(args, "tui", None)
    if tui is False:
        return "markdown"
    if tui is True:
        return "ansi"
    return "ansi" if color else "markdown"


def run_session(
    args: argparse.Namespace,
    *,
    input_fn: Optional[Iterator[str]] = None,
    out: Callable[..., None] = print,
    err: Optional[Callable[..., None]] = None,
    _work_fn: _WorkFn = _default_work,
    _plan_fn: _PlanFn = _default_plan,
    _color: Optional[bool] = None,
) -> int:
    """Run the interactive cockpit session loop.

    Output contract: outside ``--json`` the rendered cockpit goes to ``out``
    (stdout) — an ANSI frame or Markdown menus per the resolved tier. In
    ``--json`` mode the cockpit renders as chrome to ``err`` (stderr) and ``out``
    (stdout) carries only each completed work item's ``TaskResult`` as JSON (one
    object per work item, preserving the machine contract). The banner, diagnostics,
    and the closing notice always go to ``err`` (stderr). Always returns ``0``
    (clean exit on quit/EOF).

    The ``input_fn`` / ``out`` / ``err`` / ``_work_fn`` seams are for tests;
    ``_color`` overrides the colour-TTY detection that picks ANSI vs. Markdown.
    """
    repo = Path(args.repo).expanduser()
    # Agent-native default (#234): the session runs on colleague's OWN served
    # backend by default (explicit --engine > COLLEAGUE_SESSION_ENGINE >
    # COLLEAGUE_ENGINE > vllm-openai) — the prior backend stays selectable.
    engine_name = resolve_session_engine(args.engine)
    open_pr = bool(getattr(args, "pr", False))
    allow_dirty = bool(getattr(args, "allow_dirty", False))
    base = args.base
    json_mode = bool(getattr(args, "json", False))
    if err is None:
        err = _eprint

    config = EngineConfig.resolve(
        base_url=getattr(args, "base_url", None),
        model=getattr(args, "model", None),
        api_key=getattr(args, "api_key", None),
        max_steps=getattr(args, "max_steps", None),
        repo_path=repo,
    )

    color = _color if _color is not None else should_color(sys.stdout)
    view = _resolve_view(args, color=color)

    session = _Session(
        repo=repo,
        engine_name=engine_name,
        open_pr=open_pr,
        allow_dirty=allow_dirty,
        base=base,
        config=config,
        json_mode=json_mode,
        view=view,
        out=out,
        err=err,
        work_fn=_work_fn,
        plan_fn=_plan_fn,
        cortex_only=bool(getattr(args, "cortex_only", False)),
        debug_senses=bool(getattr(args, "debug_senses", False)),
    )
    return session.run(input_fn)


def cmd_session(args: argparse.Namespace) -> int:
    """Handler for the ``colleague session`` verb."""
    return run_session(args)


_SESSION_HELP = (
    "Agent-native interactive cockpit: type a free-text goal and it routes "
    "to work or plan on colleague's own backend — no subcommand needed."
)
_SESSION_DESCRIPTION = (
    "Open the interactive cockpit — the conversational, agent-native entry "
    "point to colleague.  Type a free-text goal and intent routing maps it "
    "to 'work' (the default) or 'plan' automatically; a '→ work:' / '→ plan:' "
    "line confirms the dispatch.  A number or template name runs a work template "
    "directly (never re-classified).  A line starting with '/' is a slash command "
    "(introspection + live config).  The session runs on colleague's OWN served "
    "backend by default (--engine > COLLEAGUE_SESSION_ENGINE > COLLEAGUE_ENGINE > "
    "vllm-openai).  Commit-local by default; /pr or --pr opts into push+PR."
)


def _configure_session_parser(p: argparse.ArgumentParser) -> None:
    """Add ``session``'s flags to an already-created parser.

    Shared by the legacy :func:`register` and the agentfront host-command
    ``configure`` hook (:func:`register_into`). ``session`` is a host command
    (an interactive raw-mode cockpit agentfront's rendered tools can't express);
    this builds an identical flag surface for both doors. The long ``--help``
    description is set on *p* directly so the host-command path (whose
    ``add_parser`` takes only ``help=``) keeps it too. ``func`` is left for the
    caller / agentfront to set to :func:`cmd_session`.
    """
    p.description = _SESSION_DESCRIPTION
    p.add_argument("--repo", default=".", help="Path to the target repository (default: cwd).")
    p.add_argument(
        "--engine",
        default=None,
        help=(
            "Backend plugin to use.  Precedence: explicit --engine > "
            "COLLEAGUE_SESSION_ENGINE (session-only override) > COLLEAGUE_ENGINE > "
            "vllm-openai (colleague's own served backend)."
        ),
    )
    p.add_argument(
        "--pr",
        action="store_true",
        help="Push and open a PR after each work item (default: commit locally only, no PR).",
    )
    p.add_argument(
        "--allow-dirty",
        action="store_true",
        help=(
            "Run work items even when the working tree has uncommitted tracked "
            "changes (they get committed onto the work branch). Default: refuse, "
            "to protect in-progress work (#149)."
        ),
    )
    p.add_argument("--base", default="main", help="Base branch for the PR (default: main).")
    p.add_argument(
        "--cortex-only",
        action="store_true",
        help=(
            "Bypass the senses front door for this session: run cortex-only (no "
            "senses intake or speak-back shaping, no media bridge). The artifact "
            "records mode=cortex-only. Byte-identical when no senses model is "
            "resolved. (cortex/senses arc)"
        ),
    )
    p.add_argument(
        "--debug-senses",
        action="store_true",
        help="Print the senses ContextPacket to stderr after each intake (cortex/senses arc).",
    )
    p.add_argument("--base-url", default=None, help="Override the engine base URL.")
    p.add_argument("--model", default=None, help="Override the engine model name.")
    p.add_argument("--api-key", default=None, help="Override the engine API key.")
    p.add_argument("--max-steps", type=int, default=None, help="Override the loop step budget.")
    p.add_argument(
        "--tui",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Render the dynamic ANSI cockpit (default: auto — on a colour TTY). "
            "Use --no-tui for the static Markdown view."
        ),
    )
    p.add_argument(
        "--json",
        action="store_true",
        help=(
            "Emit one JSON TaskResult per work item to stdout; render the cockpit as "
            "chrome to stderr. (The TAUI JSON mirror lives under 'tui state'.)"
        ),
    )


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("session", help=_SESSION_HELP)
    _configure_session_parser(p)
    p.set_defaults(func=cmd_session)


def register_into(app) -> None:
    """Register ``session`` as an agentfront host command.

    The interactive cockpit is a raw-mode TTY loop (per-keystroke reader, live
    ANSI redraw, a slash-autocomplete popup) — a surface agentfront's rendered
    tools (a single return value emitted once) structurally cannot express. It is
    the spec's intended carve-out: a host-owned launcher registered on the App so
    it appears in the one CLI alongside the rendered verbs, reusing
    :func:`cmd_session`'s ``(args) -> int`` handler verbatim.
    """
    app.add_command("session", cmd_session, help=_SESSION_HELP, configure=_configure_session_parser)
