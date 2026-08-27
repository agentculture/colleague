"""Headless SSE streaming is armed by default (#393, spec c2/c3, honesty h2/h3).

Before this task the vLLM driver streamed *only* when a display sink armed
``EngineConfig.on_delta`` (the session/cockpit seam). A headless
``colleague work`` never arms it, so every turn took the blocking
``urlopen`` whose ``read()`` returns only at full completion — making
``COLLEAGUE_TIMEOUT`` a per-turn *generation* ceiling rather than a
socket-idle guard. Observed live: 300-430s turns against a 600s ceiling, one
task killed on its finish turn.

This file pins the re-arming decision:

- **(a)** with no delta sink and no opt-out, a headless chat payload carries
  ``stream: true`` + ``stream_options.include_usage``;
- **(b)** ``COLLEAGUE_STREAM=0`` restores the blocking request path
  byte-identically (neither SSE key, and the blocking transport is what runs);
- **(c)** the arming rule is *engine-uniform* — every vllm-openai completion
  seat (acting/worker, deepthink, senses, evaluator) gets the same payload
  rule, because they all funnel through ``_build_chat_payload``;
- **(d)** a streaming **stall** still surfaces as a request timeout, so #268
  timeout survival and the #255 backpressure classifier keep working;
- **(e)** the mid-stream -> blocking same-turn fallback still fires with the
  headless (no-op) sink, so a broken stream never breaks a headless run;
- **(f)** mock and vllm-openai result shapes stay identical on all three
  paths (streaming, blocking-fallback, opt-out) — the all-engines rule.

HTTP is stubbed by monkeypatching ``urllib.request.urlopen`` (streaming) and
``vllm_openai._post_json`` (blocking), mirroring ``tests/test_vllm_stream.py``
— no socket is ever opened.
"""

from __future__ import annotations

import dataclasses
import json
import urllib.error
from pathlib import Path
from typing import Any

import pytest

from colleague import registry
from colleague.config import EngineConfig
from colleague.context import classify_degradable, is_request_timeout
from colleague.contract import OK, Task
from colleague.engines import vllm_openai
from colleague.engines.vllm_openai import VllmOpenAIEngine

# "chat_template_kwargs" joined this set in #416 t3: a default-resolved
# EngineConfig's ACTING seat (cortex/worker) is NOT "unset" — it resolves to
# "medium" via effort.SEAT_TABLE (t2's reasoning_effort_effective) — so this
# opt-out pin's key-set gains exactly that one new, orthogonal key; the
# stream/stream_options omission this test actually pins is unaffected.
_BLOCKING_PAYLOAD_KEYS = {
    "model",
    "messages",
    "temperature",
    "tools",
    "tool_choice",
    "chat_template_kwargs",
    "max_tokens",
}  # t16: the window clamp rides every payload


class _FakeStreamResponse:
    """Minimal ``http.client.HTTPResponse`` stand-in (see test_vllm_stream)."""

    def __init__(self, lines: list[bytes]) -> None:
        self._lines = lines

    def __enter__(self) -> "_FakeStreamResponse":
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False

    def __iter__(self):
        return iter(self._lines)


def _sse_lines(frames: list[dict[str, Any]], *, done: bool = True) -> list[bytes]:
    lines = [f"data: {json.dumps(frame)}\n".encode("utf-8") for frame in frames]
    if done:
        lines.append(b"data: [DONE]\n")
    return lines


def _content_frame(text: str) -> dict[str, Any]:
    return {"choices": [{"delta": {"content": text}}]}


def _fake_urlopen(lines: list[bytes], captured: dict[str, object]):
    def fake(request: object, timeout: float | None = None) -> _FakeStreamResponse:
        captured["timeout"] = timeout
        captured["payload"] = json.loads(request.data.decode("utf-8"))  # type: ignore[attr-defined]
        return _FakeStreamResponse(lines)

    return fake


