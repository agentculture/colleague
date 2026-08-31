"""memory_lessons — retrieval-precision instrumentation + code-lesson records.

Split out of :mod:`colleague.memory` (hard-1000-line-file-limit, t8): the
CLI-text bounding helper, the class-key/precision-scoring instrumentation,
the recall-hygiene filtering pipeline, and the code-lesson record builder +
its ``Confidence`` enum live here. :mod:`colleague.memory` re-exports every
name so existing importers and monkeypatch targets resolve unchanged.
"""

from __future__ import annotations

import enum
import hashlib
import os
import re
from typing import Any

#: Cap on free text riding the eidetic argv (defense-in-depth: argv is
#: shell-free by construction, but model/operator text is still bounded and
#: stripped of control characters before it reaches an OS command).
_CLI_TEXT_CAP = 2000


def _bound_cli_text(text: str, cap: int = _CLI_TEXT_CAP) -> str:
    """Bound + de-control free text before it rides the eidetic argv."""
    cleaned = "".join(ch for ch in str(text) if ch >= " " or ch in "\n\t")
    return cleaned[:cap]


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
