"""vLLM OpenAI driver: SSE token-streaming feeds the delta seam (feels-alive, task t4).

``tests/test_vllm_openai.py`` covers the blocking (unarmed) request/response
path; this file covers the streaming path the engine switches to when
``EngineConfig.on_delta`` is armed — see ``colleague/config.py``'s
``on_delta`` docstring and ``tests/test_delta_seam.py`` (the mock engine's
synthetic-stream reference) for the contract this must uphold.

HTTP is stubbed by monkeypatching ``urllib.request.urlopen`` with a fake
context-manager/iterable response, mirroring the existing convention in
``tests/test_vllm_openai.py`` (``test_post_json_preserves_vllm_error_body`` et
al.) rather than opening a real socket — deterministic, no threads, no ports.
"""

from __future__ import annotations

import dataclasses
import json
import urllib.error
from typing import Any

import pytest

from colleague.config import EngineConfig
from colleague.contract import OK, Task
from colleague.engines import vllm_openai
from colleague.engines.vllm_openai import (
    VllmOpenAIEngine,
    _post_json_stream,
)


class _FakeStreamResponse:
    """A minimal stand-in for ``http.client.HTTPResponse`` supporting the
    ``with urlopen(...) as response: for line in response:`` shape the
    streaming code path relies on."""

    def __init__(self, lines: list[bytes]) -> None:
        self._lines = lines

    def __enter__(self) -> "_FakeStreamResponse":
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False

    def __iter__(self):
        return iter(self._lines)


def _sse_lines(frames: list[dict[str, Any]], *, done: bool = True) -> list[bytes]:
    """Build raw SSE wire lines (``data: {json}\\n``) for *frames*, optionally
    terminated with ``data: [DONE]``."""
    lines = [f"data: {json.dumps(frame)}\n".encode("utf-8") for frame in frames]
    if done:
        lines.append(b"data: [DONE]\n")
    return lines


def _delta_frame(
    *,
    content: str | None = None,
    reasoning: str | None = None,
    reasoning_content: str | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
    finish_reason: str | None = None,
) -> dict[str, Any]:
    delta: dict[str, Any] = {}
    if content is not None:
        delta["content"] = content
    if reasoning is not None:
        delta["reasoning"] = reasoning
    if reasoning_content is not None:
        delta["reasoning_content"] = reasoning_content
    if tool_calls is not None:
        delta["tool_calls"] = tool_calls
    choice: dict[str, Any] = {"delta": delta}
    if finish_reason is not None:
        choice["finish_reason"] = finish_reason
    return {"choices": [choice]}


def _usage_frame(prompt_tokens: int, completion_tokens: int) -> dict[str, Any]:
    return {
        "choices": [],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
    }


def _fake_urlopen(lines: list[bytes], captured: dict[str, object]):
    def fake(request: object, timeout: float | None = None) -> _FakeStreamResponse:
        captured["request"] = request
        captured["timeout"] = timeout
        captured["payload"] = json.loads(request.data.decode("utf-8"))  # type: ignore[attr-defined]
        return _FakeStreamResponse(lines)

    return fake


# ── (a) deltas arrive incrementally and in order (content + reasoning) ─────


def test_deltas_arrive_incrementally_and_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    frames = [
        _delta_frame(reasoning="thinking "),
        _delta_frame(reasoning="hard"),
        _delta_frame(content="hel"),
        _delta_frame(content="lo"),
    ]
    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen(_sse_lines(frames), captured={}))

    seen: list[str] = []
    resp = _post_json_stream(
        "http://x/v1/chat/completions",
        {"model": "m", "messages": []},
        api_key="EMPTY",
        timeout=5,
        on_delta=seen.append,
    )

    assert seen == ["thinking ", "hard", "hel", "lo"]
    assert resp.content == "hello"
    assert resp.reasoning == "thinking hard"


