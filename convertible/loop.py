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
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

from convertible.contract import OK, Step, Task, TaskResult
from convertible.tools import ToolError, ToolExecutor

_DEFAULT_SYSTEM = (
    "You are a coding agent working inside a repository. Use the provided tools "
    "to inspect and edit files, then call finish with a short summary. Make the "
    "smallest change that satisfies the task."
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


def run(
    complete: CompleteFn,
    task: Task,
    *,
    max_steps: int,
    executor: ToolExecutor | None = None,
    system_prompt: str | None = None,
) -> TaskResult:
    """Drive ``complete`` against ``task`` until finish or the ``max_steps`` budget.

    ``executor`` defaults to one confined to ``task.repo_path``. Returns a uniform
    :class:`TaskResult` with the per-step trace and accumulated usage. The tool
    schemas live with each engine's ``complete`` closure, not here.
    """
    executor = executor or ToolExecutor(task.repo_path)

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

    for _ in range(max(1, max_steps)):
        resp = complete(messages)
        result.usage.add(resp.prompt_tokens, resp.completion_tokens)

        if not resp.tool_calls:
            # Model answered without requesting a tool — treat as done.
            if resp.content:
                result.summary = resp.content
            finished = True
            break

        messages.append(_assistant_message(resp))
        for call in resp.tool_calls:
            step_index = len(result.steps)
            try:
                outcome = executor.execute(call.name, call.arguments)
            except ToolError as exc:
                result.steps.append(
                    Step(step_index, call.name, call.arguments, f"error: {exc}", ok=False)
                )
                messages.append(_tool_message(call.id, f"error: {exc}"))
                continue

            result.steps.append(
                Step(step_index, call.name, call.arguments, outcome.result, ok=True)
            )
            messages.append(_tool_message(call.id, outcome.result))
            if outcome.finished:
                result.summary = outcome.finish_summary or result.summary
                finished = True
        if finished:
            break

    result.changed_files = sorted(executor.changed)
    if not finished:
        result.summary = result.summary or f"stopped at the {max_steps}-step budget"
    elif not result.summary:
        result.summary = f"completed in {len(result.steps)} step(s)"
    return result
