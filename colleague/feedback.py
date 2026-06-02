"""Per-drive feedback store — grade a drive after the fact (the ROI loop).

Drive statistics (:class:`~colleague.contract.DriveStats`) say what a drive
*cost*; feedback says how *good* it was. Together they let a caller — human or
agent — compute the ROI of outsourcing a task to colleague and decide whether
to do it again (and on which engine).

A drive is identified by its ``task_id``. Feedback is a **single record per
drive** (re-grading overwrites — decision c16), persisted as
``<task_id>.feedback.json`` beside the drive's artifact in
:func:`~colleague.artifact.artifact_dir`. A per-repo *last-drive pointer*
(``last_drive``) lets a caller grade the most recent drive without quoting its id
(``feedback ... last``).

Stdlib only (zero runtime deps): ``json`` / ``datetime`` / ``pathlib``. An absent
feedback file or pointer is a clean no-op — :func:`read_feedback` /
:func:`get_last_drive` return ``None`` (never raise) so "no feedback yet" is a
first-class state, not an error.
"""

from __future__ import annotations

import datetime
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from colleague.artifact import artifact_dir, artifact_read_dirs

#: Per-repo pointer file (in the artifact dir) naming the most recent drive.
LAST_DRIVE_FILENAME = "last_drive"

#: Inclusive rating bounds (decision c16: a 1–5 quality grade).
MIN_RATING = 1
MAX_RATING = 5

#: A drive id must be a single safe path segment. Real ids are uuid hex, but the
#: CLI accepts an arbitrary ``ref`` (``resolve_task_id`` passes explicit refs
#: through unchanged), so the id is validated before it is joined into a filename.
_SAFE_TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class FeedbackError(Exception):
    """A feedback operation that cannot be honored (bad rating, unresolvable id)."""


def _validate_task_id(task_id: str) -> str:
    """Reject a task-id that is not a single safe path segment (traversal guard).

    ``feedback_path`` joins the id into a filename and the CLI accepts an
    arbitrary ``ref``, so a value like ``../../x`` or ``/etc/passwd`` could
    otherwise escape the artifact directory on read/write. The allow-list (no
    path separators, no ``.``/``..``, not absolute) keeps real uuid-hex ids while
    blocking traversal; an invalid id raises :class:`FeedbackError`.
    """
    if task_id in (".", "..") or not _SAFE_TASK_ID.match(task_id or ""):
        raise FeedbackError(
            f"invalid drive id {task_id!r}: expected a plain id "
            "(letters, digits, '.', '_', '-'; no path separators)"
        )
    return task_id


def _now_iso() -> str:
    """Current UTC time as an ISO-8601 string."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


@dataclass
class Feedback:
    """One quality grade for a drive (single record per ``task_id``)."""

    task_id: str
    rating: int
    notes: str = ""
    by: str = ""
    at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "rating": self.rating,
            "notes": self.notes,
            "by": self.by,
            "at": self.at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Feedback":
        return cls(
            task_id=str(data["task_id"]),
            rating=int(data["rating"]),
            notes=str(data.get("notes", "")),
            by=str(data.get("by", "")),
            at=str(data.get("at", "")),
        )


def feedback_path(repo_path: str | Path, task_id: str) -> Path:
    """The feedback-record WRITE path for ``task_id`` (beside the drive artifact).

    ``task_id`` is validated as a single safe path segment first — this is the
    single chokepoint that protects both :func:`write_feedback` and
    :func:`read_feedback` from path traversal via a user-supplied ref. Writes
    always target the new ``.colleague/`` dir; reads fall back to the legacy dir
    via :func:`feedback_read_path`.
    """
    return artifact_dir(repo_path) / f"{_validate_task_id(task_id)}.feedback.json"


def feedback_read_path(repo_path: str | Path, task_id: str) -> Path:
    """The feedback-record path to READ for ``task_id``: new dir, then legacy.

    Returns the first existing record across ``.colleague/`` then ``.convertible/``
    (back-compat); if neither exists, returns the new-dir path so the caller's
    ``is_file()`` check resolves to the canonical "no feedback yet" location.
    The ``task_id`` is validated (traversal guard) before being joined.
    """
    safe_id = _validate_task_id(task_id)
    candidates = [d / f"{safe_id}.feedback.json" for d in artifact_read_dirs(repo_path)]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


def last_drive_path(repo_path: str | Path) -> Path:
    """The per-repo last-drive pointer WRITE path (new ``.colleague/`` dir)."""
    return artifact_dir(repo_path) / LAST_DRIVE_FILENAME


def set_last_drive(repo_path: str | Path, task_id: str) -> None:
    """Record ``task_id`` as the most recent drive for this repo.

    Called by the drive path after an artifact is written, so ``feedback ... last``
    resolves to it. Best-effort: creates the artifact dir if needed.
    """
    path = last_drive_path(repo_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{task_id}\n", encoding="utf-8")


def get_last_drive(repo_path: str | Path) -> Optional[str]:
    """The most recent drive's ``task_id`` for this repo, or ``None`` if unrecorded.

    Reads the new ``.colleague/`` pointer first, falling back to the legacy
    ``.convertible/`` pointer (back-compat for the rename).
    """
    for directory in artifact_read_dirs(repo_path):
        path = directory / LAST_DRIVE_FILENAME
        if not path.is_file():
            continue
        try:
            value = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if value:
            return value
    return None


def resolve_task_id(repo_path: str | Path, ref: str) -> str:
    """Resolve a feedback reference: the literal ``"last"`` or an explicit task-id.

    Raises :class:`FeedbackError` when ``"last"`` is asked for but no drive has
    been recorded in this repo yet.
    """
    if ref == "last":
        task_id = get_last_drive(repo_path)
        if not task_id:
            raise FeedbackError(
                "no 'last' drive recorded for this repo yet — run a drive first, "
                "or pass an explicit task-id"
            )
        return task_id
    return ref


def write_feedback(
    repo_path: str | Path,
    task_id: str,
    *,
    rating: int,
    notes: str = "",
    by: str = "",
    at: str | None = None,
) -> Feedback:
    """Write (overwriting) the feedback record for ``task_id``; return it.

    ``rating`` must be an integer in ``[MIN_RATING, MAX_RATING]`` — anything else
    raises :class:`FeedbackError`. A second write for the same ``task_id``
    overwrites the first (single record per drive, decision c16).
    """
    # bool is an int subclass — reject it explicitly so True/False aren't ratings.
    if (
        isinstance(rating, bool)
        or not isinstance(rating, int)
        or not (MIN_RATING <= rating <= MAX_RATING)
    ):
        raise FeedbackError(f"rating must be an integer {MIN_RATING}-{MAX_RATING}, got {rating!r}")
    record = Feedback(task_id=task_id, rating=rating, notes=notes, by=by, at=at or _now_iso())
    path = feedback_path(repo_path, task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(record.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return record


def read_feedback(repo_path: str | Path, task_id: str) -> Optional[Feedback]:
    """Read the feedback record for ``task_id``, or ``None`` when none exists.

    A missing file is a clean no-op (returns ``None``) — "no feedback yet" is a
    state, not an error. A present-but-corrupt file raises :class:`FeedbackError`.
    Reads the new ``.colleague/`` dir first, then the legacy ``.convertible/`` dir.
    """
    path = feedback_read_path(repo_path, task_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FeedbackError(f"cannot read feedback for {task_id}: {exc}") from exc
    return Feedback.from_dict(data)
