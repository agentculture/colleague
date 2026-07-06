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


# ---------------------------------------------------------------------------
# Warming retry (lobes-cli#89, 0.38.0 — colleague#292/291 S1): a warming
# audio backend answers 503 + Retry-After instead of a bare 502. transcribe/
# synthesize wait min(Retry-After, 10s) and retry ONCE, then degrade exactly
# as today; a 502 or any other failure is unaffected.
# ---------------------------------------------------------------------------


def _http_error(code: int, headers: dict | None = None) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("u", code, "err", headers or {}, io.BytesIO(b""))


def test_transcribe_retries_once_on_503_with_retry_after(tmp_path, monkeypatch):
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"x")
    calls = {"n": 0}

    def fake_urlopen(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _http_error(503, {"Retry-After": "0"})
        return _FakeResp(json.dumps({"text": "hello"}).encode())

    slept: list[float] = []
    monkeypatch.setattr(voice.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(voice.time, "sleep", slept.append)
    out = voice.transcribe(audio, stt_model="stt", base_url="http://x/v1")
    assert out == "hello"
    assert calls["n"] == 2
    assert slept == [0.0]


def test_transcribe_warming_wait_is_capped_at_ten_seconds(tmp_path, monkeypatch):
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"x")
    calls = {"n": 0}

    def fake_urlopen(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _http_error(503, {"Retry-After": "120"})
        return _FakeResp(json.dumps({"text": "hello"}).encode())

    slept: list[float] = []
    monkeypatch.setattr(voice.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(voice.time, "sleep", slept.append)
    out = voice.transcribe(audio, stt_model="stt", base_url="http://x/v1")
    assert out == "hello"
    assert slept == [10.0]  # capped, never the full 120s


def test_transcribe_degrades_when_warming_retry_also_fails(tmp_path, monkeypatch, capsys):
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"x")
    calls = {"n": 0}

    def fake_urlopen(*a, **k):
        calls["n"] += 1
        raise _http_error(503, {"Retry-After": "0"})

    monkeypatch.setattr(voice.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(voice.time, "sleep", lambda s: None)
    assert voice.transcribe(audio, stt_model="stt", base_url="http://x/v1") is None
    assert calls["n"] == 2  # exactly one bounded retry, never a loop
    assert "stt transcribe failed" in capsys.readouterr().err


def test_transcribe_502_is_unaffected_by_warming_logic(tmp_path, monkeypatch, capsys):
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"x")
    calls = {"n": 0}

    def fake_urlopen(*a, **k):
        calls["n"] += 1
        raise _http_error(502)

    monkeypatch.setattr(voice.urllib.request, "urlopen", fake_urlopen)
    assert voice.transcribe(audio, stt_model="stt", base_url="http://x/v1") is None
    assert calls["n"] == 1  # no retry — a bare 502 keeps today's degrade path
    assert "stt transcribe failed" in capsys.readouterr().err


def test_transcribe_503_without_retry_after_is_not_treated_as_warming(tmp_path, monkeypatch):
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"x")
    calls = {"n": 0}

    def fake_urlopen(*a, **k):
        calls["n"] += 1
        raise _http_error(503)  # no Retry-After header at all

    monkeypatch.setattr(voice.urllib.request, "urlopen", fake_urlopen)
    assert voice.transcribe(audio, stt_model="stt", base_url="http://x/v1") is None
    assert calls["n"] == 1  # not classified as warming — no retry attempted


def test_synthesize_retries_once_on_503_with_retry_after(tmp_path, monkeypatch):
    calls = {"n": 0}

    def fake_urlopen(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _http_error(503, {"Retry-After": "1"})
        return _FakeResp(b"RIFF\x00\x00WAVEaudio")

    slept: list[float] = []
    monkeypatch.setattr(voice.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(voice.time, "sleep", slept.append)
    out = tmp_path / "out.wav"
    result = voice.synthesize("hi", tts_model="tts", base_url="http://x/v1", out_path=out)
    assert result == out
    assert out.read_bytes() == b"RIFF\x00\x00WAVEaudio"
    assert slept == [1.0]


def test_synthesize_502_is_unaffected_by_warming_logic(tmp_path, monkeypatch, capsys):
    calls = {"n": 0}

    def fake_urlopen(*a, **k):
        calls["n"] += 1
        raise _http_error(502)

    monkeypatch.setattr(voice.urllib.request, "urlopen", fake_urlopen)
    out = tmp_path / "out.wav"
    assert voice.synthesize("hi", tts_model="tts", base_url="http://x/v1", out_path=out) is None
    assert calls["n"] == 1
    assert not out.exists()
    assert "tts synthesize failed" in capsys.readouterr().err
