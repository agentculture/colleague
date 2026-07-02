"""Tests for the media livecheck proofs (plan task t13).

Covers, with NO network / live rig required:

- fixture generation (`_make_red_png` / `_make_test_wav`) produces real,
  structurally valid media, not placeholder bytes
- `_attachment_status` extracts the delivery vocabulary from a simulated
  `TaskResult.media` record
- `classify_media_image_check`: PASS only on delivered + answer names red; a
  200-shaped-but-dropped/unknown/missing record always FAILS (never trust a
  200 alone)
- `classify_media_audio_check`: SKIP with the silent-drop reason while the
  rig drops `input_audio`; never PASS while dropped; the classification
  flips automatically to graded pass/fail once delivered
- `run_media_image_check` / `run_media_audio_check` degrade to "skipped"
  (never raise) when the endpoint is unreachable or the live call itself
  errors
"""

from __future__ import annotations

import struct
import wave
import zlib
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from colleague.livecheck import (
    _AUDIO_DROP_REASON,
    ProofResult,
    _attachment_status,
    _make_red_png,
    _make_test_wav,
    classify_media_audio_check,
    classify_media_image_check,
    run_media_audio_check,
    run_media_image_check,
)

# ---------------------------------------------------------------------------
# Fixture generation
# ---------------------------------------------------------------------------


class TestMakeRedPng:
    """`_make_red_png` hand-encodes a real, decodable PNG (stdlib zlib/struct)."""

    def test_starts_with_png_signature(self) -> None:
        assert _make_red_png()[:8] == b"\x89PNG\r\n\x1a\n"

    def test_chunks_are_structurally_valid(self) -> None:
        """Every chunk's CRC matches — this is a real PNG, not placeholder bytes."""
        data = _make_red_png()
        pos = 8
        tags = []
        while pos < len(data):
            length = struct.unpack(">I", data[pos : pos + 4])[0]
            tag = data[pos + 4 : pos + 8]
            chunk_data = data[pos + 8 : pos + 8 + length]
            crc = struct.unpack(">I", data[pos + 8 + length : pos + 12 + length])[0]
            assert crc == (zlib.crc32(tag + chunk_data) & 0xFFFFFFFF)
            tags.append(tag)
            pos += 12 + length
        assert tags == [b"IHDR", b"IDAT", b"IEND"]

    def test_pixels_are_solid_red(self) -> None:
        """Decoding IDAT yields a raw scanline buffer of solid-red RGB pixels."""
        data = _make_red_png(size=4)
        # Locate + decompress the IDAT chunk.
        pos = 8
        idat = b""
        while pos < len(data):
            length = struct.unpack(">I", data[pos : pos + 4])[0]
            tag = data[pos + 4 : pos + 8]
            chunk_data = data[pos + 8 : pos + 8 + length]
            if tag == b"IDAT":
                idat = chunk_data
            pos += 12 + length
        raw = zlib.decompress(idat)
        # 4x4 image: each row is 1 filter byte + 4*3 RGB bytes = 13 bytes.
        assert len(raw) == 4 * 13
        row0 = raw[0:13]
        assert row0[0] == 0  # filter byte: none
        assert row0[1:4] == b"\xff\x00\x00"  # first pixel: solid red
        assert row0[4:7] == b"\xff\x00\x00"  # second pixel: solid red too


class TestMakeTestWav:
    """`_make_test_wav` produces a real, readable WAV clip (stdlib `wave` only)."""

    def test_readable_by_wave_module(self) -> None:
        data = _make_test_wav()
        with wave.open(BytesIO(data), "rb") as handle:
            assert handle.getnchannels() == 1
            assert handle.getsampwidth() == 2
            assert handle.getnframes() > 0

    def test_duration_scales_frame_count(self) -> None:
        data = _make_test_wav(duration_seconds=1.0, framerate=8000)
        with wave.open(BytesIO(data), "rb") as handle:
            assert handle.getnframes() == 8000
            assert handle.getframerate() == 8000


# ---------------------------------------------------------------------------
# _attachment_status
# ---------------------------------------------------------------------------


class TestAttachmentStatus:
    def test_delivered(self) -> None:
        assert _attachment_status({"attachments": [{"path": "x", "status": "delivered"}]}) == (
            "delivered"
        )

    def test_dropped(self) -> None:
        assert _attachment_status({"attachments": [{"path": "x", "status": "dropped"}]}) == (
            "dropped"
        )

    def test_unknown(self) -> None:
        assert _attachment_status({"attachments": [{"path": "x", "status": "unknown"}]}) == (
            "unknown"
        )

    def test_none_media_is_missing(self) -> None:
        assert _attachment_status(None) == "missing"

    def test_empty_attachments_list_is_missing(self) -> None:
        assert _attachment_status({"attachments": []}) == "missing"

    def test_missing_status_key_is_missing(self) -> None:
        assert _attachment_status({"attachments": [{"path": "x"}]}) == "missing"


