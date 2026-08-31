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

import json
import os
import shutil
import subprocess  # nosec B404 - launching operator CLI is the point (trusted env, D2)
from pathlib import Path
from typing import Any

from colleague.identity import identity_env, resolve_identity
from colleague.memory_lessons import (
    CLASS_KEY_FIELD,
    CLASS_KEY_RULE,
    Confidence,
    _bound_cli_text,
    _numeric_field,
    _record_ref,
    _resolve_supersedes_chain,
    _supersedes_map,
    _threshold_exclusion,
    build_code_lesson_record,
    filter_for_injection,
    filter_recall_records,
    filter_role_scoped,
    recall_hygiene_enabled,
    recall_min_score,
    recall_min_signal,
    record_class_key,
    score_recall_precision,
    task_class_key,
)

__all__ = [
    "CLASS_KEY_FIELD",
    "CLASS_KEY_RULE",
    "Confidence",
    "_bound_cli_text",
    "_numeric_field",
    "_record_ref",
    "_resolve_supersedes_chain",
    "_supersedes_map",
    "_threshold_exclusion",
    "build_code_lesson_record",
    "filter_for_injection",
    "filter_recall_records",
    "filter_role_scoped",
    "record_class_key",
    "recall_hygiene_enabled",
    "recall_min_score",
    "recall_min_signal",
    "score_recall_precision",
    "task_class_key",
]

#: The curated allow-list of eidetic verbs the engine may invoke.
#: Only ``recall`` and ``remember`` are reachable. The one-per-process
#: ``eidetic --version`` capability probe (:func:`_rerank_supported`) is NOT a
#: verb and sits deliberately outside this list: a fixed-argv, read-only
#: metadata query with a PATH-only environment — it can neither read nor
#: write the store (Qodo #478-2).
ALLOWED_VERBS: frozenset[str] = frozenset({"recall", "remember"})

#: Bound a runaway CLI so it cannot stall the loop indefinitely.
_TIMEOUT_SECONDS = 300

# ── eidetic --rerank opt-in behind a version probe (#467, eidetic-cli#39) ────
#
# eidetic-cli 0.14.0 adds an opt-in ``--rerank`` stage to ``eidetic recall``.
# An older CLI REJECTS the unknown flag, and a wrong argv would make recall
# return [] silently — the #387-class recalled=0 failure (see the envelope
# comment inside :func:`recall`). So the flag is passed only after ONE
# ``eidetic --version`` probe per process proves the CLI is new enough; ANY
# probe failure (timeout, OSError, non-zero exit, unparseable output) means
# the flag is WITHHELD and the recall argv stays byte-identical to the
# pre-rerank surface (dark launch on a 0.13 rig).

#: Minimum eidetic-cli version whose ``recall`` accepts ``--rerank``.
_RERANK_MIN_VERSION: tuple[int, int] = (0, 14)

#: Bound on the one-per-process ``eidetic --version`` probe.
_VERSION_PROBE_TIMEOUT_SECONDS = 10

#: Per-process probe cache, keyed by the resolved CLI path (recall runs on
#: the main thread — no lock needed). Never cleared at runtime; a process
#: probes each CLI path at most once.
_RERANK_PROBE_CACHE: dict[str, bool] = {}


def _parse_version_tokens(banner: str) -> tuple[int, int] | None:
    """``(major, minor)`` from the first whitespace token shaped ``X.Y.Z``.

    Linear-time by construction (split + isdigit; no regex, no backtracking —
    Sonar S8786): each token must split on ``.`` into at least three parts
    whose first three are all plain digits.
    """
    for token in banner.split():
        parts = token.split(".")
        if len(parts) >= 3 and all(p.isdigit() for p in parts[:3]):
            return (int(parts[0]), int(parts[1]))
    return None


def _rerank_supported(cli_path: str, *, cwd: str | Path | None = None) -> bool:
    """True iff ONE cached ``eidetic --version`` probe parses >= 0.14.0.

    The probe result is cached per process in :data:`_RERANK_PROBE_CACHE`.
    Any failure — timeout, OSError, non-zero exit, or output with no
    parseable ``X.Y.Z`` — caches ``False``: the flag is withheld, never
    retried, so a flag-rejecting older CLI can never yield recalled=0.
    """
    cached = _RERANK_PROBE_CACHE.get(cli_path)
    if cached is not None:
        return cached

    supported = False
    try:
        proc = subprocess.run(  # nosec B603 # NOSONAR - fixed argv, operator CLI
            [cli_path, "--version"],
            capture_output=True,
            text=True,
            errors="replace",  # never let a non-UTF-8 byte crash the probe
            timeout=_VERSION_PROBE_TIMEOUT_SECONDS,
            cwd=str(cwd) if cwd is not None else None,
            # A version banner needs no operator environment: pass ONLY PATH
            # (resolution) — unlike recall/remember, no identity/embedder env,
            # no inherited secrets (Qodo #478-1).
            env={"PATH": os.environ.get("PATH", "")},
        )
    except (subprocess.TimeoutExpired, OSError, ValueError):
        proc = None
    if proc is not None and proc.returncode == 0:
        # "eidetic-cli X.Y.Z" — tolerate surrounding text, require X.Y.Z.
        # Token parse, no regex: Sonar S8786 flagged the previous \d+\.\d+\.\d+
        # search as super-linear under backtracking on adversarial banners.
        version = _parse_version_tokens(proc.stdout or "")
        if version is not None:
            supported = version >= _RERANK_MIN_VERSION

    _RERANK_PROBE_CACHE[cli_path] = supported
    return supported


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

    ``--rerank`` (#467) is appended iff :func:`_rerank_supported` proved the
    CLI is >= 0.14.0 — withheld on any doubt, keeping the argv byte-identical
    to the pre-rerank surface on an older rig (dark launch).
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
    if _rerank_supported(cli_path, cwd=root_path):
        # Opt-in rerank stage (#467): only a CLI proven >= 0.14.0 sees the
        # flag; otherwise the argv is byte-identical to the pre-rerank one.
        argv.append("--rerank")

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
