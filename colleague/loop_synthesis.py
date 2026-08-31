"""Finish recovery and forced synthesis — the summary precedence chain.

Extracted from ``colleague/loop.py`` (plan hard-1000-line-file-limit, t15).
A pure move (#191/#248/#231).
"""

from __future__ import annotations

from colleague.contract import NO_RESULT_PRODUCED
from colleague.loop_accounting import _account_turn
from colleague.loop_constants import (
    _EMPTY_FINISH_PROMPT,
    _EXIT_BUDGET,
    _EXIT_FINISHED,
    _EXIT_STOPPED,
    _MARKUP_SALVAGE_CHARS,
    _MARKUP_SYNTHESIS_PROMPT,
    _META_FINISH_CHARS,
    _META_FINISH_PROMPT,
    _META_FINISH_RE,
    _PHASE_SYNTHESIZING,
    _SYNTHESIS_PROMPT,
    _THIN_FINISH_CHARS,
    _THIN_FINISH_MIN_STEPS,
    _THIN_FINISH_PROMPT,
    _strip_tool_markup,
)
from colleague.loop_context import _seat_complete
from colleague.loop_transport import _complete_with_degradation
from colleague.loop_types import _Work
from colleague.loop_wire import CompleteFn, ModelResponse


def _read_heavy_zero_write(ctx: _Work) -> bool:
    """The findings-run signature shared by the thin and meta finish guards.

    Many steps spent reading, nothing written — for such a run the summary IS
    the deliverable. A run that wrote/edited files legitimately finishes short
    ("wrote out.txt"), so any write disarms both triggers; so does a short run
    (few steps = little context worth synthesizing).
    """
    stats = ctx.result.stats
    if stats.step_count < _THIN_FINISH_MIN_STEPS:
        return False
    writes = stats.tool_counts.get("write_file", 0) + stats.tool_counts.get("edit_file", 0)
    return writes == 0


def _finish_recovery_reason(ctx: _Work) -> str | None:
    """Why a *called* finish still needs a synthesis turn, or ``None`` if it doesn't.

    - ``"thin"`` (#248 mode A): the summary is a bare headline (under
      ``_THIN_FINISH_CHARS``) after a read-heavy zero-write run.
    - ``"meta"`` (#231): the summary DESCRIBES a report (claim-of-coverage
      language) without containing it — under ``_META_FINISH_CHARS`` so a real
      long report that merely says "analysis complete" is never re-opened.
    """
    summary = (ctx.result.summary or "").strip()
    if not summary or not _read_heavy_zero_write(ctx):
        return None
    if len(summary) < _THIN_FINISH_CHARS:
        return "thin"
    if len(summary) < _META_FINISH_CHARS and _META_FINISH_RE.search(summary):
        return "meta"
    return None


def _maybe_force_synthesis(ctx: _Work, outcome: str, complete: CompleteFn) -> None:
    """Force ONE no-tools synthesis turn when a context-rich run produced no summary.

    Fires on three exits, all guarded on ``not ctx.result.summary`` (an answered run
    is never touched) and ``step_count > 0`` (nothing read, nothing to synthesise):

    - **budget / stopped** (colleague#191) — the loop exhausted its step budget or
      stopped without finishing, the most expensive failure mode (full token spend,
      zero output); turn it into a usable partial.
    - **finish with an empty summary** (colleague#202) — the model *called* ``finish``
      but gave no usable summary. For a read-only verb the summary IS the deliverable,
      so a blank finish is a silent no-op (status reads ``ok``); synthesise the answer
      from what was read instead of falling back to the last planning line.
    - **finish with a thin or meta summary** (#248 mode A / #231) — the summary is a
      bare headline, or *describes* a report it never contains, after a read-heavy
      zero-write run (:func:`_finish_recovery_reason`); recovered via a dedicated
      prompt and recorded on ``TaskResult.finish_recovered``.

    Best-effort: any error or an empty answer leaves ``summary`` untouched so the
    caller falls back to the last-substantive content or the ``NO_RESULT_PRODUCED``
    sentinel. Mirrors the retry-cap precedent (:func:`_final_degraded_attempt`) and
    reuses :func:`_complete_with_degradation` so the synthesis turn is windowed to the
    context budget like any other. A finish that carries a real summary, a pilot stop
    (already carries one), or a run that already answered is byte-identical to before.
    Runtime-owned: fires identically for every backend (all-engines rule).
    """
    if outcome not in (_EXIT_BUDGET, _EXIT_STOPPED, _EXIT_FINISHED):
        return
    # Finish-recovery reasons (#248 mode A + #231): a *called* finish whose summary
    # is only a headline ("thin") or a description of an unwritten report ("meta")
    # after a read-heavy zero-write run — non-empty, so the #202 empty-finish guard
    # alone would skip both.
    reason = _finish_recovery_reason(ctx) if outcome == _EXIT_FINISHED else None
    if (ctx.result.summary and reason is None) or ctx.result.stats.step_count <= 0:
        return
    if reason == "thin":
        prompt = _THIN_FINISH_PROMPT
    elif reason == "meta":
        prompt = _META_FINISH_PROMPT
    elif outcome == _EXIT_FINISHED:
        prompt = _EMPTY_FINISH_PROMPT
    else:
        prompt = _SYNTHESIS_PROMPT
    ctx.messages.append({"role": "user", "content": prompt})
    complete = _seat_complete(ctx, "synthesis", complete)  # t19: the associate synthesis seat
    try:
        # The synthesis turn is the worst case for #206: a single no-tools completion
        # that emits no step line, so a slow backend looks wedged. Announce it loudly.
        resp = _complete_with_degradation(ctx, complete, phase=_PHASE_SYNTHESIZING)
    except Exception:  # noqa: BLE001 - best-effort; a finalize-time turn never raises
        return
    _account_turn(ctx, resp)
    content, markup_recovered = _plain_prose_synthesis(ctx, complete, resp)
    if content:
        if reason is not None:
            # Honest degradation marker (#248/#231, h8): the artifact records that
            # the summary came from a recovery turn, not the model's own finish.
            ctx.result.finish_recovered = f"{reason}-finish-synthesis"
        elif markup_recovered:
            # Honest marker (#264): the synthesis turn itself emitted tool markup
            # and the summary came from the recovery pass, not the first output.
            ctx.result.finish_recovered = "markup-synthesis"
        ctx.result.summary = content


