"""Resident middle-manager presence (presence-default-everywhere, task t11).

Pins the operator-lane beats on the mesh resident: the cap-bounded proactive
update sink (cadence + grounding + cap-is-recorded), and the c19 boundary — an
operator gets the ack beat replied-to-origin, a non-operator NEVER does.
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

from colleague.config import EngineConfig, SensesConfig  # noqa: E402
from colleague.contract import ContextPacket  # noqa: E402
from colleague.presence import UpdateCadence  # noqa: E402
from colleague.resident import appserver as appserver_mod  # noqa: E402
from colleague.resident.appserver import (  # noqa: E402
    _ResidentPresenceSink,
    build_appserver_supervisor,
)


# ── the cap-bounded proactive update sink ─────────────────────────────────────
def test_resident_presence_sink_fires_on_cadence_caps_and_emits(monkeypatch) -> None:
    def _update(feed_tail, packet, senses_config, engine, **kw):
        return {
            "update": f"working — {len(feed_tail)} feed line(s) so far",
            "latency": 0.1,
            "tokens": 5,
            "degraded": False,
        }

    monkeypatch.setattr(appserver_mod, "run_senses_update", _update)
    emitted: list[str] = []
    sink = _ResidentPresenceSink(
        senses_config=object(),
        engine=object(),
        cadence=UpdateCadence(every_steps=2, on_phase_change=False, max_updates=2),
        emit=emitted.append,
    )

    sink(2, "read_file", "a.py", True)  # step 2 → fires update 1
    sink(4, "read_file", "b.py", True)  # step 4 → fires update 2
    sink(6, "read_file", "c.py", True)  # step 6 → cap reached → recorded, no emit

    assert len(emitted) == 2  # exactly the cap — never floods the channel (h17)
    assert all(e.startswith("working —") for e in emitted)  # grounded in the real feed
    assert len([r for r in sink.records if r.point == "senses-update"]) == 2
    capped = [c for c in sink.chat if c.get("capped")]
    assert len(capped) == 1  # cap recorded once, never silent (h4)


def test_resident_presence_sink_never_raises_on_degraded_update(monkeypatch) -> None:
    monkeypatch.setattr(
        appserver_mod,
        "run_senses_update",
        lambda *a, **k: {"update": None, "latency": 0.1, "tokens": None, "degraded": True},
    )
    emitted: list[str] = []
    sink = _ResidentPresenceSink(
        senses_config=object(),
        engine=object(),
        cadence=UpdateCadence(every_steps=1, on_phase_change=False, max_updates=4),
        emit=emitted.append,
    )
    sink(1, "read_file", "a.py", True)
    # A degraded update records (honest accounting) but emits no fabricated text.
    assert emitted == []
    assert [r.degraded for r in sink.records] == [True]


def test_resident_presence_sink_close_is_safe() -> None:
    sink = _ResidentPresenceSink(
        senses_config=object(), engine=object(), cadence=UpdateCadence(), emit=lambda _t: None
    )
    sink.close()  # the CockpitProgressSink duck — must not raise


# ── the c19 boundary: operator gets the ack beat, a non-operator does not ──────
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


def _patch_intake_ack(monkeypatch, ack: str = "on it — I'll get cortex started"):
    from colleague.contract import SensesRecord

    def _intake(text, senses_config, engine, **kw):
        packet = ContextPacket(original=text, interpretation=text, confidence=0.9, ack=ack)
        return packet, SensesRecord(point="senses-intake", latency=0.1, tokens=3, degraded=False)

    monkeypatch.setattr(appserver_mod, "run_senses_intake", _intake)
    monkeypatch.setattr(appserver_mod, "run_senses_speakback", lambda *a, **k: (None, None))


async def _drive(transport, supervisor, message, *, timeout: float = 30.0):
    await supervisor.start()
    try:
        transport.inject(message)
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        while not any(
            (getattr(m, "metadata", {}) or {}).get("status") is not None
            or (getattr(m, "metadata", {}) or {}).get("phase") == "refused"
            for m in transport.sent
        ):
            if loop.time() > deadline:
                raise AssertionError("no terminal reply arrived")
            await asyncio.sleep(0.02)
    finally:
        await supervisor.stop()
    return transport.sent


def test_operator_gets_ack_replied_to_origin_before_dispatch(tmp_path, monkeypatch) -> None:
    repo = _init_repo(tmp_path)
    _patch_intake_ack(monkeypatch)
    transport = InMemoryTransport(identity="#colleague")
    supervisor = build_appserver_supervisor(
        transport=transport,
        repo_path=str(repo),
        config=_senses_config(),
        engine_name="mock",
        operator_identity="ori",
        open_pr=False,
        drain_timeout=5.0,
    )
    sent = asyncio.run(
        _drive(transport, supervisor, Message(sender="ori", target="#ops", body="do it"))
    )

    ack = sent[0]
    assert ack.metadata.get("phase") == "ack"
    assert "on it — I'll get cortex started" in ack.body
    assert ack.target == "#ops"  # reply-to-origin (c20)


def test_non_operator_never_gets_the_ack_beat(tmp_path, monkeypatch) -> None:
    repo = _init_repo(tmp_path)
    _patch_intake_ack(monkeypatch)
    transport = InMemoryTransport(identity="#colleague")
    supervisor = build_appserver_supervisor(
        transport=transport,
        repo_path=str(repo),
        config=_senses_config(),
        engine_name="mock",
        operator_identity="ori",
        open_pr=False,
        drain_timeout=5.0,
    )
    # a random peer — downgraded to read-only explorer; the c19 boundary means
    # NO operator-lane beats (no ack phase message ever enqueued).
    sent = asyncio.run(
        _drive(transport, supervisor, Message(sender="rando", target="#ops", body="investigate"))
    )
    assert not any((getattr(m, "metadata", {}) or {}).get("phase") == "ack" for m in sent)
