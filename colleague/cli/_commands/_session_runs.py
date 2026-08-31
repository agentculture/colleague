"""``_Session``'s run finalization + read-only verbs, as a mixin.

Split out of ``colleague/cli/_commands/session.py`` (the 1000-line hard limit,
plan ``hard-1000-line-file-limit`` t17), holding the methods VERBATIM.

``run_senses_speakback`` is reached through :func:`_session_mod` — the suite
patches it as an attribute of the ``session`` module, so a from-import here
would leave those patches inert.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Optional, cast

from colleague import handoff
from colleague.artifact import artifact_dir
from colleague.artifact import write as _write_artifact
from colleague.config import EngineConfig
from colleague.contract import SensesBlock, Task, TaskResult


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


class _RunLaneMixin:
    """``_Session``'s per-run finalization + read-only verb lane.

    Re-saving the artifact with session-side senses records folded in, the
    split-run speak-back, and the ``work`` / ``explore`` / ``review`` runners.
    """

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
        # Display streaming (ssv t3): speak-back replies are BARE PROSE — no
        # JSON envelope — so the raw deltas ARE the display text: arm the
        # painter's sink directly (a raw pass-through), never the extractor.
        # The owned line is already disarmed here (work-item exit), so paints
        # take the live-TTY stdout path; the shaped whole-line render below is
        # unchanged either way.
        painter = self._senses_stream_sink()
        # Kwarg passed ONLY when armed — the unarmed path keeps the exact
        # zero-arg call shape strict test doubles already pin.
        stream_kwargs = {"on_delta": painter.on_display_delta} if painter is not None else {}
        pair = self._senses_engine(**stream_kwargs)
        if pair is not None:
            senses_config, engine = pair
            shaped, speakback_record = _session_mod().run_senses_speakback(
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
        # PR link (#169): one glance away on the post-run line — only when the
        # handoff actually opened one (never synthesized).
        pr = f" · PR: {result.pr_url}" if result.pr_url else ""
        self._log(f"{result.status}: {display} [{changed}]{branch}{pr}")
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
