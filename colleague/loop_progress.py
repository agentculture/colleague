"""The loop's two observer emitters: the per-step progress sink and phase notices.

Extracted from ``colleague/loop.py`` (plan hard-1000-line-file-limit, t15).
A phase notice never advances ``step_count`` — that invariant lives in
:func:`_emit_phase` and moved with it. A pure move.

In-flight liveness on the streaming path (#479 t10)
-----------------------------------------------------
Before this, a heartbeat only fired at PHASE NOTICES (turn boundaries,
compaction, stalls) — so a single long completion, which emits no per-step
progress and no phase notice while it is generating, was silent by
construction: an operator watching the flight feed could not tell "thinking
hard" from "wedged". :func:`delta_heartbeat` closes that gap by PIGGYBACKING
on delta arrival: a caller that streams a completion (i.e. one that already
calls ``EngineConfig.on_delta`` per received chunk — see
``colleague/config.py``'s ``on_delta`` field) can wire the callable
:func:`delta_heartbeat` returns as that seam, and every arriving chunk gets a
chance to emit a throttled heartbeat via the SAME :func:`_emit_phase` this
module already uses for phase notices — so it inherits every one of that
function's invariants for free: a missing ``ctx.flight``/``ctx.progress`` is a
no-op, a raising sink is suppressed, and NO heartbeat record — piggybacked or
not — ever advances ``step_count`` (``_emit_phase`` never touches it).

Deliberately NO TIMER THREAD: the throttle is a plain monotonic-clock
comparison evaluated only when a delta actually arrives, so there is nothing
running in the background between deltas. This repo confines threads to an
explicit allow-list (``tests/test_boundary.py``); a delta-driven, thread-free
throttle was the only shape consistent with that. The cost is honest: a turn
that goes fully quiet for a stretch — no chunks at all — gets no heartbeat
either, exactly like today; the streamed answer resuming is what produces the
next one, not a clock ticking on its own.

The BLOCKING (non-streaming) path gets NO in-flight liveness from this
module, and cannot: there is no delta to piggyback on when a completion is
requested and read back as one already-finished response. This is a hole, not
a nuance — say so plainly rather than implying coverage that does not exist.
The stream guards themselves (``colleague/streamguards.py``) are unrelated and
untouched: ``IDLE_DEFAULT``/``LIFETIME_DEFAULT`` already tolerate a
byte-producing long turn correctly (the idle clock restarts on payload
bytes), so nothing about their bounds needed — or got — changed here.
"""

from __future__ import annotations

import os
import time
from contextlib import suppress
from typing import Any, Callable

from colleague.loop_types import _Work
from colleague.tui.from_work import progress_target as _progress_target


def _emit_progress(ctx: _Work, step_index: int, tool: str, arguments: Any, ok: bool) -> None:
    """Fire the per-step progress sink, if one is wired (#38). No-op otherwise.

    A progress sink is observability, never control: a raising sink must never
    abort the work item, so its failure is suppressed (the same fail-safe as hooks
    and neighbour clones).
    """
    if ctx.progress is None:
        return
    with suppress(Exception):
        ctx.progress(step_index, tool, _progress_target(arguments), ok)


def _emit_phase(ctx: _Work, detail: str) -> None:
    """Announce, through the progress sink, that a model completion is in flight (#206).

    A long single turn — above all the final no-tools synthesis turn — emits no
    per-step progress, so on a slow backend it is indistinguishable from a stall.
    Fire a phase notice via the SAME progress sink (#38), encoded with an EMPTY tool
    name so a sink renders it as a standalone line, never a step (the CLI sinks
    special-case the empty tool). Observability is never control: a missing sink is a
    no-op and a raising sink is suppressed, exactly like :func:`_emit_progress`. The
    step index carries the LIVE step count — ``len(result.steps)``, the same
    expression the per-step counter uses (#206 review: ``stats.step_count`` is only
    populated at loop exit by ``_finalize_stats``, so it would report a stale 0
    mid-run) — but the empty tool is the signal that this is a phase, not a step.
    """
    step_index = len(ctx.result.steps)  # live count; stats.step_count is 0 until finalize
    # #308: fold the phase notice onto the FLIGHT FEED too (not just the stderr /
    # cockpit sinks), so `colleague talk` / senses grounding / `flight status` have
    # a liveness signal during a long completion instead of an empty feed. A
    # ``type="heartbeat"`` record — it NEVER advances step_count and is filtered out
    # of the step-only tui replay/snapshot (a different sink). Strict no-op when not
    # a watchable flight; suppressed like every observability write.
    if ctx.flight is not None:
        started = ctx._flight_started_monotonic
        elapsed = (time.monotonic() - started[0]) if started else 0.0
        with suppress(Exception):
            ctx.flight.append_heartbeat(
                phase=detail, elapsed=elapsed, step_index=step_index, max_steps=ctx.max_steps
            )
    if ctx.progress is None:
        return
    with suppress(Exception):
        ctx.progress(step_index, "", detail, True)