def test_reasoning_content_key_spelling_is_also_honored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Some servers use ``reasoning_content`` instead of ``reasoning`` — both
    spellings must feed the delta seam and assemble into ``.reasoning``."""
    frames = [_delta_frame(reasoning_content="alt spelling")]
    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen(_sse_lines(frames), captured={}))

    seen: list[str] = []
    resp = _post_json_stream(
        "http://x/v1/chat/completions",
        {"model": "m", "messages": []},
        api_key="EMPTY",
        timeout=5,
        on_delta=seen.append,
    )

    assert seen == ["alt spelling"]
    assert resp.reasoning == "alt spelling"


# ── (b) assembled response equals the blocking-path equivalent ─────────────


def test_assembled_response_matches_blocking_equivalent_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frames = [
        _delta_frame(reasoning="deciding"),
        _delta_frame(content="writing "),
        _delta_frame(content="the file"),
        _delta_frame(
            tool_calls=[
                {
                    "index": 0,
                    "id": "call-1",
                    "function": {"name": "write_file", "arguments": ""},
                }
            ]
        ),
        _delta_frame(tool_calls=[{"index": 0, "function": {"arguments": '{"path": "a"'}}]),
        _delta_frame(tool_calls=[{"index": 0, "function": {"arguments": ', "content": "b"}'}}]),
        _usage_frame(11, 4),
    ]
    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen(_sse_lines(frames), captured={}))

    resp = _post_json_stream(
        "http://x/v1/chat/completions",
        {"model": "m", "messages": []},
        api_key="EMPTY",
        timeout=5,
        on_delta=lambda _c: None,
    )

    assert resp.content == "writing the file"
    assert resp.reasoning == "deciding"
    assert len(resp.tool_calls) == 1
    call = resp.tool_calls[0]
    assert call.id == "call-1"
    assert call.name == "write_file"
    assert call.arguments == {"path": "a", "content": "b"}
    assert resp.prompt_tokens == 11
    assert resp.completion_tokens == 4


# ── (b2) finish_reason survives the SSE accumulator (plan task t1, c4/h4) ──


def test_finish_reason_reaches_the_model_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """The accumulator previously only recorded a BOOLEAN (``saw_finish_reason``)
    and dropped the actual value at stream termination — this proves the raw
    string now survives, unchanged, into ``ModelResponse.finish_reason``."""
    frames = [
        _delta_frame(content="hi"),
        _delta_frame(finish_reason="stop"),
    ]
    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen(_sse_lines(frames), captured={}))

    resp = _post_json_stream(
        "http://x/v1/chat/completions",
        {"model": "m", "messages": []},
        api_key="EMPTY",
        timeout=5,
        on_delta=lambda _c: None,
    )

    assert resp.finish_reason == "stop"


@pytest.mark.parametrize("raw", ["stop", "length", "tool_calls", "content_filter"])
def test_every_wire_finish_reason_value_survives_verbatim(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    frames = [_delta_frame(content="x"), _delta_frame(finish_reason=raw)]
    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen(_sse_lines(frames), captured={}))

    resp = _post_json_stream(
        "http://x/v1/chat/completions",
        {"model": "m", "messages": []},
        api_key="EMPTY",
        timeout=5,
        on_delta=lambda _c: None,
    )

    assert resp.finish_reason == raw


def test_no_finish_reason_frame_defaults_to_empty_string(monkeypatch: pytest.MonkeyPatch) -> None:
    """A stream that terminates via [DONE] alone (no delta ever carried a
    non-null finish_reason) degrades to the honest "" default."""
    frames = [_delta_frame(content="hi")]
    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen(_sse_lines(frames), captured={}))

    resp = _post_json_stream(
        "http://x/v1/chat/completions",
        {"model": "m", "messages": []},
        api_key="EMPTY",
        timeout=5,
        on_delta=lambda _c: None,
    )

    assert resp.finish_reason == ""


# ── (c) tool_calls accumulate correctly across fragmented chunks ───────────


def test_tool_call_arguments_accumulate_across_many_split_fragments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arg_json = json.dumps({"path": "made.txt", "content": "hello world"})
    fragments = [arg_json[i : i + 3] for i in range(0, len(arg_json), 3)]
    frames = [
        _delta_frame(
            tool_calls=[
                {"index": 0, "id": "call-abc", "function": {"name": "write_file", "arguments": ""}}
            ]
        )
    ]
    for piece in fragments:
        frames.append(_delta_frame(tool_calls=[{"index": 0, "function": {"arguments": piece}}]))
    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen(_sse_lines(frames), captured={}))

    resp = _post_json_stream(
        "http://x/v1/chat/completions",
        {"model": "m", "messages": []},
        api_key="EMPTY",
        timeout=5,
        on_delta=lambda _c: None,
    )

    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].id == "call-abc"
    assert resp.tool_calls[0].name == "write_file"
    assert resp.tool_calls[0].arguments == {"path": "made.txt", "content": "hello world"}


def test_multiple_tool_calls_accumulate_independently_by_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frames = [
        _delta_frame(
            tool_calls=[
                {"index": 0, "id": "call-0", "function": {"name": "read_file", "arguments": ""}},
                {"index": 1, "id": "call-1", "function": {"name": "list_dir", "arguments": ""}},
            ]
        ),
        _delta_frame(tool_calls=[{"index": 0, "function": {"arguments": '{"path": "a.txt"}'}}]),
        _delta_frame(tool_calls=[{"index": 1, "function": {"arguments": '{"path": "."}'}}]),
    ]
    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen(_sse_lines(frames), captured={}))

    resp = _post_json_stream(
        "http://x/v1/chat/completions",
        {"model": "m", "messages": []},
        api_key="EMPTY",
        timeout=5,
        on_delta=lambda _c: None,
    )

    assert [c.name for c in resp.tool_calls] == ["read_file", "list_dir"]
    assert resp.tool_calls[0].arguments == {"path": "a.txt"}
    assert resp.tool_calls[1].arguments == {"path": "."}


def test_malformed_accumulated_arguments_decode_to_empty_dict_not_a_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frames = [
        _delta_frame(
            tool_calls=[
                {"index": 0, "id": "call-x", "function": {"name": "finish", "arguments": "{n"}}
            ]
        )
    ]
    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen(_sse_lines(frames), captured={}))

    resp = _post_json_stream(
        "http://x/v1/chat/completions",
        {"model": "m", "messages": []},
        api_key="EMPTY",
        timeout=5,
        on_delta=lambda _c: None,
    )

    assert resp.tool_calls[0].arguments == {}


# ── (d) unarmed sends no stream keys ────────────────────────────────────────


def test_unarmed_request_body_carries_no_stream_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_post(url: str, payload: dict, *, api_key: str, timeout: float) -> dict:
        captured["payload"] = payload
        return {"choices": [{"message": {"content": "hi"}}], "usage": {}}

    monkeypatch.setattr(vllm_openai, "_post_json", fake_post)

    engine = VllmOpenAIEngine()
    cfg = EngineConfig.resolve(base_url="http://host:9999/v1", model="m")
    assert cfg.on_delta is None
    complete = engine._make_complete(cfg, tools=[])
    complete([{"role": "user", "content": "hi"}])

    payload = captured["payload"]
    assert "stream" not in payload
    assert "stream_options" not in payload


def test_unarmed_request_body_is_byte_identical_shape_to_today(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stricter pin than (d): the full outgoing payload key-set, unarmed,
    is exactly what the pre-streaming blocking path sent."""
    captured: dict[str, object] = {}

    def fake_post(url: str, payload: dict, *, api_key: str, timeout: float) -> dict:
        captured["payload"] = payload
        return {"choices": [{"message": {"content": "hi"}}], "usage": {}}

    monkeypatch.setattr(vllm_openai, "_post_json", fake_post)

    engine = VllmOpenAIEngine()
    cfg = EngineConfig.resolve(base_url="http://host:9999/v1", model="m")
    complete = engine._make_complete(cfg, tools=[{"type": "function", "function": {"name": "x"}}])
    complete([{"role": "user", "content": "hi"}])

    assert set(captured["payload"].keys()) == {
        "model",
        "messages",
        "temperature",
        "tools",
        "tool_choice",
    }


