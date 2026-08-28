"""Batched tool execution for one model turn — the loop-facing orchestration.

adapted-from: qwen-code packages/core/src/core/coreToolScheduler.ts:4208-4293
(``attemptExecutionOfScheduledCalls`` / ``runConcurrently``) and
cli/src/nonInteractiveCli.ts:471-483, 1868-1871 (the headless path reuses the
same predicate and finalises results in ORIGINAL request order).

The loop hands every turn's tool calls to :func:`run_turn_calls`. The calls are
partitioned with :func:`colleague.toolbatch.partition_by_concurrency_safety`:
consecutive concurrency-safe calls (``read_file``, ``list_dir``,
``grep_search``, ``glob``, ``view_media``, a ``memory`` recall, a
``run_command`` the fail-closed read-only checker approves) form one batch;
every other call is a batch of its own and runs exactly as before.

The lifecycle split (spec c35 / honesty h24) — for a parallel batch:

1. **gates on the main thread, request order, BEFORE the pool** —
   :func:`colleague.loop._gate_tool_call` (``pre_tool`` hook → TAE boundary →
   approval policy) decides each call; a deny is remembered, never executed;
2. **only ``executor.execute`` runs in the pool** — the pool target is
   :func:`_execute_item`, a module-level function over
   ``(executor, name, arguments)`` that holds no loop state (the AST guard in
   ``tests/test_toolbatch_loop.py`` pins that neither it nor
   :func:`colleague.loop._execute_tool` references ``ctx`` / ``_Work``);
3. **bookkeeping on the main thread, request order, AFTER the join** — step
   indices, ``Step`` / tool-message appends, ``post_tool`` hooks, progress
   emits and the telemetry span all happen in :func:`colleague.loop._record_denial`
   / :func:`colleague.loop._record_execution`, exactly the helpers the
   sequential path uses, so the two paths cannot drift.

Width ``1`` (``COLLEAGUE_TOOL_CONCURRENCY=1``) — or a batch of one — takes the
sequential ``run_one`` path untouched, which is what makes the width-1 loop
byte-identical to the pre-batch loop (``tests/test_e2e_mock.py`` is the
all-engines pin). Failure semantics (c36 / h25): one call erroring never cancels
its siblings (each result is per-call, ok or error, in request order); a flight
``stop`` written mid-batch takes effect before the NEXT batch — the remaining
calls are recorded as skipped, non-ok steps so the wire stays valid — and
in-flight tools finish or hit their own timeout first (threads cannot be
killed). SIGTERM handling is untouched: the artifact write still lands with
every completed step.

This module imports nothing thread-shaped itself: the ``ThreadPoolExecutor``
lives behind :func:`colleague.toolbatch.run_batch`, the ONE sanctioned pool
(convention change (6), plan adopt-from-qwen-code).
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Sequence

from colleague import flight as _flightmod
from colleague import runcounts, toolbatch

#: Default width of the read-only batch pool (qwen-code's
#: ``QWEN_CODE_MAX_TOOL_CONCURRENCY`` default).
DEFAULT_TOOL_CONCURRENCY = 10
#: The operator knob; ``1`` restores the sequential loop byte-for-byte.
ENV_TOOL_CONCURRENCY = "COLLEAGUE_TOOL_CONCURRENCY"
#: Tool message + step text for calls skipped by a flight stop at a batch boundary.
STOP_SKIPPED = "skipped: flight stop requested before this batch ran"


def concurrency_width() -> int:
    """The batch width from ``COLLEAGUE_TOOL_CONCURRENCY``; unset/invalid → 10, <1 → 1."""
    raw = os.environ.get(ENV_TOOL_CONCURRENCY, "")
    try:
        width = int(raw)
    except ValueError:
        return DEFAULT_TOOL_CONCURRENCY
    return max(1, width)


def is_batch_safe(call: Any) -> bool:
    """The partition predicate over a loop ``ToolCall`` (name + arguments)."""
    return toolbatch.is_tool_call_concurrency_safe(call.name, call.arguments)


def stop_requested(ctx: Any) -> bool:
    """Peek the flight control file's ``stop`` flag WITHOUT consuming guidance.

    :meth:`colleague.flight.FlightSession.read_control` advances the guidance
    cursor, and guidance is only ever injected at the TURN boundary (a user turn
    between tool replies would break the wire), so a mid-turn check must read
    the raw file. Strict ``False`` when the run is not a watchable flight.
    """
    session = getattr(ctx, "flight", None)
    if session is None:
        return False
    path = _flightmod.control_path(session.repo_path, session.task_id)
    try:
        return bool(json.loads(path.read_text()).get("stop", False))
    except (OSError, ValueError):
        return False


@dataclass
class _Prepared:
    """One gated call: the main-thread verdict, then the pool's outcome."""

    call: Any
    arguments: Any
    reason: str | None
    hook_denied: bool
    outcome: Any = None
    exc: Any = None
    seconds: float = 0.0


