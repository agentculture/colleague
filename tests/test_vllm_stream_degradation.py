"""vLLM OpenAI driver: a broken stream never breaks a run (feels-alive, task t5).

Extends ``tests/test_vllm_stream.py`` (SSE token-streaming, task t4). That file
proves streaming *works* and that a mid-stream failure fails *legibly*; this
file proves a mid-stream failure never has to be fatal for the turn — the
engine falls back to ONE blocking (non-stream) request for the SAME turn
payload, transparently, before the loop ever sees an error.

The fallback lives in ``colleague.engines.vllm_openai._stream_or_blocking`` —
the function wired into ``_make_complete``'s ``complete()`` in place of a bare
``_post_json_stream`` call whenever ``config.on_delta`` is armed. It tries
``_post_json_stream`` first (unchanged — see test_vllm_stream.py for its own
direct-call contract) and, on a fallback-eligible failure, retries ONCE via
the SAME ``_post_json``/``_parse_response`` the unarmed path already uses.

HTTP is stubbed by monkeypatching ``urllib.request.urlopen``, mirroring the
existing convention in ``tests/test_vllm_stream.py`` — deterministic, no
threads, no ports. A read-phase TIMEOUT is deliberately excluded from the
fallback trigger set (it already has its own bounded retry at the loop level,
colleague/loop.py's ``_MAX_TIMEOUT_RETRIES`` / ``classify_degradable``) — see
``_stream_or_blocking``'s docstring for why folding it in here would let a
single turn silently spend three full ``timeout`` windows instead of two.
"""

from __future__ import annotations

import dataclasses
import http.client
import json
import urllib.error
from typing import Any

import pytest

from colleague.config import EngineConfig
from colleague.contract import OK, Task
from colleague.engines import vllm_openai
from colleague.engines.vllm_openai import VllmOpenAIEngine, _stream_or_blocking

# ── shared fixtures (mirrors tests/test_vllm_stream.py's own helpers) ──────


class _FakeStreamResponse:
    """A minimal stand-in for ``http.client.HTTPResponse`` supporting the
    ``with urlopen(...) as response: for line in response:`` shape."""

    def __init__(self, lines: list[bytes]) -> None:
        self._lines = lines

    def __enter__(self) -> "_FakeStreamResponse":
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False

    def __iter__(self):
        return iter(self._lines)


class _DyingStreamResponse:
    """Yields *lines* then raises *exc* partway through iteration — simulates
    a connection dropped mid-transfer, before any terminal frame arrives."""

    def __init__(self, lines: list[bytes], exc: BaseException) -> None:
        self._lines = lines
        self._exc = exc

    def __enter__(self) -> "_DyingStreamResponse":
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False

    def __iter__(self):
        for line in self._lines:
            yield line
        raise self._exc


