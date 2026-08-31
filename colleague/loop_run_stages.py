"""The two straight-line stages :func:`colleague.loop.run` hands off.

Extracted from ``colleague/loop.py`` (plan hard-1000-line-file-limit, t15) so
the run entry point fits the 1000-line ceiling: a sequence of strict-no-op
advisory injections fired before the turn loop, and the partial-preserving
aborted exit fired after it. Both are verbatim moves — the call order, the
comments explaining each no-op, and the ``WorkAborted`` raise are unchanged.
"""

from __future__ import annotations

from contextlib import suppress
from typing import Callable

from colleague import escalation as _escalation
from colleague import salvage
from colleague.loop_context import _maybe_offer_plan_mode
from colleague.loop_memory import _maybe_recall_memory, _maybe_remember_lesson
from colleague.loop_outcomes import _finalize_finish_states, _maybe_flag_incompletion
from colleague.loop_senses import (
    _maybe_inject_context_packet,
    _maybe_inject_self_knowledge,
    _maybe_inject_upfront_hint,
    _maybe_run_media_bridge,
    _maybe_warn_too_big,
)
from colleague.loop_synthesis import _resolve_terminal_summary
from colleague.loop_tae import _tae_finalize
from colleague.loop_transport import _agents_end
from colleague.loop_types import _Work
from colleague.loop_wire import WorkAborted


def run_upfront_injections(ctx: _Work) -> None:
    """Fire every pre-loop advisory injection, in order. Each is a strict no-op
    unless its own feature is armed, so an unarmed run is byte-identical."""
    # Up-front advisory split hint (#151) — extracted to keep run()'s cognitive
    # complexity within budget; a strict no-op unless armed and the task looks big.
    _maybe_inject_upfront_hint(ctx)

    # Up-front plan-mode advisory (#t8) — injects ONE recommendation to enter plan
    # mode for a complex task; a strict no-op unless armed (plan_offer_tokens > 0).
    _maybe_offer_plan_mode(ctx)

    # Up-front "too big for one repo" caller warning (#156) — sets
    # result.capacity_warning when even a split can't hold the job; a strict no-op
    # for a normal-sized assignment.
    _maybe_warn_too_big(ctx)

    # Recall-before (spec R1 / plan t2): inject prior lessons from the repo's
    # eidetic store as ONE advisory context message; a strict no-op unless armed.
    _maybe_recall_memory(ctx)

    # Cortex/senses packet (t6): when the task carries a senses ContextPacket,
    # inject the senses interpretation as ONE advisory companion message (cortex's
    # first message is already the operator's verbatim original) and record the
    # packet on TaskResult.senses; a strict no-op with no packet.
    _maybe_inject_context_packet(ctx)

    # Cortex-side self-knowledge (t9 / #306): when the operator's instruction is a
    # self-knowledge question (classify_selfknowledge), inject ONE advisory message
    # with the LIVE guide index + resolved self-facts so cortex answers about
    # colleague from its own docs, not a guess; a strict no-op for an ordinary turn
    # (the guide docs load ONLY on a self-knowledge turn).
    _maybe_inject_self_knowledge(ctx)

    # Media-comprehension bridge (t8, c24): with a text-only main + attached
    # media + an operator-declared multimodal second model, ONE tools-off
    # escalation describes the media and folds the answer back; strict no-op
    # otherwise. A declared multimodal senses config is preferred (t6).
    _maybe_run_media_bridge(ctx)


def finish_aborted(
    ctx: _Work, outcome: str, aborted: Exception, model: str | None, last_sub: str
) -> None:
    """The aborted exit: finalize the partial and raise :class:`WorkAborted`.

    Never returns — it always raises, carrying the populated partial result out
    to the work path (#37)."""
    result = ctx.result
    task = ctx.task
    # Carry the populated partial result out via WorkAborted; the work path
    # writes it (non-empty steps/usage/changed_files + trace) then re-surfaces
    # the failure to the operator (#37).
    # Prefer the model's last substantive content over the generic aborted
    # note so the escalation continuation (below) carries the real output
    # rather than an empty/placeholder summary (Qodo #114).
    result.summary = (
        result.summary or last_sub or (f"aborted after {len(result.steps)} step(s): {result.error}")
    )
    # Per-seat finish state (t1, c4/h4/c30) — ALWAYS-on, even the aborted
    # path, so a crashed/timed-out partial artifact still carries an
    # honest finish state (mirrors the stats finalization discipline).
    _finalize_finish_states(ctx, outcome, aborted=aborted)
    # Thought->action->evaluation episode boundary (t13) — on the aborted
    # path too, so a crashed episode still carries its honest ledger.
    _tae_finalize(ctx, outcome)
    # Escalation seam — aborted path (#106 t3): best-effort, observe-only.
    # A timeout / context-overflow / engine error is a limit worth escalating.
    # Wrapped in suppress so any escalation failure never masks the work item result.
    with suppress(Exception):
        _escalation.escalate(result, result.stats, task.repo_path, model=model)
    _agents_end(ctx)
    salvage.unregister(task.id)
    raise WorkAborted(result) from aborted


def finish_clean(
    ctx: _Work, outcome: str, complete: "Callable[..., object]", model: str | None, last_sub: str
) -> None:
    """The clean (non-aborted) exit tail, in order. Verbatim from :func:`run`."""
    result = ctx.result
    task = ctx.task

    # Summary precedence (t2 #109 + #191 + auto-compact-on-finish t3 + Qodo PR #198) —
    # RESOLVED BEFORE the not-finished escalation below so build_continuation() sees
    # the finalized summary, not an empty placeholder (Qodo #114). The ordered
    # precedence (finish summary > fresh forced synthesis > compaction self-summary
    # fallback > last-substantive > NO_RESULT_PRODUCED sentinel) lives in
    # _resolve_terminal_summary — extracted so run() stays under the S3776 threshold
    # and so synthesis runs BEFORE the compaction fallback (the stale-summary fix).
    _resolve_terminal_summary(ctx, outcome, complete, last_sub)

    # Per-seat finish state (t1, c4/h4/c30) — ALWAYS-on; runs AFTER summary
    # resolution so a NO_RESULT_PRODUCED sentinel assigned by the fallback
    # chain above is visible to the classifier.
    _finalize_finish_states(ctx, outcome)

    # Honest-incompletion (colleague#313): flag a run that produced no expected
    # deliverable — after summary resolution so it composes with finish_recovered.
    _maybe_flag_incompletion(ctx, outcome)

    # Thought->action->evaluation episode boundary (t13): ``episode_completion``
    # for a finished episode, ``declared_infeasible`` for one that ended with no
    # deliverable — then the append-only ledger folds onto the artifact. Runs
    # after summary resolution so the judged outcome is the real one; advisory,
    # never flips status. A strict no-op when unarmed.
    _tae_finalize(ctx, outcome)

    # Remember-after (spec R1 / plan t2): record this work item's lesson to the
    # repo's memory store; a strict no-op unless armed, best-effort always.
    _maybe_remember_lesson(ctx)

    # Escalation seam — not-finished path (#106 t3): step budget exhausted without
    # calling finish.  Runs AFTER summary resolution (above) so the continuation
    # record carries the real output.  Best-effort and observe-only; suppress so
    # it cannot mask the work item result.
    if result.not_finished:
        with suppress(Exception):
            _escalation.escalate(result, result.stats, task.repo_path, model=model)
    _agents_end(ctx)
    salvage.unregister(task.id)
