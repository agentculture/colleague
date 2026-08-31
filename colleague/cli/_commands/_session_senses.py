"""``_Session``'s cortex/senses lane, as a mixin.

Split out of ``colleague/cli/_commands/session.py`` (the 1000-line hard limit,
plan ``hard-1000-line-file-limit`` t17), holding the methods VERBATIM.

**Every patched senses/front-door name is reached through
:func:`_session_mod`**, never a from-import: ``run_senses_intake``,
``run_senses_update``, ``run_frontdoor``, ``senses_engine_config``,
``make_senses_display_delta`` and ``_stdout_is_tty`` are all patched by the
suite as attributes of the ``session`` module, and a bare-name call here would
resolve through THIS module's ``__globals__`` — leaving those patches green
but inert. See :func:`_session_mod`'s docstring for the rule.
"""

from __future__ import annotations

import contextlib
import time
from typing import Callable, Optional

from colleague import registry
from colleague.attribution import senses_line
from colleague.cli._commands._session_const import (
    _ACK_DISPATCH_NOTICE,
    _NARRATION_DELTA_CHARS,
    _STREAM_CUT_MARKER,
)
from colleague.cli._commands._session_input import CYCLE_MODE
from colleague.cli._commands._session_support import _SensesStreamPainter
from colleague.cockpit_run import DeltaTail, fold_delta
from colleague.config import resolve_lobes_gateway_url, resolve_presence_rung
from colleague.contract import SensesRecord, Task
from colleague.frontdoor import CORTEX, classify_frontdoor, cortex_frontdoor_outcome
from colleague.presence import is_go_word, should_clarify, should_update
from colleague.senses import FRONTDOOR_STREAM_FIELD, UPDATE_POINT


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


