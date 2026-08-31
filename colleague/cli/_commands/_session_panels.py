"""``_Session``'s cockpit panels + render lane, as a mixin.

Split out of ``colleague/cli/_commands/session.py`` (the 1000-line hard limit,
plan ``hard-1000-line-file-limit`` t17). ``_Session`` mutates shared instance
state across ~85 methods, so the lanes come out as MIXINS holding the methods
VERBATIM — never a value-passing rewrite. This one owns the one shared
:class:`CockpitState`: how it is built, folded and painted.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from typing import Optional, cast

from agentfront.taui.events import UserInput
from agentfront.taui.reducer import reduce
from agentfront.taui.render.ansi_flat import render_flat as _render_flat
from agentfront.taui.render.layout import detect_width
from agentfront.taui.render.markdown import render_markdown as _render_markdown
from agentfront.taui.state import Header, Panel, PanelItem, Status
from agentfront.taui.state import TAUIState as CockpitState
from agentfront.taui.widgets.prompt_input import plain_prompt

from colleague import cockpit, feedback, icons, layers
from colleague.cli._commands._session_const import (
    _ACTIVE_RUN_PANEL_ID,
    _CAPACITY_BUDGET_ID,
    _CAPACITY_MODE_ID,
    _CAPACITY_PANEL_ID,
    _CAPACITY_PROFILE_ID,
    _CAPACITY_SIGNAL_ID,
    _CLEAR_HOME,
    _CONVERSATION_PANEL_ID,
    _GOAL_ITEM_ID,
    _LAST_RUN_PANEL_ID,
    _NEXT_ITEM_ID,
    _NEXT_PANEL_ID,
)
from colleague.cli._commands._session_slash import (
    _SLASH_COMMANDS,
    _SLASH_GROUPS,
    _cursor_back_to_input,
    _slash_tag_style,
    build_slash_panels,
    filter_slash,
)
from colleague.cli._commands._session_support import (
    _coerce_strs,
    _goal_text,
    _mode_profile_text,
    _mode_status_text,
)
from colleague.cockpit_run import RunState, observed_ledger, reconcile
from colleague.contract import TaskResult
from colleague.policy import load_policy
from colleague.session_modes import mode_affordance_line, mode_facts, mode_facts_fragment
from colleague.telemetry import TelemetryConfig


class _PanelsMixin:
    """``_Session``'s cockpit-state lane: build it, mutate it, render it.

    State construction (``_initial_state``/``_facts``), every panel builder
    (policy, context, capacity, next, active-run, last-run), the feed/status
    mutators (``_log``/``_error``/``_refresh_status``) and the three emit paths
    (``emit``, the owned-line repaint, the live-ANSI slash popup reader).
    """

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
                # PR link (#169): present ONLY when the handoff actually returned
                # one — a local-only run renders exactly the four items above.
                *(
                    [
                        PanelItem(
                            id="last.pr",
                            label=icons.label("PR", "run", self._icons_mode),
                            status=led.pr_url,
                        )
                    ]
                    if led.pr_url
                    else []
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
        # THE mid-run choke point (at-home arc, t5): while the talk lane owns the
        # bottom input line, every mid-run redraw — the _WorkSink's per-step feed,
        # the senses ack/update/answer lines, everything that funnels through
        # emit() — scrolls the NEW conversation lines ABOVE the owned line via
        # print_above instead of a full-frame clear-home redraw that would clobber
        # the operator's in-progress cooked typing. A pure display-path change:
        # state is untouched here, so the #206 invariant holds (no step-count
        # advance, no feed line added). Owned line is armed only mid-run on a live
        # colour TTY, so at idle / off-TTY this is byte-identical.
        if self._owned_line is not None:
            self._emit_over_owned_line()
            return
        self.chrome(self._frame())

    def _emit_over_owned_line(self) -> None:
        """Scroll conversation lines added since the last emit ABOVE the owned
        input line (``print_above`` repaints the operator's pending buffer below
        each one). Only the DELTA is printed — a full-frame redraw would wipe the
        owned line and the in-progress typing. A no-op if the line disarmed
        mid-call (``print_above`` itself degrades to a plain write when disarmed)."""
        line = self._owned_line
        if line is None:
            return
        conv = self.state.conversation
        for cline in conv[self._printed_conv :]:
            line.print_above(cline.render())
        self._printed_conv = len(conv)

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
