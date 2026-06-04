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
"""

from __future__ import annotations

import datetime
import json
import time
from collections import Counter
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any, Callable

from colleague import escalation as _escalation
from colleague.context import is_context_overflow, window_messages
from colleague.contract import (
    DECISION_DENY,
    DECISION_REWRITE,
    ERROR,
    NO_RESULT_PRODUCED,
    OK,
    HookFiring,
    Step,
    Task,
    TaskResult,
)
from colleague.hooks import HookConfig, HookDecision, hook_approval_verdict, load_hooks, run_hook
from colleague.neighbours import NeighbourManager
from colleague.policy import Policy, load_policy
from colleague.telemetry import Telemetry, load_telemetry
from colleague.tools import ToolError, ToolExecutor, ToolOutcome
from colleague.tui.from_drive import progress_target as _progress_target

_DEFAULT_SYSTEM = (
    "You are a coding agent working inside a repository. Use the provided tools "
    "to inspect and edit files, then call finish with a short summary. Make the "
    "smallest change that satisfies the task."
    "\n\n"
    "Destination (optional). When a task is vague or new enough to benefit from a "
    "clear goal-frame, you MAY use the devague tool to open or update one — this is "
    "advisory and entirely your own judgement. A clear, well-scoped task needs no "
    "destination; never set one just to set one. Convergence is advisory: you can "
    "call converge or status to see gaps, but you CANNOT confirm or reject your own "
    "claims (those are user-only moves the tool does not offer). Authoritative "
    "convergence belongs to the operator, not to you. When the work reaches the "
    "goal, declare arrival by passing destination (the frame slug) and announcement "
    "(the goal-frame's arrival announcement) to the finish tool."
    "\n\n"
    "Subagents (optional). When a task naturally splits into independent, well-scoped "
    "pieces, you MAY delegate them to nested child drives. Use the subagent tool to hand "
    "ONE scoped piece to a child (optionally on a different engine/model — for example a "
    "mechanical chunk a cheaper model can do). Use the subagents tool to fan out a BATCH "
    "of independent pieces that run in PARALLEL, each isolated in its own git worktree, "
    "with a final merge child that integrates their branches and surfaces any conflict "
    "(never force-merging). A good fit: a task that asks for two or more changes in "
    "separate files that do not depend on each other — fan them out with subagents. Each "
    "child runs the same bounded tool-loop (no git handoff); its result summary returns "
    "to you and any files it writes are merged into your changed set. This is advisory and "
    "entirely your own judgement: a simple, single-file task needs none, so never delegate "
    "just to delegate. Delegation is bounded (a capped depth and per-drive fan-out), so it "
    "always terminates."
    "\n\n"
    "Culture tools (optional). Two operator-installed AgentCulture CLIs are reachable "
    "through the culture tool, with your agent identity auto-injected and the working "
    "directory pinned at the repo root. Use cli='agtag' to work the mesh issue tracker "
    "(e.g. fetch or post issues on a sibling repo) and cli='devex' to inspect a repo's "
    "agent-first surface (e.g. explain/overview/learn). Reach for them only when the task "
    "genuinely needs the mesh issue tracker or another repo's surface — never for casual "
    "mutating actions. Only agtag and devex are permitted, and identity is injected for "
    "you, so you never pass it yourself. This is advisory and entirely your own judgement: "
    "a self-contained in-repo task needs neither."
)


# Bounded reactive degradation: how many times the loop may shrink the budget and
# retry a single ``complete`` call after a *context-overflow* error before giving
# up and re-raising. Bounded AND each retry strictly shrinks the budget, so the
# retry inside one turn always terminates (the outer ``max_steps`` loop is
# unchanged). 0.6 is the shrink factor applied per retry.
_MAX_OVERFLOW_RETRIES = 3
_OVERFLOW_SHRINK_FACTOR = 0.6


@dataclass
class ToolCall:
    """A single tool invocation requested by the model."""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class ModelResponse:
    """One model turn: free text, reasoning, any tool calls, and token usage.

    ``reasoning`` is the model's chain-of-thought when the server returns it as a
    separate field (OpenAI-compatible ``message.reasoning`` / ``reasoning_content``),
    distinct from ``content`` (the final answer). It is generated but never saved
    to a file, so the loop measures it as the "thought" portion of a drive
    (char/byte lengths in :class:`~colleague.contract.DriveStats`). Empty for
    servers/models that do not emit a reasoning field.
    """

    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning: str = ""


# A ``complete`` performs one model turn given the running message list.
CompleteFn = Callable[[list[dict[str, Any]]], ModelResponse]

# A progress sink: (step_index, tool, target, ok) -> None. Default ``None`` in the
# loop is a strict no-op; the CLI wires one that writes a line per step to stderr
# (#38). Lives in the loop, fired per tool call, so every backend inherits it
# identically (the all-engines rule), exactly like hooks and telemetry.
ProgressFn = Callable[[int, str, str, bool], None]


class DriveAborted(Exception):
    """An engine raised mid-loop; carries the partial result (#37).

    The bounded loop catches the engine's exception, finalizes the partial
    :class:`~colleague.contract.TaskResult` (``status=error`` plus the
    ``steps`` / ``usage`` / ``changed_files`` accumulated so far) and raises this
    so the shared drive path can persist that partial artifact + non-empty trace
    before surfacing the error to the operator. The original exception is the
    ``__cause__``.
    """

    def __init__(self, result: TaskResult) -> None:
        super().__init__(result.error or "drive aborted")
        self.result = result


def _arguments_json(arguments: Any) -> str:
    """OpenAI wire format wants function.arguments as a JSON *string*.

    The loop carries arguments as dicts for execution; serialize only on the way
    back into the message list so strict OpenAI-compatible servers accept replayed
    turns. A value that is already a string is passed through unchanged.
    """
    if isinstance(arguments, str):
        return arguments
    return json.dumps(arguments, ensure_ascii=False)


def _assistant_message(resp: ModelResponse) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": resp.content,
        "tool_calls": [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": _arguments_json(tc.arguments)},
            }
            for tc in resp.tool_calls
        ],
    }


def _tool_message(call_id: str, content: str) -> dict[str, Any]:
    return {"role": "tool", "tool_call_id": call_id, "content": content}


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
    """Run every matching hook for *event*, record a firing per hook, in order.

    Returns the first control-bearing :class:`HookDecision` (a ``deny`` or
    ``rewrite``) seen, or ``None``. Only ``pre_tool`` callers act on the return;
    for the observe-only events (``task_start`` / ``post_tool`` / ``finish``) the
    caller ignores it. ``allow`` / ``observe`` decisions are recorded but never
    control-bearing, so scanning continues past them.

    A firing is appended for *every* hook that runs — including the allow/observe
    ones leading up to a decisive one — so the run report sees the full sequence.

    When *policy* is given and its ``hooks`` section is present, each entry's
    command is checked via :func:`~colleague.hooks.hook_approval_verdict` before
    being run.  An unapproved entry is recorded as a ``HookFiring(decision=
    "skipped")`` and skipped — it does NOT set the decisive deny/rewrite and does
    NOT block the tool for ``pre_tool``.  With no ``hooks`` section (the default)
    every entry fires exactly as before (strict no-op).
    """
    entries = hooks.hooks_for(event, tool=tool)
    if not entries:
        return None

    payload = {
        "event": event,
        "tool": tool,
        "arguments": arguments,
        "task_id": task.id,
        "repo_path": task.repo_path,
    }

    decisive = None
    for entry in entries:
        # --- Content-approval gate (r1) ---
        # Check the hook's referenced repo files against the policy before running.
        # A skip is NON-control-bearing: it does NOT set decisive and does NOT
        # block the tool for pre_tool.  With no hooks section this is a strict no-op.
        if policy is not None:
            approval = hook_approval_verdict(entry.command, policy, task.repo_path)
            if not approval.allowed:
                result.hook_firings.append(
                    HookFiring(
                        event=event,
                        tool=tool,
                        command=entry.command,
                        decision="skipped",
                        exit_code=None,
                        reason=approval.reason,
                    )
                )
                continue

        # A hook must never abort the drive. run_hook already maps timeouts /
        # launch failures to a deny; this net catches any other unexpected error
        # and records it as a fail-closed deny firing rather than propagating.
        try:
            decision = run_hook(entry, payload, cwd=task.repo_path)
        # BLE001 justified: fail-closed — any hook error becomes a deny (see the
        # note above), never propagated, so a crashing hook cannot abort the drive.
        except Exception as exc:  # noqa: BLE001
            decision = HookDecision(
                decision=DECISION_DENY, reason=f"hook error: {exc}", exit_code=None
            )
        result.hook_firings.append(
            HookFiring(
                event=event,
                tool=tool,
                command=entry.command,
                decision=decision.decision,
                exit_code=decision.exit_code,
                reason=decision.reason,
            )
        )
        # The first deny/rewrite wins; allow/observe are non-decisive — keep going.
        if decisive is None and decision.decision in (DECISION_DENY, DECISION_REWRITE):
            decisive = decision
            # A decisive pre_tool verdict short-circuits the rest of the chain.
            if event == "pre_tool":
                break
    return decisive


@dataclass(frozen=True)
class _Drive:
    """The fixed collaborators threaded through one drive's tool-loop helpers.

    Grouped so the per-call helpers take one ``ctx`` instead of a long parameter
    list. ``result`` and ``messages`` are mutated *through* these references
    during the loop — ``frozen`` fixes the bindings, not the objects they hold.
    """

    executor: ToolExecutor
    hooks: HookConfig
    telemetry: Telemetry
    task: Task
    result: TaskResult
    messages: list[dict[str, Any]]
    policy: Policy = field(default_factory=Policy)
    progress: ProgressFn | None = None
    # Proactive context-window management (t4): when ``context_budget`` is a
    # positive int the running history is trimmed to it (via ``count_tokens``,
    # defaulting to the char estimate in ``window_messages``) before each turn,
    # and a context-overflow from ``complete`` triggers a bounded shrink-and-retry.
    # ``None`` (the default) is a strict no-op — no windowing, no reactive retry.
    context_budget: int | None = None
    count_tokens: Callable[[list[dict[str, Any]]], int] | None = None
    # Last non-empty ``resp.content`` seen across ALL turns (including turns that
    # also made tool calls).  Updated in ``_drive_loop`` unconditionally whenever
    # ``resp.content`` is non-empty — this is the t2 "last-substantive-content"
    # candidate used as the no-finish summary fallback in ``run``.  Stored as a
    # mutable list[str] (single element) so the frozen ``_Drive`` dataclass can
    # still update it through the binding.
    _last_substantive: list[str] = field(default_factory=list)


def _apply_finish(result: TaskResult, outcome: ToolOutcome) -> None:
    """Record a finish on ``result`` — summary, then optional destination/announcement.

    Same order and truthiness guards as the inline finish path it replaced: the
    destination/announcement are set only when the engine declared them, so a
    finish without a goal-frame leaves those keys off the artifact (the e2e shape
    test pins this).
    """
    result.summary = outcome.finish_summary or result.summary
    if outcome.destination:
        result.destination = outcome.destination
    if outcome.announcement:
        result.announcement = outcome.announcement


def _finalize_stats(
    result: TaskResult,
    task: Task,
    executor: ToolExecutor,
    *,
    started_at: str,
    duration_seconds: float,
) -> None:
    """Fill the drive-level :class:`DriveStats` fields known only at loop exit.

    The per-turn fields (``model_turns`` and the generated reasoning/answer sizes)
    are accumulated in :func:`_drive_loop`; this fills the rest from the finished
    result + executor. Called on EVERY exit path (model finish / empty turn /
    budget / mid-loop abort) so a partial drive still gets populated stats.
    """
    stats = result.stats
    stats.request = task.instruction
    stats.started_at = started_at
    stats.duration_seconds = duration_seconds
    stats.step_count = len(result.steps)
    stats.tool_counts = dict(Counter(step.tool for step in result.steps))
    stats.files_changed = len(result.changed_files)
    stats.bytes_written = executor.bytes_written


def _emit_progress(ctx: _Drive, step_index: int, tool: str, arguments: Any, ok: bool) -> None:
    """Fire the per-step progress sink, if one is wired (#38). No-op otherwise.

    A progress sink is observability, never control: a raising sink must never
    abort the drive, so its failure is suppressed (the same fail-safe as hooks
    and neighbour clones).
    """
    if ctx.progress is None:
        return
    with suppress(Exception):
        ctx.progress(step_index, tool, _progress_target(arguments), ok)


def _deny_by_policy(ctx: _Drive, call: ToolCall, span: Any, step_index: int) -> bool:
    """Check the approval policy for ``run_command``; record and return True on deny.

    Returns ``True`` when the call is denied (the caller must return False from
    the tool-call helper). Returns ``False`` when the policy allows the call.
    Only ``run_command`` is gated — all other tools pass through unchanged.
    """
    if call.name != "run_command":
        return False
    verdict = ctx.policy.check_run_command(str(call.arguments.get("command", "")))
    if verdict.allowed:
        return False
    # Denied — mirror the pre_tool DENY shape (span, Step, tool message, progress).
    span.set(ok=False, denied=True, reason=verdict.reason)
    ctx.result.steps.append(Step(step_index, call.name, call.arguments, verdict.reason, ok=False))
    ctx.messages.append(_tool_message(call.id, verdict.reason))
    _emit_progress(ctx, step_index, call.name, call.arguments, ok=False)
    return True


def _run_tool_call(ctx: _Drive, call: ToolCall) -> bool:
    """Run one tool call inside its own telemetry span; return whether it finished.

    Owns the per-call lifecycle: the ``pre_tool`` hook (first deny/rewrite wins),
    execution, the ``post_tool`` hook, and finish detection. Kept as a single
    ``with tool_span`` block so exactly one step/tool-call metric is recorded per
    call — including the deny and error paths, which still close the span on the
    way out (they ``return False``, replacing the loop's old ``continue``).
    """
    step_index = len(ctx.result.steps)

    # One span per tool-call iteration, auto-nesting under the drive span. A
    # ``return False`` still runs the span's exit (so its metrics — one step +
    # one tool call — are recorded for deny/error paths too).
    with ctx.telemetry.tool_span(tool=call.name, step_index=step_index) as span:
        # pre_tool — the only control-bearing event. The first deny/rewrite
        # wins; allow/observe pass through. arguments may be swapped here.
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
            # Skip execution entirely; feed the reason back so the model can
            # adapt. Recorded as a non-ok Step (the firing is already recorded
            # by _fire_hooks).
            reason = (decision and decision.reason) or "denied by a pre_tool hook"
            span.set(ok=False, denied=True, reason=reason)
            ctx.telemetry.on_hook_denial()
            ctx.result.steps.append(Step(step_index, call.name, arguments, reason, ok=False))
            ctx.messages.append(_tool_message(call.id, reason))
            _emit_progress(ctx, step_index, call.name, arguments, ok=False)
            return False
        if kind == DECISION_REWRITE and decision is not None and decision.arguments is not None:
            # Execute with the hook-supplied arguments instead.
            arguments = decision.arguments

        # Policy gate: check run_command against the operator-declared allow/deny
        # policy AFTER hooks (so a hook rewrite is still gated), BEFORE execution.
        # All other tools pass through unchanged. When denied, mirrors the hook-deny
        # shape — non-ok Step + tool message — but does NOT increment the hook-denial
        # telemetry counter (this is a policy denial, not a hook denial).
        if _deny_by_policy(ctx, ToolCall(call.id, call.name, arguments), span, step_index):
            return False

        try:
            outcome = ctx.executor.execute(call.name, arguments)
        except ToolError as exc:
            span.set(ok=False, error=str(exc))
            ctx.result.steps.append(
                Step(step_index, call.name, arguments, f"error: {exc}", ok=False)
            )
            ctx.messages.append(_tool_message(call.id, f"error: {exc}"))
            _emit_progress(ctx, step_index, call.name, arguments, ok=False)
            # post_tool still fires after a tool *attempt*; observe-only.
            _fire_hooks(
                ctx.hooks,
                ctx.result,
                event="post_tool",
                task=ctx.task,
                tool=call.name,
                arguments=arguments,
                policy=ctx.policy,
            )
            return False

        span.set(ok=True, bytes=len(outcome.result), changed_file=outcome.changed_file)
        ctx.result.steps.append(Step(step_index, call.name, arguments, outcome.result, ok=True))
        ctx.messages.append(_tool_message(call.id, outcome.result))
        _emit_progress(ctx, step_index, call.name, arguments, ok=True)

        # post_tool — after the tool executed. Observe-only: the decision does
        # not alter the already-executed result this increment.
        _fire_hooks(
            ctx.hooks,
            ctx.result,
            event="post_tool",
            task=ctx.task,
            tool=call.name,
            arguments=arguments,
            policy=ctx.policy,
        )

        if not outcome.finished:
            return False
        span.set(finished=True)
        _apply_finish(ctx.result, outcome)
        return True


def _run_tool_calls(ctx: _Drive, calls: list[ToolCall]) -> bool:
    """Run every tool call in one model turn; return whether any finished.

    A finish does *not* stop the turn — the remaining calls in the same response
    still run (matching the original loop, where ``finished`` was set but the
    inner ``for`` kept iterating; only the outer step loop broke afterwards).
    """
    finished = False
    for call in calls:
        if _run_tool_call(ctx, call):
            finished = True
    return finished


def _window_in_place(ctx: _Drive, budget: int) -> None:
    """Trim ``ctx.messages`` in place to *budget* tokens (preserves head + tail).

    Mutating in place (``[:]``) keeps the trimmed history across turns — dropping
    old context is intended; there is no summarization. ``window_messages``
    defaults ``count_tokens`` to the char estimate when ``ctx.count_tokens`` is
    ``None``.
    """
    ctx.messages[:] = window_messages(ctx.messages, budget, ctx.count_tokens)


def _complete_with_degradation(ctx: _Drive, complete: CompleteFn) -> ModelResponse:
    """Window the history, call ``complete``, and degrade-on-overflow if budgeted.

    Owns the proactive window + the bounded reactive shrink-and-retry so
    :func:`_drive_loop` stays shallow (SonarCloud S3776). With no positive
    ``context_budget`` this is a thin pass-through: no windowing, ``complete`` is
    called once and whatever it raises propagates unchanged.

    With a budget set: the history is windowed to it before the call. If
    ``complete`` raises a *context-overflow* error, the effective budget is shrunk
    (``* _OVERFLOW_SHRINK_FACTOR``, floored to ≥ 1), the history is re-windowed,
    and the call retried — up to ``_MAX_OVERFLOW_RETRIES`` times. Retrying stops
    (and the original error re-raises, so :func:`run` preserves the partial) when
    the cap is reached OR a re-window can no longer reduce the message count (the
    floor: only system + first user + last turn remain). Non-overflow errors are
    never retried — they propagate immediately.
    """
    budget = ctx.context_budget
    if not isinstance(budget, int) or budget <= 0:
        # Feature off: strict pass-through, byte-identical to the pre-feature loop.
        return complete(ctx.messages)

    # Proactive window to the full budget before the first attempt.
    _window_in_place(ctx, budget)
    effective = budget
    # The first attempt plus up to _MAX_OVERFLOW_RETRIES reactive retries. Each
    # retry strictly shrinks the budget AND must reduce the message count, so the
    # loop always terminates (the floor — system + first user + last turn — and the
    # cap both stop it). On any non-overflow error, or once neither the budget nor
    # the message list can shrink further, the error propagates to run()'s
    # preserved-partial path.
    for _ in range(_MAX_OVERFLOW_RETRIES + 1):
        try:
            return complete(ctx.messages)
        except Exception as exc:  # noqa: BLE001 - re-raised below unless it is overflow
            if not is_context_overflow(str(exc)):
                raise  # non-overflow errors propagate immediately (unchanged)
            shrunk = max(1, int(effective * _OVERFLOW_SHRINK_FACTOR))
            before = len(ctx.messages)
            _window_in_place(ctx, shrunk)
            # At the floor (re-window changed nothing) AND the budget can't shrink
            # further → retrying cannot help; let this overflow propagate.
            if shrunk >= effective and len(ctx.messages) >= before:
                raise
            effective = shrunk
    # Cap exhausted while still making progress: re-raise via one final attempt.
    return complete(ctx.messages)


def _drive_loop(ctx: _Drive, complete: CompleteFn, max_steps: int) -> bool:
    """Run the bounded turn loop; return whether the model finished.

    Each turn: window the history to the context budget (if set), call
    ``complete`` (with a bounded overflow shrink-and-retry), account usage, then
    either finish (no tool calls) or run the turn's tool calls. Whatever
    ``complete`` raises (after the bounded retry) propagates to :func:`run`, which
    turns it into a preserved partial result (#37). Pulled out of :func:`run` so
    the loop body lives in one focused function and ``run`` keeps its cognitive
    complexity under the threshold (SonarCloud S3776).
    """
    for _ in range(max(1, max_steps)):
        resp = _complete_with_degradation(ctx, complete)
        ctx.result.usage.add(resp.prompt_tokens, resp.completion_tokens)
        ctx.telemetry.on_completion(resp.prompt_tokens, resp.completion_tokens)
        # Per-turn statistics (always-on): count the turn and accumulate the
        # generated reasoning/answer sizes (chars + bytes). Mirrored into the
        # optional telemetry as a strict no-op when off.
        ctx.result.stats.model_turns += 1
        ctx.result.stats.add_generated(reasoning=resp.reasoning, answer=resp.content)
        ctx.telemetry.on_generated(reasoning=resp.reasoning, answer=resp.content)

        # Track the last substantive assistant content (t2): update on EVERY turn
        # that has non-empty ``resp.content``, including turns that also make tool
        # calls (the gap at the original line ~568).  Stored via the mutable proxy
        # so the frozen ``_Drive`` binding stays intact.
        if resp.content:
            ctx._last_substantive[:] = [resp.content]

        if not resp.tool_calls:
            # Model answered without requesting a tool — treat as done.
            # Already recorded as last_substantive above; set it directly so the
            # no-finish-tool path (line 565 in the original numbering) keeps its
            # semantics: a no-tool-call terminating turn with content becomes the
            # summary immediately, before the finalize fallback in run().
            if resp.content:
                ctx.result.summary = resp.content
            return True

        ctx.messages.append(_assistant_message(resp))
        # Run the turn's tool calls; a finish on any of them ends the drive once
        # the turn completes (the remaining calls in the turn still run).
        if _run_tool_calls(ctx, resp.tool_calls):
            return True
    return False


@dataclass(frozen=True)
class Spawns:
    """The two optional delegation callbacks injected into the tool executor.

    ``single`` backs the ``subagent`` tool (built by
    :func:`colleague.subagents.make_spawn`); ``batch`` backs the ``subagents``
    (plural) tool (built by :func:`colleague.subagents.make_batch_spawn`).
    Bundling the pair keeps :func:`run`'s signature within the parameter budget
    while preserving the convenience path for callers that do not build their own
    executor. Both default ``None`` (the tool is simply unavailable).
    """

    single: Callable | None = None
    batch: Callable | None = None


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
    context_budget: int | None = None,
    count_tokens: Callable[[list[dict[str, Any]]], int] | None = None,
) -> TaskResult:
    """Drive ``complete`` against ``task`` until finish or the ``max_steps`` budget.

    ``executor`` defaults to one confined to ``task.repo_path``. ``hooks``
    defaults to the config loaded from ``task.repo_path`` (so engines that call
    :func:`run` unchanged still get the lifecycle); pass an explicit
    :class:`~colleague.hooks.HookConfig` (e.g. an empty one) to override or
    suppress repo loading. Returns a uniform :class:`TaskResult` with the
    per-step trace, accumulated usage, and every hook firing in order. The tool
    schemas live with each backend's ``complete`` closure, not here.

    ``model`` threads into per-model hook resolution: when given,
    :func:`~colleague.hooks.load_hooks` additionally loads the per-model
    overlay ``.colleague/<model>/hooks.json`` and prepends its entries ahead
    of the base entries (per-model fix takes priority). When ``None`` (the
    default) the call is identical to the base-only load — no behavior change
    for callers that do not pass a model.

    ``telemetry`` likewise defaults to :func:`~colleague.telemetry.load_telemetry`
    (a no-op unless ``COLLEAGUE_OTEL_ENABLED`` is set). When enabled, every
    tool call becomes a ``colleague.tool.*`` span and the loop records the
    per-step metrics (steps, tokens, tool latency, hook denials). This lives in
    the loop so *every* engine inherits it (the all-engines rule), exactly like
    hook firing.

    ``progress`` is an optional per-step sink ``(step_index, tool, target, ok)``
    fired after each tool call (#38); ``None`` (the default) is a strict no-op.
    Like hooks/telemetry it is runtime-owned — every backend forwards
    ``config.progress`` so the behavior is identical across backends.

    ``spawns`` is an optional :class:`Spawns` bundle of the two delegation
    callbacks. ``spawns.single`` ``(instruction, engine=None, model=None) ->
    SubResult`` (built by :func:`colleague.subagents.make_spawn`) backs the
    ``subagent`` tool; ``spawns.batch`` ``(items) -> list[SubResult]`` (built by
    :func:`colleague.subagents.make_batch_spawn`) backs the ``subagents`` (plural)
    parallel-batch tool. When given they are injected into the
    :class:`~colleague.tools.ToolExecutor` so the corresponding tool can delegate
    to nested child drives; ``None`` (the default), or a field left ``None``,
    leaves that tool unavailable (it reports so to the model). This is runtime-owned
    — backends build their own executor from ``config.subagent_spawn`` /
    ``config.subagent_batch_spawn`` (the ``executor`` seam), so the ``spawns``
    convenience path is for direct callers. Any nested results the executor
    accumulates are snapshotted onto ``result.sub_results`` on every exit path
    (alongside ``changed_files``).

    ``context_budget`` is an optional proactive token budget (t4). When a positive
    int, the running history is windowed to it (via :func:`window_messages`)
    *before* every model turn, and a context-overflow raised by ``complete``
    triggers a bounded shrink-and-retry (the budget is reduced and the history
    re-windowed, up to ``_MAX_OVERFLOW_RETRIES`` times, before the error is
    re-raised into the preserved-partial path). ``count_tokens`` is the matching
    token counter handed to ``window_messages``; ``None`` falls back to the
    char-based estimate. Both default ``None`` → no windowing, no reactive retry
    (a strict no-op, byte-identical to the pre-feature loop). Like hooks/progress
    this is runtime-owned, so every backend that forwards ``config.context_budget_tokens``
    inherits it identically (the all-engines rule).

    If ``complete`` raises mid-loop (e.g. a per-request timeout, or a
    context-overflow the bounded retry could not recover), the partial work is
    *preserved*: the accumulated ``steps`` / ``usage`` / ``changed_files`` are
    finalized onto the result with ``status=error`` and re-raised as
    :class:`DriveAborted` carrying that result, so the drive path can write a
    non-empty artifact + trace before surfacing the error (#37).
    """
    _spawns = spawns or Spawns()
    executor = executor or ToolExecutor(
        task.repo_path, spawn=_spawns.single, batch_spawn=_spawns.batch
    )
    hooks = hooks if hooks is not None else load_hooks(task.repo_path, model=model)
    # Telemetry defaults like hooks do: resolved from the environment, a no-op
    # unless explicitly enabled. Tool spans auto-nest under the drive span the
    # shared drive path opens (via the SDK's context propagation).
    telemetry = telemetry if telemetry is not None else load_telemetry()
    # Policy defaults like hooks: loaded from task.repo_path when not injected.
    # An absent or malformed approvals.json returns an empty Policy (no-op), so
    # callers that never set policy= keep byte-identical behavior.
    policy = policy if policy is not None else load_policy(task.repo_path, model=model)

    user = task.instruction
    if task.context:
        user += f"\n\nContext:\n{task.context}"
    if task.constraints:
        user += "\n\nConstraints:\n" + "\n".join(f"- {c}" for c in task.constraints)

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt or _DEFAULT_SYSTEM},
        {"role": "user", "content": user},
    ]

    result = TaskResult(task_id=task.id, status=OK)

    # Neighbour clone lifecycle — runtime-owned (all-engines rule).
    # clone_all() runs before the loop so allow-listed neighbours are available
    # to read during the drive. With no allow-list this is a safe no-op (verified
    # by NeighbourManager itself). cleanup() runs unconditionally after the loop
    # on EVERY exit path (model finish, empty turn, step-budget) to leave no
    # residue between drives.
    neighbours = NeighbourManager(task.repo_path)
    # A neighbour clone failure (unreachable remote, bad URL, timeout, bad name)
    # must never abort the drive — the loop proceeds without that neighbour. This
    # mirrors the "a hook must never abort the drive" fail-safe: neighbour clones
    # are best-effort context, not a precondition for the task.
    with suppress(Exception):
        neighbours.clone_all()

    # task_start — once, before the loop. Observe-only: side-effects only.
    _fire_hooks(hooks, result, event="task_start", task=task, policy=policy)

    # The fixed collaborators for this drive — passed as one ``ctx`` to the
    # per-turn / per-call helpers so the loop body stays shallow.
    ctx = _Drive(
        executor=executor,
        hooks=hooks,
        telemetry=telemetry,
        task=task,
        result=result,
        messages=messages,
        policy=policy,
        progress=progress,
        context_budget=context_budget,
        count_tokens=count_tokens,
    )

    # Drive timing (always-on): an ISO start stamp + a monotonic clock bracketing
    # the loop. Captured here so the duration covers the model work; finalized onto
    # DriveStats on every exit path below.
    started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    start_monotonic = time.monotonic()

    # The engine call (`complete`) may raise mid-loop. Catch it here so the
    # partial work accumulated on `result` is preserved rather than discarded
    # (#37); the finish hook + neighbour cleanup + changed_files snapshot below
    # then run on *every* exit path, including this one.
    aborted: Exception | None = None
    finished = False
    try:
        finished = _drive_loop(ctx, complete, max_steps)
    except Exception as exc:  # noqa: BLE001 - preserve partial work on any engine failure
        aborted = exc
        result.status = ERROR
        result.error = f"{type(exc).__name__}: {exc}"

    # finish — once, on every loop exit (model finish / empty turn / budget / error).
    # Observe-only this increment; requeue/re-drive is out of scope.
    _fire_hooks(hooks, result, event="finish", task=task, policy=policy)

    # Neighbour cleanup — runs on every loop exit, after the finish hook, so
    # no clone directory persists between drives. Safe even when no clones exist
    # (NeighbourManager.cleanup() is a no-op if the neighbours dir is absent).
    # Like clone_all above, a cleanup failure must never mask the task result.
    with suppress(Exception):
        neighbours.cleanup()

    result.changed_files = sorted(executor.changed)
    # Snapshot any nested child drives the executor accumulated — captured here,
    # the single place that runs on EVERY exit path (model finish / empty turn /
    # budget / the aborted path below), so a delegation survives even a mid-loop
    # engine raise. Empty when nothing was delegated → omitted from the artifact.
    result.sub_results = list(executor.sub_results)
    # Finalize the always-on drive statistics — runs on every exit path (here,
    # the single place after changed_files is known), so even a partial/aborted
    # drive carries populated stats. The optional telemetry mirrors bytes_written.
    _finalize_stats(
        result,
        task,
        executor,
        started_at=started_at,
        duration_seconds=round(time.monotonic() - start_monotonic, 6),
    )
    telemetry.on_bytes_written(result.stats.bytes_written)

    # Resolve the last-substantive-content candidate from the drive loop.
    # ``ctx._last_substantive`` is a single-element list (or empty) updated
    # unconditionally on every turn — including turns that made tool calls.
    _last_sub = ctx._last_substantive[0] if ctx._last_substantive else ""

    if aborted is not None:
        # Carry the populated partial result out via DriveAborted; the drive path
        # writes it (non-empty steps/usage/changed_files + trace) then re-surfaces
        # the failure to the operator (#37).
        # Prefer the model's last substantive content over the generic aborted
        # note so the escalation continuation (below) carries the real output
        # rather than an empty/placeholder summary (Qodo #114).
        result.summary = (
            result.summary
            or _last_sub
            or (f"aborted after {len(result.steps)} step(s): {result.error}")
        )
        # Escalation seam — aborted path (#106 t3): best-effort, observe-only.
        # A timeout / context-overflow / engine error is a limit worth escalating.
        # Wrapped in suppress so any escalation failure never masks the drive result.
        with suppress(Exception):
            _escalation.escalate(result, result.stats, task.repo_path, model=model)
        raise DriveAborted(result) from aborted

    # Explicit not-finished flag (#106 t5): set from the _drive_loop return value,
    # which is True when the model finished (finish tool or no-tool-call answer) and
    # False when the step budget was exhausted.  We are in the non-aborted path here,
    # so DriveAborted is not raised; that is a different signal and not_finished is
    # deliberately left False for it (the default covers it above).  Do NOT derive
    # this from stats.step_count: max_steps bounds model *turns* while step_count
    # counts *tool calls* (a turn may issue several), so they are not comparable.
    result.not_finished = not finished

    # Summary precedence (t2, #109) — RESOLVED BEFORE the not-finished escalation
    # below, so build_continuation() sees the finalized summary (the last
    # substantive content), not an empty placeholder (Qodo #114):
    #   1. finish_summary set by the finish tool (already on result.summary via
    #      _apply_finish at line ~305 — highest priority, untouched here).
    #   2. A no-tool-call terminating turn's content (already set at the
    #      resp.content path in _drive_loop above — second priority, also already
    #      on result.summary before we reach here).
    #   3. Last substantive assistant content seen across the drive (the t2 gap:
    #      narration emitted on a tool-call turn is now recoverable).
    #   4. NO_RESULT_PRODUCED sentinel — when the model never emitted any prose.
    if not result.summary:
        result.summary = _last_sub or NO_RESULT_PRODUCED

    # Escalation seam — not-finished path (#106 t3): step budget exhausted without
    # calling finish.  Runs AFTER summary resolution (above) so the continuation
    # record carries the real output.  Best-effort and observe-only; suppress so
    # it cannot mask the drive result.
    if result.not_finished:
        with suppress(Exception):
            _escalation.escalate(result, result.stats, task.repo_path, model=model)
    return result
