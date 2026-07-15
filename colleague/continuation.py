"""Continuation: resolve a prior work item and build a seed for continuation.

Given a task reference (``"last"`` or an explicit task id), this module resolves
the work item, loads its artifact, guards against continuing a completed or
missing work item, and returns a seed text that embeds the full continuation
record plus the original request verbatim.

Pure stdlib. Imports only from ``colleague.{artifact,feedback,escalation,contract}``.
"""

from __future__ import annotations

import json
from pathlib import Path

from colleague.artifact import find_artifact
from colleague.contract import OK, TaskResult
from colleague.escalation import build_continuation


class ContinuationError(Exception):
    """A continuation operation that cannot be honored."""


def resolve_continuation(
    repo: str | Path,
    ref: str,
    *,
    allow_completed: bool = False,
) -> tuple[str, str]:
    """Resolve *ref* to a prior work item and return ``(task_id, seed_text)``.

    Parameters
    ----------
    repo:
        The repository root path.
    ref:
        Either ``"last"`` (resolved via :func:`colleague.feedback.get_last_work`)
        or an explicit task-id string.
    allow_completed:
        When ``True``, allow continuing from a work item whose status is ``"ok"``.
        Default ``False`` raises :class:`ContinuationError` for completed items.

    Returns
    -------
    tuple[str, str]
        ``(task_id, seed_text)`` where *seed_text* is a preamble + the
        :func:`colleague.escalation.build_continuation` record + the original
        request verbatim.

    Raises
    ------
    ContinuationError
        When the artifact is missing, corrupt, or the work item finished ok
        (unless *allow_completed* is ``True``).
    """
    repo_path = Path(repo)

    # Resolve the task id from the ref.
    if ref == "last":
        from colleague.feedback import get_last_work

        task_id = get_last_work(repo_path)
        if task_id is None:
            raise ContinuationError("no 'last' work item recorded for this repo yet")
    else:
        task_id = ref

    # Load the artifact.
    artifact_path = find_artifact(repo_path, task_id)
    if artifact_path is None:
        raise ContinuationError(f"no artifact for {task_id}")

    try:
        data = json.loads(artifact_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        raise ContinuationError(f"corrupt artifact for {task_id}")

    result = TaskResult.from_dict(data)

    # Guard: ok-status artifact unless allow_completed.
    if result.status == OK and not allow_completed:
        raise ContinuationError(f"nothing to continue: {task_id} finished ok")

    # Build the seed text: preamble + continuation record + original request.
    record = build_continuation(result, result.stats)
    request = result.stats.request
    preamble = f"You are CONTINUING work item {task_id} that stopped early. Prior state:\n\n"
    seed_text = f"{preamble}{record}\n\nOriginal request:\n\n{request}"

    return (task_id, seed_text)
