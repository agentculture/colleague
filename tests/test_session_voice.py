"""Realtime-speech arc (task t5): the session voice lane.

Pins the t5 contract on the interactive ``colleague session`` cockpit:

* **c27 — the mic is NEVER hot by default.** Realtime being *available* renders
  ONE offer line and dials nothing; capture starts ONLY on the ``--voice`` flag
  or a ``/voice`` toggle, and ``/voice`` again mutes (``session.mute`` + stop
  forwarding). ``--voice`` with realtime unavailable is one honest notice, no dial.
* **ONE senses path.** A final VAD transcript is ENQUEUED on the realtime pump
  thread and drained at the SAME poll boundary a typed line is — through the
  identical ``_handle_talk_input`` → ``_talk_senses`` → ``run_senses_talk`` +
  ``flight.append_guidance`` call sites — so a voice turn lands on
  ``TaskResult.senses.chat``/``injections`` IDENTICALLY to a typed turn; senses'
  reply then plays as audio (``voice.synthesize`` + ``realtime.play_wav_bytes``,
  the batch lane) with the text still rendered.
* **Honest lane state.** ``off`` / ``live`` / ``muted`` / ``degraded`` render
  through the session's existing feed-line surface, with ``muted`` visibly
  DIFFERENT from ``degraded`` (the cockpit label·state·consequence policy).
* **Bounded teardown.** Session exit / work-item end / a mid-capture interrupt
  reap the capture handle + realtime session within their bounded joins on a
  REAL PTY-driven loop — no hang, no orphan thread.
* **Off-TTY / unarmed byte-identical.** Zero new output when realtime is ``None``
  or the colour-TTY gate fails.

Fakes injected at the ``open_session`` / ``start_capture`` / ``play_wav_bytes``
seams keep every test hardware-free and network-free — the session logic is
provable without the ``[voice]`` extra (which CI's plain-``uv sync`` test job
does not install — only the coverage job does).
GOTCHA (tests/conftest.py scrubs COLLEAGUE_* env): arm per-test via monkeypatch.
"""

from __future__ import annotations

import collections
import os
import threading
import time
from pathlib import Path

import pytest

from colleague import flight
from colleague import voice as voicemod
from colleague.cli._commands import session as session_mod
from colleague.cli._commands.session import (
    SensesSessionOptions,
    SessionIO,
    _reply_text_from_turns,
    _Session,
)
from colleague.config import EngineConfig, RealtimeConfig, SensesConfig, VoiceConfig
from colleague.contract import OK, Task, TaskResult


class _CollectingOut:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, *args: object, **kwargs: object) -> None:
        self.lines.append(" ".join(str(a) for a in args))

    def text(self) -> str:
        return "\n".join(self.lines)


class _FakeEngine:
    """Stands in for a loaded engine: the talk lane only reads its two seams."""

    def make_complete(self, config, tools=None):
        return lambda messages: None

    def make_count_tokens(self, config):
        return lambda messages: 0


class _FakeRealtimeSession:
    """Mimics :class:`colleague.realtime.RealtimeSession`'s public surface.

    ``close()`` is a BOUNDED, idempotent reap of a REAL daemon thread parked on
    an idle pipe read — exactly the shape the real pump has — so the teardown
    tests measure a genuine bounded join + no orphan, not a fake ``StringIO``
    that returns at EOF immediately (the #315 lesson).
    """

    def __init__(self, *, on_transcript=None, park: bool = False) -> None:
        self.on_transcript = on_transcript
        self._muted = False
        self.degraded = False
        self.degrade_reason = None
        self.closed = False
        self.sent: list[bytes] = []
        self._stop = threading.Event()
        self._read_fd = None
        self._thread = None
        if park:
            r, w = os.pipe()
            self._read_fd = r
            self._write_fd = w  # kept open so the read genuinely blocks (idle pipe)
            self._thread = threading.Thread(
                target=self._park_body, name="fake-realtime-pump", daemon=True
            )
            self._thread.start()

    def _park_body(self) -> None:
        # Poll-wake on the stop event, mirroring the real pump's settimeout loop.
        while not self._stop.is_set():
            r, _, _ = __import__("select").select([self._read_fd], [], [], 0.05)
            if r:
                try:
                    if not os.read(self._read_fd, 1):
                        return
                except OSError:
                    return

    def mute(self) -> None:
        self._muted = True

    def unmute(self) -> None:
        self._muted = False

    @property
    def muted(self) -> bool:
        return self._muted

    def send_audio(self, pcm16: bytes) -> bool:
        if self._muted:
            return False
        self.sent.append(pcm16)
        return True

    def close(self, *, timeout: float = 2.0) -> None:
        self.closed = True
        self._stop.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        for fd in (getattr(self, "_write_fd", None), self._read_fd):
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass

    def pump_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()


