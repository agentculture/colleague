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

import http.client
import json
import os
import sys
import urllib.error
import urllib.request
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

from colleague.config import EngineConfig
from colleague.context import count_tokens_chars
from colleague.contract import Task, TaskResult
from colleague.deepthink import make_deepthink_run
from colleague.engine import Engine
from colleague.loop import (
    CompleteFn,
    ContextControls,
    ModelResponse,
    ToolCall,
    resolve_role,
    run,
)
from colleague.senses import make_senses_run
from colleague.tools import SCHEMAS, ToolExecutor, curate_schemas, narrow_role_by_tool_set

# The one spelling of the wire content-type, referenced by every JSON POST
# below (chat completions, the SSE stream variant, and /tokenize) — S1192.
_CONTENT_TYPE_JSON = "application/json"


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
        headers={"Content-Type": _CONTENT_TYPE_JSON, "Authorization": f"Bearer {api_key}"},
    )
    try:
        with urllib.request.urlopen(
            request, timeout=timeout
        ) as response:  # nosec B310 - configured endpoint
            return json.loads(response.read().decode("utf-8"))
    except TimeoutError as exc:
        _raise_legible_timeout(url, timeout, exc)
    except urllib.error.HTTPError as exc:
        _raise_legible_http_error(url, exc)
    except urllib.error.URLError as exc:
        _raise_legible_connection_error(url, exc)


def _read_error_body(exc: urllib.error.HTTPError) -> str:
    """Best-effort decode of an HTTPError response body (``""`` if unavailable)."""
    try:
        return exc.read().decode("utf-8", "replace").strip()
    except Exception:  # nosec B110 - body is advisory; never let decoding mask the HTTP error
        return ""


# ── shared legible-error wrapping (used by both the blocking POST above and
# the streaming POST below, task t4) ───────────────────────────────────────


def _raise_legible_timeout(url: str, timeout: float, exc: BaseException) -> None:
    """Re-raise a read-phase timeout legibly (shared by blocking + streaming).

    A read-phase timeout (the server accepted the request but didn't answer
    within ``timeout``) raises a bare ``TimeoutError`` — ``socket.timeout is
    TimeoutError`` on the >=3.12 floor — which is NOT a ``URLError`` subclass,
    so it would otherwise escape unwrapped as a cryptic "timed out". Re-raise
    it legibly, keeping the phrase "timed out" so the loop's request-timeout
    detector (``colleague.context.is_request_timeout``) matches and the
    degradation / auto-split path fires (#154), and naming the
    ``COLLEAGUE_TIMEOUT`` knob to raise for a big-context audit.
    """
    raise TimeoutError(
        f"request to {url} timed out after {timeout:.0f}s — "
        f"raise COLLEAGUE_TIMEOUT for big-context audits"
    ) from exc


def _raise_legible_http_error(url: str, exc: urllib.error.HTTPError) -> None:
    """Re-raise an HTTPError with the vLLM/OpenAI body folded in (shared).

    vLLM/OpenAI carry the actionable detail (e.g. "model `X` does not
    exist") in the response *body*, which the bare HTTPError str() drops.
    Re-raise the same error class with the body folded into the message so a
    wrong-model 404 is legible instead of "HTTP Error 404: Not Found".
    """
    detail = _read_error_body(exc)
    if not detail:
        raise exc
    msg = f"{exc.msg}: {detail}"
    if exc.code == 500:
        msg = "the model server returned a 500 (server-side error, not a Colleague bug) — " + msg
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


def _raise_legible_connection_error(url: str, exc: urllib.error.URLError) -> None:
    """Re-raise a connection-level URLError with the endpoint named (shared).

    A connection-level failure (server down/refused, DNS error, TLS) — NOT an
    HTTP response. HTTPError is a URLError subclass, so callers dispatch this
    *after* their HTTPError clause and only reach it on the no-response case.
    Without it the loop would surface a cryptic "URLError: <urlopen error
    [Errno 111] Connection refused>"; raise a legible error that names the
    endpoint so a down rig or a wrong --base-url is diagnosable (mirrors the
    graceful URLError handling already in _tokenize_count).
    """
    raise ConnectionError(
        f"vLLM endpoint unreachable at {url}: {exc.reason}. "
        f"Is the server running, and is --base-url correct?"
    ) from exc


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
    # Carry the raw finish_reason out unchanged (plan task t1, covers c4/h4) —
    # previously never read on the blocking path at all. "" when the server
    # omits the field, matching every other honest-default field above.
    return ModelResponse(
        content=message.get("content") or "",
        tool_calls=calls,
        prompt_tokens=int(usage.get("prompt_tokens", 0)),
        completion_tokens=int(usage.get("completion_tokens", 0)),
        reasoning=message.get("reasoning") or message.get("reasoning_content") or "",
        finish_reason=str(choices[0].get("finish_reason") or ""),
    )


