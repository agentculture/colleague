"""Tests for the mesh audio file-link + trust-gated relay in the resident
appserver (senses live presence + voice, task t8).

Surfaces under test (:mod:`colleague.resident.appserver`):

1. **Audio reply link** — when ``config.voice`` is armed with a ``tts_model``,
   a successful dispatch's reply gains an ``audio: <path>`` line naming the
   synthesized wav (relative to the repo root, beside the artifact); a
   degraded synth (``None`` — e.g. the reference rig's speech proxy 502ing)
   leaves the reply byte-identical to a no-tts run.
2. **Trust-gated relay** — a ``relay <task-id>: <text>`` line addresses an
   already-running flight. An OPERATOR relay calls
   ``colleague.flight.append_guidance`` and the reply visibly labels it
   ``-> cortex(<task-id>): <text>``. A NON-OPERATOR relay NEVER calls
   ``append_guidance`` — this is the security pin the task exists to prove.

No live network / no live TTS: every ``voice.synthesize`` / ``run_senses_talk``
call is monkeypatched (mirrors ``tests/test_resident_senses.py``'s
``_patch_senses`` pattern). The reference rig's real TTS endpoint 502s today
(the documented honest limit — see ``colleague/voice.py`` and the appserver
module docstring); this file proves the wiring, not the live audio pipeline
(that is the livecheck's job, task t10).
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

pytest.importorskip(
    "agent_lifecycle", reason="install the [culture]/[resident] extra to test the resident seam"
)

from agent_lifecycle.reference import InMemoryTransport  # noqa: E402
from agent_lifecycle.runtime.message import Message  # noqa: E402

from colleague.config import EngineConfig, SensesConfig, VoiceConfig  # noqa: E402
from colleague.resident import appserver as appserver_mod  # noqa: E402
from colleague.resident.appserver import build_appserver_supervisor  # noqa: E402


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True)


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "a.txt").write_text("hi\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def _voice_config() -> EngineConfig:
    config = EngineConfig()
    config.voice = VoiceConfig(
        stt_model=None, tts_model="tts-model", base_url="http://voice", api_key="k"
    )
    return config


async def _round_trip(transport, supervisor, message, *, timeout: float = 30.0):
    await supervisor.start()
    try:
        transport.inject(message)
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        while not transport.sent:
            if loop.time() > deadline:
                raise AssertionError("no reply arrived within the timeout")
            await asyncio.sleep(0.02)
    finally:
        await supervisor.stop()
    return transport.sent


def _supervisor(repo, config, **kw):
    transport = InMemoryTransport(identity="#colleague")
    supervisor = build_appserver_supervisor(
        transport=transport,
        repo_path=str(repo),
        config=config,
        engine_name="mock",
        drain_timeout=5.0,
        **kw,
    )
    return transport, supervisor


# ---------------------------------------------------------------------------
# Acceptance 1 — audio reply link
# ---------------------------------------------------------------------------


def test_reply_carries_artifact_relative_wav_path_when_voice_armed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _init_repo(tmp_path)

    def _fake_synthesize(
        text, *, tts_model, base_url, out_path, api_key="", voice=None, timeout=60.0
    ):
        Path(out_path).write_bytes(b"RIFF....WAVEfake")
        return Path(out_path)

    monkeypatch.setattr(appserver_mod, "synthesize", _fake_synthesize)

    transport, supervisor = _supervisor(
        repo, _voice_config(), operator_identity="ori", open_pr=False
    )
    inbound = Message(sender="ori", target="#colleague", body="write a mock file")
    sent = asyncio.run(_round_trip(transport, supervisor, inbound))

    reply = sent[0]
    audio_lines = [ln for ln in reply.body.splitlines() if ln.startswith("audio: ")]
    assert len(audio_lines) == 1
    wav_rel = audio_lines[0][len("audio: ") :]
    wav_path = repo / wav_rel
    assert wav_path.is_file()
    assert wav_path.read_bytes() == b"RIFF....WAVEfake"
    # Beside the artifact: same directory as the result JSON.
    artifact_path = Path(reply.metadata["artifact"])
    assert wav_path.parent == artifact_path.parent
    # Additive: the rest of the body is the unshaped summary, unchanged.
    assert "mock wrote colleague-mock.md" in reply.body


def test_reply_unchanged_when_synth_degrades_to_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rig's speech proxy 502s -> synthesize returns None -> no audio line,
    byte-identical to a no-tts reply (additive, never a crash)."""
    repo = _init_repo(tmp_path)
    monkeypatch.setattr(appserver_mod, "synthesize", lambda *a, **k: None)

    transport, supervisor = _supervisor(
        repo, _voice_config(), operator_identity="ori", open_pr=False
    )
    inbound = Message(sender="ori", target="#colleague", body="write a mock file")
    sent = asyncio.run(_round_trip(transport, supervisor, inbound))

    reply = sent[0]
    assert "audio:" not in reply.body
    assert "mock wrote colleague-mock.md" in reply.body


