"""The reasoning sidecar: per-request journal beside the parent artifact (plan task t3).

A work item's model requests are journaled as a ``.reasoning.jsonl`` sidecar
under the same artifact directory the run report uses (``.colleague/`` in the
operator repo by default — :func:`colleague.artifact.artifact_dir`), so a
child's sidecar lands beside its parent artifact. Each line is one JSON
record ``{seat, turn, request_ts, request_index, text}`` — the caller stamps
``request_ts`` (see :func:`now_ts`) and ``request_index``; this module only
appends.

Guards, mirroring the artifact conventions:

* **Off-knob** — ``COLLEAGUE_REASONING_LOG=0`` disables logging entirely:
  :func:`append` writes nothing (no file, no directory) and returns ``None``,
  so a disabled run is byte-identical to one that never had the sidecar.
* **Size cap** — when appending a record would push the file past
  ``max_bytes`` (default 1 MiB), one final marker record
  ``{"truncated": true}`` is written and all further appends are no-ops —
  the truncation is discoverable, never silent.
* **Safe ids** — a ``task_id`` / ``child_id`` that is not a single path
  segment (traversal, empty) is refused: nothing is written.

Pure stdlib (``json``, ``os``, ``pathlib``, ``datetime``). This module
imports :func:`colleague.artifact.artifact` for path resolution only — the
loop imports this module, never the reverse (mirroring ``artifact.py``'s
position in the dependency graph).
"""

from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
from typing import Mapping, Optional

from colleague.artifact import artifact_dir

#: Default size cap for a reasoning sidecar (1 MiB).
DEFAULT_MAX_BYTES = 1_000_000

#: The off-knob environment variable: the string ``"0"`` disables the
#: reasoning log; anything else (or absence) leaves it enabled.
ENV_KNOB = "COLLEAGUE_REASONING_LOG"

#: The single marker record written when the size cap is hit.
_TRUNCATED_MARKER = {"truncated": True}
_MARKER_LINE = json.dumps(_TRUNCATED_MARKER, ensure_ascii=False) + "\n"


def enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    """True unless the off-knob is set to ``"0"``.

    ``env`` defaults to :data:`os.environ`; a mapping is accepted so callers
    (and tests) can pass an explicit environment. Only the exact string
    ``"0"`` disables — ``"1"``, ``"true"``, ``""`` and absence all enable.
    """
    if env is None:
        env = os.environ
    return env.get(ENV_KNOB) != "0"


def now_ts() -> str:
    """An ISO-8601 UTC timestamp for a record's ``request_ts`` field."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _is_safe_segment(segment: str) -> bool:
    """True when ``segment`` is a single path segment (no traversal/separators)."""
    return bool(segment) and segment not in (".", "..") and not any(c in segment for c in "/\\")


def _filename(task_id: str, child_id: Optional[str]) -> str:
    """The sidecar filename: ``<task_id>.reasoning.jsonl`` or, for a tagged
    child, ``<task_id>.<child_id>.reasoning.jsonl``."""
    if child_id:
        return f"{task_id}.{child_id}.reasoning.jsonl"
    return f"{task_id}.reasoning.jsonl"


def _already_truncated(path: Path) -> bool:
    """True when the file's last line is the truncation marker (best-effort).

    Only the tail is read (the marker is short and always last), so this stays
    cheap even at the cap. A missing/unreadable file is "not truncated".
    """
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            fh.seek(max(0, size - 256))
            tail = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return False
    lines = [line for line in tail.splitlines() if line]
    return bool(lines) and lines[-1] == _MARKER_LINE.rstrip("\n")


def append(
    repo_dir: str | Path,
    task_id: str,
    record: Mapping[str, object],
    child_id: Optional[str] = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
    env: Optional[Mapping[str, str]] = None,
) -> Optional[Path]:
    """Append one reasoning record to the sidecar; return the sidecar path.

    Returns ``None`` (writing nothing) when the off-knob is set, when
    ``task_id``/``child_id`` is not a safe path segment, or when the file has
    already been truncated. When appending ``record`` would push the file past
    ``max_bytes``, the truncation marker is written instead (once) and the
    path is still returned. The artifact directory is created on demand; the
    sidecar lands beside the parent artifact via :func:`artifact_dir`.
    """
    if not enabled(env):
        return None
    if not _is_safe_segment(task_id) or (child_id is not None and not _is_safe_segment(child_id)):
        return None

    path = artifact_dir(repo_dir) / _filename(task_id, child_id)
    if path.exists() and _already_truncated(path):
        return path

    line = json.dumps(dict(record), ensure_ascii=False) + "\n"
    current = path.stat().st_size if path.exists() else 0
    if current + len(line.encode("utf-8")) > max_bytes:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(_MARKER_LINE)
        return path

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line)
    return path