class _FakeCapture:
    def __init__(self) -> None:
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


def _realtime_config() -> RealtimeConfig:
    return RealtimeConfig(available=True, ws_url="ws://rig/v1/realtime", api_key="k")


def _config(*, realtime: bool = True, senses: bool = True, voice: bool = True) -> EngineConfig:
    config = EngineConfig.resolve(model="cortex-model")
    if senses:
        config.senses = SensesConfig(
            model="senses-model", base_url="http://senses", api_key="k", context_budget=24000
        )
    if voice:
        config.voice = VoiceConfig(
            stt_model="stt",
            tts_model="tts",
            stt_base_url="http://stt",
            tts_base_url="http://tts",
            api_key="k",
        )
    if realtime:
        config.realtime = _realtime_config()
    return config


def _session(tmp_path: Path, *, view: str = "ansi", config=None, cortex_only: bool = False):
    out, err = _CollectingOut(), _CollectingOut()
    result = TaskResult(task_id="t", status=OK, summary="s")

    def _fake_work(**kwargs: object):
        return result, Path(str(tmp_path)) / ".colleague" / "art.json"

    sess = _Session(
        repo=tmp_path,
        engine_name="mock",
        open_pr=False,
        base="main",
        config=config if config is not None else _config(),
        json_mode=False,
        view=view,
        io=SessionIO(out=out, err=err),
        work_fn=_fake_work,
        senses_options=SensesSessionOptions(cortex_only=cortex_only),
    )
    return sess, out, err


def _install_seams(monkeypatch, *, capture_ok: bool = True, session_park: bool = False):
    """Monkeypatch open_session / start_capture at the session's realtime seam.

    Returns a dict recording ``open_session`` / ``start_capture`` calls and the
    fake session/capture handed back, so a test can assert the mic never went
    hot from availability alone.
    """
    rec: dict = {"open_calls": [], "capture_calls": [], "session": None, "capture": None}

    def _open(cfg, *, on_transcript=None, **kw):
        rec["open_calls"].append(cfg)
        fake = _FakeRealtimeSession(on_transcript=on_transcript, park=session_park)
        rec["session"] = fake
        return fake

    def _capture(session, cfg=None, **kw):
        rec["capture_calls"].append(cfg)
        if not capture_ok:
            return None
        cap = _FakeCapture()
        rec["capture"] = cap
        return cap

    monkeypatch.setattr(session_mod.realtime, "open_session", _open)
    monkeypatch.setattr(session_mod.realtime, "start_capture", _capture)
    return rec


def _stub_talk(monkeypatch, record):
    """Stub run_senses_talk (as imported into session) + a plays list."""
    calls: list[dict] = []

    def _talk(message, **kwargs):
        calls.append({"message": message, "kwargs": kwargs})
        return record

    monkeypatch.setattr(session_mod, "run_senses_talk", _talk)
    return calls


def _spoken(monkeypatch):
    """Capture synthesize() + play_wav_bytes() calls."""
    spoken: dict = {"synth": [], "play": []}

    def _synth(text, **kw):
        spoken["synth"].append(text)
        return kw["out_path"]

    def _play(session, wav, cfg=None, **kw):
        spoken["play"].append((session, wav))
        return True

    monkeypatch.setattr(voicemod, "synthesize", _synth)
    monkeypatch.setattr(session_mod.realtime, "play_wav_bytes", _play)
    return spoken


_TALK_RECORD = {
    "answer": "reading the config",
    "relay": False,
    "relay_text": "",
    "latency": 0.4,
    "degraded": False,
    "tokens": 9,
}


# ---------------------------------------------------------------------------
# c27 — the mic is NEVER hot by default
# ---------------------------------------------------------------------------


def test_availability_offers_but_never_captures(tmp_path: Path, monkeypatch) -> None:
    """Realtime available + gate open + NOT opted in → ONE offer line, no dial."""
    rec = _install_seams(monkeypatch)
    sess, _o, _e = _session(tmp_path)
    task = Task.new(str(tmp_path), "scan")
    sess._begin_talk_lane(task)  # arms the talk lane, which offers voice

    assert rec["open_calls"] == []  # availability NEVER starts capture (c27)
    assert sess._voice_state == "off"
    conv = "\n".join(line.text for line in sess.state.conversation)
    assert "voice" in conv and "/voice" in conv  # the offer line


