"""Ears-only realtime speech client (plan task t3 of the realtime-speech arc:
docs/specs/2026-07-22-realtime-speech.md, docs/plans/2026-07-22-realtime-speech.md).

Task t1 landed :class:`colleague.config.RealtimeConfig` (the resolved dial
target) and task t2 landed this module as an import-clean packaging stub. This
task fills in the actual client: :func:`open_session` dials
``ws(s)://<origin>/v1/realtime`` with Bearer auth, sends a ``session.update``
handshake declaring ``server_vad``/``pcm16``, and returns a
:class:`RealtimeSession` that runs ONE receive-pump thread. The sync WebSocket
client (``websocket-client``, imported as ``websocket``) lives ONLY in the
opt-in ``[voice]`` extra and is imported LAZILY, inside :func:`_import_ws`,
never at module load — mirroring ``colleague/voice_devices.py`` exactly, so
this module stays import-clean on a BASE install (tests/test_realtime.py).

Ears-only design (spec c22/h15, plan task t3 instruction)
----------------------------------------------------------
The realtime session colleague dials is EARS-ONLY: it never sends
``response.create`` and never arms the bridge's own LLM turn (the bridge's
own model + its ``DEFAULT_SYSTEM_PROMPT``) — colleague consumes only session
lifecycle, VAD turn-boundary, and transcription events over the wire.
:class:`RealtimeSession` has no method that emits ``response.create`` and
never will — grepping this file's source for that literal string is part of
the boundary discipline this module documents (see
tests/test_realtime_client.py's static + live assertions). Senses (the
grounded, tools-off mind that actually answers — see ``colleague/senses.py``)
stays the ONLY producer of a spoken reply, via the existing batch
``colleague.voice.synthesize()`` lane (task t5); the realtime socket is a
listening ear, never a second voice, and cortex remains the only repo actor.
Audio-out does NOT ride this socket either way — a later task's batch TTS
lane is the only speech-out path.

Thread sanction rationale (recorded in ``tests/test_boundary.py``)
----------------------------------------------------------------------
Continuous audio streams need a receive-pump thread; ``colleague/realtime.py``
is sanctioned (spec c6, plan task t2) as the ONE additional module — after
``colleague/subagents.py`` and ``colleague/cli/_commands/_input_line.py`` — to
import ``threading`` directly. :class:`RealtimeSession`'s pump is modelled
directly on ``colleague/cli/_commands/_input_line.py``'s ``OwnedInputLine``:
ONE daemon thread, a ``threading.Event`` stop signal, a poll-wake read
(``websocket-client``'s ``settimeout`` gives the same wake-up-and-recheck
shape ``select`` gives the input line), and a BOUNDED :func:`_bounded_join` so
teardown never hangs on a parked blocking read (the #315 lesson — a fake
stream cannot prove this; ``tests/test_realtime_client.py`` proves it against
a REAL threaded stdlib socket server, never a mocked/fake WebSocket object).
A future mic-capture thread (task t4) will follow the identical discipline,
still confined to this ONE module, still gated behind the opt-in ``[voice]``
extra.

Degrade-never-raise at the session boundary
--------------------------------------------
Two DIFFERENT failure classes are handled deliberately differently:

* **The ``[voice]`` extra is not installed** — a setup/environment problem the
  operator can fix once — :func:`_import_ws` (and therefore
  :func:`open_session`) raises a clean :class:`CliError` naming
  ``pip install colleague[voice]``, exactly like every other voice function in
  this codebase (``colleague/voice_devices.py``'s ``record``). This is checked
  FIRST, before any config is even consulted.
* **A dial/handshake/mid-session failure with the extra installed** — the
  network is inherently flaky, and the whole point of this arc is a graceful
  fallback to the turn-based lane — never raises: :func:`open_session` returns
  ``None`` and :class:`RealtimeSession`'s pump thread degrades in place
  (:attr:`RealtimeSession.degraded` flips), each printing exactly
  ONE ``colleague: ...`` stderr notice (:func:`_notice`, the same convention
  ``colleague/voice.py`` uses) and never letting an exception escape this
  module's public surface.

This module is otherwise a thin layer: config is resolved ELSEWHERE
(``colleague/config.py``'s ``RealtimeConfig``) and consumed here verbatim —
this module never re-resolves an env var or a config.json section itself.
"""

from __future__ import annotations

import base64
import contextlib
import json
import queue
import sys
import threading
from typing import TYPE_CHECKING, Any, Callable, Mapping, Optional

from colleague.cli._errors import CliError

if TYPE_CHECKING:
    from colleague.config import RealtimeConfig

_INSTALL_HINT = "pip install colleague[voice]"

