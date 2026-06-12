"""colleague.resident.connection — the live IRC wire for the resident.

:class:`IRCConnection` is a small hand-rolled IRC client over
``asyncio.open_connection`` (a *client* primitive — colleague never imports
``socket`` or starts a server) that satisfies
:class:`colleague.resident.transport._IRCConn`. It is the concrete wire the
:class:`~colleague.resident.transport.IRCTransportAdapter` wraps; cultureagent's
shared IRC transport is the reference pattern (cite-don't-import, c18).

:func:`serve_live` is the SYNC entry the ``colleague promote --serve`` verb calls:
it owns ``asyncio.run`` (so the CLI layer stays async-free — the boundary guard
forbids ``asyncio`` outside ``colleague/resident/``), connects, joins channels,
and runs the supervisor until the process is interrupted.

The pure parsing (:func:`parse_line`, :func:`is_mention`) and the inbound dispatch
are unit-tested against fakes; the live network handshake is exercised by manual
end-to-end against a running mesh (no IRC server in the automated suite).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Callable, Optional

if TYPE_CHECKING:  # pragma: no cover - typing only
    from colleague.config import EngineConfig


def parse_line(raw: str) -> dict[str, Any]:
    """Parse one raw IRC line into a small dict.

    Recognises the slice the resident needs:

    * ``PING :token``                       → ``{"command": "PING", "token": …}``
    * ``:nick!user@host PRIVMSG #chan :msg`` → ``{"command": "PRIVMSG",
      "sender": "nick", "target": "#chan", "body": "msg"}``
    * ``:server 353 me = #chan :a b @c``    → ``{"command": "353",
      "channel": "#chan", "members": ["a", "b", "c"]}`` (op/voice prefixes stripped)

    Anything else returns ``{"command": <verb>}`` (or ``{}`` for an empty line).
    """
    line = raw.rstrip("\r\n")
    if not line:
        return {}

    if line.startswith("PING"):
        _, _, token = line.partition(":")
        return {"command": "PING", "token": token.strip()}

    prefix = ""
    rest = line
    if line.startswith(":"):
        prefix, _, rest = line[1:].partition(" ")

    verb, _, args = rest.partition(" ")
    verb = verb.upper()

    if verb == "PRIVMSG":
        target, _, body = args.partition(" ")
        body = body[1:] if body.startswith(":") else body
        sender = prefix.split("!", 1)[0]
        return {"command": "PRIVMSG", "sender": sender, "target": target, "body": body}

    if verb == "353":  # RPL_NAMREPLY — "<me> = <channel> :<names>"
        head, _, names = args.partition(":")
        parts = head.split()
        channel = parts[-1] if parts else ""
        members = [n.lstrip("@+%&~") for n in names.split()]
        return {"command": "353", "channel": channel, "members": members}

    return {"command": verb}


def is_mention(body: str, nick: str) -> bool:
    """Whether *body* addresses *nick* (a simple case-insensitive substring match)."""
    return bool(nick) and nick.lower() in body.lower()


class IRCConnection:
    """A minimal asyncio IRC client satisfying ``_IRCConn``.

    Construction does NOT connect; :meth:`connect` opens the stream and registers.
    A background read loop dispatches inbound PRIVMSGs to :attr:`on_message`
    ``(sender, target, body, mention)``, answers PING, and tracks channel members
    from NAMES (353) replies so :meth:`who` can answer locally.
    """

    def __init__(self, host: str, port: int, *, nick: str) -> None:
        self.host = host
        self.port = port
        self.nick = nick
        self.on_message: Optional[Callable[[str, str, str, bool], None]] = None
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._read_task: Optional["asyncio.Task[None]"] = None
        self._members: dict[str, list[str]] = {}
        self._running = False

    async def connect(self) -> None:
        """Open the connection, register (NICK/USER), and start the read loop."""
        self._reader, self._writer = await asyncio.open_connection(self.host, self.port)
        await self._send_raw(f"NICK {self.nick}")
        await self._send_raw(f"USER {self.nick} 0 * :{self.nick} (colleague resident)")
        self._running = True
        self._read_task = asyncio.create_task(self._read_loop(), name="resident-irc-read")

    async def disconnect(self) -> None:
        """Stop the read loop and close the stream."""
        self._running = False
        if self._read_task is not None:
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass
            self._read_task = None
        if self._writer is not None:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except OSError:
                pass
            self._writer = None

    async def send_privmsg(self, target: str, text: str) -> None:
        # IRC has no multi-line messages; send one PRIVMSG per line.
        for chunk in (text or "").splitlines() or [""]:
            await self._send_raw(f"PRIVMSG {target} :{chunk}")

    async def join(self, channel: str) -> None:
        await self._send_raw(f"JOIN {channel}")

    async def part(self, channel: str) -> None:
        await self._send_raw(f"PART {channel}")
        self._members.pop(channel, None)

    async def who(self, channel: str) -> list[str]:
        return list(self._members.get(channel, []))

    # -- internals -----------------------------------------------------------
    async def _send_raw(self, line: str) -> None:
        if self._writer is None:  # pragma: no cover - guarded by connect()
            raise RuntimeError("IRCConnection not connected")
        self._writer.write((line + "\r\n").encode("utf-8"))
        await self._writer.drain()

    async def _read_loop(self) -> None:  # pragma: no cover - exercised via _handle_line + live e2e
        assert self._reader is not None
        while self._running:
            raw = await self._reader.readline()
            if not raw:
                break
            await self._handle_line(raw.decode("utf-8", "replace"))

    async def _handle_line(self, raw: str) -> None:
        """Dispatch one parsed line: PING→PONG, PRIVMSG→on_message, 353→members."""
        msg = parse_line(raw)
        command = msg.get("command")
        if command == "PING":
            await self._send_raw(f"PONG :{msg.get('token', '')}")
        elif command == "PRIVMSG":
            if self.on_message is not None:
                self.on_message(
                    msg["sender"],
                    msg["target"],
                    msg["body"],
                    is_mention(msg["body"], self.nick),
                )
        elif command == "353":
            self._members[msg["channel"]] = list(msg["members"])


def serve_live(
    *,
    host: str,
    port: int,
    nick: str,
    channels: list[str],
    repo_path: str,
    config: "EngineConfig",
    engine_name: str | None,
    agent_nick: str,
    default_target: str,
) -> None:
    """Connect, join *channels*, and run the resident supervisor until interrupted.

    The SYNC entry the ``colleague promote --serve`` verb calls — it owns
    ``asyncio.run`` so the CLI layer never touches asyncio. Blocks until the
    process is interrupted (Ctrl-C / SIGTERM), then parts cleanly.
    """
    asyncio.run(
        _serve_live(
            host=host,
            port=port,
            nick=nick,
            channels=channels,
            repo_path=repo_path,
            config=config,
            engine_name=engine_name,
            agent_nick=agent_nick,
            default_target=default_target,
        )
    )


async def _serve_live(  # pragma: no cover - live wiring, exercised by manual e2e
    *,
    host: str,
    port: int,
    nick: str,
    channels: list[str],
    repo_path: str,
    config: "EngineConfig",
    engine_name: str | None,
    agent_nick: str,
    default_target: str,
) -> None:
    from colleague.resident.supervisor import build_resident_supervisor

    conn = IRCConnection(host, port, nick=nick)
    supervisor = build_resident_supervisor(
        conn=conn,
        repo_path=repo_path,
        config=config,
        engine_name=engine_name,
        agent_nick=agent_nick,
        default_target=default_target,
    )
    await conn.connect()
    for channel in channels:
        await conn.join(channel)
    await supervisor.start()
    try:
        await asyncio.Event().wait()
    finally:
        await supervisor.stop()
        await conn.disconnect()
