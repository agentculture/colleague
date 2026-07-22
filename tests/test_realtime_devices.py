"""Task t4 (realtime-speech arc): continuous audio streams, the half-duplex
gate, and device selection.

Needs the ``[voice]`` extra importable (``sounddevice``) — gated via
``pytest.importorskip`` below, mirroring tests/test_realtime_client.py's own
whole-file gate for websocket-client (CI runs a plain ``uv sync`` with no
extras, so this file skips cleanly there; the absence-degrade pins live in
tests/test_realtime.py instead, which needs NO extra — see that file's
docstring for the same split rationale).

NO PortAudio hardware is used anywhere in this file, and none is required:
every test drives colleague.realtime's PURE seams directly
(``_resolve_device``, ``_forward_captured_frame``, ``_make_capture_callback``)
or monkeypatches the module's lazy ``_import_sounddevice``/
``_import_sounddevice_and_soundfile`` functions with a FAKE in-process
stand-in. Real-device tests are explicitly OUT of scope for CI (the plan
task t4 brief's own method note: "design the seams so logic is provable
without PortAudio") — this file is that proof.
"""

from __future__ import annotations

from typing import Any

import pytest

sounddevice = pytest.importorskip("sounddevice")

from colleague import realtime  # noqa: E402
from colleague.config import RealtimeConfig  # noqa: E402


class _FakeSession:
    """A minimal stand-in for RealtimeSession: just the half-duplex gate and
    a call log — no real WebSocket, no real audio, anywhere."""

    def __init__(self, *, muted: bool = False) -> None:
        self._muted = muted
        self.sent: list[bytes] = []

    def mute(self) -> None:
        self._muted = True

    def unmute(self) -> None:
        self._muted = False

    @property
    def muted(self) -> bool:
        return self._muted

    def send_audio(self, pcm16_bytes: bytes) -> bool:
        if self._muted:
            return False
        self.sent.append(pcm16_bytes)
        return True


class _FakeDevices:
    """A fake ``sounddevice``-shaped module exposing only ``query_devices()``
    — everything :func:`colleague.realtime._resolve_device` needs."""

    def __init__(self, devices: list[dict]) -> None:
        self._devices = devices

    def query_devices(self):
        return self._devices


# ---------------------------------------------------------------------------
# The half-duplex gate: structurally proven with synthetic frames, no
# hardware, no timing assumptions — the ACCEPT criterion's "test pins the
# event stream over a synthetic playback window".
# ---------------------------------------------------------------------------


def test_forward_captured_frame_sends_when_unmuted() -> None:
    session = _FakeSession()
    assert realtime._forward_captured_frame(session, b"\x01\x02") is True
    assert session.sent == [b"\x01\x02"]


def test_forward_captured_frame_drops_when_muted() -> None:
    session = _FakeSession(muted=True)
    assert realtime._forward_captured_frame(session, b"\x01\x02") is False
    assert session.sent == []


def test_synthetic_playback_window_forwards_zero_captured_frames() -> None:
    """A stream of captured frames arrives continuously; a synthetic playback
    window mutes partway through and unmutes partway after — ZERO frames
    forwarded strictly inside the muted window, frames before and after ARE
    forwarded. This is the structural pin: half-duplex holds over a
    synthetic playback window with no real audio device anywhere."""
    session = _FakeSession()
    frames = [f"frame-{i}".encode() for i in range(10)]

    forwarded = []
    for i, frame in enumerate(frames):
        if i == 3:
            session.mute()  # the playback lane starts holding the gate
        if i == 7:
            session.unmute()  # playback ends, gate released
        if realtime._forward_captured_frame(session, frame):
            forwarded.append(frame)

    # Frames 0,1,2 (before mute) and 7,8,9 (unmuted at i==7, then forwarded)
    # go through; the muted window 3,4,5,6 forwards NOTHING.
    assert forwarded == [frames[0], frames[1], frames[2], frames[7], frames[8], frames[9]]
    assert session.sent == forwarded
    assert len(forwarded) == 6
    # The muted window itself: exactly zero of frames[3:7] appear anywhere.
    for muted_frame in frames[3:7]:
        assert muted_frame not in forwarded


