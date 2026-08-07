"""Real-socket proof: per-read timeout reset is why streaming survives a slow
turn that blocks a blocking request (session cortex turns, plan task t4,
covers c19/h16).

``urllib``'s ``timeout=`` sets the underlying socket's ``settimeout`` — a
timeout that resets on every individual blocking socket operation, not once
for the life of the request. A blocking completion sends nothing over the
wire until the WHOLE answer is ready, so the client's single read blocks for
the total generation time; a streamed completion flushes each SSE frame as it
is produced, so as long as no single GAP between frames exceeds the timeout,
the read never times out even though the total generation time does.

This is deliberately NOT ``tests/test_vllm_stream.py``'s style (monkeypatched
``urllib.request.urlopen`` with instantaneous fake frames) — that style proves
frame *parsing*, not *timing*. Proving the timeout-reset claim needs a real
socket with real, deliberate delays: a local ``http.server.ThreadingHTTPServer``
thread, per the repo convention against faking a blocking read with
``io.StringIO``. Kept fast and parallel-safe (``pytest -n auto``): a short
~1s timeout, ~0.3s inter-chunk gaps, an OS-assigned port, no shared state.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Iterator

import pytest

from colleague.config import EngineConfig
from colleague.engines.vllm_openai import VllmOpenAIEngine

_TIMEOUT = 1.0
_CHUNK_GAP = 0.3
_CHUNK_WORDS = ["thinking ", "hard ", "about ", "this ", "slow ", "answer"]
# Total generation time comfortably exceeds _TIMEOUT while every individual
# gap comfortably stays under it — the exact shape the per-read reset needs.
_TOTAL_GENERATION_SECONDS = _CHUNK_GAP * len(_CHUNK_WORDS)


class _SlowStreamingHandler(BaseHTTPRequestHandler):
    """Answers every POST with an SSE stream, one word every ``_CHUNK_GAP``."""

    protocol_version = "HTTP/1.0"  # closes the connection at the end of the response

    def log_message(self, fmt: str, *args: object) -> None:  # silence test noise
        pass

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler naming
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)  # drain the request body
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for word in _CHUNK_WORDS:
            frame = {"choices": [{"delta": {"content": word}}]}
            self.wfile.write(f"data: {json.dumps(frame)}\n\n".encode("utf-8"))
            self.wfile.flush()
            time.sleep(_CHUNK_GAP)
        usage_frame = {"choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 6}}
        self.wfile.write(f"data: {json.dumps(usage_frame)}\n\n".encode("utf-8"))
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


class _SlowBlockingHandler(BaseHTTPRequestHandler):
    """Answers every POST as a genuine blocking completion: nothing is sent
    over the wire — not even the status line — until the WHOLE (equally slow)
    answer is ready, mirroring how a non-streaming LLM server actually
    behaves (it buffers the full completion, then sends one response)."""

    protocol_version = "HTTP/1.0"

    def log_message(self, fmt: str, *args: object) -> None:  # silence test noise
        pass

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler naming
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        time.sleep(_TOTAL_GENERATION_SECONDS)  # the SAME total generation time as streaming
        body = json.dumps(
            {
                "choices": [{"message": {"content": "".join(_CHUNK_WORDS)}}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 6},
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class _QuietThreadingHTTPServer(ThreadingHTTPServer):
    """Silences ``handle_error`` — by design, ``_SlowBlockingHandler``'s
    delayed write races the client's own correctly-timed-out, closed socket
    (BrokenPipeError/ConnectionResetError); that race IS the scenario under
    test, not a bug, and must never spam the test run's stderr."""

    def handle_error(self, request: object, client_address: object) -> None:
        pass


def _serve(handler: type) -> Iterator[str]:
    server = _QuietThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/v1"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def slow_streaming_server() -> Iterator[str]:
    yield from _serve(_SlowStreamingHandler)


@pytest.fixture
def slow_blocking_server() -> Iterator[str]:
    yield from _serve(_SlowBlockingHandler)


def _config(base_url: str, *, on_delta) -> EngineConfig:
    return EngineConfig(
        base_url=base_url,
        model="m",
        timeout=_TIMEOUT,
        on_delta=on_delta,
    )


def test_streamed_completion_survives_total_time_past_the_timeout(
    slow_streaming_server: str,
) -> None:
    """Sanity precondition: the scripted total time genuinely exceeds the
    timeout, and every inter-chunk gap genuinely stays under it — otherwise
    this test would prove nothing about the reset."""
    assert _TOTAL_GENERATION_SECONDS > _TIMEOUT
    assert _CHUNK_GAP < _TIMEOUT

    deltas: list[str] = []
    config = _config(slow_streaming_server, on_delta=deltas.append)
    complete = VllmOpenAIEngine()._make_complete(config, tools=[])

    t0 = time.monotonic()
    response = complete([{"role": "user", "content": "hi"}])
    elapsed = time.monotonic() - t0

    assert response.content == "".join(_CHUNK_WORDS)
    assert response.prompt_tokens == 7
    assert response.completion_tokens == 6
    assert deltas == _CHUNK_WORDS
    # It really did take longer than the per-request timeout — proving the
    # completion survived on the strength of the per-chunk reset, not luck.
    assert elapsed > _TIMEOUT


def test_blocking_baseline_times_out_on_the_identical_total_generation_time(
    slow_blocking_server: str,
) -> None:
    """The control: the SAME total generation time, sent as one blocking
    response, blows the same request timeout — proving the streamed proof
    above is really about the transport, not a lenient timeout."""
    config = _config(slow_blocking_server, on_delta=None)
    complete = VllmOpenAIEngine()._make_complete(config, tools=[])

    t0 = time.monotonic()
    with pytest.raises(TimeoutError, match="timed out"):
        complete([{"role": "user", "content": "hi"}])
    elapsed = time.monotonic() - t0

    # Failed close to the configured timeout, not the full generation time —
    # it never got the chance to wait that long.
    assert elapsed < _TOTAL_GENERATION_SECONDS
