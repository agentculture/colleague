"""Curated memory loop tool — shell out to the operator-installed eidetic CLI.

The runtime offers two public functions that delegate to the ``eidetic`` CLI:

- ``recall(repo_path, query, top_k=5)`` — search the repo's memory store
- ``remember(repo_path, record)`` — store a new memory record

An allow-list (:data:`ALLOWED_VERBS`) restricts which eidetic verbs are
reachable: exactly ``recall`` and ``remember``.  This mirrors the pattern
used by :mod:`colleague.culture` and :mod:`colleague.devague`.

Identity propagation. Each invocation injects the resolved process identity
into the child via :func:`colleague.identity.identity_env` so the CLI
inherits ``COLLEAGUE_IDENTITY``, and runs with ``cwd`` pinned at the repo
path so the store resolves to the repo's ``.eidetic/memory``.  The CLI is
*launched as a subprocess*, never imported as Python.

When the ``eidetic`` CLI is absent (not found via ``shutil.which``), both
functions are strict no-ops: ``recall`` returns ``[]`` and ``remember``
returns ``False`` — no subprocess is attempted, no exception is raised.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess  # nosec B404 - launching operator CLI is the point (trusted env, D2)
from pathlib import Path
from typing import Any

from colleague.identity import identity_env, resolve_identity

#: The curated allow-list of eidetic verbs the engine may invoke.
#: Only ``recall`` and ``remember`` are reachable.
ALLOWED_VERBS: frozenset[str] = frozenset({"recall", "remember"})

#: Bound a runaway CLI so it cannot stall the loop indefinitely.
_TIMEOUT_SECONDS = 300


def recall(
    repo_path: str | Path,
    query: str,
    *,
    top_k: int = 5,
    timeout: float = _TIMEOUT_SECONDS,
) -> list[dict[str, Any]]:
    """Search the repo's eidetic memory store and return matching records.

    Args:
        repo_path: The repo root; the child runs with ``cwd`` pinned here.
        query: The search query to pass to ``eidetic recall``.
        top_k: Maximum number of results (default 5).

    Returns:
        A list of result dicts parsed from the CLI's JSON output.
        Returns an empty list if the CLI is absent or output is malformed.
    """
    cli_path = shutil.which("eidetic")
    if cli_path is None:
        return []

    root_path = Path(repo_path).resolve()
    identity = resolve_identity(root_path)
    env = {**os.environ, **identity_env(identity)}

    argv = [
        "eidetic",
        "recall",
        query,
        "--json",
        "--top-k",
        str(top_k),
        "--scope",
        "colleague",
        "--visibility",
        "public",
    ]

    try:
        proc = subprocess.run(  # nosec B603 - allow-listed verb, no shell, trusted env (D2)
            argv,
            cwd=str(root_path),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []

    stdout = proc.stdout or ""
    try:
        results = json.loads(stdout)
        if isinstance(results, list):
            return results
        return []
    except (json.JSONDecodeError, ValueError):
        return []


def remember(
    repo_path: str | Path,
    record: dict[str, Any],
    *,
    timeout: float = _TIMEOUT_SECONDS,
) -> bool:
    """Store a memory record in the repo's eidetic memory store.

    Args:
        repo_path: The repo root; the child runs with ``cwd`` pinned here.
        record: The record dict to store, serialized as JSON.

    Returns:
        ``True`` if the CLI succeeded (exit code 0), ``False`` otherwise.
        Returns ``False`` if the CLI is absent.
    """
    cli_path = shutil.which("eidetic")
    if cli_path is None:
        return False

    root_path = Path(repo_path).resolve()
    identity = resolve_identity(root_path)
    env = {**os.environ, **identity_env(identity)}

    record_json = json.dumps(record)
    argv = [
        "eidetic",
        "remember",
        record_json,
        "--scope",
        "colleague",
        "--visibility",
        "public",
    ]

    try:
        proc = subprocess.run(  # nosec B603 - allow-listed verb, no shell, trusted env (D2)
            argv,
            cwd=str(root_path),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False

    return proc.returncode == 0


# ── pure helpers for the runtime wiring (plan t2) ────────────────────────────

#: Cap on the injected prior-lessons block, in characters (~1k tokens) — h7's
#: "recall injection is token-capped" without bundling a tokenizer.
RECALL_BLOCK_CAP = 4000


def build_recall_block(records: list[dict[str, Any]], *, cap_chars: int = RECALL_BLOCK_CAP) -> str:
    """Render recalled records as one advisory context block, capped.

    Pure formatting — no subprocess. Empty/non-text records are skipped; an
    all-empty result yields ``""`` (the caller injects nothing).
    """
    lines = ["[memory] Prior lessons recalled from this repo's memory store (advisory):"]
    for rec in records:
        text = str(rec.get("text", "")).strip()
        if text:
            lines.append(f"- {text}")
    if len(lines) == 1:
        return ""
    return "\n".join(lines)[:cap_chars]


def build_lesson_record(task_id: str, text: str, metadata: dict[str, Any]) -> dict[str, Any]:
    """Shape one work-item lesson as an eidetic record (id/type/text/metadata).

    Idempotent by construction: the id is derived from the task id, so a
    re-remember upserts in place (eidetic dedups by id) instead of duplicating.
    """
    return {
        "id": f"work-lesson-{task_id}",
        "type": "work-lesson",
        "text": text,
        "metadata": dict(metadata),
    }