def test_voice_flag_starts_capture(tmp_path: Path, monkeypatch) -> None:
    """``--voice`` (``_voice_wanted``) dials the ears-only session + starts capture."""
    rec = _install_seams(monkeypatch)
    sess, _o, _e = _session(tmp_path)
    sess._voice_wanted = True  # what run_session sets from --voice
    task = Task.new(str(tmp_path), "scan")
    sess._begin_talk_lane(task)

    assert len(rec["open_calls"]) == 1  # dialed once
    assert len(rec["capture_calls"]) == 1  # mic capture started
    assert sess._voice_state == "live"
    # on_transcript wired to the session's enqueue seam, not a fixed-window reader.
    assert rec["session"].on_transcript == sess._on_voice_transcript


def test_voice_toggle_starts_capture_then_mutes(tmp_path: Path, monkeypatch) -> None:
    """``/voice`` on a running lane starts capture; ``/voice`` again mutes."""
    rec = _install_seams(monkeypatch)
    sess, _o, _e = _session(tmp_path)
    task = Task.new(str(tmp_path), "scan")
    sess._begin_talk_lane(task)  # lane active, not yet opted in
    assert rec["open_calls"] == []

    first = sess._toggle_voice()  # opt in → capture starts
    assert len(rec["open_calls"]) == 1
    assert sess._voice_state == "live"
    assert "live" in first

    second = sess._toggle_voice()  # again → mute (session.mute + stop forwarding)
    assert rec["session"].muted is True
    assert sess._voice_state == "muted"
    assert "muted" in second

    third = sess._toggle_voice()  # again → live
    assert rec["session"].muted is False
    assert sess._voice_state == "live"
    assert "live" in third


def test_voice_flag_unavailable_one_notice_no_dial(tmp_path: Path, monkeypatch) -> None:
    """``--voice`` with realtime unavailable = ONE honest notice, NO dial (c27)."""
    rec = _install_seams(monkeypatch)
    sess, _o, _e = _session(tmp_path, config=_config(realtime=False))
    sess._voice_wanted = True
    task = Task.new(str(tmp_path), "scan")
    sess._begin_talk_lane(task)
    sess._begin_talk_lane(task)  # a second work line must not re-notice

    assert rec["open_calls"] == []  # never dialed
    conv = "\n".join(line.text for line in sess.state.conversation)
    assert conv.count("unavailable") == 1  # exactly one honest notice


# ---------------------------------------------------------------------------
# ONE senses path — a VAD transcript enters EXACTLY the typed-input path
# ---------------------------------------------------------------------------


def _arm_live_lane(sess, rec, monkeypatch):
    sess._talk_active = True
    sess._talk_task_id = "tid"
    sess._voice_wanted = True
    monkeypatch.setattr(sess, "_senses_engine", lambda: (object(), _FakeEngine()))
    sess._arm_voice_capture()
    return rec["session"]


def test_transcript_enqueues_only_on_pump_thread(tmp_path: Path, monkeypatch) -> None:
    """The pump-thread callback ONLY enqueues (thread-safe hand-off); it does not
    call the handler directly — the main thread drains it at the poll boundary."""
    rec = _install_seams(monkeypatch)
    sess, _o, _e = _session(tmp_path)
    fake = _arm_live_lane(sess, rec, monkeypatch)
    called: list[str] = []
    monkeypatch.setattr(sess, "_handle_talk_input", lambda t: called.append(t))

    fake.on_transcript("fix the failing test")  # simulate a final VAD transcript
    assert called == []  # NOT handled on the pump thread
    assert list(sess._voice_transcripts) == ["fix the failing test"]

    sess._poll_talk_lane()  # main-thread drain at the boundary
    assert called == ["fix the failing test"]


def test_voice_transcript_routes_through_run_senses_talk_and_speaks(
    tmp_path: Path, monkeypatch
) -> None:
    """A drained transcript hits the IDENTICAL typed path (run_senses_talk +
    flight.append_chat), renders the text, and speaks the reply as audio."""
    rec = _install_seams(monkeypatch)
    sess, _o, _e = _session(tmp_path)
    fake = _arm_live_lane(sess, rec, monkeypatch)
    calls = _stub_talk(monkeypatch, _TALK_RECORD)
    spoken = _spoken(monkeypatch)

    fake.on_transcript("what changed?")
    sess._poll_talk_lane()

    # SAME run_senses_talk call site the typed lane uses, with the transcript.
    assert [c["message"] for c in calls] == ["what changed?"]
    # text still rendered (labeled senses:)
    conv = "\n".join(line.text for line in sess.state.conversation)
    assert "senses: reading the config" in conv
    # reply spoken as audio via the batch lane, played over the held gate.
    assert spoken["synth"] == ["reading the config"]
    assert len(spoken["play"]) == 1 and spoken["play"][0][0] is fake
    # record landed on the flight chat, identical shape to a typed turn.
    chat = flight.read_chat(tmp_path, "tid")
    assert len(chat) == 1
    assert chat[0]["message"] == "what changed?"
    assert chat[0]["answer"] == "reading the config"


