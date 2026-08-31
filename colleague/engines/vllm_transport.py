"""vLLM/OpenAI wire transport: blocking POST, legible errors, and SSE streaming.

Split out of ``colleague/engines/vllm_openai.py`` (plan ``hard-1000-line-file-limit``,
task t9) purely to fit the repo's hard 1000-physical-line file ceiling
(``tests/test_file_length_limit.py``) — a pure move, no behavior change. This module
owns the ``urllib``-only blocking request/response plumbing, the shared legible-error
wrapping, the call-time same-role stale-pin refresh lookup, the OpenAI response
parser, and the SSE frame reader/accumulator/mid-stream-fallback machinery
(feels-alive arc, tasks t4/t5). ``colleague/engines/vllm_payload.py`` owns the
payload-shaping + tokenize-probe helpers. ``colleague/engines/vllm_openai.py`` keeps
the :class:`~colleague.engine.Engine` entry point (the pinned
``colleague.engines.vllm_openai:VllmOpenAIEngine`` import path) plus
``_stream_or_blocking`` itself, whose bare-name calls into this module's
``_post_json``/``_post_json_stream`` must stay observable to a monkeypatch applied
to ``colleague.engines.vllm_openai`` (several existing tests patch exactly that);
everything ELSE in the streaming pipeline lives here, imported back in.

Because this still touches *only* the OpenAI ``/v1/chat/completions`` surface via
the stdlib ``urllib`` — never a vendor SDK — pointing :class:`EngineConfig` at any
OpenAI-compatible server stays a config change, never a code change (honesty
condition h2, CLAUDE.md's "the vLLM adapter only touches the OpenAI surface").
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

from colleague import stallguard, streamguards
from colleague.config import EngineConfig
from colleague.loop import ModelResponse, ToolCall

# The one spelling of the wire content-type, referenced by every JSON POST
# below (chat completions and the SSE stream variant) — S1192.
_CONTENT_TYPE_JSON = "application/json"


def _post_json(
    url: str,
    payload: dict[str, Any],
    *,
    api_key: str,
    timeout: float,
    guards: Any = None,
) -> dict[str, Any]:
    """POST ``payload`` as JSON and parse the JSON response (OpenAI wire format).

    Isolated at module scope so tests monkeypatch it to drive the loop without a
    live server.

    *guards* (c12, #438): when given, the body is read through
    ``streamguards.guarded_lines`` — the SAME watchdogs the streaming reader
    gets — so a drip-feeding server on the blocking fallback trips a guard
    within its bound. ``None`` (the default) reads the body as before.
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
            # A response supporting neither read1 nor iteration (a test double
            # with only .read()) degrades to the unguarded read — guarded_lines'
            # own degrade-don't-break rule.
            readable = hasattr(response, "read1") or hasattr(response, "__iter__")
            if guards is None or not readable:
                return json.loads(response.read().decode("utf-8"))
            return json.loads(
                b"".join(streamguards.guarded_lines(response, guards)).decode("utf-8")
            )
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


def _is_model_not_found_404(exc: urllib.error.HTTPError) -> bool:
    """True for exactly the "provider explicitly reports the pinned id
    unserved" shape (h8) — an HTTP 404 whose (already legible —
    ``_raise_legible_http_error`` folds the body into ``str(exc)`` before
    this is ever reached) message carries ``model_not_found``. Any other
    404 (a genuinely wrong URL, a missing route) — or any other status
    entirely — is a real failure a refresh can't fix and must propagate
    unguarded, exactly as before this task.
    """
    return exc.code == 404 and "model_not_found" in str(exc)


def _same_role_call_time_refresh(
    config: EngineConfig, role: str, exc: urllib.error.HTTPError
) -> str | None:
    """Resolve the SAME role's currently-discovered id for a call-time
    stale-pin refresh, or ``None`` when the refresh cannot/must not fire.

    Fires ONLY when ALL of (plus the caller-side seat gate: ``complete()``
    checks ``config.refresh_seat is not None`` BEFORE calling this at all —
    the replaced-config twins disarm that field, so a deepthink/senses 404
    never reaches this function; d5/#375, flagged implicit by the arc's
    diverse review):

    - *exc* is exactly a 404 ``model_not_found`` (:func:`_is_model_not_found_404`)
      — never any other HTTP error;
    - lobes is armed (``config.lobes_gateway_url`` is not ``None`` —
      acceptance 2: "with lobes unarmed ... the original error surfaces
      unchanged");
    - a FRESH live lobes lookup (never cached — the same no-disk-cache
      convention :func:`colleague.lobes.resolve_roles` already documents;
      the gateway may have already rotated again since resolution time)
      advertises a non-blank model for *role* (acceptance 2: "the role
      advertising no model" also leaves the original error to surface);
    - that discovered id actually differs from the stale one (else there is
      nothing to refresh to — retrying identically would just repeat the
      same 404).

    *role* is NEVER substituted for a different one — "cortex" only ever
    resolves against ``roles.cortex``, "worker" only ever against
    ``roles.worker`` (never crosses roles). Emits the SAME structured
    :class:`~colleague.lobes.ModelRefreshWarning` the resolution-time rung
    does — stderr, plus appended to ``config.model_refresh_warnings`` (a NEW
    tuple assigned in place, never a shared-list mutation, so a subagent
    child holding the same config value via ``dataclasses.replace`` is never
    cross-contaminated) — for a later task (t11) to fold into the run
    artifact.
    """
    if not _is_model_not_found_404(exc):
        return None
    if config.lobes_gateway_url is None:
        return None
    # Lazy import mirrors every other lobes-consulting call site (keeps this
    # module's import graph unchanged; lets tests monkeypatch it).
    from colleague import lobes as _lobes

    roles = _lobes.resolve_roles(config.lobes_gateway_url)
    if roles is None:
        return None
    role_info = getattr(roles, role, None)
    refreshed_id = (getattr(role_info, "model", "") or "").strip()
    if not refreshed_id or refreshed_id == config.model:
        return None
    warning = _lobes.ModelRefreshWarning(
        role=role,
        stale_id=config.model,
        source="call-time-404",
        refreshed_id=refreshed_id,
        point="call",
    )
    _lobes.emit_model_refresh_warning(warning)
    config.model_refresh_warnings = config.model_refresh_warnings + (warning,)
    return refreshed_id


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
    # ``reasoning_content``. Tokens are still taken EXACTLY from ``usage`` — the
    # current rig now reports a ``completion_tokens_details.reasoning_tokens``
    # breakdown (#416), but colleague still never reads it: tokens stay exactly
    # what ``usage`` reports and reasoning is measured by length, never a
    # tokenizer estimate — this task (t3) wires the per-seat effort REQUEST
    # (``chat_template_kwargs``, see ``_build_chat_payload``) without touching
    # token accounting at all.
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
        served_model=str(data.get("model") or ""),  # t18/c49: the SERVED id
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
    response: Any, *, terminal: list[bool] | None = None, guards: Any = None
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
    trigger, see ``_post_json_stream``). *guards* (c12): see :mod:`colleague.streamguards`.
    """
    for raw_line in streamguards.guarded_lines(response, guards) if guards else response:
        # Step-stall watchdog (#400): no-op unless the loop armed a deadline.
        stallguard.check()
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
    served_model: str = ""
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
    acc.served_model = acc.served_model or str(frame.get("model") or "")  # t18/c49


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
    guards: Any = None,
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

    *guards* (c12, #438): the turn's :class:`streamguards.StreamGuards` when
    :func:`_stream_or_blocking` shares one across both paths; ``None`` builds one.
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
            if guards is None:
                guards = streamguards.StreamGuards.from_env(base_timeout=timeout)  # c12
            for frame in _iter_sse_frames(response, terminal=terminal_marker, guards=guards):
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
        served_model=acc.served_model,
    )


# ── headless streaming default (#393) ──────────────────────────────────────
#
# Streaming used to arm ONLY off ``EngineConfig.on_delta`` — a *display* seam
# that a headless ``colleague work`` never sets (``cli/_commands/work.py``'s
# ``_arm_delta_stream`` arms it for the session/cockpit sinks and nothing
# else). So every headless turn took the blocking ``urlopen``, whose
# ``read()`` returns only once the WHOLE completion has been generated —
# which quietly turned ``COLLEAGUE_TIMEOUT`` into a per-turn *generation*
# ceiling instead of a socket-idle guard (#393; observed live: 300-430s turns
# against a 600s ceiling, one task killed on its finish turn).
#
# The fix decouples the transport from the sink: streaming arms when a delta
# sink is present OR headless streaming is enabled (the default). The sink
# seam itself is untouched — an unarmed ``on_delta`` still means "nobody wants
# to see the tokens", it just no longer means "read the whole answer in one
# blocking gulp". The delta callback the transport needs in that case is the no-op below.

#: The one env opt-out. Absent (the default) = streaming armed; any falsy
#: spelling (``0``/``false``/``no``/``off``/empty, the repo-wide
#: ``colleague.config._parse_bool`` vocabulary) restores the pre-#393 blocking
#: request path byte-identically. Read at payload-build time rather than
#: resolved onto ``EngineConfig`` so the engine's serialized config shape (the
#: artifact snapshot) stays byte-identical.
_STREAM_ENV_KEY = "COLLEAGUE_STREAM"

_STREAM_DISABLING_VALUES = ("", "0", "false", "no", "off")


def _headless_streaming_enabled() -> bool:
    """Whether SSE streaming is armed for completions with no delta sink (#393).

    Default ``True``; ``COLLEAGUE_STREAM=0`` (or any other falsy spelling)
    disables it. Deliberately consulted per payload build, so an operator can
    flip the knob for a single run without rebuilding a config.
    """
    value = os.environ.get(_STREAM_ENV_KEY)
    if value is None:
        return True
    return value.strip().lower() not in _STREAM_DISABLING_VALUES


def _noop_delta(_chunk: str) -> None:
    """The delta sink a headless streamed turn feeds (#393).

    Streaming headless is a TRANSPORT decision — bytes arriving incrementally
    so the socket read timeout measures *silence* rather than total generation
    time — not a display decision. Nothing is rendering, so the chunks are
    dropped here. Keeping this separate from ``EngineConfig.on_delta`` is what
    lets ``config.on_delta is None`` keep its original meaning ("no display
    surface armed") for every consumer that reads it.
    """


# ── mid-stream failure fallback (feels-alive arc, task t5) ─────────────────
#
# A broken stream must never break a run: ``_stream_or_blocking`` is the ONLY
# call site ``_make_complete`` uses when ``on_delta`` is armed (replacing a
# bare ``_post_json_stream`` call) — pure machinery layered on top of the
# single-attempt primitive above, with no opinion about when streaming itself is armed.


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
