"""The bounded agentic tool-loop (R3).

The loop is engine-agnostic: it is handed a ``complete`` callable that performs
*one* model turn (given the running message list, return the assistant's reply
and any tool calls) and drives it in a loop — executing each requested tool
against the repo via :class:`~colleague.tools.ToolExecutor`, feeding results
back, until the model calls ``finish`` (or stops requesting tools) or the
``max_steps`` budget is reached.

Termination is guaranteed (honesty condition h3): every path out of the loop is
either a model-signalled finish, an empty tool-call turn, or the step budget.
The mock engine supplies a scripted ``complete``; the vLLM engine supplies one
that POSTs to an OpenAI-compatible endpoint. The loop never knows the difference.

Hook lifecycle (R4). The loop fires repo-shipped hooks at four lifecycle events
— ``task_start`` (once, before the loop), ``pre_tool`` (before each tool
executes), ``post_tool`` (after a tool executes), and ``finish`` (once, on any
loop exit). The config is loaded by default from ``task.repo_path`` via
:func:`colleague.hooks.load_hooks`, so *every* engine inherits the lifecycle
for free — engines call :func:`run` unchanged (the all-engines rule). With no
hooks config nothing fires and behavior is byte-identical to a hook-free loop.

Only ``pre_tool`` is control-bearing: the first decisive decision wins — ``deny``
skips the tool (the reason is fed back to the model as the tool result) and
``rewrite`` swaps the call's arguments before execution. ``task_start`` /
``post_tool`` / ``finish`` are observe-only this increment (they run side-effects
and are recorded, but never alter control flow). Every firing is appended to
``TaskResult.hook_firings`` in order. Termination is unaffected: hooks add no new
exit path and cannot extend the step budget.

Module layout (plan hard-1000-line-file-limit, t15). The lanes live in
``colleague/loop_*.py`` siblings — ``loop_types`` (the ``_Work`` /
``ContextControls`` leaf), ``loop_wire``, ``loop_constants``, ``loop_progress``,
``loop_toolexec``, ``loop_accounting``, ``loop_hooks``, ``loop_tae``,
``loop_context``, ``loop_transport``, ``loop_turn``, ``loop_flight``,
``loop_memory``, ``loop_outcomes``, ``loop_synthesis``, ``loop_senses``,
``loop_setup``, ``loop_gatebase``, ``loop_gates``, ``loop_testgates`` and
``loop_run_stages``. NO sibling imports ``colleague.loop``: this module is the
top of the import DAG, which is why the gate lanes take their ``work_loop``
re-entry point as a parameter. What stays here is what must: :func:`run`, the
turn loop, the tool-call chain around the ``pre_tool``/``post_tool`` hook
bindings, and the ONE flight-guidance injection point.
"""

from __future__ import annotations

import datetime
import time
from contextlib import suppress
from typing import Any

