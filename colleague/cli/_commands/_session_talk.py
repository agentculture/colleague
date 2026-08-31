"""``_Session``'s concurrent senses talk lane, as a mixin.

Split out of ``colleague/cli/_commands/session.py`` (the 1000-line hard limit,
plan ``hard-1000-line-file-limit`` t17), holding the methods VERBATIM.

``run_senses_talk`` / ``senses_engine_config`` / ``make_senses_display_delta``
are reached through :func:`_session_mod` — the suite patches them as
attributes of the ``session`` module, and a from-import here would leave those
patches inert.
"""

from __future__ import annotations

import contextlib
import select
import sys
from typing import Optional

from agentfront.taui.widgets.prompt_input import plain_prompt

from colleague import flight
from colleague.cli._commands._input_line import OwnedInputLine
from colleague.cli._commands._session_input import supports_raw_mode
from colleague.cli._commands._session_support import _reply_text_from_turns
from colleague.contract import Task
from colleague.presence_engine import PresenceEngine, PresenceIO, build_presence_executor
from colleague.senses import TALK_STREAM_FIELD
from colleague.senses_loop import SensesLoopDriver


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


class _TalkLaneMixin:
    """``_Session``'s concurrent senses talk lane.

    Arming/disarming the lane and the owned input line, polling stdin at the
    progress-sink boundary, transcribing a voiced turn and relaying an
    operator line to senses. ``_park_talk_for_cortex`` — the unarmed-senses
    relay — stays on ``_Session`` itself in ``session.py``.
    """

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
            and _session_mod().senses_engine_config(self.config) is not None
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
        self._arm_owned_line()
        self._begin_voice_lane()

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
                # Cortex narration (ssv t6): the boundary beat reads the windowed
                # live-output excerpt _WorkSink.on_delta buffered — display-only
                # narration renders through the same `render` seam above.
                delta_tail=self._cortex_delta_excerpt,
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
                three_tier=getattr(self.config, "three_tier", False),
            )
        except Exception:  # noqa: BLE001 — a build failure degrades to the fixed-beat lane
            self._presence_engine = None

    def _end_talk_lane(self) -> None:
        """Disarm the talk lane on work-item exit (always cleared)."""
        self._talk_active = False
        self._talk_task_id = None
        self._talk_packet = None
        self._disarm_owned_line()
        self._end_voice_lane()

    # ── owned mid-run input line (at-home arc, t5) ───────────────────────────

    def _arm_owned_line(self) -> None:
        """Take ownership of the bottom input line for the running work item.

        Gated the same way as the raw-mode slash reader: a real POSIX colour TTY
        inside the live interactive loop (``supports_raw_mode(sys.stdin)`` +
        ``self._live``). A test seam (``_owned_line_streams``) forces arming over
        injected io streams so the wiring is exercisable without a TTY or a work
        run. Degrades to the cooked ``_poll_talk_lane`` path when the streams
        aren't a live TTY, or when ``start()`` reports a failed arm — so a session
        that ran before always still runs (h7)."""
        if self._owned_line is not None:
            return
        streams = self._owned_line_streams
        if streams is None:
            if not (self._live and supports_raw_mode(sys.stdin)):
                return
            streams = (sys.stdin, sys.stdout)
        stream_in, stream_out = streams
        line = OwnedInputLine(
            stream_in,
            stream_out,
            prompt=plain_prompt(context="colleague"),
            on_line=self._enqueue_talk,
        )
        # Everything already on screen (the echo + ack rendered before the line
        # armed) is treated as history — only lines added FROM HERE scroll above.
        self._printed_conv = len(self.state.conversation)
        if line.start():
            self._owned_line = line

    def _disarm_owned_line(self) -> None:
        """Stop the owned line (bounded, idempotent) and clear it back to the
        cooked path. A no-op when the line was never armed."""
        line = self._owned_line
        self._owned_line = None
        self._owned_talk_queue.clear()
        if line is not None:
            line.stop()

    def _enqueue_talk(self, text: str) -> None:
        """``on_line`` callback fired on the READER thread: only enqueue the
        submitted line (a thread-safe ``deque`` append). The main thread drains
        it at the next progress-sink boundary (:meth:`_poll_talk_lane`), so a
        talk message never mutates session state concurrently with the work
        loop — the same main-thread-handles-talk model as the cooked path."""
        stripped = text.strip()
        if stripped:
            self._owned_talk_queue.append(stripped)

    def _poll_talk_lane(self) -> None:
        """Thread-free stdin poll at a progress-sink boundary (t7).

        Non-blocking ``select`` (zero timeout) on stdin — NO threads (the whole
        live presence is a foreground cooperative poll, decision c). On an
        interactive TTY stdin is line-buffered (cooked), so ``select`` reports
        readable only once the operator presses Enter and ``readline`` then never
        blocks. A strict no-op unless the lane is armed; any error degrades to a
        silent no-op so a talk-lane hiccup never disturbs the running work item.

        When the owned input line is armed (t5) this does NOT read stdin — the
        reader thread owns it and enqueues each submitted line — so here it only
        drains that queue (on THIS, the main thread) into ``_handle_talk_input``,
        keeping talk handling single-threaded and each line verbatim.

        Voice turns (realtime-speech arc, t5) drain HERE too — at the SAME poll
        boundary a typed line is consumed — into the identical handler + a spoken
        reply (:meth:`_drain_voice_transcripts`), so there is ONE senses-talk
        path. A no-op unless the voice lane armed.

        A TYPED line dispatched here (either branch below) also rides
        :meth:`_dispatch_talk_line` (task t8) rather than calling
        :meth:`_handle_talk_input` bare — so the speak-only lane's spoken
        reply fires for a typed turn exactly as it does for a voice-originated
        one, gated by :meth:`_speak_reply`'s own admission check ((a live
        voice session) OR speak-only on) — a cheap no-op when neither is
        armed."""
        if not self._talk_active:
            return
        self._drain_voice_transcripts()
        if self._owned_line is not None:
            while self._owned_talk_queue:
                try:
                    text = self._owned_talk_queue.popleft()
                except IndexError:
                    break
                with contextlib.suppress(Exception):
                    self._dispatch_talk_line(text)
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
            self._dispatch_talk_line(text)

    def _handle_talk_input(self, text: str) -> None:
        """Route one operator line typed mid-run: ``/say FILE`` transcribes audio
        first, then senses answers + optionally relays (rendered labeled)."""
        if text.startswith("/say"):
            transcript = self._talk_transcribe(text[len("/say") :].strip())
            if not transcript:
                return
            text = transcript
        self._talk_senses(text)

    def _dispatch_talk_line(self, text: str) -> None:
        """Route one operator-submitted line — typed (either :meth:`_poll_talk_lane`
        branch) or a drained voice transcript (:meth:`_drain_voice_transcripts`)
        — through :meth:`_handle_talk_input`, then speak the rendered reply
        (task t8).

        Resets ``_last_talk_reply`` FIRST so a turn that produces no new
        answer (e.g. a failed ``/say``) never re-speaks a stale reply left
        over from the previous turn. :meth:`_speak_reply` is the single
        admission gate for whether anything actually plays — (a live voice
        session) OR (the speak-only toggle, ``_speak_only``) — so calling it
        here unconditionally, from every dispatch site, is a safe, cheap
        no-op whenever neither channel is armed (the h18 default-off floor)."""
        self._last_talk_reply = ""
        self._handle_talk_input(text)
        self._speak_reply(self._last_talk_reply)

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
        onto the artifact at finalize (:meth:`_finalize_split_run`).

        The rendered answer is captured onto ``_last_talk_reply`` so a
        voice-originated turn (t5) can speak it back (additive) — harmless for a
        typed turn, which never triggers playback."""
        if self._presence_engine is not None:
            turns = self._presence_engine.on_operator_message(text)
            self._last_talk_reply = _reply_text_from_turns(turns)
            if self.view == "ansi":
                self.emit()
            return
        # Display streaming (ssv t3): a mid-run talk reply grows in place above
        # the owned input line while it generates (the talk reply carries its
        # text under "answer" — TALK_STREAM_FIELD binds the streaming key to
        # run_senses_talk's own required_key). The final rendered line still
        # comes from the unchanged whole-reply path below (`_log` + emit),
        # which erases the last transient paint in place.
        painter = self._senses_stream_sink()
        # Kwarg passed ONLY when armed (the _dispatch_work lineage_kwargs
        # idiom) — the unarmed path keeps the exact zero-arg call shape.
        stream_kwargs = (
            {
                "on_delta": _session_mod().make_senses_display_delta(
                    painter.on_display_delta, field=TALK_STREAM_FIELD
                )
            }
            if painter is not None
            else {}
        )
        pair = self._senses_engine(**stream_kwargs)
        if pair is None:
            # Senses unarmed (config.senses None) — the talk lane has no front
            # door on the default path, so the typed/voiced line is PARKED for
            # cortex at the next boundary: written VERBATIM as flight guidance
            # (the same seam colleague talk's raw-guide degrade uses), never
            # returned-and-dropped.
            self._park_talk_for_cortex(text)
            return
        senses_config, engine = pair
        record = _session_mod().run_senses_talk(
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
        # Streaming containment (task t5): a completion that degraded AFTER
        # painting at least one transient row finalizes that partial text +
        # the cut-stream marker (below) instead of the generic fallback
        # answer — the reply the operator already watched streaming in is
        # never silently replaced by an unrelated canned message ("senses is
        # unavailable right now."). A turn that never streamed (painter
        # unarmed, or armed but nothing painted yet) takes the unchanged
        # fallback-answer path — byte-identical to before this task.
        cut = bool(record["degraded"]) and self._finalize_cut_stream(painter)
        self._last_talk_reply = (
            painter.painted_text if cut and painter is not None else record["answer"]
        )
        self._history_append("operator", text)
        self._history_append("senses", self._last_talk_reply)
        if not cut:
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
