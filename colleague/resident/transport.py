"""colleague.resident.transport — a thin IRC Transport/Presence over an IRC connection.

:class:`IRCTransportAdapter` adapts an IRC connection onto agent-lifecycle's
``Transport`` (``identity`` / ``send`` / ``receive``) and ``Presence``
(``join`` / ``part`` / ``who``) Protocols. It is deliberately thin and
**connection-agnostic**: it wraps any object satisfying the minimal
:class:`_IRCConn` surface — an outbound ``send_privmsg`` + presence verbs and a
single inbound ``on_message`` callback slot the adapter installs. This is the
colleague-owned analogue of cultureagent's ``IRCTransportAdapter``
(``cultureagent/clients/claude/runtime/transport.py``), cited as the reference
pattern (cite-don't-import, decision c18): the *adapter* is the agent-lifecycle
seam; the concrete wire (a hand-rolled ``asyncio.open_connection`` IRC client
over ``agentirc``) is built and injected by the supervisor wiring (t6).

Keeping the wire behind an injected interface makes the adapter fully
unit-testable against a fake — no live IRC server, no socket. ``colleague``
never imports ``socket``; the connection owns the wire.

Outbound ``send(Message)`` maps ``message.kind`` to a connection verb
(``message`` / ``privmsg`` → ``send_privmsg``); an unknown kind raises
``ValueError`` (a user-input error in agent-lifecycle terms). Inbound traffic
arrives via the installed ``on_message(sender, target, body, mention)`` callback,
is translated to a ``Message`` (``kind="privmsg"``, ``metadata={"mention": …}``),
and is yielded by ``receive()``.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable

from agent_lifecycle.runtime.message import Message

#: Outbound kinds the adapter maps to ``send_privmsg``.
KIND_MESSAGE = "message"  # agent-lifecycle default
KIND_PRIVMSG = "privmsg"

#: Inbound kind yielded by ``receive()``.
_KIND_INBOUND = "privmsg"


@runtime_checkable
class _IRCConn(Protocol):
    """The minimal slice of an IRC connection :class:`IRCTransportAdapter` wraps.

    A real connection (hand-rolled over ``asyncio.open_connection`` against
    ``agentirc``) satisfies this; so does a test fake. ``on_message`` is a
    callback slot the adapter OWNS once it wraps the connection — the connection
    invokes it ``(sender, target, body, mention)`` for each inbound line.
    """

    nick: str
    on_message: Any

    async def send_privmsg(self, target: str, text: str) -> None: ...
    async def join(self, channel: str) -> None: ...
    async def part(self, channel: str) -> None: ...
    async def who(self, channel: str) -> list[str]: ...


class IRCTransportAdapter:
    """Adapt an IRC connection to agent-lifecycle's ``Transport`` + ``Presence``.

    Satisfies both Protocols structurally. On construction it installs its own
    inbound handler on the wrapped connection's ``on_message`` slot; each fired
    callback enqueues a translated :class:`Message` that ``receive()`` drains
    forever.

    Args:
        conn: Any object satisfying :class:`_IRCConn`.
    """

    def __init__(self, conn: _IRCConn) -> None:
        self._conn = conn
        self._inbox: "asyncio.Queue[Message]" = asyncio.Queue()
        # The adapter owns inbound routing once it wraps the connection.
        self._conn.on_message = self._handle_inbound

    # -- Transport.identity --------------------------------------------------
    @property
    def identity(self) -> str:
        """This transport's own identity — the connection's IRC nick."""
        return self._conn.nick

    # -- Transport.send ------------------------------------------------------
    async def send(self, message: Message) -> None:
        """Dispatch *message* onto the connection's outbound verb.

        ``message`` / ``privmsg`` → ``send_privmsg(target, body)``. An unknown
        ``kind`` raises :class:`ValueError` (user-input error).
        """
        if message.kind in (KIND_MESSAGE, KIND_PRIVMSG):
            await self._conn.send_privmsg(message.target, message.body)
        else:
            raise ValueError(
                f"unknown message kind {message.kind!r}; expected one of: "
                f"{KIND_MESSAGE}, {KIND_PRIVMSG}"
            )

    # -- Transport.receive ---------------------------------------------------
    async def receive(self) -> AsyncIterator[Message]:
        """Yield inbound IRC traffic as agent-lifecycle ``Message`` objects (forever)."""
        while True:
            yield await self._inbox.get()

    # -- Presence ------------------------------------------------------------
    async def join(self, channel: str) -> None:
        """Join *channel* on the wrapped connection."""
        await self._conn.join(channel)

    async def part(self, channel: str) -> None:
        """Leave *channel* on the wrapped connection."""
        await self._conn.part(channel)

    async def who(self, channel: str) -> list[str]:
        """Return the current member list for *channel* (delegated to the connection)."""
        return list(await self._conn.who(channel))

    # -- inbound callback (installed on the connection) ----------------------
    def _handle_inbound(self, sender: str, target: str, body: str, mention: bool = False) -> None:
        self._inbox.put_nowait(
            Message(
                sender=sender,
                target=target,
                body=body,
                kind=_KIND_INBOUND,
                metadata={"mention": mention},
            )
        )