# ---------------------------------------------------------------------------
# Wire constants — OpenAI-Realtime-flavoured event/type names, matching
# lobes/realtime/_session.py's EventType/AudioFormat/TurnDetectionType
# (../lobes-cli/lobes/realtime/_session.py) so this client's wire shape lines
# up with the reference server's event schema. Deliberately NO
# response-create constant anywhere in this module — see the module
# docstring's ears-only section.
# ---------------------------------------------------------------------------

_EVENT_SESSION_UPDATE = "session.update"
_EVENT_APPEND = "input_audio_buffer.append"
_EVENT_TRANSCRIPTION_COMPLETED = "conversation.item.input_audio_transcription.completed"

_TURN_DETECTION_SERVER_VAD = "server_vad"
_AUDIO_FORMAT_PCM16 = "pcm16"
_DEFAULT_SAMPLE_RATE = 24000

#: How long the pump's ``ws.recv()`` blocks before raising a timeout and
#: looping back to re-check the stop event — the poll-wake, mirroring
#: ``_input_line.py``'s ``_READ_POLL_SECONDS``. Small enough that teardown is
#: imperceptible, large enough that an idle session costs ~nothing.
_RECV_POLL_SECONDS = 0.5

#: The handshake's own connect timeout — separate from the poll-wake above,
#: which is installed via ``ws.settimeout`` only AFTER the handshake succeeds.
_CONNECT_TIMEOUT_SECONDS = 10.0

#: Default bound for :meth:`RealtimeSession.close`'s pump join — never hangs.
_JOIN_TIMEOUT_SECONDS = 2.0

#: Bound for the underlying WS close handshake's own wait for the peer's
#: close-frame reply (``websocket-client``'s own default is 3s — unbounded
#: enough to defeat this module's whole "teardown never hangs" discipline
#: when the peer never acks, e.g. a server that already vanished).
_WS_CLOSE_TIMEOUT_SECONDS = 0.5


def _notice(text: str) -> None:
    """Print one ``colleague: ...`` degrade notice to stderr (mirrors ``colleague/voice.py``)."""
    print(f"colleague: {text}", file=sys.stderr)


def _import_ws() -> Any:
    """Lazily import the sync WS client, or raise a clean :class:`CliError`.

    Mirrors ``colleague/voice_devices.py``'s ``_import_audio``: the realtime
    module stays import-clean on a base install; the third-party dependency
    (``websocket-client``, imported as ``websocket``) is pulled in only when a
    realtime function actually runs — never at module load.
    """
    try:
        import websocket  # type: ignore

        return websocket
    except Exception as exc:  # noqa: BLE001 - any import failure names the extra
        raise CliError(
            1,
            f"realtime speech support is not installed ({type(exc).__name__})",
            remediation=_INSTALL_HINT,
        ) from exc


def _bounded_join(thread: threading.Thread, *, timeout: float = 1.0) -> None:
    """Join *thread* with a bounded timeout — never hangs.

    The one piece of the sanctioned thread discipline this stub already
    implements (see the module docstring): every pump/callback thread task
    t3/t4 spawns is a daemon thread stopped via a ``threading.Event`` and
    reaped through this bounded join, exactly like
    ``colleague/cli/_commands/_input_line.py``'s ``OwnedInputLine.stop``.
    Idempotent-safe: joining an already-finished thread returns immediately.
    """
    if thread.is_alive():
        thread.join(timeout=timeout)


# ---------------------------------------------------------------------------
# Base64 audio event codec — mirrors ../lobes-cli/scripts/realtime-smoke.py's
# build_append_event/decode_audio_delta_event field-for-field.
# ---------------------------------------------------------------------------


def encode_audio_append_event(pcm16_bytes: bytes) -> dict:
    """Wrap one raw PCM16 mono chunk as an ``input_audio_buffer.append`` event.

    An empty *pcm16_bytes* is valid (encodes to ``""``) — never an error.
    """
    return {
        "type": _EVENT_APPEND,
        "audio": base64.b64encode(pcm16_bytes).decode("ascii"),
    }


def decode_audio_delta_event(event: Mapping[str, Any]) -> bytes:
    """Decode a ``response.audio.delta`` event's base64 ``delta`` field to raw PCM16 bytes.

    This session is ears-only and never triggers ``response.create`` (see the
    module docstring), so no call site consumes this today — it exists so the
    OUTBOUND half of the codec is exercised symmetrically with
    :func:`encode_audio_append_event` (mirroring
    ``../lobes-cli/scripts/realtime-smoke.py``'s
    ``decode_audio_delta_event``), ready for a future opt-in caller. Raises
    :class:`ValueError` on a malformed event — a wire-codec function, not a
    degrade-never-raise session boundary function.
    """
    delta = event.get("delta")
    if not isinstance(delta, str):
        raise ValueError(
            f"response.audio.delta requires a base64 string 'delta' field, got {delta!r}"
        )
    return base64.b64decode(delta)


