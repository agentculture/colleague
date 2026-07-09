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
import select
import sys
import time
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
from agentfront.taui.widgets.slash_autocomplete import GROUP_ICON, format_tags

from colleague import cockpit, feedback, flight, handoff, icons, layers, registry
from colleague.artifact import artifact_dir
from colleague.artifact import write as _write_artifact
from colleague.attribution import cortex_working_line, senses_line
from colleague.cli._banner import emit_banner
from colleague.cli._commands._session_input import CYCLE_MODE
from colleague.cli._commands._tui_sink import fold_phase
from colleague.cli._commands.work import execute_work as _default_work
from colleague.cli._errors import CliError
from colleague.cockpit_run import RunState, fold, observed_ledger, reconcile, status_line
from colleague.commands import CommandError, discover_commands, expand_command, load_command
from colleague.config import EngineConfig, resolve_presence_rung, resolve_session_engine
from colleague.contract import SensesBlock, SensesRecord, Task, TaskResult
from colleague.frontdoor import CORTEX, classify_frontdoor, cortex_frontdoor_outcome, run_frontdoor
from colleague.media import validate_attachment
from colleague.policy import load_policy
from colleague.presence import (
    cadence_from_env,
    clarify_from_env,
    is_go_word,
    should_clarify,
    should_update,
)
from colleague.presence_engine import PresenceEngine, PresenceIO, build_presence_executor
from colleague.senses import (
    UPDATE_POINT,
    run_senses_intake,
    run_senses_speakback,
    run_senses_talk,
    run_senses_update,
    senses_engine_config,
)
from colleague.senses_loop import SensesLoopDriver
from colleague.session_intent import PLAN, classify_intent
from colleague.session_modes import (
    DEFAULT_MODE,
    ModeFacts,
    mode_affordance_line,
    mode_facts,
    mode_facts_fragment,
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

#: The FIXED dispatch notice the middle-manager lane speaks when intake carries
#: no usable ack (talking-to-one arc, t6 / h2): it acknowledges receipt and the
#: hand-off to cortex ONLY — never a fabricated understanding of the request.
_ACK_DISPATCH_NOTICE = "taking your request to cortex now."

#: The Session panel's goal item id (spec R3 / plan t9 / #256) — the running
#: work item's instruction, so the operator always sees WHAT is being driven.
_GOAL_ITEM_ID = "session.goal"
#: Goal line truncation — a first-line, at-a-glance hint, not the full instruction.
_GOAL_MAX_CHARS = 80

#: Capacity panel item ids (spec R3 / plan t9 / #256).
_CAPACITY_PANEL_ID = "capacity"
_CAPACITY_BUDGET_ID = "cap.budget"
#: The disambiguated behavior+source fact (#285 t6) — distinct from the
#: execution-profile row below; together with it these replace the old single
#: conflated "mode — steps≤N · timeout…" line.
_CAPACITY_MODE_ID = "cap.mode"
_CAPACITY_PROFILE_ID = "cap.mode_profile"
_CAPACITY_SIGNAL_ID = "cap.signal"

#: The Next panel (#285 t6) — the safest-next-move promoted from a status-text
#: line buried in the Session panel's ``content_summary`` into a first-class
#: panel + item, so every render tier (flat ANSI, Markdown, TAUI mirror) shows
#: it as a distinct fact rather than prose.
_NEXT_PANEL_ID = "next"
_NEXT_ITEM_ID = "next.action"

#: The running-state panels (#285 t7). ``active_run`` replaces the idle Next
#: block while a work item runs (goal · changes-so-far · last action, live from
#: the sink's fold events); ``last_run`` is the post-run mutation ledger
#: reconciled from ``TaskResult.stats`` + handoff, shown on the restored idle
#: layout (cumulative session totals are parked as a follow-up — spec v4).
_ACTIVE_RUN_PANEL_ID = "active_run"
_LAST_RUN_PANEL_ID = "last_run"


def _goal_text(instruction: str) -> str:
    """The goal line: *instruction*'s first line, truncated to ``_GOAL_MAX_CHARS``.

    Returns ``""`` for blank/whitespace-only instructions (e.g. a synthetic plan
    task) so the caller can treat an empty result as "no goal to show".
    """
    first_line = instruction.strip().splitlines()[0] if instruction.strip() else ""
    if len(first_line) > _GOAL_MAX_CHARS:
        return first_line[: _GOAL_MAX_CHARS - 1].rstrip() + "…"
    return first_line


def _mode_status_text(facts: ModeFacts) -> str:
    """One-line disambiguated 'behavior (source)' fact (#285 t6) — e.g.
    ``explore (pinned)`` or ``auto→work (auto)`` — kept separate from the
    execution-profile text below so an operator can tell WHICH behavior is
    active from WHETHER it was auto-classified or pinned, without either fact
    being blurred into the other."""
    if facts.resolved_from:
        return f"{facts.behavior}→{facts.resolved_from} ({facts.source})"
    return f"{facts.behavior} ({facts.source})"


def _mode_profile_text(facts: ModeFacts) -> str:
    """One-line execution-profile fact (steps/timeout/budget/fill-line/
    synthesis-reserve), or an honest 'no fixed profile' note when the mode has
    none (``auto`` with no sample input) — never a crash or a stale-looking
    blank row."""
    if not facts.profile_rows:
        return "no fixed profile (resolves per input)"
    return " · ".join(f"{label} {value}" for label, value in facts.profile_rows)


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
        # The pure run-state (#285 t7): real steps are folded into it (activity
        # ledger + last action) so the running status line and the Active-run
        # panel derive from the shared `colleague.cockpit_run` helpers, never a
        # second fold implementation. `_started` is the event-stamp anchor —
        # elapsed is computed at each sink boundary (no clock thread; the UI
        # thread blocks inside the completion), keeping the #285 "no ticking
        # clock" decision.
        self._run = RunState()
        self._started = time.monotonic()

    def __call__(self, step_index: int, tool: str, target: str, ok: bool) -> None:
        sess = self._session
        # Concurrent talk lane (t7): at EVERY sink boundary — a real step OR a
        # phase notice (thinking…/synthesizing…) — poll stdin non-blockingly so an
        # operator message is picked up promptly even mid-completion. A strict
        # no-op unless the lane is armed (off-TTY / no senses → never polls).
        # ``getattr`` keeps the sink usable against a bare state-holder in tests
        # (its documented contract) — a holder without the lane simply never polls.
        poll = getattr(sess, "_poll_talk_lane", None)
        if poll is not None:
            poll()
        # Middle-manager proactive narration (talking-to-one arc, t6): the SAME
        # existing sink boundary the talk lane polls at — cadence-gated in the
        # session helper, a strict no-op unless the lane is armed. ``getattr``
        # keeps the sink usable against a bare state-holder (its documented
        # contract), like the poll guard above.
        update = getattr(sess, "_maybe_proactive_update", None)
        if update is not None:
            update(tool, target)
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
        # Fold the step through the reducer — it advances ``work_item.step_count``,
        # appends the ``[tool] target`` line to ``state.conversation`` with the #233
        # ×N collapse, and opens the same error popup as `tui replay` on a failed
        # step (composed around, never re-implemented). The tool feed STAYS in the
        # conversation — that IS the #233 legible action feed; removing it would
        # regress that shipped feature (#285 t7 decision). The "separate blocks" the
        # spec asks for is delivered by the STRUCTURED Active-run ledger panel (goal
        # · changes-so-far · last action), folded below and rendered as its own
        # distinct block — a summary alongside the feed, not a second copy of it.
        sess.state = reduce(sess.state, work_step(tool, target, ok))
        # Fold the real step into the shared run-state and compose the live
        # status line ``phase · step N/max · current op · elapsed`` from it.
        self._run = fold(self._run, tool, target, ok)
        step = (
            sess.state.work_item.step_count
            if sess.state.work_item is not None
            else self._run.step_count
        )
        max_steps = getattr(getattr(sess, "config", None), "max_steps", None)
        line = status_line(
            self._run,
            step=step,
            max_steps=max_steps,
            elapsed_seconds=time.monotonic() - self._started,
            phase="",  # a real step replaces any phase text — no phase segment here
        )
        sess.state = replace(sess.state, status=Status(severity="info", message=line))
        # Update the live Active-run panel (goal · changes-so-far · last action)
        # if the holder is a full session — guarded so the sink stays usable
        # against the bare state-holder used in unit tests (its documented
        # contract), exactly like the `_poll_talk_lane` guard above.
        update_run = getattr(sess, "_update_active_run", None)
        if update_run is not None:
            update_run(self._run)
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


@dataclass(frozen=True)
class SessionIO:
    """The session's output sinks, bundled to hold ``_Session.__init__`` under
    the SonarCloud S107 parameter ceiling (13).

    ``out`` is the interactive cockpit's normal-path sink (stdout, or stderr
    under ``--json`` so stdout carries only each completed work item's
    ``TaskResult``); ``err`` is the diagnostic sink (always stderr). Frozen —
    a session's sinks are fixed for its lifetime (though the resulting
    ``_Session.out``/``.err`` instance attributes MAY still be reassigned
    directly post-construction, as some tests do).
    """

    out: Callable[..., None]
    err: Callable[..., None]


@dataclass(frozen=True)
class SensesSessionOptions:
    """Senses-session options (cortex/senses arc, task t8), bundled to hold
    ``_Session.__init__`` under the SonarCloud S107 parameter ceiling (13).

    ``cortex_only`` bypasses the senses front door for the whole session;
    ``debug_senses`` echoes the perceived packet to stderr. Both default off —
    with no senses model resolved the session is byte-identical either way.
    """

    cortex_only: bool = False
    debug_senses: bool = False


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
        io: SessionIO,
        work_fn: _WorkFn,
        view: str,
        allow_dirty: bool = False,
        plan_fn: _PlanFn = _default_plan,
        user_home: Optional[Path] = None,
        senses_options: Optional[SensesSessionOptions] = None,
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
        opts = senses_options if senses_options is not None else SensesSessionOptions()
        self.cortex_only = opts.cortex_only
        self.debug_senses = opts.debug_senses
        # Session mode — auto|work|plan|explore|review — cycled by shift-tab (live
        # ANSI) or the keyboard-free /mode slash. 'auto' is byte-identical to the
        # pre-mode behaviour (free text is classified per input); a pinned mode
        # overrides the classifier. Mutated only via _cycle_mode / _act_mode.
        self.mode = DEFAULT_MODE
        self.json_mode = json_mode
        self.view = view  # "ansi" (dynamic) | "markdown" (static)
        self.out = io.out
        self.err = io.err
        # The rendered cockpit is interactive chrome: stdout normally, but stderr
        # in --json mode so stdout carries only the work TaskResult(s).
        self.chrome = self.err if json_mode else self.out
        self.work_fn = work_fn
        self.plan_fn = plan_fn
        # The latest fill-line/backpressure signal a completed work item surfaced
        # on `TaskResult.capacity_warning` (spec R3 / plan t9 / #256), or `None`
        # before any work item has run. Read by `_capacity_panel`; set in
        # `_dispatch_work` right after a result is obtained, before the caller's
        # `_refresh_context()` rebuilds the panel — never on the render path.
        self._last_capacity_warning: Optional[str] = None
        # The running work item's goal, event-stamped at `_arm_run_view` and shown
        # in the Active-run panel while a work item runs (#285 t7); "" at idle.
        self._active_goal: str = ""
        # Media attachments staged by `/attach` (task t11), in staged order —
        # consumed (and cleared, one-shot) the next time a work line builds a
        # Task in `_work_line`. Empty by default, so a session that never
        # attaches anything is byte-identical to today.
        self._staged_attachments: list[dict] = []

        # Concurrent senses talk lane (senses live-presence arc, task t7): while a
        # work line runs, the operator can chat with senses at each progress-sink
        # boundary (thread-free stdin poll — see `_poll_talk_lane`). These hold the
        # running work item's id + intake packet while the lane is armed; all None
        # when no work line is running or the lane is disabled (off-TTY / no senses /
        # --cortex-only → byte-identical to today, no poll, no flight arming).
        self._talk_active = False
        self._talk_task_id: Optional[str] = None
        self._talk_packet = None

        # Middle-manager presence lane (talking-to-one arc, t6): the session-side
        # record of this work line's ack/update exchanges (folded onto
        # ``TaskResult.senses`` at finalize) plus the proactive-update cadence
        # state (colleague.presence — clock-free, env-tunable, capped per run).
        # All reset per work line by ``_reset_presence_lane``; when the lane never
        # arms (off-TTY / --no-tui / piped / --cortex-only / no senses) nothing
        # here is ever written, so those paths stay byte-identical (h9).
        self._senses_chat: list[dict] = []
        # Front-door decision record (cortex-route path) folded onto TaskResult.senses
        # by _finalize_split_run; reset per work line in _work_line (NOT in
        # _reset_presence_lane, which runs AFTER the front door sets it).
        self._frontdoor_record: Optional[SensesRecord] = None
        self._update_records: list[SensesRecord] = []
        # The senses agentic loop (presence-default-everywhere arc, t7): built per
        # work line when the presence rung resolves to ``loop`` and the live talk
        # lane arms (an interactive TTY). Live operator talk then rides the loop —
        # senses drives the conversation as an agent — while ack + proactive
        # updates stay on the (live-proven) fixed-beat methods below, which now
        # also fire off-TTY (the c19 pin-break). ``None`` for the beats/off rung
        # and every unarmed surface → byte-identical.
        self._presence_engine: Optional[PresenceEngine] = None
        self._update_cadence = cadence_from_env(os.environ)
        self._updates_sent = 0
        self._update_last_step = 0
        self._update_last_phase = ""
        self._update_cap_recorded = False
        # Clarify-first + conversation continuity (t7): the SESSION-lifetime
        # rolling operator↔senses history (c11 — threaded into every senses
        # call, windowed senses-side at call time, t4; appends gated on the
        # presence lane so an unarmed session never accumulates history), the
        # per-work-line clarify re-intake records, the clarify policy, and the
        # input seam the clarify loop pulls the operator's answer from (set by
        # ``run()``; ``None`` — e.g. under direct construction in tests —
        # dispatches immediately, clarify never fires).
        self._history: list[dict] = []
        self._clarify_records: list[SensesRecord] = []
        self._clarify_policy = clarify_from_env(os.environ)
        self._read_next: Optional[Callable[[], object]] = None

        # ``user_home`` overrides the home dir command discovery scans (default
        # ``Path.home()``). Real sessions leave it ``None`` (scan the user's home);
        # hermetic callers (e.g. tools.tui_sim) pin it so personal
        # ``~/.colleague/commands`` can't leak into a reproducible run.
        self.discovered = discover_commands(repo, user_home=user_home)
        self.palette: list[tuple[str, str]] = [
            (name, load_command(self.discovered[name]).description)
            for name in sorted(self.discovered)
        ]
        # Icon vocabulary (#285 t6): resolved once (repo/env/config precedence,
        # colleague.icons.resolve_icons) rather than per-frame, since it can only
        # change via a repo config edit + a fresh session. Applied to every
        # colleague-composed panel label via `icons.label`; a bare `"none"` mode
        # degrades every such label to plain text with no glyph.
        self._icons_mode = icons.resolve_icons(repo_path=repo)
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
                # Next is the cockpit's "what do I do now?" answer — placed first
                # so it reads before the facts that justify it (#285 t6).
                self._next_panel(facts),
                self._policy_panel(facts),
                self._context_panel(facts),
                self._capacity_panel(),
                Panel(id="commands", title="suggested work", visible=True, items=items),
                Panel(
                    id=_CONVERSATION_PANEL_ID,
                    title="Session",
                    visible=True,
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
        """``(state text, consequence text, gated?)`` for the run_command
        capability — the ``label · state · consequence`` grammar (#285 t6).

        Honest labels mirror :meth:`~colleague.policy.Policy.check_run_command`:
        an allow-list only gates when non-empty; an empty allow-list with a
        deny-list is deny-only (all others allowed); both empty is effectively
        ungated. Both lists are coerced so a malformed ``approvals.json`` can't
        crash render. The consequence text names only what the harness actually
        enforces — never a "requires confirmation" claim the harness doesn't
        make, and never "sandboxed"."""
        if runcfg is None:
            return "ungated (any command)", "any shell command runs", False
        allow = _coerce_strs(runcfg.get("allow"))
        deny = _coerce_strs(runcfg.get("deny"))
        if allow:
            shown = ", ".join(allow[:3]) + ("…" if len(allow) > 3 else "")
            return f"allow-list: {shown}", "only listed programs run", True
        if deny:
            shown = ", ".join(deny[:3]) + ("…" if len(deny) > 3 else "")
            return (
                f"deny-list: {shown} (all others allowed)",
                "listed programs are blocked; all others run",
                True,
            )
        return "present, no rules (effectively ungated)", "any shell command runs", False

    def _policy_panel(self, facts: dict) -> Panel:
        """The *Run policy* panel — the safety surface (AC #3), restructured as
        an aligned ``label · state · consequence`` grammar (#285 t6): each item
        names a capability, its current state, and the real consequence of that
        state. Honest labels only: the loop can write any repo file and run any
        command unless ``run_command`` is gated; the only real outward gate is
        push/PR (plus the checksum/token approvals gate when configured). No
        "requires confirmation" boundary is claimed — the harness enforces none
        — and the tool is never described as sandboxed."""
        run_state, run_consequence, gated = self._run_command_status(facts["runcfg"])
        run_label = icons.label("run_command", "ok" if gated else "warn", self._icons_mode)

        edits_state = "read + write within repo"
        if facts["hooks_gated"]:
            edits_state += " · hooks/commands checksum-gated"
        edits_consequence = "the loop can create/modify any repo file"

        if self.open_pr:
            handoff_state = "on"
            handoff_consequence = f"pushes a branch + opens a PR onto '{self.base}'"
            handoff_key = "run"
        else:
            handoff_state = "off"
            handoff_consequence = "commits locally only — nothing leaves this machine"
            handoff_key = "idle"
        handoff_label = icons.label("push + PR", handoff_key, self._icons_mode)

        summary = (
            f"run_command: {'gated' if gated else 'ungated'} · "
            f"edits: repo-local · push/PR: {'on' if self.open_pr else 'off'}"
        )
        return Panel(
            id="policy",
            title=icons.label("Run policy", "policy", self._icons_mode),
            visible=True,
            content_summary=summary,
            items=[
                PanelItem(
                    id="pol.run_command",
                    label=run_label,
                    status=f"{run_state} · {run_consequence}",
                ),
                PanelItem(
                    id="pol.files",
                    label="file edits",
                    status=f"{edits_state} · {edits_consequence}",
                ),
                PanelItem(
                    id="pol.handoff",
                    label=handoff_label,
                    status=f"{handoff_state} · {handoff_consequence}",
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
            title=icons.label("Context", "context", self._icons_mode),
            visible=True,
            content_summary=summary,
            items=[
                PanelItem(id="ctx.repo", label="repo", status=facts["ident"]),
                PanelItem(id="ctx.branch", label="branch", status=facts["branch"]),
                PanelItem(id="ctx.tree", label="working tree", status=tree_status),
                PanelItem(id="ctx.agents", label="AGENTS layers", status=agents_status),
                PanelItem(id="ctx.skills", label="skills", status=skills_status),
                PanelItem(
                    id="ctx.telemetry",
                    label="telemetry",
                    status="on" if facts["telemetry"] else "off",
                ),
                PanelItem(id="ctx.feedback", label="/feedback", status=fb_status),
            ],
        )

    def _capacity_panel(self) -> Panel:
        """The *Capacity* panel (spec R3 / plan t9 / #256; disambiguated #285
        t6): context budget, the THREE distinct mode facts — behavior (which
        mode), source (auto-classified vs pinned), and execution profile
        (steps/timeout/budget/fill-line) — and the latest fill-line /
        backpressure signal a completed work item surfaced. Built from cheap
        in-memory state only (``self.config`` / ``self.mode`` /
        ``self._last_capacity_warning``) — no I/O, so it renders across every
        tier via the generic panel walk (Markdown + TAUI JSON) with no
        per-renderer code, exactly like Policy/Context. No agentfront schema
        change: this rides the existing ``Panel``/``PanelItem`` shape (the
        TAUIState `capacity` block itself is the separate, agentfront-side
        upstream ask, agentfront#48 — out of scope here).

        The mode facts were previously blurred into one ``_mode_profile_status``
        line naming the mode AND its profile together; ``colleague.session_modes
        .mode_facts``/``mode_facts_fragment`` now separate behavior/source from
        the execution profile so an operator can tell each fact apart — a
        dedicated ``cap.mode`` item carries behavior+source, ``cap.mode_profile``
        carries the execution profile alone."""
        tokens = self.config.context_budget_tokens
        facts = mode_facts(self.mode)
        # A genuine capacity warning gets the warn glyph; the neutral "nothing
        # has happened yet" state must not look like a warning (#285 t6) — no
        # glyph at all for the neutral case, reserving the warning glyph for a
        # real fill-line/backpressure signal.
        has_warning = bool(self._last_capacity_warning)
        signal = self._last_capacity_warning or "none yet"
        signal_label = "capacity signal"
        if has_warning:
            signal_label = icons.label(signal_label, "warn", self._icons_mode)
        return Panel(
            id=_CAPACITY_PANEL_ID,
            title=icons.label("Capacity", "capacity", self._icons_mode),
            visible=True,
            content_summary=f"budget {tokens:,} tokens · {mode_facts_fragment(facts)}",
            items=[
                PanelItem(
                    id=_CAPACITY_BUDGET_ID,
                    label="context budget",
                    status=f"{tokens:,} tokens",
                ),
                PanelItem(
                    id=_CAPACITY_MODE_ID,
                    label=icons.label("mode", "mode", self._icons_mode),
                    status=_mode_status_text(facts),
                ),
                PanelItem(
                    id=_CAPACITY_PROFILE_ID,
                    label="execution profile",
                    status=_mode_profile_text(facts),
                ),
                PanelItem(id=_CAPACITY_SIGNAL_ID, label=signal_label, status=signal),
            ],
        )

    def _suggested_action(self, facts: dict) -> str:
        """The safest/most-useful next move (AC #1) — always answers 'what
        now?'. Returns plain text with no glyph prefix; the caller
        (:meth:`_next_panel`) applies the icons vocabulary so a genuine caution
        (a dirty tree) reads distinctly from the routine case, without a
        hardcoded emoji baked into the message itself."""
        if facts["dirty"] and not self.allow_dirty:
            return (
                "Safest next: commit or stash first (working tree is dirty), then "
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

    def _next_panel(self, facts: dict) -> Panel:
        """The *Next* panel (#285 t6) — the safest/most-useful next move
        (AC #1), promoted from a status-text line buried in the Session
        panel's ``content_summary`` into a first-class panel + item, so every
        render tier (flat ANSI, Markdown, TAUI mirror) carries it as a
        distinct fact rather than prose. Reuses :meth:`_suggested_action`'s
        dirty/clean/free-text judgment verbatim — only the rendering target
        changed. A dirty-blocked tree earns the warning glyph (a genuine
        caution); every other case gets the neutral 'next' glyph — a warning
        is never shown where none is warranted."""
        text = self._suggested_action(facts)
        dirty_blocked = facts["dirty"] and not self.allow_dirty
        key = "warn" if dirty_blocked else "next"
        return Panel(
            id=_NEXT_PANEL_ID,
            title=icons.label("Next", "next", self._icons_mode),
            visible=True,
            items=[PanelItem(id=_NEXT_ITEM_ID, label=icons.label(text, key, self._icons_mode))],
        )

    def _refresh_context(self) -> None:
        """Rebuild the next + policy + context + capacity panels in place
        (preserving the running conversation + work-templates panels). Called
        after a config change or a completed work item — both can shift
        branch / dirty / policy / feedback / capacity, and the Next panel's
        suggestion depends on dirty-state + push/PR, so it must not go stale
        (the cockpit promises to always answer 'what now?')."""
        facts = self._facts()
        rebuilt = {
            _NEXT_PANEL_ID: self._next_panel(facts),
            "policy": self._policy_panel(facts),
            "context": self._context_panel(facts),
            _CAPACITY_PANEL_ID: self._capacity_panel(),
        }
        self.state = replace(
            self.state,
            panels=[rebuilt.get(p.id, p) for p in self.state.panels],
        )

    def _with_goal(self, goal: str) -> None:
        """Set (or clear, with ``goal=""``) the Session panel's goal item —
        the running work item's instruction, so the operator always sees WHAT
        is being driven (spec R3 / plan t9 / #256). Mutates ``self.state`` via
        the frozen ``dataclasses.replace`` idiom (the same pattern
        ``_refresh_context`` uses to rebuild a panel in place).
        """
        goal_items = [PanelItem(id=_GOAL_ITEM_ID, label="🎯 goal", status=goal)] if goal else []
        self.state = replace(
            self.state,
            panels=[
                cast(Panel, replace(p, items=goal_items)) if p.id == _CONVERSATION_PANEL_ID else p
                for p in self.state.panels
            ],
        )

    # ── running-state view (#285 t7) ─────────────────────────────────────────

    def _active_run_panel(self, run: RunState) -> Panel:
        """The *Active run* panel — replaces the idle Next block while a work
        item runs (#285 t7). Shows the goal, the changes-so-far observed from the
        sink's fold events (files touched · commands run — commits are
        deliberately OMITTED mid-run, resolving parked v3: heuristic git-commit
        detection from sink events is dishonest), and the last action. Built
        purely from the shared ``colleague.cockpit_run`` run-state; no I/O."""
        led = observed_ledger(run)
        changes = f"{led.files_changed} files · {led.commands_run} commands"
        return Panel(
            id=_ACTIVE_RUN_PANEL_ID,
            title=icons.label("Active run", "run", self._icons_mode),
            visible=True,
            content_summary=changes,
            items=[
                PanelItem(
                    id="run.goal",
                    label=icons.label("goal", "mode", self._icons_mode),
                    status=self._active_goal or "(no goal)",
                ),
                PanelItem(
                    id="run.changes",
                    label=icons.label("changes so far", "ledger", self._icons_mode),
                    status=changes,
                ),
                PanelItem(
                    id="run.last",
                    label=icons.label("last action", "activity", self._icons_mode),
                    status=run.last_action or "—",
                ),
            ],
        )

    def _arm_run_view(self, goal: str) -> None:
        """Switch the cockpit to the running layout (#285 t7): collapse the
        'suggested work' templates panel, drop the idle Next block, and insert a
        live Active-run panel. Called by :meth:`_dispatch_work` before the loop
        starts; the sink then rebuilds the Active-run panel per step via
        :meth:`_update_active_run`, and :meth:`_restore_idle_view` puts the idle
        layout back afterwards. Frozen-dataclass ``replace`` idiom throughout."""
        self._active_goal = _goal_text(goal)
        active = self._active_run_panel(RunState())
        panels: list[Panel] = [active]
        for p in self.state.panels:
            if p.id == _NEXT_PANEL_ID:
                continue  # the Active-run panel takes the idle Next block's place
            if p.id == "commands":
                panels.append(cast(Panel, replace(p, visible=False)))  # templates collapse
                continue
            panels.append(p)
        self.state = replace(self.state, panels=panels)

    def _update_active_run(self, run: RunState) -> None:
        """Rebuild the Active-run panel in place from the latest run-state — the
        per-step hook :class:`_WorkSink` calls (guarded, so a bare test holder
        without this method is a no-op). A strict no-op when the panel is absent
        (the run view was never armed)."""
        if not any(p.id == _ACTIVE_RUN_PANEL_ID for p in self.state.panels):
            return
        rebuilt = self._active_run_panel(run)
        self.state = replace(
            self.state,
            panels=[rebuilt if p.id == _ACTIVE_RUN_PANEL_ID else p for p in self.state.panels],
        )

    def _last_run_panel(self, result: TaskResult) -> Panel:
        """The *Last run* mutation ledger (#285 t7) — reconciled from
        ``TaskResult.stats`` + handoff, so it is AUTHORITATIVE (files changed ·
        commands run · commits · publish state), unlike the mid-run observed
        ledger which omits commits. Shown on the restored idle layout so the
        operator always sees what the just-finished work item actually changed
        (cumulative session totals are parked as a follow-up — spec v4)."""
        led = reconcile(result)
        commits = "—" if led.commits is None else str(led.commits)
        return Panel(
            id=_LAST_RUN_PANEL_ID,
            title=icons.label("Last run", "ledger", self._icons_mode),
            visible=True,
            content_summary=(
                f"{led.files_changed} files · {led.commands_run} commands · "
                f"{commits} commits · {led.publish_state}"
            ),
            items=[
                PanelItem(
                    id="last.files",
                    label=icons.label("files changed", "ledger", self._icons_mode),
                    status=str(led.files_changed),
                ),
                PanelItem(
                    id="last.commands",
                    label=icons.label("commands run", "activity", self._icons_mode),
                    status=str(led.commands_run),
                ),
                PanelItem(
                    id="last.commits",
                    label=icons.label("commits", "ok", self._icons_mode),
                    status=commits,
                ),
                PanelItem(
                    id="last.publish",
                    label=icons.label("publish", "run", self._icons_mode),
                    status=led.publish_state or "none",
                ),
            ],
        )

    def _restore_idle_view(self, result: Optional[TaskResult]) -> None:
        """Put the idle layout back after a work item (#285 t7): remove the
        Active-run panel (its slot becomes the Next block again), un-collapse the
        templates panel, and — when a result is available — add/replace the
        Last-run ledger panel. The caller's :meth:`_refresh_context` then
        refreshes Next/policy/context/capacity content; it preserves the
        Last-run panel (not one of the ids it rebuilds), so the record survives
        onto the idle frame."""
        self._active_goal = ""
        facts = self._facts()
        next_panel = self._next_panel(facts)
        last_panel = self._last_run_panel(result) if result is not None else None
        panels: list[Panel] = []
        restored_next = False
        replaced_last = False
        for p in self.state.panels:
            if p.id in (_ACTIVE_RUN_PANEL_ID, _NEXT_PANEL_ID):
                if not restored_next:
                    panels.append(next_panel)  # the idle Next block returns
                    restored_next = True
                continue
            if p.id == "commands":
                panels.append(cast(Panel, replace(p, visible=True)))  # templates re-expand
                continue
            if p.id == _LAST_RUN_PANEL_ID and last_panel is not None:
                panels.append(last_panel)  # replace a prior last-run record in place
                replaced_last = True
                continue
            panels.append(p)
        if not restored_next:
            panels.insert(0, next_panel)
        if last_panel is not None and not replaced_last:
            panels.append(last_panel)
        # Reset the status line back to the idle status — otherwise the last
        # running status line ("step N/max · current op · elapsed") composed by
        # `_WorkSink` would linger on the restored idle frame (Qodo PR #288).
        self.state = replace(self.state, panels=panels, status=self._status())

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
                    matches,
                    selected,
                    width=detect_width(),
                    style=_slash_tag_style(),
                    groups=_SLASH_GROUPS,
                    default_group="session",
                )
                parts.append(popup)
            return "\n".join(parts) + _cursor_back_to_input(popup, prompt, buffer)

        return read_line_with_popup(_SLASH_COMMANDS, _render, filter_slash, fallback=_fallback)

    # ── the loop ─────────────────────────────────────────────────────────────

    def run(self, input_fn: Optional[Iterator[str]]) -> int:
        emit_banner(self.err, json_mode=self.json_mode)
        live_ansi = input_fn is None and self.view == "ansi"
        # The clarify loop's input seam (t7): pull ONE more operator line from
        # the SAME source this loop reads — the live raw reader or the iterator.
        self._read_next = self._read_live_ansi if live_ansi else (lambda: _read_line(input_fn))
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
        self._frontdoor_record = None
        is_free_text = bool(stripped) and not stripped.isdigit() and stripped not in self.discovered
        # Free-text routing — the active mode's verb plus, on the ``work`` verb,
        # the senses front door — lives in _route_free_text. A True return means
        # the line was fully handled there (plan/explore/review dispatched, or a
        # senses-direct answer with NO cortex work item) and this turn is done.
        if is_free_text and self._route_free_text(stripped):
            return
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
        # Cortex/senses (t8): with a senses model resolved, a free-text work line
        # runs senses intake first (perceives the request → ContextPacket on the
        # task) unless --cortex-only. Intake also renders the senses ACK, which must
        # precede the mechanical routing line (ack-first, h2) — so _prepare_senses
        # runs BEFORE the "→ work:" log, not after. classify_intent already picked
        # the VERB above; this only perceives the CONTENT — they compose, never compete.
        senses_mode, intake_record = self._prepare_senses(task, is_free_text)
        if is_free_text:
            self._log(f"→ work: {stripped}")
        # Visible hand-off (c11): when the middle-manager lane is armed, name the
        # mind now taking over so the operator sees cortex pick the work up.
        if is_free_text and self._presence_enabled():
            self._log(cortex_working_line())
        self._run_work(task, command_name, senses_mode=senses_mode, intake_record=intake_record)

    def _route_free_text(self, stripped: str) -> bool:
        """Route a free-text work line, returning True when it was fully handled
        here (caller returns) and False to fall through to work-template selection
        + cortex dispatch.

        The ROUTE is deterministic: ``route_for`` picks the verb (``auto``
        classifies via ``classify_intent``; ``work``/``plan``/``explore``/``review``
        pin it), then — on the ``work`` verb ONLY — the senses front door
        (talking-to-one-teammate) is consulted. A non-repo turn (greeting / question
        about colleague itself) is answered DIRECTLY by senses with NO cortex work
        item (no branch, no eidetic record); a repo-touching turn records the
        cortex-route decision on ``self._frontdoor_record`` and returns False so the
        caller dispatches to cortex exactly as before. The front door is a
        deterministic classifier + at most one tools-off senses completion.
        """
        verb = route_for(self.mode, stripped, classify_intent)
        if verb == PLAN:
            self._log(f"→ plan: {stripped}")
            self._run_plan(stripped)
            return True
        if verb == "explore":
            self._log(f"→ explore: {stripped}")
            self._run_explore(stripped)
            return True
        if verb == "review":
            self._log(f"→ review: {stripped}")
            self._run_review(stripped)
            return True
        outcome = self._run_frontdoor(stripped)
        if outcome is not None and outcome.answered_directly:
            self._render_senses_direct(stripped, outcome)
            return True
        if outcome is not None:
            self._frontdoor_record = outcome.record
        return False

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
        ``execute_work`` — the same code path the ``work --mode`` flag uses.

        The cockpit visibly changes state for the duration (#285 t7): the run
        view is armed before the loop (templates collapse, a live Active-run
        panel appears) and the idle layout is restored afterwards with a
        Last-run ledger — on the success AND the error path, so the cockpit
        never strands the operator in a half-running frame."""
        # #307 / decision c18: the session arms the file-based flight plane by
        # default (in addition to its in-place stdin talk lane), so a SECOND
        # terminal can `colleague talk` into a running session. Respect the
        # opt-out (COLLEAGUE_WATCH=0 / config.json {watch:false}, resolved onto
        # config.watch); a talk lane that already armed it stays armed. Session
        # runs in-place, so the plane lands in the operator repo (no #310 concern),
        # and execute_work's presence builders are skipped for the session's own
        # progress sink, so this only arms the plane — no doubled narration.
        if not task.watch:
            want = bool(getattr(config, "watch", True))
            # #307 nesting-safety (Qodo #312): degrade to no-watch at the flight
            # depth cap, like colleague work's _arm_watch — a session nested
            # inside a flight must not arm a plane past the cap. (No
            # child_depth_env propagation: the session's subagents run
            # in-process, not as CLI shell-outs, and cumulative env increments
            # across the session's sequential dispatches would wrongly trip the
            # cap.)
            task.watch = want and not flight.depth_exceeded()
        self._arm_run_view(task.instruction)
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
            self._restore_idle_view(None)  # error path — never leave the run view armed
            return None
        result, _artifact = pair
        # The Capacity panel's signal row (spec R3 / plan t9 / #256) surfaces the
        # latest fill-line/backpressure warning; captured here, BEFORE the
        # caller's `_refresh_context()` rebuilds the panel, so it is never stale.
        self._last_capacity_warning = result.capacity_warning
        self._restore_idle_view(result)  # idle layout back + authoritative last-run ledger
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
        self._reset_presence_lane()
        if self.config.senses is None:
            return None, None
        if self.cortex_only or not is_free_text:
            return "cortex-only", None
        pair = self._senses_engine()
        if pair is None:
            return "cortex-only", None
        senses_config, engine = pair
        self._history_append("operator", task.instruction)
        packet, record = run_senses_intake(
            task.instruction, senses_config, engine, history=list(self._history) or None
        )
        if packet is None:
            self._log("senses: intake degraded — using the raw request")
            self._render_ack(None)
        else:
            task.context_packet = packet
            self._log(
                f"senses: perceived {packet.task_type or 'request'} "
                f"(confidence {packet.confidence:.2f})"
            )
            if self.debug_senses:
                self.err(f"[debug-senses] {packet.to_dict()}")
            # Clarify-first (t7): ask BEFORE acknowledging, so the ack speaks
            # from the FINAL (possibly refined) packet at dispatch time.
            packet = self._maybe_clarify(task, packet, senses_config, engine)
            self._render_ack(packet.ack)
        return "split", record

    # ── senses front door (talking-to-one-teammate) ──────────────────────────

    def _run_frontdoor(self, text: str):
        """Consult the senses front door for a free-text work line.

        Returns a :class:`~colleague.frontdoor.FrontDoorOutcome`, or ``None`` when
        the front door is a strict no-op — senses unarmed, ``--cortex-only``, or
        media staged (a media turn is always cortex work). On ``None`` the caller
        dispatches to cortex exactly as before (byte-identical). The ROUTE is a
        deterministic classifier; senses is consulted (one tools-off completion)
        only on a non-repo turn, and never raises (run_frontdoor degrades). The
        CORTEX route is short-circuited BEFORE any senses engine load — it is the
        common case and never consults senses — so it is recorded even when the
        senses engine can't be resolved."""
        if self.config.senses is None or self.cortex_only or self._staged_attachments:
            return None
        # Deterministic route FIRST (pure regex, no engine): the CORTEX route — the
        # common case — never consults senses, so don't resolve/load the senses
        # engine for it, and record the route even if the engine can't load.
        if classify_frontdoor(text) == CORTEX:
            return cortex_frontdoor_outcome()
        pair = self._senses_engine()
        if pair is None:
            return None
        senses_config, engine = pair
        return run_frontdoor(
            text,
            senses_config=senses_config,
            make_complete=engine.make_complete,
            make_count_tokens=engine.make_count_tokens(senses_config),
            history=list(self._history) or None,
            # #311: persist a standalone auditable record of this senses-direct turn
            # (it has no TaskResult) beside the operator repo's .colleague/ artifacts.
            record_repo=str(self.repo),
        )

    def _render_senses_direct(self, text: str, outcome) -> None:
        """Speak senses' direct answer to a non-repo turn — NO cortex work item.

        The point of the front door: a greeting or a question about colleague
        itself is answered by the fast front lobe with NO git branch and NO
        eidetic record (the work loop never runs). The exchange threads into the
        rolling history for continuity and is reconstructable from the session
        transcript (a senses-direct turn produces no TaskResult to fold onto — an
        honest limit noted in the feature doc)."""
        self._history_append("operator", text)
        self._log(f"→ senses: {text}")
        self._log(senses_line(outcome.answer or ""))
        self._history_append("senses", outcome.answer or "")
        # A senses-direct turn produces NO work item / TaskResult, so its exchange
        # must NOT accumulate in the per-work-item `_senses_chat` buffer (which is
        # reset per work line and folded into a work item's artifact) — that would
        # leak over a senses-only conversation. Continuity is already carried by the
        # capped `_history` appends above; the turn is reconstructable from the transcript.
        if self.view == "ansi":
            self.emit()

    # ── middle-manager presence lane (talking-to-one arc, t6) ────────────────

    def _reset_presence_lane(self) -> None:
        """Reset the per-work-line middle-manager state (ack/update/clarify
        exchanges + cadence counters) at intake time, so one line's exchanges
        never leak into the next work item's artifact. The session-lifetime
        rolling ``_history`` deliberately survives (c11 — continuity spans work
        lines within one session)."""
        self._senses_chat = []
        self._update_records = []
        self._clarify_records = []
        self._updates_sent = 0
        self._update_last_step = 0
        self._update_last_phase = ""
        self._update_cap_recorded = False
        # The senses agentic loop is rebuilt per work line in _begin_talk_lane
        # (loop rung) and cleared here so one line's loop never leaks to the next.
        self._presence_engine = None

    def _history_append(self, role: str, text: str) -> None:
        """Append one exchange to the session-lifetime rolling history (t7/c11).

        Gated on the presence lane — an unarmed session (off-TTY / --no-tui /
        piped / --cortex-only / no senses) NEVER accumulates history, so every
        senses call it makes stays byte-identical (h5/h9). Capped to the last
        50 entries as a memory bound; windowing to senses' own budget happens
        senses-side at call time (t4), dropping oldest whole entries first."""
        if not self._presence_enabled() or not text:
            return
        self._history.append({"role": role, "text": text})
        if len(self._history) > 50:
            del self._history[: len(self._history) - 50]

    def _read_clarify_answer(self) -> Optional[str]:
        """Pull ONE operator line for a clarify question from the session's own
        input source. ``None`` (EOF / no source / a read error) means dispatch
        — clarification can never withhold work (h8). A shift-tab CYCLE_MODE
        sentinel re-reads; it is never an answer."""
        if self._read_next is None:
            return None
        try:
            raw = self._read_next()
            while raw is CYCLE_MODE:
                raw = self._read_next()
        except Exception:  # noqa: BLE001 — a broken input source dispatches
            return None
        if raw is None:
            return None
        return str(raw).strip()

    def _maybe_clarify(self, task: Task, packet, senses_config, engine):
        """Clarify-first (t7 / c19): on a low-confidence intake senses MAY ask
        the operator before dispatching — more than one question allowed
        (senses judges via the packet it authored: confidence + omissions),
        bounded by the generous env-tunable ceiling (loop-proofing, h8).

        Returns the FINAL packet. Dispatch is never withheld: an explicit
        go-word, an empty answer, EOF, or a missing input source all dispatch
        immediately. Every exchange is recorded on the per-line chat (kind=
        "clarify") AND the rolling history; each answer re-runs intake over the
        instruction + the operator's verbatim clarification, so clarify refines
        the packet — the dispatched instruction always still CONTAINS the
        operator's original verbatim words plus their own answers, never a
        rewrite (h8)."""
        if not self._presence_enabled() or self._read_next is None:
            return packet
        asked = 0
        while should_clarify(
            self._clarify_policy,
            confidence=packet.confidence,
            has_omissions=bool(packet.omissions),
            questions_asked=asked,
        ):
            gap = packet.omissions[0]
            question = (
                f"before I hand this to cortex — your request left '{gap}' "
                "unspecified. Add details, or say 'go' to dispatch as-is."
            )
            self._log(f"senses: {question}")
            self._senses_chat.append(
                {"kind": "clarify", "role": "senses", "text": question, "at": time.time()}
            )
            self._history_append("senses", question)
            if self.view == "ansi":
                self.emit()
            answer = self._read_clarify_answer()
            asked += 1
            if not answer or is_go_word(answer):
                if answer:
                    self._log(answer)
                    self._senses_chat.append(
                        {
                            "kind": "clarify",
                            "role": "operator",
                            "text": answer,
                            "go": True,
                            "at": time.time(),
                        }
                    )
                    self._history_append("operator", answer)
                break
            self._log(answer)
            self._senses_chat.append(
                {"kind": "clarify", "role": "operator", "text": answer, "at": time.time()}
            )
            self._history_append("operator", answer)
            # The operator's verbatim answer joins the instruction (their words,
            # appended — never a rewrite of the original request, h8) and intake
            # re-perceives the refined whole with the conversation threaded.
            composed = f"{task.instruction}\n\nOperator clarification: {answer}"
            refined, refine_record = run_senses_intake(
                composed, senses_config, engine, history=list(self._history) or None
            )
            self._clarify_records.append(refine_record)
            task.instruction = composed
            if refined is not None:
                packet = refined
                task.context_packet = refined
        return packet

    def _presence_rung(self) -> str:
        """The resolved presence rung for this session: ``loop`` / ``beats`` /
        ``off`` (:func:`colleague.config.resolve_presence_rung`).

        ``off`` whenever senses is unresolved or ``--cortex-only`` is set — those
        stay byte-identical. Otherwise the operator's request (default ``loop``)
        selects the senses-loop lane or the fixed-beat opt-down."""
        return resolve_presence_rung(self.config, cortex_only=self.cortex_only, repo_path=self.repo)

    def _presence_enabled(self) -> bool:
        """True iff the middle-manager lane (ack + proactive updates + clarify)
        speaks for this session.

        Armed whenever the presence rung is not ``off`` — presence-default-
        everywhere (t7): unlike the pre-arc gate, this NO LONGER requires an
        interactive colour TTY, so off-TTY / piped / ``--no-tui`` sessions now
        carry labeled ``senses:`` ack + update lines too (the deliberate c19
        pin-break). ``--cortex-only`` / no senses still resolve to ``off`` →
        byte-identical. The live *concurrent talk* lane (a non-blocking stdin
        poll) still requires a real TTY — see :meth:`_talk_lane_enabled`."""
        return self._presence_rung() != "off"

    def _render_ack(self, ack: Optional[str]) -> None:
        """Speak the acknowledgment BEFORE cortex's first step (t6 / c9).

        The ack text is senses' own line riding the intake completion
        (``packet.ack``, task t1); a missing or degraded ack renders the FIXED
        dispatch notice — never fabricated understanding (h2). Every spoken ack
        is recorded as a ``kind="ack"`` chat entry for the artifact fold, so the
        exchange is reconstructable from the artifact alone (h14)."""
        if not self._presence_enabled():
            return
        text = (ack or "").strip() or _ACK_DISPATCH_NOTICE
        self._log(f"senses: {text}")
        self._senses_chat.append(
            {
                "kind": "ack",
                "text": text,
                "fixed": not (ack or "").strip(),
                "at": time.time(),
            }
        )
        self._history_append("senses", text)
        if self.view == "ansi":
            self.emit()

    def _maybe_proactive_update(self, tool: str, target: str) -> None:
        """Proactive middle-manager narration at a progress-sink boundary (t6).

        Cadence-gated (:mod:`colleague.presence`): fires on a phase CHANGE or
        every N steps, capped per run — a strict no-op unless the talk lane
        armed this work line, so unarmed sessions never poll, call, or render.
        A fired update renders as a labeled ``senses:`` conversation line (the
        raw feed stays — senses augments, never hides) and is recorded (a
        ``senses-update`` record + a ``kind="update"`` chat entry) for the
        artifact fold at finalize. Hitting the cap is recorded ONCE, never
        silent (h4). A degraded call still counts toward the cap and still
        records — diagnosable, never silent. Never raises, and never advances
        ``step_count`` (the #206 invariant: narration is presentation, not
        work — only the reducer's real-step fold advances the count).

        Presence-default-everywhere (t7): gated on :meth:`_presence_enabled`
        (the rung, not the TTY talk lane), so proactive updates now also fire
        off-TTY / piped — the c19 pin-break. On the ``loop`` rung the session's
        live talk rides the senses agentic loop; proactive narration stays on
        this (live-proven) fixed-beat path either way."""
        if not self._presence_enabled():
            return
        try:
            phase_changed = False
            if not tool:
                # A phase notice (#206) — its target is the phase label; only a
                # CHANGED label counts (thinking… → thinking… is not a change).
                phase_changed = target != self._update_last_phase
                self._update_last_phase = target
            wi = self.state.work_item
            step_count = wi.step_count if wi is not None else 0
            fire, reason = should_update(
                self._update_cadence,
                step_count=step_count,
                last_update_step=self._update_last_step,
                phase_changed=phase_changed,
                updates_sent=self._updates_sent,
            )
            if reason == "cap":
                if not self._update_cap_recorded:
                    self._update_cap_recorded = True
                    self._log(
                        "senses: (update cap reached — staying quiet now; "
                        "COLLEAGUE_SENSES_UPDATE_CAP raises it)"
                    )
                    self._senses_chat.append({"kind": "update", "capped": True, "at": time.time()})
                return
            if not fire:
                return
            pair = self._senses_engine()
            if pair is None:
                return
            senses_config, engine = pair
            feed_lines = self._talk_feed_tail().splitlines()
            record = run_senses_update(
                feed_lines,
                self._talk_packet,
                senses_config,
                engine,
                history=list(self._history) or None,
            )
            # A fired attempt consumes senses budget whether or not it produced
            # text — count it toward the cap either way (honest accounting).
            self._updates_sent += 1
            self._update_last_step = step_count
            if record is None:
                return
            self._update_records.append(
                SensesRecord(
                    point=UPDATE_POINT,
                    latency=record["latency"],
                    tokens=record.get("tokens"),
                    degraded=record["degraded"],
                )
            )
            text = record.get("update")
            if text:
                self._log(f"senses: {text}")
                self._senses_chat.append(
                    {
                        "kind": "update",
                        "text": text,
                        "latency": record["latency"],
                        "degraded": record["degraded"],
                        "at": time.time(),
                    }
                )
                self._history_append("senses", text)
                if self.view == "ansi":
                    self.emit()
        except Exception:  # noqa: BLE001 — narration must never disturb the run
            return

    # ── concurrent senses talk lane (senses live-presence arc, task t7) ──────

    def _talk_lane_enabled(self) -> bool:
        """True iff the concurrent talk lane should arm for a work line.

        Armed only on an interactive colour TTY (``view == "ansi"``) with a senses
        model resolved and not a session-wide ``--cortex-only`` bypass. Off-TTY /
        --no-tui / piped / no-senses → False, so the session is byte-identical to
        today: no stdin poll, no flight arming (t7 acceptance)."""
        return (
            self.view == "ansi"
            and not self.cortex_only
            and senses_engine_config(self.config) is not None
        )

    def _begin_talk_lane(self, task: Task) -> None:
        """Arm the talk lane for *task* (a no-op unless enabled).

        Marks the task watchable so ``execute_work`` arms the flight plane — the
        operator's relays land as guidance at the next tool-call boundary — and
        records the id + intake packet the lane answers from."""
        self._talk_active = self._talk_lane_enabled()
        if not self._talk_active:
            return
        task.watch = True
        self._talk_task_id = task.id
        self._talk_packet = getattr(task, "context_packet", None)
        self._maybe_build_presence_engine()

    def _maybe_build_presence_engine(self) -> None:
        """Build the senses agentic loop for this work line on the ``loop`` rung.

        Live operator talk then rides the loop (:meth:`_talk_senses`) — senses
        drives the conversation as an agent, choosing coordination moves — while
        ack + proactive updates stay on the fixed-beat methods. A no-op (leaves
        ``_presence_engine`` at ``None``, byte-identical) on the ``beats`` rung,
        when senses is unresolved, or on any build failure — the run always
        proceeds."""
        self._presence_engine = None
        if self._presence_rung() != "loop":
            return
        pair = self._senses_engine()
        if pair is None:
            return
        senses_config, engine = pair

        def _relay(text: str) -> None:
            if self._talk_task_id is not None:
                with contextlib.suppress(Exception):
                    flight.append_guidance(self.repo, self._talk_task_id, text)

        try:
            io = PresenceIO(
                render=self._log,
                append_guidance=_relay,
                read_flight=self._talk_feed_tail,
                feed_tail=self._talk_feed_tail,
                task_state=self._talk_task_state,
                dispatch_to_cortex=lambda _i: None,  # the session runs cortex itself
                poll_operator_input=lambda: None,  # the session polls stdin itself
            )
            driver = SensesLoopDriver(
                senses_config=senses_config,
                make_complete=engine.make_complete,
                executor=build_presence_executor(io),
                make_count_tokens=engine.make_count_tokens(senses_config),
                initial_rung="loop",
            )
            self._presence_engine = PresenceEngine(
                driver=driver,
                io=io,
                cadence=self._update_cadence,
                history_provider=lambda: list(self._history) or None,
            )
        except Exception:  # noqa: BLE001 — a build failure degrades to the fixed-beat lane
            self._presence_engine = None

    def _end_talk_lane(self) -> None:
        """Disarm the talk lane on work-item exit (always cleared)."""
        self._talk_active = False
        self._talk_task_id = None
        self._talk_packet = None

    def _poll_talk_lane(self) -> None:
        """Thread-free stdin poll at a progress-sink boundary (t7).

        Non-blocking ``select`` (zero timeout) on stdin — NO threads (the whole
        live presence is a foreground cooperative poll, decision c). On an
        interactive TTY stdin is line-buffered (cooked), so ``select`` reports
        readable only once the operator presses Enter and ``readline`` then never
        blocks. A strict no-op unless the lane is armed; any error degrades to a
        silent no-op so a talk-lane hiccup never disturbs the running work item."""
        if not self._talk_active:
            return
        try:
            ready, _, _ = select.select([sys.stdin], [], [], 0)
        except (OSError, ValueError):
            return
        if not ready:
            return
        try:
            line = sys.stdin.readline()
        except (OSError, ValueError):
            return
        text = line.strip()
        if not text:
            return
        with contextlib.suppress(Exception):
            self._handle_talk_input(text)

    def _handle_talk_input(self, text: str) -> None:
        """Route one operator line typed mid-run: ``/say FILE`` transcribes audio
        first, then senses answers + optionally relays (rendered labeled)."""
        if text.startswith("/say"):
            transcript = self._talk_transcribe(text[len("/say") :].strip())
            if not transcript:
                return
            text = transcript
        self._talk_senses(text)

    def _talk_transcribe(self, path: str) -> Optional[str]:
        """Transcribe an audio FILE to text via the stt role (``/say``). Degrades to
        a notice + None when no stt is configured or transcription fails — the
        verbatim transcript, when present, is the raw operator message."""
        if not path:
            self._log("senses: /say needs a file path")
            return None
        voice_cfg = getattr(self.config, "voice", None)
        if voice_cfg is None or not getattr(voice_cfg, "stt_model", None):
            self._log("senses: no stt configured — cannot transcribe /say audio")
            return None
        from colleague import voice as voicemod

        transcript = voicemod.transcribe(
            path,
            stt_model=voice_cfg.stt_model,
            base_url=voice_cfg.stt_base_url,
            api_key=voice_cfg.api_key,
        )
        if not transcript:
            self._log("senses: could not transcribe the audio")
            return None
        self._log(f"you (voice): {transcript}")
        return transcript

    def _talk_senses(self, text: str) -> None:
        """Answer one operator message with senses, grounded in the live run
        context, and relay into cortex when senses judges it (or an explicit
        ``cortex:`` prefix forces it). Every answer is labeled ``senses:``, every
        relay echoes ``-> cortex:`` and records a flight chat line (folded into the
        artifact at finish, t5) — nothing silent (the awareness invariant).

        On the ``loop`` rung the message rides the senses agentic loop
        (:class:`~colleague.presence_engine.PresenceEngine`) — senses chooses a
        coordination move (reply / guide-cortex / read-flight …) rather than a
        single fixed talk turn — with the loop enforcing the verbatim-to-cortex
        invariant on any relay. The engine renders + records; the exchange folds
        onto the artifact at finalize (:meth:`_finalize_split_run`)."""
        if self._presence_engine is not None:
            self._presence_engine.on_operator_message(text)
            if self.view == "ansi":
                self.emit()
            return
        pair = self._senses_engine()
        if pair is None:
            return
        senses_config, engine = pair
        record = run_senses_talk(
            text,
            feed_tail=self._talk_feed_tail(),
            packet=self._talk_packet,
            task_state=self._talk_task_state(),
            senses_config=senses_config,
            make_complete=engine.make_complete,
            make_count_tokens=engine.make_count_tokens(senses_config),
            history=list(self._history) or None,
        )
        if record is None:
            return
        self._history_append("operator", text)
        self._history_append("senses", record["answer"])
        self._log(f"senses: {record['answer']}")
        with contextlib.suppress(Exception):
            flight.append_chat(
                self.repo,
                self._talk_task_id,
                {
                    "message": text,
                    "answer": record["answer"],
                    "relay": record["relay"],
                    "relay_text": record.get("relay_text", ""),
                    "latency": record["latency"],
                    "degraded": record["degraded"],
                },
            )
        if record["relay"]:
            relay_text = record.get("relay_text") or text
            with contextlib.suppress(Exception):
                flight.append_guidance(self.repo, self._talk_task_id, relay_text)
            self._log(f"-> cortex: {relay_text}")
        if self.view == "ansi":
            self.emit()

    def _talk_feed_tail(self, max_lines: int = 40) -> str:
        """The recent flight-feed text senses grounds its answer on (last
        *max_lines* lines), or '' when the feed is absent."""
        if self._talk_task_id is None:
            return ""
        try:
            feed = flight.feed_path(self.repo, self._talk_task_id)
            if not feed.exists():
                return ""
            return "\n".join(feed.read_text().splitlines()[-max_lines:])
        except Exception:  # noqa: BLE001 - grounding is best-effort
            return ""

    def _talk_task_state(self) -> Optional[dict]:
        """A short live snapshot (step/running) for senses grounding, taken from
        the cockpit work item — never fabricated."""
        wi = self.state.work_item
        if wi is None:
            return None
        return {"step": wi.step_count, "running": wi.running}

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
            shaped, speakback_record = run_senses_speakback(
                result.summary, senses_config, engine, history=list(self._history) or None
            )
        if result.senses is None:
            result.senses = SensesBlock(mode="split", packet=None, records=[])
        pre = [intake_record] if intake_record is not None else []
        # The front-door route decision (cortex path) leads the records so the
        # turn's senses→cortex hand-off is reconstructable from the artifact (h5).
        if self._frontdoor_record is not None:
            pre = [self._frontdoor_record, *pre]
        post = [speakback_record] if speakback_record is not None else []
        # Middle-manager fold (t6/t7): clarify re-intake records slot after the
        # intake (they happened pre-run), proactive-update records between the
        # loop's own records and speak-back; the ack/update/clarify chat entries
        # append after any flight-folded talk exchanges — so the whole
        # operator-senses exchange is reconstructable from the artifact alone
        # (h14). Empty lists when the lane never armed → byte-identical.
        result.senses.records = (
            pre
            + list(self._clarify_records)
            + list(result.senses.records)
            + list(self._update_records)
            + post
        )
        if self._senses_chat:
            result.senses.chat = list(result.senses.chat) + list(self._senses_chat)
        # Presence-default-everywhere (t7): fold the senses agentic loop's own
        # records / chat / injections onto the artifact when the loop ran this
        # line, so the loop-driven conversation is reconstructable from the
        # artifact alone (h6). A no-op (byte-identical) when the loop never armed.
        if self._presence_engine is not None:
            snap = self._presence_engine.snapshot()
            result.senses.records = list(result.senses.records) + list(snap["records"])
            if snap["chat"]:
                result.senses.chat = list(result.senses.chat) + list(snap["chat"])
            if snap["injections"]:
                result.senses.injections = list(result.senses.injections) + list(snap["injections"])
        if shaped:
            self._history_append("senses", shaped)
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
        # Arm the concurrent talk lane for the duration of this work item (t7): a
        # no-op unless enabled (off-TTY / no senses / --cortex-only). When enabled
        # it marks the task watchable so the flight plane is armed — the operator's
        # relays land as guidance at the next tool-call boundary, on the SAME
        # file-based flight plane the `colleague flight`/`colleague talk` clients use.
        self._begin_talk_lane(task)
        try:
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
        finally:
            self._end_talk_lane()
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
    SlashSpec("model", "<name>", "switch the model", "runtime", ("model", "config")),
    SlashSpec(
        "mode",
        "[name]",
        "show/cycle the session mode (auto|work|plan|explore|review) — shift-tab equivalent",
        "runtime",
        ("interactive",),
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
        io=SessionIO(out=out, err=err),
        work_fn=_work_fn,
        plan_fn=_plan_fn,
        senses_options=SensesSessionOptions(
            cortex_only=bool(getattr(args, "cortex_only", False)),
            debug_senses=bool(getattr(args, "debug_senses", False)),
        ),
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
            "senses intake or speak-back shaping, no senses media bridge). The "
            "artifact records mode=cortex-only. Byte-identical when no senses "
            "model is resolved. (cortex/senses arc)"
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
