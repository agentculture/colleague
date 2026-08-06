"""Tests for streamed senses completions (plan task t2, covers c2/h2).

Surfaces under test:

1. :func:`colleague.senses.senses_engine_config` no longer silently inherits
   the PARENT config's ``on_delta`` — a senses call streams only when the
   caller explicitly arms it via the new ``on_delta`` keyword.
2. :func:`colleague.senses.make_senses_display_delta` — the senses-side
   streaming adapter: a raw per-chunk ``on_delta`` callback that decodes a
   streamed JSON-move envelope (:mod:`colleague.senses_stream`, task t1)
   incrementally, forwarding display text to a caller-supplied sink; never
   raises into the engine's read loop, and stops forwarding cleanly once the
   stream is judged hopeless (a malformed or non-envelope reply).
3. End to end, against REAL local HTTP servers (one SSE-streaming, one
   blocking — mirrors ``tests/test_vllm_stream_timeout_reset.py``'s real-
   socket harness, never ``io.StringIO``): a senses turn run streamed
   delivers a final result byte-identical to the blocking path on the same
   transcript, with the SAME token usage, while the display-delta callback
   observes the text incrementally when the reply actually carries a
   ``"text"`` field (the coordination loop's ``reply_to_operator`` move shape
   — the exact envelope :mod:`colleague.senses_stream` was built to decode).
   ``run_senses_talk`` (whose reply carries ``"answer"``, not ``"text"``) and
   ``run_senses_speakback`` (whose reply is plain text, no JSON at all) are
   exercised too: both still agree byte-for-byte streamed vs. blocking, and
   the extractor is proven to decline cleanly (zero deltas, no exception)
   rather than mis-render prose it was never built to parse.
"""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Iterator

from colleague.config import EngineConfig, SensesConfig
from colleague.engines.vllm_openai import VllmOpenAIEngine
from colleague.senses import (
    make_senses_display_delta,
    run_senses_speakback,
    run_senses_talk,
    senses_engine_config,
)

# ---------------------------------------------------------------------------
# Real-socket harness (mirrors tests/test_vllm_stream_timeout_reset.py) — a
# genuine http.server thread per side, never a faked/monkeypatched transport.
# ---------------------------------------------------------------------------


def _sse_frame(payload: dict) -> bytes:
    return f"data: {json.dumps(payload)}\n\n".encode("utf-8")


def _make_streaming_handler(chunks: "list[str]", usage: dict) -> type:
    """A handler answering every POST with *chunks* as SSE content deltas,
    then a final usage frame and ``[DONE]`` — regardless of request path, so
    the SAME server also safely answers the engine's ``/tokenize`` probe
    (rejected as non-JSON there, which degrades to the char estimate)."""

    class _StreamingHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def log_message(self, fmt: str, *args: object) -> None:  # silence test noise
            pass

        def do_POST(self) -> None:  # noqa: N802 - stdlib handler naming
            length = int(self.headers.get("Content-Length", 0))
            self.rfile.read(length)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for chunk in chunks:
                self.wfile.write(_sse_frame({"choices": [{"delta": {"content": chunk}}]}))
                self.wfile.flush()
            self.wfile.write(_sse_frame({"choices": [], "usage": usage}))
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()

    return _StreamingHandler


