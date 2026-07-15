"""The run report: result artifact + structured trace log (R5).

Every work item produces two files under an artifact directory (``.colleague/`` in
the repo by default):

* ``<task_id>.json`` — the full :class:`~colleague.contract.TaskResult` as JSON,
  the handoff payload for Guildmaster/Taskmaster/Steward;
* ``<task_id>.trace.jsonl`` — one JSON line per loop step, for the operator.

:func:`write` always succeeds for any result it is given — including a failed
run whose ``status == "error"`` (honesty condition h5). The caller is
responsible for constructing an error result and still calling :func:`write`
so a crash never leaves an empty run report; :func:`failed_result` builds that
error result.
"""

from __future__ import annotations

import datetime
import glob
import json
from pathlib import Path
from typing import Optional

from colleague.contract import ERROR, TaskResult
from colleague.slug import slugify

DEFAULT_ARTIFACT_DIRNAME = ".colleague"
#: Deprecated pre-rename artifact dir; consulted on READS only (back-compat), so
#: drives graded under the old name stay readable. Writes always target the new
#: name above.
LEGACY_ARTIFACT_DIRNAME = ".convertible"


def artifact_dir(repo_path: str | Path) -> Path:
    """The default artifact directory inside a repo (the WRITE target)."""
    return Path(repo_path) / DEFAULT_ARTIFACT_DIRNAME


def artifact_read_dirs(repo_path: str | Path) -> list[Path]:
    """Artifact dirs to consult on READS, new name first then legacy fallback.

    A caller that reads a per-work-item artifact (feedback record, last-work pointer)
    should look under the new ``.colleague/`` first and fall back to the legacy
    ``.convertible/`` so a work item recorded before the rename stays readable.
    """
    repo_path = Path(repo_path)
    return [repo_path / DEFAULT_ARTIFACT_DIRNAME, repo_path / LEGACY_ARTIFACT_DIRNAME]


#: Contents of the self-ignoring ``.gitignore`` written into the bookkeeping dir
#: (#322). Mirrors the repo-level rules colleague's own ``.gitignore`` uses:
#: everything local except the two operator-committable subdirs.
_SELF_IGNORE = (
    "# auto-written by colleague: keep run artifacts out of the host repo's git status\n"
    "*\n"
    "!commands/\n"
    "!commands/**\n"
    "!skills/\n"
    "!skills/**\n"
)


def ensure_self_ignored(directory: str | Path) -> None:
    """Write a self-ignoring ``.gitignore`` into the bookkeeping dir (#322).

    A consumer repo that never gitignored ``.colleague/`` would otherwise stage
    the whole run trace (artifact JSON, step trace, ``last_work``) on a routine
    ``git add -A``. The written pattern ignores everything under the dir —
    including the ``.gitignore`` itself, which git still honors — except the
    operator-committable ``commands/`` and ``skills/`` overlays. Idempotent (an
    existing ``.gitignore`` is never overwritten — the operator owns it) and
    best-effort (an unwritable dir never fails a run).
    """
    root = Path(directory)
    marker = root / ".gitignore"
    try:
        if marker.exists():
            return
        root.mkdir(parents=True, exist_ok=True)
        marker.write_text(_SELF_IGNORE, encoding="utf-8")
    except OSError:
        pass


def failed_result(task_id: str, error: str, *, request: str = "") -> TaskResult:
    """Build an error-status result for a work item that raised before completing.

    When ``request`` (the task instruction) is given, it is recorded on the
    result's ``stats`` along with a start timestamp — so even an early-failure
    artifact (one written before the loop could populate stats) stays
    discoverable by request and sortable by time in ``feedback list``, and its
    filename is slugged like any other (#132). Omitting it preserves the prior
    empty-stats behavior byte-for-byte.
    """
    result = TaskResult(task_id=task_id, status=ERROR, summary="work item failed", error=error)
    if request:
        result.stats.request = request
        result.stats.started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    return result


def artifact_stem(task_id: str, request: str) -> str:
    """The filename stem for a work item's artifacts: ``<task_id>.<slug>`` or bare id.

    The ``task_id`` stays the authoritative key; the request *slug* is a lossy
    label appended so the work item is recognisable in an ``ls`` of ``.colleague/``
    (and matches the slug in the work branch — see
    :func:`colleague.handoff._branch_name`). An empty slug (no request, all
    punctuation) falls back to the bare ``task_id`` so the name is always valid.
    """
    slug = slugify(request)
    return f"{task_id}.{slug}" if slug else task_id


