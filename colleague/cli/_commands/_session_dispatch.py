"""``_Session``'s loop + work/plan dispatch lane, as a mixin.

Split out of ``colleague/cli/_commands/session.py`` (the 1000-line hard limit,
plan ``hard-1000-line-file-limit`` t17), holding the methods VERBATIM.

``_WorkSink`` is reached through a LAZY module-attribute lookup
(:func:`_session_mod`) rather than an import: it is pinned to ``session.py``
by ``tests/test_talking_to_one_boundary.py`` and patched there as
``session_mod._WorkSink.on_delta``.
"""

from __future__ import annotations

import contextlib
import io
import json
from dataclasses import replace
from pathlib import Path
from typing import Callable, Iterator, Optional

from agentfront.taui.state import WorkItem

from colleague import flight, handoff
from colleague.attribution import cortex_working_line
from colleague.cli._banner import emit_banner
from colleague.cli._commands import work as _work_mod
from colleague.cli._commands._session_actions import _CONFIG_ACTIONS
from colleague.cli._commands._session_const import _QUIT_TOKENS
from colleague.cli._commands._session_input import CYCLE_MODE
from colleague.cli._commands._session_slash import (
    _HELP_COMPACT,
    _HELP_TEXT,
    _HELP_VERBOSE,
    _INTROSPECT,
)
from colleague.cli._commands._session_support import _T, _read_line, _resolve_selection
from colleague.cli._errors import CliError
from colleague.config import EngineConfig
from colleague.contract import Task, TaskResult
from colleague.heal import COMMIT, STASH, parse_heal_choice, render_heal_prompt
from colleague.session_intent import PLAN, classify_intent
from colleague.session_modes import next_mode, route_for


def _session_mod():
    """The ``session`` module object, looked up LAZILY at call time.

    Every name reached through this helper is one the suite patches as
    ``monkeypatch.setattr(session_mod, "<name>", ...)``. A bare-name call
    resolves through the ``__globals__`` of the module the calling function is
    TEXTUALLY defined in, so a ``from colleague.senses import run_senses_talk``
    here would (a) be dead weight and (b) silently defeat those patches — they
    would stay green while intercepting nothing. Looking the name up as an
    ATTRIBUTE of the ``session`` module at call time keeps every one of them
    effective (the same rule ``_work_chain.py`` follows for
    ``work_mod.execute_work``). The import is function-local because
    ``session`` imports THIS module at import time.
    """
    from colleague.cli._commands import session as _session

    return _session


