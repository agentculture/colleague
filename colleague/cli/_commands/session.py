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
import os

# ``select`` (like ``sys`` and the ``realtime`` module below) is imported here
# rather than only in the lane module that uses it, because the suite reaches
# it AS A SESSION ATTRIBUTE — ``monkeypatch.setattr(session_mod.select,
# "select", ...)`` patches the shared stdlib module object every lane sees, so
# the seam keeps working from here.
import select  # noqa: F401 - `session_mod.select` is a patch seam
import sys
import time
from collections import deque
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Iterator, Optional

from agentfront.taui.colors import should_color
from agentfront.taui.reducer import reduce
from agentfront.taui.state import Status

from colleague import realtime  # noqa: F401 - `session_mod.realtime` is a patch seam
from colleague import flight, icons
from colleague.cli._commands._input_line import OwnedInputLine
from colleague.cli._commands._session_actions import (  # noqa: F401 - re-exported
    _CONFIG_ACTIONS,
    _act_attach,
    _act_base,
    _act_effort,
    _act_engine,
    _act_learn_from,
    _act_mode,
    _act_model,
    _act_pr,
    _act_speak,
    _act_voice,
)
from colleague.cli._commands._session_const import (  # noqa: F401 - re-exported
    _ACK_DISPATCH_NOTICE,
    _ACTIVE_RUN_PANEL_ID,
    _CAPACITY_BUDGET_ID,
    _CAPACITY_MODE_ID,
    _CAPACITY_PANEL_ID,
    _CAPACITY_PROFILE_ID,
    _CAPACITY_SIGNAL_ID,
    _CLEAR_HOME,
    _CONVERSATION_PANEL_ID,
    _GOAL_ITEM_ID,
    _GOAL_MAX_CHARS,
    _LAST_RUN_PANEL_ID,
    _NARRATION_DELTA_CHARS,
    _NEXT_ITEM_ID,
    _NEXT_PANEL_ID,
    _QUIT_TOKENS,
    _SPEAK_SENSES_UNARMED_LINE,
    _SPEAK_STATE_LINES,
    _SPEAK_UNAVAILABLE_LINE,
    _STREAM_CUT_MARKER,
    _SUGGESTION_PREFIXES,
    _VOICE_OFFER_LINE,
    _VOICE_SENSES_UNARMED_LINE,
    _VOICE_STATE_LINES,
    _VOICE_UNAVAILABLE_LINE,
)
from colleague.cli._commands._session_dispatch import _DispatchMixin
from colleague.cli._commands._session_panels import _PanelsMixin
from colleague.cli._commands._session_parser import (  # noqa: F401 - re-exported
    _SESSION_DESCRIPTION,
    _SESSION_HELP,
    _configure_session_parser,
)
from colleague.cli._commands._session_runs import _RunLaneMixin
from colleague.cli._commands._session_senses import _SensesMixin
from colleague.cli._commands._session_slash import (  # noqa: F401 - re-exported
    _HELP_COMPACT,
    _HELP_TEXT,
    _HELP_VERBOSE,
    _INTROSPECT,
    _SLASH_COMMANDS,
    _SLASH_GROUPS,
    SlashSpec,
    _cursor_back_to_input,
    _format_help,
    _format_help_verbose,
    _grouped,
    _slash_tag_style,
    build_slash_panels,
    filter_slash,
)
from colleague.cli._commands._session_support import (  # noqa: F401 - re-exported
    _T,
    _ChainFn,
    _coerce_strs,
    _default_plan,
    _eprint,
    _goal_text,
    _mode_profile_text,
    _mode_status_text,
    _PlanFn,
    _read_line,
    _reply_text_from_turns,
    _resolve_selection,
    _SensesStreamPainter,
    _WorkFn,
)
from colleague.cli._commands._session_talk import _TalkLaneMixin
from colleague.cli._commands._session_voice import _VoiceLaneMixin
from colleague.cli._commands._tui_sink import fold_phase
from colleague.cli._commands.work import _resolve_chain_arming
from colleague.cli._commands.work import execute_work as _default_work
from colleague.cli._commands.work import execute_work_chain as _default_chain
from colleague.cockpit_run import (
    DeltaTail,
    RunState,
    delta_status_message,
    fold,
    fold_delta,
    mark_delta_rendered,
    should_repaint_delta,
    status_line,
)
from colleague.commands import discover_commands, load_command
from colleague.config import EngineConfig, resolve_session_engine
from colleague.contract import SensesRecord
from colleague.frontdoor import (  # noqa: F401 - reached as `session_mod.<name>`
    cortex_frontdoor_outcome,
    run_frontdoor,
)
from colleague.presence import cadence_from_env, clarify_from_env
from colleague.presence_engine import PresenceEngine
from colleague.senses import (  # noqa: F401 - patched via session_mod
    make_senses_display_delta,
    run_senses_intake,
    run_senses_speakback,
    run_senses_talk,
    run_senses_update,
    senses_engine_config,
)
from colleague.session_modes import DEFAULT_MODE
from colleague.tui.from_work import work_step