# ── SSE token-streaming (feels-alive arc, task t4) ─────────────────────────
#
# Feeds ``EngineConfig.on_delta`` (colleague/config.py) as the model answers,
# instead of only after the full completion lands. Armed only when
# ``config.on_delta is not None`` — see ``_make_complete`` below, which is the
# ONLY call site that decides blocking vs. streaming; this section is pure
# machinery with no opinion about when it runs.


def _emit_delta(on_delta: Callable[[str], None], chunk: str | None) -> None:
    """Feed *chunk* to *on_delta*, suppressing any exception it raises.

    Mirrors ``colleague.engines.mock._emit_synthetic_deltas``'s convention: a
    raising sink must never break the run. A no-op on an empty/absent chunk.
    """
    if not chunk:
        return
    with suppress(Exception):
        on_delta(chunk)


def _iter_sse_frames(
    response: Any, *, terminal: list[bool] | None = None
) -> Iterator[dict[str, Any]]:
    """Yield decoded JSON payloads from an SSE ``data: {...}`` stream.

    Iterates *response* line by line as bytes arrive (an
    ``http.client.HTTPResponse`` is iterable — no full-body buffering, so a
    caller observes a chunk the moment its line lands, not after the whole
    response has been read). Blank lines and SSE comment lines (a ``:``
    prefix — vLLM/OpenAI use these for keepalives) are tolerated and
    skipped; any other non-``data:`` field (``event:``, ``id:``, ``retry:``)
    is tolerated too, since this stream only ever needs ``data:``.
    ``data: [DONE]`` — the OpenAI/vLLM stream terminator — stops iteration
    WITHOUT yielding a frame, and nothing after it is ever read. A malformed
    ``data:`` payload's ``json.JSONDecodeError`` propagates unguarded,
    matching the blocking path's own unguarded ``json.loads`` on a malformed
    response body — a mid-stream failure must stay legible, never silently
    swallowed.

    *terminal*, when given, is a mutable one-element out-param (``terminal[0]``)
    set to ``True`` right before returning on ``data: [DONE]`` — the same
    mutable-box convention ``colleague.loop`` already uses for out-of-band
    signals (e.g. ``ctx._backpressure_state``). It is the only way a caller can
    tell "the server sent the real terminator" apart from "the connection
    simply ran out of lines" (task t5's missing-terminal-frame degradation
    trigger, see ``_post_json_stream``).
    """
    for raw_line in response:
        line = raw_line.decode("utf-8").strip()
        if not line or line.startswith(":"):
            continue
        if not line.startswith("data:"):
            continue
        payload = line[len("data:") :].strip()
        if payload == "[DONE]":
            if terminal is not None:
                terminal[0] = True
            return
        yield json.loads(payload)


def _accumulate_tool_call_fragment(
    fragments: dict[int, dict[str, str]], fragment: dict[str, Any]
) -> None:
    """Fold one incremental ``delta.tool_calls[]`` fragment into *fragments*.

    The OpenAI/vLLM streaming wire format sends a tool call's ``id`` and
    ``function.name`` ONCE — typically the fragment that introduces its
    ``index`` — then dribbles ``function.arguments`` across MANY subsequent
    fragments as a partial JSON string that must be concatenated, never
    overwritten.
    """
    index = fragment.get("index", 0)
    slot = fragments.setdefault(index, {"id": "", "name": "", "arguments": ""})
    if fragment.get("id"):
        slot["id"] = fragment["id"]
    function = fragment.get("function") or {}
    if function.get("name"):
        slot["name"] = function["name"]
    if function.get("arguments"):
        slot["arguments"] += function["arguments"]