# ---------------------------------------------------------------------------
# In-flight liveness on the streaming path (#479 t10) — see the module
# docstring for the full picture: this piggybacks a throttled heartbeat onto
# per-delta arrival, with no timer thread, entirely by reusing _emit_phase.
# ---------------------------------------------------------------------------

#: Operator knob: minimum wall-clock seconds between two piggybacked
#: heartbeats for ONE streamed completion. Unset/unparsable/non-positive ->
#: the default — a heartbeat with no floor at all would fire once per delta
#: on a fast stream, which is exactly the "distinguishable from noise"
#: problem a throttle exists to prevent, so a bad value degrades to the
#: default rather than to "no throttle".
DELTA_HEARTBEAT_ENV = "COLLEAGUE_DELTA_HEARTBEAT_INTERVAL"
DELTA_HEARTBEAT_DEFAULT = 3.0

#: The phase text a piggybacked heartbeat carries by default — distinct from
#: ``_PHASE_THINKING`` (fired once, before the completion starts) so a reader
#: of the flight feed can tell "the turn began" from "the turn is still
#: producing bytes" apart.
_PHASE_STREAMING = "receiving the model's answer — bytes are still arriving, this is not a stall…"


def _delta_heartbeat_interval() -> float:
    """The throttle floor in seconds; see :data:`DELTA_HEARTBEAT_ENV`."""
    raw = os.environ.get(DELTA_HEARTBEAT_ENV)
    if raw is None:
        return DELTA_HEARTBEAT_DEFAULT
    try:
        value = float(raw)
    except ValueError:
        return DELTA_HEARTBEAT_DEFAULT
    return value if value > 0 else DELTA_HEARTBEAT_DEFAULT


def delta_heartbeat(ctx: _Work, phase: str = _PHASE_STREAMING) -> Callable[[str], None]:
    """Return a throttled, ``EngineConfig.on_delta``-shaped liveness callback.

    Piggybacks on delta arrival instead of a timer thread: the returned
    callable does nothing on its own between calls — it is driven entirely by
    whichever caller invokes it once per streamed chunk (the same seam a
    cockpit sink arms today, ``colleague/config.py``'s ``on_delta`` field).
    Each call compares the wall clock against the last emission and only
    fires :func:`_emit_phase` — unchanged, so every one of its invariants
    (missing/raising sink is a no-op, ``step_count`` never advances) applies
    here too — once :func:`_delta_heartbeat_interval` seconds have actually
    elapsed; a burst of deltas inside that window is silently absorbed. An
    empty chunk (``""`` — some transports emit one as a sentinel) never counts
    as arrival and is ignored before the clock is even read.

    The throttle state (``last_emit``) lives in this closure, per call to
    :func:`delta_heartbeat` — nothing is stored on *ctx* itself, so two
    concurrent streamed completions built from two separate calls throttle
    independently.
    """
    last_emit: list[float] = []

    def _on_delta(chunk: str) -> None:
        if not chunk:
            return
        now = time.monotonic()
        if last_emit and (now - last_emit[0]) < _delta_heartbeat_interval():
            return
        last_emit[:] = [now]
        _emit_phase(ctx, phase)

    return _on_delta