# ---------------------------------------------------------------------------
# classify_media_image_check — the red-answer + delivered conjunction
# ---------------------------------------------------------------------------


class TestClassifyMediaImageCheck:
    def test_delivered_and_names_red_passes(self) -> None:
        media = {"attachments": [{"path": "red.png", "status": "delivered"}]}
        status, detail = classify_media_image_check(media, "The color is red.")
        assert status == "passed"
        assert "red" in detail.lower()

    def test_case_insensitive_red(self) -> None:
        media = {"attachments": [{"path": "red.png", "status": "delivered"}]}
        status, _ = classify_media_image_check(media, "RED")
        assert status == "passed"

    def test_delivered_but_no_red_in_answer_fails(self) -> None:
        media = {"attachments": [{"path": "red.png", "status": "delivered"}]}
        status, detail = classify_media_image_check(media, "It looks blue.")
        assert status == "failed"
        assert "did not name red" in detail

    def test_dropped_with_red_answer_still_fails(self) -> None:
        """The acceptance-defining case: a 200 whose media record says dropped
        must FAIL even when the (hallucinated/guessed) answer happens to say
        red — a 200 is never trusted alone."""
        media = {"attachments": [{"path": "red.png", "status": "dropped"}]}
        status, detail = classify_media_image_check(media, "red")
        assert status == "failed"
        assert "not delivered" in detail
        assert "dropped" in detail

    def test_unknown_status_fails(self) -> None:
        media = {"attachments": [{"path": "red.png", "status": "unknown"}]}
        status, _ = classify_media_image_check(media, "red")
        assert status == "failed"

    def test_missing_media_record_fails(self) -> None:
        status, detail = classify_media_image_check(None, "red")
        assert status == "failed"
        assert "missing" in detail

    def test_empty_answer_fails(self) -> None:
        media = {"attachments": [{"path": "red.png", "status": "delivered"}]}
        status, _ = classify_media_image_check(media, "")
        assert status == "failed"


# ---------------------------------------------------------------------------
# classify_media_audio_check — the honest SKIP-on-drop
# ---------------------------------------------------------------------------


class TestClassifyMediaAudioCheck:
    def test_dropped_skips_with_silent_drop_reason(self) -> None:
        media = {"attachments": [{"path": "clip.wav", "status": "dropped"}]}
        status, detail = classify_media_audio_check(media, "some transcript")
        assert status == "skipped"
        assert detail == _AUDIO_DROP_REASON
        assert "input_audio" in detail

    def test_never_passes_while_dropped_even_with_a_plausible_answer(self) -> None:
        media = {"attachments": [{"path": "clip.wav", "status": "dropped"}]}
        status, _ = classify_media_audio_check(media, "a person speaking calmly")
        assert status != "passed"
        assert status == "skipped"

    def test_unknown_status_skips(self) -> None:
        media = {"attachments": [{"path": "clip.wav", "status": "unknown"}]}
        status, detail = classify_media_audio_check(media, "")
        assert status == "skipped"
        assert "unknown" in detail

    def test_missing_media_record_skips(self) -> None:
        status, detail = classify_media_audio_check(None, "")
        assert status == "skipped"
        assert "missing" in detail

    def test_delivered_with_answer_passes(self) -> None:
        """The automatic flip: the day the rig actually consumes input_audio,
        a delivered attachment is graded like any other proof."""
        media = {"attachments": [{"path": "clip.wav", "status": "delivered"}]}
        status, detail = classify_media_audio_check(media, "a short beep tone")
        assert status == "passed"
        assert "delivered" in detail

    def test_delivered_with_no_answer_fails(self) -> None:
        media = {"attachments": [{"path": "clip.wav", "status": "delivered"}]}
        status, _ = classify_media_audio_check(media, "   ")
        assert status == "failed"


# ---------------------------------------------------------------------------
# run_media_image_check / run_media_audio_check — offline degradation +
# live-call-error degradation (never a traceback, never a hidden network call)
# ---------------------------------------------------------------------------


