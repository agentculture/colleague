"""Task t3: the [voice] extra's device layer imports lazily and degrades cleanly."""

from pathlib import Path

import pytest

from colleague import voice_devices
from colleague.cli._errors import CliError


def test_module_imports_without_the_extra():
    # Importing the module must NOT require sounddevice/soundfile (lazy imports).
    assert hasattr(voice_devices, "record")
    assert hasattr(voice_devices, "play")


def test_record_without_extra_raises_clean_clierror():
    # No [voice] extra on the test machine -> record raises a CliError naming the extra.
    with pytest.raises(CliError) as exc:
        voice_devices.record("/tmp/whatever.wav", seconds=0.1)
    assert "colleague[voice]" in (exc.value.remediation or "")


def test_play_without_extra_returns_false_and_keeps_wav(tmp_path, capsys):
    wav = tmp_path / "out.wav"
    wav.write_bytes(b"RIFF\x00\x00WAVEdata")  # a pre-written wav (e.g. from tts)
    ok = voice_devices.play(wav)
    assert ok is False  # additive: degrades, never raises
    assert wav.exists()  # the wav is NEVER lost on a play failure
    assert wav.read_bytes() == b"RIFF\x00\x00WAVEdata"  # untouched
    err = capsys.readouterr().err
    assert "playback unavailable" in err or "playback failed" in err


def test_voice_devices_has_no_subprocess_or_module_level_audio_import():
    src = Path(voice_devices.__file__).read_text()
    assert "import subprocess" not in src
    # sounddevice/soundfile must appear ONLY inside functions (lazy), never at col 0.
    for line in src.splitlines():
        assert not (line.startswith("import sounddevice") or line.startswith("import soundfile"))
