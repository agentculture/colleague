"""Stream guards — idle + lifetime watchdogs over ONE streamed turn (c12/h10).

adapted-from: qwen-code packages/core/src/core/openaiContentGenerator/
constants.ts:1-68 (``DEFAULT_STREAM_IDLE_TIMEOUT_MS`` / ``DEFAULT_STREAM_MAX_LIFETIME_MS``)
and pipeline.ts:412-530 (``withStreamGuards``) — Copyright 2026 Qwen Team,
Apache-2.0. Re-implemented as stdlib Python (adopt-from-qwen-code arc).

``COLLEAGUE_TIMEOUT`` bounds every socket operation; it never bounded a stream
that keeps *dripping* — a byte at a time, never a newline — which resets any
idle watchdog forever (qwen-code issue #8597 burned hours that way). Two
independent guards close that:

- ``COLLEAGUE_STREAM_IDLE_TIMEOUT`` (default 240s) — seconds with NO non-comment
  payload BYTES arriving (a newline is not the unit of progress: a long line
  still streaming — an SSE frame, or a blocking JSON body — restarts the clock
  as its bytes land). SSE comment lines (a ``:`` prefix — vLLM/OpenAI use
  these for keepalives) do NOT restart the idle clock: a gateway relaying
  keepalives over a dead upstream must not look alive (#438 guidance 4). The
  request timeout already bounds each read, so this guard only fires when it is
  the NEARER bound; the request timeout keeps its meaning.
- ``COLLEAGUE_STREAM_MAX_LIFETIME`` (default 1800s) — seconds since the stream
  opened, regardless of activity.

``0``, a negative, a non-finite (``inf``/``nan``), or an unparsable value
disables a guard; both disabled means
:meth:`StreamGuards.from_env` returns ``None`` and the SSE reader is
byte-identical to the unguarded one. A trip raises :class:`StreamGuardTripped`
— a :class:`colleague.stallguard.TurnStalled` — so it rides the loop's existing
stall path; ``guard`` names which watchdog it was.

Leaf-level like :mod:`colleague.stallguard`: stdlib only, no threads, no
import from the loop, config or any engine.
"""

from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterator, Optional

from colleague.stallguard import TurnStalled

__all__ = ["StreamGuards", "StreamGuardTripped", "guarded_lines", "stall_notice"]

IDLE_ENV = "COLLEAGUE_STREAM_IDLE_TIMEOUT"
LIFETIME_ENV = "COLLEAGUE_STREAM_MAX_LIFETIME"
IDLE_DEFAULT = 240.0
LIFETIME_DEFAULT = 1800.0
_KNOB = {"stream-idle": IDLE_ENV, "stream-lifetime": LIFETIME_ENV}


class StreamGuardTripped(TurnStalled):
    """A stream guard's deadline passed; ``guard`` is ``stream-idle`` or ``stream-lifetime``."""

    def __init__(self, seconds: float, bound: float, *, guard: str) -> None:
        super().__init__(seconds, bound)
        self.guard = guard
        self.args = (f"{guard}: stream guard tripped after {seconds:.1f}s (bound {bound:.0f}s)",)


def _read_bound(env: str, default: float) -> Optional[float]:
    """One knob: unset -> *default*; only a FINITE positive float arms a guard.

    ``0``/negative/unparseable -> disabled (``None``), and so do ``inf``/``nan``
    (``float("inf")`` parses and passes ``> 0`` but is not a valid
    ``socket.settimeout`` argument — an infinite bound would arm a guard that
    can never trip, and ``nan`` poisons every comparison).
    """
    raw = os.environ.get(env)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return None
    if not math.isfinite(value) or value <= 0:
        return None
    return value


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
        """Non-comment payload bytes arrived (a whole line, or the decidably
        non-comment part of one still streaming): restart the idle clock (the
        lifetime clock never restarts). SSE comment lines (keepalives) do NOT call this —
        a gateway relaying keepalives over a dead upstream must not look alive
        (#438 guidance 4)."""
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


def _guarded_line_fallback(response: Any, guards: StreamGuards) -> Iterator[bytes]:
    """Per-line guard checks for a response with no ``read1`` (a test
    double) — the degrade path ``guarded_lines`` falls back to."""
    for raw_line in response:
        if not _is_comment_line(raw_line):
            guards.saw_bytes()
        guards.check()
        yield raw_line


