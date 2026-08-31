"""The loop's two observer emitters: the per-step progress sink and phase notices.

Extracted from ``colleague/loop.py`` (plan hard-1000-line-file-limit, t15).
A phase notice never advances ``step_count`` — that invariant lives in
:func:`_emit_phase` and moved with it. A pure move.
"""

from __future__ import annotations

import time
from contextlib import suppress
from typing import Any

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
