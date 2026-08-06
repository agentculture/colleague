"""Speak-only lane (task t8): TTS-speaks each senses REPLY while the operator
only types — no mic, no realtime session, no half-duplex gate.

Pins the t8 contract on the interactive ``colleague session`` cockpit:

* **h18/c22 — default OFF, nothing else can arm it.** ``_speak_only`` is a
  pure ``_Session`` attribute (never part of ``EngineConfig``/config.json
  resolution) with exactly TWO writers: the ``--speak`` flag and the
  ``/speak`` toggle. No mode profile, session mode, or config default can
  flip it.
* **c7/h5 — the mic wall stands.** Speak-only never constructs a realtime
  session, never calls ``open_session``/``start_capture``, never transcribes
  audio. Only ``--voice``/``/voice`` can ever construct a voice session.
* **c21 — session-free playback.** ``_speak_reply`` plays through
  ``realtime.play_wav_bytes_local`` (no session, no half-duplex gate) when
  speak-only is the ONLY armed channel; a live voice session still rides the
  gated ``realtime.play_wav_bytes``.
* **h17 — degrade-never-raise.** A synth or playback failure leaves the
  already-rendered text byte-identical; nothing raises.
* **Replies-only (risk r1 / open q4).** Only senses' rendered REPLY text is
  spoken — never narration, never presence/status lines.

Fakes injected at the ``_senses_engine`` / ``run_senses_talk`` /
``voice.synthesize`` / ``realtime.*`` seams keep every test hardware-free and
network-free, mirroring ``tests/test_session_voice.py``.
GOTCHA (tests/conftest.py scrubs COLLEAGUE_*): arm per-test via monkeypatch.
"""

from __future__ import annotations

import contextlib
import dataclasses
import inspect
import io
import os
import threading
import time
from pathlib import Path

import pytest

from colleague import profiles as profiles_mod
from colleague import session_modes as session_modes_mod
from colleague import voice as voicemod
from colleague.cli._commands import session as session_mod
from colleague.cli._commands.session import SensesSessionOptions, SessionIO, _Session
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


def _config(*, tts: bool = True, senses: bool = True, realtime: bool = False) -> EngineConfig:
    config = EngineConfig.resolve(model="cortex-model")
    if senses:
        config.senses = SensesConfig(
            model="senses-model", base_url="http://senses", api_key="k", context_budget=24000
        )
    if tts:
        config.voice = VoiceConfig(
            stt_model=None,
            tts_model="tts",
            stt_base_url="",
            tts_base_url="http://tts",
            api_key="k",
        )
    if realtime:
        config.realtime = RealtimeConfig(available=True, ws_url="ws://rig/v1/realtime", api_key="k")
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


def _arm_talk_lane(sess, monkeypatch) -> None:
    """Arm the talk lane directly (bypassing the colour-TTY gate machinery
    tested elsewhere) and stub the senses engine seam — mirrors
    ``test_session_voice.py``'s ``_arm_live_lane`` minus the voice dial.
    Accepts ``**kw`` because an owned-line-armed session also passes
    ``on_delta`` (display-streaming arming, ssv t3)."""
    sess._talk_active = True
    sess._talk_task_id = "tid"
    monkeypatch.setattr(sess, "_senses_engine", lambda **kw: (object(), _FakeEngine()))


def _stub_talk(monkeypatch, record):
    """Stub run_senses_talk (as imported into session)."""
    calls: list[dict] = []

    def _talk(message, **kwargs):
        calls.append({"message": message, "kwargs": kwargs})
        return record

    monkeypatch.setattr(session_mod, "run_senses_talk", _talk)
    return calls


def _spoken(monkeypatch):
    """Capture synthesize() + BOTH playback seams' calls."""
    spoken: dict = {"synth": [], "play_gated": [], "play_local": []}

    def _synth(text, **kw):
        spoken["synth"].append(text)
        return kw["out_path"]

    def _play_gated(session, wav, cfg=None, **kw):
        spoken["play_gated"].append((session, wav))
        return True

    def _play_local(wav, cfg=None, **kw):
        spoken["play_local"].append(wav)
        return True

    monkeypatch.setattr(voicemod, "synthesize", _synth)
    monkeypatch.setattr(session_mod.realtime, "play_wav_bytes", _play_gated)
    monkeypatch.setattr(session_mod.realtime, "play_wav_bytes_local", _play_local)
    return spoken


