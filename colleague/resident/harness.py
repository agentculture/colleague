"""colleague.resident.harness — colleague's bounded tool-loop as a long-lived Harness.

:class:`ColleagueHarness` adapts colleague's synchronous, bounded work-item loop
(:meth:`colleague.engine.Engine.work`) onto agent-lifecycle's asyncio-native
``Harness`` Protocol (``start`` / ``feed_message`` / ``replies`` / ``stop``), so
the *same* coder-agent engine that drives a bounded ``colleague work`` item can
also serve as a resident Culture peer that answers messages over a long-lived
session.

Each inbound :class:`~agent_lifecycle.runtime.message.Message` is processed as
ONE bounded turn — a fresh :class:`~colleague.contract.Task` run through
``engine.work`` (the existing tool-loop, **no git handoff**: the resident
converses, it does not open PRs). The reply is the turn's ``summary``. The
harness *session* outlives any single turn: a turn that exhausts its step budget
ends *that turn* with a partial answer; the session continues to the next message
— honesty **h10**, the bounded step cap bounds a turn, never the resident's
presence.

This is **additive**: it wraps the loop, it does not change it. ``colleague
work`` stays byte-identical (honesty **h3**). ``engine.work`` is synchronous, so
it runs in the event loop's default executor — the inbound/outbound pumps and the
transport keepalive stay responsive during a long turn.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any, Optional

from agent_lifecycle.runtime.message import Message

from colleague import registry
from colleague.contract import Task

if TYPE_CHECKING:  # pragma: no cover - typing only, no runtime import
    from colleague.config import EngineConfig
    from colleague.engine import Engine

# Sentinel placed on the reply queue by stop() to end the replies() stream.
_STOP: object = object()


class ColleagueHarness:
    """agent-lifecycle ``Harness`` adapter wrapping colleague's bounded engine loop.

    Satisfies :class:`agent_lifecycle.runtime.harness.Harness` structurally (no
    base-class import required). All four methods are asyncio-native; none accepts
    a transport, presence, channel, or connection — the Supervisor bridges the
    transport layer externally.

    Args:
        repo_path: The repo the resident works in (each turn runs here).
        config: The resolved :class:`~colleague.config.EngineConfig` — the SAME
            backend colleague uses for bounded work items (decision c21).
        engine_name: Backend name; defaults to ``config.engine``.
        agent_nick: This resident's identity, used as ``sender`` on replies.
        default_target: Fallback ``target`` for a reply when the inbound message
            carries none.
    """

    def __init__(
        self,
        repo_path: str,
        config: "EngineConfig",
        *,
        engine_name: str | None = None,
        agent_nick: str = "colleague",
        default_target: str = "",
    ) -> None:
        self._repo_path = str(repo_path)
        self._config = config
        self._engine_name = engine_name or getattr(config, "engine", "mock")
        self._agent_nick = agent_nick
        self._default_target = default_target
        self._engine: Optional["Engine"] = None
        # Queue bridges synchronous turn completion → the replies() async generator.
        self._reply_queue: "asyncio.Queue[Any]" = asyncio.Queue()
        # Memoised single reply stream: replies() is a single-consumer iterator
        # (one outbound pump drains it). Returning a fresh generator on every call
        # would let a second caller race the queue and silently lose messages, so
        # we hand back the SAME iterator — a second concurrent `async for` then
        # fails loudly ("generator already running") instead of dropping replies.
        self._replies_iter: Optional[AsyncIterator[Message]] = None

    async def start(self) -> None:
        """Resolve the engine once (the long-lived session boots here)."""
        self._engine = registry.load(self._engine_name)
        self._replies_iter = None  # fresh reply stream per session (supports restart)

    async def feed_message(self, message: Message) -> None:
        """Run one bounded turn for *message* and enqueue the reply.

        The turn is ``engine.work`` over a fresh ``Task`` built from
        ``message.body`` — the existing bounded tool-loop, with NO git handoff.
        It runs in the default executor (``engine.work`` is synchronous) so a
        long turn never blocks the event loop / transport keepalive. The turn's
        ``summary`` becomes the reply body; a step-budget-exhausted turn still
        produces a (partial) reply and the session continues (h10).
        """
        if self._engine is None:
            # Tolerate a feed before start() — boot lazily rather than NPE.
            self._engine = registry.load(self._engine_name)

        body = getattr(message, "body", "") or ""
        target = getattr(message, "target", "") or self._default_target
        task = Task.new(self._repo_path, body, engine=self._engine_name)

        engine = self._engine
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, engine.work, task, self._config)

        reply = Message(
            sender=self._agent_nick,
            target=target,
            body=result.summary or "",
            kind="message",
            metadata={"task_id": result.task_id, "status": result.status},
        )
        await self._reply_queue.put(reply)

    def replies(self) -> AsyncIterator[Message]:
        """Return the single async iterator yielding reply Messages until :meth:`stop`.

        The SAME iterator is returned on every call within a session (memoised) —
        the reply stream has exactly one consumer (the supervisor's outbound pump).
        """
        if self._replies_iter is None:
            self._replies_iter = self._replies_gen()
        return self._replies_iter

    async def _replies_gen(self) -> AsyncIterator[Message]:
        while True:
            item = await self._reply_queue.get()
            if item is _STOP:
                return
            yield item

    async def stop(self) -> None:
        """End the reply stream (insert the stop sentinel) and drop the engine."""
        await self._reply_queue.put(_STOP)
        self._engine = None