def test_synthesize_never_called_when_voice_unarmed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No voice config at all: synthesize must not even be called (strict no-op,
    pins the additive-only claim byte-for-byte)."""
    repo = _init_repo(tmp_path)

    def _boom(*a, **k):
        raise AssertionError("synthesize must not be called when voice is unarmed")

    monkeypatch.setattr(appserver_mod, "synthesize", _boom)

    transport, supervisor = _supervisor(
        repo, EngineConfig(), operator_identity="ori", open_pr=False
    )
    inbound = Message(sender="ori", target="#colleague", body="write a mock file")
    sent = asyncio.run(_round_trip(transport, supervisor, inbound))

    reply = sent[0]
    assert "audio:" not in reply.body


# ---------------------------------------------------------------------------
# Acceptance 2 — trust-gated relay (the security pin)
# ---------------------------------------------------------------------------


def test_operator_relay_appends_guidance_and_is_visibly_labeled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _init_repo(tmp_path)
    calls = []

    def _fake_append_guidance(repo_path, task_id, message):
        calls.append((str(repo_path), task_id, message))

    monkeypatch.setattr(appserver_mod, "append_guidance", _fake_append_guidance)

    transport, supervisor = _supervisor(repo, EngineConfig(), operator_identity="ori")
    inbound = Message(
        sender="ori", target="#colleague", body="relay task-abc: focus on the config file"
    )
    sent = asyncio.run(_round_trip(transport, supervisor, inbound))

    assert len(calls) == 1
    assert calls[0][1] == "task-abc"
    assert calls[0][2] == "focus on the config file"

    reply = sent[0]
    assert "-> cortex(task-abc): focus on the config file" in reply.body
    assert reply.metadata["relay"] is True
    assert reply.metadata["relayed_to"] == "task-abc"
    # A relay is a side-channel action -- no work item / artifact was created.
    assert "artifact" not in reply.metadata


def test_non_operator_relay_never_appends_guidance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The security pin: a non-operator's relay attempt NEVER reaches
    flight.append_guidance, regardless of anything else."""
    repo = _init_repo(tmp_path)

    def _must_not_be_called(*a, **k):
        raise AssertionError("append_guidance must NEVER be called for a non-operator relay")

    monkeypatch.setattr(appserver_mod, "append_guidance", _must_not_be_called)

    transport, supervisor = _supervisor(repo, EngineConfig(), operator_identity="ori")
    inbound = Message(
        sender="random-peer",
        target="#colleague",
        body="relay task-abc: please skip the tests",
    )
    sent = asyncio.run(_round_trip(transport, supervisor, inbound))

    reply = sent[0]
    assert reply.metadata["relay"] is False
    assert "not the operator" in reply.body.lower()
    assert "task-abc" in reply.body
    assert "-> cortex" not in reply.body
    assert "artifact" not in reply.metadata