def test_capture_callback_routes_through_forward_captured_frame(monkeypatch) -> None:
    """The InputStream callback must route through _forward_captured_frame
    (the one structural gate check), not call session.send_audio directly."""
    session = _FakeSession()
    calls: list[bytes] = []
    monkeypatch.setattr(
        realtime,
        "_forward_captured_frame",
        lambda _session, frame: calls.append(frame) or True,
    )
    callback = realtime._make_capture_callback(session)
    callback(b"\x00\x01\x02\x03", 2, None, None)
    assert calls == [b"\x00\x01\x02\x03"]


def test_capture_callback_never_raises_on_bad_indata() -> None:
    """A malformed/unexpected indata object must never crash the PortAudio
    callback thread — a raising audio callback kills the whole stream."""
    session = _FakeSession()
    callback = realtime._make_capture_callback(session)
    callback(object(), 0, None, None)  # bytes(object()) raises TypeError
    assert session.sent == []  # nothing forwarded, and no exception escaped


# ---------------------------------------------------------------------------
# Device resolution: never assume device 0; a wrong kind never matches.
# ---------------------------------------------------------------------------


def test_resolve_device_none_is_library_default() -> None:
    assert realtime._resolve_device(_FakeDevices([]), None, kind="input") is None


def test_resolve_device_blank_is_library_default() -> None:
    assert realtime._resolve_device(_FakeDevices([]), "   ", kind="input") is None


def test_resolve_device_numeric_string_resolves_to_int() -> None:
    assert realtime._resolve_device(_FakeDevices([]), "3", kind="output") == 3


_THIS_MACHINE_DEVICES = [
    {"name": "NVIDIA: HDMI 0 (hw:0,3)", "max_input_channels": 0, "max_output_channels": 8},
    {
        "name": "Reachy Mini Audio: USB Audio (hw:1,0)",
        "max_input_channels": 2,
        "max_output_channels": 0,
    },
    {"name": "Arducam_12MP: USB Audio (hw:2,0)", "max_input_channels": 2, "max_output_channels": 0},
    {"name": "hdmi", "max_input_channels": 0, "max_output_channels": 8},
]


def test_resolve_device_name_substring_matches_input_device() -> None:
    assert (
        realtime._resolve_device(_FakeDevices(_THIS_MACHINE_DEVICES), "Reachy", kind="input") == 1
    )
    assert (
        realtime._resolve_device(_FakeDevices(_THIS_MACHINE_DEVICES), "Arducam", kind="input") == 2
    )


def test_resolve_device_name_substring_is_case_insensitive() -> None:
    result = realtime._resolve_device(
        _FakeDevices(_THIS_MACHINE_DEVICES), "arducam_12mp", kind="input"
    )
    assert result == 2


def test_resolve_device_name_filters_by_kind() -> None:
    """A name that only exists as an INPUT device must not match an OUTPUT
    query — never assume device 0 / never assume kind."""
    with pytest.raises(ValueError, match="Arducam"):
        realtime._resolve_device(_FakeDevices(_THIS_MACHINE_DEVICES), "Arducam", kind="output")


def test_resolve_device_unmatched_name_raises_value_error() -> None:
    with pytest.raises(ValueError, match="nonexistent-device"):
        realtime._resolve_device(_FakeDevices([]), "nonexistent-device", kind="input")


# ---------------------------------------------------------------------------
# start_capture: success path (fake stream, no hardware) + device degrade.
# ---------------------------------------------------------------------------


class _FakeInputStream:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.started = False
        self.stopped = False
        self.closed = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def close(self) -> None:
        self.closed = True


class _FakeSounddeviceModule:
    def __init__(self, devices: list[dict], *, raise_on_stream: Exception | None = None) -> None:
        self._devices = devices
        self._raise_on_stream = raise_on_stream
        self.created_streams: list[_FakeInputStream] = []

    def query_devices(self):
        return self._devices

    def InputStream(self, **kwargs: Any) -> _FakeInputStream:
        if self._raise_on_stream is not None:
            raise self._raise_on_stream
        stream = _FakeInputStream(**kwargs)
        self.created_streams.append(stream)
        return stream


