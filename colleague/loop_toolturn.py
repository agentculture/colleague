"""The per-tool-call turn chain: gate, deny, execute, record.

Extracted from ``colleague/loop.py`` (plan hard-1000-line-file-limit, t19). This
is the pipeline :func:`_run_tool_call` drives for every model-requested tool
call — ``pre_tool`` hook / TAE boundary / approval policy gate
(:func:`_gate_tool_call`), a refusal's bookkeeping (:func:`_record_denial`), the
``post_tool`` hook binding (:func:`_fire_post_tool`), and a completed attempt's
bookkeeping (:func:`_record_execution`). It is also the sequential per-call path
the read-only tool-batch pool (``colleague/toolbatch_loop.py``) reuses verbatim
for its own bookkeeping phase (``_loop._record_denial`` / ``_loop._record_execution``)
and gate phase (``_loop._gate_tool_call``).

``colleague/loop.py`` stays the top of the import DAG, so this module never
imports it back. The one thing here that would otherwise need to reach into
``colleague.loop`` — firing the ``pre_tool``/``post_tool`` hooks via
``colleague.loop._fire_hooks`` (the binding that keeps ``colleague.loop.run_hook``
the single overridable seam) — is threaded in as the ``fire_hooks`` parameter
instead, exactly the same injection pattern ``colleague/loop_gates.py`` uses for
its ``work_loop`` re-entry point. ``colleague/loop.py`` and
``colleague/toolbatch_loop.py`` both pass their own ``_fire_hooks`` at the call
site; a pure move otherwise.
"""

from __future__ import annotations

from typing import Any, Callable

from colleague.contract import DECISION_DENY, DECISION_REWRITE, Step
from colleague.loop_outcomes import _apply_finish
from colleague.loop_progress import _emit_progress
from colleague.loop_tae import _tae_close, _tae_verdict
from colleague.loop_toolexec import _execute_tool, _policy_verdict, _track_unknown_tool
from colleague.loop_types import _Work
from colleague.loop_wire import ToolCall, _tool_message
from colleague.tools import ToolError

#: Signature of the loop's ``_fire_hooks`` binding, threaded in by the caller
#: rather than imported (this module never imports ``colleague.loop``).
FireHooksFn = Callable[..., Any]


def _gate_tool_call(
    ctx: _Work, call: ToolCall, *, fire_hooks: FireHooksFn
) -> tuple[Any, str | None, bool]:
    """The three gates, decision only: ``(arguments, deny_reason, hook_denied)``.

    ``pre_tool`` hook (the only control-bearing event — first deny/rewrite wins, a
    rewrite swaps the arguments) → the thought→action→evaluation boundary (t13:
    the HOST classifies a consequential action; alignment is never permission) →
    the operator's approval policy AFTER hooks so a rewrite is still gated. Every
    gate runs on the MAIN thread in request order BEFORE any execution — the
    batch path (:mod:`colleague.toolbatch_loop`) relies on that.
    """
    arguments = call.arguments
    decision = fire_hooks(
        ctx.hooks,
        ctx.result,
        event="pre_tool",
        task=ctx.task,
        tool=call.name,
        arguments=arguments,
        policy=ctx.policy,
    )
    kind = decision.decision if decision is not None else None
    if kind == DECISION_DENY:
        return arguments, (decision and decision.reason) or "denied by a pre_tool hook", True
    if kind == DECISION_REWRITE and decision is not None and decision.arguments is not None:
        arguments = decision.arguments
    gated = ToolCall(call.id, call.name, arguments)
    reason = _tae_verdict(ctx, gated)
    if reason is None:
        reason = _policy_verdict(ctx, gated)
    return arguments, reason, False