def test_voice_turn_chat_record_shape_identical_to_typed(tmp_path: Path, monkeypatch) -> None:
    """A voice turn and a typed turn produce flight-chat records of IDENTICAL shape
    (same keys) — voice adds no source marker to the persisted record."""
    rec = _install_seams(monkeypatch)
    sess, _o, _e = _session(tmp_path)
    _arm_live_lane(sess, rec, monkeypatch)
    _stub_talk(monkeypatch, _TALK_RECORD)
    _spoken(monkeypatch)

    sess._handle_talk_input("typed message")  # typed path
    rec["session"].on_transcript("spoken message")
    sess._poll_talk_lane()  # voice path

    chat = flight.read_chat(tmp_path, "tid")
    assert len(chat) == 2
    assert set(chat[0].keys()) == set(chat[1].keys())  # identical record shape


def test_relay_reaches_flight_guidance_from_voice(tmp_path: Path, monkeypatch) -> None:
    """A voice turn senses judges relay-worthy hits the SAME flight-guidance call
    site a typed relay does (voice turns become cortex guidance identically)."""
    rec = _install_seams(monkeypatch)
    sess, _o, _e = _session(tmp_path)
    fake = _arm_live_lane(sess, rec, monkeypatch)
    relay_record = dict(_TALK_RECORD, relay=True, relay_text="focus on the parser")
    _stub_talk(monkeypatch, relay_record)
    _spoken(monkeypatch)

    fake.on_transcript("the parser is wrong")
    sess._poll_talk_lane()

    guidance = flight.FlightSession(tmp_path, "tid").read_control().guidance
    assert "focus on the parser" in guidance


def test_synth_failure_never_touches_the_text(tmp_path: Path, monkeypatch) -> None:
    """A synth/playback failure is additive — the already-rendered text stands,
    no exception escapes (degrade-never-raise)."""
    rec = _install_seams(monkeypatch)
    sess, _o, _e = _session(tmp_path)
    fake = _arm_live_lane(sess, rec, monkeypatch)
    _stub_talk(monkeypatch, _TALK_RECORD)
    monkeypatch.setattr(voicemod, "synthesize", lambda *a, **k: None)  # synth degraded
    played: list = []
    monkeypatch.setattr(session_mod.realtime, "play_wav_bytes", lambda *a, **k: played.append(a))

    fake.on_transcript("hello")
    sess._poll_talk_lane()  # must not raise

    conv = "\n".join(line.text for line in sess.state.conversation)
    assert "senses: reading the config" in conv  # text unaffected
    assert played == []  # nothing to play when synth degraded


# ---------------------------------------------------------------------------
# Honest lane state — muted MUST render differently from degraded
# ---------------------------------------------------------------------------


def test_lane_state_lines_are_all_distinct(tmp_path: Path) -> None:
    lines = session_mod._VOICE_STATE_LINES
    assert set(lines) == {"off", "live", "muted", "degraded"}
    assert len(set(lines.values())) == 4  # every state reads differently
    # the crux: muted is visibly different from degraded (test-pinned)
    assert lines["muted"] != lines["degraded"]
    assert "muted" in lines["muted"] and "degraded" in lines["degraded"]


def test_render_voice_state_muted_vs_degraded(tmp_path: Path) -> None:
    sess, _o, _e = _session(tmp_path)
    sess._voice_state = "muted"
    sess._render_voice_state()
    sess._voice_state = "degraded"
    sess._render_voice_state()
    conv = [line.text for line in sess.state.conversation]
    muted_line = next(t for t in conv if "muted" in t)
    degraded_line = next(t for t in conv if "degraded" in t)
    assert muted_line != degraded_line


def test_capture_failure_renders_degraded_not_muted(tmp_path: Path, monkeypatch) -> None:
    """A device that won't open degrades the lane (start_capture → None) — the
    session stays usable in the typed lane, and the state is 'degraded'."""
    _install_seams(monkeypatch, capture_ok=False)
    sess, _o, _e = _session(tmp_path)
    sess._voice_wanted = True
    task = Task.new(str(tmp_path), "scan")
    sess._begin_talk_lane(task)

    assert sess._voice_state == "degraded"  # NOT muted
    conv = "\n".join(line.text for line in sess.state.conversation)
    assert "degraded" in conv