class _FakeBlockingResponse:
    """A minimal stand-in for a blocking ``urlopen`` response — ``.read()``
    only, no iteration, matching what ``_post_json`` consumes."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> "_FakeBlockingResponse":
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


def _sse_lines(frames: list[dict[str, Any]], *, done: bool = True) -> list[bytes]:
    lines = [f"data: {json.dumps(frame)}\n".encode("utf-8") for frame in frames]
    if done:
        lines.append(b"data: [DONE]\n")
    return lines


def _delta_frame(*, content: str | None = None, finish_reason: str | None = None) -> dict[str, Any]:
    delta: dict[str, Any] = {}
    if content is not None:
        delta["content"] = content
    choice: dict[str, Any] = {"delta": delta}
    if finish_reason is not None:
        choice["finish_reason"] = finish_reason
    return {"choices": [choice]}


def _blocking_body(content: str, *, prompt_tokens: int = 3, completion_tokens: int = 2) -> bytes:
    return json.dumps(
        {
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
        }
    ).encode("utf-8")


# ── (a) mid-stream connection drop falls back to blocking, same turn ───────


def test_mid_stream_connection_drop_falls_back_to_blocking_within_the_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"n": 0}

    def fake_urlopen(request: Any, timeout: float | None = None) -> object:
        calls["n"] += 1
        if calls["n"] == 1:
            return _DyingStreamResponse(
                [f"data: {json.dumps(_delta_frame(content='par'))}\n".encode("utf-8")],
                http.client.IncompleteRead(b""),
            )
        return _FakeBlockingResponse(_blocking_body("blocking answer"))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    seen: list[str] = []
    resp = _stream_or_blocking(
        "http://x/v1/chat/completions",
        {"model": "m", "messages": [], "stream": True},
        api_key="EMPTY",
        timeout=5,
        on_delta=seen.append,
    )

    assert resp.content == "blocking answer"
    assert resp.prompt_tokens == 3
    assert resp.completion_tokens == 2
    assert seen == ["par"]  # deltas emitted before death are not retracted
    assert calls["n"] == 2  # exactly one stream attempt + one blocking retry


def test_mid_stream_url_error_falls_back_to_blocking_within_the_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"n": 0}

    def fake_urlopen(request: Any, timeout: float | None = None) -> object:
        calls["n"] += 1
        if calls["n"] == 1:
            return _DyingStreamResponse(
                [f"data: {json.dumps(_delta_frame(content='hel'))}\n".encode("utf-8")],
                urllib.error.URLError("connection reset by peer"),
            )
        return _FakeBlockingResponse(_blocking_body("recovered"))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    seen: list[str] = []
    resp = _stream_or_blocking(
        "http://x/v1/chat/completions",
        {"model": "m", "messages": [], "stream": True},
        api_key="EMPTY",
        timeout=5,
        on_delta=seen.append,
    )

    assert resp.content == "recovered"
    assert seen == ["hel"]
    assert calls["n"] == 2


# ── (b) malformed SSE JSON frame falls back to blocking ────────────────────


def test_malformed_json_frame_falls_back_to_blocking_within_the_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"n": 0}
    broken_lines = [b"data: {not-json}\n", b"data: [DONE]\n"]

    def fake_urlopen(request: Any, timeout: float | None = None) -> object:
        calls["n"] += 1
        if calls["n"] == 1:
            return _FakeStreamResponse(broken_lines)
        return _FakeBlockingResponse(_blocking_body("blocking after malformed frame"))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    resp = _stream_or_blocking(
        "http://x/v1/chat/completions",
        {"model": "m", "messages": [], "stream": True},
        api_key="EMPTY",
        timeout=5,
        on_delta=lambda _c: None,
    )

    assert resp.content == "blocking after malformed frame"
    assert calls["n"] == 2


# ── (c) stream ends with no [DONE] and no finish_reason: missing terminal ──


def test_stream_ending_without_done_or_finish_reason_falls_back_to_blocking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pins the exact trigger: a stream that simply runs out of lines — no
    ``[DONE]``, no frame carrying a ``finish_reason`` — is treated as
    incomplete and degrades, same as an explicit connection drop."""
    calls = {"n": 0}
    # NOT terminated: no [DONE], no finish_reason anywhere.
    incomplete_lines = _sse_lines([_delta_frame(content="cut off")], done=False)

    def fake_urlopen(request: Any, timeout: float | None = None) -> object:
        calls["n"] += 1
        if calls["n"] == 1:
            return _FakeStreamResponse(incomplete_lines)
        return _FakeBlockingResponse(_blocking_body("full answer"))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    seen: list[str] = []
    resp = _stream_or_blocking(
        "http://x/v1/chat/completions",
        {"model": "m", "messages": [], "stream": True},
        api_key="EMPTY",
        timeout=5,
        on_delta=seen.append,
    )

    assert resp.content == "full answer"
    assert seen == ["cut off"]
    assert calls["n"] == 2