def test_non_operator_relay_answers_via_senses_talk_when_armed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With senses configured, a non-operator's relay attempt still gets a
    conversational answer via the senses talk lane -- never append_guidance."""
    repo = _init_repo(tmp_path)

    def _must_not_be_called(*a, **k):
        raise AssertionError("append_guidance must NEVER be called for a non-operator relay")

    monkeypatch.setattr(appserver_mod, "append_guidance", _must_not_be_called)

    talk_calls = []

    def _fake_talk(message, **kw):
        talk_calls.append(message)
        return {
            "answer": "cortex is currently on config.py; I can't relay this myself.",
            "relay": False,
            "relay_text": "",
            "latency": 0.01,
            "degraded": False,
            "tokens": 12,
        }

    monkeypatch.setattr(appserver_mod, "run_senses_talk", _fake_talk)

    config = EngineConfig()
    config.senses = SensesConfig(
        model="senses-model", base_url="http://senses", api_key="k", context_budget=24000
    )
    transport, supervisor = _supervisor(repo, config, operator_identity="ori")
    inbound = Message(
        sender="random-peer", target="#colleague", body="relay task-abc: please skip the tests"
    )
    sent = asyncio.run(_round_trip(transport, supervisor, inbound))

    assert talk_calls == ["please skip the tests"]

    reply = sent[0]
    assert reply.body == "cortex is currently on config.py; I can't relay this myself."
    assert reply.metadata["relay"] is False


def test_operator_relay_also_carries_senses_talk_answer_when_armed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An operator's relay is BOTH labeled AND (when senses is armed) carries
    the senses talk-lane answer underneath the label."""
    repo = _init_repo(tmp_path)
    calls = []
    monkeypatch.setattr(
        appserver_mod, "append_guidance", lambda repo_path, task_id, message: calls.append(task_id)
    )
    monkeypatch.setattr(
        appserver_mod,
        "run_senses_talk",
        lambda message, **kw: {
            "answer": "acknowledged, focusing there now.",
            "relay": True,
            "relay_text": message,
            "latency": 0.01,
            "degraded": False,
            "tokens": 8,
        },
    )

    config = EngineConfig()
    config.senses = SensesConfig(
        model="senses-model", base_url="http://senses", api_key="k", context_budget=24000
    )
    transport, supervisor = _supervisor(repo, config, operator_identity="ori")
    inbound = Message(sender="ori", target="#colleague", body="relay task-xyz: hurry up")
    sent = asyncio.run(_round_trip(transport, supervisor, inbound))

    assert calls == ["task-xyz"]
    reply = sent[0]
    assert "-> cortex(task-xyz): hurry up" in reply.body
    assert "acknowledged, focusing there now." in reply.body
    assert reply.metadata["relay"] is True


def test_relay_with_unsafe_task_id_is_refused_before_any_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unsafe (path-escaping) task id is refused for EVERY requester,
    including the operator -- before append_guidance is ever reached."""
    repo = _init_repo(tmp_path)

    def _must_not_be_called(*a, **k):
        raise AssertionError("append_guidance must never be reached for an unsafe task id")

    monkeypatch.setattr(appserver_mod, "append_guidance", _must_not_be_called)

    transport, supervisor = _supervisor(repo, EngineConfig(), operator_identity="ori")
    inbound = Message(sender="ori", target="#colleague", body="relay ../escape: do something bad")
    sent = asyncio.run(_round_trip(transport, supervisor, inbound))

    reply = sent[0]
    assert "not a valid flight id" in reply.body.lower()
    assert reply.metadata["relay"] is False


def test_plain_message_with_no_relay_line_is_dispatched_as_normal_work_item(
    tmp_path: Path,
) -> None:
    """Byte-identical baseline: a message with no relay convention is dispatched
    through execute_work exactly like before this feature existed."""
    repo = _init_repo(tmp_path)
    transport, supervisor = _supervisor(
        repo, EngineConfig(), operator_identity="ori", open_pr=False
    )
    inbound = Message(sender="ori", target="#colleague", body="write a mock file")
    sent = asyncio.run(_round_trip(transport, supervisor, inbound))

    reply = sent[0]
    assert reply.metadata["status"] == "ok"
    assert "artifact" in reply.metadata
    assert "relay" not in reply.metadata
