"""Tests for colleague.media — pure-stdlib media attachment helpers."""

import base64

import pytest

from colleague.media import (
    IMAGE_TOKEN_ESTIMATE,
    MAX_ATTACHMENT_BYTES,
    build_part,
    flatten_parts,
    validate_attachment,
)

# ── validate_attachment ──────────────────────────────────────────────


class TestValidateAttachment:
    """validate_attachment(path) → {path, media_type}."""

    def test_png(self, tmp_path):
        f = tmp_path / "icon.png"
        f.write_bytes(b"\x89PNG")
        result = validate_attachment(str(f))
        assert result["path"] == str(f)
        assert result["media_type"] == "image/png"

    def test_jpg_maps_to_jpeg(self, tmp_path):
        f = tmp_path / "photo.jpg"
        f.write_bytes(b"\xff\xd8")
        result = validate_attachment(str(f))
        assert result["media_type"] == "image/jpeg"

    def test_jpeg(self, tmp_path):
        f = tmp_path / "photo.jpeg"
        f.write_bytes(b"\xff\xd8")
        result = validate_attachment(str(f))
        assert result["media_type"] == "image/jpeg"

    def test_gif(self, tmp_path):
        f = tmp_path / "anim.gif"
        f.write_bytes(b"GIF89a")
        result = validate_attachment(str(f))
        assert result["media_type"] == "image/gif"

    def test_webp(self, tmp_path):
        f = tmp_path / "img.webp"
        f.write_bytes(b"RIFF")
        result = validate_attachment(str(f))
        assert result["media_type"] == "image/webp"

    def test_wav(self, tmp_path):
        f = tmp_path / "clip.wav"
        f.write_bytes(b"RIFF")
        result = validate_attachment(str(f))
        assert result["media_type"] == "audio/wav"

    def test_mp3(self, tmp_path):
        f = tmp_path / "song.mp3"
        f.write_bytes(b"\xff")
        result = validate_attachment(str(f))
        assert result["media_type"] == "audio/mp3"

    def test_ogg(self, tmp_path):
        f = tmp_path / "track.ogg"
        f.write_bytes(b"OggS")
        result = validate_attachment(str(f))
        assert result["media_type"] == "audio/ogg"

    def test_flac(self, tmp_path):
        f = tmp_path / "lossless.flac"
        f.write_bytes(b"fLaC")
        result = validate_attachment(str(f))
        assert result["media_type"] == "audio/flac"

    def test_missing_file_raises(self):
        with pytest.raises(ValueError, match="does-not-exist.png"):
            validate_attachment("does-not-exist.png")

    def test_unknown_extension_raises(self, tmp_path):
        f = tmp_path / "data.xyz"
        f.write_bytes(b"")
        with pytest.raises(ValueError, match="data.xyz"):
            validate_attachment(str(f))

    def test_no_extension_raises(self, tmp_path):
        f = tmp_path / "README"
        f.write_bytes(b"hello")
        with pytest.raises(ValueError, match="README"):
            validate_attachment(str(f))

    def test_uppercase_extension(self, tmp_path):
        f = tmp_path / "LOGO.PNG"
        f.write_bytes(b"\x89PNG")
        result = validate_attachment(str(f))
        assert result["media_type"] == "image/png"

    def test_directory_path_raises(self, tmp_path):
        d = tmp_path / "not_a_file.png"
        d.mkdir()
        with pytest.raises(ValueError, match="not_a_file.png"):
            validate_attachment(str(d))

    def test_oversize_file_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr("colleague.media.MAX_ATTACHMENT_BYTES", 16)
        f = tmp_path / "big.png"
        f.write_bytes(b"\x89PNG" + b"\x00" * 32)
        with pytest.raises(ValueError, match="too large"):
            validate_attachment(str(f))

    def test_file_within_cap_still_validates(self, tmp_path, monkeypatch):
        monkeypatch.setattr("colleague.media.MAX_ATTACHMENT_BYTES", 16)
        f = tmp_path / "small.png"
        f.write_bytes(b"\x89PNG")
        result = validate_attachment(str(f))
        assert result["path"] == str(f)
        assert result["media_type"] == "image/png"

    def test_default_cap_value(self):
        assert MAX_ATTACHMENT_BYTES == 16 * 1024 * 1024


