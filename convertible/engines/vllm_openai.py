"""The vLLM OpenAI-compatible engine — the first real coder backend (R2).

It drives a local coding model (the reference rig: Qwen3-32B on a vLLM server at
``localhost:8001``) purely through the OpenAI ``/v1/chat/completions`` surface
with tool/function calling. Because it touches *only* that surface — and uses the
stdlib ``urllib`` rather than any vendor SDK — pointing :class:`EngineConfig` at
any OpenAI-compatible server (vLLM, llama.cpp, an OpenAI proxy) is a config
change, never a code change (honesty condition h2).

vLLM note: tool calling needs the server started with ``--enable-auto-tool-choice``
and a ``--tool-call-parser`` matching the model (e.g. ``hermes`` for many models,
``qwen3_coder`` for some Qwen3 builds). The engine is parser-agnostic — it only
needs the server to emit OpenAI-format tool calls.
"""

from __future__ import annotations

import json
import urllib.request
from typing import Any

from convertible.config import EngineConfig
from convertible.contract import Task, TaskResult
from convertible.engine import Engine
from convertible.loop import CompleteFn, ModelResponse, ToolCall, run
from convertible.tools import SCHEMAS


def _post_json(
    url: str, payload: dict[str, Any], *, api_key: str, timeout: float
) -> dict[str, Any]:
    """POST ``payload`` as JSON and parse the JSON response (OpenAI wire format).

    Isolated at module scope so tests monkeypatch it to drive the loop without a
    live server.
    """
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
    )
    with urllib.request.urlopen(
        request, timeout=timeout
    ) as response:  # nosec B310 - configured endpoint
        return json.loads(response.read().decode("utf-8"))


def _parse_response(data: dict[str, Any]) -> ModelResponse:
    """Translate an OpenAI chat-completion response into a :class:`ModelResponse`."""
    choices = data.get("choices") or [{}]
    message = choices[0].get("message", {}) if choices else {}
    calls: list[ToolCall] = []
    for raw in message.get("tool_calls") or []:
        function = raw.get("function", {})
        arguments = function.get("arguments", "{}")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments or "{}")
            except json.JSONDecodeError:
                arguments = {}
        calls.append(
            ToolCall(id=raw.get("id", ""), name=function.get("name", ""), arguments=arguments)
        )
    usage = data.get("usage") or {}
    return ModelResponse(
        content=message.get("content") or "",
        tool_calls=calls,
        prompt_tokens=int(usage.get("prompt_tokens", 0)),
        completion_tokens=int(usage.get("completion_tokens", 0)),
    )


class VllmOpenAIEngine(Engine):
    """Drives an OpenAI-compatible chat-completions endpoint with tool calling."""

    name = "vllm-openai"

    def _make_complete(self, config: EngineConfig) -> CompleteFn:
        url = f"{config.base_url.rstrip('/')}/chat/completions"

        def complete(messages: list[dict[str, Any]]) -> ModelResponse:
            payload: dict[str, Any] = {
                "model": config.model,
                "messages": messages,
                "tools": SCHEMAS,
                "tool_choice": "auto",
                "temperature": config.temperature,
            }
            data = _post_json(url, payload, api_key=config.api_key, timeout=config.timeout)
            return _parse_response(data)

        return complete

    def drive(self, task: Task, config: EngineConfig) -> TaskResult:
        return run(
            self._make_complete(config),
            task,
            max_steps=config.max_steps,
            system_prompt=self.system_prompt(task, config),
            model=config.model,
            progress=config.progress,
            spawn=config.subagent_spawn,
        )
