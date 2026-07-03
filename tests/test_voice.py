"""Tests for colleague/voice — STT/TTS wire clients (no network)."""

import io
import json
import urllib.error
from pathlib import Path

from colleague import voice


class _FakeResp:
    """Minimal context-manager that returns pre-set bytes on .read()."""

    def __init__(self, data: bytes):
        self._data = data

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_transcribe_returns_verbatim_transcript(tmp_path, monkeypatch):
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"RIFFfake")
    monkeypatch.setattr(
        voice.urllib.request,
        "urlopen",
        lambda *a, **k: _FakeResp(json.dumps({"text": "hello  WORLD  spaced"}).encode()),
    )
    out = voice.transcribe(audio, stt_model="stt", base_url="http://x/v1")
    assert out == "hello  WORLD  spaced"  # exact, incl. double spaces


def test_transcribe_degrades_on_http_error(tmp_path, monkeypatch, capsys):
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"x")

    def boom(*a, **k):
        raise urllib.error.HTTPError("u", 500, "err", {}, io.BytesIO(b""))

    monkeypatch.setattr(voice.urllib.request, "urlopen", boom)
    assert voice.transcribe(audio, stt_model="stt", base_url="http://x/v1") is None
    assert "stt transcribe failed" in capsys.readouterr().err


def test_synthesize_writes_wav_and_returns_path(tmp_path, monkeypatch):
    monkeypatch.setattr(
        voice.urllib.request,
        "urlopen",
        lambda *a, **k: _FakeResp(b"RIFF\x00\x00WAVEaudio"),
    )
    out = tmp_path / "out.wav"
    result = voice.synthesize("hi", tts_model="tts", base_url="http://x/v1", out_path=out)
    assert result == out
    assert out.read_bytes() == b"RIFF\x00\x00WAVEaudio"


def test_synthesize_degrades_on_no_audio_json(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        voice.urllib.request,
        "urlopen",
        lambda *a, **k: _FakeResp(json.dumps({"error": "no audio"}).encode()),
    )
    out = tmp_path / "out.wav"
    assert voice.synthesize("hi", tts_model="tts", base_url="http://x/v1", out_path=out) is None
    assert not out.exists()
    assert "no audio" in capsys.readouterr().err


def test_voice_module_has_no_subprocess():
    src = Path(voice.__file__).read_text()
    assert "import subprocess" not in src
    assert "subprocess" not in src
