"""The run report: result artifact + structured trace log (R5).

Every drive produces two files under an artifact directory (``.colleague/`` in
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

    A caller that reads a per-drive artifact (feedback record, last-drive pointer)
    should look under the new ``.colleague/`` first and fall back to the legacy
    ``.convertible/`` so a drive recorded before the rename stays readable.
    """
    repo_path = Path(repo_path)
    return [repo_path / DEFAULT_ARTIFACT_DIRNAME, repo_path / LEGACY_ARTIFACT_DIRNAME]


def failed_result(task_id: str, error: str) -> TaskResult:
    """Build an error-status result for a drive that raised before completing."""
    return TaskResult(task_id=task_id, status=ERROR, summary="drive failed", error=error)


def artifact_stem(task_id: str, request: str) -> str:
    """The filename stem for a drive's artifacts: ``<task_id>.<slug>`` or bare id.

    The ``task_id`` stays the authoritative key; the request *slug* is a lossy
    label appended so the drive is recognisable in an ``ls`` of ``.colleague/``
    (and matches the slug in the drive branch — see
    :func:`colleague.handoff._branch_name`). An empty slug (no request, all
    punctuation) falls back to the bare ``task_id`` so the name is always valid.
    """
    slug = slugify(request)
    return f"{task_id}.{slug}" if slug else task_id


def write(result: TaskResult, directory: str | Path) -> Path:
    """Write the result JSON + trace JSONL into ``directory``; return the result path.

    Names the files ``<task_id>.<slug>.json`` / ``.trace.jsonl`` where the slug is
    derived from the drive's request (bare ``<task_id>`` when no slug is
    derivable). Sets ``result.artifacts_path`` to the result-JSON path so the
    value travels inside the artifact itself — the authoritative path for any
    reader, regardless of the naming scheme.
    """
    out = Path(directory)
    out.mkdir(parents=True, exist_ok=True)
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
    legacy ``.convertible/`` dir, so a drive recorded under either scheme stays
    findable. The drive's own ``<task_id>.feedback.json`` is never mistaken for
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

    Reads the drive's artifact (:func:`find_artifact`) and returns
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
