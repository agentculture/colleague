"""Pure-stdlib helpers for media attachments (images, audio).

Provides attachment validation, OpenAI content-part construction, and
content flattening for the multi-modal input path.
"""

import base64
from pathlib import Path

# Per-image-tile prompt-token estimate measured on the live Gemma4 probe 2026-07-02.
IMAGE_TOKEN_ESTIMATE = 260

#: Size cap for a ``Task.attachments`` entry (CLI ``--attach``, session
#: ``/attach``, and mesh ``attach:`` references all funnel through
#: :func:`validate_attachment`). Mirrors the intent of ``colleague.tools``'s
#: ``MAX_MEDIA_BYTES`` (the ``view_media`` tool's 4 MB cap) but is defined here,
#: not imported, to avoid a tools->media->tools layering cycle. Sized generously
#: above any real attachment (screenshots, short clips) while still bounding
#: memory + the base64-inflated prompt a non-operator mesh request could force.
MAX_ATTACHMENT_BYTES = 16 * 1024 * 1024

# Extension → media type mapping.
_MEDIA_TYPES: dict[str, str] = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "wav": "audio/wav",
    "mp3": "audio/mp3",
    "ogg": "audio/ogg",
    "flac": "audio/flac",
}


def validate_attachment(path: str) -> dict:
    """Validate *path* exists, is a regular file, has a known media
    extension, and is within :data:`MAX_ATTACHMENT_BYTES`.

    Returns a dict with keys ``path`` (str) and ``media_type`` (str).
    Raises ``ValueError`` for a missing file, a non-regular-file path (e.g. a
    directory), an unknown extension, or an oversize file. All three
    attachment surfaces (CLI ``--attach``, session ``/attach``, mesh
    ``attach:`` references) funnel through this one function, so the size cap
    is enforced here rather than at each call site.
    """
    p = Path(path)
    if not p.exists():
        raise ValueError(f"Attachment file not found: {path}")
    if not p.is_file():
        raise ValueError(f"Attachment path is not a regular file: {path}")

    ext = p.suffix.lstrip(".").lower()
    if ext not in _MEDIA_TYPES:
        raise ValueError(f"Unknown attachment extension '{ext}' for {path}")

    size = p.stat().st_size
    if size > MAX_ATTACHMENT_BYTES:
        raise ValueError(
            f"attachment too large: {path} is {size} bytes " f"(max {MAX_ATTACHMENT_BYTES})"
        )

    return {"path": str(p), "media_type": _MEDIA_TYPES[ext]}


def build_part(attachment: dict) -> dict:
    """Build a standard OpenAI content part from a validated attachment.

    * ``attachment`` is the dict returned by :func:`validate_attachment`.
    * Image attachments become ``{"type": "image_url", "image_url": ...}``.
    * Audio attachments become ``{"type": "input_audio", "input_audio": ...}``.
    """
    file_bytes = Path(attachment["path"]).read_bytes()
    encoded = base64.b64encode(file_bytes).decode("ascii")
    media_type = attachment["media_type"]

    if media_type.startswith("image/"):
        return {
            "type": "image_url",
            "image_url": {"url": f"data:{media_type};base64,{encoded}"},
        }

    # audio
    ext = Path(attachment["path"]).suffix.lstrip(".").lower()
    return {
        "type": "input_audio",
        "input_audio": {"data": encoded, "format": ext},
    }


def flatten_parts(content) -> str:
    """Flatten *content* to a plain string.

    * A plain ``str`` passes through unchanged.
    * A list of parts is joined: text parts pass through, media parts
      become bracketed placeholders (e.g. ``[image attachment]`` or
      ``[audio attachment]``).
    """
    if isinstance(content, str):
        return content

    segments: list[str] = []
    for part in content:
        if part.get("type") == "text":
            segments.append(part["text"])
        elif part.get("type") == "image_url":
            segments.append("[image attachment]")
        elif part.get("type") == "input_audio":
            segments.append("[audio attachment]")
        # unknown part types are silently skipped
    return "".join(segments)
