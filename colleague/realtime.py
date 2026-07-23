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

Continuous audio: capture, playback, the half-duplex gate (plan task t4)
--------------------------------------------------------------------------
Task t3 above wired the WS session; this task wires actual sound to and from
it. Three pieces, all in THIS module (sequential by design — the plan groups
t3+t4 in one file):

* :func:`start_capture` — opens a mono PCM16 ``sounddevice.InputStream`` at
  :data:`_DEFAULT_SAMPLE_RATE` (24kHz, the bridge's own ``CLIENT_SAMPLE_RATE``
  — see ``../lobes-cli/lobes/realtime/protocol.py``) and forwards every
  captured frame into a :class:`RealtimeSession` via :meth:`RealtimeSession.
  send_audio`. Captured **directly as int16** (``dtype="int16"``) rather than
  float32-then-converted — the plan brief permits either
  ("float32->int16 (or capture int16 directly)"); requesting int16 straight
  from PortAudio needs no numpy arithmetic on this module's side at all,
  which keeps the capture path exactly as thin as the WS codec above. The
  samplerate is requested directly from the device (the "or configure"
  half of "resample-or-configure to 24000 Hz") — no resampler is implemented;
  a device that cannot open at 24kHz degrades like any other bad device (see
  below), it does not silently resample.
* :func:`play_wav_bytes` — plays a WAV (bytes or a path) through
  ``sounddevice.play``/``wait``, **holding the half-duplex gate** for the
  whole duration (:meth:`RealtimeSession.mute` before the first sample,
  :meth:`RealtimeSession.unmute` after the last — never leaving the gate
  held past playback, even on failure).
