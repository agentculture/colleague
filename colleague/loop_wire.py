"""The engine-facing wire types the loop exchanges with a backend.

``ToolCall`` / ``ModelResponse`` / ``CompleteFn`` / ``WorkAborted`` plus the three
message builders. Extracted from ``colleague/loop.py`` (plan
hard-1000-line-file-limit, t15) as a leaf; re-exported from ``colleague.loop``
so every engine's ``from colleague.loop import ModelResponse, ToolCall`` is
unchanged. A pure move.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

from colleague.contract import TaskResult


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
    to a file, so the loop measures it as the "thought" portion of a work item
    (char/byte lengths in :class:`~colleague.contract.WorkStats`). Empty for
    servers/models that do not emit a reasoning field.

    ``finish_reason`` is the raw backend-reported reason THIS turn's completion
    ended (OpenAI-compatible ``choices[0].finish_reason``, e.g. ``"stop"`` /
    ``"tool_calls"`` / ``"length"`` / ``"content_filter"``), carried out of the
    vLLM adapter's blocking AND streaming paths unchanged (t1, c4/h4); ``""``
    for an engine that never reports it. :mod:`colleague.finishstate` reads the
    LAST turn's value via a private tracking cell, never re-derived from content.
    ``served_model`` is the id the reply itself named (t18/c49; ``""`` when absent).
    """

    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning: str = ""
    finish_reason: str = ""
    served_model: str = ""


# A ``complete`` performs one model turn given the running message list.
CompleteFn = Callable[[list[dict[str, Any]]], ModelResponse]


class WorkAborted(Exception):
    """An engine raised mid-loop; carries the partial result (#37).

    The bounded loop catches the engine's exception, finalizes the partial
    :class:`~colleague.contract.TaskResult` (``status=error`` plus the
    ``steps`` / ``usage`` / ``changed_files`` accumulated so far) and raises this
    so the shared work path can persist that partial artifact + non-empty trace
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
