"""The bounded agentic tool-loop (R3).

The loop is engine-agnostic: it is handed a ``complete`` callable that performs
*one* model turn (given the running message list, return the assistant's reply
and any tool calls) and drives it in a loop — executing each requested tool
against the repo via :class:`~convertible.tools.ToolExecutor`, feeding results
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
:func:`convertible.hooks.load_hooks`, so *every* engine inherits the lifecycle
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

import json
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any, Callable

from convertible.contract import (
    DECISION_DENY,
    DECISION_REWRITE,
    ERROR,
    OK,
    HookFiring,
    Step,
    Task,
    TaskResult,
)
from convertible.hooks import HookConfig, HookDecision, load_hooks, run_hook
from convertible.neighbours import NeighbourManager
from convertible.policy import Policy, load_policy
from convertible.telemetry import Telemetry, load_telemetry
from convertible.tools import ToolError, ToolExecutor, ToolOutcome

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
)


@dataclass
class ToolCall:
    """A single tool invocation requested by the model."""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class ModelResponse:
    """One model turn: free text, any tool calls, and token usage."""

    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0


# A ``complete`` performs one model turn given the running message list.
CompleteFn = Callable[[list[dict[str, Any]]], ModelResponse]

# A progress sink: (step_index, tool, target, ok) -> None. Default ``None`` in the
# loop is a strict no-op; the CLI wires one that writes a line per step to stderr
# (#38). Lives in the loop, fired per tool call, so every engine inherits it
# identically (the all-engines rule), exactly like hooks and telemetry.
ProgressFn = Callable[[int, str, str, bool], None]


class DriveAborted(Exception):
    """An engine raised mid-loop; carries the partial result (#37).

    The bounded loop catches the engine's exception, finalizes the partial
    :class:`~convertible.contract.TaskResult` (``status=error`` plus the
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
) -> HookDecision | None:
    """Run every matching hook for *event*, record a firing per hook, in order.

    Returns the first control-bearing :class:`HookDecision` (a ``deny`` or
    ``rewrite``) seen, or ``None``. Only ``pre_tool`` callers act on the return;
    for the observe-only events (``task_start`` / ``post_tool`` / ``finish``) the
    caller ignores it. ``allow`` / ``observe`` decisions are recorded but never
    control-bearing, so scanning continues past them.

    A firing is appended for *every* hook that runs — including the allow/observe
    ones leading up to a decisive one — so the dashboard sees the full sequence.
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


def _progress_target(arguments: Any) -> str:
    """A short human hint for a tool call's subject (its path / command / name)."""
    if not isinstance(arguments, dict):
        return ""
    for key in ("path", "command", "name", "summary", "subcommand"):
        value = arguments.get(key)
        if value:
            text = str(value).splitlines()[0].strip()
            return text if len(text) <= 48 else text[:45] + "..."
    return ""


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


def _drive_loop(ctx: _Drive, complete: CompleteFn, max_steps: int) -> bool:
    """Run the bounded turn loop; return whether the model finished.

    Each turn: call ``complete``, account usage, then either finish (no tool
    calls) or run the turn's tool calls. Whatever ``complete`` raises propagates
    to :func:`run`, which turns it into a preserved partial result (#37). Pulled
    out of :func:`run` so the loop body lives in one focused function and ``run``
    keeps its cognitive complexity under the threshold (SonarCloud S3776).
    """
    for _ in range(max(1, max_steps)):
        resp = complete(ctx.messages)
        ctx.result.usage.add(resp.prompt_tokens, resp.completion_tokens)
        ctx.telemetry.on_completion(resp.prompt_tokens, resp.completion_tokens)

        if not resp.tool_calls:
            # Model answered without requesting a tool — treat as done.
            if resp.content:
                ctx.result.summary = resp.content
            return True

        ctx.messages.append(_assistant_message(resp))
        # Run the turn's tool calls; a finish on any of them ends the drive once
        # the turn completes (the remaining calls in the turn still run).
        if _run_tool_calls(ctx, resp.tool_calls):
            return True
    return False


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
) -> TaskResult:
    """Drive ``complete`` against ``task`` until finish or the ``max_steps`` budget.

    ``executor`` defaults to one confined to ``task.repo_path``. ``hooks``
    defaults to the config loaded from ``task.repo_path`` (so engines that call
    :func:`run` unchanged still get the lifecycle); pass an explicit
    :class:`~convertible.hooks.HookConfig` (e.g. an empty one) to override or
    suppress repo loading. Returns a uniform :class:`TaskResult` with the
    per-step trace, accumulated usage, and every hook firing in order. The tool
    schemas live with each engine's ``complete`` closure, not here.

    ``model`` threads into per-model hook resolution: when given,
    :func:`~convertible.hooks.load_hooks` additionally loads the per-model
    overlay ``.convertible/<model>/hooks.json`` and prepends its entries ahead
    of the base entries (per-model fix takes priority). When ``None`` (the
    default) the call is identical to the base-only load — no behavior change
    for callers that do not pass a model.

    ``telemetry`` likewise defaults to :func:`~convertible.telemetry.load_telemetry`
    (a no-op unless ``CONVERTIBLE_OTEL_ENABLED`` is set). When enabled, every
    tool call becomes a ``convertible.tool.*`` span and the loop records the
    per-step metrics (steps, tokens, tool latency, hook denials). This lives in
    the loop so *every* engine inherits it (the all-engines rule), exactly like
    hook firing.

    ``progress`` is an optional per-step sink ``(step_index, tool, target, ok)``
    fired after each tool call (#38); ``None`` (the default) is a strict no-op.
    Like hooks/telemetry it is chassis-owned — every engine forwards
    ``config.progress`` so the behavior is identical across engines.

    If ``complete`` raises mid-loop (e.g. a per-request timeout), the partial
    work is *preserved*: the accumulated ``steps`` / ``usage`` / ``changed_files``
    are finalized onto the result with ``status=error`` and re-raised as
    :class:`DriveAborted` carrying that result, so the drive path can write a
    non-empty artifact + trace before surfacing the error (#37).
    """
    executor = executor or ToolExecutor(task.repo_path)
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
    finished = False

    # Neighbour clone lifecycle — chassis-owned (all-engines rule).
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
    _fire_hooks(hooks, result, event="task_start", task=task)

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
    )

    # The engine call (`complete`) may raise mid-loop. Catch it here so the
    # partial work accumulated on `result` is preserved rather than discarded
    # (#37); the finish hook + neighbour cleanup + changed_files snapshot below
    # then run on *every* exit path, including this one.
    aborted: Exception | None = None
    try:
        finished = _drive_loop(ctx, complete, max_steps)
    except Exception as exc:  # noqa: BLE001 - preserve partial work on any engine failure
        aborted = exc
        result.status = ERROR
        result.error = f"{type(exc).__name__}: {exc}"

    # finish — once, on every loop exit (model finish / empty turn / budget / error).
    # Observe-only this increment; requeue/re-drive is out of scope.
    _fire_hooks(hooks, result, event="finish", task=task)

    # Neighbour cleanup — runs on every loop exit, after the finish hook, so
    # no clone directory persists between drives. Safe even when no clones exist
    # (NeighbourManager.cleanup() is a no-op if the neighbours dir is absent).
    # Like clone_all above, a cleanup failure must never mask the task result.
    with suppress(Exception):
        neighbours.cleanup()

    result.changed_files = sorted(executor.changed)

    if aborted is not None:
        # Carry the populated partial result out via DriveAborted; the drive path
        # writes it (non-empty steps/usage/changed_files + trace) then re-surfaces
        # the failure to the operator (#37).
        result.summary = result.summary or (
            f"aborted after {len(result.steps)} step(s): {result.error}"
        )
        raise DriveAborted(result) from aborted

    if not finished:
        result.summary = result.summary or f"stopped at the {max_steps}-step budget"
    elif not result.summary:
        result.summary = f"completed in {len(result.steps)} step(s)"
    return result
