"""colleague.resident.supervisor — wire the resident harness to the IRC transport.

:func:`build_resident_supervisor` constructs the :class:`IRCTransportAdapter`
(over an injected IRC connection) and the :class:`ColleagueHarness` (colleague's
bounded loop as its driving engine) and returns an ``agent_lifecycle``
``Supervisor`` — the pump bridge — that wires them: inbound ``transport.receive()`` →
``harness.feed_message()``; outbound ``harness.replies()`` → ``transport.send()``,
with drain-bounded shutdown.

The returned supervisor is **unstarted**: the caller (the ``colleague promote``
verb) owns its ``start()`` / ``stop()`` lifecycle. The resident is a SEPARATE,
explicitly-started process — it is NEVER reached by the bounded ``colleague
work`` path (honesty **h11**). This module imports nothing from the work CLI or
the git handoff; a conversational resident neither branches nor opens PRs.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Awaitable

from agent_lifecycle.runtime.supervisor import Supervisor

from colleague.resident.harness import ColleagueHarness
from colleague.resident.transport import IRCTransportAdapter

if TYPE_CHECKING:  # pragma: no cover - typing only
    from colleague.config import EngineConfig
    from colleague.resident.transport import _IRCConn


def build_resident_supervisor(
    *,
    conn: "_IRCConn",
    repo_path: str,
    config: "EngineConfig",
    engine_name: str | None = None,
    agent_nick: str = "colleague",
    default_target: str = "",
    drain_timeout: float = Supervisor.DEFAULT_DRAIN_TIMEOUT,
) -> Supervisor:
    """Wire the resident transport ↔ harness through agent-lifecycle's Supervisor.

    Args:
        conn: An object satisfying :class:`colleague.resident.transport._IRCConn`
            (the live IRC wire, or a fake). Wrapped in an
            :class:`IRCTransportAdapter`.
        repo_path: The repo the resident works in (each turn runs here).
        config: The resolved :class:`~colleague.config.EngineConfig` — the same
            backend colleague uses for bounded work items (c21).
        engine_name: Backend name; defaults to ``config.engine``.
        agent_nick: This resident's identity (``sender`` on outbound replies).
        default_target: Fallback reply target when an inbound message carries none.
        drain_timeout: Seconds the supervisor lets the outbound pump drain on stop.

    Returns:
        An UNSTARTED ``agent_lifecycle.runtime.supervisor.Supervisor`` bridging the
        constructed transport adapter and harness. The caller owns its lifecycle.
    """
    transport = IRCTransportAdapter(conn)
    harness = ColleagueHarness(
        repo_path,
        config,
        engine_name=engine_name,
        agent_nick=agent_nick,
        default_target=default_target,
    )
    return Supervisor(transport, harness, drain_timeout=drain_timeout)


def serve_resident(supervisor: Supervisor) -> None:
    """Run *supervisor* until interrupted — the resident's blocking entry point.

    This OWNS the asyncio event loop (``asyncio.run``) so the ``colleague``
    CLI layer stays async-free: the boundary guard forbids ``import asyncio``
    outside ``colleague/resident/``, so the ``colleague promote`` verb calls this
    SYNCHRONOUS function rather than touching asyncio itself. Blocks until the
    process is interrupted (Ctrl-C / SIGTERM), then drains and stops cleanly.
    """
    asyncio.run(_serve(supervisor))


async def _serve(supervisor: Supervisor, *, stop: "Awaitable[object] | None" = None) -> None:
    """Start *supervisor*, wait for *stop* (or forever), then stop it in a finally.

    ``stop`` defaults to a never-completing wait (the resident runs until the
    process is interrupted); a test injects an already-resolving awaitable so the
    start → stop lifecycle is exercised deterministically.
    """
    await supervisor.start()
    try:
        await (stop if stop is not None else asyncio.Event().wait())
    finally:
        await supervisor.stop()
