"""stt/tts wire clients for the senses live-presence + voice arc.

Pure-urllib OpenAI audio wire format. Turn-based (record -> transcribe -> work ->
speak), degrade-never-raise: any failure returns None + ONE stderr notice, never
an exception. No shell spawning, no third-party deps (mic/speaker live behind the
[voice] extra, task t3).

**Warming retry (lobes-cli#89, 0.38.0 — colleague#292/291 S1).** stt/tts
readiness is now live-probed via the gateway's realtime bridge; a warming
audio backend answers HTTP 503 with a ``Retry-After`` header instead of the
old bare 502. ``transcribe``/``synthesize`` treat that specific shape as
"warming": wait ``min(Retry-After, 10s)`` and retry the SAME request ONCE,
then fall through to the unchanged degrade-never-raise path exactly as
before. A 502, a 503 with no/invalid ``Retry-After``, or any other failure
(including the retry's own failure) is NOT treated as warming — it degrades
immediately, byte-identical to pre-0.38 behavior.
"""

from __future__ import annotations

import json
import mimetypes
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Optional

#: Cap on the bounded warming wait — never sleep the full advertised
#: Retry-After, however large (a defensive ceiling, not a rig expectation).
_MAX_WARMING_WAIT_SECONDS = 10.0


def _notice(text: str) -> None:
    print(f"colleague: {text}", file=sys.stderr)


def _warming_wait_seconds(exc: urllib.error.HTTPError) -> Optional[float]:
    """Return the bounded warming wait for a 503 + ``Retry-After``, else ``None``.

    Only an HTTP 503 with a present, non-negative, numeric ``Retry-After``
    header classifies as "warming" (lobes-cli#89). A 502, a 503 with no/
    malformed ``Retry-After``, or any other status is NOT warming — the
    caller keeps today's degrade path exactly, no retry attempted.
    """
    if exc.code != 503:
        return None
    headers = exc.headers
    retry_after = headers.get("Retry-After") if headers is not None else None
    if retry_after is None:
        return None
    try:
        seconds = float(str(retry_after).strip())
    except (TypeError, ValueError):
        return None
    if seconds < 0:
        return None
    return min(seconds, _MAX_WARMING_WAIT_SECONDS)


def _urlopen_with_warming_retry(request: urllib.request.Request, *, timeout: float, kind: str):
    """``urlopen`` *request*, retrying ONCE on a 503+Retry-After "warming" signal.

    Any other failure (a bare 502, a malformed 503, or the retry's own
    failure) propagates to the caller's existing degrade-never-raise
    ``except Exception`` — this helper adds exactly one bounded retry, never
    a loop, and never changes behavior for a non-warming failure.
    """
    try:
        return urllib.request.urlopen(request, timeout=timeout)  # nosec B310
    except urllib.error.HTTPError as exc:
        wait = _warming_wait_seconds(exc)
        if wait is None:
            raise
        _notice(f"{kind}: backend warming (503, Retry-After {wait:g}s) — retrying once")
        time.sleep(wait)
        return urllib.request.urlopen(request, timeout=timeout)  # nosec B310


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
    verbatim invariant — never trim/normalize). A 503 + Retry-After ("warming",
    lobes-cli#89) waits min(Retry-After, 10s) and retries ONCE; any other
    4xx/5xx/timeout/parse failure (including the retry's own failure) degrades
    to None + one stderr notice. Never raises."""
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
        with _urlopen_with_warming_retry(req, timeout=timeout, kind="stt transcribe") as resp:
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
    the bytes to out_path and return Path(out_path). A 503 + Retry-After
    ("warming", lobes-cli#89) waits min(Retry-After, 10s) and retries ONCE; a
    502 / JSON 'no audio' / error body / the retry's own failure degrades to
    None + one stderr notice and writes NO file. Never raises."""
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
        with _urlopen_with_warming_retry(req, timeout=timeout, kind="tts synthesize") as resp:
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
