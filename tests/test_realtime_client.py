"""Task t3 (realtime-speech arc): the real dial/handshake/pump/degrade client.

Builds on tests/test_realtime.py's stub-era boundary tests (kept, still
green when the [voice] extra is present or absent — see that file's
docstring) with the REAL behaviour: dial + Bearer auth, the
``session.update`` handshake, the base64 audio event codec, the receive-pump
thread, and degrade-never-raise on a mid-session kill.

These tests need the ``[voice]`` extra installed (``uv sync --extra voice``)
so ``websocket-client`` is importable — see this repo's dev-loop note for
this task. ``colleague/realtime.py`` itself never opens a socket directly
(test_boundary.py enforces this); the fake WebSocket SERVER below is a
threaded, stdlib-only (``socket``/``threading``/``hashlib``) RFC 6455 peer
that lives HERE, in tests only, exactly as the brief specifies — it exists so
colleague.realtime's real sync WebSocket CLIENT (``websocket-client``) has
something real to dial, handshake with, and be killed by. It intentionally
implements only what colleague's client needs: the opening handshake, masked
client->server text-frame reads, and unmasked server->client text-frame
writes.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import socket
import struct
import threading
import time

import pytest

# The real [voice]-extra dependency this whole file exercises directly: every
# test here drives colleague.realtime's REAL websocket-client against the fake
# server below, so absence of the extra skips the FILE. This gate is GENUINE
# (unlike the one PR #356's triage removed from tests/test_realtime_devices.py,
# which never touched the package it gated on) — but a skipped file still reads
# as UNCOVERED new code, so CI's coverage job now syncs `--extra voice`, pinned
# by test_coverage_ci_job_installs_the_voice_extra. The plain-`uv sync` test job
# stays extra-free, and the absence-degrade pins deliberately live in
# tests/test_realtime.py, which needs no extra — nothing is hidden by this
# whole-file gate (the media-arc importorskip lesson).
websocket = pytest.importorskip("websocket")

from colleague import realtime  # noqa: E402
from colleague.cli._errors import CliError  # noqa: E402
from colleague.config import RealtimeConfig  # noqa: E402

# ---------------------------------------------------------------------------
# A minimal RFC 6455 SERVER — stdlib-only, lives in tests only. Modelled on
# the handshake/frame arithmetic in
# ../lobes-cli/scripts/realtime-smoke.py's client-side WebSocketClient, just
# inverted for the server role (unmasked writes, masked reads).
# ---------------------------------------------------------------------------

_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"  # RFC 6455 SS4.2.2, fixed by spec.
_OPCODE_TEXT = 0x1
_OPCODE_CLOSE = 0x8


def _accept_key(sec_websocket_key: str) -> str:
    digest = hashlib.sha1(  # nosec B324 - RFC 6455-mandated, not a security use
        (sec_websocket_key + _WS_GUID).encode("ascii")
    ).digest()
    return base64.b64encode(digest).decode("ascii")


def _build_server_frame(opcode: int, payload: bytes = b"") -> bytes:
    """One complete, unmasked server->client frame (FIN always set)."""
    header = bytearray()
    header.append(0x80 | (opcode & 0x0F))
    length = len(payload)
    if length < 126:
        header.append(length)
    elif length < 65536:
        header.append(126)
        header += struct.pack("!H", length)
    else:
        header.append(127)
        header += struct.pack("!Q", length)
    return bytes(header) + payload


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    """Read exactly *n* bytes or return whatever arrived before EOF (possibly empty)."""
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            break
        buf.extend(chunk)
    return bytes(buf)


def _read_client_frame(sock: socket.socket):
    """Read one client->server frame (masked, per RFC 6455 SS5.1). ``None`` on EOF."""
    header = _recv_exact(sock, 2)
    if len(header) < 2:
        return None
    b0, b1 = header[0], header[1]
    opcode = b0 & 0x0F
    masked = bool(b1 & 0x80)
    length = b1 & 0x7F
    if length == 126:
        ext = _recv_exact(sock, 2)
        if len(ext) < 2:
            return None
        length = struct.unpack("!H", ext)[0]
    elif length == 127:
        ext = _recv_exact(sock, 8)
        if len(ext) < 8:
            return None
        length = struct.unpack("!Q", ext)[0]
    mask_key = _recv_exact(sock, 4) if masked else b""
    payload = _recv_exact(sock, length) if length else b""
    if masked and mask_key:
        payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
    return opcode, payload


class FakeRealtimeServer:
    """A single-connection fake ``/v1/realtime`` peer for exercising the real client.

    ``start()`` begins listening; the first TCP connection is accepted,
    handshaken, and read from in a background thread that appends every
    decoded JSON text event to :attr:`received_events`. :meth:`send_event`
    writes a server->client event once a client has connected.
    :meth:`kill_connection` closes the raw socket out from under the client —
    the mid-session-kill test's trigger.
    """

    def __init__(self) -> None:
        self._listen = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listen.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listen.bind(("127.0.0.1", 0))
        self._listen.listen(1)
        self.port: int = self._listen.getsockname()[1]

        self.received_events: list = []
        self.request_headers: dict = {}
        self._events_lock = threading.Lock()
        self._conn_ready = threading.Event()
        self._conn: "socket.socket | None" = None
        self._stop = threading.Event()
        self._accept_thread = threading.Thread(target=self._accept_and_serve, daemon=True)
        self._send_lock = threading.Lock()

    def url(self) -> str:
        return f"ws://127.0.0.1:{self.port}/v1/realtime"

    def start(self) -> None:
        self._accept_thread.start()

    def wait_connected(self, timeout: float = 5.0) -> bool:
        return self._conn_ready.wait(timeout=timeout)

    def wait_for_event_count(self, n: int, timeout: float = 5.0) -> list:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._events_lock:
                if len(self.received_events) >= n:
                    return list(self.received_events)
            time.sleep(0.02)
        with self._events_lock:
            return list(self.received_events)

    def send_event(self, event: dict) -> None:
        assert self.wait_connected(), "fake server: client never connected"
        frame = _build_server_frame(_OPCODE_TEXT, json.dumps(event).encode("utf-8"))
        with self._send_lock:
            self._conn.sendall(frame)  # type: ignore[union-attr]

    def kill_connection(self) -> None:
        """Simulate a mid-session server-initiated disconnect (a hard reset,
        not a clean close handshake) — the trigger for the degrade test."""
        assert self.wait_connected(), "fake server: client never connected"
        with contextlib.suppress(Exception):
            self._conn.shutdown(socket.SHUT_RDWR)  # type: ignore[union-attr]
        with contextlib.suppress(Exception):
            self._conn.close()  # type: ignore[union-attr]

    def stop(self) -> None:
        self._stop.set()
        with contextlib.suppress(Exception):
            self._listen.close()
        if self._conn is not None:
            with contextlib.suppress(Exception):
                self._conn.close()
        self._accept_thread.join(timeout=2.0)

    def _accept_and_serve(self) -> None:
        self._listen.settimeout(5.0)
        try:
            conn, _addr = self._listen.accept()
        except OSError:
            return
        conn.settimeout(5.0)
        try:
            self._handshake(conn)
        except Exception:
            with contextlib.suppress(Exception):
                conn.close()
            return
        self._conn = conn
        self._conn_ready.set()
        self._read_loop(conn)

    def _handshake(self, conn: socket.socket) -> None:
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = conn.recv(4096)
            if not chunk:
                raise ConnectionError("client closed during handshake")
            buf += chunk
        head, _, _rest = buf.partition(b"\r\n\r\n")
        lines = head.decode("latin-1").split("\r\n")
        for line in lines[1:]:
            if ":" in line:
                name, _, value = line.partition(":")
                self.request_headers[name.strip().lower()] = value.strip()
        key = self.request_headers.get("sec-websocket-key", "")
        accept = _accept_key(key)
        response = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
        ).encode("latin-1")
        conn.sendall(response)

    def _read_loop(self, conn: socket.socket) -> None:
        try:
            while not self._stop.is_set():
                try:
                    frame = _read_client_frame(conn)
                except OSError:
                    break
                if frame is None:
                    break
                opcode, payload = frame
                if opcode == _OPCODE_CLOSE:
                    break
                if opcode == _OPCODE_TEXT:
                    try:
                        event = json.loads(payload.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        continue
                    with self._events_lock:
                        self.received_events.append(event)
        except OSError:
            pass


@pytest.fixture
def fake_server():
    server = FakeRealtimeServer()
    server.start()
    try:
        yield server
    finally:
        server.stop()


def _config(server: FakeRealtimeServer, *, api_key: str = "") -> RealtimeConfig:
    return RealtimeConfig(available=True, ws_url=server.url(), api_key=api_key)


# ---------------------------------------------------------------------------
# Pure codec tests — no socket at all.
# ---------------------------------------------------------------------------


def test_encode_audio_append_event_roundtrips_base64():
    pcm = b"\x01\x02\x03\x04"
    event = realtime.encode_audio_append_event(pcm)
    assert event["type"] == "input_audio_buffer.append"
    assert base64.b64decode(event["audio"]) == pcm


def test_encode_audio_append_event_handles_empty_chunk():
    event = realtime.encode_audio_append_event(b"")
    assert event["audio"] == ""


def test_decode_audio_delta_event_roundtrips_base64():
    pcm = b"\xaa\xbb\xcc"
    encoded = base64.b64encode(pcm).decode("ascii")
    decoded = realtime.decode_audio_delta_event({"type": "response.audio.delta", "delta": encoded})
    assert decoded == pcm


def test_decode_audio_delta_event_rejects_missing_delta():
    with pytest.raises(ValueError):
        realtime.decode_audio_delta_event({"type": "response.audio.delta"})


def test_module_source_never_sends_response_create():
    """Static ears-only guarantee: the literal event type this module must
    never send does not appear anywhere in its source at all."""
    src_path = realtime.__file__
    with open(src_path, encoding="utf-8") as fh:
        src = fh.read()
    assert '"response.create"' not in src
    assert "'response.create'" not in src


# ---------------------------------------------------------------------------
# Live tests against the fake stdlib WS server.
# ---------------------------------------------------------------------------


def test_open_session_dials_with_bearer_header_and_sends_session_update(fake_server, monkeypatch):
    monkeypatch.delenv("COLLEAGUE_REALTIME_API_KEY", raising=False)
    config = _config(fake_server, api_key="s3cr3t")

    session = realtime.open_session(config)
    try:
        assert session is not None
        assert fake_server.wait_connected()
        assert fake_server.request_headers.get("authorization") == "Bearer s3cr3t"

        events = fake_server.wait_for_event_count(1)
        assert events, "server never received the session.update handshake event"
        handshake = events[0]
        assert handshake["type"] == "session.update"
        assert handshake["session"]["turn_detection"]["type"] == "server_vad"
        assert handshake["session"]["input_audio_format"] == "pcm16"
    finally:
        if session is not None:
            session.close()


def test_open_session_without_api_key_sends_no_authorization_header(fake_server):
    config = _config(fake_server, api_key="")
    session = realtime.open_session(config)
    try:
        assert session is not None
        assert fake_server.wait_connected()
        assert "authorization" not in fake_server.request_headers
    finally:
        if session is not None:
            session.close()


def test_send_audio_encodes_base64_append_event_on_the_wire(fake_server):
    config = _config(fake_server)
    session = realtime.open_session(config)
    try:
        assert session is not None
        fake_server.wait_for_event_count(1)  # the session.update handshake
        pcm = b"\x10\x20\x30\x40"
        assert session.send_audio(pcm) is True

        events = fake_server.wait_for_event_count(2)
        assert len(events) == 2
        append_event = events[1]
        assert append_event["type"] == "input_audio_buffer.append"
        assert base64.b64decode(append_event["audio"]) == pcm
    finally:
        if session is not None:
            session.close()


def test_send_audio_while_muted_sends_nothing(fake_server):
    config = _config(fake_server)
    session = realtime.open_session(config)
    try:
        assert session is not None
        fake_server.wait_for_event_count(1)  # the session.update handshake
        session.mute()
        assert session.muted is True
        assert session.send_audio(b"\x01\x02") is False
        time.sleep(0.2)  # give the (nonexistent) send a chance to have landed
        assert len(fake_server.received_events) == 1  # only the handshake
        session.unmute()
        assert session.muted is False
        assert session.send_audio(b"\x01\x02") is True
        events = fake_server.wait_for_event_count(2)
        assert len(events) == 2
    finally:
        if session is not None:
            session.close()


def test_transcript_event_reaches_both_callback_and_queue(fake_server):
    seen: list = []
    config = _config(fake_server)
    session = realtime.open_session(config, on_transcript=seen.append)
    try:
        assert session is not None
        fake_server.wait_connected()
        fake_server.send_event(
            {
                "type": "conversation.item.input_audio_transcription.completed",
                "text": "hello colleague",
            }
        )
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and not seen:
            time.sleep(0.02)
        assert seen == ["hello colleague"]
        assert session.transcripts.get(timeout=1.0) == "hello colleague"
    finally:
        if session is not None:
            session.close()


def test_vad_boundary_events_reach_the_generic_on_event_callback(fake_server):
    seen: list = []
    config = _config(fake_server)
    session = realtime.open_session(config, on_event=seen.append)
    try:
        assert session is not None
        fake_server.wait_connected()
        fake_server.send_event({"type": "input_audio_buffer.speech_started", "item_id": "i1"})
        fake_server.send_event({"type": "input_audio_buffer.speech_stopped", "item_id": "i1"})
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and len(seen) < 2:
            time.sleep(0.02)
        types = [event.get("type") for event in seen]
        assert "input_audio_buffer.speech_started" in types
        assert "input_audio_buffer.speech_stopped" in types
    finally:
        if session is not None:
            session.close()


def test_no_response_create_ever_sent_over_the_wire(fake_server):
    """Live counterpart of test_module_source_never_sends_response_create:
    drive a full session (handshake + audio send + transcript receipt) and
    assert the fake server never once saw a response.create event."""
    config = _config(fake_server)
    session = realtime.open_session(config)
    try:
        assert session is not None
        fake_server.wait_for_event_count(1)
        session.send_audio(b"\x00\x00" * 16)
        fake_server.send_event(
            {
                "type": "conversation.item.input_audio_transcription.completed",
                "text": "no reply should ever be requested",
            }
        )
        time.sleep(0.2)
        types = [event.get("type") for event in fake_server.received_events]
        assert "response.create" not in types
    finally:
        if session is not None:
            session.close()


def test_mid_session_kill_degrades_with_exactly_one_stderr_notice(fake_server, capsys):
    config = _config(fake_server)
    session = realtime.open_session(config)
    try:
        assert session is not None
        assert fake_server.wait_connected()
        assert session.degraded is False

        fake_server.kill_connection()

        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and not session.degraded:
            time.sleep(0.02)
        assert session.degraded is True
        assert session.degrade_reason is not None

        captured = capsys.readouterr()
        notice_lines = [
            line
            for line in captured.err.splitlines()
            if line.startswith("colleague: realtime session degraded")
        ]
        assert len(notice_lines) == 1, notice_lines

        # send_audio must degrade cleanly too — never raise — once dead.
        assert session.send_audio(b"\x01\x02") is False
    finally:
        session.close()


def test_open_session_dial_failure_returns_none_with_one_notice(capsys):
    """Nothing is listening on this port — a connection-refused dial failure
    must degrade to None, never raise, with exactly one stderr notice."""
    unused = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    unused.bind(("127.0.0.1", 0))
    port = unused.getsockname()[1]
    unused.close()  # freed immediately — nothing will accept on this port

    config = RealtimeConfig(available=True, ws_url=f"ws://127.0.0.1:{port}/v1/realtime", api_key="")
    session = realtime.open_session(config)
    assert session is None

    captured = capsys.readouterr()
    notice_lines = [line for line in captured.err.splitlines() if line.startswith("colleague: ")]
    assert len(notice_lines) == 1, notice_lines
    assert "realtime dial failed" in notice_lines[0]


def test_open_session_with_no_config_makes_zero_dial_attempts_and_returns_none():
    """``config is None`` (the ``EngineConfig.realtime is None`` contract) must
    short-circuit to None with no dial attempt at all — and must NOT raise,
    unlike the extra-absent case (checked before config is ever read)."""
    assert realtime.open_session(None) is None


def test_close_is_idempotent_and_never_hangs(fake_server):
    config = _config(fake_server)
    session = realtime.open_session(config)
    assert session is not None
    session.close()
    session.close()  # a second close must be a no-op, not an error.


def test_pump_bounded_join_is_bounded_on_a_real_blocking_socket_read(fake_server):
    """The #315 lesson: a fake/mock recv() that returns instantly would let a
    broken bounded-join implementation pass by accident. This test's
    ``ws.recv()`` is genuinely parked in a blocking OS-level read against a
    REAL socket (the fake server above never sends anything and never closes)
    — only the poll-wake settimeout + stop event can unblock it, so a bound
    here is real evidence, not a vacuous pass.
    """
    config = _config(fake_server)
    session = realtime.open_session(config)
    assert session is not None
    assert fake_server.wait_connected()

    started = time.monotonic()
    session.close(timeout=2.0)
    elapsed = time.monotonic() - started

    # The poll-wake tick is _RECV_POLL_SECONDS (0.5s); a couple of ticks plus
    # scheduling slack is generously bounded well under the 2s ceiling itself.
    assert elapsed < 2.0, f"close() took {elapsed:.2f}s — the bounded join did not bound anything"


def test_open_session_raises_clierror_when_extra_absent(monkeypatch):
    """Mirrors tests/test_realtime.py's stub-era test, pinned here too since
    this file always runs with the extra installed: simulate "extra absent"
    by making _import_ws fail, and confirm open_session still raises CliError
    BEFORE touching config — the one behaviour this task preserves unchanged."""

    def _boom():
        raise CliError(
            1,
            "realtime speech support is not installed (boom)",
            remediation="pip install colleague[voice]",
        )

    monkeypatch.setattr(realtime, "_import_ws", _boom)
    config = RealtimeConfig(available=True, ws_url="ws://x/v1/realtime", api_key="")
    with pytest.raises(CliError) as exc:
        realtime.open_session(config)
    assert "colleague[voice]" in (exc.value.remediation or "")


def test_websocket_client_is_actually_importable_in_this_env():
    """Sanity check that this test file's own environment has the [voice]
    extra installed — if this fails, the whole file's live tests are
    meaningless, not just individually skipped."""
    assert websocket.create_connection is not None
