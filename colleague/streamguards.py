"""Stream guards — idle + lifetime watchdogs over ONE streamed turn (c12/h10).

adapted-from: qwen-code packages/core/src/core/openaiContentGenerator/
constants.ts:1-68 (``DEFAULT_STREAM_IDLE_TIMEOUT_MS`` / ``DEFAULT_STREAM_MAX_LIFETIME_MS``)
and pipeline.ts:412-530 (``withStreamGuards``) — Copyright 2026 Qwen Team,
Apache-2.0. Re-implemented as stdlib Python (adopt-from-qwen-code arc).

``COLLEAGUE_TIMEOUT`` bounds every socket operation; it never bounded a stream
that keeps *dripping* — a byte at a time, never a newline — which resets any
idle watchdog forever (qwen-code issue #8597 burned hours that way). Two
independent guards close that:

- ``COLLEAGUE_STREAM_IDLE_TIMEOUT`` (default 240s) — seconds with NO bytes
  arriving. The request timeout already bounds each read, so this guard only
  fires when it is the NEARER bound; the request timeout keeps its meaning.
- ``COLLEAGUE_STREAM_MAX_LIFETIME`` (default 900s) — seconds since the stream
  opened, regardless of activity.

``0`` (or anything unparsable) disables a guard; both disabled means
:meth:`StreamGuards.from_env` returns ``None`` and the SSE reader is
byte-identical to the unguarded one. A trip raises :class:`StreamGuardTripped`
— a :class:`colleague.stallguard.TurnStalled` — so it rides the loop's existing
stall path; ``guard`` names which watchdog it was.

Leaf-level like :mod:`colleague.stallguard`: stdlib only, no threads, no
import from the loop, config or any engine.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Iterator, Optional

from colleague.stallguard import TurnStalled

__all__ = ["StreamGuards", "StreamGuardTripped", "guarded_lines", "stall_notice"]

IDLE_ENV = "COLLEAGUE_STREAM_IDLE_TIMEOUT"
LIFETIME_ENV = "COLLEAGUE_STREAM_MAX_LIFETIME"
IDLE_DEFAULT = 240.0
LIFETIME_DEFAULT = 900.0
_KNOB = {"stream-idle": IDLE_ENV, "stream-lifetime": LIFETIME_ENV}


class StreamGuardTripped(TurnStalled):
    """A stream guard's deadline passed; ``guard`` is ``stream-idle`` or ``stream-lifetime``."""

    def __init__(self, seconds: float, bound: float, *, guard: str) -> None:
        super().__init__(seconds, bound)
        self.guard = guard
        self.args = (f"{guard}: stream guard tripped after {seconds:.1f}s (bound {bound:.0f}s)",)


def _read_bound(env: str, default: float) -> Optional[float]:
    """One knob: unset -> *default*; ``0``/negative/unparsable -> disabled (``None``)."""
    raw = os.environ.get(env)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value > 0 else None


@dataclass
class StreamGuards:
    """The armed deadlines of one stream; see the module docstring."""

    idle: Optional[float]
    lifetime: Optional[float]
    started: float
    last_bytes: float
    #: the request timeout (``COLLEAGUE_TIMEOUT``) — a socket read is never
    #: given LONGER than this, only shorter when a guard deadline is nearer.
    base_timeout: Optional[float] = None

    @classmethod
    def from_env(
        cls, now: Optional[float] = None, *, base_timeout: Optional[float] = None
    ) -> Optional["StreamGuards"]:
        idle = _read_bound(IDLE_ENV, IDLE_DEFAULT)
        lifetime = _read_bound(LIFETIME_ENV, LIFETIME_DEFAULT)
        if idle is None and lifetime is None:
            return None
        current = time.monotonic() if now is None else now
        return cls(idle, lifetime, current, current, base_timeout)

    def saw_bytes(self, now: Optional[float] = None) -> None:
        """Bytes arrived: restart the idle clock (the lifetime clock never restarts)."""
        self.last_bytes = time.monotonic() if now is None else now

    def _deadlines(self, now: float) -> list[tuple[float, str, float, float]]:
        out: list[tuple[float, str, float, float]] = []
        if self.idle is not None:
            out.append(
                (self.last_bytes + self.idle, "stream-idle", now - self.last_bytes, self.idle)
            )
        if self.lifetime is not None:
            out.append(
                (self.started + self.lifetime, "stream-lifetime", now - self.started, self.lifetime)
            )
        return out

    def check(self, now: Optional[float] = None) -> None:
        """Raise :class:`StreamGuardTripped` for the first guard whose deadline passed."""
        current = time.monotonic() if now is None else now
        for deadline, guard, elapsed, bound in self._deadlines(current):
            if current > deadline:
                raise StreamGuardTripped(elapsed, bound, guard=guard)

    def wait_for(self, now: Optional[float] = None) -> Optional[float]:
        """Seconds until the nearest deadline (raises first if one already passed)."""
        current = time.monotonic() if now is None else now
        self.check(current)
        deadlines = self._deadlines(current)
        return max(0.0, min(d for d, *_ in deadlines) - current) if deadlines else None


def guarded_lines(response: Any, guards: StreamGuards) -> Iterator[bytes]:
    """Yield *response*'s lines one socket READ at a time, consulting *guards*
    before and after every read.

    Reading per chunk (``read1``) rather than per line is the whole point: a
    drip-feeding server that never sends a newline would block a line iterator
    forever while the guards never got a turn. Each read's socket timeout is
    shortened to the nearer guard deadline (never lengthened past
    ``guards.base_timeout``, so ``COLLEAGUE_TIMEOUT`` keeps its meaning); a timeout that
    lands past a guard deadline is that guard's trip, any other timeout
    re-raises unchanged as the request timeout it always was. A response with
    no ``read1`` (a test double) degrades to the plain line iterator with
    per-line checks; a socket that is already closed (a fully buffered body)
    simply stops being re-timed.
    """
    read1 = getattr(response, "read1", None)
    sock = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
    if read1 is None:
        for raw_line in response:
            guards.saw_bytes()
            guards.check()
            yield raw_line
        return
    buffer = bytearray()
    base = guards.base_timeout
    while True:
        wait = guards.wait_for()
        if sock is not None:
            try:
                sock.settimeout(wait if base is None or wait is None else min(base, wait))
            except OSError:
                sock = None  # closed underneath us: the body is already buffered
        try:
            chunk = read1(8192)
        except TimeoutError:
            guards.check()  # a guard deadline passed -> StreamGuardTripped names it
            raise  # otherwise: the request timeout, unchanged
        except ValueError:
            chunk = b""  # read on a closed file: end of stream
        if not chunk:
            if buffer:
                yield bytes(buffer)
            return
        guards.saw_bytes()
        guards.check()
        buffer.extend(chunk)
        while (newline := buffer.find(b"\n")) >= 0:
            yield bytes(buffer[: newline + 1])
            del buffer[: newline + 1]


def stall_notice(guard: str, seconds: float, bound: float) -> str:
    """The loop's phase notice for a tripped stream guard, naming the knob to raise."""
    return (
        f"{guard}: the stream guard tripped after {seconds:.0f}s (bound {bound:.0f}s) — "
        f"ending the episode with a partial; raise {_KNOB.get(guard, IDLE_ENV)} (0 disables)"
    )