def test_stream_ending_with_finish_reason_but_no_done_is_NOT_degraded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The converse of (c): a ``finish_reason`` alone (no ``[DONE]``) is a
    legitimate terminal signal some servers use — must NOT trigger a
    fallback (only one urlopen call)."""
    lines = _sse_lines(
        [_delta_frame(content="done via finish_reason", finish_reason="stop")], done=False
    )

    calls = {"n": 0}

    def fake_urlopen(request: Any, timeout: float | None = None) -> object:
        calls["n"] += 1
        return _FakeStreamResponse(lines)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    resp = _stream_or_blocking(
        "http://x/v1/chat/completions",
        {"model": "m", "messages": [], "stream": True},
        api_key="EMPTY",
        timeout=5,
        on_delta=lambda _c: None,
    )

    assert resp.content == "done via finish_reason"
    assert calls["n"] == 1  # no fallback needed — a legitimate terminal signal


# ── (d) a stream-refusing server (400/422 naming stream) falls back ────────


def test_stream_refusing_server_400_falls_back_to_blocking(monkeypatch: pytest.MonkeyPatch) -> None:
    class _ErrorBody:
        def read(self) -> bytes:
            return b'{"error":{"message":"stream_options is not supported by this model"}}'

        def close(self) -> None:
            pass

    calls = {"n": 0}

    def fake_urlopen(request: Any, timeout: float | None = None) -> object:
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.HTTPError(
                "http://x/v1/chat/completions", 400, "Bad Request", {}, _ErrorBody()
            )
        return _FakeBlockingResponse(_blocking_body("answered without streaming"))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    resp = _stream_or_blocking(
        "http://x/v1/chat/completions",
        {"model": "m", "messages": [], "stream": True, "stream_options": {"include_usage": True}},
        api_key="EMPTY",
        timeout=5,
        on_delta=lambda _c: None,
    )

    assert resp.content == "answered without streaming"
    assert calls["n"] == 2


def test_unrelated_400_error_does_not_fall_back(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 400 that has NOTHING to do with streaming (e.g. a bad request body)
    is a real failure — it must propagate, not silently retry blocking."""

    class _ErrorBody:
        def read(self) -> bytes:
            return b'{"error":{"message":"invalid temperature value"}}'

        def close(self) -> None:
            pass

    calls = {"n": 0}

    def fake_urlopen(request: Any, timeout: float | None = None) -> object:
        calls["n"] += 1
        raise urllib.error.HTTPError(
            "http://x/v1/chat/completions", 400, "Bad Request", {}, _ErrorBody()
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(urllib.error.HTTPError) as exc:
        _stream_or_blocking(
            "http://x/v1/chat/completions",
            {"model": "m", "messages": [], "stream": True},
            api_key="EMPTY",
            timeout=5,
            on_delta=lambda _c: None,
        )

    assert "temperature" in str(exc.value)
    assert calls["n"] == 1  # no blocking retry attempted for an unrelated 400


# ── (e) blocking fallback ALSO fails: original legible error propagates ────


def test_blocking_fallback_also_failing_propagates_the_legible_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"n": 0}

    def fake_urlopen(request: Any, timeout: float | None = None) -> object:
        calls["n"] += 1
        if calls["n"] == 1:
            return _DyingStreamResponse(
                [f"data: {json.dumps(_delta_frame(content='x'))}\n".encode("utf-8")],
                http.client.IncompleteRead(b""),
            )
        raise urllib.error.URLError("[Errno 111] Connection refused")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(ConnectionError) as exc:
        _stream_or_blocking(
            "http://x/v1/chat/completions",
            {"model": "m", "messages": [], "stream": True},
            api_key="EMPTY",
            timeout=5,
            on_delta=lambda _c: None,
        )

    assert "unreachable" in str(exc.value)
    assert calls["n"] == 2  # bounded: exactly one stream attempt + one blocking attempt


# ── (f) full engine.work() e2e: a mid-stream death still yields status ok ──


