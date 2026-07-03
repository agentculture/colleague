"""Cortex/senses mesh-resident split-mode wiring (cortex/senses arc, t9).

With a senses model resolved, the ``[resident]`` appserver runs an inbound mesh
message through senses INTAKE (→ a ContextPacket on the work item, so the loop
records mode=split) and shapes the reply via SPEAK-BACK; the artifact keeps the
raw cortex summary. The c19 trust model is UNCHANGED — intake runs regardless of
trust tier, but write authorization (the role) is untouched. With no senses model
resolved the resident is byte-identical (proven here + by the unmodified existing
resident suite).

End-to-end through agent-lifecycle's in-process Supervisor + reference transport
against ``--engine mock`` (the established resident harness), with intake /
speak-back monkeypatched for determinism (the mock cannot produce a real packet).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

pytest.importorskip(
    "agent_lifecycle", reason="install the [culture]/[resident] extra to test the resident seam"
)

import subprocess  # noqa: E402

from agent_lifecycle.reference import InMemoryTransport  # noqa: E402
from agent_lifecycle.runtime.message import Message  # noqa: E402

from colleague.config import EngineConfig, SensesConfig  # noqa: E402
from colleague.contract import ContextPacket, SensesRecord  # noqa: E402
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


def _senses_config() -> EngineConfig:
    config = EngineConfig()
    config.senses = SensesConfig(
        model="senses-model", base_url="http://senses", api_key="k", context_budget=24000
    )
    return config


def _patch_senses(monkeypatch, *, shaped="shaped mesh reply", task_type="bugfix"):
    def _intake(text, senses_config, engine, **kw):
        # Packet.original is set to the inbound text VERBATIM (never the model).
        return (
            ContextPacket(original=text, interpretation="perceived", task_type=task_type),
            SensesRecord(point="senses-intake", latency=0.1, tokens=10, degraded=False),
        )

    def _speak(summary, senses_config, engine, **kw):
        return shaped, SensesRecord(point="senses-speakback", latency=0.1, tokens=5, degraded=False)

    monkeypatch.setattr(appserver_mod, "run_senses_intake", _intake)
    monkeypatch.setattr(appserver_mod, "run_senses_speakback", _speak)


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
# Acceptance 1 — packet + mode on the artifact, shaped speak-back as the reply
# ---------------------------------------------------------------------------


def test_operator_split_run_records_packet_mode_and_shapes_reply(tmp_path, monkeypatch) -> None:
    repo = _init_repo(tmp_path)
    _patch_senses(monkeypatch, shaped="Done — wrote the mock file, in plain words.")
    transport, supervisor = _supervisor(
        repo, _senses_config(), operator_identity="ori", open_pr=False
    )

    inbound = Message(sender="ori", target="#colleague", body="write a mock file")
    sent = asyncio.run(_round_trip(transport, supervisor, inbound))

    assert len(sent) == 1
    reply = sent[0]
    # The mesh reply is the SHAPED speak-back...
    assert reply.body == "Done — wrote the mock file, in plain words."
    assert reply.metadata["status"] == "ok"

    # ...while the artifact carries mode=split + the packet + intake/speak-back
    # timings, and keeps the RAW cortex summary (never the shaped text).
    data = json.loads(Path(reply.metadata["artifact"]).read_text(encoding="utf-8"))
    assert data["senses"]["mode"] == "split"
    assert data["senses"]["packet"]["original"] == "write a mock file"  # verbatim
    points = [r["point"] for r in data["senses"]["records"]]
    assert points == ["senses-intake", "senses-speakback"]
    assert "mock wrote colleague-mock.md" in data["summary"]  # raw cortex summary
    assert data["summary"] != reply.body  # display shaped, artifact raw


def test_c19_trust_unchanged_intake_runs_for_nonoperator(tmp_path, monkeypatch) -> None:
    """A non-operator request runs read-only (explorer role) — but intake STILL
    perceives it (senses is tools-off; the trust tier is unchanged)."""
    repo = _init_repo(tmp_path)
    _patch_senses(monkeypatch, shaped="here is what I found")
    transport, supervisor = _supervisor(repo, _senses_config(), operator_identity="ori")

    inbound = Message(sender="random-peer", target="#colleague", body="investigate the repo")
    sent = asyncio.run(_round_trip(transport, supervisor, inbound))

    reply = sent[0]
    assert reply.metadata["role"] == "explorer"  # trust tier UNCHANGED (read-only)
    assert reply.body == "here is what I found"  # still shaped
    data = json.loads(Path(reply.metadata["artifact"]).read_text(encoding="utf-8"))
    assert data["senses"]["mode"] == "split"
    assert data["senses"]["packet"]["original"] == "investigate the repo"


# ---------------------------------------------------------------------------
# Acceptance 2 — senses unresolved: byte-identical
# ---------------------------------------------------------------------------


def test_senses_unresolved_resident_is_byte_identical(tmp_path, monkeypatch) -> None:
    def _boom(*a, **k):
        raise AssertionError("senses must not run without a senses model")

    monkeypatch.setattr(appserver_mod, "run_senses_intake", _boom)
    monkeypatch.setattr(appserver_mod, "run_senses_speakback", _boom)
    repo = _init_repo(tmp_path)
    transport, supervisor = _supervisor(
        repo, EngineConfig(), operator_identity="ori", open_pr=False
    )

    inbound = Message(sender="ori", target="#colleague", body="write a mock file")
    sent = asyncio.run(_round_trip(transport, supervisor, inbound))

    reply = sent[0]
    # Reply is the raw cortex summary; no senses key on the artifact.
    assert "mock wrote colleague-mock.md" in reply.body
    data = json.loads(Path(reply.metadata["artifact"]).read_text(encoding="utf-8"))
    assert "senses" not in data  # omit-when-None → byte-identical artifact
