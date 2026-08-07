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

Embedder env overrides (one-embedder increment, S2, colleague#291/#292 task
t19). Both functions accept an optional ``env_overrides`` mapping — the
loop threads ``config.embed_env`` (built from the resolved lobes ``embedder``
role, see :func:`colleague.lobes.embed_env`) through here so the eidetic CLI
child inherits ``EIDETIC_EMBED_URL``/``EIDETIC_EMBED_MODEL`` when armed.
**Operator wins**: the merge order is ``env_overrides`` first, then
``os.environ`` (which shadows any override key already present in the
caller's own environment), then :func:`identity_env` last (unchanged
precedence) — an env var an operator already exported is NEVER overwritten
by a lobes-discovered value. Absent *env_overrides* (the default, ``None``)
is byte-identical to before this task.
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
    env_overrides: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Search the repo's eidetic memory store and return matching records.

    Args:
        repo_path: The repo root; the child runs with ``cwd`` pinned here.
        query: The search query to pass to ``eidetic recall``.
        top_k: Maximum number of results (default 5).
        env_overrides: Optional env vars to merge in (e.g. the embedder's
            ``EIDETIC_EMBED_URL``/``_MODEL``, S2 task t19) — an operator-set
            env var of the SAME name always wins (see module docstring).

    Returns:
        A list of result dicts parsed from the CLI's JSON output.
        Returns an empty list if the CLI is absent or output is malformed.
    """
    cli_path = shutil.which("eidetic")
    if cli_path is None:
        return []

    root_path = Path(repo_path).resolve()
    identity = resolve_identity(root_path)
    env = {**(env_overrides or {}), **os.environ, **identity_env(identity)}

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
    except (subprocess.TimeoutExpired, OSError):
        return []

    stdout = proc.stdout or ""
    try:
        results = json.loads(stdout)
        if isinstance(results, list):
            return results
        return []
    except ValueError:
        return []


def remember(
    repo_path: str | Path,
    record: dict[str, Any],
    *,
    timeout: float = _TIMEOUT_SECONDS,
    env_overrides: dict[str, str] | None = None,
) -> bool:
    """Store a memory record in the repo's eidetic memory store.

    Args:
        repo_path: The repo root; the child runs with ``cwd`` pinned here.
        record: The record dict to store, serialized as JSON.
        env_overrides: Optional env vars to merge in (e.g. the embedder's
            ``EIDETIC_EMBED_URL``/``_MODEL``, S2 task t19) — an operator-set
            env var of the SAME name always wins (see module docstring).

    Returns:
        ``True`` if the CLI succeeded (exit code 0), ``False`` otherwise.
        Returns ``False`` if the CLI is absent.
    """
    cli_path = shutil.which("eidetic")
    if cli_path is None:
        return False

    root_path = Path(repo_path).resolve()
    identity = resolve_identity(root_path)
    env = {**(env_overrides or {}), **os.environ, **identity_env(identity)}

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
    except (subprocess.TimeoutExpired, OSError):
        return False

    return proc.returncode == 0


# ── pure helpers for the runtime wiring (plan t2) ────────────────────────────

#: Cap on the injected prior-lessons block, in characters (~1k tokens) — h7's
#: "recall injection is token-capped" without bundling a tokenizer.
RECALL_BLOCK_CAP = 4000


#: Cap on each folded report field in the lesson text, in characters.
_REPORT_FIELD_CAP = 200


def _fold_lint(report: "Any") -> str:
    """Fold a LintReport into one bounded sentence."""
    parts = []
    for item in getattr(report, "fixed", None) or []:
        parts.append(str(item)[:_REPORT_FIELD_CAP])
    for item in getattr(report, "residual", None) or []:
        parts.append(str(item)[:_REPORT_FIELD_CAP])
    for item in getattr(report, "skipped", None) or []:
        parts.append(str(item)[:_REPORT_FIELD_CAP])
    if not parts:
        return ""
    joined = "; ".join(parts)
    return "Lint: " + joined[:_REPORT_FIELD_CAP] + "."


def _fold_test_integrity(report: "Any") -> str:
    """Fold a TestIntegrityReport into one bounded sentence."""
    findings = getattr(report, "findings", None) or []
    if not findings:
        return ""
    parts = []
    for f in findings:
        sym = str(getattr(f, "symbol", "?"))[:_REPORT_FIELD_CAP]
        kind = str(getattr(f, "kind", "?"))
        tf = str(getattr(f, "test_file", "?"))[:_REPORT_FIELD_CAP]
        imf = str(getattr(f, "impl_file", "?"))[:_REPORT_FIELD_CAP]
        parts.append(f"{sym} ({kind}): {tf} ↔ {imf}")
    return "Test integrity: " + "; ".join(parts) + "."


def _fold_affected_tests(report: "Any") -> str:
    """Fold an AffectedTestsReport into one bounded sentence."""
    status = str(getattr(report, "status", "?"))
    selected = getattr(report, "selected", None) or []
    total = getattr(report, "total", 0)
    passed = getattr(report, "passed", None)
    failed = getattr(report, "failed", None)
    counts = []
    if passed is not None:
        counts.append(f"{passed} passed")
    if failed is not None:
        counts.append(f"{failed} failed")
    tail = ", ".join(counts) or status
    cap_note = f" (capped from {total})" if getattr(report, "capped", False) else ""
    files = ", ".join(str(s)[:_REPORT_FIELD_CAP] for s in selected[:5])
    if len(selected) > 5:
        files += f" +{len(selected) - 5} more"
    return f"Affected tests: {status} — {len(selected)} file(s){cap_note}: {tail} ({files})."


def compose_lesson_text(result: "Any", request_head: str = "") -> str:
    """Compose the remember-after lesson text from a finished result (#379 rung 1).

    Deterministic — no model turn. Beyond the always-present telemetry
    prefix (stub-compatible: recall consumers parse it), a run that carries
    FAILURE SUBSTANCE gets it folded in verbatim, bounded per field: the
    #313 incompletion record (reason, evidence, recommendation), the error
    string, and any stale-pin refresh warnings — so a future run recalling
    this record learns WHAT failed and what to do differently, not just
    step counts. An ok run without substance stays byte-compatible with the
    pre-#379 stub shape.

    Rung 1.5: lint_report, test_integrity_report, and affected_tests_report
    are each folded into the lesson text, bounded per field.
    """
    stats = result.stats
    tools = ", ".join(f"{k}={v}" for k, v in sorted(stats.tool_counts.items()))
    text = (
        f"Work item {result.task_id} finished {result.status} on request: "
        f"{request_head}. steps={stats.step_count}, tools=({tools}), "
        f"files_changed={len(result.changed_files)}."
    )
    signals = []
    if result.finish_recovered:
        signals.append(f"finish_recovered={result.finish_recovered}")
    if result.capacity_warning:
        signals.append("capacity_warning")
    if result.not_finished:
        signals.append("step budget exhausted")
    if result.stopped_without_finish:
        signals.append("stopped without finish")
    if signals:
        text += " Signals: " + "; ".join(signals) + "."
    inc = getattr(result, "incompletion", None)
    if inc is not None:
        text += (
            f" Incompletion: {str(inc.reason)[:120]} — "
            f"evidence: {str(inc.evidence)[:200]}; "
            f"recommendation: {str(inc.recommendation)[:200]}."
        )
    error = getattr(result, "error", None)
    if error:
        text += f" Error: {str(error)[:200]}."
    for w in getattr(result, "warnings", None) or []:
        text += (
            f" Model-pin refresh ({w.get('point', '?')}): "
            f"{w.get('stale_id', '?')} (via {w.get('source', '?')}) -> "
            f"{w.get('refreshed_id', '?')}."
        )
    # Rung 1.5: fold pre-finish gate reports
    lint = getattr(result, "lint_report", None)
    if lint is not None:
        text += " " + _fold_lint(lint)
    ti = getattr(result, "test_integrity_report", None)
    if ti is not None:
        text += " " + _fold_test_integrity(ti)
    at = getattr(result, "affected_tests_report", None)
    if at is not None:
        text += " " + _fold_affected_tests(at)
    return text


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
