"""Task t2 (realtime-speech arc): colleague/realtime.py packaging + import-cleanliness.

This is the boundary + packaging smoke test for the realtime speech client
stub — it does NOT test any dial/session/pump behaviour (task t3 builds that
and gets its own test file). Mirrors ``tests/test_voice_devices.py`` exactly:
a base install (the ``[voice]`` extra absent, as it is in this dev/CI
environment — see pyproject.toml's dev group, which never pins sounddevice/
soundfile/websocket-client) must import ``colleague.realtime`` cleanly and any
call into it must degrade to a clean :class:`CliError`, never a raw
``ImportError``/traceback.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from colleague import realtime
from colleague.cli._errors import CliError


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


def test_realtime_module_has_no_module_level_websocket_import():
    """The third-party WS client must appear ONLY inside a function body (lazy)."""
    src = Path(realtime.__file__).read_text(encoding="utf-8")
    for line in src.splitlines():
        assert not line.startswith("import websocket"), (
            "colleague/realtime.py must import websocket lazily, inside a "
            "function, never at module level"
        )


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
