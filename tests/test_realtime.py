"""Task t2 (realtime-speech arc): colleague/realtime.py packaging + import-cleanliness.

This is the boundary + packaging smoke test for the realtime speech client
stub — it does NOT test the live dial/session/pump behaviour against a real
socket (task t3 builds that and gets its own test file,
tests/test_realtime_client.py, which really does need websocket-client).
Mirrors ``tests/test_voice_devices.py`` exactly: a base install (the
``[voice]`` extra absent — see pyproject.toml's dev group, which never pins
sounddevice/soundfile/websocket-client) must import ``colleague.realtime``
cleanly and any call into it must degrade to a clean :class:`CliError`, never
a raw ``ImportError``/traceback.

Every test here is deliberately extra-INDEPENDENT (it blocks or fakes the
lazy import rather than gating the file), so it runs on every CI job — the
PR #356 triage lesson about whole-file ``importorskip`` gates hiding pins.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from colleague import realtime
from colleague.cli._errors import CliError
from colleague.config import RealtimeConfig


def test_module_imports_without_the_extra():
    """Importing colleague.realtime must NOT require websocket-client (lazy import)."""
    assert hasattr(realtime, "_import_ws")
    assert hasattr(realtime, "open_session")


def _block_voice_extra(monkeypatch):
    """Simulate the [voice] extra being ABSENT, env-independently.

    A ``None`` entry in ``sys.modules`` makes ``import websocket`` (etc.)
    raise ImportError even when the package IS installed (e.g. a dev venv
    synced with ``--extra voice``, or ``--all-extras``), so these degrade
    pins hold in every environment instead of asserting on the machine's
    installation state. monkeypatch restores the real entries on teardown.
    """
    for name in ("websocket", "sounddevice", "soundfile"):
        monkeypatch.setitem(sys.modules, name, None)


def test_module_pulls_in_no_third_party_import():
    """Importing colleague.realtime introduces no third-party top-level module.

    Runs in a HERMETIC subprocess so the verdict is about the module's own
    import graph — independent of whether the [voice] extra is installed in
    this venv and of whatever sibling test files already imported into this
    xdist worker's ``sys.modules``.
    """
    code = (
        "import sys; import colleague.realtime; " "sys.exit(1 if 'websocket' in sys.modules else 0)"
    )
    proc = subprocess.run(  # noqa: S603 - fixed argv, no untrusted input
        [sys.executable, "-c", code], capture_output=True, timeout=60
    )
    assert proc.returncode == 0, (
        "colleague.realtime must not pull in the websocket-client package "
        "merely by being imported"
    )


def test_open_session_without_extra_raises_clean_clierror(monkeypatch):
    """With [voice] absent (simulated), open_session raises a clean CliError naming the extra."""
    _block_voice_extra(monkeypatch)
    with pytest.raises(CliError) as exc:
        realtime.open_session()
    assert "colleague[voice]" in (exc.value.remediation or "")


def test_import_ws_without_extra_raises_clean_clierror(monkeypatch):
    _block_voice_extra(monkeypatch)
    with pytest.raises(CliError) as exc:
        realtime._import_ws()
    assert "colleague[voice]" in (exc.value.remediation or "")


def test_start_capture_without_extra_raises_clean_clierror(monkeypatch):
    """Task t4: starting capture is a deliberate operator action that
    genuinely cannot proceed without [voice] — mirrors open_session's own
    "extra missing raises a clean CliError" stance. Checked FIRST, before
    *session*/*config* are touched at all, so passing None here is safe."""
    _block_voice_extra(monkeypatch)
    with pytest.raises(CliError) as exc:
        realtime.start_capture(None)
    assert "colleague[voice]" in (exc.value.remediation or "")


def test_play_wav_bytes_without_extra_degrades_to_false(capsys, monkeypatch):
    """Task t4: playback is ADDITIVE (mirrors colleague.voice_devices.play) —
    a missing extra degrades to False + one stderr notice, never raises, and
    never touches *session* (checked before session.mute() would fire)."""
    _block_voice_extra(monkeypatch)
    ok = realtime.play_wav_bytes(None, b"RIFF....WAVEdata")
    assert ok is False
    err = capsys.readouterr().err
    assert "colleague[voice]" in err
    assert err.count("colleague:") == 1


def test_play_wav_bytes_local_without_extra_degrades_to_false(capsys, monkeypatch):
    """Task t8 (speak-only lane): play_wav_bytes_local takes NO session at
    all (there is no gate to touch), and degrades identically to
    play_wav_bytes on a missing [voice] extra — one honest notice, no raise."""
    _block_voice_extra(monkeypatch)
    ok = realtime.play_wav_bytes_local(b"RIFF....WAVEdata")
    assert ok is False
    err = capsys.readouterr().err
    assert "colleague[voice]" in err
    assert err.count("colleague:") == 1


class _HandshakeFailureWS:
    """A dialled socket whose handshake ``send`` fails — records how (and with
    which kwargs) ``open_session``'s failure path closes it."""

    def __init__(self) -> None:
        self.close_kwargs: dict | None = None

    def send(self, payload):
        raise RuntimeError("handshake boom")

    def settimeout(self, value):  # pragma: no cover - never reached
        raise AssertionError("settimeout must not run after send() failed")

    def close(self, **kwargs):
        self.close_kwargs = kwargs


def test_open_session_handshake_failure_closes_the_socket_bounded(monkeypatch, capsys):
    """A handshake that fails must tear the socket down under the SAME bounded
    close timeout ``RealtimeSession.close()`` enforces.

    Left to websocket-client's 3s default, a peer that never acks the close
    frame — exactly the misconfigured/unauthorized rig this path exists for —
    would stall session startup well past the teardown bound this module
    otherwise guarantees. (Qodo review, PR #356.)
    """
    ws = _HandshakeFailureWS()

    class _Module:
        @staticmethod
        def create_connection(url, timeout=None, header=None):
            return ws

    monkeypatch.setattr(realtime, "_import_ws", lambda: _Module)
    config = RealtimeConfig(available=True, ws_url="ws://127.0.0.1:1/v1/realtime", api_key="")

    assert realtime.open_session(config) is None
    assert ws.close_kwargs == {"timeout": realtime._WS_CLOSE_TIMEOUT_SECONDS}

    notices = [
        line for line in capsys.readouterr().err.splitlines() if line.startswith("colleague")
    ]
    assert len(notices) == 1, notices
    assert "realtime handshake failed" in notices[0]


def test_realtime_module_has_no_module_level_websocket_import():
    """The third-party WS client must appear ONLY inside a function body (lazy)."""
    src = Path(realtime.__file__).read_text(encoding="utf-8")
    for line in src.splitlines():
        assert not line.startswith("import websocket"), (
            "colleague/realtime.py must import websocket lazily, inside a "
            "function, never at module level"
        )


class _SendFailureWS:
    """A connected socket whose ``send`` fails — no pump is ever started against
    it, so these tests drive RealtimeSession's pure seams single-threaded."""

    def send(self, payload):
        raise RuntimeError("send boom")

    def close(self, **kwargs):
        pass


def test_send_audio_failure_degrades_in_place_and_returns_false(capsys):
    """A send failure degrades the session rather than propagating — the caller
    (the capture callback, running on the audio thread) only sees ``False``."""
    session = realtime.RealtimeSession(_SendFailureWS())

    assert session.send_audio(b"\x00\x01") is False
    assert session.degraded is True
    assert "send failed" in (session.degrade_reason or "")
    assert "realtime session degraded" in capsys.readouterr().err

    # A second failure must NOT print a second notice (exactly one, ever) and
    # must not overwrite the first reason.
    assert session.send_audio(b"\x02\x03") is False
    assert capsys.readouterr().err == ""
    assert "send failed" in (session.degrade_reason or "")


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param(b"\x00binary frame", id="binary-frame"),
        pytest.param("{not json", id="malformed-json"),
        pytest.param("[1, 2, 3]", id="json-but-not-an-object"),
        pytest.param('{"type": "unrelated.event"}', id="unrelated-event"),
        pytest.param(
            '{"type": "conversation.item.input_audio_transcription.completed"}',
            id="completed-without-text",
        ),
        pytest.param(
            '{"type": "conversation.item.input_audio_transcription.completed", "text": 7}',
            id="completed-with-non-string-text",
        ),
    ],
)
def test_pump_frame_handling_never_yields_a_bogus_transcript(raw):
    """Every frame the ears-only wire does NOT define is ignored defensively —
    none of them may crash the pump or enqueue a transcript."""
    got: list[str] = []
    session = realtime.RealtimeSession(_SendFailureWS(), on_transcript=got.append)

    session._handle_raw(raw)

    assert got == []
    assert session.transcripts.empty()
    assert session.degraded is False


def test_on_event_callback_failure_never_breaks_the_pump():
    """A caller callback that raises is suppressed — the transcript still lands
    (the callback is the caller's problem, the queue is the contract)."""
    session = realtime.RealtimeSession(
        _SendFailureWS(),
        on_event=lambda _event: (_ for _ in ()).throw(RuntimeError("callback boom")),
    )

    session._handle_raw(
        '{"type": "conversation.item.input_audio_transcription.completed", "text": "hi"}'
    )

    assert session.transcripts.get_nowait() == "hi"


def test_coverage_ci_job_installs_the_voice_extra():
    """The coverage job must sync ``--extra voice``.

    tests/test_realtime_client.py legitimately gates on websocket-client (it
    dials colleague's REAL sync WS client against a stdlib fake server), so a
    coverage job without the extra skips that whole file and reports its
    ~86 exercised lines of colleague/realtime.py as UNCOVERED new code —
    which is precisely what failed PR #356's Sonar new-code gate (32.6%).
    Pinned here so the fix cannot silently regress. The sibling plain-``uv
    sync`` test job stays extra-free on purpose, which is what keeps the
    extra-ABSENT degrade paths above honest.
    """
    workflow = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "tests.yml"
    sync_lines = [
        line.strip()
        for line in workflow.read_text(encoding="utf-8").splitlines()
        if "uv sync" in line and "--cov" not in line
    ]
    coverage_syncs = [line for line in sync_lines if "--extra" in line]
    assert coverage_syncs, f"no extra-installing `uv sync` line found: {sync_lines}"
    assert all("--extra voice" in line for line in coverage_syncs), coverage_syncs


def test_realtime_module_has_no_subprocess_or_socket_import():
    """The sanctioned thread-confinement entry does not also smuggle in a
    socket/subprocess primitive — those stay out of colleague/realtime.py."""
    src = Path(realtime.__file__).read_text(encoding="utf-8")
    assert "import subprocess" not in src
    assert "import socket" not in src
    assert "import asyncio" not in src


def test_bounded_join_uses_a_timeout_and_never_hangs_on_a_dead_thread():
    """The one real piece of thread discipline this stub implements: a bounded
    join helper embodying the sanctioned stop-event + bounded-join discipline
    (tests/test_boundary.py's recorded rationale for this module)."""
    import threading

    t = threading.Thread(target=lambda: None)
    t.start()
    t.join()  # let it finish naturally first
    # Calling the helper on an already-finished thread must return promptly —
    # it must not raise, and must not block waiting on a timeout for a thread
    # that is already dead.
    realtime._bounded_join(t, timeout=0.01)