class TestRunMediaChecksOffline:
    """Both live-runner functions must degrade to skipped, never raise, and
    never touch VllmOpenAIEngine when the endpoint probe reports unreachable."""

    @patch("colleague.livecheck.probe_endpoint")
    def test_image_check_skips_when_unreachable(self, mock_probe, tmp_path: Path) -> None:
        mock_probe.return_value = {
            "endpoint": "http://localhost:8000/v1",
            "reachable": False,
            "reason": "Connection refused",
        }
        with patch("colleague.livecheck.VllmOpenAIEngine") as mock_engine_cls:
            result = run_media_image_check(tmp_path)
        assert isinstance(result, ProofResult)
        assert result.file == "media_image"
        assert result.status == "skipped"
        assert "unreachable" in result.detail
        mock_engine_cls.assert_not_called()

    @patch("colleague.livecheck.probe_endpoint")
    def test_audio_check_skips_when_unreachable(self, mock_probe, tmp_path: Path) -> None:
        mock_probe.return_value = {
            "endpoint": "http://localhost:8000/v1",
            "reachable": False,
            "reason": "Connection refused",
        }
        with patch("colleague.livecheck.VllmOpenAIEngine") as mock_engine_cls:
            result = run_media_audio_check(tmp_path)
        assert isinstance(result, ProofResult)
        assert result.file == "media_audio"
        assert result.status == "skipped"
        assert "unreachable" in result.detail
        mock_engine_cls.assert_not_called()


class TestRunMediaChecksLiveCallErrors:
    """A live call that raises (network drop mid-flight, malformed response,
    ...) degrades the check to skipped instead of propagating — never a
    traceback (t13 acceptance)."""

    @patch("colleague.livecheck.probe_endpoint")
    def test_image_check_degrades_on_engine_exception(self, mock_probe, tmp_path: Path) -> None:
        mock_probe.return_value = {"endpoint": "http://x/v1", "reachable": True, "reason": None}

        class _Boom:
            def work(self, task, config):
                raise RuntimeError("connection reset mid-flight")

        with patch("colleague.livecheck.VllmOpenAIEngine", return_value=_Boom()):
            result = run_media_image_check(tmp_path)
        assert result.status == "skipped"
        assert "proof error" in result.detail

    @patch("colleague.livecheck.probe_endpoint")
    def test_audio_check_degrades_on_engine_exception(self, mock_probe, tmp_path: Path) -> None:
        mock_probe.return_value = {"endpoint": "http://x/v1", "reachable": True, "reason": None}

        class _Boom:
            def work(self, task, config):
                raise RuntimeError("connection reset mid-flight")

        with patch("colleague.livecheck.VllmOpenAIEngine", return_value=_Boom()):
            result = run_media_audio_check(tmp_path)
        assert result.status == "skipped"
        assert "proof error" in result.detail


class TestRunMediaChecksHappyPath:
    """With a reachable endpoint and a fake engine standing in for the live
    rig, the runner builds a real attachment, drives one work() call, and
    classifies the result — proving the wiring without touching the network."""

    @patch("colleague.livecheck.probe_endpoint")
    def test_image_check_end_to_end_with_fake_engine(self, mock_probe, tmp_path: Path) -> None:
        mock_probe.return_value = {"endpoint": "http://x/v1", "reachable": True, "reason": None}
        captured = {}

        class _FakeEngine:
            def work(self, task, config):
                captured["task"] = task
                assert task.attachments is not None
                assert len(task.attachments) == 1
                assert task.attachments[0]["media_type"] == "image/png"
                return SimpleNamespace(
                    media={
                        "attachments": [
                            {"path": task.attachments[0]["path"], "status": "delivered"}
                        ]
                    },
                    summary="The image is red.",
                )

        with patch("colleague.livecheck.VllmOpenAIEngine", return_value=_FakeEngine()):
            result = run_media_image_check(tmp_path)

        assert result.file == "media_image"
        assert result.status == "passed"
        assert "attach" in captured["task"].instruction.lower() or "color" in (
            captured["task"].instruction.lower()
        )

    @patch("colleague.livecheck.probe_endpoint")
    def test_audio_check_end_to_end_with_fake_engine_still_skips(
        self, mock_probe, tmp_path: Path
    ) -> None:
        """Even with a live-shaped round trip, today's rig drops the audio —
        the fake engine replays that shape and the check must SKIP, not pass."""
        mock_probe.return_value = {"endpoint": "http://x/v1", "reachable": True, "reason": None}

        class _FakeEngine:
            def work(self, task, config):
                assert task.attachments is not None
                assert task.attachments[0]["media_type"] == "audio/wav"
                return SimpleNamespace(
                    media={
                        "attachments": [{"path": task.attachments[0]["path"], "status": "dropped"}]
                    },
                    summary="",
                )

        with patch("colleague.livecheck.VllmOpenAIEngine", return_value=_FakeEngine()):
            result = run_media_audio_check(tmp_path)

        assert result.file == "media_audio"
        assert result.status == "skipped"
        assert result.detail == _AUDIO_DROP_REASON