def _decode_tool_call_arguments(arguments: str) -> dict[str, Any]:
    """Decode an accumulated streaming tool-call ``arguments`` string to a dict.

    Mirrors ``_parse_response``'s own decode rule for the blocking path: an
    empty/absent string is treated as ``"{}"``, and a malformed string decodes
    to ``{}`` rather than raising — an assembled tool call must survive a
    truncated/garbled arguments stream, the same tolerance the blocking path
    already affords a malformed response body.
    """
    try:
        return json.loads(arguments or "{}")
    except json.JSONDecodeError:
        return {}


def _finalize_tool_calls(fragments: dict[int, dict[str, str]]) -> list[ToolCall]:
    """Turn accumulated ``delta.tool_calls`` fragments into ordered ``ToolCall``\\ s.

    Ordered by ``index`` — the wire order the calls were introduced in.
    """
    return [
        ToolCall(
            id=fragments[index]["id"],
            name=fragments[index]["name"],
            arguments=_decode_tool_call_arguments(fragments[index]["arguments"]),
        )
        for index in sorted(fragments)
    ]


@dataclass
class _StreamAccumulator:
    """Mutable per-turn accumulator :func:`_post_json_stream` folds frames into.

    Extracted so the frame-handling helpers below (and the loop that calls
    them) can share this state by reference instead of ``_post_json_stream``
    threading five separate locals through nested conditionals — the sole
    purpose is keeping that function's cognitive complexity low (S3776), with
    IDENTICAL observable behavior.
    """

    content_parts: list[str] = field(default_factory=list)
    reasoning_parts: list[str] = field(default_factory=list)
    tool_call_fragments: dict[int, dict[str, str]] = field(default_factory=dict)
    usage: dict[str, Any] = field(default_factory=dict)
    saw_finish_reason: bool = False
    # The actual raw finish_reason value (plan task t1, covers c4/h4) — kept
    # alongside ``saw_finish_reason`` (which only the stream-completeness check
    # below needs) rather than replacing it, so a legitimate "" value from a
    # server is never confused with "never saw one" via truthiness.
    finish_reason: str = ""


def _emit_content_and_reasoning_deltas(
    delta: dict[str, Any], acc: _StreamAccumulator, on_delta: Callable[[str], None]
) -> None:
    """Fold one frame's ``delta`` content/reasoning chunks into *acc*, feeding
    each to *on_delta* as it arrives. Honors both ``reasoning`` and
    ``reasoning_content`` key spellings (some servers use the latter).
    """
    content_chunk = delta.get("content")
    if content_chunk:
        acc.content_parts.append(content_chunk)
        _emit_delta(on_delta, content_chunk)
    reasoning_chunk = delta.get("reasoning") or delta.get("reasoning_content")
    if reasoning_chunk:
        acc.reasoning_parts.append(reasoning_chunk)
        _emit_delta(on_delta, reasoning_chunk)


def _accumulate_frame_tool_calls(delta: dict[str, Any], acc: _StreamAccumulator) -> None:
    """Fold every ``delta.tool_calls[]`` fragment on one frame into *acc*."""
    for fragment in delta.get("tool_calls") or []:
        _accumulate_tool_call_fragment(acc.tool_call_fragments, fragment)


def _capture_frame_usage(frame: dict[str, Any], acc: _StreamAccumulator) -> None:
    """Record *frame*'s ``usage`` on *acc* verbatim when present (task t4).

    The LAST usage-bearing frame wins — a later call simply overwrites the
    previous one, matching ``stream_options.include_usage``'s convention of
    sending the final tally on the closing frame.
    """
    frame_usage = frame.get("usage")
    if frame_usage:
        acc.usage = frame_usage


def _apply_stream_frame(
    frame: dict[str, Any], acc: _StreamAccumulator, on_delta: Callable[[str], None]
) -> None:
    """Fold one decoded SSE frame into *acc* (content, reasoning, tool-call
    fragments, ``finish_reason``, and usage) — the single per-frame dispatch
    :func:`_post_json_stream`'s loop body calls, so the frame-shape branching
    lives in its own low-complexity function rather than nested inside the
    streaming loop.
    """
    choices = frame.get("choices") or []
    if choices:
        delta = choices[0].get("delta") or {}
        _emit_content_and_reasoning_deltas(delta, acc, on_delta)
        _accumulate_frame_tool_calls(delta, acc)
        raw_finish_reason = choices[0].get("finish_reason")
        if raw_finish_reason is not None:
            acc.saw_finish_reason = True
            # Carry the value out (t1) — previously only the boolean above
            # survived; the string itself was dropped at stream termination.
            acc.finish_reason = str(raw_finish_reason)
    _capture_frame_usage(frame, acc)


