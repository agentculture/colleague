"""t3 — IRCTransportAdapter: a thin IRC Transport/Presence over an injected wire.

Covers spec targets c1 (the resident joins the mesh / is reachable), h6 (reachable
+ holds channels), h7 (a named channel exists to share). Tested against a fake
connection — no live IRC server, no socket — exactly as cultureagent tests its
own adapter.
"""

from __future__ import annotations

import asyncio

import pytest
from agent_lifecycle.runtime.message import Message
from agent_lifecycle.runtime.transport import Presence, Transport

from colleague.resident.transport import IRCTransportAdapter


class _FakeConn:
    """A minimal _IRCConn fake: records outbound verbs, fakes membership + who()."""

    def __init__(self, nick: str = "colleague") -> None:
        self.nick = nick
        self.on_message = None  # installed by the adapter
        self.sent: list[tuple[str, str]] = []
        self.members: dict[str, list[str]] = {}
        self.joined: list[str] = []
        self.parted: list[str] = []

    async def send_privmsg(self, target: str, text: str) -> None:
        self.sent.append((target, text))

    async def join(self, channel: str) -> None:
        self.joined.append(channel)
        self.members.setdefault(channel, []).append(self.nick)

    async def part(self, channel: str) -> None:
        self.parted.append(channel)
        self.members.get(channel, []).clear()

    async def who(self, channel: str) -> list[str]:
        return list(self.members.get(channel, []))


def test_satisfies_transport_and_presence() -> None:
    """The adapter structurally satisfies BOTH agent-lifecycle Protocols."""
    adapter = IRCTransportAdapter(_FakeConn())
    assert isinstance(adapter, Transport)
    assert isinstance(adapter, Presence)


def test_identity_is_connection_nick() -> None:
    adapter = IRCTransportAdapter(_FakeConn(nick="spark-colleague"))
    assert adapter.identity == "spark-colleague"


def test_send_dispatches_privmsg() -> None:
    conn = _FakeConn()
    adapter = IRCTransportAdapter(conn)
    asyncio.run(adapter.send(Message(sender="colleague", target="#c", body="hello")))
    asyncio.run(adapter.send(Message(sender="colleague", target="#c", body="hi", kind="privmsg")))
    assert conn.sent == [("#c", "hello"), ("#c", "hi")]


def test_send_unknown_kind_raises() -> None:
    adapter = IRCTransportAdapter(_FakeConn())
    with pytest.raises(ValueError):
        asyncio.run(adapter.send(Message(sender="c", target="#c", body="x", kind="bogus")))


def test_inbound_irc_becomes_message_via_receive() -> None:
    """An inbound callback fire is translated to a Message and yielded by receive()."""
    conn = _FakeConn()
    adapter = IRCTransportAdapter(conn)

    async def _body() -> Message:
        gen = adapter.receive()
        # Simulate the wire delivering an inbound mention.
        conn.on_message("peer", "#colleague", "hey colleague", True)
        return await gen.__anext__()

    msg = asyncio.run(_body())
    assert msg.sender == "peer"
    assert msg.target == "#colleague"
    assert msg.body == "hey colleague"
    assert msg.kind == "privmsg"
    assert msg.metadata["mention"] is True


def test_presence_join_part_who() -> None:
    """join/part change membership; who() returns the member list (h6 — holds channels)."""
    conn = _FakeConn(nick="colleague")
    adapter = IRCTransportAdapter(conn)

    async def _body() -> tuple[list[str], list[str]]:
        await adapter.join("#colleague")
        present = await adapter.who("#colleague")
        await adapter.part("#colleague")
        empty = await adapter.who("#colleague")
        return present, empty

    present, empty = asyncio.run(_body())
    assert present == ["colleague"]
    assert empty == []
    assert conn.joined == ["#colleague"] and conn.parted == ["#colleague"]
