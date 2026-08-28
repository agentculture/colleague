"""Batched tool execution for one model turn — the loop-facing orchestration.

adapted-from: qwen-code packages/core/src/core/coreToolScheduler.ts:4208-4293
(``attemptExecutionOfScheduledCalls`` / ``runConcurrently``) and
cli/src/nonInteractiveCli.ts:471-483, 1868-1871 (the headless path reuses the
same predicate and finalises results in ORIGINAL request order).

The loop hands every turn's tool calls to :func:`run_turn_calls`. The calls are
partitioned with :func:`colleague.toolbatch.partition_by_concurrency_safety`:
consecutive concurrency-safe calls (``read_file``, ``list_dir``,
``grep_search``, ``glob``, ``view_media``, ``web``, a ``memory`` recall, a
``run_command`` the fail-closed read-only checker approves) form one batch;
every other call is a batch of its own and runs exactly as before. A ``web``
``page *`` call is additionally throttled by :func:`_run_web_capped`
(``COLLEAGUE_WEB_CONCURRENCY``, default 3) — a MAIN-thread partition of the
batch into sequential waves of at most that many ``page *`` calls each
(t18 — Qodo #4/#8: the prior worker-side ``threading.Semaphore`` is gone; no
new thread primitive is added). The web-call budget (``colleague/webbudget.py``)
is likewise checked-and-incremented on the main thread, in request order,
BEFORE a ``web`` item is submitted — never inside the pool.

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
from colleague import runcounts, toolbatch, webbudget

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
    """Gate (main) → web budget (main) → execute (pool, web-capped waves) →
    record (main, request order) one safe batch."""
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
    submitted = _apply_web_budget(ctx.executor, runnable)  # phase 1.5 — main thread, request order
    results = (
        _run_web_capped(  # phase 2 — only execute() in the pool, web waves ≤ web_concurrency()
            [(ctx.executor, p.call.name, p.arguments) for p in submitted], width
        )
    )
    for item, (outcome, exc, seconds) in zip(submitted, results):
        item.outcome, item.exc, item.seconds = outcome, exc, seconds
    for item in demoted:  # sequential, request order, never in the pool
        item.outcome, item.exc, item.seconds = _execute_item(
            (ctx.executor, item.call.name, item.arguments)
        )
    _record_web_failures(ctx.executor, submitted)  # main thread, after the join
    runcounts.bump(ctx.result, "batches_run")  # t20: exact scoreboard
    runcounts.bump(ctx.result, "calls_parallelised", len(submitted))
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


def _apply_web_budget(executor: Any, runnable: list[_Prepared]) -> list[_Prepared]:
    """Check-and-increment the web budget for every ``web`` item in *runnable*,
    on the MAIN thread, in request order, BEFORE anything is submitted to the
    pool (t18 — Qodo #4/#8: the prior worker-side check-then-increment raced).
    A refused item (cap already hit) is never submitted — its outcome becomes
    the cap :class:`~colleague.tools.ToolError`, exactly as if ``execute()``
    itself had raised it. Every item that IS submitted has its arguments
    stamped with the private ``_budget_counted: True`` key so
    ``web_schemas.dispatch`` skips its own (worker-thread) counting.

    Returns the items that are still to be submitted, in the same order.
    """
    from colleague.tools import ToolError  # local: avoids the import cycle

    submitted: list[_Prepared] = []
    for item in runnable:
        if item.call.name != "web":
            submitted.append(item)
            continue
        try:
            webbudget.check_and_increment(executor)
        except ToolError as exc:
            item.outcome, item.exc, item.seconds = None, exc, 0.0
            continue
        item.arguments = {**item.arguments, "_budget_counted": True}
        submitted.append(item)
    return submitted


def _web_capped_waves(items: Sequence[tuple[Any, str, Any]], cap: int) -> list[list[tuple]]:
    """Partition ``(executor, name, arguments)`` items into consecutive waves
    holding at most ``cap`` ``web`` ``page *`` items each; a non-page item
    (including ``search``) rides along in whichever wave it lands in, never
    forcing a split and never itself counted against ``cap``."""
    waves: list[list[tuple]] = []
    page_count = 0
    for item in items:
        _, name, arguments = item
        is_page = toolbatch.is_web_page_verb(name, arguments)
        if not waves or (is_page and page_count >= cap):
            waves.append([])
            page_count = 0
        waves[-1].append(item)
        if is_page:
            page_count += 1
    return waves


def _run_web_capped(items: Sequence[tuple[Any, str, Any]], width: int) -> list[tuple]:
    """Run *items* through :func:`colleague.toolbatch.run_batch`, but split
    into SEQUENTIAL waves so no more than ``web_concurrency()`` ``web``
    ``page *`` calls are ever in flight at once (t18 — the cap moved off a
    worker-side semaphore onto this main-thread partition). Each wave still
    runs its own members concurrently up to ``width``; only the ``page *``
    population per wave is capped."""
    results: list[tuple] = []
    for wave in _web_capped_waves(items, toolbatch.web_concurrency()):
        results.extend(toolbatch.run_batch(_execute_item, wave, width))
    return results


def _record_web_failures(executor: Any, submitted: list[_Prepared]) -> None:
    """After the join, on the main thread: count a submitted ``web`` item as
    failed when its rendered result does not carry ``lifecycle_state:
    succeeded`` — parsed from the already-rendered text, never re-fetched."""
    for item in submitted:
        if item.call.name != "web":
            continue
        text = item.outcome.result if item.outcome is not None else ""
        if "lifecycle_state: succeeded" not in (text or ""):
            webbudget.record_result(executor, None)


def _skip_remaining(ctx: Any, calls: Sequence[Any]) -> None:
    """Record every not-yet-run call as a skipped, non-ok step so the wire stays valid."""
    from colleague import loop as _loop  # lazy: loop imports this module

    for call in calls:
        step_index = len(ctx.result.steps)
        with ctx.telemetry.tool_span(tool=call.name, step_index=step_index) as span:
            _loop._record_denial(ctx, call, call.arguments, span, step_index, STOP_SKIPPED, False)
