"""Senses live-presence arc (task t7): the session concurrent talk lane.

Pins the t7 contract on the interactive session: while a work line runs, the
operator chats with senses at progress-sink boundaries via a THREAD-FREE stdin
poll; a typed message is answered (labeled ``senses:``) and an instruction is
relayed into the running loop as flight guidance (echoing ``-> cortex:``); a
``/say FILE`` line transcribes audio first; and off-TTY / no-senses is
byte-identical (the lane never arms, never polls). The lane methods are exercised
directly (driving real stdin through a live loop is non-deterministic).
"""

from __future__ import annotations

from pathlib import Path

from colleague import flight
from colleague.cli._commands import session as session_mod
from colleague.cli._commands.session import SensesSessionOptions, SessionIO, _Session
from colleague.config import EngineConfig, SensesConfig, VoiceConfig
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


def _senses_config() -> EngineConfig:
    config = EngineConfig.resolve(model="cortex-model")
    config.senses = SensesConfig(
        model="senses-model", base_url="http://senses", api_key="k", context_budget=24000
    )
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
        config=config if config is not None else _senses_config(),
        json_mode=False,
        view=view,
        io=SessionIO(out=out, err=err),
        work_fn=_fake_work,
        senses_options=SensesSessionOptions(cortex_only=cortex_only),
    )
    return sess, out, err


def _stub_talk(monkeypatch, record):
    """Stub run_senses_talk (as imported into session) + _senses_engine seam."""
    calls: list[str] = []

    def _talk(message, **kwargs):
        calls.append(message)
        return record

    monkeypatch.setattr(session_mod, "run_senses_talk", _talk)
    return calls


# --- gating: byte-identical off-TTY / no senses / --cortex-only -------------


def test_talk_lane_enabled_on_ansi_with_senses(tmp_path: Path) -> None:
    sess, _o, _e = _session(tmp_path, view="ansi")
    assert sess._talk_lane_enabled() is True


def test_talk_lane_disabled_off_tty(tmp_path: Path) -> None:
    sess, _o, _e = _session(tmp_path, view="markdown")
    assert sess._talk_lane_enabled() is False


def test_talk_lane_disabled_when_no_senses(tmp_path: Path) -> None:
    config = EngineConfig.resolve(model="cortex-model")  # no .senses
    sess, _o, _e = _session(tmp_path, view="ansi", config=config)
    assert sess._talk_lane_enabled() is False


def test_talk_lane_disabled_cortex_only(tmp_path: Path) -> None:
    sess, _o, _e = _session(tmp_path, view="ansi", cortex_only=True)
    assert sess._talk_lane_enabled() is False


# --- flight arming: enabled arms the plane; disabled leaves the task alone ---


def test_begin_talk_lane_arms_flight_when_enabled(tmp_path: Path) -> None:
    sess, _o, _e = _session(tmp_path, view="ansi")
    task = Task.new(str(tmp_path), "scan")
    assert task.watch is False
    sess._begin_talk_lane(task)
    assert sess._talk_active is True
    assert task.watch is True  # armed so relays land on the flight plane
    assert sess._talk_task_id == task.id
    sess._end_talk_lane()
    assert sess._talk_active is False
    assert sess._talk_task_id is None


def test_begin_talk_lane_noop_off_tty(tmp_path: Path) -> None:
    sess, _o, _e = _session(tmp_path, view="markdown")
    task = Task.new(str(tmp_path), "scan")
    sess._begin_talk_lane(task)
    assert sess._talk_active is False
    assert task.watch is False  # byte-identical: the flight is never armed


# --- answering + relay --------------------------------------------------------


def test_talk_senses_answers_labeled_and_records_chat(tmp_path: Path, monkeypatch) -> None:
    sess, out, _e = _session(tmp_path, view="ansi")
    sess._talk_active = True
    sess._talk_task_id = "tid"
    monkeypatch.setattr(sess, "_senses_engine", lambda: (object(), _FakeEngine()))
    _stub_talk(
        monkeypatch,
        {
            "answer": "reading the config",
            "relay": False,
            "relay_text": "",
            "latency": 0.5,
            "degraded": False,
            "tokens": 12,
        },
    )
    sess._talk_senses("how's it going?")

    # labeled answer in the cockpit conversation
    conv = "\n".join(line.text for line in sess.state.conversation)
    assert "senses: reading the config" in conv
    # exchange recorded for the artifact fold (t5)
    chat = flight.read_chat(tmp_path, "tid")
    assert len(chat) == 1
    assert chat[0]["message"] == "how's it going?"
    assert chat[0]["answer"] == "reading the config"
    assert chat[0]["relay"] is False


