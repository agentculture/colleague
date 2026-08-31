"""``_Session``'s realtime voice + speak-only lanes, as a mixin.

Split out of ``colleague/cli/_commands/session.py`` (the 1000-line hard limit,
plan ``hard-1000-line-file-limit`` t17), holding the methods VERBATIM.

``realtime`` is imported as a MODULE (never its functions by name), so
``monkeypatch.setattr(session_mod.realtime, "play_wav_bytes_local", …)`` —
which patches the shared ``colleague.realtime`` module object, not a session
attribute — keeps working unchanged.
"""

from __future__ import annotations

import contextlib

from colleague import realtime
from colleague.artifact import artifact_dir
from colleague.cli._commands._session_const import (
    _SPEAK_SENSES_UNARMED_LINE,
    _SPEAK_STATE_LINES,
    _SPEAK_UNAVAILABLE_LINE,
    _VOICE_OFFER_LINE,
    _VOICE_SENSES_UNARMED_LINE,
    _VOICE_STATE_LINES,
    _VOICE_UNAVAILABLE_LINE,
)
from colleague.cli._errors import CliError


class _VoiceLaneMixin:
    """``_Session``'s realtime voice + speak-only lanes.

    Availability probing, the c27 explicit opt-in gate, arming/draining mic
    capture, speaking a reply back, and the ``/voice`` / ``/speak`` toggles.
    """

    # ── voice lane (realtime-speech arc, t5) ─────────────────────────────────

    def _voice_available(self) -> bool:
        """Whether the config resolved a genuinely dialable realtime target.

        Absence (``EngineConfig.realtime is None``) means the voice lane makes
        ZERO dial attempts — the c27 contract that availability alone is the
        gate for the offer line, never for capture."""
        return getattr(self.config, "realtime", None) is not None

    def _voice_gate_open(self) -> bool:
        """The c27 arming gate: an interactive colour TTY (``view == "ansi"``) +
        senses armed + realtime available + not a session-wide ``--cortex-only``
        bypass. Reuses :meth:`_talk_lane_enabled` (the SAME colour-TTY + senses +
        not-cortex-only gate the typed talk lane uses) and adds realtime
        availability — so voice never arms anywhere the typed talk lane wouldn't,
        and off-TTY / no-senses / unavailable stays byte-identical."""
        return self._talk_lane_enabled() and self._voice_available()

    def _begin_voice_lane(self) -> None:
        """Arm (or merely OFFER) the voice lane for the running work item.

        c27, decisively: realtime *availability* NEVER starts capture. With the
        gate open and the operator NOT opted in, this renders exactly ONE offer
        line and dials nothing; only ``--voice`` / a prior ``/voice`` toggle
        (:attr:`_voice_wanted`) actually dials + captures (:meth:`_arm_voice_capture`).
        ``--voice`` asked for while realtime is unavailable prints exactly ONE
        honest notice, no dial. A strict no-op (byte-identical, zero output) when
        the talk lane isn't active — i.e. off-TTY / no senses / ``--cortex-only``,
        the same surfaces the typed talk lane stays silent on."""
        if getattr(self.config, "senses", None) is None:
            # qwen-direct (t7): --voice on the single-model default path — one
            # honest dormant line (colour TTY only; off-TTY stays byte-identical).
            if self._voice_wanted and not self._voice_unavailable_noticed and self.view == "ansi":
                self._voice_unavailable_noticed = True
                self._render_voice_line(_VOICE_SENSES_UNARMED_LINE)
            return
        if not self._talk_active:
            return
        if not self._voice_available():
            if self._voice_wanted and not self._voice_unavailable_noticed:
                self._voice_unavailable_noticed = True
                self._render_voice_line(_VOICE_UNAVAILABLE_LINE)
            return
        if self._voice_wanted:
            self._arm_voice_capture()
        elif not self._voice_offer_shown:
            self._voice_offer_shown = True
            self._render_voice_line(_VOICE_OFFER_LINE)

    def _arm_voice_capture(self) -> None:
        """Dial the EARS-ONLY realtime session and start mic capture, wiring final
        VAD transcripts into the SAME typed-input path (:meth:`_on_voice_transcript`).

        Consumes the t3/t4 building blocks verbatim: :func:`realtime.open_session`
        (ears-only; the spoken reply rides the batch TTS lane, never this socket)
        and :func:`realtime.start_capture` (server-VAD turn ends — no fixed window,
        no push-to-talk). Degrade-never-raise and ADDITIVE: a missing ``[voice]``
        extra (``CliError``), a failed dial (``None``), or a device that won't open
        (``start_capture`` → ``None``) degrades the lane to ``degraded`` with one
        honest line and leaves the TYPED lane fully usable — the run never fails."""
        if self._voice_session is not None:
            return  # already armed for this work line
        cfg = getattr(self.config, "realtime", None)
        try:
            session = realtime.open_session(cfg, on_transcript=self._on_voice_transcript)
        except CliError as exc:
            self._voice_state = "degraded"
            self._render_voice_line(
                f"voice · degraded · {exc.message} ({exc.remediation}) — typed lane only"
            )
            return
        except Exception:  # noqa: BLE001 - degrade-never-raise at the lane boundary
            self._voice_state = "degraded"
            self._render_voice_state()
            return
        if session is None:
            self._voice_state = "degraded"
            self._render_voice_state()
            return
        capture = realtime.start_capture(session, cfg)
        if capture is None:
            # No mic → this socket can never carry a voice turn (a transcript
            # only ever arrives from captured audio), so reap it NOW rather
            # than holding an idle WS + pump thread until _end_voice_lane().
            # Leaves the lane in exactly the dial-failure shape above —
            # ``_voice_session is None`` + ``degraded`` — so every downstream
            # reader (drain / speak / toggle) takes the identical path.
            self._voice_state = "degraded"
            with contextlib.suppress(Exception):
                session.close()  # bounded join
        else:
            self._voice_session = session
            self._voice_capture = capture
            self._voice_state = "live"
        self._render_voice_state()

    def _on_voice_transcript(self, text: str) -> None:
        """``on_transcript`` callback fired on the realtime PUMP thread: only
        enqueue the final VAD transcript (a thread-safe ``deque`` append). The
        main thread drains it at the next progress-sink boundary
        (:meth:`_drain_voice_transcripts`), so a voice turn never mutates session
        state concurrently with the work loop — the exact ``_enqueue_talk`` model
        the owned-line reader thread uses for a typed line."""
        stripped = (text or "").strip()
        if stripped:
            self._voice_transcripts.append(stripped)

    def _drain_voice_transcripts(self) -> None:
        """Drain pump-enqueued VAD transcripts into the IDENTICAL typed-input
        handler, on THIS (the main) thread, then speak senses' reply.

        This is the ONE senses path: each transcript goes through the same
        :meth:`_handle_talk_input` → :meth:`_talk_senses` → ``run_senses_talk`` +
        ``flight.append_guidance`` call sites a typed line takes, so a voice turn
        lands on ``TaskResult.senses.chat``/``injections`` identically. After the
        answer renders, :meth:`_speak_reply` synthesizes + plays it (additively).
        Also reflects a pump degrade into the honest lane state. A strict no-op
        when the voice lane never armed."""
        if self._voice_session is None:
            return
        if getattr(self._voice_session, "degraded", False) and self._voice_state not in (
            "degraded",
            "off",
        ):
            self._voice_state = "degraded"
            self._render_voice_state()
        while self._voice_transcripts:
            try:
                text = self._voice_transcripts.popleft()
            except IndexError:
                break
            if not text:
                continue
            with contextlib.suppress(Exception):
                self._dispatch_talk_line(text)  # THE identical typed-input + speak path

    def _speak_reply(self, text: str) -> None:
        """Speak senses' just-rendered REPLY text through the EXISTING batch TTS
        lane (:func:`colleague.voice.synthesize`) + local playback.

        Admission gate (task t8, h5): **(a live voice session) OR (the
        speak-only toggle, ``_speak_only``)** — either channel can arm spoken
        playback of a reply; with neither armed this is a fast no-op, so a
        default session (both off, h18) never imports ``colleague.voice``,
        never touches the filesystem, never calls out. c7/c27 stand
        untouched: nothing in this method ever constructs a realtime session
        or starts capture — it only *plays*.

        Replies-only (risk r1 / open q4): *text* is whatever the caller
        rendered as senses' reply — never narration, ack, or a presence/status
        line. The loop rung already narrows this at the source
        (:func:`_reply_text_from_turns` excludes narration structurally; see
        its docstring for the documented one-line widening spot); this method
        trusts its caller and speaks *text* verbatim.

        Playback path: with a live voice session, :func:`realtime.play_wav_bytes`
        HOLDS the half-duplex mute gate for the duration (there is a mic to
        protect from re-hearing the speaker). With speak-only alone — no
        session, no mic, nothing to mute — playback rides the session-free
        :func:`realtime.play_wav_bytes_local` instead (task t8's split): same
        device resolution (``RealtimeConfig.output_device``, absent/``None``
        falling back to the default output device), same
        degrade-never-raise contract, no gate.

        ADDITIVE, degrade-never-raise (h17): no reply / neither channel armed /
        no ``tts`` configured / a synth or playback failure all leave the
        already-rendered TEXT byte-identical — audio never affects the text
        path, and nothing here ever raises."""
        if not text:
            return
        if self._voice_session is None and not self._speak_only:
            return
        voice_cfg = getattr(self.config, "voice", None)
        tts_model = getattr(voice_cfg, "tts_model", None) if voice_cfg is not None else None
        if not tts_model:
            return
        from colleague import voice as voicemod

        try:
            out_dir = artifact_dir(self.repo)
            out_dir.mkdir(parents=True, exist_ok=True)
            self._voice_reply_n = getattr(self, "_voice_reply_n", 0) + 1
            out_path = out_dir / f"voice-reply-{self._voice_reply_n:04d}.wav"
            wav = voicemod.synthesize(
                text,
                tts_model=tts_model,
                base_url=getattr(voice_cfg, "tts_base_url", "") or "",
                out_path=out_path,
                api_key=getattr(voice_cfg, "api_key", "") or "",
            )
            if wav is None:
                return  # synth degraded — the text reply already stands, nothing to play
            realtime_cfg = getattr(self.config, "realtime", None)
            if self._voice_session is not None:
                realtime.play_wav_bytes(self._voice_session, str(wav), realtime_cfg)
            else:
                realtime.play_wav_bytes_local(str(wav), realtime_cfg)
        except Exception:  # nosec B110 # noqa: BLE001 - additive and degrade-never-raise
            pass

    def _voice_state_line(self) -> str:
        return _VOICE_STATE_LINES.get(self._voice_state, _VOICE_STATE_LINES["off"])

    def _render_voice_state(self) -> None:
        """Render the current honest lane state through the session's existing
        feed-line surface (the same ``_log`` + ``emit`` path the senses/presence
        lines use). ``muted`` and ``degraded`` render as DISTINCT lines."""
        self._render_voice_line(self._voice_state_line())

    def _render_voice_line(self, line: str) -> None:
        self._log(line)
        if self.view == "ansi":
            self.emit()

    def _toggle_voice(self) -> str:
        """``/voice`` — the c27 opt-in toggle, returning a confirmation string.

        Realtime unavailable → one honest notice, no dial. On a running lane the
        FIRST toggle opts in and starts capture (off → live); toggling again mutes
        (live → muted: ``session.mute`` + stop forwarding) and once more resumes
        (muted → live). ``degraded`` stays degraded — a toggle can't un-break a
        dead lane. Off a work item (no talk lane) it flips the wanted preference,
        which the next work item's talk lane honors."""
        if getattr(self.config, "senses", None) is None:
            return _VOICE_SENSES_UNARMED_LINE
        if not self._voice_available():
            return _VOICE_UNAVAILABLE_LINE
        self._voice_wanted = True
        session = self._voice_session
        if session is None:
            if self._talk_active and self._voice_gate_open():
                self._arm_voice_capture()
                return self._voice_state_line()
            return "voice · on · capture starts when the next work item runs"
        if self._voice_state == "muted":
            with contextlib.suppress(Exception):
                session.unmute()
            self._voice_state = "live"
        elif self._voice_state == "live":
            with contextlib.suppress(Exception):
                session.mute()
            self._voice_state = "muted"
        # degraded: no live/muted transition — the line still reports it honestly.
        self._render_voice_state()
        return self._voice_state_line()

    # ── speak-only lane (task t8) ─────────────────────────────────────────

    def _speak_available(self) -> bool:
        """Whether a genuinely dialable tts endpoint resolved.

        Speak-only needs ONLY ``tts_model`` — NEVER ``stt`` (c7: the mic wall
        stands untouched) and never realtime availability (speak-only has no
        session to dial in the first place)."""
        voice_cfg = getattr(self.config, "voice", None)
        return bool(getattr(voice_cfg, "tts_model", None)) if voice_cfg is not None else False

    def _toggle_speak(self) -> str:
        """``/speak`` — the speak-only opt-in toggle (task t8), returning a
        confirmation string the ``_slash`` dispatcher logs.

        TTS-speaks each senses REPLY while the operator only types — no mic,
        no realtime session, no half-duplex gate (see :meth:`_speak_reply`).
        Independent of ``/voice``/``--voice``: flips exactly ONE piece of
        state, ``_speak_only`` (default OFF, h18/c22 — this toggle plus
        ``--speak`` are its ONLY writers). No tts resolved → one honest
        notice through the SAME label·state·consequence line seam
        ``/voice`` uses, and stays off (never raises)."""
        if getattr(self.config, "senses", None) is None:
            return _SPEAK_SENSES_UNARMED_LINE
        if not self._speak_available():
            return _SPEAK_UNAVAILABLE_LINE
        self._speak_only = not self._speak_only
        return _SPEAK_STATE_LINES["on" if self._speak_only else "off"]

    def _end_voice_lane(self) -> None:
        """Tear down the voice lane on work-item / session exit (or a mid-capture
        interrupt), within bounded joins. Stops mic capture
        (:meth:`CaptureHandle.stop`) then closes the realtime session
        (:meth:`RealtimeSession.close`, a BOUNDED pump join) — both idempotent and
        never-raising, so teardown can never hang or leave an orphan thread. The
        wanted PREFERENCE persists (a later work item re-arms); only the live
        resources are reaped, and the state resets to ``off``."""
        capture = self._voice_capture
        session = self._voice_session
        self._voice_capture = None
        self._voice_session = None
        self._voice_transcripts.clear()
        self._voice_state = "off"
        if capture is not None:
            with contextlib.suppress(Exception):
                capture.stop()
        if session is not None:
            with contextlib.suppress(Exception):
                session.close()  # bounded join
