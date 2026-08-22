"""Curated memory loop tool — shell out to the operator-installed eidetic CLI.

The runtime offers two public functions that delegate to the ``eidetic`` CLI:

- ``recall(repo_path, query, top_k=5)`` — search the repo's memory store
- ``remember(repo_path, record)`` — store a new memory record

A third pair of pure, env-driven helpers — ``filter_for_injection`` /
``filter_recall_records`` — apply recall thresholding + supersedes hygiene to
what gets INJECTED from a recall result (plan t6, spec c10/h9); see the
module comment above their definitions for the full rule and the composition
rule with the retrieval-precision instrumentation.

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

import enum
import hashlib
import json
import os
import re
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

#: Cap on free text riding the eidetic argv (defense-in-depth: argv is
#: shell-free by construction, but model/operator text is still bounded and
#: stripped of control characters before it reaches an OS command).
_CLI_TEXT_CAP = 2000


def _bound_cli_text(text: str, cap: int = _CLI_TEXT_CAP) -> str:
    """Bound + de-control free text before it rides the eidetic argv."""
    cleaned = "".join(ch for ch in str(text) if ch >= " " or ch in "\n\t")
    return cleaned[:cap]


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
        _bound_cli_text(query),
        "--json",
        "--top-k",
        str(top_k),
        "--scope",
        "colleague",
        "--visibility",
        "public",
    ]

    try:
        proc = subprocess.run(  # nosec B603 # NOSONAR - argv list, no shell; free text
            # is bounded+de-controlled (_bound_cli_text) before it rides the argv (S8705)
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
    except ValueError:
        return []
    if isinstance(results, list):
        return results
    if isinstance(results, dict):
        # eidetic >= 0.13 wraps results in an envelope:
        # {"query": ..., "mode": ..., "truncated": ..., "items": [...]}.
        # Accept both shapes so recall keeps working across the CLI's
        # output-contract change (caught live in the #387 proof session:
        # every armed run silently recorded recalled=0).
        items = results.get("items")
        if isinstance(items, list):
            return items
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
        proc = subprocess.run(  # nosec B603 # NOSONAR - argv list, no shell; free text
            # is bounded+de-controlled (_bound_cli_text) before it rides the argv (S8705)
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


#: The metadata ``kind`` value stamped on a split-next-time record (plan t8,
#: spec c15/h10) — see :func:`build_split_record`.
SPLIT_RECORD_KIND = "split-next-time"


def _record_kind(record: dict[str, Any]) -> str:
    """Read a recalled record's stamped ``kind`` from its two declared places.

    Mirrors :func:`record_class_key`'s two-place lookup (``metadata`` first,
    a flattened top-level fallback second) — eidetic CLIs have shipped both
    shapes. Missing/non-string/non-dict metadata reads as ``""``.
    """
    if not isinstance(record, dict):
        return ""
    meta = record.get("metadata")
    if isinstance(meta, dict):
        value = meta.get("kind")
        if isinstance(value, str):
            return value
    value = record.get("kind")
    return value if isinstance(value, str) else ""


def build_recall_block(records: list[dict[str, Any]], *, cap_chars: int = RECALL_BLOCK_CAP) -> str:
    """Render recalled records as one advisory context block, capped.

    Pure formatting — no subprocess. Empty/non-text records are skipped; an
    all-empty result yields ``""`` (the caller injects nothing).

    A recalled ``split-next-time`` record (plan t8, spec c15/h10 — a
    retroactive too-hard/too-long signal from a prior attempt at this same
    task) renders FIRST, as its own "Split recommendation from a prior
    attempt: …" line, ahead of the ordinary prior-lessons block. A recall
    with no such record is byte-identical to the pre-t8 rendering.
    """
    split_lines: list[str] = []
    lesson_records: list[dict[str, Any]] = []
    for rec in records:
        if _record_kind(rec) == SPLIT_RECORD_KIND:
            text = str(rec.get("text", "")).strip()
            if text:
                split_lines.append(f"Split recommendation from a prior attempt: {text}")
        else:
            lesson_records.append(rec)

    lesson_lines = ["[memory] Prior lessons recalled from this repo's memory store (advisory):"]
    for rec in lesson_records:
        text = str(rec.get("text", "")).strip()
        if text:
            lesson_lines.append(f"- {text}")

    lines = list(split_lines)
    if len(lesson_lines) > 1:
        lines.extend(lesson_lines)
    if not lines:
        return ""
    return "\n".join(lines)[:cap_chars]


#: The four seats that a lesson can be attributed to.
_VALID_COMPONENTS: frozenset[str] = frozenset({"front", "worker", "evaluator", "system"})


def attribute_component(thought_ok: bool, action_faithful: bool, verdict_correct: bool) -> str:
    """Determine which seat failed from the triad of boolean facts.

    Attribution table:

    - **front** — faithful action from a bad thought
      (``thought_ok=False``, ``action_faithful=True``)
    - **worker** — good thought but action drift
      (``thought_ok=True``, ``action_faithful=False``)
    - **evaluator** — incorrect evaluator rejection/approval
      (``verdict_correct=False`` and neither of the above); note this INCLUDES
      the good-thought/faithful-action/wrong-verdict case, which is the
      textbook incorrect verdict and belongs to the evaluator, not to
      ``system``
    - **system** — cross-role or routing failure: the residual bucket for a
      failure not attributable to any single seat's policy

    Deterministic and total: every combination of the three booleans maps
    to exactly one of the four component strings. The caller only invokes
    this when there IS a failure to attribute; the all-true input therefore
    falls to ``system`` rather than describing a healthy run.
    """
    if not thought_ok and action_faithful:
        return "front"
    if thought_ok and not action_faithful:
        return "worker"
    if not verdict_correct:
        return "evaluator"
    return "system"


def build_lesson_record(task_id: str, text: str, metadata: dict[str, Any]) -> dict[str, Any]:
    """Shape one work-item lesson as an eidetic record (id/type/text/metadata).

    Idempotent by construction: the id is derived from the task id, so a
    re-remember upserts in place (eidetic dedups by id) instead of duplicating.

    If *metadata* carries a ``component`` key, it must be one of
    ``front``, ``worker``, ``evaluator``, or ``system`` — any other value
    raises ``ValueError``.  A missing ``component`` key is accepted (legacy
    records carry no component).
    """
    meta = dict(metadata)
    comp = meta.get("component")
    if comp is not None and comp not in _VALID_COMPONENTS:
        raise ValueError(
            f"Invalid lesson component {comp!r}; must be one of {sorted(_VALID_COMPONENTS)}"
        )
    return {
        "id": f"work-lesson-{task_id}",
        "type": "work-lesson",
        "text": text,
        "metadata": meta,
    }


# ── retroactive split-next-time record (plan t8, spec c15/h10) ──────────────
#
# A too-hard/too-long signal — the run exhausted its step/#313 budget or ran
# past the operator's ``too_long_min`` — is worth recording so the NEXT
# attempt at the same task is warned up front, before it burns its own
# budget the same way. This is entirely a remember-after / recall-before
# composition inside this module: :func:`should_record_split` is the pure
# predicate, :func:`build_split_record` shapes the record (embedding
# :func:`colleague.autosplit.build_split_recommendation`'s message, imported
# lazily to avoid a colleague.config/colleague.autosplit import cycle at
# module load time), and :func:`maybe_remember_split` is the one place that
# calls :func:`remember` for it — the after-run lane the grep guard in
# ``tests/test_memory_split_record.py`` checks is the ONLY caller (never
# loop.py's step handling, never mid-run).

#: Fallback child-count hint when the caller cannot derive one from a real
#: ``autosplit_target_tokens``/``context_budget_tokens`` pair (e.g. a config
#: object missing those fields) — a fixed, honest "probably split into ~4"
#: rather than a fabricated precise number.
_DEFAULT_SPLIT_CHILD_COUNT = 4

#: Fallback per-child token budget embedded in the recommendation text when
#: the caller's config carries no usable ``context_budget_tokens``.
_DEFAULT_SPLIT_PER_CHILD_BUDGET = 8000


def should_record_split(result: "Any", config: "Any", duration_seconds: float) -> bool:
    """True iff *result* shows a too-hard/too-long signal worth a split hint.

    Any ONE of three independent triggers is sufficient (spec c15/h10):

    - the #313 incompletion reason is exactly
      :data:`colleague.incompletion.REASON_BUDGET_EXHAUSTED`;
    - the run consumed its full step budget
      (``result.stats.step_count >= config.max_steps``);
    - wall-clock *duration_seconds* exceeded ``config.too_long_min`` minutes.

    Pure and IO-free — *config* is duck-typed (only ``max_steps``/
    ``too_long_min`` are read) so a lightweight stand-in works in tests.
    """
    from colleague.incompletion import REASON_BUDGET_EXHAUSTED

    inc = getattr(result, "incompletion", None)
    if inc is not None and getattr(inc, "reason", None) == REASON_BUDGET_EXHAUSTED:
        return True

    stats = getattr(result, "stats", None)
    step_count = getattr(stats, "step_count", 0) if stats is not None else 0
    max_steps = getattr(config, "max_steps", None)
    if isinstance(max_steps, int) and max_steps > 0 and step_count >= max_steps:
        return True

    too_long_min = getattr(config, "too_long_min", None)
    if isinstance(too_long_min, (int, float)) and too_long_min > 0:
        if duration_seconds > too_long_min * 60:
            return True

    return False


def _split_reason(result: "Any", config: "Any") -> str:
    """The single reason label that made :func:`should_record_split` true.

    Priority order matches the predicate's own checks — the #313 reason wins
    when present, else the step-budget signal, else the wall-clock signal.
    Callers only reach here after :func:`should_record_split` returned
    ``True``, so one of the three always applies.
    """
    from colleague.incompletion import REASON_BUDGET_EXHAUSTED

    inc = getattr(result, "incompletion", None)
    if inc is not None and getattr(inc, "reason", None) == REASON_BUDGET_EXHAUSTED:
        return REASON_BUDGET_EXHAUSTED

    stats = getattr(result, "stats", None)
    step_count = getattr(stats, "step_count", 0) if stats is not None else 0
    max_steps = getattr(config, "max_steps", None)
    if isinstance(max_steps, int) and max_steps > 0 and step_count >= max_steps:
        return "max-steps-reached"

    return "too-long"


def _split_child_count_hint(config: "Any") -> tuple[int, int]:
    """``(child_count, per_child_budget_tokens)`` derived from *config*.

    Thin pass-through to :func:`colleague.autosplit.child_count` (imported
    lazily to avoid a load-time cycle) when *config* carries a usable
    ``autosplit_target_tokens``/``context_budget_tokens`` pair; the fixed
    fallback constants otherwise.
    """
    target = getattr(config, "autosplit_target_tokens", None)
    per_child = getattr(config, "context_budget_tokens", None)
    if isinstance(target, int) and target > 0 and isinstance(per_child, int) and per_child > 0:
        from colleague.autosplit import child_count as _child_count

        return _child_count(target, per_child), per_child
    return _DEFAULT_SPLIT_CHILD_COUNT, _DEFAULT_SPLIT_PER_CHILD_BUDGET


def build_split_record(
    task_id: str,
    slug: str,
    *,
    reason: str,
    steps: int,
    duration_seconds: float,
    child_count: int,
    request_excerpt: str = "",
    per_child_budget_tokens: int = _DEFAULT_SPLIT_PER_CHILD_BUDGET,
) -> dict[str, Any]:
    """Shape ONE 'split-next-time' record, mirroring :func:`build_lesson_record`.

    The ``text`` field embeds :func:`colleague.autosplit.build_split_recommendation`'s
    structured message (imported lazily — same cycle-avoidance reason as
    :func:`_split_child_count_hint`) so a future recall-before renders the
    SAME concrete numbers (per-child budget, child cap) a live autosplit
    reactive nudge would.

    Idempotent by construction, like :func:`build_lesson_record`: the id is
    derived from the task id, so a re-remember upserts in place.
    """
    from colleague.autosplit import build_split_recommendation

    max_children = max(1, int(child_count))
    recommendation = build_split_recommendation(
        per_child_budget_tokens=int(per_child_budget_tokens),
        max_children=max_children,
    )
    text = (
        f"A prior attempt at {slug!r} ended with reason={reason} after "
        f"{int(steps)} step(s), {float(duration_seconds):.1f}s. {recommendation}"
    )
    if request_excerpt:
        text += f" (request: {request_excerpt[:120]!r})"

    metadata: dict[str, Any] = {
        "kind": SPLIT_RECORD_KIND,
        "task_slug": slug,
        "reason": reason,
        "steps": int(steps),
        "duration_seconds": float(duration_seconds),
        "child_count_hint": max_children,
    }
    return {
        "id": f"split-next-time-{task_id}",
        "type": "work-lesson",
        "text": text,
        "metadata": metadata,
    }


def maybe_remember_split(
    repo_path: str | Path,
    task_id: str,
    slug: str,
    result: "Any",
    config: "Any",
    duration_seconds: float,
    *,
    request_excerpt: str = "",
    timeout: float = _TIMEOUT_SECONDS,
    env_overrides: dict[str, str] | None = None,
) -> bool:
    """The remember-after lane for the split-next-time record (spec c15/h10).

    Writes exactly ONE extra record — via :func:`remember`, the same eidetic
    write path :func:`build_lesson_record`'s caller uses — when
    :func:`should_record_split` is true; a strict no-op (returns ``False``,
    no subprocess) otherwise. This is the ONLY caller of
    :func:`build_split_record`/:func:`should_record_split` in the runtime —
    it fires exclusively from the after-run lane, never from mid-run step
    handling, so a run's running seat/effort is never touched.
    """
    if not should_record_split(result, config, duration_seconds):
        return False

    stats = getattr(result, "stats", None)
    steps = getattr(stats, "step_count", 0) if stats is not None else 0
    reason = _split_reason(result, config)
    child_count, per_child_budget_tokens = _split_child_count_hint(config)

    record = build_split_record(
        task_id,
        slug,
        reason=reason,
        steps=steps,
        duration_seconds=duration_seconds,
        child_count=child_count,
        request_excerpt=request_excerpt,
        per_child_budget_tokens=per_child_budget_tokens,
    )
    return remember(repo_path, record, timeout=timeout, env_overrides=env_overrides)


# ── retrieval-precision instrumentation (post-387 program, spec c9/h8/h24) ──
#
# THE PRE-DECLARED RULE (versioned, deterministic, no model judgment).
#
# The #387 dogfooding run showed recall injections near-saturating
# RECALL_BLOCK_CAP by generation 7: SELECTION, not store size, became the
# binding constraint — and nothing measured whether the RIGHT lesson surfaced.
# These three pure functions make that measurable per work item, so a rerun can
# plot a learning CURVE instead of totals.
#
# Rule ``class-key-slug-v1``, in full:
#
# 1. A work item's CLASS is its assignment text: ``task.goal`` when set, else
#    ``task.instruction`` (the same source the recall query derives from).
# 2. The class KEY is that text lowercased, split on every non-alphanumeric
#    run, the first _CLASS_KEY_TOKENS tokens joined with "-", truncated to
#    _CLASS_KEY_CAP chars.  Empty text yields "" (unscoreable — no fields).
# 3. Remember-after STAMPS that key into the lesson record's ``metadata``
#    under ``CLASS_KEY_FIELD``.
# 4. A recalled record is CLASS-RELEVANT iff its stamped key, read from
#    exactly two declared places (``record["metadata"]["class_key"]`` first,
#    then a flattened ``record["class_key"]``), is EXACTLY EQUAL to the
#    recalling task's class key.  Nothing else counts: no substring match, no
#    score threshold, no LLM judgment at record time, no post-hoc human call.
#
# Consequence, stated honestly: records predating the stamp (or written by the
# operator's own /remember) can never be class-relevant.  That is visible in
# the artifact as ``class_relevant_recalled: 0`` rather than hidden — the same
# honest-degradation stance as the rest of the memory seam.
#
# Composition note (deliberate): the score is computed over the RECALLED set,
# before any injection filtering.  A later relevance-threshold / supersedes
# pass filters what gets INJECTED and records its own exclusions; it does not
# change what these fields mean.

#: The pre-declared, versioned id of the class-relevance rule above.  It rides
#: every scored artifact so a reader can tell WHICH rule produced the numbers.
CLASS_KEY_RULE = "class-key-slug-v1"

#: The record field (inside ``metadata``, or flattened) carrying the class key.
CLASS_KEY_FIELD = "class_key"

#: How many leading tokens of the assignment text the class slug keeps.
_CLASS_KEY_TOKENS = 8

#: Hard cap on the class slug, in characters.
_CLASS_KEY_CAP = 64


def task_class_key(text: str) -> str:
    """Derive the deterministic class key for a work item's assignment text.

    Pure and total: same text in, same key out, on any machine, with no model
    turn and no store access.  Returns ``""`` for text with no alphanumeric
    content (an unscoreable work item — the caller emits no precision fields).
    """
    tokens = [tok for tok in re.split(r"[^a-z0-9]+", str(text).lower()) if tok]
    if not tokens:
        return ""
    return "-".join(tokens[:_CLASS_KEY_TOKENS])[:_CLASS_KEY_CAP]


def record_class_key(record: dict[str, Any]) -> str:
    """Read a recalled record's stamped class key from its two declared places.

    ``record["metadata"]["class_key"]`` wins; a flattened ``record["class_key"]``
    is the fallback (eidetic CLIs have shipped both shapes).  Anything else —
    missing, non-string, non-dict metadata — reads as ``""`` (not relevant).
    """
    if not isinstance(record, dict):
        return ""
    meta = record.get("metadata")
    if isinstance(meta, dict):
        value = meta.get(CLASS_KEY_FIELD)
        if isinstance(value, str):
            return value
    value = record.get(CLASS_KEY_FIELD)
    return value if isinstance(value, str) else ""


def score_recall_precision(records: list[dict[str, Any]], class_key: str) -> dict[str, Any]:
    """Score one recall against the pre-declared class-relevance rule.

    Returns the per-task precision fields destined for ``TaskResult.memory``:

    - ``class_key`` — the recalling task's key (audit: what was matched on)
    - ``precision_rule`` — :data:`CLASS_KEY_RULE` (audit: which rule)
    - ``class_relevant_recalled`` — how many recalled records matched
    - ``class_relevant_in_top_k`` — did at least one surface in the top-k
    - ``class_relevant_rank`` — 1-based rank of the FIRST match; omitted (not
      null) when there is none, mirroring the artifact's omit-when-absent style

    An empty *class_key* returns ``{}`` — an unscoreable work item adds no
    fields rather than recording a meaningless zero.
    """
    if not class_key:
        return {}
    ranks = [
        index + 1
        for index, record in enumerate(records or [])
        if record_class_key(record) == class_key
    ]
    scored: dict[str, Any] = {
        "class_key": class_key,
        "precision_rule": CLASS_KEY_RULE,
        "class_relevant_recalled": len(ranks),
        "class_relevant_in_top_k": bool(ranks),
    }
    if ranks:
        scored["class_relevant_rank"] = ranks[0]
    return scored


# ── recall thresholding + supersedes hygiene, INJECTION-ONLY (plan t6, c10/h9) ──
#
# By generation 7 of the #387 dogfooding run the injected recall block was
# near-saturating RECALL_BLOCK_CAP — at that point SELECTION, not store size,
# is the binding constraint, and the operator's stated risk is "too much
# context; the wrong lesson surfaced". This pass answers that risk
# colleague-side, over the ``score``/``signal``/``supersedes`` fields eidetic's
# ``recall`` bundle already returns per record (see eidetic's
# ``Record.to_dict()``) — no new eidetic-cli verbs (parked cross-repo, c16).
#
# COMPOSITION RULE WITH t5 (read before touching this section): t5's
# retrieval-precision fields (``class_relevant_recalled`` /
# ``class_relevant_in_top_k`` / ``class_relevant_rank``) are scored over the
# full RECALLED set, BEFORE this pass runs. This pass filters only what gets
# INJECTED into the model's context; it must never be given to
# :func:`score_recall_precision` in place of the full ``records`` list — a
# record dropped here was still recalled, and must still count there.
#
# Two independent hygiene moves, both advisory-context concerns only (they
# never touch the store):
#
# 1. Threshold — a record whose numeric ``score`` is below ``min_score``, or
#    whose numeric ``signal`` is below ``min_signal``, is excluded. A record
#    missing the field, or carrying a non-numeric value, is never excluded on
#    that axis — there is nothing to threshold, so it passes (fail open, not
#    closed, matching every other memory-seam degrade).
# 2. Supersedes — when a recalled record R declares
#    ``supersedes == S["id"]`` for another recalled record S present in the
#    SAME recalled batch, S is dropped in favor of R. A recalled batch is
#    relevance-ordered, not time-ordered, so "newer" is NOT knowable here:
#    when several records supersede the same id the LAST one in batch order
#    wins, which is arbitrary but deterministic and stated rather than
#    implied (qodo-code-review, PR #403 comment 3746507435);
#    eidetic's own supersedes/shadowing is the long-term corrective — this is
#    the colleague-side stopgap over what one recall call already returned).
#
# Every exclusion is returned, never silently dropped (h9); the caller
# (``loop.py``'s ``_maybe_recall_memory``) rides it onto ``TaskResult.memory``
# as ``recall_excluded`` — omitted when nothing was excluded, so a run that
# excludes nothing serializes byte-identically to before this task.

#: Master switch for the whole hygiene pass (threshold + supersedes). Default
#: ON; a falsy value ("0"/"false"/"no"/"off", case-insensitive) restores
#: pre-t6 injection behavior byte-for-byte — every recalled record is kept,
#: nothing is ever excluded — regardless of the threshold env vars below.
RECALL_HYGIENE_ENV = "COLLEAGUE_RECALL_HYGIENE"

#: Optional numeric floor on a recalled record's ``score`` field. Unset (the
#: default) means this axis never excludes anything, so hygiene being ON
#: alone changes nothing until an operator opts into an actual bound.
RECALL_MIN_SCORE_ENV = "COLLEAGUE_RECALL_MIN_SCORE"

#: Optional numeric floor on a recalled record's ``signal`` (freshness)
#: field. Same unset-by-default stance as ``RECALL_MIN_SCORE_ENV``.
RECALL_MIN_SIGNAL_ENV = "COLLEAGUE_RECALL_MIN_SIGNAL"

_FALSY_ENV_VALUES = {"0", "false", "no", "off"}


def _env_source(env: dict[str, str] | None) -> Any:
    return env if env is not None else os.environ


def recall_hygiene_enabled(env: dict[str, str] | None = None) -> bool:
    """Resolve the master hygiene switch: default ON, opt out via env.

    *env* is an injectable mapping for tests; ``None`` (the default) reads
    the real process environment, mirroring the rest of this module's env
    knobs.
    """
    raw = _env_source(env).get(RECALL_HYGIENE_ENV)
    if raw is None:
        return True
    return raw.strip().lower() not in _FALSY_ENV_VALUES


def _resolve_env_float(name: str, env: dict[str, str] | None) -> float | None:
    """Read *name* from *env* as a float; unset/blank/unparseable ⇒ ``None``
    (that axis never excludes anything — an operator typo degrades to
    no-op, never a crash)."""
    raw = _env_source(env).get(name)
    if raw is None or not str(raw).strip():
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def recall_min_score(env: dict[str, str] | None = None) -> float | None:
    """Resolve :data:`RECALL_MIN_SCORE_ENV`, or ``None`` when unset."""
    return _resolve_env_float(RECALL_MIN_SCORE_ENV, env)


def recall_min_signal(env: dict[str, str] | None = None) -> float | None:
    """Resolve :data:`RECALL_MIN_SIGNAL_ENV`, or ``None`` when unset."""
    return _resolve_env_float(RECALL_MIN_SIGNAL_ENV, env)


def _record_ref(record: dict[str, Any], index: int) -> Any:
    """A record's traceable reference for an exclusion entry: its id when it
    has one, else its position in the recalled batch."""
    if isinstance(record, dict):
        rid = record.get("id")
        if isinstance(rid, str) and rid:
            return rid
    return f"#{index}"


def _numeric_field(record: dict[str, Any], field: str) -> float | None:
    if not isinstance(record, dict):
        return None
    value = record.get(field)
    if isinstance(value, bool):  # bool is an int subclass — never a score/signal
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _threshold_exclusion(
    record: dict[str, Any],
    index: int,
    min_score: float | None,
    min_signal: float | None,
) -> dict[str, Any] | None:
    """Return this record's exclusion entry, or ``None`` when it survives.

    A record is only ever excluded by a floor that is BOTH configured and
    numerically comparable — a missing or non-numeric field fails open, so
    hygiene never silently drops a record it cannot judge.
    """
    for field, floor, reason in (
        ("score", min_score, "below-min-score"),
        ("signal", min_signal, "below-min-signal"),
    ):
        if floor is None:
            continue
        value = _numeric_field(record, field)
        if value is not None and value < floor:
            return {"id": _record_ref(record, index), "reason": reason}
    return None


def _supersedes_map(surviving: list[tuple[int, dict[str, Any]]]) -> dict[str, str]:
    """Map ``superseded id -> superseding id`` WITHIN this recalled batch.

    Only ids actually present in the batch are ever dropped — a supersedes
    pointer to a record outside this recalled set is not actionable here (it
    may not even be relevant), so it is left alone.
    """
    present_ids = {
        record.get("id")
        for _, record in surviving
        if isinstance(record, dict) and isinstance(record.get("id"), str)
    }
    mapping: dict[str, str] = {}
    for _, record in surviving:
        if not isinstance(record, dict):
            continue
        supersedes = record.get("supersedes")
        rid = record.get("id")
        # A superseder with no usable id cannot be named in the exclusion
        # reason, and "superseded-by:?" is not traceable — so such an edge
        # drops nothing at all rather than removing a record the operator
        # could never account for.
        if not (isinstance(rid, str) and rid):
            continue
        if (
            isinstance(supersedes, str)
            and supersedes
            and supersedes in present_ids
            and supersedes != rid
        ):
            # Plain assignment, not setdefault: LAST in batch order wins, per
            # the documented rule above.
            mapping[supersedes] = rid
    return mapping


def _resolve_supersedes_chain(mapping: dict[str, str]) -> dict[str, str]:
    """Collapse each superseded id to its FINAL surviving superseder.

    Two problems the raw one-step mapping has (qodo-code-review, PR #402
    comment 3746408309):

    * **Chains.** With A superseded by B and B superseded by C, the raw map
      reports A as ``superseded-by:B`` — but B is itself excluded, so the
      reason points a debugger at a record that is not in the injected block.
      Walk to the terminal superseder and name that instead.
    * **Cycles.** A supersedes B and B supersedes A has NO terminal
      superseder; applying the raw map would exclude every record in the
      cycle and could silently empty the recall block. A cycle is therefore
      left UNRESOLVED — nothing in it is dropped. Dropping an arbitrary
      member would be a coin toss, and dropping all of them loses data the
      operator asked to recall.
    """
    resolved: dict[str, str] = {}
    for start, first in mapping.items():
        seen = {start}
        current: str | None = first
        while current in mapping:
            if current in seen:  # cycle — no terminal superseder exists
                current = None
                break
            seen.add(current)
            current = mapping[current]
        if current is not None:
            resolved[start] = current
    return resolved


def filter_recall_records(
    records: list[dict[str, Any]],
    *,
    min_score: float | None = None,
    min_signal: float | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Filter recalled records for INJECTION only — threshold, then supersedes.

    Pure — no subprocess, no store access, no env reads (see
    :func:`filter_for_injection` for the env-driven wrapper). Returns
    ``(kept, excluded)``:

    - ``kept`` preserves the input order of every record that survives both
      passes.
    - ``excluded`` is a list of ``{"id", "reason"}`` — ``id`` is the record's
      own id when present, else ``"#<index>"`` in the input batch;
      ``reason`` is one of ``"below-min-score"``, ``"below-min-signal"``, or
      ``"superseded-by:<id>"``.

    See the module comment above for the full rule and the composition note
    with :func:`score_recall_precision` (this function must never feed a
    filtered subset back into precision scoring).
    """
    records = list(records or [])
    excluded: list[dict[str, Any]] = []
    surviving_threshold: list[tuple[int, dict[str, Any]]] = []

    for index, record in enumerate(records):
        exclusion = _threshold_exclusion(record, index, min_score, min_signal)
        if exclusion is not None:
            excluded.append(exclusion)
        else:
            surviving_threshold.append((index, record))

    superseded_ids = _resolve_supersedes_chain(_supersedes_map(surviving_threshold))

    kept: list[dict[str, Any]] = []
    for _, record in surviving_threshold:
        rid = record.get("id") if isinstance(record, dict) else None
        if isinstance(rid, str) and rid in superseded_ids:
            excluded.append({"id": rid, "reason": f"superseded-by:{superseded_ids[rid]}"})
            continue
        kept.append(record)

    return kept, excluded


