"""The memory lane: recall-before and remember-after (with the rung-2 distiller).

Extracted from ``colleague/loop.py`` (plan hard-1000-line-file-limit, t15).
The split-next-time record stays where it was — in ``colleague/memory.py``'s
after-run lane, never reachable from the loop's step handling. A pure move.
"""

from __future__ import annotations

from contextlib import suppress
from pathlib import Path
from typing import Any, Callable

from colleague import effortrecord as _effortrecord
from colleague import lessons as _lessonsmod
from colleague import memory as _memorymod
from colleague.contract import TaskResult
from colleague.loop_constants import _MEMORY_TIMEOUT
from colleague.loop_types import _Work


def _memory_armed(ctx: _Work) -> bool:
    """Memory fires only when enabled AND the repo opted in by carrying a store.

    The store check is what keeps the default-ON flag safe: a tmp test repo (or
    any repo without ``.eidetic/``) never spawns the CLI — a strict no-op. CLI
    absence is handled inside :mod:`colleague.memory` (t1's contract).
    """
    if not ctx.memory_enabled:
        return False
    return (Path(_memory_repo(ctx)) / ".eidetic").is_dir()


def _memory_repo(ctx: _Work) -> str:
    """The durable store root: the operator repo for isolated runs (t2 fix).

    An isolated run's ``task.repo_path`` is a throwaway worktree that is reaped
    after handoff — a lesson written there would be silently lost (caught live
    on the first mock smoke run). ``execute_work`` threads the real root via
    ``config.memory_root``; the in-place session path falls back to the task's
    own repo.
    """
    return ctx.memory_root or ctx.task.repo_path


def _memory_class_source(ctx: _Work) -> str:
    """The ONE assignment text both memory seams key off (goal, else instruction).

    Recall-before uses it as the query; remember-after stamps its class key
    (``memory.task_class_key``) onto the lesson record. Sharing this single
    expression is what makes the retrieval-precision rule closed: run N's stamp
    is derived from exactly the string run N+1 matches against.
    """
    return (ctx.task.goal or ctx.task.instruction or "").strip()[:200]


def _maybe_recall_memory(ctx: _Work) -> None:
    """Recall-before (spec R1 / plan t2): prior lessons as ONE advisory message.

    The query derives from the task's goal (when set) or the instruction head;
    the injected block is char-capped (``memory.RECALL_BLOCK_CAP`` — h7's
    token-cap without a tokenizer) and the whole exchange is recorded on
    ``TaskResult.memory`` so a misleading recall is diagnosable from the
    artifact (h7). Best-effort: any failure leaves the run untouched.

    Retrieval-precision instrumentation (post-#387, spec c9/h8/h24): the
    recalled set is additionally scored against the PRE-DECLARED, deterministic
    class-relevance rule documented in :mod:`colleague.memory`
    (``CLASS_KEY_RULE``) — never a model judgment at record time — so an
    artifact answers "did the class-relevant lesson surface in top-k?" per
    work item, which is what makes a learning CURVE measurable.

    Recall thresholding + supersedes hygiene (plan t6, spec c10/h9):
    before injection, :func:`colleague.memory.filter_for_injection` drops a
    below-threshold record (by eidetic's returned ``score``/``signal``
    fields) and a superseded sibling record (per its returned ``supersedes``
    field), env-gated and env-configured entirely inside
    :mod:`colleague.memory`. THE COMPOSITION RULE: this filters only what
    gets INJECTED — the precision score above is computed over the full
    ``records`` set, unfiltered, so a record excluded here still counts
    toward ``class_relevant_recalled``/``class_relevant_rank``. Every
    exclusion is recorded on ``TaskResult.memory`` as ``recall_excluded``
    (omitted when nothing was excluded) — traceable, never silent.
    """
    if not _memory_armed(ctx):
        return
    query = _memory_class_source(ctx)
    try:
        records = _memorymod.recall(
            _memory_repo(ctx),
            query,
            top_k=5,
            timeout=_MEMORY_TIMEOUT,
            env_overrides=ctx.embed_env,
        )
    except Exception:  # noqa: BLE001
        # Advisory context only, never a precondition — a recall failure must
        # not block the run.
        return
    kept, excluded = _memorymod.filter_for_injection(records)
    block = _memorymod.build_recall_block(kept) if kept else ""
    if block:
        ctx.messages.append({"role": "user", "content": block})
    ctx.result.memory = {
        "query": query,
        "recalled": len(records),
        "injected_chars": len(block),
        # Scored over the RECALLED set (pre-injection, pre-hygiene-filtering)
        # so the t6 relevance threshold/supersedes pass records its own
        # exclusions without changing what these fields mean. Empty class key
        # ⇒ no fields (unscoreable, never a meaningless zero).
        **_memorymod.score_recall_precision(records, _memorymod.task_class_key(query)),
    }
    if excluded:
        ctx.result.memory["recall_excluded"] = excluded


def _resolve_distill_fn(ctx: _Work) -> Callable[..., Any] | None:
    """The effective distillation seam: injected fn, else author-built child fn.

    Production wiring (t16): when from_config resolved an author and no
    explicit fn was injected, the detaching fn is built HERE so the child
    targets the durable memory repo. Lazy import (distill.py pulls
    background/memory, must not load for memory-less runs). ``None`` = rung-1.
    """
    if ctx.distill_fn is not None:
        return ctx.distill_fn
    if ctx.distill_author is None or not ctx.memory_distill:
        return None
    with suppress(Exception):
        from colleague import distill as _distillmod

        author = ctx.distill_author
        return _distillmod.make_distill_fn(
            _memory_repo(ctx),
            getattr(author, "model", None),
            getattr(author, "base_url", ""),
            getattr(author, "api_key", ""),
            getattr(author, "effort", None),
        )
    return None