# ---------------------------------------------------------------------------
# Where the rest of this module lives
# ---------------------------------------------------------------------------
# ``_Session`` mutates shared instance state across ~85 methods, so the lanes
# split out under plan ``hard-1000-line-file-limit`` t17 are MIXINS holding
# their methods VERBATIM — never a value-passing rewrite:
#
#   _session_panels.py    _PanelsMixin     cockpit state, panels, the emit paths
#   _session_dispatch.py  _DispatchMixin   the input loop, slash, work dispatch
#   _session_senses.py    _SensesMixin     intake, front door, narration
#   _session_talk.py      _TalkLaneMixin   the concurrent senses talk lane
#   _session_voice.py     _VoiceLaneMixin  realtime voice + speak-only
#   _session_runs.py      _RunLaneMixin    run finalization, explore/review
#
# plus the coupling-free ``_session_const`` / ``_session_support`` /
# ``_session_slash`` / ``_session_parser`` siblings, all re-exported above.
#
# THREE things deliberately did NOT move, because tests pin them HERE:
#   * ``_WorkSink`` and the one cadence-gated proactive-update call it
#     makes — ``tests/test_talking_to_one_boundary.py`` requires that call
#     to sit inside ``_WorkSink.__call__`` in a file named ``session.py``;
#   * ``_stdout_is_tty`` — patched as ``session_mod._stdout_is_tty``;
#   * ``_Session._park_talk_for_cortex`` — the unarmed-senses relay, so
#     ``tests/test_senses_live_presence_proofs.py``'s ``flight.append_guidance(``
#     call-site check still reads a REAL relay in this file.
#
# Every moved call to a name the suite patches on THIS module reaches back
# through a lazy module-attribute lookup (``_session_mod()``); a from-import
# would leave those patches green but inert.


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
        # Live generation tail (feels-alive arc, task t6): accumulates the
        # CURRENT turn's streamed text (see `on_delta`); reset at the top of
        # every `__call__` so a stale tail can never linger past the turn
        # that produced it — the same clearing rule `_tui_sink.py`'s
        # `CockpitProgressSink` uses for the standalone `work --tui` cockpit.
        self._delta = DeltaTail()

    @property
    def wants_delta_stream(self) -> bool:
        """Whether this sink should arm the engine's ``on_delta`` seam (task t6,
        extended by t4/ssv, covers c19/h16).

        Originally gated on the session's dynamic ANSI tier (the only tier
        that redraws per sink call, ``sess.emit()`` in ``__call__`` below) —
        but the seam has a SECOND job besides live display: arming it flips
        the engine onto its incrementally-consumed streamed request path
        (``config.on_delta is not None`` is the ONLY blocking-vs-streaming
        decision, ``colleague/engines/vllm_openai.py``'s ``_make_complete``),
        whose PER-READ socket timeout resets on every chunk instead of once
        for the whole completion. A long session turn on a slow model can hit
        the SAME request timeout a quick one comfortably clears — leaving the
        seam unarmed off the ANSI tier was silently costing that survival, not
        "nothing" as originally documented. Every session cortex turn now
        arms the seam regardless of render tier; the VISIBLE redraw stays
        ANSI-only inside ``on_delta``/``__call__`` below (unchanged) — a
        piped/``--json``/Markdown session still computes-but-never-shows a
        live tail, and its own frame output stays byte-identical (proven by
        ``tests/test_cockpit_delta_tail.py``'s
        ``test_session_markdown_tier_now_arms_deltas_but_never_redraws_them``).
        ``getattr`` degrades a bare state-holder (no ``view`` attribute at
        all, the pattern several other guards below already use) to
        ``False`` — never armed by accident against a test double that never
        declared a view tier at all. No new CLI flag: this is a resolution
        change, not an opt-in.
        """
        return getattr(self._session, "view", None) is not None

    def __call__(self, step_index: int, tool: str, target: str, ok: bool) -> None:
        sess = self._session
        # A real step or a phase notice ends the current turn's live-generation
        # tail (task t6): reset it so a stale "generating… …" text can never
        # linger once the loop has moved on.
        self._delta = DeltaTail()
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

    def on_delta(self, chunk: str) -> None:
        """Fold ONE streamed text delta onto the session's live STATUS surface
        (feels-alive arc, task t6; extended off the ANSI tier by t4/ssv).

        Called whenever `wants_delta_stream` was `True` at arming time — now
        EVERY session tier (t4/ssv), not only the dynamic ANSI one, since
        arming has a job beyond display: it flips the engine onto its
        per-read-timeout-resetting streamed path (see `wants_delta_stream`'s
        docstring). The redraw itself stays ANSI-gated: ``sess.view ==
        "ansi"`` below is the REAL arming decision for the visible frame — a
        Markdown/``--json`` tier still folds *chunk* into `DeltaTail` and
        `sess.state.status` (cheap, pure computation) but never calls
        `sess.emit()`, so its own output is unaffected. Accumulates *chunk*
        into the current turn's `DeltaTail` and, throttled to at most once
        per `DELTA_REPAINT_THRESHOLD` accumulated characters, folds the
        sanitized tail onto ``sess.state.status`` via the SAME `fold_phase`
        a phase notice uses and (ANSI only) redraws exactly one frame. Never
        creates a work step and never touches the conversation feed (the
        #206 invariant, held identically to `__call__`'s phase-notice branch).
        Cleared by the very next `__call__`.

        Cortex narration capture (ssv t6, c23): every chunk ALSO folds into the
        session's windowed narration buffer (`_fold_cortex_delta`) — BEFORE the
        display throttle below, so the buffer never misses sub-threshold text.
        Buffering is the ONLY thing that happens here: no senses completion is
        ever issued inside this callback (it would stall the stream read), and
        no thread is spawned — the boundary beats read the buffer later.
        `getattr` keeps the sink usable against a bare state-holder in tests
        (its documented contract), like the guards in `__call__`.
        """
        sess = self._session
        fold_narration = getattr(sess, "_fold_cortex_delta", None)
        if fold_narration is not None:
            fold_narration(chunk)
        self._delta = fold_delta(self._delta, chunk)
        if not should_repaint_delta(self._delta):
            return
        self._delta = mark_delta_rendered(self._delta)
        sess.state = fold_phase(sess.state, delta_status_message(self._delta))
        if sess.view == "ansi":
            sess.emit()

    def close(self) -> None:  # called by execute_work on every exit path
        return None