def _retime_socket(sock: Any, wait: Optional[float], base: Optional[float]) -> Any:
    """Shorten *sock*'s timeout to the nearer of *wait*/*base* (never
    lengthened past *base*, so ``COLLEAGUE_TIMEOUT`` keeps its meaning);
    return ``None`` if the socket is already closed underneath us (a fully
    buffered body), so the caller stops re-timing it."""
    try:
        sock.settimeout(wait if base is None or wait is None else min(base, wait))
        return sock
    except OSError:
        return None  # closed underneath us: the body is already buffered


def _read_next_chunk(read1: Callable[[int], bytes], guards: StreamGuards) -> bytes:
    """Read one chunk via *read1*, converting a timeout into whichever guard
    tripped it. A timeout landing past a guard deadline becomes that guard's
    :class:`StreamGuardTripped`; any other timeout re-raises unchanged as the
    request timeout it always was. A read on an already-closed file returns
    ``b""`` (end of stream)."""
    try:
        return read1(8192)
    except TimeoutError:
        guards.check()  # a guard deadline passed -> StreamGuardTripped names it
        raise  # otherwise: the request timeout, unchanged
    except ValueError:
        return b""  # read on a closed file: end of stream


def _drain_complete_lines(buffer: bytearray) -> Iterator[bytes]:
    """Yield and remove every complete (newline-terminated) line at the
    front of *buffer*, leaving any trailing partial line in place."""
    while (newline := buffer.find(b"\n")) >= 0:
        yield bytes(buffer[: newline + 1])
        del buffer[: newline + 1]


def _is_comment_line(line: bytes) -> bool:
    """True for an SSE comment line (a ``:`` prefix after any leading
    whitespace) — the keepalives vLLM/OpenAI gateways relay. A comment line
    carries no payload, so it must NOT restart the idle clock (#438 guidance 4)."""
    return line.lstrip().startswith(b":")


def _partial_is_payload(partial: bytes) -> bool:
    """True once the INCOMPLETE trailing line in the buffer has arrived far
    enough to be decidably NOT an SSE comment.

    Waiting for a newline before restarting the idle clock is wrong: a long
    payload line with no newline yet — a blocking JSON body read through
    :func:`guarded_lines`, or an SSE frame streamed continuously — makes real
    progress while the idle deadline elapses, and ``stream-idle`` trips on a
    healthy transfer. One byte decides it: after stripping leading whitespace,
    a ``:`` means comment (still no refresh, #438 guidance 4), anything else
    means payload. An all-whitespace-so-far partial is still UNDECIDED and
    refreshes nothing — the next byte settles it.
    """
    head = partial.lstrip()
    return bool(head) and not head.startswith(b":")


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

    The per-chunk deadline/idle bookkeeping (socket re-timing, the guarded
    read itself, draining complete lines out of the buffer) is each factored
    into its own helper purely to keep this function's own cognitive
    complexity low (SonarCloud python:S3776); the read1-chunking semantics
    are unchanged from the single-function form.
    """
    read1 = getattr(response, "read1", None)
    sock = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
    if read1 is None:
        yield from _guarded_line_fallback(response, guards)
        return
    buffer = bytearray()
    base = guards.base_timeout
    while True:
        wait = guards.wait_for()
        if sock is not None:
            sock = _retime_socket(sock, wait, base)
        chunk = _read_next_chunk(read1, guards)
        if not chunk:
            if buffer:
                yield bytes(buffer)
            return
        buffer.extend(chunk)
        for line in _drain_complete_lines(buffer):
            if not _is_comment_line(line):
                guards.saw_bytes()
            guards.check()
            yield line
        # The bytes this chunk left in the INCOMPLETE trailing line count too,
        # the moment that line is decidably non-comment: a newline is not the
        # unit of progress. (A non-empty trailing line always ends with a byte
        # from this chunk, so no stale partial can keep refreshing the clock.)
        if _partial_is_payload(bytes(buffer)):
            guards.saw_bytes()
        guards.check()  # every chunk gets a turn, not only a completed line


def stall_notice(guard: str, seconds: float, bound: float) -> str:
    """The loop's phase notice for a tripped stream guard, naming the knob to raise."""
    return (
        f"{guard}: the stream guard tripped after {seconds:.0f}s (bound {bound:.0f}s) — "
        f"ending the episode with a partial; raise {_KNOB.get(guard, IDLE_ENV)} (0 disables)"
    )