class _DispatchMixin:
    """``_Session``'s input loop and work/plan dispatch lane.

    The blocking ``run`` loop, slash routing, the dirty-tree heal offer, the
    tracked-dispatch wrapper and ``_dispatch_work`` — the one place a session
    line becomes an ``execute_work`` / ``execute_work_chain`` call.
    """

    # ── the loop ─────────────────────────────────────────────────────────────

    def run(self, input_fn: Optional[Iterator[str]]) -> int:
        emit_banner(self.err, json_mode=self.json_mode)
        live_ansi = input_fn is None and self.view == "ansi"
        # Only a genuine live interactive colour-TTY loop may take ownership of
        # the bottom input line (t5) — a test-seam iterator / static view keeps
        # the cooked path, byte-identical.
        self._live = live_ansi
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
        # Safety net: a work item's own finally already disarms the owned line +
        # reaps the voice lane, but a break out of the loop mid-arm (or a future
        # path) must never leave the reader thread or the realtime pump running.
        # Both stops are bounded + idempotent.
        self._disarm_owned_line()
        self._end_voice_lane()
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

        if verb == "continue":
            self._slash_continue(rest[0] if rest else "last")
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

    def _slash_continue(self, ref: str) -> None:
        """Resume a cut work item from its persisted artifact (#167).

        The session leg of the continue affordance: the SAME resolve path
        ``work --continue`` uses (a bare ``/continue`` defaults to ``last``),
        dispatched through the ordinary work path so the cockpit, heal guard,
        and artifact writes all behave exactly like a fresh dispatch. The
        ok-guard error text is the CLI's own (``ContinuationError`` verbatim),
        so an agent driving the session off-TTY parses one shape.
        """
        from colleague.continuation import ContinuationError, prior_task_text, resolve_continuation

        ref = (ref or "last").strip() or "last"
        warnings: list[dict] = []
        try:
            prior_id, seed = resolve_continuation(
                self.repo,
                ref,
                agents_armed=bool(getattr(self.config, "agents", False)),
                warnings=warnings,
            )
        except ContinuationError as exc:
            self._error(f"error: {exc}")
            return
        # Re-apply the prior run's recorded acting-seat rung (effort-v4 t8,
        # c32) — the same leg work --continue takes. An explicit /effort this
        # session wins (the _effort_explicit marker, c25): the re-apply
        # stands down rather than clobbering the operator's choice. The
        # mismatch warning (h19) is staged on config.continuation_warnings
        # (drained onto TaskResult.warnings by _stamp_run_metadata) and
        # printed with the other continuation diagnostics below.
        if not getattr(self, "_effort_explicit", False):
            from colleague.cli._commands._listing import reapply_recorded_effort

            reapply_recorded_effort(self.config, self.repo, prior_id, warnings=warnings)
        for warning in warnings:
            self._error(f"continuation: {warning['detail']}")
        self._log(f"→ continue: resuming {prior_id}")
        if not self._heal_dirty_tree_if_needed():
            return
        task = Task.new(str(self.repo), seed, engine=self.engine_name)
        self._continued_from_next = prior_id
        # c22/h15/h3: the ORIGINAL brief, propagated onto the resumed run's
        # artifact — never this seed.
        self._continuation_task_text_next = prior_task_text(self.repo, prior_id)
        self._run_work(task, None)

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
        # Dirty-tree heal (#168): a colour-TTY session that KNOWS the dispatch
        # would hit the #149 refusal offers the one explicit choice now, BEFORE
        # the senses ack and the doomed run. Off-TTY / --json / allow-dirty
        # sessions fall through byte-identically (the runtime guard still rules).
        if not self._heal_dirty_tree_if_needed():
            return
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
            self._log(cortex_working_line(three_tier=self.config.three_tier))
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

    def _heal_dirty_tree_if_needed(self) -> bool:
        """Offer the three-choice dirty-tree heal before a doomed dispatch (#168).

        Returns ``True`` when the dispatch may proceed: tree clean, the session
        already runs ``--allow-dirty``, not a live colour TTY (the prompt never
        blocks a pipe — the dispatch then meets today's refusal unchanged), the
        operator chose commit-onto-work-branch (a ONE-RUN waiver, never sticky),
        or the stash succeeded. Returns ``False`` when the operator aborted
        (empty input / unknown / explicit abort) or the stash failed — the
        dispatch is cancelled with the tree untouched. Every choice's
        consequence + undo is in the prompt copy itself (colleague/heal.py).
        """
        if self.allow_dirty or not self._live or self._read_next is None:
            return True
        if not handoff.working_tree_dirty(self.repo):
            return True
        self.out(render_heal_prompt())
        # The live ANSI reader can yield the CYCLE_MODE sentinel (shift-tab) —
        # not a string; re-read past it (mode cycling has no meaning inside the
        # heal prompt). EOF/None aborts, matching empty input.
        raw = self._read_next()
        while raw is CYCLE_MODE:
            raw = self._read_next()
        choice = parse_heal_choice(str(raw or "").strip())
        if choice is COMMIT:
            self._heal_allow_dirty_once = True
            self._log(
                "healing: your uncommitted tracked edits will ride the work branch "
                "(undo there: git reset --soft HEAD~1)"
            )
            return True
        if choice is STASH:
            ref = handoff.heal_stash(self.repo)
            if ref is None:
                self._error("stash failed — dispatch cancelled; your edits are untouched")
                return False
            self._log(f"healing: stashed as {ref} — recover with: git stash pop")
            return True
        self._log("dispatch cancelled — your edits are untouched")
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
        heal_waiver = self._heal_allow_dirty_once
        self._heal_allow_dirty_once = False
        continued_from = self._continued_from_next
        self._continued_from_next = None
        continuation_task_text = self._continuation_task_text_next
        self._continuation_task_text_next = None
        # Passed ONLY when set: an ordinary dispatch keeps the exact work_fn
        # call shape stable for strict test doubles / injected work_fns.
        lineage_kwargs = (
            {"continued_from": continued_from, "continuation_task_text": continuation_task_text}
            if continued_from
            else {}
        )

        def _single_episode() -> tuple[TaskResult, Path]:
            return self.work_fn(
                repo=self.repo,
                engine_name=self.engine_name,
                task=task,
                open_pr=open_pr,
                allow_dirty=self.allow_dirty or heal_waiver,
                **lineage_kwargs,
                base=self.base,
                config=config,
                command_name=command_name,
                display=_work_mod.DisplayOptions(sink=_session_mod()._WorkSink(self)),
                mode=mode,
            )

        def _armed_chain() -> tuple[TaskResult, Path]:
            # Episode chaining (indefinite-run t9): an armed session dispatches
            # through the SAME chain loop `work --until-done` drives
            # (execute_work_chain) — identical semantics (handoff-once c26,
            # tree carry c6, verbatim inheritance c28), never a session-only
            # fork. Same kwargs shape as the single-episode call, plus the cap
            # resolved once at session start.
            return self.chain_fn(
                repo=self.repo,
                engine_name=self.engine_name,
                task=task,
                open_pr=open_pr,
                allow_dirty=self.allow_dirty or heal_waiver,
                **lineage_kwargs,
                base=self.base,
                config=config,
                command_name=command_name,
                progress_sink=_session_mod()._WorkSink(self),
                mode=mode,
                cap=self.chain_cap,
            )

        pair = self._run_tracked(
            task.id,
            _armed_chain if self.chain_cap is not None else _single_episode,
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