from colleague import editgate as _editgate
from colleague import escalation as _escalation  # noqa: F401 - patched as ``loop._escalation``
from colleague import loop_hooks as _loop_hooks
from colleague import loop_run_stages as _run_stages
from colleague import loopguards as _loopguards
from colleague import stallguard  # noqa: F401 - reached as ``loop.stallguard``
from colleague import media, salvage
from colleague import toolbatch_loop as _toolbatch_loop
from colleague import webbudget
from colleague.contract import (
    DECISION_DENY,
    DECISION_REWRITE,
    ERROR,
    OK,
    Step,
    Task,
    TaskResult,
    prompt_digest_for,
)
from colleague.hooks import HookConfig, HookDecision, load_hooks, run_hook
from colleague.loop_accounting import (  # noqa: F401 - also re-exported on this namespace
    _account_turn,
)
from colleague.loop_constants import (  # noqa: F401 - also re-exported on this namespace
    _EXIT_BUDGET,
    _EXIT_FINISHED,
    _EXIT_LOOP_GUARD,
    _EXIT_PILOT_STOP,
    _EXIT_STALLED,
    _EXIT_STOPPED,
    _EXIT_TOOL_PROTOCOL,
    _FINISH_NUDGE,
    _MARKUP_SYNTHESIS_PROMPT,
    _MAX_OVERFLOW_RETRIES,
    _MAX_TIMEOUT_RETRIES,
    _MEDIA_DELIVERY_FLOOR,
    _STALL_FLOOR_SECONDS,
    _parse_literal_finish,
    _strip_tool_markup,
)
from colleague.loop_context import (  # noqa: F401 - also re-exported on this namespace
    _compact_history,
    _consume_fillline_declaration,
    _distinct_folders_read,
    _inject_split_recommendation,
    _maybe_microcompact,
    _maybe_offer_fillline,
    _maybe_offer_mapping_fanout,
    _maybe_offer_plan_mode,
    _maybe_offer_review_fanout,
    _offer_fillline,
    _seat_complete,
)
from colleague.loop_flight import (  # noqa: F401 - also re-exported on this namespace
    _arm_flight,
    _flight_record,
    _flight_repo_path,
    _fold_flight_chat,
    _reap_flight,
    _record_applied_injection,
)
from colleague.loop_gatebase import (  # noqa: F401 - also re-exported on this namespace
    _gate_changed_set,
    _gates_deferred_to_chain,
)
from colleague.loop_gates import (  # noqa: F401 - also re-exported on this namespace
    _run_pre_finish_gates,
)
from colleague.loop_memory import (  # noqa: F401 - also re-exported on this namespace
    _maybe_recall_memory,
    _maybe_remember_lesson,
)
from colleague.loop_outcomes import (  # noqa: F401 - also re-exported on this namespace
    _apply_finish,
    _apply_outcome_flags,
    _finalize_finish_states,
    _finalize_stats,
    _maybe_flag_incompletion,
    _resolve_nudge_cap,
    _resolve_reading_budget,
    _senses_finish_record,
)
from colleague.loop_progress import (  # noqa: F401 - also re-exported on this namespace
    _emit_phase,
    _emit_progress,
)
from colleague.loop_senses import (  # noqa: F401 - also re-exported on this namespace
    _classify_media_delivery,
    _maybe_inject_context_packet,
    _maybe_inject_self_knowledge,
    _maybe_inject_upfront_hint,
    _maybe_record_media_delivery,
    _maybe_run_media_bridge,
    _maybe_warn_too_big,
)
from colleague.loop_setup import (  # noqa: F401 - also re-exported on this namespace
    _build_user_message,
    _resolve_run_collaborators,
    curated_schemas,
    resolve_role,
)
from colleague.loop_synthesis import (  # noqa: F401 - also re-exported on this namespace
    _maybe_force_synthesis,
    _resolve_terminal_summary,
)
from colleague.loop_tae import (  # noqa: F401 - also re-exported on this namespace
    _tae_close,
    _tae_drain,
    _tae_finalize,
    _tae_verdict,
)
from colleague.loop_testgates import (  # noqa: F401 - also re-exported on this namespace
    _affectedtests_controls,
    _maybe_run_acceptance_selfcheck,
    _parse_acceptance_outcomes,
)
from colleague.loop_toolexec import (  # noqa: F401 - also re-exported on this namespace
    _execute_tool,
    _policy_verdict,
    _tool_protocol_broken,
    _track_unknown_tool,
)
from colleague.loop_transport import (  # noqa: F401 - also re-exported on this namespace
    _agents_begin,
    _agents_end,
    _complete_turn_or_retry,
    _is_truncated_turn,
    _mark_progress,
    _record_turn_latency,
    _stall_bound,
    _stalled_between_turns,
    _turn_transport_guarded,
)
from colleague.loop_turn import (  # noqa: F401 - also re-exported on this namespace
    _handle_no_tool_turn,
)
from colleague.loop_types import (  # noqa: F401 - also re-exported on this namespace
    ContextControls,
    ProgressFn,
    Spawns,
    _make_timeout_escalator,
    _make_transport_guard_probe,
    _too_long_min_of,
    _Work,
)
from colleague.loop_wire import (  # noqa: F401 - also re-exported on this namespace
    CompleteFn,
    ModelResponse,
    ToolCall,
    WorkAborted,
    _assistant_message,
    _tool_message,
)
from colleague.neighbours import NeighbourManager
from colleague.policy import Policy, load_policy
from colleague.prompttext import default_system as _default_system_text
from colleague.telemetry import Telemetry, load_telemetry
from colleague.tools import ToolError, ToolExecutor

# The default system prompt lives in colleague/prompttext.py (adopted qwen-code
# structure + the COLLEAGUE_PROMPT_VARIANT=v1 floor). Built ONCE at import for the
# model-agnostic default family; Engine.system_prompt() builds the model-keyed
# variant once per run. Kept under this name so nothing else in the loop changes.
_DEFAULT_SYSTEM = _default_system_text()


def _fire_hooks(
    hooks: HookConfig,
    result: TaskResult,
    *,
    event: str,
    task: Task,
    tool: str | None = None,
    arguments: dict[str, Any] | None = None,
    policy: Policy | None = None,
) -> HookDecision | None:
    """Fire every matching hook for *event* — the loop's binding of the lane.

    The lane itself is :func:`colleague.loop_hooks.fire_hooks`; this binding
    exists so the hook subprocess runner is looked up as ``run_hook`` in THIS
    module's namespace on every call. That keeps ``colleague.loop.run_hook``
    the single overridable seam it has always been — the contract that a
    crashing hook can never abort the work item is proven by overriding
    exactly this name.
    """
    return _loop_hooks.fire_hooks(
        hooks,
        result,
        event=event,
        task=task,
        runner=run_hook,
        tool=tool,
        arguments=arguments,
        policy=policy,
    )


def _tae_commit_initial_plan(ctx: _Work) -> None:
    """The ``initial_plan_commit`` boundary — the FRONT commits thought 1.

    The committed thought is injected as a user turn so the worker acts under a
    named ``thought_id`` (which its next consequential action then binds to).
    A strict no-op when the mode is unarmed; best-effort always — a front that
    cannot commit leaves the worker without action authority, which the
    per-tool-call gate then reports honestly rather than crashing the run.
    """
    if ctx.tae is None:
        return
    with suppress(Exception):
        ctx.tae.commit_initial_plan(_build_user_message(ctx.task))
    _tae_drain(ctx)


