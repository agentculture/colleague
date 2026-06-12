"""t6 — resident supervisor wiring: transport ↔ harness through the pump bridge.

Covers spec targets c7 (the resident answers a peer end-to-end), h11 (the resident
is a separate explicit entry, never on the `colleague work` path). The end-to-end
pump is proven against a fake IRC connection + a fake engine — no live server, no
model.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip(
    "agent_lifecycle", reason="install the [culture] extra to test the resident seam"
)

from agent_lifecycle.runtime.supervisor import (  # noqa: E402
    Supervisor,
    SupervisorStatus,
)

from colleague.contract import TaskResult  # noqa: E402
from colleague.resident.supervisor import build_resident_supervisor  # noqa: E402


class _FakeConn:
    """Minimal _IRCConn fake: records outbound privmsgs; the adapter installs on_message."""

    def __init__(self, nick: str = "colleague") -> None:
        self.nick = nick
        self.on_message = None
        self.sent: list[tuple[str, str]] = []

    async def send_privmsg(self, target: str, text: str) -> None:
        self.sent.append((target, text))

    async def join(self, channel: str) -> None: ...
    async def part(self, channel: str) -> None: ...

    async def who(self, channel: str) -> list[str]:
        return [self.nick]


class _FakeEngine:
    def work(self, task, config) -> TaskResult:
        return TaskResult(
            task_id=task.id, status="completed", summary=f"reply to {task.instruction}"
        )


def _build(monkeypatch, tmp_path: Path, conn: _FakeConn) -> Supervisor:
    monkeypatch.setattr("colleague.registry.load", lambda name: _FakeEngine())
    return build_resident_supervisor(
        conn=conn,
        repo_path=str(tmp_path),
        config=SimpleNamespace(engine="mock"),
        engine_name="mock",
        drain_timeout=1.0,
    )


def test_build_returns_unstarted_supervisor(monkeypatch, tmp_path: Path) -> None:
    sup = _build(monkeypatch, tmp_path, _FakeConn())
    assert isinstance(sup, Supervisor)
    assert sup.status() is SupervisorStatus.STOPPED


def test_end_to_end_pump_peer_message_gets_a_reply(monkeypatch, tmp_path: Path) -> None:
    """c7: an inbound peer message pumps to the harness and the reply is sent back out."""
    conn = _FakeConn()
    sup = _build(monkeypatch, tmp_path, conn)

    async def _body() -> list[tuple[str, str]]:
        await sup.start()
        assert sup.status() is SupervisorStatus.RUNNING
        # The wire delivers an inbound mention; the pump bridge does the rest.
        conn.on_message("peer", "#colleague", "ping", True)
        for _ in range(200):  # poll up to ~2s for the reply to be sent
            if conn.sent:
                break
            await asyncio.sleep(0.01)
        await sup.stop()
        return conn.sent

    sent = asyncio.run(_body())
    assert sent == [("#colleague", "reply to ping")]


def test_resident_is_separate_from_work_path(monkeypatch, tmp_path: Path) -> None:
    """h11: the resident supervisor module never touches the `colleague work` / handoff path."""
    import re

    src = Path("colleague/resident/supervisor.py").read_text(encoding="utf-8")
    assert not re.search(r"^\s*(import|from)\s+.*handoff", src, re.MULTILINE)
    assert "execute_work" not in src
    assert "cli._commands.work" not in src and "cli/_commands/work" not in src


def test_serve_starts_then_stops_in_finally() -> None:
    """serve_resident's loop starts the supervisor, waits, then stops it in a finally.

    Exercised via the inner _serve with an injected stop awaitable so the
    blocking lifecycle is deterministic (serve_resident itself only wraps it in
    asyncio.run — the asyncio entry that keeps the CLI layer async-free)."""
    from colleague.resident.supervisor import _serve

    class _FakeSup:
        def __init__(self) -> None:
            self.events: list[str] = []

        async def start(self) -> None:
            self.events.append("start")

        async def stop(self) -> None:
            self.events.append("stop")

    async def _body() -> list[str]:
        sup = _FakeSup()
        ev = asyncio.Event()
        ev.set()  # resolve immediately so _serve falls through to stop()
        await _serve(sup, stop=ev.wait())
        return sup.events

    assert asyncio.run(_body()) == ["start", "stop"]