def _install_voice_seams(monkeypatch):
    """Record any attempt to construct a realtime session or start capture —
    the h5 boundary this whole file exists to prove never fires."""
    rec: dict = {"open_calls": [], "capture_calls": []}

    def _open(cfg, *, on_transcript=None, **kw):
        rec["open_calls"].append(cfg)
        raise AssertionError("speak-only must never dial a realtime session")

    def _capture(session, cfg=None, **kw):
        rec["capture_calls"].append(cfg)
        raise AssertionError("speak-only must never start mic capture")

    monkeypatch.setattr(session_mod.realtime, "open_session", _open)
    monkeypatch.setattr(session_mod.realtime, "start_capture", _capture)
    return rec


_TALK_RECORD = {
    "answer": "reading the config",
    "relay": False,
    "relay_text": "",
    "latency": 0.4,
    "degraded": False,
    "tokens": 9,
}


# ---------------------------------------------------------------------------
# h18/c22 — default OFF; nothing but --speak / /speak can ever flip it
# ---------------------------------------------------------------------------


def test_speak_only_default_off_on_a_fresh_session(tmp_path: Path) -> None:
    sess, _o, _e = _session(tmp_path)
    assert sess._speak_only is False


def test_speak_only_is_not_an_engineconfig_field() -> None:
    """Structural guarantee: ``_speak_only`` lives ONLY on ``_Session`` — it is
    not part of ``EngineConfig`` at all, so config.json / env resolution
    cannot touch it (mirrors ``_voice_wanted``'s own design)."""
    field_names = {f.name for f in dataclasses.fields(EngineConfig)}
    assert "speak_only" not in field_names
    assert "speak" not in field_names


def test_no_mode_profile_knob_ever_names_speak(tmp_path: Path) -> None:
    """``apply_mode_profile`` only fills the knobs named in
    ``_PROFILE_ENV_KEYS`` — none of them is speak-related, and no built-in
    ``ModeProfile`` carries a speak/voice field at all."""
    from colleague.config import _PROFILE_ENV_KEYS

    assert not any("speak" in key.lower() for key in _PROFILE_ENV_KEYS)
    profile_fields = {f.name for f in dataclasses.fields(profiles_mod.ModeProfile)}
    assert not any("speak" in name.lower() for name in profile_fields)


def test_profiles_and_session_modes_source_never_mentions_speak() -> None:
    """Source-level sweep (grep-equivalent): neither the mode-profile catalog
    nor the session-mode router references speak-only at all — the two
    writers (``--speak``, ``/speak``) live exclusively in
    ``colleague/cli/_commands/session.py``."""
    assert "speak" not in inspect.getsource(profiles_mod).lower()
    assert "speak" not in inspect.getsource(session_modes_mod).lower()


def test_speak_only_survives_apply_mode_profile_for_every_mode(tmp_path: Path) -> None:
    """Driving every session mode through the REAL profile-application path
    never sets (or could set) ``_speak_only`` — it isn't a config field for
    ``apply_mode_profile`` to touch in the first place."""
    from colleague.config import apply_mode_profile
    from colleague.session_modes import MODES

    for mode in MODES:
        sess, _o, _e = _session(tmp_path)
        sess.config = apply_mode_profile(sess.config, mode)
        assert sess._speak_only is False


def test_configure_session_parser_speak_flag_defaults_false() -> None:
    import argparse

    p = argparse.ArgumentParser()
    session_mod._configure_session_parser(p)
    ns = p.parse_args(["--speak"])
    assert ns.speak is True
    ns2 = p.parse_args([])
    assert ns2.speak is False


# ---------------------------------------------------------------------------
# c7/h5 — zero voice-session objects; only --voice/-​/voice can build one
# ---------------------------------------------------------------------------


def test_speak_only_on_voice_off_never_constructs_a_voice_session(
    tmp_path: Path, monkeypatch
) -> None:
    rec = _install_voice_seams(monkeypatch)
    sess, _o, _e = _session(tmp_path)
    sess._speak_only = True
    task = Task.new(str(tmp_path), "scan")

    sess._begin_talk_lane(task)  # arms the talk lane; must not touch realtime

    assert rec["open_calls"] == []
    assert rec["capture_calls"] == []
    assert sess._voice_session is None


def test_speak_only_zero_stt_calls(tmp_path: Path, monkeypatch) -> None:
    """Speak-only needs ONLY tts — stt/transcribe is never consulted."""
    sess, _o, _e = _session(tmp_path)
    sess._speak_only = True
    _arm_talk_lane(sess, monkeypatch)
    calls = _stub_talk(monkeypatch, _TALK_RECORD)
    _spoken(monkeypatch)
    transcribe_calls: list[str] = []
    monkeypatch.setattr(
        voicemod, "transcribe", lambda *a, **k: transcribe_calls.append(a) or "should not happen"
    )

    sess._dispatch_talk_line("what changed?")

    assert [c["message"] for c in calls] == ["what changed?"]
    assert transcribe_calls == []


