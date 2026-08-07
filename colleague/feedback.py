"""Per-work-item feedback store — grade a work item after the fact (the ROI loop).

Work statistics (:class:`~colleague.contract.WorkStats`) say what a work item
*cost*; feedback says how *good* it was. Together they let a caller — human or
agent — compute the ROI of asking colleague to do a task and decide whether
to do it again (and on which engine).

A work item is identified by its ``task_id``. Feedback is recorded **per
(task_id, author)** pair — re-grading the SAME author overwrites (decision c16),
but a DIFFERENT author's record for the same work item lands beside it rather
than overwriting it (c17/h14: author provenance). ``author`` defaults to
``"operator"`` (a human grade) and persists at ``<task_id>.feedback.json`` —
byte-identical to the pre-author on-disk shape, so a legacy record with no
``author`` key still loads (as ``"operator"``). A non-default author (today,
only ``"cortex"`` — a self-grade) persists at
``<task_id>.<author>.feedback.json``, beside the work item's artifact in
:func:`~colleague.artifact.artifact_dir`. A per-repo *last-work pointer*
(``last_work``) lets a caller grade the most recent work item without quoting its
id (``feedback ... last``).

Stdlib only (zero runtime deps): ``json`` / ``datetime`` / ``pathlib``. An absent
feedback file or pointer is a clean no-op — :func:`read_feedback` /
:func:`get_last_work` return ``None`` (never raise) so "no feedback yet" is a
first-class state, not an error.
"""

from __future__ import annotations

import datetime
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from colleague import correction
from colleague import memory as memorymod
from colleague.artifact import (
    artifact_dir,
    artifact_read_dirs,
    ensure_self_ignored,
    find_artifact,
    read_artifact,
)

#: Per-repo pointer file (in the artifact dir) naming the most recent work item.
LAST_WORK_FILENAME = "last_work"
#: Legacy pointer filename (pre drive→work rename); still read as a fallback.
LAST_DRIVE_FILENAME = "last_drive"

#: Inclusive rating bounds (decision c16: a 1–5 quality grade).
MIN_RATING = 1
MAX_RATING = 5

#: The human operator's grade — the default author, and the only author the
#: pre-author on-disk shape ever recorded (back-compat).
DEFAULT_AUTHOR = "operator"
#: A self-grade the acting mind records for its own work item (c17/h14). Lands
#: beside an operator record for the same task_id rather than overwriting it.
CORTEX_AUTHOR = "cortex"
#: The full sanctioned author vocabulary — anything else is refused.
ALLOWED_AUTHORS = (DEFAULT_AUTHOR, CORTEX_AUTHOR)

#: A work item id must be a single safe path segment. Real ids are uuid hex, but the
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


def _validate_author(author: str) -> str:
    """Reject an author outside the sanctioned set (c17/h14).

    Only ``"operator"`` (a human grade) and ``"cortex"`` (a self-grade the
    acting mind records for its own work item) are recognised — anything else
    raises :class:`FeedbackError`, mirroring :func:`_validate_task_id`'s
    convention.
    """
    if author not in ALLOWED_AUTHORS:
        raise FeedbackError(
            f"invalid author {author!r}: expected one of {', '.join(ALLOWED_AUTHORS)}"
        )
    return author


def _feedback_filename(task_id: str, author: str) -> str:
    """The on-disk feedback filename for one ``(task_id, author)`` pair.

    The default author (``"operator"``) keeps the pre-author bare filename
    (``<task_id>.feedback.json``) — byte-identical back-compat for both a
    legacy record already on disk and a caller that never mentions authors. A
    non-default author lands in a sibling file (``<task_id>.<author>.feedback.json``)
    so the two coexist rather than overwrite each other.
    """
    if author == DEFAULT_AUTHOR:
        return f"{task_id}.feedback.json"
    return f"{task_id}.{author}.feedback.json"