def test_full_loop_survives_a_mid_stream_death_status_ok_shape_unchanged(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Drives ``VllmOpenAIEngine.work`` through TWO turns where the FIRST
    turn's stream dies mid-transfer and degrades to blocking, and the SECOND
    turn streams normally — the resulting ``TaskResult`` must be exactly the
    same shape a clean run produces (status ok, correct file, correct
    summary, correct total usage, and exactly 2 counted model turns — the
    engine-internal retry must be INVISIBLE to the loop's own bookkeeping)."""
    turn_1_dying = [
        f"data: {json.dumps(_delta_frame(content='deciding'))}\n".encode("utf-8"),
    ]
    turn_1_blocking = json.dumps(
        {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "function": {
                                    "name": "write_file",
                                    "arguments": '{"path": "made.txt", "content": "by qwen"}',
                                },
                            }
                        ]
                    }
                }
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2},
        }
    ).encode("utf-8")
    turn_2_stream = _sse_lines(
        [
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call-2",
                                    "function": {
                                        "name": "finish",
                                        "arguments": '{"summary": "wrote made.txt"}',
                                    },
                                }
                            ]
                        }
                    }
                ]
            },
            {"choices": [], "usage": {"prompt_tokens": 6, "completion_tokens": 3}},
        ]
    )

    calls = {"chat": 0}

    def fake_urlopen(request: Any, timeout: float | None = None) -> object:
        if not request.full_url.endswith("/chat/completions"):
            # ContextControls.from_config's /tokenize probe shares this seam
            # (test_vllm_stream.py documents the same discrimination); a
            # simulated "endpoint absent" failure degrades to the char
            # estimate exactly as it does against a real tokenize-less server.
            raise urllib.error.URLError("no such endpoint (test double)")
        calls["chat"] += 1
        if calls["chat"] == 1:
            return _DyingStreamResponse(turn_1_dying, http.client.IncompleteRead(b""))
        if calls["chat"] == 2:
            return _FakeBlockingResponse(turn_1_blocking)
        return _FakeStreamResponse(turn_2_stream)

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
    # turn 1 (5+2, from the BLOCKING fallback, never the dead stream) + turn 2
    # (6+3) == 16 — the failed stream attempt contributes zero usage.
    assert result.usage.total_tokens == 16
    # Exactly 2 model turns counted — the engine-internal stream-then-blocking
    # retry for turn 1 is invisible to the loop's own per-turn bookkeeping.
    assert result.stats.model_turns == 2
    assert calls["chat"] == 3  # turn 1 stream (dies) + turn 1 blocking + turn 2 stream
    assert "deciding" in deltas  # the pre-death delta from turn 1 was still delivered
    assert len(deltas) > 0


# ── (g) unarmed path: zero behavior change ──────────────────────────────────


def test_unarmed_path_never_touches_the_stream_fallback_wrapper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With ``on_delta`` unarmed, ``_stream_or_blocking`` must never even be
    called — the unarmed path stays exactly ``_post_json`` + ``_parse_response``,
    the pre-t4 shape, with no stream keys and exactly one HTTP call."""

    def fail_if_called(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("_stream_or_blocking must not run when on_delta is None")

    monkeypatch.setattr(vllm_openai, "_stream_or_blocking", fail_if_called)

    calls = {"n": 0}

    def fake_post(url: str, payload: dict, *, api_key: str, timeout: float) -> dict:
        calls["n"] += 1
        assert "stream" not in payload
        assert "stream_options" not in payload
        return {"choices": [{"message": {"content": "hi"}}], "usage": {}}

    monkeypatch.setattr(vllm_openai, "_post_json", fake_post)

    engine = VllmOpenAIEngine()
    cfg = EngineConfig.resolve(base_url="http://host:9999/v1", model="m")
    assert cfg.on_delta is None
    complete = engine._make_complete(cfg, tools=[])
    resp = complete([{"role": "user", "content": "hi"}])

    assert resp.content == "hi"
    assert calls["n"] == 1
