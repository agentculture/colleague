"""Stream guards — idle + lifetime watchdogs on the SSE path (adopt-from-qwen-code c12/h10).

``COLLEAGUE_TIMEOUT`` bounds each socket operation; it never bounded a stream
that keeps *dripping* (a byte at a time, forever). qwen-code's three-tier
watchdog (openaiContentGenerator/constants.ts:1-68, pipeline.ts:412-530)
adds two independent guards; these tests pin colleague's port:

- ``COLLEAGUE_STREAM_IDLE_TIMEOUT`` (default 240s) and
  ``COLLEAGUE_STREAM_MAX_LIFETIME`` (default 1800s) are read in the stream
  reader; ``0`` disables either;
- a trip raises the existing :class:`stallguard.TurnStalled` path and the
  run's ``TaskResult.warnings`` names WHICH guard tripped;
- ``COLLEAGUE_TIMEOUT`` semantics are unchanged (a silent gap longer than it
  is still a legible request timeout).

Every transport test below runs against a REAL ``http.server`` on a real
socket (never a fake iterable stream): a fake hides exactly the blocking-read
behaviour these guards exist for.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

import pytest

from colleague import loop, streamguards
from colleague.context import is_request_timeout
from colleague.contract import INCOMPLETE, Task
from colleague.engines import vllm_openai
from colleague.loop import ModelResponse

# --- a real SSE server whose body is scripted per test ----------------------


def _frame(text: str, *, finish: str | None = None) -> bytes:
    payload = {
        "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": finish}],
    }
    return f"data: {json.dumps(payload)}\n\n".encode()


class _Server:
    """A ThreadingHTTPServer that streams whatever ``script`` writes."""

    def __init__(self, script: Callable[[Callable[[bytes], None]], None]) -> None:
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_a) -> None:  # quiet
                pass

            def do_POST(self) -> None:
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()

                def write(chunk: bytes) -> None:
                    self.wfile.write(f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n")
                    self.wfile.flush()

                try:
                    outer.script(write)
                    self.wfile.write(b"0\r\n\r\n")
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass

        self.script = script
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self) -> str:
        self.thread.start()
        host, port = self.httpd.server_address[:2]
        return f"http://{host}:{port}/v1/chat/completions"

    def __exit__(self, *exc: object) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


def _stream(url: str, timeout: float) -> ModelResponse:
    return vllm_openai._post_json_stream(
        url,
        {"model": "m", "messages": [], "stream": True},
        api_key="k",
        timeout=timeout,
        on_delta=lambda _s: None,
    )


def _stream_or_blocking(url: str, timeout: float) -> ModelResponse:
    return vllm_openai._stream_or_blocking(
        url,
        {"model": "m", "messages": [], "stream": True},
        api_key="k",
        timeout=timeout,
        on_delta=lambda _s: None,
    )


# --- knobs -------------------------------------------------------------------


def test_defaults_and_zero_disables(monkeypatch) -> None:
    monkeypatch.delenv("COLLEAGUE_STREAM_IDLE_TIMEOUT", raising=False)
    monkeypatch.delenv("COLLEAGUE_STREAM_MAX_LIFETIME", raising=False)
    guards = streamguards.StreamGuards.from_env()
    assert guards.idle == 240.0
    assert guards.lifetime == 1800.0
    monkeypatch.setenv("COLLEAGUE_STREAM_IDLE_TIMEOUT", "0")
    monkeypatch.setenv("COLLEAGUE_STREAM_MAX_LIFETIME", "0")
    assert streamguards.StreamGuards.from_env() is None
    monkeypatch.setenv("COLLEAGUE_STREAM_IDLE_TIMEOUT", "12.5")
    monkeypatch.setenv("COLLEAGUE_STREAM_MAX_LIFETIME", "garbage")
    guards = streamguards.StreamGuards.from_env()
    assert guards is not None
    assert guards.idle == 12.5
    assert guards.lifetime is None


@pytest.mark.parametrize(
    "raw",
    ["inf", "-inf", "nan", "-5", "garbage"],
)
def test_non_finite_or_non_positive_knobs_disable_the_guard(monkeypatch, raw) -> None:
    """Only FINITE positive floats may arm a guard: inf/nan/negative/unparseable
    all disable it (None) — inf/nan would be passed straight to
    socket.settimeout, which is not a valid timeout."""
    monkeypatch.setenv("COLLEAGUE_STREAM_IDLE_TIMEOUT", raw)
    monkeypatch.setenv("COLLEAGUE_STREAM_MAX_LIFETIME", raw)
    assert streamguards.StreamGuards.from_env() is None
    # One bad knob disables only that guard; the other keeps its default.
    monkeypatch.setenv("COLLEAGUE_STREAM_MAX_LIFETIME", "900")
    guards = streamguards.StreamGuards.from_env()
    assert guards is not None
    assert guards.idle is None
    assert guards.lifetime == 900.0


def test_finite_positive_knob_still_arms(monkeypatch) -> None:
    monkeypatch.setenv("COLLEAGUE_STREAM_IDLE_TIMEOUT", "12.5")
    guards = streamguards.StreamGuards.from_env()
    assert guards is not None
    assert guards.idle == 12.5


# --- the two trips, on a real socket -----------------------------------------


def test_idle_gap_trips_the_idle_guard(monkeypatch) -> None:
    """A silent gap longer than the idle bound (but shorter than COLLEAGUE_TIMEOUT)
    trips 'stream-idle' — promptly, not when the next byte finally lands."""
    monkeypatch.setenv("COLLEAGUE_STREAM_IDLE_TIMEOUT", "0.4")
    monkeypatch.setenv("COLLEAGUE_STREAM_MAX_LIFETIME", "30")

    def script(write):
        write(_frame("hello"))
        time.sleep(3.0)  # silent gap, well past the idle bound
        write(_frame("", finish="stop"))
        write(b"data: [DONE]\n\n")

    with _Server(script) as url:
        start = time.monotonic()
        with pytest.raises(streamguards.StreamGuardTripped) as excinfo:
            _stream(url, timeout=10.0)  # request timeout is LARGER than the idle bound
        elapsed = time.monotonic() - start
    assert excinfo.value.guard == "stream-idle"
    assert excinfo.value.bound == pytest.approx(0.4)
    assert 0.4 <= elapsed < 2.5, elapsed  # tripped at the bound, not at the 3s gap's end


def test_keepalive_comments_do_not_reset_the_idle_guard(monkeypatch) -> None:
    """A gateway relaying SSE keepalives (``:`` comment lines) over a dead upstream
    must NOT look alive: only non-comment payload lines restart the idle clock
    (#438 guidance 4). A stream that sends one real frame and then only keepalives
    trips ``stream-idle`` at its deadline instead of being kept alive by them."""
    monkeypatch.setenv("COLLEAGUE_STREAM_IDLE_TIMEOUT", "0.4")
    monkeypatch.setenv("COLLEAGUE_STREAM_MAX_LIFETIME", "30")

    def script(write):
        write(_frame("hello"))  # one real payload line
        for _ in range(30):  # ~3s of keepalives, well past the 0.4s idle bound
            write(b": keepalive\n")
            time.sleep(0.1)

    with _Server(script) as url:
        start = time.monotonic()
        with pytest.raises(streamguards.StreamGuardTripped) as excinfo:
            _stream(url, timeout=10.0)  # request timeout is LARGER than the idle bound
        elapsed = time.monotonic() - start
    assert excinfo.value.guard == "stream-idle"
    assert excinfo.value.bound == pytest.approx(0.4)
    # Tripped at the idle deadline after the last REAL frame, not kept alive by the keepalives.
    assert 0.4 <= elapsed < 1.5, elapsed


def test_drip_feed_trips_the_lifetime_guard(monkeypatch) -> None:
    """One byte at a time, forever, never a newline: the idle guard never fires
    (bytes keep arriving) — the lifetime guard is what ends it (qwen #8597)."""
    monkeypatch.setenv("COLLEAGUE_STREAM_IDLE_TIMEOUT", "5")
    monkeypatch.setenv("COLLEAGUE_STREAM_MAX_LIFETIME", "0.6")

    def script(write):
        write(b"data: ")
        for _ in range(400):  # ~8s of dripping, far past the lifetime bound
            write(b"x")
            time.sleep(0.02)

    with _Server(script) as url:
        start = time.monotonic()
        with pytest.raises(streamguards.StreamGuardTripped) as excinfo:
            _stream(url, timeout=10.0)
        elapsed = time.monotonic() - start
    assert excinfo.value.guard == "stream-lifetime"
    assert excinfo.value.bound == pytest.approx(0.6)
    assert 0.6 <= elapsed < 3.0, elapsed


# --- the blocking fallback is bounded by the SAME guards (#438) --------------


_BLOCKING_BODY = json.dumps(
    {"choices": [{"index": 0, "message": {"content": "ok"}, "finish_reason": "stop"}]}
).encode()


def _counting(script: Callable[[Callable[[bytes], None], int], None]):
    """``_Server``'s Handler closes over ONE script; wrap it to number requests
    (request 1 = the streaming attempt, request 2 = the blocking fallback)."""
    request_no = 0

    def counting_script(write: Callable[[bytes], None]) -> None:
        nonlocal request_no
        request_no += 1
        script(write, request_no)

    return counting_script


def _incomplete_stream(write: Callable[[bytes], None]) -> None:
    """One real frame, then the connection closes with NO terminal frame ->
    ``_StreamIncomplete`` -> the turn degrades to ONE blocking POST."""
    write(_frame("partial"))


def test_fallback_stall_trips_the_idle_guard(monkeypatch) -> None:
    """The non-streaming fallback of ``_stream_or_blocking`` must be bounded by
    the SAME StreamGuards the streaming reader gets — not a plain
    ``response.read()`` that hangs until the request timeout.

    Real socket, never a mock: the first request is an SSE stream that closes
    with no terminal frame (``_StreamIncomplete`` — a fallback-eligible
    failure), so the turn degrades to ONE blocking POST. That blocking POST
    sends the head of a JSON body and then goes SILENT — the exact shape a
    fake iterable stream hides (the fake-streams-hide-blocking-reader-bugs
    lesson). The idle guard must trip within its bound, promptly, instead of
    the turn sitting out the full 10s request timeout. (A body that keeps
    *arriving* is progress and must NOT trip — see
    ``test_continuous_no_newline_body_does_not_trip_the_idle_guard``.)
    """
    monkeypatch.setenv("COLLEAGUE_STREAM_IDLE_TIMEOUT", "0.4")
    monkeypatch.setenv("COLLEAGUE_STREAM_MAX_LIFETIME", "30")

    def script(write, request_no):
        if request_no == 1:
            _incomplete_stream(write)
            return
        # Blocking fallback: the head of the body, then a long silence.
        write(_BLOCKING_BODY[:10])
        time.sleep(3.0)  # well past the 0.4s idle bound

    with _Server(_counting(script)) as url:
        start = time.monotonic()
        with pytest.raises(streamguards.StreamGuardTripped) as excinfo:
            _stream_or_blocking(url, timeout=10.0)  # request timeout is LARGER than the idle bound
        elapsed = time.monotonic() - start
    assert excinfo.value.guard == "stream-idle"
    assert excinfo.value.bound == pytest.approx(0.4)
    # Tripped at the idle bound on the fallback's silence, not at the 10s request timeout.
    assert 0.4 <= elapsed < 3.0, elapsed


def test_continuous_no_newline_body_does_not_trip_the_idle_guard(monkeypatch) -> None:
    """Regression (Qodo 3887387003): a payload that arrives as ONE long line
    with no newline is real progress and must restart the idle clock as its
    bytes land — not sit undelivered while ``stream-idle`` elapses.

    The blocking fallback's JSON body is exactly that shape (and is now read
    through ``guarded_lines``): dripped over ~2s with a 0.4s idle bound, it
    must COMPLETE, not trip. Refreshing only on a completed line made this a
    guaranteed false trip on any body slower than the bound.
    """
    monkeypatch.setenv("COLLEAGUE_STREAM_IDLE_TIMEOUT", "0.4")
    monkeypatch.setenv("COLLEAGUE_STREAM_MAX_LIFETIME", "30")

    def script(write, request_no):
        if request_no == 1:
            _incomplete_stream(write)
            return
        # Blocking fallback: drip the JSON body byte by byte, never a newline,
        # for far longer than the 0.4s idle bound. Bytes never stop arriving.
        for byte in _BLOCKING_BODY:
            write(bytes([byte]))
            time.sleep(0.02)

    with _Server(_counting(script)) as url:
        response = _stream_or_blocking(url, timeout=10.0)
    assert response.content == "ok"


def test_partial_comment_keepalive_still_trips_the_idle_guard(monkeypatch) -> None:
    """The mid-line idle refresh must NOT leak the comment exclusion (#438
    guidance 4): a keepalive dripped WITHOUT its newline is still a comment
    from its first byte, so a gateway relaying one over a dead upstream still
    trips ``stream-idle`` at its deadline."""
    monkeypatch.setenv("COLLEAGUE_STREAM_IDLE_TIMEOUT", "0.4")
    monkeypatch.setenv("COLLEAGUE_STREAM_MAX_LIFETIME", "30")

    def script(write):
        write(_frame("hello"))  # the one real payload line
        write(b": ")  # a comment line that never terminates...
        for _ in range(150):  # ...dripped for ~3s, well past the idle bound
            write(b"keepalive ")
            time.sleep(0.02)

    with _Server(script) as url:
        start = time.monotonic()
        with pytest.raises(streamguards.StreamGuardTripped) as excinfo:
            _stream(url, timeout=10.0)  # request timeout is LARGER than the idle bound
        elapsed = time.monotonic() - start
    assert excinfo.value.guard == "stream-idle"
    assert excinfo.value.bound == pytest.approx(0.4)
    assert 0.4 <= elapsed < 1.5, elapsed


def test_fallback_shares_the_streaming_guards_object(monkeypatch) -> None:
    """``_stream_or_blocking`` builds ONE guard object per turn and hands the
    SAME one to the streaming reader and the blocking fallback — the fallback
    is not unguarded, and the turn does not re-read the knobs a second time.
    """
    # A generous idle bound: this test asserts object SHARING, not a trip —
    # the fallback's JSON body carries no newline, so the idle clock (which
    # only restarts on a non-comment payload LINE) would otherwise be a
    # flaky source of trips on slow CI.
    monkeypatch.setenv("COLLEAGUE_STREAM_IDLE_TIMEOUT", "30")
    monkeypatch.setenv("COLLEAGUE_STREAM_MAX_LIFETIME", "30")

    from_env_calls: list[Any] = []
    real_from_env = streamguards.StreamGuards.from_env  # bound classmethod: no cls needed

    def counting_from_env(cls: Any, *args: Any, **kwargs: Any) -> Any:
        guards = real_from_env(*args, **kwargs)
        from_env_calls.append(guards)
        return guards

    monkeypatch.setattr(streamguards.StreamGuards, "from_env", classmethod(counting_from_env))

    # A pure unit assertion: both transports are stubbed, so no socket is
    # opened and conftest's autouse _sse_bridge_over_blocking_stubs (which
    # dispatches urlopen through the module-level _post_json) never engages.
    stream_guards: list[Any] = []
    fallback_guards: list[Any] = []
    turn = {"choices": [{"index": 0, "message": {"content": "ok"}, "finish_reason": "stop"}]}

    def stub_post_json_stream(url, payload, **kwargs):
        stream_guards.append(kwargs.get("guards"))
        raise ConnectionError("stream died mid-turn")  # a _STREAM_FALLBACK_ERRORS member

    def stub_post_json(url, payload, **kwargs):
        fallback_guards.append(kwargs.get("guards"))
        return turn

    monkeypatch.setattr(vllm_openai, "_post_json_stream", stub_post_json_stream)
    monkeypatch.setattr(vllm_openai, "_post_json", stub_post_json)

    _stream_or_blocking("http://stub.invalid/v1/chat/completions", timeout=10.0)

    # Exactly ONE guard object per turn, and BOTH paths got that SAME object.
    assert len(from_env_calls) == 1
    assert from_env_calls[0].idle == 30.0
    assert len(stream_guards) == 1
    assert stream_guards[0] is from_env_calls[0]
    assert len(fallback_guards) == 1
    assert fallback_guards[0] is from_env_calls[0]


def test_guards_disabled_drip_completes_and_timeout_semantics_unchanged(monkeypatch) -> None:
    """With both knobs at 0 a dripped-but-finite stream completes normally, and a
    silent gap longer than COLLEAGUE_TIMEOUT is still the legible request timeout."""
    monkeypatch.setenv("COLLEAGUE_STREAM_IDLE_TIMEOUT", "0")
    monkeypatch.setenv("COLLEAGUE_STREAM_MAX_LIFETIME", "0")

    def dripping(write):
        for b in _frame("drip"):
            write(bytes([b]))
            time.sleep(0.005)
        write(_frame("", finish="stop"))
        write(b"data: [DONE]\n\n")

    with _Server(dripping) as url:
        resp = _stream(url, timeout=10.0)
    assert resp.content == "drip"

    def silent(write):
        write(_frame("a"))
        time.sleep(2.0)
        write(b"data: [DONE]\n\n")

    with _Server(silent) as url:
        with pytest.raises(TimeoutError) as excinfo:
            _stream(url, timeout=0.3)
    assert is_request_timeout(str(excinfo.value))
    assert "COLLEAGUE_TIMEOUT" in str(excinfo.value)


def test_request_timeout_still_wins_when_it_is_the_nearer_bound(monkeypatch) -> None:
    """Guards armed with LARGE bounds change nothing about a short COLLEAGUE_TIMEOUT."""
    monkeypatch.setenv("COLLEAGUE_STREAM_IDLE_TIMEOUT", "240")
    monkeypatch.setenv("COLLEAGUE_STREAM_MAX_LIFETIME", "900")

    def silent(write):
        write(_frame("a"))
        time.sleep(2.0)

    with _Server(silent) as url:
        with pytest.raises(TimeoutError) as excinfo:
            _stream(url, timeout=0.3)
    assert is_request_timeout(str(excinfo.value))


# --- the loop names the guard ------------------------------------------------


@pytest.fixture
def task(tmp_path: Path) -> Task:
    repo = tmp_path / "repo"
    repo.mkdir()
    return Task.new(str(repo), "watch the stream")


def test_loop_warning_names_the_guard(task: Task) -> None:
    def tripping(_messages):
        raise streamguards.StreamGuardTripped(1.2, 0.5, guard="stream-lifetime")

    result = loop.run(tripping, task, max_steps=3)
    assert result.status == INCOMPLETE
    stalls = [w for w in result.warnings if w.get("kind") == "step-stall"]
    assert len(stalls) == 1
    assert stalls[0]["guard"] == "stream-lifetime"
    assert result.incompletion is not None
    assert result.incompletion.reason == "step-stall"


def test_step_stall_warning_keeps_its_default_guard_name(task: Task, monkeypatch) -> None:
    monkeypatch.setenv("COLLEAGUE_MAX_STEP_STALL", "0.2")

    def streaming_forever(_messages):
        while True:
            time.sleep(0.02)
            loop.stallguard.check()

    result = loop.run(streaming_forever, task, max_steps=3)
    stalls = [w for w in result.warnings if w.get("kind") == "step-stall"]
    assert stalls
    assert stalls[0]["guard"] == "step-stall"