class _StreamIncomplete(Exception):
    """Internal sentinel (task t5): the SSE stream ended with no terminal frame.

    Raised by :func:`_post_json_stream` when the frame iterator is exhausted
    — the connection closed, no exception — WITHOUT ever observing a
    ``data: [DONE]`` terminator OR a delta carrying a non-null
    ``finish_reason``. Either signal alone is enough to call the stream
    complete (some servers omit ``[DONE]`` and rely on ``finish_reason``, or
    vice versa); missing BOTH means the connection was cut mid-answer (e.g. a
    proxy that silently closes the socket) — the exact trigger task t5 pins.

    Caught ONLY by :func:`_stream_or_blocking` to decide the one-time
    blocking fallback; a direct call to :func:`_post_json_stream` still lets
    this propagate unguarded, matching how a malformed frame's
    ``json.JSONDecodeError`` already propagates unguarded from that function.
    """


def _post_json_stream(
    url: str,
    payload: dict[str, Any],
    *,
    api_key: str,
    timeout: float,
    on_delta: Callable[[str], None],
) -> ModelResponse:
    """POST *payload* (already carrying ``stream``/``stream_options``) and
    incrementally assemble a :class:`ModelResponse` from Server-Sent Events,
    feeding each content/reasoning delta to *on_delta* as it arrives.

    Shares ``_post_json``'s own request construction and legible error
    wrapping (a read-phase timeout, an HTTPError with its body folded in, a
    connection-level URLError — see ``_raise_legible_*`` above) so a
    mid-stream failure surfaces through the SAME exception family the
    blocking path does: the loop's degradation classifier
    (``colleague.context.classify_degradable``) matches identically either
    way. A malformed ``data:`` frame's ``json.JSONDecodeError``, an
    ``http.client.IncompleteRead``, and a missing-terminal-frame
    :class:`_StreamIncomplete` all propagate unguarded too — this function
    stays a single honest attempt; deciding whether/how to recover from any
    of these is :func:`_stream_or_blocking`'s job (task t5), the function
    actually wired into the armed completion path.

    Usage is taken VERBATIM from the final usage-bearing chunk
    (``stream_options.include_usage``); if the server sends none, the usage
    fields stay at their honest zero default — exactly what the blocking path
    already does for a response with no ``usage`` key (:func:`_parse_response`,
    ``ModelResponse.prompt_tokens``/``completion_tokens`` are plain ``int``
    fields, not ``Optional``) — never an estimate.
    """
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": _CONTENT_TYPE_JSON, "Authorization": f"Bearer {api_key}"},
    )
    acc = _StreamAccumulator()
    terminal_marker: list[bool] = [False]
    try:
        with urllib.request.urlopen(
            request, timeout=timeout
        ) as response:  # nosec B310 - configured endpoint
            for frame in _iter_sse_frames(response, terminal=terminal_marker):
                _apply_stream_frame(frame, acc, on_delta)
            if not terminal_marker[0] and not acc.saw_finish_reason:
                # The connection closed cleanly (no exception) but neither
                # terminal signal ever arrived — a truncated stream, not a
                # completed one (task t5's missing-terminal-frame trigger).
                raise _StreamIncomplete(
                    "SSE stream ended without a terminal frame "
                    "([DONE] or a non-null finish_reason)"
                )
    except TimeoutError as exc:
        _raise_legible_timeout(url, timeout, exc)
    except urllib.error.HTTPError as exc:
        _raise_legible_http_error(url, exc)
    except urllib.error.URLError as exc:
        _raise_legible_connection_error(url, exc)

    return ModelResponse(
        content="".join(acc.content_parts),
        tool_calls=_finalize_tool_calls(acc.tool_call_fragments),
        prompt_tokens=int(acc.usage.get("prompt_tokens", 0)),
        completion_tokens=int(acc.usage.get("completion_tokens", 0)),
        reasoning="".join(acc.reasoning_parts),
        finish_reason=acc.finish_reason,
    )


# ── mid-stream failure fallback (feels-alive arc, task t5) ─────────────────
#
# A broken stream must never break a run: ``_stream_or_blocking`` is the ONLY
# call site ``_make_complete`` uses when ``on_delta`` is armed (replacing a
# bare ``_post_json_stream`` call) — pure machinery layered on top of the
# single-attempt primitive above, with no opinion about when streaming itself
# is armed.


