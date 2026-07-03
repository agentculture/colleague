"""Mic capture + speaker playback for the opt-in [voice] extra (senses
live-presence + voice arc, task t3).

Audio device I/O is opt-in: the sounddevice/soundfile deps live ONLY in the
``[voice]`` extra and are imported LAZILY inside each function — a BASE install
imports THIS module fine and only errors (cleanly, naming ``pip install
colleague[voice]``) when a capture/playback function is actually called without
the extra. Playback is strictly additive: a :func:`play` failure (missing extra
OR a runtime error) leaves the written wav untouched on disk and returns
``False`` + one stderr notice, never raising. NO subprocess, NO module-level
third-party import.
"""

from __future__ import annotations

import sys
from pathlib import Path

from colleague.cli._errors import CliError

_INSTALL_HINT = "pip install colleague[voice]"


def _import_audio():
    """Lazily import the [voice] extra's deps, or raise a clean CliError."""
    try:
        import sounddevice  # type: ignore
        import soundfile  # type: ignore

        return sounddevice, soundfile
    except Exception as exc:  # noqa: BLE001 - any import failure names the extra
        raise CliError(
            1,
            f"audio device support is not installed ({type(exc).__name__})",
            remediation=_INSTALL_HINT,
        ) from exc


def record(out_path: str | Path, *, seconds: float = 5.0, samplerate: int = 16000) -> Path:
    """Capture *seconds* of mono mic audio to *out_path* (a .wav) and return it.

    Requires the [voice] extra: raises a clean :class:`CliError` naming
    ``pip install colleague[voice]`` when the extra is absent (you cannot capture
    without the device lib). Never returns None — it returns the path or raises.
    """
    sounddevice, soundfile = _import_audio()
    frames = int(seconds * samplerate)
    data = sounddevice.rec(frames, samplerate=samplerate, channels=1)
    sounddevice.wait()
    out = Path(out_path)
    soundfile.write(str(out), data, samplerate)
    return out


def play(path: str | Path) -> bool:
    """Play a .wav aloud through the speaker. Return True on success.

    ADDITIVE + degrade-never-raise: a missing extra OR any playback error returns
    False + ONE stderr notice, and NEVER touches the wav on disk (the audio is
    preserved for a mic-less/file consumer). Playback failure must never lose the
    written wav or crash the caller.
    """
    p = Path(path)
    try:
        sounddevice, soundfile = _import_audio()
    except CliError:
        print(
            f"colleague: audio playback unavailable ({_INSTALL_HINT}) — wav saved at {p}",
            file=sys.stderr,
        )
        return False
    try:
        data, samplerate = soundfile.read(str(p))
        sounddevice.play(data, samplerate)
        sounddevice.wait()
        return True
    except Exception as exc:  # noqa: BLE001 - additive: never lose the wav
        print(
            f"colleague: audio playback failed ({type(exc).__name__}) — wav saved at {p}",
            file=sys.stderr,
        )
        return False