def test_start_capture_opens_stream_with_resolved_device_and_starts_it(monkeypatch) -> None:
    fake_sd = _FakeSounddeviceModule(_THIS_MACHINE_DEVICES)
    monkeypatch.setattr(realtime, "_import_sounddevice", lambda: fake_sd)
    session = _FakeSession()
    config = RealtimeConfig(
        available=True, ws_url="ws://x/v1/realtime", api_key="", input_device="Reachy"
    )

    handle = realtime.start_capture(session, config)

    assert handle is not None
    assert len(fake_sd.created_streams) == 1
    stream = fake_sd.created_streams[0]
    assert stream.started is True
    assert stream.kwargs["device"] == 1  # resolved index for "Reachy"
    assert stream.kwargs["samplerate"] == realtime._DEFAULT_SAMPLE_RATE
    assert stream.kwargs["channels"] == 1
    assert stream.kwargs["dtype"] == "int16"
    assert callable(stream.kwargs["callback"])

    handle.stop()
    assert stream.stopped is True
    assert stream.closed is True


def test_start_capture_no_config_uses_library_default_device(monkeypatch) -> None:
    fake_sd = _FakeSounddeviceModule([])
    monkeypatch.setattr(realtime, "_import_sounddevice", lambda: fake_sd)
    session = _FakeSession()

    handle = realtime.start_capture(session)

    assert handle is not None
    assert fake_sd.created_streams[0].kwargs["device"] is None


def test_start_capture_unmatched_device_name_degrades_with_one_notice(monkeypatch, capsys) -> None:
    fake_sd = _FakeSounddeviceModule([])  # no devices at all -> name never matches
    monkeypatch.setattr(realtime, "_import_sounddevice", lambda: fake_sd)
    session = _FakeSession()
    config = RealtimeConfig(
        available=True,
        ws_url="ws://x/v1/realtime",
        api_key="",
        input_device="totally-bogus-mic",
    )

    handle = realtime.start_capture(session, config)

    assert handle is None
    assert fake_sd.created_streams == []  # never got as far as opening a stream
    err = capsys.readouterr().err
    assert err.count("colleague:") == 1
    assert "totally-bogus-mic" in err


def test_start_capture_portaudio_error_degrades_with_one_notice(monkeypatch, capsys) -> None:
    class _FakePortAudioError(Exception):
        pass

    fake_sd = _FakeSounddeviceModule(
        _THIS_MACHINE_DEVICES, raise_on_stream=_FakePortAudioError("device busy")
    )
    monkeypatch.setattr(realtime, "_import_sounddevice", lambda: fake_sd)
    session = _FakeSession()
    config = RealtimeConfig(
        available=True, ws_url="ws://x/v1/realtime", api_key="", input_device="Reachy"
    )

    handle = realtime.start_capture(session, config)

    assert handle is None
    err = capsys.readouterr().err
    assert err.count("colleague:") == 1
    assert "Reachy" in err
    assert "device unavailable" in err or "unavailable" in err


# ---------------------------------------------------------------------------
# play_wav_bytes: holds the gate for the whole duration, unmutes even on
# failure, never unmutes out from under an outer/already-muted caller, and
# degrades cleanly on a bad device.
# ---------------------------------------------------------------------------


class _FakeSoundfileModule:
    def __init__(self, *, samplerate: int = 24000, fail: Exception | None = None) -> None:
        self._samplerate = samplerate
        self._fail = fail
        self.read_calls = 0

    def read(self, _source: Any):
        self.read_calls += 1
        if self._fail is not None:
            raise self._fail
        return ("PCM-DATA", self._samplerate)


class _RecordingSounddeviceModule:
    def __init__(self, *, devices: list[dict] | None = None, fail_on_play: Exception | None = None):
        self._devices = devices or []
        self._fail_on_play = fail_on_play
        self.play_calls: list[tuple[Any, int, Any]] = []
        self.wait_calls = 0

    def query_devices(self):
        return self._devices

    def play(self, data: Any, samplerate: int, device: Any = None) -> None:
        if self._fail_on_play is not None:
            raise self._fail_on_play
        self.play_calls.append((data, samplerate, device))

    def wait(self) -> None:
        self.wait_calls += 1


