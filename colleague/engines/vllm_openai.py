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
import os
import sys
import urllib.error
import urllib.request
from typing import Any, Callable

from colleague.config import EngineConfig
from colleague.context import count_tokens_chars
from colleague.contract import Task, TaskResult
from colleague.engine import Engine
from colleague.loop import CompleteFn, ContextControls, ModelResponse, ToolCall, run
from colleague.tools import SCHEMAS, ToolExecutor


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
    except TimeoutError as exc:
        # A read-phase timeout (the server accepted the request but didn't answer
        # within ``timeout``) raises a bare ``TimeoutError`` — ``socket.timeout is
        # TimeoutError`` on the >=3.12 floor — which is NOT a ``URLError`` subclass,
        # so it would otherwise escape this function unwrapped as a cryptic "timed
        # out". Re-raise it legibly, keeping the phrase "timed out" so the loop's
        # request-timeout detector (``colleague.context.is_request_timeout``) matches
        # and the degradation / auto-split path fires (#154), and naming the
        # ``COLLEAGUE_TIMEOUT`` knob to raise for a big-context audit.
        raise TimeoutError(
            f"request to {url} timed out after {timeout:.0f}s — "
            f"raise COLLEAGUE_TIMEOUT for big-context audits"
        ) from exc
    except urllib.error.HTTPError as exc:
        # vLLM/OpenAI carry the actionable detail (e.g. "model `X` does not
        # exist") in the response *body*, which the bare HTTPError str() drops.
        # Re-raise the same error class with the body folded into the message so
        # a wrong-model 404 is legible instead of "HTTP Error 404: Not Found".
        detail = _read_error_body(exc)
        if not detail:
            raise
        msg = f"{exc.msg}: {detail}"
        if exc.code == 500:
            msg = (
                "the model server returned a 500 (server-side error, not a "
                "Colleague bug) — " + msg
            )
            if "EngineCore" in detail or "InternalServerError" in detail:
                msg += (
                    " — the server likely crashed on a tool-calling request "
                    "(a vLLM build that can't handle tools + "
                    "speculative-decoding/FP4 at this size is the usual cause). "
                    "Run 'colleague doctor --probe' to test tool calling, and "
                    "check the server's --enable-auto-tool-choice / "
                    "--tool-call-parser / speculative-decoding config."
                )
        raise urllib.error.HTTPError(url, exc.code, msg, exc.headers, None) from exc
    except urllib.error.URLError as exc:
        # A connection-level failure (server down/refused, DNS error, TLS) — NOT an
        # HTTP response. HTTPError is a URLError subclass, so this clause sits
        # *after* it and only sees the no-response case. Without it the loop would
        # surface a cryptic "URLError: <urlopen error [Errno 111] Connection
        # refused>"; raise a legible error that names the endpoint so a down rig or
        # a wrong --base-url is diagnosable (mirrors the graceful URLError handling
        # already in _tokenize_count).
        raise ConnectionError(
            f"vLLM endpoint unreachable at {url}: {exc.reason}. "
            f"Is the server running, and is --base-url correct?"
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
            if os.environ.get("COLLEAGUE_DUMP_REQUEST"):
                # Best-effort: a diagnostic dump must NEVER break a work item — a
                # closed/broken stderr (e.g. `2>/dev/null`, a dead pipe) raises
                # BrokenPipeError/OSError, which would otherwise abort before the
                # POST even runs (#184).
                try:
                    sys.stderr.write(
                        "colleague: outgoing request payload:\n"
                        + json.dumps(payload, indent=2)
                        + "\n"
                    )
                except OSError:  # nosec B110 - diagnostic only; never mask the real work
                    pass
            data = _post_json(url, payload, api_key=config.api_key, timeout=config.timeout)
            return _parse_response(data)

        return complete

    def make_complete(self, config: EngineConfig) -> CompleteFn:
        """Public one-shot completion seam (see :meth:`Engine.make_complete`).

        Returns the same ``complete`` the work loop uses, so non-work-loop
        features (``colleague plan``) can drive the live model directly.
        """
        return self._make_complete(config)

    def work(self, task: Task, config: EngineConfig) -> TaskResult:
        """Work the task through the shared bounded tool-loop.

        Each model turn is completed via the server's OpenAI-compatible
        ``/v1/chat/completions`` endpoint. Returns a :class:`TaskResult`.
        """
        return run(
            self._make_complete(config),
            task,
            max_steps=config.max_steps,
            system_prompt=self.system_prompt(task, config),
            model=config.model,
            progress=config.progress,
            # The engine builds the repo-confined executor so the config-derived
            # output cap (and subagent spawn) ride the existing ``executor`` seam
            # — keeps ``run()`` from growing another parameter (all-engines rule).
            executor=ToolExecutor(
                task.repo_path,
                spawn=config.subagent_spawn,
                batch_spawn=config.subagent_batch_spawn,
                max_output_chars=config.max_output_chars,
            ),
            # Context-window management (windowing + reactive auto-split #151),
            # forwarded identically by every backend (all-engines rule); dormant
            # unless a trigger fires.
            context=ContextControls(
                budget=config.context_budget_tokens,
                count_tokens=self._make_count_tokens(config),
                autosplit_target=config.autosplit_target_tokens,
                fillline_threshold=config.fillline_threshold,
                fanout_files=config.fanout_files,
                plan_offer_tokens=config.plan_offer_tokens,
                max_continue_nudges=config.max_continue_nudges,
            ),
        )