def test_capture_failure_reaps_the_realtime_session_immediately(
    tmp_path: Path, monkeypatch
) -> None:
    """A dialled socket whose capture never starts is reaped AT the failure, not
    held open until ``_end_voice_lane``.

    Without a mic there is no path by which a transcript can ever arrive, so an
    open WS + parked pump thread would idle for the whole work item buying
    nothing. The lane is left in exactly the dial-failure shape
    (``_voice_session is None`` + ``degraded``) so every downstream reader takes
    one path. (Qodo review, PR #356.)
    """
    rec = _install_seams(monkeypatch, capture_ok=False, session_park=True)
    sess, _o, _e = _session(tmp_path)
    sess._voice_wanted = True
    task = Task.new(str(tmp_path), "scan")
    sess._begin_talk_lane(task)

    fake = rec["session"]
    assert fake is not None, "the lane must still have dialled"
    assert fake.closed is True, "the failed lane's socket was left open"
    assert not fake.pump_alive(), "the failed lane orphaned its pump thread"
    assert sess._voice_session is None
    assert sess._voice_state == "degraded"


def test_pump_degrade_reflects_into_lane_state(tmp_path: Path, monkeypatch) -> None:
    """When the realtime pump degrades mid-session, the next poll reflects it into
    the honest lane state (degraded), once."""
    rec = _install_seams(monkeypatch)
    sess, _o, _e = _session(tmp_path)
    fake = _arm_live_lane(sess, rec, monkeypatch)
    assert sess._voice_state == "live"
    fake.degraded = True  # the pump fell back to the turn-based path

    sess._poll_talk_lane()
    assert sess._voice_state == "degraded"


# ---------------------------------------------------------------------------
# Bounded teardown — no hang, no orphan thread
# ---------------------------------------------------------------------------


def test_end_voice_lane_bounded_join_no_orphan(tmp_path: Path, monkeypatch) -> None:
    """`_end_voice_lane` reaps a REAL parked pump thread within the bounded join,
    leaving no orphan thread — measured on a genuine blocking pipe read."""
    rec = _install_seams(monkeypatch, session_park=True)
    sess, _o, _e = _session(tmp_path)
    baseline = set(threading.enumerate())
    fake = _arm_live_lane(sess, rec, monkeypatch)
    cap = rec["capture"]
    assert fake.pump_alive()  # a real thread is parked

    started = time.monotonic()
    sess._end_voice_lane()
    elapsed = time.monotonic() - started

    assert elapsed < 2.0, f"teardown was not bounded: {elapsed:.2f}s"
    assert not fake.pump_alive(), "pump thread survived teardown — orphan"
    assert fake.closed is True and cap.stopped is True
    assert sess._voice_session is None and sess._voice_state == "off"
    # no orphan thread left behind
    assert set(threading.enumerate()) <= baseline | {threading.current_thread()}


def test_end_talk_lane_tears_down_voice(tmp_path: Path, monkeypatch) -> None:
    rec = _install_seams(monkeypatch, session_park=True)
    sess, _o, _e = _session(tmp_path)
    fake = _arm_live_lane(sess, rec, monkeypatch)
    sess._end_talk_lane()  # work-item end
    assert fake.closed is True
    assert sess._voice_session is None


def test_ctrl_c_mid_capture_tears_down(tmp_path: Path, monkeypatch) -> None:
    """A mid-capture interrupt (KeyboardInterrupt raised inside the running work
    item) still reaps the voice lane via `_run_work`'s finally — bounded, no orphan."""
    rec = _install_seams(monkeypatch, session_park=True)
    sess, _o, _e = _session(tmp_path)
    sess._voice_wanted = True
    monkeypatch.setattr(sess, "_senses_engine", lambda: (object(), _FakeEngine()))

    def _boom(task, **kwargs):
        raise KeyboardInterrupt()

    monkeypatch.setattr(sess, "_dispatch_work", _boom)
    task = Task.new(str(tmp_path), "scan")
    with pytest.raises(KeyboardInterrupt):
        sess._run_work(task, None)

    assert rec["session"].closed is True  # reaped by the finally
    assert not rec["session"].pump_alive()
    assert sess._voice_session is None


# ---------------------------------------------------------------------------
# The lane's remaining degrade paths — every one of these leaves the TYPED lane
# fully usable and the rendered text byte-identical (the arc's degrade-never-
# raise contract). Pinned in PR #356's triage, which measured them as the
# arc's uncovered new code.
# ---------------------------------------------------------------------------


def test_begin_voice_lane_is_a_strict_noop_off_the_talk_lane(tmp_path: Path, monkeypatch) -> None:
    """No talk lane (off-TTY / no senses / --cortex-only) → zero dial, zero output."""
    rec = _install_seams(monkeypatch)
    sess, _o, _e = _session(tmp_path)
    sess._talk_active = False
    sess._voice_wanted = True
    before = len(sess.state.conversation)

    sess._begin_voice_lane()

    assert rec["open_calls"] == []
    assert len(sess.state.conversation) == before
    assert sess._voice_state == "off"