def test_speak_only_exactly_one_synth_and_local_playback_per_reply(
    tmp_path: Path, monkeypatch
) -> None:
    """The call-count core of h5/c21: with speak-only on and no voice session,
    exactly ONE synth + ONE session-FREE playback call happens per senses
    reply — never the gated play_wav_bytes (there is no session to gate)."""
    sess, _o, _e = _session(tmp_path)
    sess._speak_only = True
    _arm_talk_lane(sess, monkeypatch)
    _stub_talk(monkeypatch, _TALK_RECORD)
    spoken = _spoken(monkeypatch)

    sess._dispatch_talk_line("what changed?")

    assert spoken["synth"] == ["reading the config"]
    assert len(spoken["play_local"]) == 1
    assert spoken["play_gated"] == []  # never the session-gated seam


def test_voice_off_and_speak_only_off_zero_synth_calls(tmp_path: Path, monkeypatch) -> None:
    """Neither channel armed (today's default) → _speak_reply never even
    imports colleague.voice — the h18 default-off floor, call-count proof."""
    sess, _o, _e = _session(tmp_path)
    assert sess._speak_only is False
    assert sess._voice_session is None
    _arm_talk_lane(sess, monkeypatch)
    _stub_talk(monkeypatch, _TALK_RECORD)
    spoken = _spoken(monkeypatch)

    sess._dispatch_talk_line("what changed?")

    assert spoken["synth"] == []
    assert spoken["play_local"] == []
    assert spoken["play_gated"] == []


def test_only_voice_flag_state_constructs_a_session_not_speak(tmp_path: Path, monkeypatch) -> None:
    """--speak (speak-only) never flips _voice_wanted, and toggling /speak
    never arms a realtime dial — only --voice / /voice ever do (h5)."""
    rec = _install_voice_seams(monkeypatch)
    sess, _o, _e = _session(tmp_path, config=_config(tts=True, realtime=True))
    msg = sess._toggle_speak()  # /speak on
    assert "on" in msg
    assert sess._speak_only is True
    assert sess._voice_wanted is False

    task = Task.new(str(tmp_path), "scan")
    sess._begin_talk_lane(task)

    assert rec["open_calls"] == []  # speak-only alone never dials realtime
    assert sess._voice_session is None


# ---------------------------------------------------------------------------
# c21 — session-free playback keeps working with/without a resolved
# RealtimeConfig (output device selection stays intact either way)
# ---------------------------------------------------------------------------


def test_speak_only_works_with_no_realtime_config_at_all(tmp_path: Path, monkeypatch) -> None:
    """Speak-only needs no RealtimeConfig to exist — config.realtime stays
    None, and playback still resolves (falls back to the default device)."""
    sess, _o, _e = _session(tmp_path, config=_config(tts=True, realtime=False))
    assert sess.config.realtime is None
    sess._speak_only = True
    _arm_talk_lane(sess, monkeypatch)
    _stub_talk(monkeypatch, _TALK_RECORD)
    spoken = _spoken(monkeypatch)

    sess._dispatch_talk_line("what changed?")

    assert len(spoken["play_local"]) == 1


def test_speak_only_passes_realtime_config_through_for_device_selection(
    tmp_path: Path, monkeypatch
) -> None:
    """When a RealtimeConfig IS resolved (e.g. for its output_device), the
    session-free playback path still receives it — device selection is not
    lost by dropping the session."""
    sess, _o, _e = _session(tmp_path, config=_config(tts=True, realtime=True))
    sess._speak_only = True
    _arm_talk_lane(sess, monkeypatch)
    _stub_talk(monkeypatch, _TALK_RECORD)
    passed_cfg: list = []

    def _synth(text, **kw):
        return kw["out_path"]

    def _play_local(wav, cfg=None, **kw):
        passed_cfg.append(cfg)
        return True

    monkeypatch.setattr(voicemod, "synthesize", _synth)
    monkeypatch.setattr(session_mod.realtime, "play_wav_bytes_local", _play_local)

    sess._dispatch_talk_line("what changed?")

    assert passed_cfg == [sess.config.realtime]


# ---------------------------------------------------------------------------
# h17 — degrade-never-raise: text stands even when synth/playback fails
# ---------------------------------------------------------------------------