def test_talk_senses_relay_reaches_flight_guidance(tmp_path: Path, monkeypatch) -> None:
    sess, out, _e = _session(tmp_path, view="ansi")
    sess._talk_active = True
    sess._talk_task_id = "tid"
    monkeypatch.setattr(sess, "_senses_engine", lambda: (object(), _FakeEngine()))
    _stub_talk(
        monkeypatch,
        {
            "answer": "ok, relaying",
            "relay": True,
            "relay_text": "focus on tests",
            "latency": 0.4,
            "degraded": False,
            "tokens": 8,
        },
    )
    sess._talk_senses("cortex: focus on tests")

    # the relay lands on the flight control file's guidance list
    guidance = flight.FlightSession(tmp_path, "tid").read_control().guidance
    assert "focus on tests" in guidance
    # and is visibly echoed
    conv = "\n".join(line.text for line in sess.state.conversation)
    assert "-> cortex: focus on tests" in conv


def test_talk_senses_unarmed_parks_for_cortex(tmp_path: Path, monkeypatch) -> None:
    # Default path: senses unarmed (config.senses None) + a typed mid-run line —
    # the line is PARKED for cortex at the next boundary, written VERBATIM as
    # flight guidance (the same seam colleague talk's raw-guide degrade uses),
    # with zero senses calls and no return-and-drop.
    config = EngineConfig.resolve(model="cortex-model")  # no .senses
    sess, _o, _e = _session(tmp_path, view="ansi", config=config)
    sess._talk_active = True
    sess._talk_task_id = "tid"
    senses_calls = {"n": 0}

    def _talk(message, **kwargs):
        senses_calls["n"] += 1
        return None

    monkeypatch.setattr(session_mod, "run_senses_talk", _talk)
    sess._talk_senses("focus on the tests")

    assert senses_calls["n"] == 0  # zero senses calls
    guidance = flight.FlightSession(tmp_path, "tid").read_control().guidance
    assert guidance == ["focus on the tests"]  # exactly one, verbatim
    conv = "\n".join(line.text for line in sess.state.conversation)
    assert "parked for cortex at the next boundary" in conv


# --- poll: no-op when disabled; reads a line when armed ----------------------


def test_poll_talk_lane_is_noop_when_disabled(tmp_path: Path, monkeypatch) -> None:
    sess, _o, _e = _session(tmp_path, view="ansi")
    sess._talk_active = False
    # select must never be consulted when the lane is disabled.
    monkeypatch.setattr(
        session_mod.select,
        "select",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("polled")),
    )
    sess._poll_talk_lane()  # no exception → never polled


def test_poll_talk_lane_reads_line_and_answers(tmp_path: Path, monkeypatch) -> None:
    sess, _o, _e = _session(tmp_path, view="ansi")
    sess._talk_active = True
    sess._talk_task_id = "tid"
    monkeypatch.setattr(sess, "_senses_engine", lambda: (object(), _FakeEngine()))
    calls = _stub_talk(
        monkeypatch,
        {
            "answer": "sure",
            "relay": False,
            "relay_text": "",
            "latency": 0.1,
            "degraded": False,
            "tokens": 1,
        },
    )
    monkeypatch.setattr(session_mod.select, "select", lambda *a, **k: ([sys_stdin_marker], [], []))
    monkeypatch.setattr(session_mod.sys, "stdin", _FakeStdin("what are you doing?\n"))

    sess._poll_talk_lane()
    assert calls == ["what are you doing?"]


# --- /say audio input -------------------------------------------------------


def test_say_transcribes_audio_then_answers(tmp_path: Path, monkeypatch) -> None:
    config = _senses_config()
    config.voice = VoiceConfig(
        stt_model="stt",
        tts_model=None,
        stt_base_url="http://voice/v1",
        tts_base_url="http://voice/v1",
        api_key="k",
    )
    sess, _o, _e = _session(tmp_path, view="ansi", config=config)
    sess._talk_active = True
    sess._talk_task_id = "tid"
    monkeypatch.setattr(sess, "_senses_engine", lambda: (object(), _FakeEngine()))
    calls = _stub_talk(
        monkeypatch,
        {
            "answer": "got it",
            "relay": False,
            "relay_text": "",
            "latency": 0.1,
            "degraded": False,
            "tokens": 1,
        },
    )

    from colleague import voice as voicemod

    monkeypatch.setattr(voicemod, "transcribe", lambda *a, **k: "spoken instruction")

    sess._handle_talk_input("/say /tmp/note.wav")
    # the verbatim transcript becomes the operator message
    assert calls == ["spoken instruction"]


sys_stdin_marker = object()


class _FakeStdin:
    def __init__(self, line: str) -> None:
        self._line = line

    def readline(self) -> str:
        return self._line