def _now_iso() -> str:
    """Current UTC time as an ISO-8601 string."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


@dataclass
class Feedback:
    """One quality grade for a work item (single record per ``(task_id, author)``).

    When ``chain`` is ``True``, this record was written as part of a
    chain-aware grade (:func:`grade_chain`) that walked the
    ``continued_from`` lineage. ``author`` (c17/h14) distinguishes WHO graded —
    ``"operator"`` (default) or ``"cortex"`` — so a cortex self-grade can coexist
    beside an operator's grade for the same work item instead of overwriting it.
    """

    task_id: str
    rating: int
    notes: str = ""
    by: str = ""
    at: str = ""
    chain: bool = False
    author: str = DEFAULT_AUTHOR

    def to_dict(self) -> dict[str, Any]:
        # ``chain``/``author`` are omit-when-default: an ordinary operator grade
        # keeps the exact persisted shape the contract doc pins
        # (test_contract_doc.py) — only a chain-graded or non-operator record
        # carries the extra key.
        data: dict[str, Any] = {
            "task_id": self.task_id,
            "rating": self.rating,
            "notes": self.notes,
            "by": self.by,
            "at": self.at,
        }
        if self.chain:
            data["chain"] = True
        if self.author != DEFAULT_AUTHOR:
            data["author"] = self.author
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Feedback":
        return cls(
            task_id=str(data["task_id"]),
            rating=int(data["rating"]),
            notes=str(data.get("notes", "")),
            by=str(data.get("by", "")),
            at=str(data.get("at", "")),
            chain=bool(data.get("chain", False)),
            # A legacy record has no "author" key at all — reads back as the
            # default "operator" (back-compat pinned by a test).
            author=str(data.get("author") or DEFAULT_AUTHOR),
        )


def feedback_path(repo_path: str | Path, task_id: str, author: str = DEFAULT_AUTHOR) -> Path:
    """The feedback-record WRITE path for ``(task_id, author)`` (beside the artifact).

    ``task_id`` is validated as a single safe path segment first — this is the
    single chokepoint that protects both :func:`write_feedback` and
    :func:`read_feedback` from path traversal via a user-supplied ref.
    ``author`` is validated against :data:`ALLOWED_AUTHORS`. Writes always
    target the new ``.colleague/`` dir; reads fall back to the legacy dir via
    :func:`feedback_read_path`.
    """
    safe_id = _validate_task_id(task_id)
    safe_author = _validate_author(author)
    return artifact_dir(repo_path) / _feedback_filename(safe_id, safe_author)


def feedback_read_path(repo_path: str | Path, task_id: str, author: str = DEFAULT_AUTHOR) -> Path:
    """The feedback-record path to READ for ``(task_id, author)``: new dir, then legacy.

    Returns the first existing record across ``.colleague/`` then ``.convertible/``
    (back-compat); if neither exists, returns the new-dir path so the caller's
    ``is_file()`` check resolves to the canonical "no feedback yet" location.
    ``task_id``/``author`` are validated (traversal guard / sanctioned set)
    before being joined.
    """
    safe_id = _validate_task_id(task_id)
    safe_author = _validate_author(author)
    filename = _feedback_filename(safe_id, safe_author)
    candidates = [d / filename for d in artifact_read_dirs(repo_path)]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


def last_work_path(repo_path: str | Path) -> Path:
    """The per-repo last-work pointer WRITE path (new ``.colleague/`` dir)."""
    return artifact_dir(repo_path) / LAST_WORK_FILENAME


def set_last_work(repo_path: str | Path, task_id: str) -> None:
    """Record ``task_id`` as the most recent work item for this repo.

    Called by the work path after an artifact is written, so ``feedback ... last``
    resolves to it. Best-effort: creates the artifact dir if needed.
    """
    path = last_work_path(repo_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ensure_self_ignored(path.parent)
    path.write_text(f"{task_id}\n", encoding="utf-8")


def get_last_work(repo_path: str | Path) -> Optional[str]:
    """The most recent work item's ``task_id`` for this repo, or ``None`` if unrecorded.

    Reads the new ``last_work`` pointer first, then falls back to the legacy
    ``last_drive`` pointer (pre drive→work rename) — across both the new
    ``.colleague/`` dir and the legacy ``.convertible/`` dir.
    """
    for directory in artifact_read_dirs(repo_path):
        for filename in (LAST_WORK_FILENAME, LAST_DRIVE_FILENAME):
            path = directory / filename
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

    Raises :class:`FeedbackError` when ``"last"`` is asked for but no work item
    has been recorded in this repo yet.
    """
    if ref == "last":
        task_id = get_last_work(repo_path)
        if not task_id:
            raise FeedbackError(
                "no 'last' work item recorded for this repo yet — run a work item "
                "first, or pass an explicit task-id"
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
    author: str = DEFAULT_AUTHOR,
) -> Feedback:
    """Write (overwriting) the feedback record for ``(task_id, author)``; return it.

    ``rating`` must be an integer in ``[MIN_RATING, MAX_RATING]`` — anything else
    raises :class:`FeedbackError`. ``author`` must be one of
    :data:`ALLOWED_AUTHORS` — anything else likewise raises
    :class:`FeedbackError`. A second write for the SAME ``(task_id, author)``
    overwrites the first (idempotent regrade, decision c16); a DIFFERENT
    author's write for the same ``task_id`` lands beside it instead (c17/h14).
    """
    # bool is an int subclass — reject it explicitly so True/False aren't ratings.
    if (
        isinstance(rating, bool)
        or not isinstance(rating, int)
        or not (MIN_RATING <= rating <= MAX_RATING)
    ):
        raise FeedbackError(f"rating must be an integer {MIN_RATING}-{MAX_RATING}, got {rating!r}")
    author = _validate_author(author)
    record = Feedback(
        task_id=task_id, rating=rating, notes=notes, by=by, at=at or _now_iso(), author=author
    )
    path = feedback_path(repo_path, task_id, author=author)
    path.parent.mkdir(parents=True, exist_ok=True)
    ensure_self_ignored(path.parent)
    path.write_text(
        json.dumps(record.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    # Grade-time auto-trigger (self-learning t12, c18/h15): when the graded
    # work item's own artifact carries BOTH pr_url and tip_sha, attempt a
    # correction-diff capture now. The grade above has ALREADY landed on
    # disk — maybe_capture_correction is a strict best-effort call that never
    # raises (its own try/except absorbs everything), so this can only ever
    # ADD an observable capture outcome, never take the grade away (AC2,
    # pinned by test_auto_trigger.py's test_capture_failure_never_blocks_the_grade).
    maybe_capture_correction(repo_path, task_id)
    return record


def grade_chain(
    repo_path: str | Path,
    task_id: str,
    *,
    rating: int,
    notes: str = "",
    by: str = "",
    at: str | None = None,
    author: str = DEFAULT_AUTHOR,
) -> list[Feedback]:
    """Grade every episode in a ``continued_from`` chain, starting from ``task_id``.

    Walks the lineage backwards through ``continued_from`` links, writing a
    feedback record for each episode.  Cycles are detected via a visited-set
    (the walk stops cleanly).  A missing artifact also stops the walk
    (no crash).

    Returns the list of :class:`Feedback` records written, ordered from the
    tail (``task_id``) back through the chain.  Each record carries
    ``chain=True`` so callers can distinguish chain-graded records from
    standalone grades. ``author`` (c17/h14) is applied to every episode in the
    chain, same as ``rating``/``notes``/``by``.
    """
    records: list[Feedback] = []
    visited: set[str] = set()

    current_id: str | None = task_id
    while current_id is not None:
        if current_id in visited:
            break  # cycle detected — stop cleanly
        visited.add(current_id)

        # Resolve the artifact for this episode.
        artifact_path = find_artifact(repo_path, current_id)
        if artifact_path is None:
            break  # missing artifact — stop cleanly

        # Write feedback for this episode.
        record = write_feedback(
            repo_path,
            current_id,
            rating=rating,
            notes=notes,
            by=by,
            at=at,
            author=author,
        )
        record.chain = True
        # Re-write with the chain marker so the persisted record carries it.
        path = feedback_path(repo_path, current_id, author=author)
        path.write_text(
            json.dumps(record.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        records.append(record)

        # Walk to the next ancestor.
        try:
            data = json.loads(artifact_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            break
        parent = data.get("continued_from")
        if not isinstance(parent, str) or not parent:
            break
        current_id = parent

    return records


def read_feedback(
    repo_path: str | Path, task_id: str, author: str = DEFAULT_AUTHOR
) -> Optional[Feedback]:
    """Read the ``author``'s feedback record for ``task_id``, or ``None`` when none exists.

    A missing file is a clean no-op (returns ``None``) — "no feedback yet" is a
    state, not an error. A present-but-corrupt file raises :class:`FeedbackError`,
    as does an ``author`` outside :data:`ALLOWED_AUTHORS`. Reads the new
    ``.colleague/`` dir first, then the legacy ``.convertible/`` dir. ``author``
    defaults to ``"operator"`` — the same record every pre-author caller reads.
    """
    path = feedback_read_path(repo_path, task_id, author=author)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FeedbackError(f"cannot read feedback for {task_id}: {exc}") from exc
    return Feedback.from_dict(data)


@dataclass
class WorkSummary:
    """One row of :func:`list_work_items`: a work item identified by its request + grade.

    The durable answer to "which drive was that?" when the order is forgotten and
    ``last`` can't be trusted — every recorded work item, recognisable by its request
    and result, gradable by its ``task_id``. ``rating`` is ``None`` for an
    ungraded work item (a clean state, not an error).
    """

    task_id: str
    started_at: str = ""
    status: str = ""
    request: str = ""
    summary: str = ""
    rating: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "started_at": self.started_at,
            "status": self.status,
            "request": self.request,
            "summary": self.summary,
            "rating": self.rating,
        }


def _load_work_artifact(path: Path) -> Optional[dict[str, Any]]:
    """Parse a result-artifact JSON file, or ``None`` to skip it.

    Skips feedback records (``*.feedback.json``), correction-capture sidecars
    (``*-correction-capture.json``, t12), and any unreadable/corrupt file —
    :func:`list_work_items` is best-effort and must never raise on a stray file.
    """
    if path.name.endswith(".feedback.json") or path.name.endswith(_CAPTURE_SUFFIX):
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _work_rating(repo_path: str | Path, task_id: str) -> Optional[int]:
    """The recorded rating for ``task_id``, or ``None`` (corrupt feedback ignored)."""
    try:
        record = read_feedback(repo_path, task_id)
    except FeedbackError:
        return None
    return record.rating if record is not None else None


def _work_summary(repo_path: str | Path, data: dict[str, Any]) -> WorkSummary:
    """Build a :class:`WorkSummary` from a parsed artifact + its feedback grade."""
    stats = data.get("stats") or {}
    task_id = str(data.get("task_id") or "")
    return WorkSummary(
        task_id=task_id,
        started_at=str(stats.get("started_at") or ""),
        status=str(data.get("status") or ""),
        request=str(stats.get("request") or ""),
        summary=str(data.get("summary") or ""),
        rating=_work_rating(repo_path, task_id),
    )


def list_work_items(repo_path: str | Path) -> list[WorkSummary]:
    """Every recorded work item in the repo, newest-first, with its grade folded in.

    Scans the artifact dirs (new then legacy) for result-JSON files — excluding
    each work item's ``<task_id>.feedback.json`` — reads the authoritative ``task_id``
    from the JSON *contents* (so the filename scheme, bare or slugged, doesn't
    matter), and pairs it with its feedback rating (``None`` when ungraded).
    Tolerant: an unreadable or corrupt file is skipped, never raised. Deduped by
    ``task_id`` (the new dir shadows the legacy one); sorted by ``stats.started_at``
    descending (drives without a timestamp sort last).
    """
    seen: set[str] = set()
    rows: list[WorkSummary] = []
    for directory in artifact_read_dirs(repo_path):
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.json")):
            data = _load_work_artifact(path)
            if data is None:
                continue
            task_id = str(data.get("task_id") or "")
            if task_id and task_id not in seen:
                seen.add(task_id)
                rows.append(_work_summary(repo_path, data))
    rows.sort(key=lambda r: r.started_at, reverse=True)
    return rows


# ---------------------------------------------------------------------------
# `feedback export` — the ROI ledger line (docs/contract.md)
# ---------------------------------------------------------------------------


def parse_since(value: str) -> Optional[datetime.datetime]:
    """Best-effort ISO-8601 date/datetime parse, coerced to UTC-aware.

    Accepts a bare date (``2026-07-01``) or a full ISO-8601 timestamp, with or
    without a timezone offset. A naive value is assumed UTC (matching
    ``_now_iso``'s own UTC-aware stamps and ``stats.started_at``) so a
    bare-date ``--since`` compares correctly. Returns ``None`` on anything
    unparseable rather than raising — the CLI layer decides whether that is a
    hard error (a malformed ``--since`` flag) or a soft skip (a malformed
    ``started_at`` read back from a stray artifact).
    """
    try:
        parsed = datetime.datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed


def _safe_int(value: Any) -> int:
    """Coerce to int, returning 0 on any non-int-coercible value (best-effort)."""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _read_work_stats_slim(repo_path: str | Path, task_id: str) -> dict[str, int]:
    """The export line's slim ``stats`` sub-shape for ``task_id``'s artifact.

    Best-effort: a missing or corrupt artifact yields all-zero counts rather
    than raising — the export is a reporting convenience over an already
    graded work item, never a hard dependency on artifact health.
    """
    zero = {"steps": 0, "files_changed": 0, "bytes_written": 0}
    path = find_artifact(repo_path, task_id)
    if path is None:
        return zero
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return zero
    if not isinstance(data, dict):
        return zero
    stats = data.get("stats")
    if not isinstance(stats, dict):
        return zero
    return {
        "steps": _safe_int(stats.get("step_count")),
        "files_changed": _safe_int(stats.get("files_changed")),
        "bytes_written": _safe_int(stats.get("bytes_written")),
    }


def export_work_items(
    repo_path: str | Path,
    *,
    min_rating: Optional[int] = None,
    since: Optional[str] = None,
    include_cortex_authored: bool = False,
) -> list[dict[str, Any]]:
    """Every **graded** work item, newest-first, as one export-line dict each.

    Joins :func:`list_work_items` (scan + dedup + ordering) with each work
    item's :class:`Feedback` record and a slim stats read — no new storage,
    no new file format. An **ungraded** work item (no feedback record) is
    excluded entirely (docs/contract.md's "ROI ledger, not a work-item
    inventory" distinction from ``feedback list``).

    ``min_rating`` keeps only rows with ``rating >= min_rating`` (``None`` /
    non-positive is a no-op — every rating is already ``>= 1``). ``since`` is
    an ISO-8601 date/datetime string; only rows whose ``stats.started_at`` is
    on or after it are kept. A row whose ``started_at`` cannot be parsed is
    excluded when a ``since`` filter is active (conservative — an
    unparseable timestamp can't be proven to satisfy the filter).

    **Author filter (c30/h25 — flywheel exclusion):** by default only
    operator-authored feedback records are exported. Cortex-authored records
    (a model grading its own work) are excluded because a model grading its
    own work must not train itself — the feedback export feeds the learning
    loop, and including self-grades would create a feedback flywheel where
    the model reinforces its own biases. Use ``include_cortex_authored=True``
    to opt in explicitly when you need the full picture.
    """
    since_dt = parse_since(since) if since else None
    rows: list[dict[str, Any]] = []
    for item in list_work_items(repo_path):
        # Determine which author's record to use.
        # Operator always takes precedence (the human's judgment is the
        # authoritative grade for the ROI ledger).
        op_record = _work_feedback_record(repo_path, item.task_id, author=DEFAULT_AUTHOR)
        ctx_record: Optional[Feedback] = None
        if include_cortex_authored:
            ctx_record = _work_feedback_record(repo_path, item.task_id, author=CORTEX_AUTHOR)

        record = op_record if op_record is not None else ctx_record
        if record is None:
            continue  # no feedback record at all — skip

        # Apply filters using the selected record's rating.
        if min_rating is not None and min_rating > 0 and record.rating < min_rating:
            continue
        if since_dt is not None:
            started = parse_since(item.started_at) if item.started_at else None
            if started is None or started < since_dt:
                continue

        rows.append(
            {
                "task_id": item.task_id,
                "request": item.request,
                "summary": item.summary,
                "rating": record.rating,
                "notes": record.notes,
                "status": item.status,
                "at": record.at,
                "stats": _read_work_stats_slim(repo_path, item.task_id),
            }
        )
    return rows


def _work_feedback_record(
    repo_path: str | Path, task_id: str, *, author: str = DEFAULT_AUTHOR
) -> Optional[Feedback]:
    """The feedback record for ``task_id`` from the given ``author``, or ``None``."""
    try:
        return read_feedback(repo_path, task_id, author=author)
    except FeedbackError:
        return None


# ---------------------------------------------------------------------------
# Seamless auto-trigger lane (plan t12, covers c18/h15) — the ROI loop closes
# the loop on itself: a graded/merged work item's own correction (what an
# operator or a follow-up run fixed) becomes a code-lesson, WITHOUT an
# operator having to remember to ask for it.
#
# ONE shared best-effort primitive (`maybe_capture_correction`) fires from TWO
# triggers:
#   1. grade time — wired into `write_feedback` above.
#   2. work-start — `capture_uncaptured_predecessor` (built on the pure-ish
#      `find_uncaptured_predecessor` detector), wired into
#      `colleague.cli._commands.work.execute_work`.
#
# Both triggers share the SAME honesty contract: ANY missing fact, or ANY
# exception raised anywhere in the correction/memory machinery, yields an
# observable non-raising outcome — "fired" / "skipped" / "failed", with a
# `reason` — persisted as a sidecar JSON file beside the work item's own
# artifact (`<task_id>-correction-capture.json`, read back via
# `read_correction_capture`). A capture failure can only ever ADD that
# sidecar; it never blocks or undoes the action that triggered it (a grade,
# or the next work item starting) — c18's pinned behavior.
# ---------------------------------------------------------------------------

#: Outcome vocabulary for a correction-capture attempt (t12).
CAPTURE_FIRED = "fired"
CAPTURE_SKIPPED = "skipped"
CAPTURE_FAILED = "failed"

#: The sidecar filename suffix. Deliberately a HYPHEN (not the dot every real
#: artifact/feedback filename uses right after the task id) so
#: :func:`colleague.artifact.find_artifact`'s ``<task_id>.*.json`` glob can
#: never mistake this sidecar for the work item's own result artifact.
_CAPTURE_SUFFIX = "-correction-capture.json"


def _capture_filename(task_id: str) -> str:
    return f"{task_id}{_CAPTURE_SUFFIX}"


def correction_capture_path(repo_path: str | Path, task_id: str) -> Path:
    """The correction-capture sidecar WRITE path for ``task_id`` (t12).

    ``task_id`` is validated the same way :func:`feedback_path` validates its
    own (traversal guard) — this sidecar lives beside the work item's
    artifact and feedback record in :func:`~colleague.artifact.artifact_dir`.
    """
    safe_id = _validate_task_id(task_id)
    return artifact_dir(repo_path) / _capture_filename(safe_id)


def read_correction_capture(repo_path: str | Path, task_id: str) -> Optional[dict[str, Any]]:
    """Read back ``task_id``'s correction-capture outcome, or ``None`` if none exists.

    Best-effort read across the new dir then the legacy dir (mirrors
    :func:`feedback_read_path`): a missing or corrupt sidecar is a clean
    ``None``, never an error — "no capture attempted yet" is a state, not a
    failure.
    """
    if task_id in (".", "..") or not _SAFE_TASK_ID.match(task_id or ""):
        return None  # a tolerant traversal guard — read-only, never raises
    filename = _capture_filename(task_id)
    for directory in artifact_read_dirs(repo_path):
        path = directory / filename
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None
    return None


def _write_correction_capture(repo_path: str | Path, task_id: str, outcome: dict[str, Any]) -> None:
    """Persist a correction-capture outcome; best-effort (never raises).

    Two narrow, typed except clauses (matching the ``ensure_self_ignored``/
    ``_reap_dangling_last_work`` convention elsewhere in this module) rather
    than a bare ``except Exception: pass`` — a bad/unsafe ``task_id`` raises
    :class:`FeedbackError` from :func:`correction_capture_path`; an unwritable
    dir raises :class:`OSError`. Either way, persisting the outcome is itself
    best-effort — it must never be the thing that raises.
    """
    try:
        path = correction_capture_path(repo_path, task_id)
    except FeedbackError:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        ensure_self_ignored(path.parent)
        path.write_text(json.dumps(outcome, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except OSError:
        pass


def _capture_precondition_reason(result: Any) -> Optional[str]:
    """The honest skip reason when a capture precondition is missing, else None."""
    if result is None:
        return "no artifact found for this work item"
    if not result.pr_url:
        return "artifact carries no pr_url (no PR opened / not handed off)"
    if not result.tip_sha:
        return "artifact carries no tip_sha (handoff produced no commit)"
    return None


def _capture_hunks_as_lessons(repo_path: str | Path, result: Any, outcome: dict[str, Any]) -> None:
    """Resolve the merge, diff the tip, store one code-lesson per hunk (t12)."""
    changed_files = list(result.changed_files or [])
    merge_sha = correction.resolve_merge_commit(repo_path, result.pr_url)
    diff_record = correction.capture_correction_diff(
        repo_path, result.tip_sha, merge_sha, changed_files
    )
    if not diff_record.ok:
        outcome["reason"] = diff_record.note or "correction diff unavailable"
        return
    stored = 0
    for hunk in diff_record.hunks.values():
        lesson = correction.build_code_lesson(hunk)
        lesson_record = memorymod.build_code_lesson_record(
            area=lesson.area or lesson.file_path,
            convention=lesson.convention or f"correction on {lesson.file_path}",
            evidence=lesson.evidence,
            confidence=memorymod.Confidence.low,
        )
        if memorymod.remember(repo_path, lesson_record):
            stored += 1
    outcome["outcome"] = CAPTURE_FIRED
    outcome["hunks_captured"] = len(diff_record.hunks)
    outcome["lessons_stored"] = stored
    outcome["reason"] = f"captured {len(diff_record.hunks)} hunk(s), stored {stored} lesson(s)"


def maybe_capture_correction(repo_path: str | Path, task_id: str) -> dict[str, Any]:
    """Best-effort correction-diff capture for one work item (t12, c18/h15).

    Reads ``task_id``'s own artifact; when it carries BOTH ``pr_url`` and
    ``tip_sha`` (the two facts :func:`colleague.correction.capture_correction_diff`
    needs beyond ``changed_files``, itself always present on the artifact),
    resolves the PR's squash-merge commit
    (:func:`colleague.correction.resolve_merge_commit`) and captures the
    scoped diff (:func:`colleague.correction.capture_correction_diff`). Each
    resulting hunk becomes one code-lesson
    (:func:`colleague.correction.build_code_lesson` +
    :func:`colleague.memory.build_code_lesson_record`) stored via
    :func:`colleague.memory.remember`.

    **Idempotent short-circuit:** when a PRIOR call already recorded a FIRED
    outcome for this ``task_id``, that record is returned unchanged — no
    re-resolution, no re-diff, no re-remember (a re-grade of an already
    correction-captured work item is a cheap no-op).

    **Never raises.** ANY missing fact yields an honest ``"skipped"`` outcome
    naming the missing fact; ANY exception anywhere in the correction/memory
    call chain yields a ``"failed"`` outcome naming the exception — this
    function's own try/except is the honesty boundary: a capture failure can
    only ever be recorded, never propagated (c18's pinned "the grade must
    always land" behavior). The outcome is both returned AND persisted as a
    sidecar (:func:`_write_correction_capture`) so a caller that only wants
    the side effect (the grade-time / work-start triggers) doesn't need the
    return value, and a test can read it back independently.
    """
    outcome: dict[str, Any] = {
        "task_id": task_id,
        "outcome": CAPTURE_SKIPPED,
        "reason": "",
        "hunks_captured": 0,
        "lessons_stored": 0,
        "at": _now_iso(),
    }
    try:
        existing = read_correction_capture(repo_path, task_id)
        if existing is not None and existing.get("outcome") == CAPTURE_FIRED:
            return existing  # already captured — idempotent short-circuit, no re-fire

        result = read_artifact(repo_path, task_id)
        reason = _capture_precondition_reason(result)
        if reason is not None:
            outcome["reason"] = reason
        else:
            _capture_hunks_as_lessons(repo_path, result, outcome)
    except Exception as exc:  # noqa: BLE001 - a capture failure must never block/fail the grade
        outcome["outcome"] = CAPTURE_FAILED
        outcome["reason"] = f"correction capture failed: {exc}"

    _write_correction_capture(repo_path, task_id, outcome)
    return outcome


def find_uncaptured_predecessor(repo_path: str | Path) -> Optional[str]:
    """The repo's most recent work item's ``task_id``, IF it looks like an
    uncaptured merged predecessor — or ``None`` (t12 AC3).

    Read-only detection, no subprocess: reads the ``last_work`` pointer and
    that work item's own artifact — the actual merge-commit lookup (which
    DOES shell out) happens only inside :func:`maybe_capture_correction`,
    called separately by :func:`capture_uncaptured_predecessor` once this
    function has said there is something worth attempting.

    Returns the task_id when the last work item's artifact carries BOTH
    ``pr_url`` and ``tip_sha`` (a plausible merge candidate) AND no PRIOR
    capture attempt for it already recorded a FIRED outcome. A prior
    ``"skipped"``/``"failed"`` attempt still counts as uncaptured — worth
    retrying later (e.g. the PR may have merged since, or ``gh`` may now be
    reachable) — only a FIRED capture is considered done. Returns ``None``
    when there is no last-work pointer, its artifact is missing either fact,
    or it was already captured.
    """
    task_id = get_last_work(repo_path)
    if not task_id:
        return None
    result = read_artifact(repo_path, task_id)
    if result is None or not result.pr_url or not result.tip_sha:
        return None
    existing = read_correction_capture(repo_path, task_id)
    if existing is not None and existing.get("outcome") == CAPTURE_FIRED:
        return None
    return task_id


def capture_uncaptured_predecessor(repo_path: str | Path) -> Optional[dict[str, Any]]:
    """Colleague's own action as trigger (t12 AC3): if the repo's last work
    item looks like an uncaptured merged predecessor
    (:func:`find_uncaptured_predecessor`), capture it now.

    Meant to be called best-effort at the START of the NEXT work item (see
    ``colleague.cli._commands.work.execute_work``) — the moment colleague
    itself notices a predecessor nobody ever graded-and-captured. Returns the
    capture outcome dict, or ``None`` when there was no predecessor to
    capture (the common case — every caller must treat ``None`` as "nothing
    to do", never as a failure). Inherits :func:`maybe_capture_correction`'s
    own never-raises contract, so a caller can invoke this unguarded.
    """
    task_id = find_uncaptured_predecessor(repo_path)
    if task_id is None:
        return None
    return maybe_capture_correction(repo_path, task_id)