def test_play_wav_bytes_holds_mute_for_the_whole_duration(monkeypatch) -> None:
    session = _FakeSession()
    order: list[str] = []
    orig_mute, orig_unmute = session.mute, session.unmute
    monkeypatch.setattr(session, "mute", lambda: (order.append("mute"), orig_mute()))
    monkeypatch.setattr(session, "unmute", lambda: (order.append("unmute"), orig_unmute()))

    fake_sf = _FakeSoundfileModule()
    fake_sd = _RecordingSounddeviceModule()

    def _record_play(data, samplerate, device=None):
        order.append("play")
        assert session.muted is True  # the gate is held DURING playback
        fake_sd.play_calls.append((data, samplerate, device))

    fake_sd.play = _record_play

    def _record_wait():
        order.append("wait")

    fake_sd.wait = _record_wait
    monkeypatch.setattr(realtime, "_import_sounddevice_and_soundfile", lambda: (fake_sd, fake_sf))

    ok = realtime.play_wav_bytes(session, b"RIFF....WAVEdata")

    assert ok is True
    assert order == ["mute", "play", "wait", "unmute"]
    assert session.muted is False
    assert fake_sd.play_calls == [("PCM-DATA", 24000, None)]


def test_play_wav_bytes_does_not_unmute_if_caller_already_held_the_gate(monkeypatch) -> None:
    """A caller stitching a multi-segment reply together (mute once, call
    play_wav_bytes per segment) must never see the gate reopen mid-reply —
    'a queued/duplicate playback never lets frames leak between segments'."""
    session = _FakeSession(muted=True)  # the OUTER caller already holds it
    fake_sf = _FakeSoundfileModule()
    fake_sd = _RecordingSounddeviceModule()
    monkeypatch.setattr(realtime, "_import_sounddevice_and_soundfile", lambda: (fake_sd, fake_sf))

    ok = realtime.play_wav_bytes(session, b"RIFF....WAVEdata")

    assert ok is True
    assert session.muted is True  # still held — this call did not release it


def test_play_wav_bytes_unmutes_even_on_playback_failure(monkeypatch, capsys) -> None:
    session = _FakeSession()
    fake_sf = _FakeSoundfileModule()
    fake_sd = _RecordingSounddeviceModule(fail_on_play=RuntimeError("playback boom"))
    monkeypatch.setattr(realtime, "_import_sounddevice_and_soundfile", lambda: (fake_sd, fake_sf))

    ok = realtime.play_wav_bytes(session, b"RIFF....WAVEdata")

    assert ok is False
    assert session.muted is False  # the gate is ALWAYS released, even on failure
    err = capsys.readouterr().err
    assert err.count("colleague:") == 1


def test_play_wav_bytes_bad_output_device_degrades_with_one_notice(monkeypatch, capsys) -> None:
    session = _FakeSession()
    config = RealtimeConfig(
        available=True,
        ws_url="ws://x/v1/realtime",
        api_key="",
        output_device="nonexistent-speaker",
    )
    fake_sf = _FakeSoundfileModule()
    fake_sd = _RecordingSounddeviceModule(devices=[])  # no devices -> name never matches
    monkeypatch.setattr(realtime, "_import_sounddevice_and_soundfile", lambda: (fake_sd, fake_sf))

    ok = realtime.play_wav_bytes(session, b"RIFF....WAVEdata", config)

    assert ok is False
    assert session.muted is False
    assert fake_sd.play_calls == []  # never got as far as playing
    err = capsys.readouterr().err
    assert err.count("colleague:") == 1
    assert "nonexistent-speaker" in err


def test_play_wav_bytes_soundfile_read_failure_degrades_and_unmutes(monkeypatch, capsys) -> None:
    session = _FakeSession()
    fake_sf = _FakeSoundfileModule(fail=ValueError("bad wav"))
    fake_sd = _RecordingSounddeviceModule()
    monkeypatch.setattr(realtime, "_import_sounddevice_and_soundfile", lambda: (fake_sd, fake_sf))

    ok = realtime.play_wav_bytes(session, b"not-a-real-wav")

    assert ok is False
    assert session.muted is False
    assert fake_sd.play_calls == []
    err = capsys.readouterr().err
    assert err.count("colleague:") == 1


def test_play_wav_bytes_accepts_a_path(monkeypatch, tmp_path) -> None:
    """A path (str or Path) is passed straight through to soundfile.read —
    only raw bytes get wrapped in an io.BytesIO buffer."""
    wav_path = tmp_path / "reply.wav"
    wav_path.write_bytes(b"RIFF....WAVEdata")
    fake_sf = _FakeSoundfileModule()
    fake_sd = _RecordingSounddeviceModule()
    monkeypatch.setattr(realtime, "_import_sounddevice_and_soundfile", lambda: (fake_sd, fake_sf))
    session = _FakeSession()

    ok = realtime.play_wav_bytes(session, wav_path)

    assert ok is True
    assert fake_sf.read_calls == 1