def _build_session_update_event(*, sample_rate: int = _DEFAULT_SAMPLE_RATE) -> dict:
    """The ``session.update`` handshake event: ``server_vad`` turn detection, PCM16."""
    return {
        "type": _EVENT_SESSION_UPDATE,
        "session": {
            "turn_detection": {"type": _TURN_DETECTION_SERVER_VAD},
            "input_audio_format": _AUDIO_FORMAT_PCM16,
            "input_audio_sample_rate": sample_rate,
        },
    }


def _bearer_headers(api_key: str) -> list:
    """``["Authorization: Bearer <key>"]``, or ``[]`` when *api_key* is empty."""
    if not api_key:
        return []
    return [f"Authorization: Bearer {api_key}"]


class RealtimeSession:
    """An open ears-only realtime session: one WebSocket + one receive pump.

    Construct via :func:`open_session`, never directly — the constructor
    assumes *ws* is already connected and the ``session.update`` handshake
    already sent. Call :meth:`start` once to spawn the receive pump, then
    :meth:`send_audio` per captured PCM16 chunk (task t4 wires a real mic);
    :meth:`close` stops the pump (bounded join) and closes the socket.

    Two ways to consume a transcript, both driven from the SAME event (a
    caller may use either or both): the ``on_transcript`` callback passed to
    :func:`open_session`, and the :attr:`transcripts` queue this object owns.

    ``mute``/``unmute`` are the half-duplex gate hook task t4 needs: while
    muted, :meth:`send_audio` is a silent no-op (so playing the assistant's
    own synthesized reply back over a speaker never gets picked back up by
    the mic and re-sent) — the receive pump itself is UNAFFECTED by muting;
    VAD/transcription events keep flowing either way.
    """

    def __init__(
        self,
        ws: Any,
        *,
        on_transcript: Optional[Callable[[str], None]] = None,
        on_event: Optional[Callable[[dict], None]] = None,
    ) -> None:
        self._ws = ws
        self._on_transcript: Callable[[str], None] = on_transcript or (lambda _text: None)
        self._on_event: Callable[[dict], None] = on_event or (lambda _event: None)

        #: Every completed transcript, in arrival order — this object's own
        #: queue, so a caller with no callback wired can still poll it.
        self.transcripts: "queue.Queue[str]" = queue.Queue()

        self._send_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._mute_event = threading.Event()
        self._degraded_event = threading.Event()
        self._degrade_reason: Optional[str] = None
        self._thread = threading.Thread(
            target=self._pump, name="colleague-realtime-pump", daemon=True
        )

    def start(self) -> None:
        """Spawn the ONE receive-pump thread. Call exactly once, after connecting."""
        self._thread.start()

    # -- half-duplex gate (task t4 drives this while TTS plays back) -------

    def mute(self) -> None:
        """Gate :meth:`send_audio` closed — a no-op until :meth:`unmute`."""
        self._mute_event.set()

    def unmute(self) -> None:
        """Re-open the :meth:`send_audio` gate."""
        self._mute_event.clear()

    @property
    def muted(self) -> bool:
        return self._mute_event.is_set()

    # -- audio in ------------------------------------------------------------

    def send_audio(self, pcm16_bytes: bytes) -> bool:
        """Base64-wrap *pcm16_bytes* into ``input_audio_buffer.append`` and send it.

        Returns ``False`` without sending anything when muted or the session
        has already degraded — never raises. A send failure degrades the
        session in place (one stderr notice) rather than propagating.
        """
        if self._mute_event.is_set() or self._degraded_event.is_set():
            return False
        try:
            event = encode_audio_append_event(pcm16_bytes)
            with self._send_lock:
                self._ws.send(json.dumps(event))
            return True
        except Exception as exc:  # noqa: BLE001 - degrade-never-raise
            self._degrade(f"send failed ({type(exc).__name__})")
            return False

    # -- lifecycle -----------------------------------------------------------

    @property
    def degraded(self) -> bool:
        """``True`` once the receive pump has fallen back to the turn-based path."""
        return self._degraded_event.is_set()

    @property
    def degrade_reason(self) -> Optional[str]:
        """The reason :attr:`degraded` flipped, or ``None`` while still connected."""
        return self._degrade_reason

    def close(self, *, timeout: float = _JOIN_TIMEOUT_SECONDS) -> None:
        """Stop the pump (bounded join) and close the socket. Idempotent; never raises.

        ``ws.close()`` is passed its own bounded ``timeout`` too — left to its
        library default (3s), a peer that never acks the close frame (e.g. one
        that already vanished, exactly the mid-session-kill case) would make
        THIS call hang well past the pump's own bounded join, defeating the
        "teardown never hangs" discipline this method exists to uphold.
        """
        self._stop_event.set()
        _bounded_join(self._thread, timeout=timeout)
        with contextlib.suppress(Exception):
            self._ws.close(timeout=_WS_CLOSE_TIMEOUT_SECONDS)

    # -- receive pump (the ONE sanctioned thread body) ------------------------

    def _degrade(self, reason: str) -> None:
        """Flip to the degraded state and print exactly ONE stderr notice."""
        if self._degraded_event.is_set():
            return
        self._degraded_event.set()
        self._degrade_reason = reason
        _notice(f"realtime session degraded to the turn-based path ({reason})")

    def _pump(self) -> None:
        """The receive-pump thread body: poll-wake via ``ws.settimeout``, degrade on failure.

        Never raises past this method — every recv failure (timeout aside)
        degrades the session in place and returns, ending the thread.
        """
        ws = self._ws
        try:
            while not self._stop_event.is_set():
                try:
                    raw = ws.recv()
                except Exception as exc:  # noqa: BLE001 - classified below
                    if _is_recv_timeout(exc):
                        continue  # poll-wake tick — re-check the stop event.
                    self._degrade(f"connection closed ({type(exc).__name__})")
                    return
                if not raw:
                    # An empty read with no exception: the server sent (and
                    # this client auto-acked) a CLOSE frame.
                    self._degrade("connection closed (server sent a close frame)")
                    return
                self._handle_raw(raw)
        except Exception as exc:  # noqa: BLE001 - the pump must never crash the process
            self._degrade(f"pump crashed ({type(exc).__name__})")

    def _handle_raw(self, raw: Any) -> None:
        if isinstance(raw, bytes):
            return  # this wire never sends binary frames — ignored defensively.
        try:
            event = json.loads(raw)
        except (TypeError, ValueError):
            return  # a malformed text frame is ignored, never crashes the pump.
        if not isinstance(event, dict):
            return
        with contextlib.suppress(Exception):
            self._on_event(event)
        if event.get("type") == _EVENT_TRANSCRIPTION_COMPLETED:
            text = event.get("text")
            if isinstance(text, str):
                self.transcripts.put(text)
                with contextlib.suppress(Exception):
                    self._on_transcript(text)
        # Any response.* event (this session never triggers one, but a
        # nonconformant/future server might still emit one) is deliberately
        # NOT acted on here — see the module docstring's ears-only section.