def test_armed_request_body_adds_exactly_the_two_stream_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        "urllib.request.urlopen",
        _fake_urlopen(_sse_lines([_delta_frame(content="hi")]), captured=captured),
    )

    engine = VllmOpenAIEngine()
    cfg = dataclasses.replace(
        EngineConfig.resolve(base_url="http://host:9999/v1", model="m"),
        on_delta=lambda _c: None,
    )
    complete = engine._make_complete(cfg, tools=[])
    complete([{"role": "user", "content": "hi"}])

    payload = captured["payload"]
    assert payload["stream"] is True
    assert payload["stream_options"] == {"include_usage": True}


# ── (e) a usage-less stream yields honest None/zero usage, never estimated ─


def test_usage_less_stream_yields_honest_zero_usage_not_estimated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No usage-bearing frame at all: the blocking path already treats a
    response with no ``usage`` key as 0/0 (``_parse_response``, ``usage =
    data.get("usage") or {}``) rather than ``None`` (``ModelResponse.prompt_tokens``
    /``completion_tokens`` are plain ``int`` fields, not ``Optional``) — the
    streaming path must land on that SAME honest zero, never a char-count
    estimate standing in for a real token count."""
    frames = [_delta_frame(content="no usage here")]
    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen(_sse_lines(frames), captured={}))

    resp = _post_json_stream(
        "http://x/v1/chat/completions",
        {"model": "m", "messages": []},
        api_key="EMPTY",
        timeout=5,
        on_delta=lambda _c: None,
    )

    assert resp.prompt_tokens == 0
    assert resp.completion_tokens == 0


# ── (f) [DONE] handling + trailing whitespace / keepalive lines tolerated ──


def test_done_marker_terminates_and_keepalive_comment_lines_are_tolerated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lines = [
        b": keepalive\n",
        b"\n",  # blank line
        f"data: {json.dumps(_delta_frame(content='he'))}\n".encode("utf-8"),
        b"   \n",  # whitespace-only line
        f"data: {json.dumps(_delta_frame(content='llo'))}  \n".encode("utf-8"),  # trailing ws
        b": another keepalive\n",
        b"data: [DONE]\n",
        # A frame AFTER [DONE] must never be consumed — proves iteration truly
        # stops rather than merely ignoring the terminator.
        f"data: {json.dumps(_delta_frame(content='ignored'))}\n".encode("utf-8"),
    ]
    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen(lines, captured={}))

    seen: list[str] = []
    resp = _post_json_stream(
        "http://x/v1/chat/completions",
        {"model": "m", "messages": []},
        api_key="EMPTY",
        timeout=5,
        on_delta=seen.append,
    )

    assert resp.content == "hello"
    assert seen == ["he", "llo"]


# ── errors propagate through the same family the blocking path uses ───────


def test_http_error_body_is_folded_in_legibly_same_as_blocking_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Response:
        def read(self) -> bytes:
            return b'{"error":{"message":"The model `X` does not exist."}}'

        def close(self) -> None:
            pass

    def fake_urlopen(*_args: object, **_kwargs: object) -> object:
        raise urllib.error.HTTPError(
            "http://x/v1/chat/completions", 404, "Not Found", {}, _Response()
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(urllib.error.HTTPError) as exc:
        _post_json_stream(
            "http://x/v1/chat/completions",
            {"model": "m", "messages": []},
            api_key="EMPTY",
            timeout=5,
            on_delta=lambda _c: None,
        )
    assert "X" in str(exc.value)


def test_connection_refused_becomes_legible_connection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(*_args: object, **_kwargs: object) -> object:
        raise urllib.error.URLError("[Errno 111] Connection refused")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(ConnectionError) as exc:
        _post_json_stream(
            "http://x/v1/chat/completions",
            {"model": "m", "messages": []},
            api_key="EMPTY",
            timeout=5,
            on_delta=lambda _c: None,
        )
    assert "unreachable" in str(exc.value)


def test_read_timeout_becomes_legible_timeout_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(*_args: object, **_kwargs: object) -> object:
        raise TimeoutError("timed out")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(TimeoutError) as exc:
        _post_json_stream(
            "http://x/v1/chat/completions",
            {"model": "m", "messages": []},
            api_key="EMPTY",
            timeout=5,
            on_delta=lambda _c: None,
        )
    assert "timed out" in str(exc.value)
    from colleague.context import classify_degradable

    assert classify_degradable(str(exc.value)) == "timeout"


def test_malformed_json_frame_propagates_unguarded(monkeypatch: pytest.MonkeyPatch) -> None:
    """A mid-stream malformed frame is NOT silently swallowed into an empty
    response — it must be legible, matching the blocking path's own
    unguarded ``json.loads`` on a malformed response body."""
    lines = [b"data: {not-json}\n", b"data: [DONE]\n"]
    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen(lines, captured={}))

    with pytest.raises(json.JSONDecodeError):
        _post_json_stream(
            "http://x/v1/chat/completions",
            {"model": "m", "messages": []},
            api_key="EMPTY",
            timeout=5,
            on_delta=lambda _c: None,
        )


# ── a raising on_delta sink never breaks the run ────────────────────────────


def test_raising_on_delta_sink_is_suppressed(monkeypatch: pytest.MonkeyPatch) -> None:
    frames = [_delta_frame(content="a"), _delta_frame(content="b")]
    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen(_sse_lines(frames), captured={}))

    def raising_sink(_chunk: str) -> None:
        raise RuntimeError("boom")

    resp = _post_json_stream(
        "http://x/v1/chat/completions",
        {"model": "m", "messages": []},
        api_key="EMPTY",
        timeout=5,
        on_delta=raising_sink,
    )

    assert resp.content == "ab"  # assembly is unaffected by the sink raising


# ── end-to-end: a streaming turn drives the SAME loop shape as blocking ────


def test_full_loop_over_a_streamed_turn_matches_blocking_shape(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Drives ``VllmOpenAIEngine.work`` through TWO streamed turns (write_file,
    then finish) and checks the resulting TaskResult matches the shape
    ``test_vllm_openai.py``'s ``test_drive_runs_full_loop_over_mocked_http``
    pins for the blocking path — streaming must be an invisible transport
    swap from the loop's point of view."""
    turn_1 = _sse_lines(
        [
            _delta_frame(reasoning="deciding to write"),
            _delta_frame(
                tool_calls=[
                    {
                        "index": 0,
                        "id": "call-1",
                        "function": {
                            "name": "write_file",
                            "arguments": '{"path": "made.txt", "content": "by qwen"}',
                        },
                    }
                ]
            ),
            _usage_frame(5, 2),
        ]
    )
    turn_2 = _sse_lines(
        [
            _delta_frame(
                tool_calls=[
                    {
                        "index": 0,
                        "id": "call-2",
                        "function": {
                            "name": "finish",
                            "arguments": '{"summary": "wrote made.txt"}',
                        },
                    }
                ]
            ),
            _delta_frame(finish_reason="stop"),
            _usage_frame(6, 3),
        ]
    )
    responses = [turn_1, turn_2]
    state = {"i": 0}

    def fake_urlopen(request: Any, timeout: float | None = None) -> _FakeStreamResponse:
        # ``ContextControls.from_config`` also probes the server's
        # ``/tokenize`` endpoint through this SAME ``urllib.request.urlopen``
        # seam (``_make_count_tokens``); only the ``/chat/completions`` calls
        # should consume the scripted turn list, so route anything else to a
        # simulated "endpoint absent" failure — exactly what
        # ``_tokenize_count`` already tolerates (falls back to the char
        # estimate), same as it does against a real, tokenize-less server.
        if not request.full_url.endswith("/chat/completions"):
            raise urllib.error.URLError("no such endpoint (test double)")
        lines = responses[min(state["i"], len(responses) - 1)]
        state["i"] += 1
        return _FakeStreamResponse(lines)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    deltas: list[str] = []
    task = Task.new(str(tmp_path), "write made.txt", engine="vllm-openai")
    cfg = dataclasses.replace(
        EngineConfig.resolve(base_url="http://other-host:9999/v1", model="my-model"),
        on_delta=deltas.append,
    )
    result = VllmOpenAIEngine().work(task, cfg)

    assert result.status == OK
    assert (tmp_path / "made.txt").read_text() == "by qwen"
    assert result.summary == "wrote made.txt"
    # The loop sums (prompt+completion) across BOTH turns exactly as it does
    # for the blocking path (test_vllm_openai.py's own full-loop pin):
    # turn 1 (5+2) + turn 2 (6+3) == 16.
    assert result.usage.total_tokens == 16
    assert len(deltas) > 0  # the seam really streamed something
    # Plan task t1 (c4/h4): the finishing turn's real wire finish_reason
    # ("stop") reached the artifact's per-seat finish state, end to end.
    assert result.finish_states[0].finish_reason == "stop"
    assert result.finish_states[0].state == "deliberate"