def _execute_item(item: tuple[Any, str, Any]) -> tuple[Any, Any, float]:
    """The pool target: ``(executor, name, arguments)`` → ``(outcome, exc, seconds)``.

    Holds no loop state on purpose — see the module docstring (c35/h24).
    """
    from colleague import loop as _loop  # lazy: loop imports this module

    executor, name, arguments = item
    started = time.monotonic()
    outcome, exc = _loop._execute_tool(executor, name, arguments)
    return outcome, exc, time.monotonic() - started


def run_turn_calls(ctx: Any, calls: Sequence[Any], run_one: Callable[[Any, Any], bool]) -> bool:
    """Run one turn's tool calls as ordered batches; return whether any finished.

    ``run_one`` is the loop's sequential per-call path (``_run_tool_call``); it is
    used verbatim for every single-call batch and whenever the width is 1.
    """
    width = concurrency_width()
    batches = toolbatch.partition_by_concurrency_safety(list(calls), is_batch_safe)
    finished = False
    for index, batch in enumerate(batches):
        if index and stop_requested(ctx):
            _skip_remaining(ctx, [call for rest in batches[index:] for call in rest])
            break
        if width <= 1 or len(batch) <= 1:
            for call in batch:
                if run_one(ctx, call):
                    finished = True
        elif _run_parallel_batch(ctx, batch, width):
            finished = True
    return finished


def _run_parallel_batch(ctx: Any, batch: Sequence[Any], width: int) -> bool:
    """Gate (main) → execute (pool) → record (main, request order) one safe batch."""
    from colleague import loop as _loop  # lazy: loop imports this module

    prepared: list[_Prepared] = []
    for call in batch:  # phase 1 — every gate on the main thread, request order
        arguments, reason, hook_denied = _loop._gate_tool_call(ctx, call)
        prepared.append(_Prepared(call, arguments, reason, hook_denied))
    # A pre_tool REWRITE can turn a read-only call into a mutating one after the
    # partition (Qodo #441-13): re-check safety on the GATED arguments — a call
    # that is no longer batch-safe is demoted and runs alone after the pool.
    allowed = [item for item in prepared if item.reason is None]
    runnable = [
        p for p in allowed if toolbatch.is_tool_call_concurrency_safe(p.call.name, p.arguments)
    ]
    demoted = [p for p in allowed if p not in runnable]
    results = toolbatch.run_batch(  # phase 2 — only execute() in the pool
        _execute_item, [(ctx.executor, p.call.name, p.arguments) for p in runnable], width
    )
    for item, (outcome, exc, seconds) in zip(runnable, results):
        item.outcome, item.exc, item.seconds = outcome, exc, seconds
    for item in demoted:  # sequential, request order, never in the pool
        item.outcome, item.exc, item.seconds = _execute_item(
            (ctx.executor, item.call.name, item.arguments)
        )
    runcounts.bump(ctx.result, "batches_run")  # t20: exact scoreboard
    runcounts.bump(ctx.result, "calls_parallelised", len(runnable))
    finished = False
    for item in prepared:  # phase 3 — bookkeeping on the main thread, request order
        step_index = len(ctx.result.steps)
        with ctx.telemetry.tool_span(tool=item.call.name, step_index=step_index) as span:
            if item.reason is not None:
                _loop._record_denial(
                    ctx, item.call, item.arguments, span, step_index, item.reason, item.hook_denied
                )
                continue
            span.set(batched=item in runnable, exec_seconds=item.seconds)
            if _loop._record_execution(
                ctx, item.call, item.arguments, span, step_index, item.outcome, item.exc
            ):
                finished = True
    return finished


def _skip_remaining(ctx: Any, calls: Sequence[Any]) -> None:
    """Record every not-yet-run call as a skipped, non-ok step so the wire stays valid."""
    from colleague import loop as _loop  # lazy: loop imports this module

    for call in calls:
        step_index = len(ctx.result.steps)
        with ctx.telemetry.tool_span(tool=call.name, step_index=step_index) as span:
            _loop._record_denial(ctx, call, call.arguments, span, step_index, STOP_SKIPPED, False)
