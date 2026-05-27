"""The dashboard: result artifact + structured trace log (R5).

Every drive produces two files under an artifact directory (``.convertible/`` in
the repo by default):

* ``<task_id>.json`` — the full :class:`~convertible.contract.TaskResult` as JSON,
  the handoff payload for Guildmaster/Taskmaster/Steward;
* ``<task_id>.trace.jsonl`` — one JSON line per loop step, for the operator.

:func:`write` always succeeds for any result it is given — including a failed
run whose ``status == "error"`` (honesty condition h5). The caller is
responsible for constructing an error result and still calling :func:`write`
so a crash never leaves an empty dashboard; :func:`failed_result` builds that
error result.
"""

from __future__ import annotations

import json
from pathlib import Path

from convertible.contract import ERROR, TaskResult

DEFAULT_ARTIFACT_DIRNAME = ".convertible"


def artifact_dir(repo_path: str | Path) -> Path:
    """The default artifact directory inside a repo."""
    return Path(repo_path) / DEFAULT_ARTIFACT_DIRNAME


def failed_result(task_id: str, error: str) -> TaskResult:
    """Build an error-status result for a drive that raised before completing."""
    return TaskResult(task_id=task_id, status=ERROR, summary="drive failed", error=error)


def write(result: TaskResult, directory: str | Path) -> Path:
    """Write the result JSON + trace JSONL into ``directory``; return the result path.

    Sets ``result.artifacts_path`` to the result-JSON path so the value travels
    inside the artifact itself.
    """
    out = Path(directory)
    out.mkdir(parents=True, exist_ok=True)
    result_path = out / f"{result.task_id}.json"
    result.artifacts_path = str(result_path)

    result_path.write_text(
        json.dumps(result.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    trace_path = out / f"{result.task_id}.trace.jsonl"
    with trace_path.open("w", encoding="utf-8") as fh:
        for step in result.steps:
            fh.write(json.dumps(step.to_dict(), ensure_ascii=False) + "\n")

    return result_path