def write(result: TaskResult, directory: str | Path) -> Path:
    """Write the result JSON + trace JSONL into ``directory``; return the result path.

    Names the files ``<task_id>.<slug>.json`` / ``.trace.jsonl`` where the slug is
    derived from the work item's request (bare ``<task_id>`` when no slug is
    derivable). Sets ``result.artifacts_path`` to the result-JSON path so the
    value travels inside the artifact itself — the authoritative path for any
    reader, regardless of the naming scheme.
    """
    out = Path(directory)
    out.mkdir(parents=True, exist_ok=True)
    ensure_self_ignored(out)
    stem = artifact_stem(result.task_id, result.stats.request)
    result_path = out / f"{stem}.json"
    result.artifacts_path = str(result_path)

    result_path.write_text(
        json.dumps(result.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    trace_path = out / f"{stem}.trace.jsonl"
    with trace_path.open("w", encoding="utf-8") as fh:
        for step in result.steps:
            fh.write(json.dumps(step.to_dict(), ensure_ascii=False) + "\n")

    return result_path


def _is_safe_segment(task_id: str) -> bool:
    """True when ``task_id`` is a single path segment (no traversal/separators)."""
    return bool(task_id) and task_id not in (".", "..") and not any(c in task_id for c in "/\\")


def find_artifact(repo_path: str | Path, task_id: str) -> Optional[Path]:
    """The result-JSON artifact for ``task_id``, or ``None`` if none exists.

    Resolves **both** the bare legacy name (``<task_id>.json``) and the slugged
    name (``<task_id>.<slug>.json``) across the new ``.colleague/`` dir then the
    legacy ``.convertible/`` dir, so a work item recorded under either scheme stays
    findable. The work item's own ``<task_id>.feedback.json`` is never mistaken for
    its artifact. Returns ``None`` for an unsafe (traversal) id.
    """
    if not _is_safe_segment(task_id):
        return None
    for directory in artifact_read_dirs(repo_path):
        bare = directory / f"{task_id}.json"
        if bare.is_file():
            return bare
        matches = sorted(
            p
            for p in directory.glob(f"{glob.escape(task_id)}.*.json")
            if p.is_file() and not p.name.endswith(".feedback.json")
        )
        if matches:
            return matches[0]
    return None


def read_request(repo_path: str | Path, task_id: str) -> Optional[str]:
    """The original request recorded for ``task_id``, or ``None`` (best-effort).

    Reads the work item's artifact (:func:`find_artifact`) and returns
    ``stats.request``. Any failure — missing artifact, unreadable/corrupt JSON,
    absent field — yields ``None`` so a caller (e.g. the ``feedback last``
    resolution note) never breaks on a gone or malformed artifact.
    """
    path = find_artifact(repo_path, task_id)
    if path is None:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    request = (data.get("stats") or {}).get("request")
    return request if isinstance(request, str) and request else None


def _is_empty_file(path: Path) -> bool:
    """True when ``path`` is a 0-byte regular file (a definitively broken write)."""
    try:
        return path.is_file() and path.stat().st_size == 0
    except OSError:
        return False


def _unlink_action(path: Path, *, dry_run: bool, dry_label: str, ok_label: str) -> str:
    """Delete ``path`` (or report a dry-run); return the action label or ``failed``."""
    if dry_run:
        return dry_label
    try:
        path.unlink()
        return ok_label
    except OSError:
        return "failed"


def _reap_empty_artifact_files(adir: Path, *, dry_run: bool) -> list[dict]:
    """Reap 0-byte ``*.json`` / ``*.trace.jsonl`` under ``adir`` (truncated writes)."""
    results: list[dict] = []
    seen: set[Path] = set()
    for pattern in ("*.json", "*.trace.jsonl"):
        for path in sorted(adir.glob(pattern)):
            if path in seen or not _is_empty_file(path):
                continue
            seen.add(path)
            action = _unlink_action(
                path, dry_run=dry_run, dry_label="would-reap", ok_label="reaped"
            )
            results.append({"artifact": path.name, "action": action})
    return results


def _reap_dangling_last_work(repo: Path, *, dry_run: bool) -> list[dict]:
    """Clear a ``last_work`` pointer that no longer resolves to a real artifact."""
    # Local import avoids a module-level cycle (feedback imports artifact).
    from colleague.feedback import get_last_work, last_work_path

    lw = last_work_path(repo)
    if not lw.is_file():
        return []
    task_id = get_last_work(repo)
    artifact = find_artifact(repo, task_id) if task_id else None
    if artifact is not None and not _is_empty_file(artifact):
        return []  # still resolves to a real (non-empty) artifact — keep it
    action = _unlink_action(lw, dry_run=dry_run, dry_label="would-clear", ok_label="cleared")
    return [{"artifact": lw.name, "action": action}]


def reap_artifacts(repo_path: str | Path, *, dry_run: bool = False) -> list[dict]:
    """Remove orphaned 0-byte ``.colleague/`` artifacts; return per-file actions (#162).

    A crashed work item can leave **0-byte** run artifacts (``<id>.<slug>.json`` /
    ``.trace.jsonl``) and a ``last_work`` pointer aimed at a now-missing/empty
    artifact. This reaps exactly those: a 0-byte ``*.json`` / ``*.trace.jsonl``
    under ``.colleague/`` is unambiguously a truncated write, and a ``last_work``
    that resolves to nothing is dead bookkeeping. A **non-empty** artifact is a
    gradable record the feedback loop depends on and is **never** touched.

    Returns one dict per affected file: ``{artifact, action}`` where ``action`` is
    ``reaped`` / ``would-reap`` (dry-run) / ``failed`` for a file, or
    ``cleared`` / ``would-clear`` / ``failed`` for the ``last_work`` pointer.
    Scoped strictly to the ``.colleague/`` write dir; a missing dir is a no-op.
    """
    repo = Path(repo_path)
    adir = artifact_dir(repo)
    results: list[dict] = []
    if adir.is_dir():
        results.extend(_reap_empty_artifact_files(adir, dry_run=dry_run))
    results.extend(_reap_dangling_last_work(repo, dry_run=dry_run))
    return results