def _make_blocking_handler(full_text: str, usage: dict) -> type:
    """A handler answering every POST as ONE blocking JSON completion body."""

    class _BlockingHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def log_message(self, fmt: str, *args: object) -> None:  # silence test noise
            pass

        def do_POST(self) -> None:  # noqa: N802 - stdlib handler naming
            length = int(self.headers.get("Content-Length", 0))
            self.rfile.read(length)
            body = json.dumps(
                {"choices": [{"message": {"content": full_text}}], "usage": usage}
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return _BlockingHandler


@contextmanager
def _serve(handler_cls: type) -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/v1"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


# ---------------------------------------------------------------------------
# senses_engine_config — no longer silently inherits the parent's on_delta
# ---------------------------------------------------------------------------


def _config_with_senses(**overrides: Any) -> EngineConfig:
    defaults: dict[str, Any] = dict(
        senses=SensesConfig(
            model="senses-model",
            base_url="http://senses:8003/v1",
            api_key="senses-key",
            context_budget=32768,
        )
    )
    defaults.update(overrides)
    return EngineConfig(**defaults)


class TestSensesEngineConfigOnDelta:
    def test_clears_inherited_on_delta_by_default(self) -> None:
        parent = _config_with_senses(on_delta=lambda chunk: None)

        sc = senses_engine_config(parent)

        assert sc is not None
        assert sc.on_delta is None

    def test_arms_an_explicit_on_delta(self) -> None:
        parent = _config_with_senses(on_delta=lambda chunk: None)
        senses_deltas: "list[str]" = []
        sink = senses_deltas.append

        sc = senses_engine_config(parent, on_delta=sink)

        assert sc is not None
        assert sc.on_delta is sink
        assert sc.on_delta is not parent.on_delta

    def test_no_senses_declared_still_returns_none_with_on_delta_kw(self) -> None:
        assert senses_engine_config(EngineConfig(), on_delta=lambda chunk: None) is None

    def test_unrelated_knobs_still_inherit_unchanged(self) -> None:
        """Byte-identical regression guard: only ``on_delta`` changed behavior."""
        parent = _config_with_senses(max_steps=99, timeout=42.0)

        sc = senses_engine_config(parent)

        assert sc is not None
        assert sc.max_steps == 99
        assert sc.timeout == 42.0


# ---------------------------------------------------------------------------
# make_senses_display_delta — the streaming adapter, no network
# ---------------------------------------------------------------------------

#: The exact JSON-move-envelope shape colleague/senses_stream.py (t1) targets
#: — a ``reply_to_operator`` move, chunked across an SSE stream boundary the
#: way a live model actually splits it (mirrors tests/test_senses_stream.py's
#: own live-probed chunk sequence, with different content).
_ENVELOPE_CHUNKS = [
    "```",
    "json\n",
    '{"move": "reply_to_operator", "text": "',
    "Tests are green",
    " now.",
    '"}',
    "\n```",
]
_ENVELOPE_FULL = "".join(_ENVELOPE_CHUNKS)
_EXPECTED_DISPLAY_TEXT = "Tests are green now."
_USAGE = {"prompt_tokens": 11, "completion_tokens": 13}


class TestMakeSensesDisplayDelta:
    def test_forwards_incremental_display_deltas_from_the_text_field(self) -> None:
        deltas: "list[str]" = []
        on_delta = make_senses_display_delta(deltas.append)

        for chunk in _ENVELOPE_CHUNKS:
            on_delta(chunk)

        # AC3: at least two incremental deltas were observed, and their
        # concatenation is exactly the envelope's "text" field value — fence
        # markers, braces, keys, and the closing quote/brace/fence withheld.
        assert len(deltas) >= 2
        assert "".join(deltas) == _EXPECTED_DISPLAY_TEXT

    def test_stops_forwarding_after_a_non_envelope_reply_without_raising(self) -> None:
        """A plain-text reply (no JSON at all, like run_senses_speakback's) is
        not an envelope — EnvelopeStream fails on the very first character,
        and the adapter must stop cleanly, never raise into the caller."""
        deltas: "list[str]" = []
        on_delta = make_senses_display_delta(deltas.append)

        for chunk in ["The build ", "is green ", "and all tests pass."]:
            on_delta(chunk)  # must not raise

        assert deltas == []

    def test_swallows_a_raising_display_delta_sink(self) -> None:
        def _boom(_: str) -> None:
            raise RuntimeError("a rendering sink blew up")

        on_delta = make_senses_display_delta(_boom)

        for chunk in _ENVELOPE_CHUNKS:
            on_delta(chunk)  # must not raise despite the sink always raising

    def test_a_fresh_adapter_per_completion_does_not_leak_state(self) -> None:
        """Two independent adapters (as :func:`senses_engine_config` builds
        fresh per call) never share EnvelopeStream state."""
        first: "list[str]" = []
        second: "list[str]" = []
        on_delta_a = make_senses_display_delta(first.append)
        on_delta_b = make_senses_display_delta(second.append)

        for chunk in _ENVELOPE_CHUNKS:
            on_delta_a(chunk)
        for chunk in _ENVELOPE_CHUNKS:
            on_delta_b(chunk)

        assert "".join(first) == "".join(second) == _EXPECTED_DISPLAY_TEXT


# ---------------------------------------------------------------------------
# End to end: streamed vs. blocking, real sockets
# ---------------------------------------------------------------------------


class TestStreamedSensesReplyMatchesBlocking:
    """A senses reply riding the coordination loop's JSON-move envelope, run
    streamed (``on_delta`` armed via :func:`make_senses_display_delta`)
    through the engine's EXISTING streamed-vs-blocking decision point
    (``VllmOpenAIEngine._make_complete``, unchanged by this task), delivers
    the SAME final content and token usage as running it blocking — while the
    display-delta callback observes the text incrementally (AC1 + AC3)."""

    def test_streamed_and_blocking_agree_and_stream_yields_live_deltas(self) -> None:
        engine = VllmOpenAIEngine()
        display_deltas: "list[str]" = []

        with _serve(_make_streaming_handler(_ENVELOPE_CHUNKS, _USAGE)) as stream_url:
            on_delta = make_senses_display_delta(display_deltas.append)
            streamed_config = EngineConfig(
                base_url=stream_url, model="senses-model", on_delta=on_delta
            )
            streamed = engine._make_complete(streamed_config, tools=[])(
                [{"role": "user", "content": "status?"}]
            )

        with _serve(_make_blocking_handler(_ENVELOPE_FULL, _USAGE)) as block_url:
            blocking_config = EngineConfig(base_url=block_url, model="senses-model")
            blocking = engine._make_complete(blocking_config, tools=[])(
                [{"role": "user", "content": "status?"}]
            )

        # AC1: byte-identical final text, streamed vs. blocking.
        assert streamed.content == _ENVELOPE_FULL
        assert streamed.content == blocking.content
        # AC3: usage/token accounting identical both paths — taken verbatim
        # from the server, never estimated.
        assert streamed.prompt_tokens == blocking.prompt_tokens == _USAGE["prompt_tokens"]
        assert (
            streamed.completion_tokens == blocking.completion_tokens == _USAGE["completion_tokens"]
        )
        # AC3: the display-delta callback saw >= 2 incremental deltas.
        assert len(display_deltas) >= 2
        assert "".join(display_deltas) == _EXPECTED_DISPLAY_TEXT


_TALK_JSON = json.dumps(
    {
        "answer": "cortex is currently editing colleague/config.py.",
        "relay": False,
        "relay_text": "",
    }
)
_TALK_CHUNKS = [_TALK_JSON[:20], _TALK_JSON[20:45], _TALK_JSON[45:]]


class TestStreamedRunSensesTalkMatchesBlocking:
    """``run_senses_talk``'s reply carries ``"answer"``, not ``"text"`` — the
    extractor forwards no display deltas for it (nothing to decline: it is a
    syntactically valid JSON object, just without the one key the extractor
    targets), but arming ``on_delta`` must still leave the final result
    byte-identical to the blocking path (AC1 + the usage half of AC3)."""

    def test_final_answer_and_tokens_identical_streamed_vs_blocking(self) -> None:
        engine = VllmOpenAIEngine()
        display_deltas: "list[str]" = []

        with _serve(_make_streaming_handler(_TALK_CHUNKS, _USAGE)) as stream_url:
            senses_stub = SensesConfig(
                model="senses-model", base_url=stream_url, api_key="k", context_budget=100000
            )
            on_delta = make_senses_display_delta(display_deltas.append)
            streaming_config = senses_engine_config(
                EngineConfig(senses=senses_stub), on_delta=on_delta
            )
            streamed = run_senses_talk(
                "what's cortex doing?",
                feed_tail="",
                packet=None,
                task_state=None,
                senses_config=streaming_config,
                make_complete=engine.make_complete,
            )

        with _serve(_make_blocking_handler(_TALK_JSON, _USAGE)) as block_url:
            block_stub = SensesConfig(
                model="senses-model", base_url=block_url, api_key="k", context_budget=100000
            )
            blocking_config = senses_engine_config(EngineConfig(senses=block_stub))
            blocking = run_senses_talk(
                "what's cortex doing?",
                feed_tail="",
                packet=None,
                task_state=None,
                senses_config=blocking_config,
                make_complete=engine.make_complete,
            )

        assert streamed is not None and blocking is not None
        assert streamed["degraded"] is False
        assert blocking["degraded"] is False
        assert (
            streamed["answer"]
            == blocking["answer"]
            == "cortex is currently editing colleague/config.py."
        )
        assert streamed["relay"] is False and blocking["relay"] is False
        expected_tokens = _USAGE["prompt_tokens"] + _USAGE["completion_tokens"]
        assert streamed["tokens"] == blocking["tokens"] == expected_tokens
        # No "text" key on the wire: the extractor stays silent, never raises.
        assert display_deltas == []


_SPEAKBACK_TEXT = "The build is green and all tests pass."
_SPEAKBACK_CHUNKS = ["The build is green ", "and all tests pass."]


class TestStreamedRunSensesSpeakbackMatchesBlocking:
    """``run_senses_speakback`` returns the raw reply text verbatim — no JSON
    at all. Arming ``on_delta`` must still leave the final text identical to
    blocking, and the extractor must decline cleanly (EnvelopeStream fails on
    the first non-``{``/backtick character) rather than mis-render prose it
    was never built to parse."""

    def test_final_text_identical_and_extractor_declines_cleanly(self) -> None:
        engine = VllmOpenAIEngine()
        display_deltas: "list[str]" = []

        with _serve(_make_streaming_handler(_SPEAKBACK_CHUNKS, _USAGE)) as stream_url:
            senses_stub = SensesConfig(
                model="senses-model", base_url=stream_url, api_key="k", context_budget=100000
            )
            on_delta = make_senses_display_delta(display_deltas.append)
            streaming_config = senses_engine_config(
                EngineConfig(senses=senses_stub), on_delta=on_delta
            )
            streamed_text, streamed_record = run_senses_speakback(
                "raw work summary", streaming_config, engine
            )

        with _serve(_make_blocking_handler(_SPEAKBACK_TEXT, _USAGE)) as block_url:
            block_stub = SensesConfig(
                model="senses-model", base_url=block_url, api_key="k", context_budget=100000
            )
            blocking_config = senses_engine_config(EngineConfig(senses=block_stub))
            blocking_text, blocking_record = run_senses_speakback(
                "raw work summary", blocking_config, engine
            )

        assert streamed_text == blocking_text == _SPEAKBACK_TEXT
        assert streamed_record.degraded is False
        assert blocking_record.degraded is False
        expected_tokens = _USAGE["prompt_tokens"] + _USAGE["completion_tokens"]
        assert streamed_record.tokens == blocking_record.tokens == expected_tokens
        # No display deltas — the plain-text reply was never a JSON envelope,
        # so the adapter declined immediately, and cleanly (no exception).
        assert display_deltas == []