def _blocking_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """*payload* with the streaming-only keys stripped (task t5 fallback).

    The fallback POSTs the SAME turn to the SAME blocking surface the unarmed
    path already uses (:func:`_post_json`) — sending ``stream: true`` there
    would make a compliant server answer with an SSE body again, which
    :func:`_parse_response`'s plain ``json.loads`` can't read.
    """
    return {k: v for k, v in payload.items() if k not in ("stream", "stream_options")}


_STREAM_UNSUPPORTED_HTTP_CODES = (400, 422)


def _is_stream_unsupported_http_error(exc: urllib.error.HTTPError) -> bool:
    """True for the 'server refuses to stream' shape (task t5).

    A 400/422 whose (already legible — see ``_raise_legible_http_error``)
    message names ``stream``/``stream_options`` is how an OpenAI-compatible
    server rejects a streaming request outright. Any OTHER status/body is a
    genuine failure — retrying blocking is unlikely to fix a real server-side
    error, so it is left to propagate exactly as it does today (no wasted
    fallback attempt).
    """
    return exc.code in _STREAM_UNSUPPORTED_HTTP_CODES and "stream" in (exc.msg or "").lower()


# The mid-stream failure shapes that ARE a *streaming*-specific problem — see
# ``_stream_or_blocking``'s docstring for why a request TIMEOUT is
# deliberately excluded from this set.
_STREAM_FALLBACK_ERRORS = (
    _StreamIncomplete,
    json.JSONDecodeError,
    http.client.IncompleteRead,
    ConnectionError,
)


def _emit_stream_fallback_notice(reason: str) -> None:
    """One legible stderr line when a stream degrades to blocking (task t5).

    Mirrors the existing ``colleague: ...`` stderr-notice convention (e.g.
    ``colleague.config._emit_lobes_unreachable_notice``) and, like the
    ``COLLEAGUE_DUMP_REQUEST`` diagnostic above, must never itself break a
    turn — swallow a broken/closed stderr (e.g. ``2>/dev/null``) rather than
    raise.
    """
    with suppress(OSError):
        print(
            f"colleague: streaming turn degraded to a blocking request ({reason}) "
            "— the turn itself is unaffected",
            file=sys.stderr,
        )