def test_arm_voice_capture_is_idempotent_within_a_work_item(tmp_path: Path, monkeypatch) -> None:
    """Already armed → the second call dials nothing (one socket per work item)."""
    rec = _install_seams(monkeypatch)
    sess, _o, _e = _session(tmp_path)
    _arm_live_lane(sess, rec, monkeypatch)
    assert len(rec["open_calls"]) == 1

    sess._arm_voice_capture()

    assert len(rec["open_calls"]) == 1


def test_dial_returning_none_degrades_the_lane(tmp_path: Path, monkeypatch) -> None:
    """``open_session`` → None (the dial-failure contract) degrades, never raises."""
    monkeypatch.setattr(session_mod.realtime, "open_session", lambda cfg, **kw: None)
    sess, _o, _e = _session(tmp_path)
    sess._talk_active = True
    sess._voice_wanted = True

    sess._arm_voice_capture()

    assert sess._voice_session is None
    assert sess._voice_state == "degraded"


def test_dial_raising_an_unexpected_error_degrades_the_lane(tmp_path: Path, monkeypatch) -> None:
    """Not every failure is the modelled CliError/None pair — an unexpected raise
    at the lane boundary still degrades rather than failing the work item."""

    def _boom(cfg, **kw):
        raise RuntimeError("the rig hung up mid-dial")

    monkeypatch.setattr(session_mod.realtime, "open_session", _boom)
    sess, _o, _e = _session(tmp_path)
    sess._talk_active = True
    sess._voice_wanted = True

    sess._arm_voice_capture()  # must not raise

    assert sess._voice_session is None
    assert sess._voice_state == "degraded"


def test_speak_reply_without_a_tts_model_plays_nothing(tmp_path: Path, monkeypatch) -> None:
    """Realtime armed but no ``tts`` role configured: the text reply already
    stands, and nothing is synthesized or played."""
    rec = _install_seams(monkeypatch)
    sess, _o, _e = _session(tmp_path, config=_config(voice=False))
    _arm_live_lane(sess, rec, monkeypatch)
    spoken = _spoken(monkeypatch)

    sess._speak_reply("reading the config")

    assert spoken["synth"] == [] and spoken["play"] == []


def test_speak_reply_swallows_a_synth_exception(tmp_path: Path, monkeypatch) -> None:
    """A synth that RAISES (not merely returns None) is still additive — the
    already-rendered text stands and nothing escapes."""
    rec = _install_seams(monkeypatch)
    sess, _o, _e = _session(tmp_path)
    _arm_live_lane(sess, rec, monkeypatch)

    def _boom(text, **kw):
        raise RuntimeError("tts endpoint down")

    played: list = []
    monkeypatch.setattr(voicemod, "synthesize", _boom)
    monkeypatch.setattr(session_mod.realtime, "play_wav_bytes", lambda *a, **k: played.append(a))

    sess._speak_reply("reading the config")  # must not raise

    assert played == []


def test_drain_skips_an_empty_transcript(tmp_path: Path, monkeypatch) -> None:
    """A blank transcript that reached the deque (the pump-thread callback strips,
    but the drain does not trust that) is skipped, not handed to the talk lane."""
    rec = _install_seams(monkeypatch)
    sess, _o, _e = _session(tmp_path)
    _arm_live_lane(sess, rec, monkeypatch)
    handled: list[str] = []
    monkeypatch.setattr(sess, "_handle_talk_input", lambda t: handled.append(t))
    sess._voice_transcripts.append("")

    sess._drain_voice_transcripts()

    assert handled == []


def test_drain_survives_a_concurrently_emptied_queue(tmp_path: Path, monkeypatch) -> None:
    """The drain's ``popleft`` race guard: the pump thread appends while the main
    thread drains, so a queue that reads non-empty can be empty one line later.
    Simulated here with a deque whose ``popleft`` always loses that race."""

    class _RacingDeque(collections.deque):
        def popleft(self):
            raise IndexError("drained concurrently")

    rec = _install_seams(monkeypatch)
    sess, _o, _e = _session(tmp_path)
    _arm_live_lane(sess, rec, monkeypatch)
    sess._voice_transcripts = _RacingDeque(["never read"])

    sess._drain_voice_transcripts()  # must break out, not spin or raise