def _record_denial(
    ctx: _Work, call: ToolCall, arguments: Any, span: Any, step_index: int, reason: str, hook: bool
) -> None:
    """Record a refused call — span, (hook-denial metric,) non-ok Step, tool message, progress."""
    span.set(ok=False, denied=True, reason=reason)
    if hook:
        ctx.telemetry.on_hook_denial()
    ctx.result.steps.append(Step(step_index, call.name, arguments, reason, ok=False))
    ctx.messages.append(_tool_message(call.id, reason))
    _emit_progress(ctx, step_index, call.name, arguments, ok=False)


def _fire_post_tool(ctx: _Work, tool: str, arguments: Any, *, fire_hooks: FireHooksFn) -> None:
    """``post_tool`` fires after every tool *attempt*; observe-only this increment."""
    fire_hooks(
        ctx.hooks,
        ctx.result,
        event="post_tool",
        task=ctx.task,
        tool=tool,
        arguments=arguments,
        policy=ctx.policy,
    )


def _record_execution(
    ctx: _Work,
    call: ToolCall,
    arguments: Any,
    span: Any,
    step_index: int,
    outcome: Any,
    exc: Any,
    *,
    fire_hooks: FireHooksFn,
) -> bool:
    """Bookkeeping after ONE execute attempt (sequential AND batch paths); True on finish."""
    if exc is not None:
        msg = (
            str(exc)
            if isinstance(exc, ToolError)
            else f"bad tool arguments: {type(exc).__name__}: {exc}"
        )
        _track_unknown_tool(ctx, call.name, exc)
        _tae_close(ctx, call.name, False)
        span.set(ok=False, error=msg)
        ctx.result.steps.append(Step(step_index, call.name, arguments, f"error: {msg}", ok=False))
        ctx.messages.append(_tool_message(call.id, f"error: {msg}"))
        _emit_progress(ctx, step_index, call.name, arguments, ok=False)
        _fire_post_tool(ctx, call.name, arguments, fire_hooks=fire_hooks)
        return False
    _track_unknown_tool(ctx, call.name, None)
    _tae_close(ctx, call.name, True)
    span.set(ok=True, bytes=len(outcome.result), changed_file=outcome.changed_file)
    ctx.result.steps.append(Step(step_index, call.name, arguments, outcome.result, ok=True))
    # Keep the executor's live step counter in step with the trace (Qodo #469/4):
    # a hire minted by a handler reads ``created_step`` off it. Guarded — a
    # loop driven without an executor (phase-notice doubles) has none.
    if ctx.executor is not None:
        ctx.executor.step_count = len(ctx.result.steps)
    ctx.messages.append(_tool_message(call.id, outcome.result))
    if outcome.media_part is not None:
        # view_media fold (t5): the tool message stays a plain string (wire-safe);
        # the image rides a follow-up user parts message the next turn sees.
        ctx.messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": f"[{call.name}] {outcome.result}"},
                    outcome.media_part,
                ],
            }
        )
    _emit_progress(ctx, step_index, call.name, arguments, ok=True)
    _fire_post_tool(ctx, call.name, arguments, fire_hooks=fire_hooks)
    if not outcome.finished:
        return False
    span.set(finished=True)
    _apply_finish(ctx.result, outcome)
    return True


def _run_tool_call(ctx: _Work, call: ToolCall, *, fire_hooks: FireHooksFn) -> bool:
    """Run one tool call inside its own telemetry span; return whether it finished.

    gate → execute → record, inside ONE ``with tool_span`` block so exactly one
    step/tool-call metric is recorded per call — deny and error paths included.
    """
    step_index = len(ctx.result.steps)
    with ctx.telemetry.tool_span(tool=call.name, step_index=step_index) as span:
        arguments, reason, hook_denied = _gate_tool_call(ctx, call, fire_hooks=fire_hooks)
        if reason is not None:
            _record_denial(ctx, call, arguments, span, step_index, reason, hook_denied)
            return False
        outcome, exc = _execute_tool(ctx.executor, call.name, arguments)
        return _record_execution(
            ctx, call, arguments, span, step_index, outcome, exc, fire_hooks=fire_hooks
        )