def _stdout_is_tty() -> bool:
    """Whether stdout is a genuine terminal (module-level so tests can seam it).

    Gates the UNOWNED live-TTY paint path in :meth:`_Session._senses_stream_sink`:
    a ``--tui``-forced ANSI session piped somewhere must still arm nothing —
    a transient paint into a pipe would change piped output (h12)."""
    try:
        return bool(sys.stdout.isatty())
    except Exception:  # noqa: BLE001 - a stdout without isatty is not a TTY
        return False


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


class _Session(
    _PanelsMixin,
    _DispatchMixin,
    _SensesMixin,
    _TalkLaneMixin,
    _VoiceLaneMixin,
    _RunLaneMixin,
):
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
        # Episode chaining (indefinite-run t9): the session front's --until-done
        # arming. ``chain_cap`` is None when unarmed — every dispatch is the
        # ordinary single-episode ``work_fn`` call, byte-identical to today. An
        # int cap arms EVERY work item this session dispatches through
        # ``chain_fn`` — by default ``work.execute_work_chain``, the exact chain
        # loop ``work --until-done`` drives (shared dispatch path, no
        # session-only fork). Resolved ONCE at session start by ``run_session``
        # (flag > env > config.json, c28 verbatim inheritance) and set
        # post-construction (the documented post-construction attribute idiom —
        # ``__init__``'s signature stays at the S107 bundle ceiling).
        self.chain_cap: Optional[int] = None
        self.chain_fn: _ChainFn = _default_chain
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

        # Owned mid-run input line (at-home arc, t5): on a LIVE colour TTY the
        # talk lane takes ownership of the bottom input line via a sanctioned
        # reader thread (:class:`OwnedInputLine`), so mid-run output prints ABOVE
        # the operator's in-progress typing (``print_above``) instead of a
        # full-frame clear-home redraw that would clobber the cooked tty echo.
        # ``None`` on every non-live / off-colour-TTY / --json / --no-tui / unarmed
        # path → byte-identical (the cooked ``_poll_talk_lane`` select poll stays
        # the fallback). ``_owned_line_streams`` is a test seam: when set it forces
        # arming over injected io streams (no real TTY needed); production leaves it
        # ``None`` and gates on a live colour-TTY session. ``_owned_talk_queue`` is
        # the thread-safe hand-off — the reader thread only ENQUEUES a submitted
        # line; the main thread drains it at the next progress-sink boundary (in
        # ``_poll_talk_lane``), so a talk message never mutates session state
        # concurrently. ``_printed_conv`` tracks how many conversation lines have
        # already scrolled above the owned line (the ``print_above`` delta cursor).
        # One-run dirty-guard waiver granted by the heal prompt's commit choice
        # (#168); consumed (reset) by the next _dispatch_work. Never persists.
        self._heal_allow_dirty_once = False
        # Lineage for the next dispatch when /continue seeded it (#167); consumed
        # (reset) by _dispatch_work, mirroring the heal waiver cell above.
        self._continued_from_next: Optional[str] = None
        # Propagated original task_text (c22/h15/h3), consumed alongside the
        # lineage cell above.
        self._continuation_task_text_next: Optional[str] = None
        self._owned_line: Optional[OwnedInputLine] = None
        self._owned_line_streams: Optional[tuple[object, object]] = None
        self._owned_talk_queue: "deque[str]" = deque()
        self._printed_conv = 0
        # True only inside the genuine live interactive loop (``run`` with no
        # test ``input_fn`` and the ANSI view). Gates real-TTY owned-line arming.
        self._live = False

        # Voice lane (realtime-speech arc, t5): opt-in mic capture + a spoken
        # senses reply, wired into the SAME typed-input path (ONE senses path).
        # All dormant unless armed → byte-identical (t6 pins the off-TTY / unarmed
        # zero-output floor). ``_voice_wanted`` is the c27 opt-in (the --voice flag,
        # set post-construction by ``run_session``, or a ``/voice`` toggle);
        # realtime *availability* NEVER starts capture on its own. ``_voice_session``
        # / ``_voice_capture`` are the live ears-only realtime resources, armed per
        # work line (like the owned line) when wanted + the gate passes, and reaped
        # on work-item / session exit with their bounded joins. ``_voice_state`` is
        # the honest lane state (off / live / muted / degraded — muted ≠ degraded).
        # ``_voice_transcripts`` is the pump-thread → main-thread hand-off: a final
        # VAD transcript is ENQUEUED on the pump thread (``_on_voice_transcript``)
        # and drained at the SAME poll boundary a typed line is (``_poll_talk_lane``
        # → ``_drain_voice_transcripts``), so a voice turn never mutates session
        # state concurrently. ``_last_talk_reply`` captures senses' rendered answer
        # so a voice turn can speak it back (additive). The two once-flags keep the
        # offer line / unavailable notice to exactly one emission per session.
        self._voice_wanted = False
        self._voice_session: Optional[object] = None
        self._voice_capture: Optional[object] = None
        self._voice_state = "off"
        self._voice_transcripts: "deque[str]" = deque()
        self._voice_offer_shown = False
        self._voice_unavailable_noticed = False
        self._last_talk_reply = ""

        # Speak-only lane (task t8): TTS-speaks each senses REPLY while the
        # operator only types — no mic, no realtime session, no half-duplex
        # gate (there is no capture stream to protect). Independent of the
        # voice lane above: ``_speak_only`` is the ONLY writer of this state
        # (the ``--speak`` flag, set post-construction by ``run_session``, or a
        # ``/speak`` toggle, :meth:`_toggle_speak`) — no config default,
        # profile, or mode ever touches it (h18/c22: this attribute is not
        # part of ``EngineConfig``/config.json resolution at all, structurally
        # ruling that out). Default OFF → byte-identical to today.
        # :meth:`_speak_reply`'s own gate — (a live voice session) OR
        # (``_speak_only``) — decides whether a reply actually gets spoken;
        # c7/c27 stand untouched: NOTHING here ever arms the mic or stt.
        self._speak_only = False

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
        # Cortex narration buffer (ssv t6): a windowed tail of the running work
        # item's raw streamed deltas, folded by `_WorkSink.on_delta` via
        # `_fold_cortex_delta` (pure buffering — never a completion, c23) and
        # read by the presence engine's boundary beats through
        # `PresenceIO.delta_tail` so senses can author '<<higher self thought>>'
        # narration. Reset per work line (`_reset_presence_lane`); pure state —
        # an unarmed session folds it silently and renders nothing (h19).
        self._cortex_delta_tail = DeltaTail()
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

    def _park_talk_for_cortex(self, text: str) -> None:
        """Park one unarmed talk line for cortex at the next boundary.

        The senses talk lane has no front door on the default path (senses
        unarmed, ``config.senses is None``), so a typed/voiced line is written
        VERBATIM as flight guidance — the same seam colleague talk's raw-guide
        degrade uses — and a ``parked for cortex at the next boundary`` line is
        logged. Nothing is returned-and-dropped. A no-op when the talk lane is
        not armed (no flight to park onto)."""
        if self._talk_task_id is None:
            return
        with contextlib.suppress(Exception):
            flight.append_guidance(self.repo, self._talk_task_id, text)
        self._log("parked for cortex at the next boundary")
        if self.view == "ansi":
            self.emit()


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
    _chain_fn: _ChainFn = _default_chain,
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

    # Mode-profile explicit-knob guard (#336): mirrors cmd_work's guard
    # (work.py:1701-1703). Every session dispatch runs with mode="work"
    # (_run_work) — its profile's max_steps happens to equal today's built-in
    # default, so this looked behaviour-neutral, but apply_mode_profile still
    # refills any knob NOT named on config.explicit_knobs, so an operator
    # --max-steps was silently clobbered back to the profile default. Marking
    # it explicit here (once, at session start) keeps every dispatch honest.
    if getattr(args, "max_steps", None) is not None:
        config.explicit_knobs = frozenset({"max_steps"})

    # Episode chaining (indefinite-run t9): resolve the session's arming ONCE
    # at start — flag > env > config.json, via the SAME _resolve_chain_arming
    # the work front uses (the env/config legs already rode EngineConfig.resolve
    # above). Every work item this session dispatches inherits the pair
    # verbatim (c28); unarmed leaves chain_cap None — byte-identical dispatch.
    chain_cap, chain_armed = _resolve_chain_arming(args, config)

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
    # Post-construction (the documented attribute idiom — see _Session.__init__):
    # the chain seam is always injectable; the cap is set only when armed.
    session.chain_fn = _chain_fn
    if chain_armed:
        session.chain_cap = chain_cap
    # Voice lane opt-in (realtime-speech arc, t5, c27): --voice arms the WANTED
    # preference; capture still only starts when a work item's talk lane begins
    # AND the colour-TTY + senses + realtime gate passes. Unset → byte-identical.
    session._voice_wanted = bool(getattr(args, "voice", False))
    # Speak-only lane opt-in (task t8, h18/c22): --speak is the ONE other
    # writer of ``_speak_only`` besides ``/speak`` — no config default,
    # profile, or mode ever sets it. Unset → byte-identical (default OFF).
    session._speak_only = bool(getattr(args, "speak", False))
    return session.run(input_fn)


def cmd_session(args: argparse.Namespace) -> int:
    """Handler for the ``colleague session`` verb."""
    return run_session(args)


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