def _wait_for(predicate, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


@pytest.mark.skipif(not hasattr(os, "openpty"), reason="needs POSIX openpty")
def test_pty_driven_session_reaps_voice_lane_no_orphan(tmp_path: Path, monkeypatch) -> None:
    """A REAL PTY-driven session: the loop's input is read from a genuine
    ``os.openpty`` slave via BLOCKING reads, run on a background thread; a work
    line arrives over the pty, arming the voice lane (a fake realtime session that
    spawns a REAL daemon pump thread parked on a blocking pipe read), and at
    work-item end the lane is reaped within its bounded join. Closing the pty
    master sends EOF, the loop breaks, and the session-exit safety net reaps again.

    We MEASURE, on the real loop: exit promptness (bounded, < 5s), that the parked
    pump thread died (no hang), and — via ``threading.enumerate()`` before/after —
    that NO orphan thread survives. Driving input over a real pty (blocking reads
    that wake on the master's EOF) keeps this genuinely PTY-driven while avoiding
    the raw per-keystroke reader's interaction with pytest's stdio capture (that
    surface is covered by the repo's autocomplete raw-loop pty tests)."""
    rec = _install_seams(monkeypatch, session_park=True)

    config = _config()
    result = TaskResult(task_id="t", status=OK, summary="s")

    def _fake_work(**kwargs):
        return result, tmp_path / ".colleague" / "art.json"

    master, slave = os.openpty()
    stream_in = os.fdopen(slave, "r")

    def _pty_lines():
        """Yield lines read from the REAL pty slave (blocking), ending on EOF.

        A pty slave read after the master closes surfaces as either a clean EOF
        (empty read) or an ``OSError(EIO)`` on Linux; both mean end-of-input, so
        both end the generator exactly as a real reader treats EOF (→ the loop
        breaks cleanly and runs its safety-net teardown)."""
        while True:
            try:
                line = stream_in.readline()  # a genuine blocking pty read
            except OSError:
                return  # master closed → EIO on the slave == end of input (EOF)
            if not line:  # clean EOF — the master was closed
                return
            yield line.rstrip("\r\n")

    sess = _Session(
        repo=tmp_path,
        engine_name="mock",
        open_pr=False,
        base="main",
        config=config,
        json_mode=False,
        view="ansi",
        io=SessionIO(out=_CollectingOut(), err=_CollectingOut()),
        work_fn=_fake_work,
    )
    sess._voice_wanted = True

    baseline = set(threading.enumerate())
    box: dict = {}

    def _run() -> None:
        try:
            box["rc"] = sess.run(input_fn=_pty_lines())
        except Exception as exc:  # surfaced in the main thread
            box["error"] = exc

    runner = threading.Thread(target=_run, daemon=True)
    runner.start()
    os.write(master, b"fix the bug\n")  # a genuine work line, delivered over the pty

    # THE measured core: the work line's voice lane armed (a real parked pump
    # thread) and, at work-item end, was reaped within the bounded join — proven
    # on the REAL PTY-driven loop, no hang, no orphan.
    assert _wait_for(lambda: rec["session"] is not None), "voice lane never armed"
    assert _wait_for(lambda: not rec["session"].pump_alive()), "pump thread orphaned"
    assert rec["session"].closed is True  # bounded close ran on the real loop
    reaped = rec["session"]

    started = time.monotonic()
    os.close(master)  # EOF over the pty → the loop's blocking read returns → break
    runner.join(timeout=5.0)
    elapsed = time.monotonic() - started

    assert not runner.is_alive(), "session loop did not exit — possible hang"
    assert elapsed < 5.0, f"session exit not prompt: {elapsed:.2f}s"
    assert "error" not in box, box.get("error")
    assert box.get("rc") == 0
    assert not reaped.pump_alive()  # no orphan pump thread
    time.sleep(0.05)
    assert set(threading.enumerate()) <= baseline | {threading.current_thread()}
    with __import__("contextlib").suppress(OSError):
        stream_in.close()


# ---------------------------------------------------------------------------
# VAD-driven + typed still works while live
# ---------------------------------------------------------------------------


def test_typed_input_still_works_while_voice_live(tmp_path: Path, monkeypatch) -> None:
    rec = _install_seams(monkeypatch)
    sess, _o, _e = _session(tmp_path)
    _arm_live_lane(sess, rec, monkeypatch)
    calls = _stub_talk(monkeypatch, _TALK_RECORD)
    _spoken(monkeypatch)
    assert sess._voice_state == "live"

    sess._handle_talk_input("a typed question while the mic is live")
    assert [c["message"] for c in calls] == ["a typed question while the mic is live"]


def test_reply_text_from_turns_extracts_answer(tmp_path: Path) -> None:
    """The loop-rung reply extractor pulls senses' operator-facing text from the
    returned turns (so a loop-rung voice turn can be spoken too)."""

    class _Turn:
        def __init__(self, entry):
            self.chat_entry = entry

    turns = [_Turn({"answer": "on it"}), _Turn(None), _Turn({"text": "and done"})]
    assert _reply_text_from_turns(turns) == "on it and done"
    assert _reply_text_from_turns([]) == ""
    assert _reply_text_from_turns(None) == ""


# ---------------------------------------------------------------------------
# Off-TTY / --json / unarmed — byte-identical (zero new output)
# ---------------------------------------------------------------------------


def test_voice_noop_off_tty(tmp_path: Path, monkeypatch) -> None:
    """view=markdown (off-TTY / --no-tui / --json): the voice lane never arms,
    never offers, never dials — byte-identical."""
    rec = _install_seams(monkeypatch)
    sess, _o, _e = _session(tmp_path, view="markdown")
    sess._voice_wanted = True  # even with --voice asked for
    task = Task.new(str(tmp_path), "scan")
    before = list(sess.state.conversation)
    sess._begin_talk_lane(task)

    assert rec["open_calls"] == []
    assert sess._voice_state == "off"
    assert list(sess.state.conversation) == before  # zero new output


def test_voice_noop_when_realtime_none_and_not_wanted(tmp_path: Path, monkeypatch) -> None:
    rec = _install_seams(monkeypatch)
    sess, _o, _e = _session(tmp_path, config=_config(realtime=False))
    task = Task.new(str(tmp_path), "scan")
    before = list(sess.state.conversation)
    sess._begin_talk_lane(task)

    assert rec["open_calls"] == []
    assert list(sess.state.conversation) == before  # no offer, no notice, no dial


def test_voice_noop_cortex_only(tmp_path: Path, monkeypatch) -> None:
    rec = _install_seams(monkeypatch)
    sess, _o, _e = _session(tmp_path, cortex_only=True)
    sess._voice_wanted = True
    task = Task.new(str(tmp_path), "scan")
    sess._begin_talk_lane(task)
    assert rec["open_calls"] == []
    assert sess._voice_state == "off"


def test_toggle_voice_unavailable_is_one_notice(tmp_path: Path, monkeypatch) -> None:
    _install_seams(monkeypatch)
    sess, _o, _e = _session(tmp_path, config=_config(realtime=False))
    msg = sess._toggle_voice()
    assert "unavailable" in msg or "not available" in msg


# ---------------------------------------------------------------------------
# catalog + flag surface
# ---------------------------------------------------------------------------


def test_voice_in_slash_catalog() -> None:
    names = {spec.name for spec in session_mod._SLASH_COMMANDS}
    assert "voice" in names


def test_voice_is_a_config_action() -> None:
    assert "voice" in session_mod._CONFIG_ACTIONS


def test_session_parser_has_voice_flag() -> None:
    import argparse

    p = argparse.ArgumentParser()
    session_mod._configure_session_parser(p)
    ns = p.parse_args(["--voice"])
    assert ns.voice is True
    ns2 = p.parse_args([])
    assert ns2.voice is False


# ── qwen-direct (t7): the single-model default path keeps voice/speak dormant ──


def test_voice_toggle_unarmed_senses_prints_dormant_line_no_dial(
    tmp_path: Path, monkeypatch
) -> None:
    """config.senses None (the default) → `/voice` is one honest dormant line:
    no capture armed, the wanted preference untouched, never a raise."""
    from colleague.cli._commands.session import _VOICE_SENSES_UNARMED_LINE

    sess, _o, _e = _session(tmp_path, config=_config(realtime=True, senses=False))
    _install_seams(monkeypatch)
    line = sess._toggle_voice()
    assert line == _VOICE_SENSES_UNARMED_LINE
    assert sess._voice_session is None and sess._voice_capture is None
    assert sess._voice_wanted is False


def test_speak_toggle_unarmed_senses_prints_dormant_line(tmp_path: Path) -> None:
    from colleague.cli._commands.session import _SPEAK_SENSES_UNARMED_LINE

    sess, _o, _e = _session(tmp_path, config=_config(realtime=True, senses=False))
    assert sess._toggle_speak() == _SPEAK_SENSES_UNARMED_LINE
    assert sess._speak_only is False


def test_voice_flag_unarmed_senses_one_dormant_line_ansi_only(tmp_path: Path, monkeypatch) -> None:
    """--voice on the default path renders exactly ONE dormant line on the colour
    TTY and nothing off-TTY (the byte-identical floor)."""
    from colleague.cli._commands.session import _VOICE_SENSES_UNARMED_LINE

    sess, _o, _e = _session(tmp_path, config=_config(realtime=True, senses=False))
    rendered: list[str] = []
    monkeypatch.setattr(sess, "_render_voice_line", lambda line: rendered.append(line))
    sess._voice_wanted = True
    sess._begin_voice_lane()
    sess._begin_voice_lane()
    assert rendered == [_VOICE_SENSES_UNARMED_LINE]
    md, _o2, _e2 = _session(tmp_path, view="markdown", config=_config(realtime=True, senses=False))
    md_rendered: list[str] = []
    monkeypatch.setattr(md, "_render_voice_line", lambda line: md_rendered.append(line))
    md._voice_wanted = True
    md._begin_voice_lane()
    assert md_rendered == []