class _SensesMixin:
    """``_Session``'s cortex/senses split — intake, front door, narration.

    The senses engine resolution, the streaming painter sink, intake +
    clarify, the deterministic front door, the presence ack and the
    cadence-gated proactive update fired from ``_WorkSink.__call__``.
    """

    # ── cortex/senses split (t8) ─────────────────────────────────────────────

    def _senses_engine(self, *, on_delta: Optional[Callable[[str], None]] = None):
        """Return ``(senses_config, engine)`` for a senses call, or ``None``.

        ``None`` when no senses model is resolved (byte-identical) or the engine
        cannot be loaded — the caller then proceeds cortex-only. Both intake and
        speak-back go through this one seam.

        ``on_delta`` (ssv t3) arms display streaming for THIS call's completion
        (forwarded verbatim to :func:`senses_engine_config`, which never
        inherits the parent's sink — t2). Default ``None`` keeps every caller
        that doesn't name it — intake, clarify, proactive updates, the
        presence-engine build — on the blocking path, byte-identical."""
        senses_config = _session_mod().senses_engine_config(self.config, on_delta=on_delta)
        if senses_config is None:
            return None
        try:
            engine = registry.load(self.engine_name)
        except Exception:  # noqa: BLE001 - an unloadable engine → proceed cortex-only
            return None
        return senses_config, engine

    def _senses_stream_sink(self) -> Optional[_SensesStreamPainter]:
        """The ssv-t3 arming decision, in ONE place: a fresh painter — senses
        display streaming arms — ONLY on a live colour-TTY conversation
        surface. Two qualifying shapes: the owned input line is armed (a
        mid-run talk turn — paints ride its lock-protected ``stream_paint``),
        or the genuine live ANSI loop is between prompts on a real stdout TTY
        (a front-door / speak-back turn — paints write the same transient
        sequence to stdout). Everything else — piped, ``--json``, the
        Markdown tier, a scripted/direct-construction session — returns
        ``None``: ``on_delta`` stays unarmed, the engine takes its blocking
        path, and output stays byte-identical to today (h12)."""
        if self.view != "ansi" or self.json_mode:
            return None
        if self._owned_line is not None:
            return _SensesStreamPainter(self)
        if self._live and _session_mod()._stdout_is_tty():
            return _SensesStreamPainter(self)
        return None

    def _finalize_cut_stream(self, painter: Optional[_SensesStreamPainter]) -> bool:
        """Contain a senses turn whose stream died mid-reply (ssv task t5,
        covers c25/h20) — the turn seam every streamed surface degrades
        through.

        When *painter* already painted at least one transient row THIS turn
        (``painter.paints > 0``), the partial text it holds
        (:attr:`_SensesStreamPainter.painted_text`) is finalized as a REAL
        line (:meth:`_log` — a newline-terminated conversation entry, never
        overwritten by a later transient paint) followed by the ONE legible
        marker line (:data:`_STREAM_CUT_MARKER`), printed via :meth:`_error`
        — the session's EXISTING ``error:`` seam/prefix, reused verbatim,
        never a new one. This is how a streamed reply that never finished is
        contained: the operator sees exactly what senses had said so far,
        plus an honest note that it was cut short — never a traceback, and
        never silently replaced by an unrelated canned fallback message.

        The caller decides WHEN to call this — typically ``degraded and
        painter is not None`` — reusing the run function's own ``degraded``
        signal, which is itself derived from the engine's stream-
        completeness accounting (a missing terminal frame / finish_reason
        surfaces as an exception the run function's own try/except already
        degrades into that flag, colleague/engines/vllm_openai.py's
        ``_StreamIncomplete`` chief among the shapes). This function never
        re-derives completeness itself, only acts on what's already known.

        Returns ``True`` when it fired (the caller then skips ITS OWN
        generic fallback-answer render for this turn — the partial text +
        marker already said everything there is to say). Returns ``False``
        — a strict no-op — when nothing was ever painted (``painter is
        None`` or ``painter.paints == 0``): the caller's existing
        fallback-text render stays byte-identical to before this task (the
        golden, no-streaming path).

        Never raises: a rendering hiccup here must never crash the turn or
        let a traceback escape (AC1) — suppressed exactly like every other
        painter write in this module.
        """
        if painter is None or painter.paints == 0:
            return False
        with contextlib.suppress(Exception):
            self._log(senses_line(painter.painted_text))
            self._error(_STREAM_CUT_MARKER)
        return True

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
        packet, record = _session_mod().run_senses_intake(
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
        # Display streaming (ssv t3): on a live colour TTY the direct answer
        # renders as ONE growing `senses:` line while it generates. The
        # front-door reply carries its text under "answer" (the same key
        # run_senses_frontdoor's parser requires — FRONTDOOR_STREAM_FIELD
        # binds them), decoded incrementally by the t2 extractor adapter.
        painter = self._senses_stream_sink()
        # Kwarg passed ONLY when armed (the _dispatch_work lineage_kwargs
        # idiom): the unarmed path keeps the exact zero-arg call shape strict
        # test doubles already pin.
        stream_kwargs = (
            {
                "on_delta": _session_mod().make_senses_display_delta(
                    painter.on_display_delta, field=FRONTDOOR_STREAM_FIELD
                )
            }
            if painter is not None
            else {}
        )
        pair = self._senses_engine(**stream_kwargs)
        if pair is None:
            return None
        senses_config, engine = pair
        outcome = _session_mod().run_frontdoor(
            text,
            senses_config=senses_config,
            make_complete=engine.make_complete,
            make_count_tokens=engine.make_count_tokens(senses_config),
            history=list(self._history) or None,
            # #311: persist a standalone auditable record of this senses-direct turn
            # (it has no TaskResult) beside the operator repo's .colleague/ artifacts.
            record_repo=str(self.repo),
            # task t10: ground a senses-direct answer in the REAL resolved
            # runtime state (config is the ORIGINAL main config, never the
            # senses-replaced senses_config above) so "what model are you?"
            # answers with the actual resolved model ids.
            config=self.config,
            gateway_url=resolve_lobes_gateway_url(self.repo),
        )
        # Streaming containment (task t5): a degraded front-door turn already
        # falls through to cortex with NO senses-direct render at all (by
        # design — an unanswerable/ambiguous turn defers to cortex, c19) —
        # but a partial paint from BEFORE the degrade must still be
        # finalized, or the next redraw silently wipes it with no
        # explanation. A strict no-op when nothing painted this turn.
        if outcome.degraded:
            self._finalize_cut_stream(painter)
        return outcome

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
        # Speak-only / voice speak-back (ssv t8 + t12 proof C): the front door
        # is the most common conversational turn, and it rendered silently —
        # only the talk lane spoke. Same single seam, same admission gate
        # (no-op unless /speak, --speak, or a live voice session).
        self._speak_reply(outcome.answer or "")
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
        # The cortex narration buffer resets per work line too (ssv t6) — a
        # stale excerpt from the previous run must never feed a new line's beat.
        self._cortex_delta_tail = DeltaTail()

    def _fold_cortex_delta(self, chunk: str) -> None:
        """Fold ONE raw cortex delta chunk into the narration buffer (ssv t6).

        PURE state (c23): sanitize + append + keep the trailing
        :data:`_NARRATION_DELTA_CHARS` window (the cockpit's own ``fold_delta``,
        wider window). Called from ``_WorkSink.on_delta`` — inside cortex's
        streaming read — so it must never issue a completion, render, block, or
        raise; any failure keeps the previous tail (narration is presentation,
        never control)."""
        try:
            self._cortex_delta_tail = fold_delta(
                self._cortex_delta_tail, chunk, width=_NARRATION_DELTA_CHARS
            )
        except Exception:  # nosec B110 # noqa: BLE001 - capture must never disturb the stream
            pass

    def _cortex_delta_excerpt(self) -> str:
        """The windowed live-output excerpt a boundary beat narrates from (ssv t6).

        Read by the presence engine (``PresenceIO.delta_tail``) at each boundary;
        prompt-input for that one beat only — never accumulated into senses'
        history (c14)."""
        return self._cortex_delta_tail.text

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
            refined, refine_record = _session_mod().run_senses_intake(
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
            record = _session_mod().run_senses_update(
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