def _distill_pass(
    ctx: _Work,
    result: TaskResult,
    request_head: str,
    text: str,
    metadata: dict[str, Any],
) -> tuple[str, dict[str, int] | None]:
    """Run the rung-2 distillation attempt; return (text, counters).

    Mutates *metadata* with the honest outcome state: ``validated`` (lesson
    folded, origin=model), ``detached`` (the background child owns the outcome
    — never conflated with a sync refusal, the t16 composition seam), or
    ``no-lesson-extracted``. No seam / knob off returns *text* unchanged with
    ``None`` counters — the rung-1 floor.
    """
    distill_fn = _resolve_distill_fn(ctx)
    if distill_fn is None or not ctx.memory_distill:
        return text, None
    # t5 (h6): the distill seat is BUILT the moment the pass launches — record
    # its already-resolved rung (DistillAuthor.effort, never recomputed) on the
    # artifact effort block; an injected fn without an author records nothing.
    if ctx.distill_author is not None:
        _effortrecord.record(result, "distill", getattr(ctx.distill_author, "effort", None))
    counts = {"attempts": 1, "validated": 0}
    raw: Any = None
    with suppress(Exception):
        raw = distill_fn(result, request_head)
    if raw is None and getattr(distill_fn, "detached", False):
        metadata["distill"] = "detached"
        return text, counts
    lesson = _lessonsmod.parse_lesson_json(raw)
    verdict = _lessonsmod.validate_lesson(lesson if lesson is not None else raw)
    if lesson is not None and verdict.allowed:
        counts["validated"] = 1
        text += (
            f" Lesson (origin=model): pattern: {lesson['pattern']} — "
            f"constant: {lesson['constant']} — reason: {lesson['reason']}."
        )
        metadata["distill"] = "validated"
        metadata["lesson_origin"] = "model"
    else:
        metadata["distill"] = "no-lesson-extracted"
    return text, counts


def _maybe_remember_lesson(ctx: _Work) -> None:
    """Remember-after (spec R1 / plan t2): one deterministic lesson per work item.

    Composed from the finished result's own facts (status, steps, tool counts,
    honesty markers) — no extra model turn. Idempotent: the record id derives
    from the task id, so a re-run upserts. An INCOMPLETE run is recorded too —
    failures are the most valuable lessons. Best-effort: a store failure never
    masks the work item result; the outcome lands on ``TaskResult.memory``.
    """
    if not _memory_armed(ctx):
        return
    result = ctx.result
    instruction = (ctx.task.instruction or "").strip()
    request_head = instruction.splitlines()[0][:120] if instruction else ""
    # Lesson-grade composition (#379 rung 1) lives in colleague/memory.py —
    # the failure substance (incompletion, error, refresh warnings) rides
    # the record deterministically.
    text = _memorymod.compose_lesson_text(result, request_head)
    metadata: dict[str, Any] = {"topic": "colleague-work-lesson", "status": result.status}
    # Stamp the class key (post-#387, spec c9/h8) so a LATER run recalling this
    # record can score, deterministically and without judgment, whether the
    # class-relevant lesson surfaced in its top-k. Derived from the same single
    # assignment-text expression the recall query uses.
    class_key = _memorymod.task_class_key(_memory_class_source(ctx))
    if class_key:
        metadata[_memorymod.CLASS_KEY_FIELD] = class_key
    # Rung 2 (t9): ONE gated distillation attempt through the injectable seam.
    # The lesson rides the record ONLY when it schema-validates (anti-fabrication,
    # spec c9/h9); anything else leaves the rung-1 record standing with the
    # honest no-lesson-extracted marker. No seam / knob off = rung-1 floor,
    # byte-identical (spec c16/h13, c29/h24) — counters appear only when armed.
    text, distill_counts = _distill_pass(ctx, result, request_head, text, metadata)
    record = _memorymod.build_lesson_record(result.task_id, text, metadata)
    recorded = False
    with suppress(Exception):
        recorded = _memorymod.remember(
            _memory_repo(ctx),
            record,
            timeout=_MEMORY_TIMEOUT,
            env_overrides=ctx.embed_env,
        )
    if result.memory is None:
        result.memory = {}
    result.memory["lesson_recorded"] = bool(recorded)
    # Split-next-time record (#416 c15/h10): the too-hard/too-long signals are
    # judged ONLY here, after the run ended; memory.py owns the predicate + record.
    with suppress(Exception):
        from types import SimpleNamespace as _SimpleNamespace

        from colleague.slug import slugify as _slugify

        _split_recorded = bool(
            _memorymod.maybe_remember_split(
                _memory_repo(ctx),
                result.task_id,
                _slugify(request_head or instruction[:80]),
                result,
                _SimpleNamespace(max_steps=ctx.max_steps, too_long_min=ctx.too_long_min),
                float(getattr(result.stats, "duration_seconds", 0.0) or 0.0),
                request_excerpt=request_head,
                timeout=_MEMORY_TIMEOUT,
                env_overrides=ctx.embed_env,
            )
        )
        if _split_recorded:
            # Key present ONLY when a record was written — the unarmed/ordinary
            # ``result.memory`` key set stays byte-identical (pinned in tests).
            result.memory["split_recorded"] = True
    if distill_counts is not None:
        # The armed-is-not-alive counter (spec c28/h23): a seam that never
        # validates is visible as attempts>0, validated=0 on every artifact.
        result.memory["distill_attempts"] = distill_counts["attempts"]
        result.memory["distill_validated"] = distill_counts["validated"]
