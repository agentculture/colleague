"""t8 (wire) — IRC connection: pure parsing + inbound dispatch against fakes.

The live network handshake is exercised by manual end-to-end against a running
mesh (no IRC server in the automated suite); here we test the pure helpers and
the line-dispatch (PING→PONG, PRIVMSG→on_message, 353→members) deterministically.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip(
    "agent_lifecycle", reason="install the [culture] extra to test the resident seam"
)

from colleague.resident.connection import (  # noqa: E402
    IRCConnection,
    is_mention,
    parse_line,
)
from colleague.resident.transport import _IRCConn  # noqa: E402


def test_parse_privmsg() -> None:
    m = parse_line(":alice!u@h PRIVMSG #colleague :hey there\r\n")
    assert m == {
        "command": "PRIVMSG",
        "sender": "alice",
        "target": "#colleague",
        "body": "hey there",
    }


def test_parse_ping() -> None:
    assert parse_line("PING :LAG12345") == {"command": "PING", "token": "LAG12345"}


def test_parse_353_names_strips_prefixes() -> None:
    m = parse_line(":srv 353 me = #colleague :alice @bob +carol\r\n")
    assert m == {"command": "353", "channel": "#colleague", "members": ["alice", "bob", "carol"]}


def test_parse_empty_and_unknown() -> None:
    assert parse_line("") == {}
    assert parse_line(":srv 001 me :welcome")["command"] == "001"


def test_is_mention() -> None:
    assert is_mention("hey colleague, ping?", "colleague") is True
    assert is_mention("nothing for me", "colleague") is False
    assert is_mention("anything", "") is False


def test_connection_satisfies_irc_conn_protocol() -> None:
    conn = IRCConnection("localhost", 6667, nick="colleague")
    assert isinstance(conn, _IRCConn)
    assert conn.nick == "colleague"


class _FakeWriter:
    def __init__(self) -> None:
        self.data = b""

    def write(self, b: bytes) -> None:
        self.data += b

    async def drain(self) -> None:
        return None


def test_handle_ping_writes_pong() -> None:
    conn = IRCConnection("h", 1, nick="colleague")
    conn._writer = _FakeWriter()
    asyncio.run(conn._handle_line("PING :tok99"))
    assert conn._writer.data == b"PONG :tok99\r\n"


def test_handle_privmsg_fires_on_message_with_mention() -> None:
    conn = IRCConnection("h", 1, nick="colleague")
    seen: list[tuple[str, str, str, bool]] = []
    conn.on_message = lambda s, t, b, m: seen.append((s, t, b, m))
    asyncio.run(conn._handle_line(":peer!u@h PRIVMSG #colleague :hey colleague\r\n"))
    assert seen == [("peer", "#colleague", "hey colleague", True)]


def test_handle_353_populates_who() -> None:
    conn = IRCConnection("h", 1, nick="colleague")
    asyncio.run(conn._handle_line(":srv 353 me = #colleague :alice @colleague\r\n"))
    assert asyncio.run(conn.who("#colleague")) == ["alice", "colleague"]