# ── build_part ───────────────────────────────────────────────────────


class TestBuildPart:
    """build_part(attachment) → OpenAI content part dict."""

    def _image_attachment(self, tmp_path, ext="png"):
        f = tmp_path / f"img.{ext}"
        f.write_bytes(b"\x89PNGraw")
        return validate_attachment(str(f))

    def _audio_attachment(self, tmp_path, ext="wav"):
        f = tmp_path / f"clip.{ext}"
        f.write_bytes(b"RIFFraw")
        return validate_attachment(str(f))

    def test_image_part_shape(self, tmp_path):
        att = self._image_attachment(tmp_path, "png")
        part = build_part(att)
        assert part["type"] == "image_url"
        assert "image_url" in part
        url = part["image_url"]["url"]
        assert url.startswith("data:image/png;base64,")

    def test_image_part_base64_roundtrips(self, tmp_path):
        raw = b"\x89PNGraw"
        att = self._image_attachment(tmp_path, "png")
        part = build_part(att)
        encoded = part["image_url"]["url"].split(",", 1)[1]
        assert base64.b64decode(encoded) == raw

    def test_jpg_becomes_image_jpeg(self, tmp_path):
        att = self._image_attachment(tmp_path, "jpg")
        part = build_part(att)
        url = part["image_url"]["url"]
        assert url.startswith("data:image/jpeg;base64,")

    def test_audio_part_shape(self, tmp_path):
        att = self._audio_attachment(tmp_path, "wav")
        part = build_part(att)
        assert part["type"] == "input_audio"
        assert "input_audio" in part
        assert part["input_audio"]["format"] == "wav"

    def test_audio_part_base64_roundtrips(self, tmp_path):
        raw = b"RIFFraw"
        att = self._audio_attachment(tmp_path, "mp3")
        part = build_part(att)
        encoded = part["input_audio"]["data"]
        assert base64.b64decode(encoded) == raw

    def test_audio_format_matches_extension(self, tmp_path):
        for ext in ("wav", "mp3", "ogg", "flac"):
            att = self._audio_attachment(tmp_path, ext)
            part = build_part(att)
            assert part["input_audio"]["format"] == ext


# ── IMAGE_TOKEN_ESTIMATE ────────────────────────────────────────────


class TestImageTokenEstimate:
    def test_value(self):
        assert IMAGE_TOKEN_ESTIMATE == 260

    def test_is_int(self):
        assert isinstance(IMAGE_TOKEN_ESTIMATE, int)


# ── flatten_parts ──────────────────────────────────────────────────


class TestFlattenParts:
    """flatten_parts(content) → plain string."""

    def test_plain_string_passthrough(self):
        assert flatten_parts("hello world") == "hello world"

    def test_text_part_passthrough(self):
        parts = [{"type": "text", "text": "hello"}]
        assert flatten_parts(parts) == "hello"

    def test_image_part_placeholder(self):
        parts = [
            {"type": "text", "text": "see "},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
        ]
        result = flatten_parts(parts)
        assert "[image attachment]" in result
        assert "see " in result

    def test_audio_part_placeholder(self):
        parts = [
            {"type": "text", "text": "hear "},
            {"type": "input_audio", "input_audio": {"data": "abc", "format": "wav"}},
        ]
        result = flatten_parts(parts)
        assert "[audio attachment]" in result
        assert "hear " in result

    def test_mixed_parts(self):
        parts = [
            {"type": "text", "text": "A "},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,x"}},
            {"type": "text", "text": " B "},
            {"type": "input_audio", "input_audio": {"data": "y", "format": "mp3"}},
            {"type": "text", "text": " C"},
        ]
        result = flatten_parts(parts)
        assert "A " in result
        assert "[image attachment]" in result
        assert " B " in result
        assert "[audio attachment]" in result
        assert " C" in result

    def test_empty_parts_list(self):
        assert flatten_parts([]) == ""

    def test_unknown_part_type_ignored(self):
        parts = [
            {"type": "text", "text": "x "},
            {"type": "unknown_type"},
        ]
        result = flatten_parts(parts)
        assert result == "x "