def _stream_or_blocking(
    url: str,
    payload: dict[str, Any],
    *,
    api_key: str,
    timeout: float,
    on_delta: Callable[[str], None],
) -> ModelResponse:
    """Stream one turn, falling back to ONE blocking request on a mid-stream
    failure — so a broken stream never breaks a run (task t5).

    Tries :func:`_post_json_stream` first (the SAME *payload*, still carrying
    ``stream``/``stream_options``). Any deltas already emitted via *on_delta*
    before a failure are NOT retracted — the cockpit's live tail treats a
    later event as superseding an in-flight one (t6), so a superseded partial
    stream is harmless — this function only decides whether the TURN itself
    recovers.

    Falls back to ONE blocking (non-stream) POST for the identical turn — via
    the SAME :func:`_post_json`/:func:`_parse_response` the unarmed path
    already uses, stripped of the stream keys (:func:`_blocking_payload`) —
    on exactly the failure shapes that are a *streaming*-specific problem,
    never a genuine model/server failure a retry can't fix:

      - the stream ended with no terminal frame (:class:`_StreamIncomplete`);
      - a malformed ``data:`` JSON frame (``json.JSONDecodeError``);
      - a connection drop mid-transfer (``http.client.IncompleteRead``, or the
        legible ``ConnectionError`` :func:`_raise_legible_connection_error`
        already wraps a bare ``URLError`` into — whether the drop happened at
        open or mid-transfer, the wrapped shape is the same);
      - a stream-refusing server: a 400/422 naming ``stream``/``stream_options``
        (:func:`_is_stream_unsupported_http_error`) — arming ``on_delta`` is
        display-only and must never make an otherwise-working server unusable.

    A read-phase TIMEOUT is deliberately NOT fallback-eligible here — it
    already has its own bounded retry at the loop level
    (``colleague.context.classify_degradable`` /
    ``colleague.loop._MAX_TIMEOUT_RETRIES``). Folding it into this fallback
    too would let a single turn silently spend THREE full ``timeout`` windows
    (the stream attempt, the blocking fallback, and the loop's own retry)
    instead of the documented worst case of two — and an unrelated HTTP
    error (any status/body not naming stream support) is left alone for the
    same "don't waste an attempt on a failure retrying can't fix" reason.

    Worst-case timing (documented, not enforced by a new retry loop): ONE
    stream attempt up to *timeout*, plus — only on a fallback-eligible
    failure — ONE blocking attempt reusing the SAME *timeout*. Bounded at
    2×timeout for a single turn, never more; this is the only retry this
    function performs.

    A failing blocking attempt propagates ITS OWN error unchanged (already
    legible via :func:`_post_json`'s own wrapping) — the loop's existing
    degradation path handles it exactly as it does today.
    """
    try:
        return _post_json_stream(url, payload, api_key=api_key, timeout=timeout, on_delta=on_delta)
    except urllib.error.HTTPError as exc:
        if not _is_stream_unsupported_http_error(exc):
            raise
        _emit_stream_fallback_notice(f"server rejected streaming ({exc.code}): {exc.msg}")
    except _STREAM_FALLBACK_ERRORS as exc:
        _emit_stream_fallback_notice(f"{type(exc).__name__}: {exc}")

    data = _post_json(url, _blocking_payload(payload), api_key=api_key, timeout=timeout)
    return _parse_response(data)


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
        headers={"Content-Type": _CONTENT_TYPE_JSON, "Authorization": f"Bearer {api_key}"},
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

    def _make_complete(
        self, config: EngineConfig, tools: list[dict[str, Any]] | None = None
    ) -> CompleteFn:
        url = f"{config.base_url.rstrip('/')}/chat/completions"
        # The offered tool schema: the full SCHEMAS by default, or the role-curated
        # subset (#t4) when work() resolved a role. Captured once (per-config, not
        # per-turn). make_complete()/plan mode pass no tools → full SCHEMAS.
        offered_tools = tools if tools is not None else SCHEMAS

        def complete(messages: list[dict[str, Any]]) -> ModelResponse:
            payload: dict[str, Any] = {
                "model": config.model,
                "messages": messages,
                "temperature": config.temperature,
            }
            # An EMPTY offered-tools list is the honest "tools-off" invariant (the
            # deepthink seam relies on this, colleague/deepthink.py task t2): omit
            # BOTH "tools" and "tool_choice" from the payload entirely rather than
            # sending an empty tools array, which some servers 400 on and which is
            # not honestly "no tools" anyway. ``None`` never reaches here — it was
            # already resolved to the full SCHEMAS above — so a caller that omits
            # ``tools`` (e.g. plan mode) stays byte-identical to before this change.
            if offered_tools:
                payload["tools"] = offered_tools
                payload["tool_choice"] = "auto"
            # Token-delta seam (feels-alive arc, task t4): an armed on_delta
            # switches the request to an incrementally-consumed SSE stream, so
            # each content/reasoning chunk reaches the sink as it arrives
            # instead of only after the full completion lands (the served
            # Qwen spends its long silent time in reasoning — this is the
            # silence the seam fixes). Unarmed (``config.on_delta is None``,
            # the default) adds NEITHER key — byte-identical to the
            # pre-streaming request body.
            streaming = config.on_delta is not None
            if streaming:
                payload["stream"] = True
                payload["stream_options"] = {"include_usage": True}
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
            if streaming:
                # A mid-stream failure degrades to ONE blocking request for
                # THIS SAME turn (task t5) — the loop never sees the
                # transport hiccup, only a normal ModelResponse.
                return _stream_or_blocking(
                    url,
                    payload,
                    api_key=config.api_key,
                    timeout=config.timeout,
                    on_delta=config.on_delta,
                )
            data = _post_json(url, payload, api_key=config.api_key, timeout=config.timeout)
            return _parse_response(data)

        return complete

    def make_complete(
        self, config: EngineConfig, tools: list[dict[str, Any]] | None = None
    ) -> CompleteFn:
        """Public one-shot completion seam (see :meth:`Engine.make_complete`).

        Returns the same ``complete`` the work loop uses, so non-work-loop
        features (``colleague plan``, the deepthink escalation seam) can drive
        a live model directly. ``tools=None`` (the default) sends the full
        SCHEMAS — byte-identical to today, the plan-mode pin; ``tools=[]`` is
        the tools-off invariant the deepthink seam relies on (see
        :meth:`Engine.make_complete`).
        """
        return self._make_complete(config, tools=tools)

    def make_count_tokens(self, config: EngineConfig) -> Callable[[list[dict[str, Any]]], int]:
        """Public one-shot token-counter seam (see :meth:`Engine.make_count_tokens`).

        Returns the same exact-or-estimate counter the work loop uses
        internally — the server's ``/tokenize`` endpoint, degrading to the
        char-heuristic estimate on any error — so a feature calling
        :meth:`make_complete` outside the loop (the deepthink seam, task t2)
        windows its prompt with the loop's own precision.
        """
        return self._make_count_tokens(config)

    def work(self, task: Task, config: EngineConfig) -> TaskResult:
        """Work the task through the shared bounded tool-loop.

        Each model turn is completed via the server's OpenAI-compatible
        ``/v1/chat/completions`` endpoint. Returns a :class:`TaskResult`.
        """
        # Typed-subagent role (#t4): resolve config.role once and build the child's
        # curated tool schema + role-aware executor from it. None → full-surface
        # SCHEMAS + an unrestricted executor (byte-identical to the pre-role path).
        # The role PROMPT is composed by the role-aware self.system_prompt below.
        role = resolve_role(config, task.repo_path)
        # Dual-model deepthink (t5): ONE binding per work item, injected into BOTH
        # the executor (the model-facing tool) and the ContextControls (the
        # runtime escalation points) — None for a single-model config, which also
        # keeps the deepthink tool schema un-offered (byte-identical run).
        dt_run = make_deepthink_run(config, self.name)
        # Cortex/senses media bridge (t6): the SAME binding every backend passes to
        # ContextControls (all-engines rule); ``None`` for a config without senses
        # keeps the senses bridge dormant (byte-identical).
        senses_run = make_senses_run(config, self.name)
        # Change-content consumption lane (t3, spec c8/h8): an applied
        # worker.tools narrowing on the attached config-lifecycle intersects the
        # role-curated surface. Read the attachment's snapshot DEFENSIVELY — the
        # real EpisodeConfigLifecycle exposes ``snapshot`` as a read-only
        # property (already-evaluated, not callable), while a future frozen
        # child view (r2/t10) may expose a ``snapshot()`` METHOD instead — so
        # this neither assumes nor requires either shape. No lifecycle, or a
        # snapshot with the default/empty ``tool_set`` (c26: () means
        # not-narrowed), leaves ``role`` untouched: byte-identical to today.
        lifecycle = getattr(config, "config_lifecycle", None)
        tool_set: tuple[str, ...] = ()
        if lifecycle is not None:
            snapshot_attr = getattr(lifecycle, "snapshot", None)
            snapshot = snapshot_attr() if callable(snapshot_attr) else snapshot_attr
            tool_set = getattr(snapshot, "tool_set", ()) or ()
        role = narrow_role_by_tool_set(role, tool_set)
        offered_tools = curate_schemas(role, deepthink=dt_run is not None)
        return run(
            self._make_complete(config, tools=offered_tools),
            task,
            max_steps=config.max_steps,
            system_prompt=self.system_prompt(task, config),
            model=config.model,
            progress=config.progress,
            # The engine builds the repo-confined executor so the config-derived
            # output cap (and subagent spawn) ride the existing ``executor`` seam
            # — keeps ``run()`` from growing another parameter (all-engines rule).
            # ``allowlist=role`` makes the executor REFUSE any tool the role
            # withholds — ``role`` here is already tool_set-narrowed above, so
            # this is the SAME single allowlist seam a narrowed-away tool is
            # refused through, never a second refusal mechanism.
            executor=ToolExecutor(
                task.repo_path,
                spawn=config.subagent_spawn,
                batch_spawn=config.subagent_batch_spawn,
                max_output_chars=config.max_output_chars,
                allowlist=role,
                deepthink=dt_run,
            ),
            # Context-window management (windowing + reactive auto-split #151),
            # forwarded identically by every backend (all-engines rule); dormant
            # unless a trigger fires.
            # ``from_config`` is the single source for the config→controls forwarding
            # both backends share (all-engines rule); the vLLM backend's one
            # per-backend variation is its exact ``/tokenize`` counter.
            context=ContextControls.from_config(
                config,
                count_tokens=self._make_count_tokens(config),
                deepthink_run=dt_run,
                senses_run=senses_run,
            ),
        )
