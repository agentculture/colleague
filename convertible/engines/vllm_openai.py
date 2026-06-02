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
import urllib.error
import urllib.request
from typing import Any, Callable

from convertible.config import EngineConfig
from convertible.context import count_tokens_chars
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
    try:
        with urllib.request.urlopen(
            request, timeout=timeout
        ) as response:  # nosec B310 - configured endpoint
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # vLLM/OpenAI carry the actionable detail (e.g. "model `X` does not
        # exist") in the response *body*, which the bare HTTPError str() drops.
        # Re-raise the same error class with the body folded into the message so
        # a wrong-model 404 is legible instead of "HTTP Error 404: Not Found".
        detail = _read_error_body(exc)
        if not detail:
            raise
        raise urllib.error.HTTPError(
            url, exc.code, f"{exc.msg}: {detail}", exc.headers, None
        ) from exc


def _read_error_body(exc: urllib.error.HTTPError) -> str:
    """Best-effort decode of an HTTPError response body (``""`` if unavailable)."""
    try:
        return exc.read().decode("utf-8", "replace").strip()
    except Exception:  # nosec B110 - body is advisory; never let decoding mask the HTTP error
        return ""


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
    # Capture the model's chain-of-thought when the server returns it as a
    # separate field (was previously discarded). Reasoning models served by vLLM
    # (e.g. Qwen3) put thinking in ``message.reasoning``; some servers use
    # ``reasoning_content``. Tokens are still taken EXACTLY from ``usage`` (this
    # server reports no completion_tokens_details, so there is no reasoning-token
    # breakdown — the loop measures reasoning by length, never estimates tokens).
    return ModelResponse(
        content=message.get("content") or "",
        tool_calls=calls,
        prompt_tokens=int(usage.get("prompt_tokens", 0)),
        completion_tokens=int(usage.get("completion_tokens", 0)),
        reasoning=message.get("reasoning") or message.get("reasoning_content") or "",
    )


def _tokenize_url(base_url: str) -> str:
    """Derive the vLLM ``/tokenize`` URL from an OpenAI-style ``base_url``.

    ``/tokenize`` is served at the *server root*, not under ``/v1`` like the chat
    surface. Strip a trailing ``/v1`` (with or without a trailing slash) to get the
    root, then append ``/tokenize`` — so ``http://host:8001/v1`` (or
    ``…/v1/``) → ``http://host:8001/tokenize``. A base_url that does not end in
    ``/v1`` just gets ``/tokenize`` appended to its stripped form.
    """
    root = base_url.rstrip("/")
    if root.endswith("/v1"):
        root = root[: -len("/v1")]
    return f"{root.rstrip('/')}/tokenize"


def _tokenize_post(
    url: str, payload: dict[str, Any], *, api_key: str, timeout: float
) -> dict[str, Any]:
    """POST ``payload`` to the vLLM ``/tokenize`` endpoint and parse the JSON reply.

    Reuses the same wire *style* as :func:`_post_json` (stdlib urllib, JSON body,
    Bearer auth) but is a SEPARATE function on purpose: the chat-completions tests
    monkeypatch ``_post_json`` with a stateful scripted mock, and the per-turn
    windowing tokenize probe must NOT consume that script. Keeping tokenize on its
    own function means a chat mock never intercepts a tokenize call (and vice
    versa); the unit tests drive this path by patching :func:`_tokenize_count`.
    """
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
    )
    with urllib.request.urlopen(  # nosec B310 - configured endpoint
        request, timeout=timeout
    ) as response:
        return json.loads(response.read().decode("utf-8"))


def _tokenize_count(
    messages: list[dict[str, Any]], *, url: str, model: str, api_key: str, timeout: float
) -> int | None:
    """Return the server's exact token count for *messages*, or ``None`` on any error.

    POSTs ``{"model", "messages"}`` to the vLLM ``/tokenize`` endpoint and reads the
    integer ``"count"`` field. Returns ``None`` for *any* failure — HTTPError
    (incl. a 404 on a server with no ``/tokenize``), URLError, timeout, JSON decode
    error, or a missing / non-int ``count`` — so the public counter can fall back to
    the char estimate. Tolerating failure is what keeps retargeting a non-vLLM
    OpenAI server a config change, not a code change.
    """
    try:
        data = _tokenize_post(
            url,
            {"model": model, "messages": messages},
            api_key=api_key,
            timeout=timeout,
        )
    except Exception:  # nosec B110 - any tokenize failure falls back to the char estimate
        return None
    count = data.get("count")
    if isinstance(count, bool) or not isinstance(count, int):
        return None
    return count


class VllmOpenAIEngine(Engine):
    """Drives an OpenAI-compatible chat-completions endpoint with tool calling."""

    name = "vllm-openai"

    def _make_count_tokens(self, config: EngineConfig) -> Callable[[list[dict[str, Any]]], int]:
        """Build the exact-or-estimate token counter the loop windows history with.

        The returned callable counts tokens for a candidate message list via the
        server's ``/tokenize`` endpoint (exact) and falls back to the zero-dep
        :func:`count_tokens_chars` estimate on any error. It ALWAYS returns an int.
        Exact when the served model exposes ``/tokenize``; char-approximate when it
        does not — so the same engine works against any OpenAI-compatible server
        with no code change (honesty condition h2).
        """
        url = _tokenize_url(config.base_url)

        def counter(messages: list[dict[str, Any]]) -> int:
            exact = _tokenize_count(
                messages,
                url=url,
                model=config.model,
                api_key=config.api_key,
                timeout=config.timeout,
            )
            return exact if exact is not None else count_tokens_chars(messages)

        return counter

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
            context_budget=config.context_budget_tokens,
            count_tokens=self._make_count_tokens(config),
        )