def _gate_tool_call(ctx: _Work, call: ToolCall) -> tuple[Any, str | None, bool]:
    """The three gates, decision only: ``(arguments, deny_reason, hook_denied)``.

    ``pre_tool`` hook (the only control-bearing event — first deny/rewrite wins, a
    rewrite swaps the arguments) → the thought→action→evaluation boundary (t13:
    the HOST classifies a consequential action; alignment is never permission) →
    the operator's approval policy AFTER hooks so a rewrite is still gated. Every
    gate runs on the MAIN thread in request order BEFORE any execution — the
    batch path (:mod:`colleague.toolbatch_loop`) relies on that.
    """
    arguments = call.arguments
    decision = _fire_hooks(
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


def _fire_post_tool(ctx: _Work, tool: str, arguments: Any) -> None:
    """``post_tool`` fires after every tool *attempt*; observe-only this increment."""
    _fire_hooks(
        ctx.hooks,
        ctx.result,
        event="post_tool",
        task=ctx.task,
        tool=tool,
        arguments=arguments,
        policy=ctx.policy,
    )


def _record_execution(
    ctx: _Work, call: ToolCall, arguments: Any, span: Any, step_index: int, outcome: Any, exc: Any
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
        _fire_post_tool(ctx, call.name, arguments)
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
    _fire_post_tool(ctx, call.name, arguments)
    if not outcome.finished:
        return False
    span.set(finished=True)
    _apply_finish(ctx.result, outcome)
    return True


def _run_tool_call(ctx: _Work, call: ToolCall) -> bool:
    """Run one tool call inside its own telemetry span; return whether it finished.

    gate → execute → record, inside ONE ``with tool_span`` block so exactly one
    step/tool-call metric is recorded per call — deny and error paths included.
    """
    step_index = len(ctx.result.steps)
    with ctx.telemetry.tool_span(tool=call.name, step_index=step_index) as span:
        arguments, reason, hook_denied = _gate_tool_call(ctx, call)
        if reason is not None:
            _record_denial(ctx, call, arguments, span, step_index, reason, hook_denied)
            return False
        outcome, exc = _execute_tool(ctx.executor, call.name, arguments)
        return _record_execution(ctx, call, arguments, span, step_index, outcome, exc)


def _run_tool_calls(ctx: _Work, calls: list[ToolCall]) -> bool:
    """Run every tool call in one model turn; return whether any finished.

    Calls are partitioned into ordered batches (:mod:`colleague.toolbatch_loop`,
    c6/c35): consecutive read-only calls run in parallel under
    ``COLLEAGUE_TOOL_CONCURRENCY`` (default 10; 1 = the sequential path,
    byte-identical to the pre-batch loop), every mutating call runs alone, and
    results land in request order. A finish does *not* stop the turn — the
    remaining calls still run (the original inner ``for`` kept iterating; only the
    outer step loop broke afterwards). A flight stop is honoured at the BATCH
    boundary: in-flight tools finish or hit their own timeout first (threads
    cannot be killed), so stop latency is up to the slowest in-flight tool's own
    timeout — never "immediate" (c36/h25).
    """
    return _toolbatch_loop.run_turn_calls(ctx, calls, _run_tool_call)


def _advance_and_mark(ctx: _Work, resp: ModelResponse, nudges: int) -> tuple[int, str | None]:
    """:func:`_advance_turn`, then restart the step-stall clock if a step completed (#400)."""
    steps_before = len(ctx.result.steps)
    nudges, exit_reason = _advance_turn(ctx, resp, nudges)
    if len(ctx.result.steps) > steps_before:
        _mark_progress(ctx)
    return nudges, exit_reason


def _advance_turn(ctx: _Work, resp: ModelResponse, nudges: int) -> tuple[int, str | None]:
    """Process a normal (non-fill-line) turn; return ``(nudges, exit_reason_or_None)``.

    Either handles a no-tool-call turn (nudge once, else stop) or runs the turn's tool
    calls (a finish ends the work item). Extracted from :func:`_work_loop` so that
    function's cognitive complexity stays within budget (SonarCloud S3776).
    """
    if not resp.tool_calls:
        return _handle_no_tool_turn(ctx, resp, nudges)
    trip = _loopguards.check(ctx.result.steps, resp.tool_calls)  # t16: always-on guards
    if trip is not None:
        ctx.result.warnings.append(trip)
        return nudges, _EXIT_LOOP_GUARD
    ctx.messages.append(_assistant_message(resp))
    # Run the turn's tool calls; a finish on any of them ends the work item once the
    # turn completes (the remaining calls in the turn still run).
    if _run_tool_calls(ctx, resp.tool_calls):
        return nudges, _EXIT_FINISHED
    return nudges, None


def _flight_stop_requested(ctx: _Work) -> bool:
    """Read the flight control file at a turn boundary; inject guidance, report stop.

    A strict no-op (returns ``False``) when the work item is not a watchable flight.
    Each unconsumed guidance message is injected as a user-role turn so the model
    incorporates it on its NEXT turn; a ``stop`` directive asks the loop to end
    cooperatively. Both take effect only HERE, at the boundary — never mid-turn
    (cooperative, not preemptive).

    Under the ARMED thought→action→evaluation mode (t13) the guidance does NOT
    become a raw worker turn: mid-run operator words that silently redefine the
    running thought behind the evaluator's back are the forbidden move. Instead
    each message is routed to the FRONT as an observation
    (:meth:`colleague.tae_loop.TaeSession.observe`), and only a thought the
    front actually commits — superseding the old one — reaches the worker, via
    the drained brief. The artifact/feed injection record is unchanged either
    way, so the operator's steering stays reconstructable.
    """
    if ctx.flight is None:
        return False
    control = ctx.flight.read_control()
    for message in control.guidance:
        if ctx.tae is not None:
            with suppress(Exception):
                ctx.tae.observe(message, source="flight-guidance")
            _tae_drain(ctx)
        else:
            ctx.messages.append({"role": "user", "content": f"[pilot guidance] {message}"})
        _record_applied_injection(ctx, message)
    return bool(control.stop)


def _work_loop(ctx: _Work, complete: CompleteFn, max_steps: int) -> str:
    """Run the bounded turn loop; return how it ended (one of the ``_EXIT_*`` constants).

    Each turn: window the history to the context budget (if set), call
    ``complete`` (with a bounded overflow shrink-and-retry), account usage, then
    either run the turn's tool calls or handle a no-tool-call turn. Whatever
    ``complete`` raises (after the bounded retry) propagates to :func:`run`, which
    turns it into a preserved partial result (#37). Pulled out of :func:`run` so
    the loop body lives in one focused function and ``run`` keeps its cognitive
    complexity under the threshold (SonarCloud S3776).

    Returns ``_EXIT_FINISHED`` (the finish tool was called), ``_EXIT_STOPPED`` (the
    model ended a turn with no tool call and — even after one nudge — never called
    finish; colleague#142), or ``_EXIT_BUDGET`` (``max_steps`` *model turns* taken
    without finishing).

    The budget counts *successful model turns* (``stats.model_turns``), not raw
    loop iterations: an exhausted-overflow iteration that only injects the
    auto-split recommendation (no ``complete`` returned, so no turn accounted) must
    NOT consume the budget — otherwise an overflow on the final iteration would
    leave the model zero turns to act on the recommendation (#151 review). Still
    bounded: the one-time injection aside, every iteration either accounts a turn
    (advancing toward the cap) or re-raises (exiting the loop), so it runs at most
    ``max_steps + 1`` iterations.
    """
    nudges = 0
    last_prompt_tokens = 0
    budget = max(1, max_steps)
    _mark_progress(ctx)
    while ctx.result.stats.model_turns < budget:
        # Step-stall watchdog (#400): a turn that crossed the bound (in-stream via
        # stallguard, or measured here between turns) ends the episode honestly.
        if _stalled_between_turns(ctx):
            return _EXIT_STALLED
        # Flight-control checkpoint (piloting): at this turn boundary honor a pilot's
        # cooperative `stop` and inject any new `guidance` BEFORE the next model call.
        # A strict no-op when the work item is not a watchable flight.
        if _flight_stop_requested(ctx):
            return _EXIT_PILOT_STOP
        # Unknown-tool streak guard (#321): stop a run whose tool-call channel is
        # provably broken rather than re-burning the remaining budget on it.
        if _tool_protocol_broken(ctx):
            return _EXIT_TOOL_PROTOCOL
        last_prompt_tokens = _maybe_microcompact(ctx, last_prompt_tokens)  # t16: floor first
        # Proactive fill-line decision (#156): when the last turn's context crossed the
        # threshold, offer the one capacity decision (compact | split | handoff) BEFORE
        # this turn completes, so the model declares it by its next action. No-op when
        # dormant / already offered / under the line.
        _maybe_offer_fillline(ctx, last_prompt_tokens)
        # Mapping fan-out advisory (#188): once a wide read-only survey has read many
        # files serially, nudge the model ONCE to fan out per-folder via `subagents`
        # rather than spend the rest of its step budget reading. No-op when dormant /
        # already offered / under the files-read threshold.
        _maybe_offer_mapping_fanout(ctx)
        # Review fan-out advisory (#220b): once a review has read across many folders,
        # nudge the model ONCE to fan out per-folder read-only `reviewer` subagents
        # rather than keep reading serially. No-op when dormant / already offered /
        # under the distinct-folders threshold.
        _maybe_offer_review_fanout(ctx)
        resp = _complete_turn_or_retry(ctx, complete)
        if resp is None:
            continue
        _account_turn(ctx, resp)
        last_prompt_tokens = resp.prompt_tokens
        # Episode-boundary config lifecycle loop seam (t6): record the pinned
        # effective-config digest for THIS completed model turn. A strict
        # no-op without a lifecycle; when present, every recorded digest
        # within one ``run()`` call is identical by construction — nothing
        # between two ``observe_turn()`` calls ever mutates the snapshot.
        if ctx.config_lifecycle is not None:
            ctx.config_lifecycle.observe_turn()
        # Delivered-vs-dropped verification (t9, decision c25): classify the
        # task's attachments from the FIRST media-bearing completion's
        # token-contribution signal; a strict no-op afterwards and for
        # attachment-less runs.
        _maybe_record_media_delivery(ctx, resp)

        # If a fill-line decision is pending (#156), this turn is the model's
        # declaration: record it and, on a pure compact declaration, summarize +
        # continue from the compact note. A compact-with-tool-calls turn or a
        # split/finish declaration falls through so the declaring turn's tool calls
        # still run (never discarded).
        if _consume_fillline_declaration(ctx, resp, complete):
            continue

        nudges, exit_reason = _advance_and_mark(ctx, resp, nudges)
        # Record this turn on the live flight feed (no-op when unwatched) — placed
        # after _advance_turn so the step trace + stats already reflect the turn, and
        # before the exit return so a finishing turn is still recorded.
        _flight_record(ctx, resp)
        if exit_reason is not None:
            return exit_reason
    return _EXIT_BUDGET


def _build_initial_content(task: Task) -> "str | list[dict[str, Any]]":
    """The first user turn's content: a plain string, or content parts with media.

    With ``task.attachments`` empty/None this returns :func:`_build_user_message`'s
    string UNCHANGED — the h8 baseline: downstream string-assuming code
    (windowing, markup re-parse, fill-line) must never meet a surprise list on
    an attachment-less run. With attachments it returns OpenAI content parts:
    one text part carrying the full task prompt, then one part per attachment
    in order (:func:`colleague.media.build_part`). An attachment whose file
    became unreadable between surface validation and here degrades to a text
    placeholder naming the path — a broken attachment must never abort the run
    (the delivered/dropped verification is the honest record, task t9).
    """
    text = _build_user_message(task)
    if not task.attachments:
        return text
    parts: list[dict[str, Any]] = [{"type": "text", "text": text}]
    for attachment in task.attachments:
        try:
            parts.append(media.build_part(attachment))
        except (OSError, ValueError, KeyError) as exc:
            path = attachment.get("path", "?") if isinstance(attachment, dict) else "?"
            parts.append({"type": "text", "text": f"[attachment {path} unreadable: {exc}]"})
    return parts


def _resolve_runtime_defaults(
    task: Task,
    model: str | None,
    hooks: HookConfig | None,
    telemetry: Telemetry | None,
    policy: Policy | None,
) -> tuple[HookConfig, Telemetry, Policy]:
    """Default the three repo-resolved collaborators (hooks/telemetry/policy) when
    a caller didn't inject them. Kept out of ``run()`` so the per-field
    ``is not None`` ternaries don't inflate its cognitive complexity (mirrors
    ``_affectedtests_controls``). Byte-identical to the inline defaulting:
    hooks/policy resolve from ``task.repo_path`` (+ per-model overlay when
    ``model`` is given); telemetry resolves from the environment (a no-op
    unless ``COLLEAGUE_OTEL_ENABLED`` is set)."""
    return (
        hooks if hooks is not None else load_hooks(task.repo_path, model=model),
        telemetry if telemetry is not None else load_telemetry(),
        policy if policy is not None else load_policy(task.repo_path, model=model),
    )


def run(
    complete: CompleteFn,
    task: Task,
    *,
    max_steps: int,
    executor: ToolExecutor | None = None,
    system_prompt: str | None = None,
    hooks: HookConfig | None = None,
    telemetry: Telemetry | None = None,
    model: str | None = None,
    progress: ProgressFn | None = None,
    policy: Policy | None = None,
    spawns: Spawns | None = None,
    context: ContextControls | None = None,
    seat: str = "cortex",
) -> TaskResult:
    """Drive ``complete`` against ``task`` until finish or the ``max_steps`` budget.

    ``executor`` defaults to one confined to ``task.repo_path``. ``hooks`` defaults to the config
    loaded from ``task.repo_path`` (so engines that call :func:`run` unchanged still get the
    lifecycle); pass an explicit :class:`~colleague.hooks.HookConfig` (e.g. an empty one) to
    override or suppress repo loading. Returns a uniform :class:`TaskResult` with the per-step
    trace, accumulated usage, and every hook firing in order. The tool schemas live with each
    backend's ``complete`` closure, not here.

    ``model`` threads into per-model hook resolution: when given,
    :func:`~colleague.hooks.load_hooks` additionally loads the per-model overlay
    ``.colleague/<model>/hooks.json`` and prepends its entries ahead of the base entries (per-model
    fix takes priority); ``None`` (the default) is the base-only load — no behavior change for
    callers that do not pass a model.

    ``telemetry`` likewise defaults to :func:`~colleague.telemetry.load_telemetry` (a no-op unless
    ``COLLEAGUE_OTEL_ENABLED`` is set). When enabled, every tool call becomes a
    ``colleague.tool.*`` span and the loop records the per-step metrics (steps, tokens, tool
    latency, hook denials) — lives in the loop so *every* engine inherits it (the all-engines
    rule), like hook firing.

    ``progress`` is an optional per-step sink ``(step_index, tool, target, ok)`` fired after each
    tool call (#38); ``None`` (the default) is a strict no-op. Like hooks/telemetry, runtime-owned
    — every backend forwards ``config.progress``.

    ``spawns`` is an optional :class:`Spawns` bundle of the two delegation callbacks —
    ``spawns.single`` backs the ``subagent`` tool, ``spawns.batch`` backs the parallel
    ``subagents`` tool (built by :func:`colleague.subagents.make_spawn`/``make_batch_spawn``) —
    injected into the :class:`~colleague.tools.ToolExecutor` when given; ``None`` (or an unset
    field) leaves that tool unavailable. Runtime-owned: backends build their own executor via
    ``config.subagent_spawn``/``config.subagent_batch_spawn`` (the ``executor`` seam) for direct
    callers. Nested results snapshot onto ``result.sub_results`` on every exit path (with
    ``changed_files``).

    ``context`` is an optional :class:`ContextControls` bundle of the three
    context-window-management knobs — ``budget`` (windows history + drives the bounded overflow
    shrink-and-retry), ``count_tokens`` (handed to :func:`window_messages`), and
    ``autosplit_target`` (with ``budget`` also positive, arms reactive auto-split #151: an
    exhausted overflow recommends splitting via ``subagents`` before escalating, plus a coarse
    up-front hint) — see that class for the per-field contract. ``None``, or any field ``None``/0,
    is a strict no-op byte-identical to the pre-feature loop; runtime-owned (all-engines rule):
    every backend forwards its ``config`` budget + autosplit target here.

    If ``complete`` raises mid-loop (e.g. a per-request timeout, or a context-overflow the bounded
    retry could not recover), the partial work is *preserved*: the accumulated ``steps`` /
    ``usage`` / ``changed_files`` are finalized onto the result with ``status=error`` and re-raised
    as :class:`WorkAborted` carrying that result, so the work path can write a non-empty artifact +
    trace before surfacing the error (#37).

    ``seat`` names the acting seat for the flight run-start marker (#308) — forwarded verbatim to
    :meth:`~colleague.flight.FlightSession.append_run_start` and nowhere else (t2,
    change-content-consumption-lane spec, covers c9/h9). The default ``"cortex"`` keeps every
    caller that does not pass ``seat`` byte-identical to the pre-t2 line. Each engine's ``work()``
    resolves which seat actually acts (``"worker"`` under three-tier execution) and passes the
    label here — ``run()`` never inspects ``config`` (not a parameter), so the resolution decision
    stays at the call site; this only threads the already-resolved label to the one emit call (h11:
    no other path branches on ``seat``).

    ``run`` resumes the web-call budget on continuation (t9) from the prior episode's
    ``web_calls``/``web_failed``, embedded by :func:`colleague.escalation.build_continuation` and
    parsed via :func:`colleague.webbudget.resume_counts` — the same seam as ``context_note``.
    """
    _spawns, _context, executor = _resolve_run_collaborators(spawns, context, executor, task)
    # t21: a continuation seed's own preamble names the resumed task id (all
    # engines build ``executor`` from ``task.repo_path`` alone); reading it
    # back here needs no wiring between continuation.py and the executor.
    executor.context_note = _editgate.continuation_id(task.instruction)
    # The run's identity on the executor (Qodo #469/4): a hire mints with the
    # real task id (its ledger ref is ``artifact:<task_id>#hires[...]``) instead
    # of "" — the same no-wiring seam ``context_note`` uses. ``step_count`` is
    # kept live by the step recorder below.
    executor.task_id = task.id
    executor.step_count = 0
    executor.web_calls, executor.web_failed = webbudget.resume_counts(task.instruction)
    # hooks/telemetry/policy each default from the repo (or the environment, for
    # telemetry) when not injected — see _resolve_runtime_defaults for the
    # per-field contract (byte-identical to the prior inline defaulting).
    hooks, telemetry, policy = _resolve_runtime_defaults(task, model, hooks, telemetry, policy)

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt or _DEFAULT_SYSTEM},
        {"role": "user", "content": _build_initial_content(task)},
    ]

    result = TaskResult(task_id=task.id, status=OK)
    # Prompt digest (t7) — stamped the moment the result exists, not by the
    # engine after run() returns: the two paths that never reach that line (a
    # WorkAborted carrying this same partial, and the interrupt-salvage handler
    # reading the live object registered below) are exactly the runs whose arm
    # attribution matters most. Digests the ``system_prompt`` ARGUMENT, never
    # the ``_DEFAULT_SYSTEM`` fallback, so a caller that composed no prompt
    # still leaves the key off the artifact — byte-identical.
    result.prompt_digest = prompt_digest_for(system_prompt)
    # Interrupt salvage (#410): expose the live partial so the work CLI's
    # SIGTERM/SIGINT handler can write the artifact before the process unwinds.
    salvage.register(task.id, result)

    # Neighbour clone lifecycle — runtime-owned (all-engines rule).
    # clone_all() runs before the loop so allow-listed neighbours are available
    # to read during the work item. With no allow-list this is a safe no-op (verified
    # by NeighbourManager itself). cleanup() runs unconditionally after the loop
    # on EVERY exit path (model finish, empty turn, step-budget) to leave no
    # residue between drives.
    neighbours = NeighbourManager(task.repo_path)
    # A neighbour clone failure (unreachable remote, bad URL, timeout, bad name)
    # must never abort the work item — the loop proceeds without that neighbour. This
    # mirrors the "a hook must never abort the work item" fail-safe: neighbour clones
    # are best-effort context, not a precondition for the task.
    with suppress(Exception):
        neighbours.clone_all()

    # task_start — once, before the loop. Observe-only: side-effects only.
    _fire_hooks(hooks, result, event="task_start", task=task, policy=policy)

    # Arm the flight-control plane when this is a watchable flight (a strict no-op
    # otherwise); inherited by every backend (the all-engines rule).
    flight_session = _arm_flight(task)

    # The fixed collaborators for this drive — passed as one ``ctx`` to the
    # per-turn / per-call helpers so the loop body stays shallow.
    ctx = _Work(
        executor=executor,
        hooks=hooks,
        telemetry=telemetry,
        task=task,
        result=result,
        messages=messages,
        policy=policy,
        progress=progress,
        model=model or "",
        senses_model=_context.senses_model,
        lobes_gateway=_context.lobes_gateway,
        max_steps=max_steps,
        context_budget=_context.budget,
        count_tokens=_context.count_tokens,
        deepthink_run=_context.deepthink_run,
        associate_complete=_context.associate_complete,
        media_bridge=_context.media_bridge,
        senses_run=_context.senses_run,
        senses_media_bridge=_context.senses_media_bridge,
        autosplit_target=_context.autosplit_target,
        capacity_threshold=_context.fillline_threshold,
        too_long_min=_context.too_long_min,
        chain_armed=_context.chain_armed,
        chain_episode=_context.chain_episode,
        # No or-() guard: ContextControls defaults it to () and from_config
        # normalizes — a bare tuple() keeps run() under the S3776 ceiling.
        chain_prior_changed=tuple(_context.chain_prior_changed),
        compaction_cap=_context.compaction_cap,
        mapping_fanout_files=_context.fanout_files,
        review_fanout_folders=_context.review_fanout_folders,
        plan_offer_tokens=_context.plan_offer_tokens,
        max_continue_nudges=_resolve_nudge_cap(_context),
        request_timeout=_context.request_timeout,
        fanout_throttle=_context.throttle_fanout,
        agents=_context.agents_run,
        escalate_timeout=_context.escalate_timeout,
        transport_guarded=_context.transport_guarded,
        flight=flight_session,
        lint_enabled=bool(_context.lint),
        lint_fix_retries=_context.lint_fix_retries or 0,
        coherence_enabled=bool(_context.coherence),
        memory_enabled=bool(_context.memory),
        memory_root=_context.memory_root,
        memory_distill=bool(_context.memory_distill),
        distill_fn=_context.distill_fn,
        distill_author=_context.distill_author,
        embed_env=dict(_context.embed_env or {}),
        testintegrity_enabled=bool(_context.testintegrity),
        testintegrity_fix_retries=_context.testintegrity_fix_retries,
        testintegrity_reviewer_model=_context.testintegrity_reviewer_model,
        config_lifecycle=_context.config_lifecycle,
        tae=_context.tae_session,
        **_affectedtests_controls(_context),
    )

    # Thought->action->evaluation initial-plan commit (t13): the FRONT commits
    # the episode's first typed thought and it is injected as a user turn, so
    # the worker acts under a named thought_id. A strict no-op when unarmed.
    # Model-bound agents (#411, t15): open the ledger at the operator repo, resolve
    # the acting profile, seed the immutable request, and append the STATIC
    # guidance + nucleus to the system prompt ONCE (cache-friendly). No-op unarmed.
    _agents_begin(ctx, model or "", executor)
    _tae_commit_initial_plan(ctx)

    # Every pre-loop advisory injection, in order (split hint / plan-mode offer /
    # too-big warning / recall-before / senses packet / self-knowledge / media
    # bridge). Each is a strict no-op unless its own feature is armed.
    _run_stages.run_upfront_injections(ctx)

    # Drive timing (always-on): an ISO start stamp + a monotonic clock bracketing
    # the loop. Captured here so the duration covers the model work; finalized onto
    # WorkStats on every exit path below.
    started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    start_monotonic = time.monotonic()

    # #308 liveness: a run-start marker on the flight feed BEFORE the first
    # completion, so a pilot / senses can say "<seat> started, working on <goal>"
    # instead of "I don't know" during a slow first turn. Record the monotonic
    # start so ``_emit_phase`` can stamp each heartbeat's elapsed. Strict no-op
    # (and no feed line) when this is not a watchable flight. ``seat`` (t2,
    # change-content-consumption-lane spec, c9/h9) names the acting seat —
    # already resolved by the caller (``run()``'s own docstring); this call is
    # the ONE place that value is used, keeping the rest of the turn loop
    # untouched (h11).
    if ctx.flight is not None:
        ctx._flight_started_monotonic.append(start_monotonic)
        with suppress(Exception):
            ctx.flight.append_run_start(goal=task.goal, max_steps=max_steps, seat=seat)

    # The engine call (`complete`) may raise mid-loop. Catch it here so the
    # partial work accumulated on `result` is preserved rather than discarded
    # (#37); the finish hook + neighbour cleanup + changed_files snapshot below
    # then run on *every* exit path, including this one.
    aborted: Exception | None = None
    outcome = _EXIT_BUDGET
    # Synthesis reserve (#197) — held back from the reading budget so the
    # forced-synthesis verdict (#191) runs with fresher context. A strict no-op
    # when no reserve is set (see _resolve_reading_budget).
    reading_budget = _resolve_reading_budget(_context, max_steps)
    try:
        outcome = _work_loop(ctx, complete, reading_budget)
    except Exception as exc:  # noqa: BLE001 - preserve partial work on any engine failure
        aborted = exc
        result.status = ERROR
        result.error = f"{type(exc).__name__}: {exc}"

    # Episode-boundary config lifecycle (t6, decisions c8/h8/c26/h22): mark ONE
    # boundary — on EVERY loop exit (model finish / no-tool stop / budget /
    # pilot-stop / tool-protocol-broken / an aborted engine raise above), never
    # gated on which ``_EXIT_*`` reason ended the episode. This is the T1
    # regression fix: a prior tool-step-only boundary rule would silently skip
    # the no-tool-call stop path. A strict no-op without a lifecycle threaded in.
    if ctx.config_lifecycle is not None:
        ctx.config_lifecycle.end_episode()

    # finish — once, on every loop exit (model finish / empty turn / budget / error).
    # Observe-only this increment; requeue/re-drive is out of scope.
    _fire_hooks(hooks, result, event="finish", task=task, policy=policy)

    # Neighbour cleanup — runs on every loop exit, after the finish hook, so
    # no clone directory persists between drives. Safe even when no clones exist
    # (NeighbourManager.cleanup() is a no-op if the neighbours dir is absent).
    # Like clone_all above, a cleanup failure must never mask the task result.
    with suppress(Exception):
        neighbours.cleanup()

    # Live talk-lane fold (t5) — read the flight chat log into TaskResult.senses
    # BEFORE the reap deletes it, so the operator's mid-run conversation survives in
    # the artifact. A strict no-op when not a flight / no talk lane was used.
    _fold_flight_chat(ctx)

    # Flight cleanup — reap the live feed/control/chat on finish so the plane stays
    # ephemeral (a no-op when the work item was not a flight).
    _reap_flight(ctx)

    # Pre-finish gates — or their chain deferral (#335): the branch lives in
    # _run_pre_finish_gates (its docstring carries the full contract), keeping
    # run() flat under the S3776 ceiling. Runs BEFORE the changed_files
    # snapshot + stats below so any fix-turn edits are captured; the handoff
    # always proceeds.
    _run_pre_finish_gates(ctx, complete, outcome, aborted, work_loop=_work_loop)

    # Deepthink tool-call records (t5 / spec c14): snapshot the executor's
    # accumulated records BEFORE the self-check (which may append its own), in
    # firing order. No records → result.deepthink stays None → the key is
    # omitted from the artifact (byte-identical single-model run). getattr:
    # run() is a public seam and a test may pass a minimal executor stand-in.
    _dt_calls = getattr(executor, "deepthink_calls", None)
    if _dt_calls:
        result.deepthink = list(_dt_calls)

    # Acceptance self-check (t15 / spec R6 / #259): on a CLEAN finish of a task
    # that declared acceptance criteria, ONE bounded completion records advisory
    # per-criterion {criterion, met, evidence} outcomes on
    # result.acceptance_outcomes. Runs after the gates so it grades the final
    # (lint-fixed) state; never flips status; strict no-op without criteria.
    # A dual-model run escalates the grading to the deepthink model first (t5).
    _maybe_run_acceptance_selfcheck(ctx, complete, outcome, aborted)

    result.changed_files = sorted(executor.changed)
    # Record the typed-subagent role this work item ran as (#t4), on every exit
    # path. ``None`` (no role) is omit-when-None in to_dict → byte-identical.
    result.role = _context.role
    # Snapshot any nested child work items the executor accumulated — captured here,
    # the single place that runs on EVERY exit path (model finish / empty turn /
    # budget / the aborted path below), so a delegation survives even a mid-loop
    # engine raise. Empty when nothing was delegated → omitted from the artifact.
    result.sub_results = list(executor.sub_results)
    # hires (delegation-follow-ups t13/t14, Qodo #469/2): the SAME every-exit-path
    # snapshot as sub_results — without it a successful hire lived only on the
    # executor and the artifact promised evidence it never carried. Empty (no
    # roster, or an unarmed run) → the omit-when-empty key stays absent.
    from colleague import hire_assign as _hire_assign

    result.hires = _hire_assign.hires_block(executor)
    # Finalize the always-on drive statistics — runs on every exit path (here,
    # the single place after changed_files is known), so even a partial/aborted
    # drive carries populated stats. The optional telemetry mirrors bytes_written.
    _finalize_stats(
        result,
        task,
        executor,
        started_at=started_at,
        duration_seconds=round(time.monotonic() - start_monotonic, 6),
        model=model or "",
        served_model=(ctx._served_model[0] if ctx._served_model else ""),
    )
    telemetry.on_bytes_written(result.stats.bytes_written)

    # Resolve the last-substantive-content candidate from the work item loop.
    # ``ctx._last_substantive`` is a single-element list (or empty) updated
    # unconditionally on every turn — including turns that made tool calls.
    _last_sub = ctx._last_substantive[0] if ctx._last_substantive else ""

    if aborted is not None:
        # Finalize + raise WorkAborted with the partial preserved (#37).
        _run_stages.finish_aborted(ctx, outcome, aborted, model, _last_sub)

    # Outcome flags + honest status (#106 t5 + colleague#142 + colleague#192):
    # derived from the _work_loop return. We are in the non-aborted path here, so
    # WorkAborted is not raised — that is a different signal and the flags are left
    # False for it (the default covers it above). Two orthogonal non-clean exits:
    #   * not_finished           — step budget exhausted without finishing (#106 t5).
    #   * stopped_without_finish — the model ended on a no-tool-call turn and, even
    #     after the nudge cap, never called finish (colleague#142); a caller must
    #     treat the result as a partial, not authoritative.
    # A clean finish leaves both False + status OK; any other outcome is INCOMPLETE;
    # a pilot's cooperative stop is a partial too. Do NOT derive either flag from
    # stats.step_count: max_steps bounds model *turns* while step_count counts *tool
    # calls*. (Flags + status set in the helper to keep run() under the S3776
    # cognitive-complexity threshold.)
    _apply_outcome_flags(result, outcome, _last_sub)

    # The clean-exit tail: summary precedence, per-seat finish states, honest
    # incompletion, the TAE episode boundary, remember-after, the not-finished
    # escalation seam and the agent/salvage close-out — in that order.
    _run_stages.finish_clean(ctx, outcome, complete, model, _last_sub)
    return result