def filter_role_scoped(
    records: list[dict[str, Any]],
    role: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Keep only the lessons *role* is entitled to see (plan task t17, c39/h31).

    A lesson is injected when ANY of these holds:

    * its ``metadata.component`` equals *role* — the lesson is about this seat;
    * its ``metadata.cross_role`` is true — an EXPLICIT opt-in to every seat;
    * it carries no ``component`` at all — legacy/unscoped records are never
      silently dropped (a pre-t17 store must keep working).

    Everything else is excluded with reason ``not-scoped-to:<role>``, so the
    exclusion stays traceable on ``TaskResult.memory`` rather than silent.
    """
    kept: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for record in records or []:
        metadata = record.get("metadata")
        component = metadata.get("component") if isinstance(metadata, dict) else None
        cross_role = bool(metadata.get("cross_role")) if isinstance(metadata, dict) else False
        if not component or cross_role or component == role:
            kept.append(record)
        else:
            excluded.append({"id": record.get("id", ""), "reason": f"not-scoped-to:{role}"})
    return kept, excluded


def filter_for_injection(
    records: list[dict[str, Any]],
    *,
    role: str | None = None,
    env: dict[str, str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Env-driven wrapper around :func:`filter_recall_records` (t6 entry point).

    With the master switch off (:func:`recall_hygiene_enabled` false), this
    is a strict identity: ``(list(records), [])`` — every recalled record is
    kept and nothing is ever excluded, byte-identical to injection behavior
    before this task, regardless of the threshold env vars.

    *role* (plan task t17) additionally narrows the kept set to the lessons
    that seat is entitled to see — see :func:`filter_role_scoped`. It is
    deliberately NOT gated on the hygiene master switch: role scoping is a
    correctness property of the thought-action-evaluation mode (a lesson about
    the evaluator must never be injected into the worker), not a tuning knob.
    ``role=None`` — every pre-t17 caller — leaves behaviour byte-identical.
    """
    if role is None:
        if not recall_hygiene_enabled(env):
            return list(records or []), []
        return filter_recall_records(
            records,
            min_score=recall_min_score(env),
            min_signal=recall_min_signal(env),
        )
    if not recall_hygiene_enabled(env):
        kept, excluded = list(records or []), []
    else:
        kept, excluded = filter_recall_records(
            records,
            min_score=recall_min_score(env),
            min_signal=recall_min_signal(env),
        )
    kept, role_excluded = filter_role_scoped(kept, role)
    return kept, excluded + role_excluded


# ── code-lesson record type (plan t8, spec c4/h4) ──────────────────────────


class Confidence(enum.Enum):
    """Bounded confidence levels for code-lesson records.

    Honest default is low — a single observation is not proof.
    Values are floats in [0.0, 1.0] for JSON serialization.
    """

    low = 0.1
    medium = 0.5
    high = 0.9


def build_code_lesson_record(
    area: str,
    convention: str,
    evidence: str,
    *,
    confidence: Confidence | float = Confidence.low,
) -> dict[str, Any]:
    """Shape one code-lesson record (id/type/area/convention/evidence/confidence).

    Pure function — no subprocess, no store access. A store-less repo remains
    a zero-subprocess no-op (the triple gate is untouched).

    The id is derived from the content (area + convention + evidence) so
    identical lessons upsert in place, and the ``code-lesson-`` prefix
    guarantees no collision with ``work-lesson-<task_id>`` ids.

    Evidence is verbatim substance: a lint-fix line, a failing-test name,
    a diff hunk — not a summary or interpretation.

    Confidence defaults to ``Confidence.low`` (honest default: one
    observation is not proof).
    """
    # Resolve confidence to a float value.
    if isinstance(confidence, Confidence):
        confidence_value: float = confidence.value
    else:
        confidence_value = float(confidence)

    # Deterministic id from content — idempotent upsert, no collision with
    # work-lesson-<task_id> (different prefix).
    content = f"{area}\x00{convention}\x00{evidence}"
    digest = hashlib.sha256(content.encode()).hexdigest()[:12]
    record_id = f"code-lesson-{digest}"

    # The eidetic CLI rejects any record missing id/text/type (#392) — the
    # searchable body composes the three lesson facts. The record JSON rides
    # the eidetic argv, so the text is bounded like every other argv-borne
    # free text (the evidence field keeps the verbatim substance; the id
    # digest above is computed from the UNbounded content, so identical
    # lessons still upsert in place).
    text = _bound_cli_text(f"Code lesson ({area}): {convention}\nEvidence: {evidence}")

    return {
        "id": record_id,
        "type": "code-lesson",
        "text": text,
        "area": area,
        "convention": convention,
        "evidence": evidence,
        "confidence": confidence_value,
    }