def _stub_stream(monkeypatch: pytest.MonkeyPatch, captured: dict[str, object]) -> None:
    monkeypatch.setattr(
        "urllib.request.urlopen",
        _fake_urlopen(_sse_lines([_content_frame("hi")]), captured=captured),
    )


def _stub_blocking(monkeypatch: pytest.MonkeyPatch, captured: dict[str, object]) -> None:
    def fake_post(url: str, payload: dict, *, api_key: str, timeout: float) -> dict:
        captured["payload"] = payload
        return {"choices": [{"message": {"content": "hi"}}], "usage": {}}

    monkeypatch.setattr(vllm_openai, "_post_json", fake_post)


def _cfg(**overrides: Any) -> EngineConfig:
    cfg = EngineConfig.resolve(base_url="http://host:9999/v1", model="m")
    return dataclasses.replace(cfg, **overrides) if overrides else cfg


# ── (a) headless, no delta sink, no opt-out -> the SSE keys are on the wire ──


def test_headless_payload_carries_the_sse_keys_with_no_delta_sink(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#393: the bug was that this payload had NEITHER key, so the whole turn
    arrived only at completion and the socket timeout became a generation
    ceiling."""
    captured: dict[str, object] = {}
    _stub_stream(monkeypatch, captured)

    cfg = _cfg()
    assert cfg.on_delta is None  # headless: nothing armed the display seam

    complete = VllmOpenAIEngine()._make_complete(cfg, tools=[])
    resp = complete([{"role": "user", "content": "hi"}])

    payload = captured["payload"]
    assert payload["stream"] is True
    assert payload["stream_options"] == {"include_usage": True}
    assert resp.content == "hi"


def test_headless_streaming_is_the_default_with_the_env_var_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("COLLEAGUE_STREAM", raising=False)
    assert vllm_openai._headless_streaming_enabled() is True


# ── (b) COLLEAGUE_STREAM=0 restores the blocking path byte-identically ──────


def test_opt_out_restores_the_blocking_transport_and_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COLLEAGUE_STREAM", "0")
    captured: dict[str, object] = {}
    _stub_blocking(monkeypatch, captured)
    # Any attempt to stream would explode instead of silently working.
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *a, **k: pytest.fail("opt-out must never open a stream"),
    )

    complete = VllmOpenAIEngine()._make_complete(
        _cfg(), tools=[{"type": "function", "function": {"name": "x"}}]
    )
    complete([{"role": "user", "content": "hi"}])

    payload = captured["payload"]
    assert "stream" not in payload
    assert "stream_options" not in payload
    # Byte-identical key-set to the pre-#393 blocking body.
    assert set(payload.keys()) == _BLOCKING_PAYLOAD_KEYS


@pytest.mark.parametrize("value", ["0", "false", "FALSE", "no", "off", "", "  "])
def test_every_falsy_spelling_disables_headless_streaming(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("COLLEAGUE_STREAM", value)
    assert vllm_openai._headless_streaming_enabled() is False


@pytest.mark.parametrize("value", ["1", "true", "yes", "on", "anything"])
def test_every_truthy_spelling_keeps_headless_streaming_armed(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("COLLEAGUE_STREAM", value)
    assert vllm_openai._headless_streaming_enabled() is True


def test_opt_out_never_suppresses_an_explicitly_armed_delta_sink(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``COLLEAGUE_STREAM=0`` opts out of the *headless default* only — it must
    not silently kill the session/cockpit live tail, whose sink is an explicit
    caller decision (work.py ``_arm_delta_stream``)."""
    monkeypatch.setenv("COLLEAGUE_STREAM", "0")
    captured: dict[str, object] = {}
    _stub_stream(monkeypatch, captured)

    deltas: list[str] = []
    complete = VllmOpenAIEngine()._make_complete(_cfg(on_delta=deltas.append), tools=[])
    complete([{"role": "user", "content": "hi"}])

    assert captured["payload"]["stream"] is True
    assert deltas == ["hi"]


# ── (c) engine-uniform: every seat gets the same payload rule ───────────────


@pytest.mark.parametrize(
    "seat_config",
    [
        pytest.param({}, id="acting-cortex"),
        pytest.param({"worker": object()}, id="worker-three-tier"),
        # deepthink / senses / evaluator seats are `dataclasses.replace` copies
        # with a different model+base_url and refresh_seat cleared (see
        # colleague.deepthink.deepthink_engine_config /
        # colleague.senses.senses_engine_config) — all drive the SAME
        # Engine.make_complete seam with tools=[].
        pytest.param({"model": "reasoner", "refresh_seat": None}, id="deepthink-or-senses"),
    ],
)
def test_streaming_arms_uniformly_across_every_completion_seat(
    monkeypatch: pytest.MonkeyPatch, seat_config: dict[str, Any]
) -> None:
    captured: dict[str, object] = {}
    _stub_stream(monkeypatch, captured)

    engine = VllmOpenAIEngine()
    # `make_complete` is the PUBLIC seam deepthink/senses/evaluator all use.
    complete = engine.make_complete(_cfg(**seat_config), tools=[])
    complete([{"role": "user", "content": "hi"}])

    assert captured["payload"]["stream"] is True
    assert captured["payload"]["stream_options"] == {"include_usage": True}


def test_build_chat_payload_is_the_single_arming_decision() -> None:
    """The rule lives in ONE place, so no seat can drift away from it."""
    payload, streaming = VllmOpenAIEngine._build_chat_payload(_cfg(), [], [])
    assert streaming is True
    assert payload["stream"] is True


# ── (d) a streaming STALL still classifies as a request timeout (#268) ──────


def test_streaming_stall_still_classifies_as_a_request_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Streaming changes what a long turn MEANS — a long *generation* is now
    legitimate, and only a genuine stall (no bytes within the read window)
    trips the socket timeout. That stall must still reach the loop as a
    request timeout so #268 survival and #255 backpressure keep firing."""

    def stalling_urlopen(request: object, timeout: float | None = None):
        raise TimeoutError("timed out")

    monkeypatch.setattr("urllib.request.urlopen", stalling_urlopen)

    complete = VllmOpenAIEngine()._make_complete(_cfg(), tools=[])
    with pytest.raises(TimeoutError) as excinfo:
        complete([{"role": "user", "content": "hi"}])

    message = str(excinfo.value)
    assert is_request_timeout(message)
    assert classify_degradable(message) == "timeout"


def test_a_mid_stream_stall_is_not_swallowed_by_the_blocking_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A read-phase timeout is deliberately NOT fallback-eligible (it has its
    own bounded retry at the loop level) — arming streaming headless must not
    change that, or one turn could spend three full timeout windows."""

    def stalling_urlopen(request: object, timeout: float | None = None):
        raise TimeoutError("timed out")

    monkeypatch.setattr("urllib.request.urlopen", stalling_urlopen)
    monkeypatch.setattr(
        vllm_openai,
        "_post_json",
        lambda *a, **k: pytest.fail("a stall must not consume the blocking fallback"),
    )

    complete = VllmOpenAIEngine()._make_complete(_cfg(), tools=[])
    with pytest.raises(TimeoutError):
        complete([{"role": "user", "content": "hi"}])


# ── (e) the mid-stream -> blocking fallback still fires headless ────────────


def test_truncated_headless_stream_falls_back_to_one_blocking_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No terminal frame -> _StreamIncomplete -> ONE blocking POST for the same
    turn, with the SSE keys stripped. The headless no-op sink must not change
    this (it is the same `_stream_or_blocking` the armed path uses)."""
    monkeypatch.setattr(
        "urllib.request.urlopen",
        _fake_urlopen(_sse_lines([_content_frame("par")], done=False), captured={}),
    )
    blocking: dict[str, object] = {}
    _stub_blocking(monkeypatch, blocking)

    complete = VllmOpenAIEngine()._make_complete(_cfg(), tools=[])
    resp = complete([{"role": "user", "content": "hi"}])

    assert resp.content == "hi"  # the blocking answer, not the truncated stream
    assert "stream" not in blocking["payload"]
    assert "stream_options" not in blocking["payload"]


def test_a_stream_refusing_server_still_degrades_headless(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Arming streaming by DEFAULT must never make an otherwise-working
    OpenAI-compatible server unusable — the 400/422-naming-stream degrade is
    what keeps 'retarget any server' a config change (h2)."""

    def refusing_urlopen(request: object, timeout: float | None = None):
        raise urllib.error.HTTPError(
            "http://host:9999/v1/chat/completions",
            400,
            "stream is not supported",
            None,  # type: ignore[arg-type]
            None,
        )

    monkeypatch.setattr("urllib.request.urlopen", refusing_urlopen)
    blocking: dict[str, object] = {}
    _stub_blocking(monkeypatch, blocking)

    complete = VllmOpenAIEngine()._make_complete(_cfg(), tools=[])
    assert complete([{"role": "user", "content": "hi"}]).content == "hi"


# ── (f) all-engines shape parity across all three paths ────────────────────


def _script_turns() -> list[dict[str, Any]]:
    return [
        {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "1",
                                "function": {
                                    "name": "write_file",
                                    "arguments": json.dumps(
                                        {"path": "out.txt", "content": "from the model"}
                                    ),
                                },
                            }
                        ],
                    }
                }
            ],
            "usage": {"prompt_tokens": 7, "completion_tokens": 3},
        },
        {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "2",
                                "function": {
                                    "name": "finish",
                                    "arguments": json.dumps({"summary": "wrote out.txt"}),
                                },
                            }
                        ],
                    }
                }
            ],
            "usage": {"prompt_tokens": 4, "completion_tokens": 1},
        },
    ]


def _tool_call_sse(turn: dict[str, Any]) -> list[bytes]:
    """Re-express one blocking turn as the SSE frames a server would send."""
    message = turn["choices"][0]["message"]
    frames: list[dict[str, Any]] = []
    for index, call in enumerate(message.get("tool_calls") or []):
        frames.append(
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": index,
                                    "id": call["id"],
                                    "function": {
                                        "name": call["function"]["name"],
                                        "arguments": call["function"]["arguments"],
                                    },
                                }
                            ]
                        }
                    }
                ]
            }
        )
    frames.append({"choices": [{"delta": {}, "finish_reason": "tool_calls"}]})
    frames.append({"choices": [], "usage": turn["usage"]})
    return _sse_lines(frames)


def _stub_scripted_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    turns = _script_turns()
    state = {"i": 0}

    def fake(request: object, timeout: float | None = None) -> _FakeStreamResponse:
        # Only the chat surface is scripted: the driver's OTHER urllib caller
        # is the /tokenize probe (`_tokenize_post`), whose failure is a
        # sanctioned degrade to the char estimate — never a scripted turn.
        if not str(getattr(request, "full_url", "")).endswith("/chat/completions"):
            raise urllib.error.URLError("no /tokenize in this test")
        turn = turns[min(state["i"], len(turns) - 1)]
        state["i"] += 1
        return _FakeStreamResponse(_tool_call_sse(turn))

    monkeypatch.setattr("urllib.request.urlopen", fake)


def _stub_scripted_blocking(monkeypatch: pytest.MonkeyPatch) -> None:
    turns = _script_turns()
    state = {"i": 0}

    def fake_post(url: str, payload: dict, *, api_key: str, timeout: float) -> dict:
        turn = turns[min(state["i"], len(turns) - 1)]
        state["i"] += 1
        return turn

    monkeypatch.setattr(vllm_openai, "_post_json", fake_post)


def _key_shape(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _key_shape(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return _key_shape(value[0]) if value else None
    return None


@pytest.mark.parametrize("path", ["streaming", "opt-out"])
def test_mock_and_vllm_result_shapes_stay_identical_on_every_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    """The all-engines rule under #393: flipping the streaming default must not
    make mock and vllm-openai diverge in result SHAPE on any path."""
    if path == "opt-out":
        monkeypatch.setenv("COLLEAGUE_STREAM", "0")
        _stub_scripted_blocking(monkeypatch)
    else:
        _stub_scripted_stream(monkeypatch)

    cfg = EngineConfig.resolve()
    mock_repo = tmp_path / "mock"
    vllm_repo = tmp_path / "vllm"
    mock_repo.mkdir()
    vllm_repo.mkdir()

    mock_result = registry.load("mock").work(Task.new(str(mock_repo), "do work"), cfg)
    vllm_result = registry.load("vllm-openai").work(Task.new(str(vllm_repo), "do work"), cfg)

    assert mock_result.status == OK
    assert vllm_result.status == OK
    assert _key_shape(mock_result.to_dict()) == _key_shape(vllm_result.to_dict())
    assert vllm_result.changed_files


def test_streaming_and_opt_out_yield_the_same_vllm_result_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The third path pairing: a streamed run and an opted-out run of the SAME
    scripted turns produce the same result shape and the same summary."""
    streamed_repo = tmp_path / "streamed"
    blocking_repo = tmp_path / "blocking"
    streamed_repo.mkdir()
    blocking_repo.mkdir()

    with monkeypatch.context() as m:
        _stub_scripted_stream(m)
        streamed = registry.load("vllm-openai").work(
            Task.new(str(streamed_repo), "do work"), EngineConfig.resolve()
        )
    with monkeypatch.context() as m:
        m.setenv("COLLEAGUE_STREAM", "0")
        _stub_scripted_blocking(m)
        blocking = registry.load("vllm-openai").work(
            Task.new(str(blocking_repo), "do work"), EngineConfig.resolve()
        )

    assert streamed.status == blocking.status == OK
    assert _key_shape(streamed.to_dict()) == _key_shape(blocking.to_dict())
    assert streamed.summary == blocking.summary


# ── a FALSEY-but-present delta sink must still receive every delta ───────────
#
# Regression for qodo-code-review on PR #401 (comment 3746408765). The arming
# decision is `config.on_delta is not None`, so a callable whose __bool__ is
# False arms streaming — but the callback was selected with `or`, which would
# swap that very sink for the no-op and silently drop every delta. The two
# tests below pin BOTH halves of that inconsistency.


class _FalseySink:
    """A legitimate delta sink that is falsey — e.g. a collector defining
    ``__len__`` so callers can ask how much it has captured."""

    def __init__(self) -> None:
        self.chunks: list[str] = []

    def __call__(self, chunk: str) -> None:
        self.chunks.append(chunk)

    def __len__(self) -> int:  # empty collector => falsey
        return len(self.chunks)


def test_a_falsey_delta_sink_still_receives_its_deltas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = _FalseySink()
    assert not sink  # precondition: falsey while empty, yet not None
    captured: dict[str, object] = {}
    _stub_stream(monkeypatch, captured)

    cfg = _cfg(on_delta=sink)
    complete = VllmOpenAIEngine()._make_complete(cfg, tools=[])
    resp = complete([{"role": "user", "content": "hi"}])

    assert resp.content == "hi"
    # With `or`, these deltas would have gone to _noop_delta instead.
    assert "".join(sink.chunks) == "hi"


def test_the_arming_test_and_the_sink_choice_use_the_same_predicate() -> None:
    """Both must key on ``is None`` — never truthiness.

    Asserted against BEHAVIOUR, not against where the choice happens to live:
    a falsey-but-present sink is returned unchanged, and only ``None`` yields
    the no-op. The module is also checked to be free of the truthiness idiom
    so the bug cannot creep back in at any call site.
    """
    import inspect

    sink = _FalseySink()
    assert not sink  # falsey, but a real sink
    assert vllm_openai._delta_sink(sink) is sink
    assert vllm_openai._delta_sink(None) is vllm_openai._noop_delta
    assert "on_delta or _noop_delta" not in inspect.getsource(vllm_openai)