def test_speak_only_synth_degrade_leaves_text_untouched(tmp_path: Path, monkeypatch) -> None:
    sess, _o, _e = _session(tmp_path)
    sess._speak_only = True
    _arm_talk_lane(sess, monkeypatch)
    _stub_talk(monkeypatch, _TALK_RECORD)
    monkeypatch.setattr(voicemod, "synthesize", lambda *a, **k: None)  # synth degraded
    played: list = []
    monkeypatch.setattr(
        session_mod.realtime, "play_wav_bytes_local", lambda *a, **k: played.append(a)
    )

    sess._dispatch_talk_line("hello")  # must not raise

    conv = "\n".join(line.text for line in sess.state.conversation)
    assert "senses: reading the config" in conv
    assert played == []


def test_speak_only_synth_exception_leaves_text_untouched(tmp_path: Path, monkeypatch) -> None:
    sess, _o, _e = _session(tmp_path)
    sess._speak_only = True
    _arm_talk_lane(sess, monkeypatch)
    _stub_talk(monkeypatch, _TALK_RECORD)

    def _boom(text, **kw):
        raise RuntimeError("tts endpoint down")

    monkeypatch.setattr(voicemod, "synthesize", _boom)
    played: list = []
    monkeypatch.setattr(
        session_mod.realtime, "play_wav_bytes_local", lambda *a, **k: played.append(a)
    )

    sess._dispatch_talk_line("hello")  # must not raise

    conv = "\n".join(line.text for line in sess.state.conversation)
    assert "senses: reading the config" in conv
    assert played == []


def test_speak_only_playback_exception_leaves_text_untouched(tmp_path: Path, monkeypatch) -> None:
    """A playback failure (not just a synth one) is equally additive."""
    sess, _o, _e = _session(tmp_path)
    sess._speak_only = True
    _arm_talk_lane(sess, monkeypatch)
    _stub_talk(monkeypatch, _TALK_RECORD)
    monkeypatch.setattr(voicemod, "synthesize", lambda text, **kw: kw["out_path"])

    def _boom_play(*a, **k):
        raise RuntimeError("device busy")

    monkeypatch.setattr(session_mod.realtime, "play_wav_bytes_local", _boom_play)

    sess._dispatch_talk_line("hello")  # must not raise

    conv = "\n".join(line.text for line in sess.state.conversation)
    assert "senses: reading the config" in conv


# ---------------------------------------------------------------------------
# /speak toggle + --speak flag registration (mirrors /voice's own tests)
# ---------------------------------------------------------------------------


def test_speak_in_slash_catalog() -> None:
    names = {spec.name for spec in session_mod._SLASH_COMMANDS}
    assert "speak" in names


def test_speak_is_a_config_action() -> None:
    assert "speak" in session_mod._CONFIG_ACTIONS


def test_toggle_speak_on_then_off(tmp_path: Path) -> None:
    sess, _o, _e = _session(tmp_path)
    first = sess._toggle_speak()
    assert sess._speak_only is True
    assert "on" in first

    second = sess._toggle_speak()
    assert sess._speak_only is False
    assert "off" in second


def test_toggle_speak_unavailable_when_no_tts(tmp_path: Path) -> None:
    sess, _o, _e = _session(tmp_path, config=_config(tts=False))
    msg = sess._toggle_speak()
    assert "unavailable" in msg
    assert sess._speak_only is False


def test_speak_state_lines_are_distinct() -> None:
    lines = session_mod._SPEAK_STATE_LINES
    assert set(lines) == {"off", "on"}
    assert lines["off"] != lines["on"]


# ---------------------------------------------------------------------------
# Replies-only (risk r1 / open q4): narration is never spoken, only the reply
# ---------------------------------------------------------------------------


class _FakeTurn:
    def __init__(self, chat_entry=None, narration=None) -> None:
        self.chat_entry = chat_entry
        self.narration = narration


class _FakePresenceEngine:
    def __init__(self, turns: list) -> None:
        self._turns = turns

    def on_operator_message(self, text: str) -> list:
        return self._turns


def test_speak_only_speaks_the_reply_not_the_narration(tmp_path: Path, monkeypatch) -> None:
    """A single dispatched operator message that produced BOTH a narrate move
    (no chat_entry, per SensesLoopDriver._build_turn) and a reply move (chat_entry
    with 'answer') must synth EXACTLY the reply text — the narration is never
    joined into what gets spoken."""
    sess, _o, _e = _session(tmp_path)
    sess._speak_only = True
    sess._talk_active = True
    sess._presence_engine = _FakePresenceEngine(
        [
            _FakeTurn(chat_entry=None, narration="<<higher self thought>> investigating…"),
            _FakeTurn(chat_entry={"message": "what changed?", "answer": "three files edited"}),
        ]
    )
    spoken = _spoken(monkeypatch)

    sess._dispatch_talk_line("what changed?")

    assert spoken["synth"] == ["three files edited"]
    assert len(spoken["play_local"]) == 1