def _is_recv_timeout(exc: Exception) -> bool:
    """True when *exc* is the poll-wake timeout, not a real disconnect.

    Duck-typed on the exception's class name rather than importing
    ``websocket`` at module level (this function may be called from a pump
    thread whose ``websocket`` module reference is already lazily imported by
    :func:`open_session`, but this helper itself must stay import-clean).
    """
    return type(exc).__name__ == "WebSocketTimeoutException"


def open_session(
    config: "Optional[RealtimeConfig]" = None,
    *,
    on_transcript: Optional[Callable[[str], None]] = None,
    on_event: Optional[Callable[[dict], None]] = None,
    sample_rate: int = _DEFAULT_SAMPLE_RATE,
) -> Optional[RealtimeSession]:
    """Dial *config*'s realtime session and return a started :class:`RealtimeSession`.

    Consumes :class:`colleague.config.RealtimeConfig` verbatim — this
    function never re-resolves an env var or a config.json section itself.

    Two failure classes, handled deliberately differently (see the module
    docstring): the ``[voice]`` extra missing raises a clean
    :class:`CliError` (checked FIRST, before *config* is even read);
    *config* being ``None`` (nothing resolved to dial — the
    ``EngineConfig.realtime is None`` contract) or any dial/handshake failure
    returns ``None`` with ONE stderr notice, never raising.
    """
    ws_module = _import_ws()
    if config is None:
        return None
    headers = _bearer_headers(config.api_key)
    try:
        ws = ws_module.create_connection(
            config.ws_url, timeout=_CONNECT_TIMEOUT_SECONDS, header=headers
        )
    except Exception as exc:  # noqa: BLE001 - degrade-never-raise
        _notice(
            f"realtime dial failed ({type(exc).__name__}) — falling back to the turn-based path"
        )
        return None
    try:
        ws.send(json.dumps(_build_session_update_event(sample_rate=sample_rate)))
        ws.settimeout(_RECV_POLL_SECONDS)
    except Exception as exc:  # noqa: BLE001 - degrade-never-raise
        _notice(
            f"realtime handshake failed ({type(exc).__name__}) — "
            "falling back to the turn-based path"
        )
        with contextlib.suppress(Exception):
            ws.close()
        return None

    session = RealtimeSession(ws, on_transcript=on_transcript, on_event=on_event)
    session.start()
    return session