def _plain_prose_synthesis(
    ctx: _Work, complete: CompleteFn, first: ModelResponse
) -> tuple[str, bool]:
    """Return ``(content, recovered)`` — plain-prose text from a synthesis turn (#264).

    ``recovered`` is True when the first synthesis output was markup-contaminated
    and a recovery pass produced the returned content: ONE bounded plain-prose
    retry, else the prose prefix before the first marker when substantive
    (>= ``_MARKUP_SALVAGE_CHARS``). An empty return means nothing usable survived —
    the caller leaves the summary unset so ``_resolve_terminal_summary`` falls
    through to its next rung instead of shipping garbled markup as the deliverable.
    """
    content = (first.content or "").strip()
    prefix = _strip_tool_markup(content)
    if prefix == content:
        return content, False
    ctx.messages.append({"role": "assistant", "content": first.content})
    ctx.messages.append({"role": "user", "content": _MARKUP_SYNTHESIS_PROMPT})
    try:
        retry = _complete_with_degradation(ctx, complete, phase=_PHASE_SYNTHESIZING)
    except Exception:  # noqa: BLE001 - best-effort; salvage what the first turn had
        return (prefix if len(prefix) >= _MARKUP_SALVAGE_CHARS else ""), True
    _account_turn(ctx, retry)
    retry_content = (retry.content or "").strip()
    retry_prefix = _strip_tool_markup(retry_content)
    if retry_content and retry_prefix == retry_content:
        return retry_content, True
    best = retry_prefix if len(retry_prefix) > len(prefix) else prefix
    return (best if len(best) >= _MARKUP_SALVAGE_CHARS else ""), True


def _resolve_terminal_summary(
    ctx: _Work, outcome: str, complete: CompleteFn, last_sub: str
) -> None:
    """Resolve ``result.summary`` on a non-finish exit; a finish/pilot summary is kept.

    Order is the point (it fixes the stale-compaction-summary regression, Qodo
    PR #198): force ONE no-tools synthesis turn (#191) **first** so the summary
    reflects everything read — INCLUDING any tool work the model did *after* a
    mid-run compaction. A run's own compaction self-summary (auto-compact-on-finish,
    t3) predates that later work, so it is only the **fallback** when synthesis
    yields nothing (it still survives to the exit — its reason for being captured),
    never preferred over a fresh synthesis. Final fallback: the last substantive
    prose, else the ``NO_RESULT_PRODUCED`` sentinel.

    A clean ``finish`` (or a pilot stop) already set ``result.summary``, so
    ``_maybe_force_synthesis`` and both fallbacks no-op — byte-identical to before.
    Extracted from :func:`run` so that function stays under the S3776
    cognitive-complexity threshold.
    """
    _maybe_force_synthesis(ctx, outcome, complete)
    if not ctx.result.summary and ctx._compacted_summary:
        ctx.result.summary = ctx._compacted_summary[0]
    if not ctx.result.summary:
        ctx.result.summary = last_sub or NO_RESULT_PRODUCED
