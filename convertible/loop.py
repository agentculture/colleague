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
    OK,
    HookFiring,
    Step,
    Task,
    TaskResult,
)
from convertible.hooks import HookConfig, HookDecision, load_hooks, run_hook
from convertible.neighbours import NeighbourManager
from convertible.telemetry import Telemetry, load_telemetry
from convertible.tools import ToolError, ToolExecutor

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
        except Exception as exc:  # noqa: BLE001 - a hook crash is contained, not fatal
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
    """
    executor = executor or ToolExecutor(task.repo_path)
    hooks = hooks if hooks is not None else load_hooks(task.repo_path, model=model)
    # Telemetry defaults like hooks do: resolved from the environment, a no-op
    # unless explicitly enabled. Tool spans auto-nest under the drive span the
    # shared drive path opens (via the SDK's context propagation).
    telemetry = telemetry if telemetry is not None else load_telemetry()

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

    for _ in range(max(1, max_steps)):
        resp = complete(messages)
        result.usage.add(resp.prompt_tokens, resp.completion_tokens)
        telemetry.on_completion(resp.prompt_tokens, resp.completion_tokens)

        if not resp.tool_calls:
            # Model answered without requesting a tool — treat as done.
            if resp.content:
                result.summary = resp.content
            finished = True
            break

        messages.append(_assistant_message(resp))
        for call in resp.tool_calls:
            step_index = len(result.steps)

            # One span per tool-call iteration, auto-nesting under the drive
            # span. ``continue`` still runs the span's exit (so its metrics —
            # one step + one tool call — are recorded for deny/error paths too).
            with telemetry.tool_span(tool=call.name, step_index=step_index) as span:
                # pre_tool — the only control-bearing event. The first
                # deny/rewrite wins; allow/observe pass through. arguments may
                # be swapped here.
                arguments = call.arguments
                verdict = _fire_hooks(
                    hooks,
                    result,
                    event="pre_tool",
                    task=task,
                    tool=call.name,
                    arguments=arguments,
                )
                if verdict is not None and verdict.decision == DECISION_DENY:
                    # Skip execution entirely; feed the reason back so the model
                    # can adapt. Recorded as a non-ok Step (the firing is
                    # already recorded by _fire_hooks).
                    reason = verdict.reason or "denied by a pre_tool hook"
                    span.set(ok=False, denied=True, reason=reason)
                    telemetry.on_hook_denial()
                    result.steps.append(Step(step_index, call.name, arguments, reason, ok=False))
                    messages.append(_tool_message(call.id, reason))
                    continue
                if (
                    verdict is not None
                    and verdict.decision == DECISION_REWRITE
                    and verdict.arguments is not None
                ):
                    # Execute with the hook-supplied arguments instead.
                    arguments = verdict.arguments

                try:
                    outcome = executor.execute(call.name, arguments)
                except ToolError as exc:
                    span.set(ok=False, error=str(exc))
                    result.steps.append(
                        Step(step_index, call.name, arguments, f"error: {exc}", ok=False)
                    )
                    messages.append(_tool_message(call.id, f"error: {exc}"))
                    # post_tool still fires after a tool *attempt*; observe-only.
                    _fire_hooks(
                        hooks,
                        result,
                        event="post_tool",
                        task=task,
                        tool=call.name,
                        arguments=arguments,
                    )
                    continue

                span.set(ok=True, bytes=len(outcome.result), changed_file=outcome.changed_file)
                result.steps.append(Step(step_index, call.name, arguments, outcome.result, ok=True))
                messages.append(_tool_message(call.id, outcome.result))

                # post_tool — after the tool executed. Observe-only: the
                # decision does not alter the already-executed result this
                # increment.
                _fire_hooks(
                    hooks,
                    result,
                    event="post_tool",
                    task=task,
                    tool=call.name,
                    arguments=arguments,
                )

                if outcome.finished:
                    span.set(finished=True)
                    result.summary = outcome.finish_summary or result.summary
                    if outcome.destination:
                        result.destination = outcome.destination
                    if outcome.announcement:
                        result.announcement = outcome.announcement
                    finished = True
        if finished:
            break

    # finish — once, on every loop exit (model finish / empty turn / budget).
    # Observe-only this increment; requeue/re-drive is out of scope.
    _fire_hooks(hooks, result, event="finish", task=task)

    # Neighbour cleanup — runs on every loop exit, after the finish hook, so
    # no clone directory persists between drives. Safe even when no clones exist
    # (NeighbourManager.cleanup() is a no-op if the neighbours dir is absent).
    # Like clone_all above, a cleanup failure must never mask the task result.
    with suppress(Exception):
        neighbours.cleanup()

    result.changed_files = sorted(executor.changed)
    if not finished:
        result.summary = result.summary or f"stopped at the {max_steps}-step budget"
    elif not result.summary:
        result.summary = f"completed in {len(result.steps)} step(s)"
    return result
