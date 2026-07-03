"""stt/tts wire clients for the senses live-presence + voice arc.

Pure-urllib OpenAI audio wire format. Turn-based (record -> transcribe -> work ->
speak), degrade-never-raise: any failure returns None + ONE stderr notice, never
an exception. No shell spawning, no third-party deps (mic/speaker live behind the
[voice] extra, task t3).
"""

from __future__ import annotations

import json
import mimetypes
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Optional


def _notice(text: str) -> None:
    print(f"colleague: {text}", file=sys.stderr)


def transcribe(
    audio_path: str | Path,
    *,
    stt_model: str,
    base_url: str,
    api_key: str = "",
    timeout: float = 30.0,
) -> Optional[str]:
    """POST the audio file as multipart/form-data to {base_url}/audio/transcriptions
    (fields: model + file). Return the server transcript text EXACTLY (the v1
    verbatim invariant — never trim/normalize). None + one stderr notice on any
    4xx/5xx/timeout/parse failure. Never raises."""
    try:
        path = Path(audio_path)
        raw = path.read_bytes()
        boundary = "----colleague" + uuid.uuid4().hex
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        pre = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="model"\r\n\r\n{stt_model}\r\n'
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
            f"Content-Type: {ctype}\r\n\r\n"
        ).encode("utf-8")
        post = f"\r\n--{boundary}--\r\n".encode("utf-8")
        body = pre + raw + post
        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        req = urllib.request.Request(
            f"{base_url}/audio/transcriptions", data=body, headers=headers, method="POST"
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310
            payload = json.loads(resp.read().decode("utf-8"))
        text = payload.get("text")
        if not isinstance(text, str):
            _notice("stt transcribe returned no text — proceeding without a transcript")
            return None
        return text
    except Exception as exc:  # noqa: BLE001 - degrade-never-raise
        _notice(f"stt transcribe failed ({type(exc).__name__}) — proceeding without a transcript")
        return None


def synthesize(
    text: str,
    *,
    tts_model: str,
    base_url: str,
    out_path: str | Path,
    api_key: str = "",
    voice: Optional[str] = None,
    timeout: float = 60.0,
) -> Optional[Path]:
    """POST JSON {model, input, response_format:"wav"[, voice]} to
    {base_url}/audio/speech. On a 200 with a non-empty, non-JSON-error body, write
    the bytes to out_path and return Path(out_path). A 502 / JSON 'no audio' / error
    body degrades to None + one stderr notice and writes NO file. Never raises."""
    try:
        payload = {"model": tts_model, "input": text, "response_format": "wav"}
        if voice:
            payload["voice"] = voice
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        req = urllib.request.Request(
            f"{base_url}/audio/speech",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310
            data = resp.read()
        # A JSON error body (the rig's speech proxy 502s with {"error": ...}) is NOT
        # audio: detect it and degrade rather than writing a bogus wav.
        if not data:
            _notice("tts synthesize returned empty body — text reply unchanged")
            return None
        stripped = data.lstrip()
        if stripped[:1] in (b"{", b"["):
            try:
                json.loads(data.decode("utf-8"))
                _notice("tts synthesize returned no audio — text reply unchanged")
                return None
            except ValueError:
                pass  # not JSON after all — treat as audio bytes
        out = Path(out_path)
        out.write_bytes(data)
        return out
    except Exception as exc:  # noqa: BLE001 - degrade-never-raise
        _notice(f"tts synthesize failed ({type(exc).__name__}) — text reply unchanged")
        return None