* The half-duplex gate itself is :class:`RealtimeSession`'s existing
  ``threading.Event`` (``mute``/``unmute``/``muted``, t3) — t4 adds no new
  gate primitive, it adds the two callers that actually hold it. The check
  is STRUCTURAL and belongs to the CAPTURE side: :func:`_forward_captured_frame`
  checks :attr:`RealtimeSession.muted` and returns WITHOUT calling
  ``send_audio`` at all while held — a captured frame during playback is
  dropped before it ever reaches the encode step, the send lock, or the
  wire (``RealtimeSession.send_audio`` itself *also* checks ``muted`` — t3's
  own belt; this is the capture lane's suspenders, and the seam
  ``tests/test_realtime_devices.py`` drives directly with synthetic frames,
  no PortAudio involved, per the plan's own "design the seams so logic is
  provable without PortAudio" method note).

Client-edge mute, not an AEC substitute banned elsewhere
-----------------------------------------------------------
``../lobes-cli``'s Astro browser client (``site/src/scripts/mic-capture.ts``)
deliberately does NOT auto-mute during playback — deviation d1 there records
that the browser's own ``echoCancellation`` constraint owns AEC, and an
automatic mute would defeat barge-in. This machine's actual hardware
(Reachy Mini USB audio, an Arducam mic, an HDMI sink) has no such
echo-cancelling front end reachable from Python/PortAudio, so the SAME
deviation d1 places the AEC-substitute responsibility at exactly this
client edge instead (see ``../lobes-cli/scripts/realtime-voice-loop.py``'s
own ``muted = threading.Event()`` mic-feed gate, the direct precedent this
module's gate mirrors) — colleague's mute here is that substitute, not a
violation of the browser-side ban (a different client, a different hardware
reality, the same documented rationale).

Nested/sequential holds: never unmute out from under an outer caller
-------------------------------------------------------------------------
:func:`play_wav_bytes` only calls :meth:`RealtimeSession.unmute` in its
``finally`` block when THIS call is the one that transitioned the gate
closed (``already_muted`` was ``False`` on entry) — a caller stitching a
multi-segment spoken reply together (mute once, call
:func:`play_wav_bytes` once per segment, unmute once at the very end) never
sees the gate flicker open between segments, which is what "a queued/
duplicate playback never lets frames leak between segments" requires.

Device selection: never assume device 0
-------------------------------------------
:func:`_resolve_device` resolves :class:`~colleague.config.RealtimeConfig`'s
``input_device``/``output_device`` (a PortAudio index as a numeric string, or
a case-insensitive name substring — e.g. ``"Reachy Mini"``, ``"Arducam"``)
against ``sounddevice.query_devices()``, filtered by the requested kind
(``max_input_channels`` / ``max_output_channels`` > 0) so a name that only
exists as the WRONG kind of device never silently matches. ``None``/blank
resolves to ``None`` — the library's own default, never a hardcoded index
(this machine alone has at least: HDMI outputs 0-3, a Reachy Mini USB capture
device, an Arducam capture device, and PipeWire's own aggregate/default
nodes — "device 0" is a genuinely different piece of hardware on every box).
A device that fails to open (a bad id, an unmatched name, a PortAudioError)
is caught by :func:`start_capture`/:func:`play_wav_bytes` and degrades with
exactly ONE ``colleague: ...`` stderr notice NAMING the configured value —
never a traceback, and the session itself stays usable in the turn-based/
text lane either way (this is additive to :class:`RealtimeSession`, not a
replacement for it).
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
        """Flip to the degraded state and print exactly ONE stderr notice.

        A failure that lands DURING teardown (``close()`` shuts the socket
        under the pump, whose recv then errors) is not a degradation the
        operator can act on — the state still flips (callers may read
        ``.degraded``), but the notice is suppressed so "degraded" never
        prints after ``close()`` returned.
        """
        if self._degraded_event.is_set():
            return
        self._degraded_event.set()
        self._degrade_reason = reason
        if not self._stop_event.is_set():
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

    Prefers a real ``isinstance`` check against the class from the
    already-imported ``websocket`` module (looked up via ``sys.modules`` so
    this helper itself stays import-clean — it may run on the pump thread
    after :func:`open_session` lazily imported the package), falling back to
    the class-name comparison only when that lookup yields nothing (e.g. a
    test double raising a same-named exception).
    """
    ws_mod = sys.modules.get("websocket")
    timeout_cls = getattr(ws_mod, "WebSocketTimeoutException", None) if ws_mod else None
    if isinstance(timeout_cls, type) and isinstance(exc, timeout_cls):
        return True
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
        # Bounded exactly like RealtimeSession.close() — a peer that never acks
        # the close frame must not hang the failure path either (see that
        # method's docstring for why the library default 3s is too long).
        with contextlib.suppress(Exception):
            ws.close(timeout=_WS_CLOSE_TIMEOUT_SECONDS)
        return None

    session = RealtimeSession(ws, on_transcript=on_transcript, on_event=on_event)
    session.start()
    return session


# ---------------------------------------------------------------------------
# Continuous audio streams + the half-duplex gate + device selection
# (realtime-speech arc, plan task t4). Same module as the WS client above,
# sequential by design — see the module docstring's "Continuous audio"
# section for the full rationale.
# ---------------------------------------------------------------------------

_DEVICE_INSTALL_HINT = _INSTALL_HINT  # same [voice] extra covers sounddevice/soundfile too.


def _import_sounddevice() -> Any:
    """Lazily import ``sounddevice`` only (mic capture needs no WAV container —
    just raw PCM16 frames straight off the device, so ``soundfile`` is not
    needed here). Mirrors :func:`_import_ws`/``colleague.voice_devices.
    _import_audio``: raises a clean :class:`CliError` naming
    ``pip install colleague[voice]`` when the extra is absent, never a raw
    ``ImportError``.
    """
    try:
        import sounddevice  # type: ignore

        return sounddevice
    except Exception as exc:  # noqa: BLE001 - any import failure names the extra
        raise CliError(
            1,
            f"realtime audio device support is not installed ({type(exc).__name__})",
            remediation=_DEVICE_INSTALL_HINT,
        ) from exc


def _import_sounddevice_and_soundfile() -> Any:
    """Lazily import BOTH ``sounddevice`` and ``soundfile`` (playback needs
    ``soundfile`` to decode the WAV container before ``sounddevice`` can play
    the raw samples). Returns ``(sounddevice, soundfile)``; raises a clean
    :class:`CliError` naming ``pip install colleague[voice]`` when either is
    absent — mirrors :func:`_import_sounddevice`.
    """
    try:
        import sounddevice  # type: ignore
        import soundfile  # type: ignore

        return sounddevice, soundfile
    except Exception as exc:  # noqa: BLE001 - any import failure names the extra
        raise CliError(
            1,
            f"realtime audio device support is not installed ({type(exc).__name__})",
            remediation=_DEVICE_INSTALL_HINT,
        ) from exc


def _resolve_device(sounddevice_module: Any, value: Optional[str], *, kind: str) -> Any:
    """Resolve *value* (a PortAudio id, a name substring, or ``None``) to
    whatever sounddevice's own ``device=`` kwarg accepts, for the given
    *kind* (``"input"`` or ``"output"``).

    ``None`` or a blank/whitespace-only string resolves to ``None`` — the
    audio library's own default device, NEVER a hard-coded index (see the
    module docstring's "Device selection: never assume device 0" section). A
    purely-numeric string (e.g. ``"2"``, allowing a leading ``-``) resolves
    to that integer PortAudio index directly. Anything else is matched as a
    CASE-INSENSITIVE SUBSTRING against ``sounddevice_module.query_devices()``'s
    device names, restricted to devices that support *kind* (an ``"input"``
    match requires ``max_input_channels > 0``, an ``"output"`` match requires
    ``max_output_channels > 0`` — a name that only exists as the wrong kind of
    device never silently matches); the first match (lowest index) wins.

    Raises :class:`ValueError` when a non-blank name matches no device of the
    right kind — the caller (:func:`start_capture`/:func:`play_wav_bytes`)
    catches this alongside any ``PortAudioError`` from actually opening the
    stream and degrades with ONE stderr notice naming *value*; this function
    itself never prints anything and never degrades on its own.
    """
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    bare = stripped[1:] if stripped[0] == "-" else stripped
    if bare.isdigit():
        return int(stripped)
    channel_key = "max_input_channels" if kind == "input" else "max_output_channels"
    needle = stripped.lower()
    for index, info in enumerate(sounddevice_module.query_devices()):
        name = str(info.get("name", ""))
        channels = info.get(channel_key, 0)
        if channels and channels > 0 and needle in name.lower():
            return index
    raise ValueError(f"no {kind} device matching {value!r}")


def _forward_captured_frame(session: RealtimeSession, pcm16_bytes: bytes) -> bool:
    """Forward one captured PCM16 mono frame to *session* — UNLESS the
    half-duplex gate is held.

    THE structural half-duplex check (see the module docstring): while
    :attr:`RealtimeSession.muted` is ``True`` (the playback lane is holding
    the gate via :func:`play_wav_bytes`), this returns ``False`` WITHOUT
    calling :meth:`RealtimeSession.send_audio` at all — the captured frame is
    dropped before it ever reaches the encode step, the send lock, or the
    wire. ``RealtimeSession.send_audio`` has its own internal mute check too
    (t3's own belt); this is the capture lane's suspenders, and it is the
    exact seam ``tests/test_realtime_devices.py`` drives directly with
    synthetic frames — no PortAudio, no real device — to pin "zero frames
    forwarded during a synthetic playback window".
    """
    if session.muted:
        return False
    return session.send_audio(pcm16_bytes)


def _make_capture_callback(session: RealtimeSession) -> Callable[[Any, int, Any, Any], None]:
    """Build the ``sounddevice.InputStream`` callback that forwards each
    captured frame to *session* via :func:`_forward_captured_frame`.

    Extracted as its own function (not an inline closure body) so tests can
    drive it directly with synthetic ``indata`` values — no PortAudio, no
    real device involved (see ``tests/test_realtime_devices.py``). The
    callback itself must NEVER raise past this boundary: a raising
    ``sounddevice`` stream callback kills the whole audio stream, so any
    conversion/forwarding failure is swallowed here (mirrors this module's
    degrade-never-raise stance everywhere else).
    """

    def _callback(indata: Any, _frames: int, _time_info: Any, _status: Any) -> None:
        with contextlib.suppress(Exception):
            _forward_captured_frame(session, bytes(indata))

    return _callback


class CaptureHandle:
    """A started capture stream returned by :func:`start_capture`.

    Wraps the underlying ``sounddevice`` stream so a caller holds ONE object
    for the capture lane's lifecycle. PortAudio owns the actual audio
    thread/callback invocation (see the module docstring's thread-sanction
    rationale in ``tests/test_boundary.py``) — this class spawns no
    ``threading.Thread`` of its own; it only owns start/stop of the stream.
    """

    def __init__(self, stream: Any) -> None:
        self._stream = stream

    def stop(self) -> None:
        """Stop and close the underlying stream. Idempotent; never raises."""
        with contextlib.suppress(Exception):
            self._stream.stop()
        with contextlib.suppress(Exception):
            self._stream.close()


def start_capture(
    session: RealtimeSession,
    config: "Optional[RealtimeConfig]" = None,
    *,
    samplerate: int = _DEFAULT_SAMPLE_RATE,
    blocksize: int = 0,
) -> Optional[CaptureHandle]:
    """Open a mono int16 PCM16 capture stream at *samplerate* Hz (default
    :data:`_DEFAULT_SAMPLE_RATE`, 24kHz — the bridge's ``CLIENT_SAMPLE_RATE``)
    and start forwarding every captured frame into *session* (gated by the
    half-duplex mute — see :func:`_forward_captured_frame`).

    Device resolves from ``config.input_device`` (an id or a name substring;
    see :func:`_resolve_device`) — absent/``None`` config resolves to the
    ``sounddevice`` library's own default input device.

    Two failure classes, deliberately different (mirrors :func:`open_session`
    and ``colleague.voice_devices.record``): the ``[voice]`` extra missing
    raises a clean :class:`CliError` naming ``pip install colleague[voice]``
    (checked FIRST, before *config* is even read — starting capture is a
    deliberate operator action that genuinely cannot proceed without the
    extra). Once the extra IS installed, a bad/missing device (a
    ``PortAudioError``, an unmatched name — anything :func:`_resolve_device`
    or opening the stream itself raises) degrades: ONE ``colleague: ...``
    stderr notice naming the configured device value, and returns ``None`` —
    never a traceback, and *session* itself stays usable in the turn-based/
    text lane (this is additive, not a replacement).
    """
    sounddevice = _import_sounddevice()
    device_value = config.input_device if config is not None else None
    try:
        device = _resolve_device(sounddevice, device_value, kind="input")
        stream = sounddevice.InputStream(
            samplerate=samplerate,
            channels=1,
            dtype="int16",
            device=device,
            blocksize=blocksize,
            callback=_make_capture_callback(session),
        )
        stream.start()
    except Exception as exc:  # noqa: BLE001 - degrade-never-raise at the device boundary
        _notice(
            f"realtime capture device unavailable (input_device={device_value!r}, "
            f"{type(exc).__name__}) — falling back to the turn-based path"
        )
        return None
    return CaptureHandle(stream)


def _read_wav(soundfile_module: Any, wav: Any) -> tuple[Any, int]:
    """Decode *wav* (raw WAV bytes, or a path) via *soundfile_module*, returning
    ``(samples, samplerate)`` exactly as ``soundfile.read`` returns them.

    Raw ``bytes``/``bytearray`` is wrapped in an in-memory buffer (``soundfile``
    needs a seekable file-like object, not a bare ``bytes``); a path
    (``str``/``os.PathLike``) is passed straight through — ``soundfile``
    already accepts either directly.
    """
    if isinstance(wav, (bytes, bytearray)):
        import io

        return soundfile_module.read(io.BytesIO(bytes(wav)))
    return soundfile_module.read(wav)


def play_wav_bytes(
    session: RealtimeSession,
    wav: Any,
    config: "Optional[RealtimeConfig]" = None,
) -> bool:
    """Play a WAV (raw bytes or a path) through ``sounddevice``, HOLDING
    *session*'s half-duplex gate for the whole duration.

    :meth:`RealtimeSession.mute` fires before the first sample plays;
    :meth:`RealtimeSession.unmute` fires after the last sample finishes (in a
    ``finally``, so a mid-playback failure still releases the gate — this
    function never leaves a session permanently deaf). Nested/sequential-safe
    (see the module docstring): if *session* was ALREADY muted on entry (an
    outer caller stitching a multi-segment reply together), this call does
    NOT unmute at the end — only the call that actually closed the gate
    reopens it, so "a queued/duplicate playback never lets frames leak
    between segments."

    Device resolves from ``config.output_device`` (see :func:`_resolve_device`)
    — absent/``None`` config resolves to the ``sounddevice`` library's own
    default output device.

    Degrade-never-raise, ADDITIVE (mirrors ``colleague.voice_devices.play``):
    a missing ``[voice]`` extra, a bad/missing device, or any playback error
    prints ONE ``colleague: ...`` stderr notice and returns ``False`` — never
    raises. The missing-extra case is checked BEFORE *session* is touched at
    all (so the gate is never spuriously toggled when nothing can play).
    """
    try:
        sounddevice, soundfile = _import_sounddevice_and_soundfile()
    except CliError as exc:
        _notice(
            f"realtime playback unavailable ({exc}, {exc.remediation}) — "
            "falling back to the turn-based path"
        )
        return False
    device_value = config.output_device if config is not None else None
    # TOCTOU note: between reading ``session.muted`` and ``session.mute()``
    # a PortAudio callback could forward at most ONE already-in-flight frame
    # (~1.7ms of audio at 24kHz int16 blocks) — far below the server VAD's
    # speech threshold, so the gate stays effective without a lock around
    # the transition; ``send_audio``'s own mute re-check narrows it further.
    already_muted = session.muted
    session.mute()
    try:
        data, samplerate = _read_wav(soundfile, wav)
        device = _resolve_device(sounddevice, device_value, kind="output")
        sounddevice.play(data, samplerate, device=device)
        sounddevice.wait()
        return True
    except Exception as exc:  # noqa: BLE001 - degrade-never-raise
        _notice(
            f"realtime playback failed (output_device={device_value!r}, "
            f"{type(exc).__name__}) — falling back to the turn-based path"
        )
        return False
    finally:
        if not already_muted:
            session.unmute()