def test_reply_text_from_turns_excludes_narration_by_construction() -> None:
    """Direct pin on the extractor itself: a narrate-shaped turn (chat_entry
    None) contributes nothing, even though it carries a narration string."""
    from colleague.cli._commands.session import _reply_text_from_turns

    turns = [
        _FakeTurn(chat_entry=None, narration="a narration line"),
        _FakeTurn(chat_entry={"answer": "the actual reply"}),
    ]
    assert _reply_text_from_turns(turns) == "the actual reply"


# ---------------------------------------------------------------------------
# Real-PTY: typing stays live during synchronous speak-only playback
# ---------------------------------------------------------------------------


def _wait_for(predicate, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


@pytest.mark.skipif(not hasattr(os, "openpty"), reason="needs POSIX openpty")
def test_typing_stays_live_during_speak_only_playback_real_pty(tmp_path: Path, monkeypatch) -> None:
    """Task t8: _speak_reply runs synth+playback SYNCHRONOUSLY on whichever
    thread drives the talk lane. This proves the OwnedInputLine reader
    thread — independent of that thread — keeps buffering keystrokes typed
    WHILE playback blocks: nothing typed during audio is lost, even though
    the next prompt repaint waits for playback to finish. Bounded retry (2)
    for PTY flake."""
    last_error: "BaseException | None" = None
    for _attempt in range(2):  # bounded PTY-flake retry
        try:
            _run_typing_survives_playback(tmp_path, monkeypatch)
            return
        except AssertionError as exc:  # pragma: no cover - flake path
            last_error = exc
    raise AssertionError(f"PTY typing-survives-playback failed twice: {last_error}")


def _run_typing_survives_playback(tmp_path: Path, monkeypatch) -> None:
    synth_started = threading.Event()
    release_synth = threading.Event()

    def _blocking_synth(text, **kw):
        synth_started.set()
        release_synth.wait(timeout=2.0)
        return kw["out_path"]

    def _fast_play_local(wav, cfg=None, **kw):
        return True

    monkeypatch.setattr(voicemod, "synthesize", _blocking_synth)
    monkeypatch.setattr(session_mod.realtime, "play_wav_bytes_local", _fast_play_local)

    sess, _o, _e = _session(tmp_path)
    sess._speak_only = True
    _arm_talk_lane(sess, monkeypatch)
    _stub_talk(monkeypatch, _TALK_RECORD)

    master, slave = os.openpty()
    stream_in = os.fdopen(slave, "rb", buffering=0)
    fake_out = io.StringIO()
    sess._owned_line_streams = (stream_in, fake_out)
    sess._arm_owned_line()
    assert sess._owned_line is not None, "owned line failed to arm over the real pty"

    drive: "threading.Thread | None" = None
    try:
        os.write(master, b"what changed?\n")
        assert _wait_for(lambda: len(sess._owned_talk_queue) >= 1), "submitted line never queued"

        # Drive the poll (which will block in _blocking_synth) off the main
        # test thread — mirroring how, in production, the reader thread is
        # ALREADY independent of whatever thread runs the session loop.
        drive = threading.Thread(target=sess._poll_talk_lane, daemon=True)
        drive.start()
        assert synth_started.wait(timeout=2.0), "synth (playback) never started"

        # WHILE synth/playback is blocked, the operator keeps typing — over
        # the SAME real pty, into the reader thread.
        os.write(master, b"still typing")
        assert _wait_for(
            lambda: sess._owned_line._pending == "still typing"
        ), f"typed input lost during blocking playback (pending={sess._owned_line._pending!r})"

        release_synth.set()  # let the blocked synth/playback return
        drive.join(timeout=2.0)
        assert not drive.is_alive(), "the talk-lane poll never returned"

        # Submit the buffered line — it must arrive whole, nothing lost.
        os.write(master, b"\n")
        assert _wait_for(lambda: len(sess._owned_talk_queue) >= 1)
        assert list(sess._owned_talk_queue) == ["still typing"]
    finally:
        release_synth.set()
        if drive is not None:
            drive.join(timeout=2.0)
        sess._disarm_owned_line()
        with contextlib.suppress(Exception):
            stream_in.close()
        with contextlib.suppress(Exception):
            os.close(master)
