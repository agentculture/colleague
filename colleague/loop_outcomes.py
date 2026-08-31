"""Terminal bookkeeping: outcome flags, finish states, stats, honest incompletion.

Extracted from ``colleague/loop.py`` (plan hard-1000-line-file-limit, t15).
A pure move.
"""

from __future__ import annotations

from collections import Counter

from colleague import associate
from colleague import loopguards as _loopguards
from colleague import runcounts as _runcounts
from colleague import webbudget
from colleague.context import classify_degradable
from colleague.contract import (
    FINISH_DELIBERATE,
    FINISH_EMPTY,
    FINISH_TRUNCATED,
    INCOMPLETE,
    OK,
    FinishRecord,
    IncompletionRecord,
    SensesBlock,
    Task,
    TaskResult,
)
from colleague.finishstate import classify_finish_state
from colleague.incompletion import classify_incompletion
from colleague.loop_constants import (
    _EXIT_BUDGET,
    _EXIT_FINISHED,
    _EXIT_LOOP_GUARD,
    _EXIT_PILOT_STOP,
    _EXIT_STALLED,
    _EXIT_STOPPED,
    _EXIT_TOOL_PROTOCOL,
    _STALL_ENV,
)
from colleague.loop_types import _MAX_FINISH_NUDGES, ContextControls, _Work
from colleague.roles import is_read_only
from colleague.tools import ToolExecutor, ToolOutcome


def _apply_finish(result: TaskResult, outcome: ToolOutcome) -> None:
    """Record a finish on ``result`` — summary, then optional destination/announcement.

    Same order and truthiness guards as the inline finish path it replaced: the
    destination/announcement are set only when the engine declared them, so a
    finish without a goal-frame leaves those keys off the artifact (the e2e shape
    test pins this).
    """
    result.summary = outcome.finish_summary or result.summary
    if outcome.destination:
        result.destination = outcome.destination
    if outcome.announcement:
        result.announcement = outcome.announcement


def _finalize_stats(
    result: TaskResult,
    task: Task,
    executor: ToolExecutor,
    *,
    started_at: str,
    duration_seconds: float,
    model: str = "",
    served_model: str = "",
) -> None:
    """Fill the :class:`WorkStats` fields known only at loop exit (every exit path).

    Per-turn fields accumulate in :func:`_work_loop`; ``engine``/``model`` make
    the ROI block self-describing, ``served_model`` (t18) is what the reply named.
    """
    stats = result.stats
    stats.request = task.instruction
    stats.engine = task.engine
    stats.model = associate.recorded_model(model, served_model)  # t18/c49
    stats.started_at = started_at
    stats.duration_seconds = duration_seconds
    stats.step_count = len(result.steps)
    stats.tool_counts = dict(Counter(step.tool for step in result.steps))
    stats.files_changed = len(result.changed_files)
    stats.bytes_written = executor.bytes_written
    webbudget.finalize(result, executor)  # t9: web-call counters + cap warning
    _runcounts.finalize(result, executor)  # t20: derived harness counters


def _apply_outcome_flags(result: TaskResult, outcome: str, last_sub: str) -> None:
    """Map the loop's exit reason onto the result's partial-state flags, status, + summary.

    A pilot's cooperative ``stop`` is a PARTIAL, not an authoritative result, so it
    is flagged like a no-finish stop (never a bare ``ok`` with no result; composes
    with the honest-status work, colleague#192) and its summary names the cause.

    Honest status (colleague#192): any non-``_EXIT_FINISHED`` outcome that did not
    already become ``ERROR`` (the aborted path in :func:`run` handles that, before
    this is called) is ``INCOMPLETE``; a clean finish stays ``OK``. Orthogonal to
    the ``not_finished`` / ``stopped_without_finish`` flags. Folded in here (rather
    than a separate ``if`` in :func:`run`) to keep ``run`` under the S3776
    cognitive-complexity threshold.
    """
    result.not_finished = outcome in (_EXIT_BUDGET, _EXIT_STALLED)
    result.stopped_without_finish = outcome in (
        _EXIT_STOPPED,
        _EXIT_PILOT_STOP,
        _EXIT_TOOL_PROTOCOL,
        _EXIT_LOOP_GUARD,
    )
    if outcome != _EXIT_FINISHED:
        result.status = INCOMPLETE
    if outcome == _EXIT_PILOT_STOP:
        note = f"Stopped by pilot after {len(result.steps)} step(s) (partial)."
        result.summary = f"{note} {last_sub}".strip() if last_sub else note
    if outcome == _EXIT_STALLED:
        note = (
            f"Stopped after {len(result.steps)} step(s): no step completed within the "
            "step-stall bound (#400) — partial preserved (see warnings)."
        )
        result.summary = f"{note} {last_sub}".strip() if last_sub else note
        if result.incompletion is None:
            stalled = next((w for w in result.warnings if w.get("kind") == "step-stall"), {})
            result.incompletion = IncompletionRecord(
                reason="step-stall",
                evidence=(
                    f"no completed step for {stalled.get('seconds', '?')}s "
                    f"(bound {stalled.get('bound_seconds', '?')}s)"
                ),
                recommendation=(
                    f"resume with a smaller brief or raise {_STALL_ENV}; the partial "
                    "is preserved on the artifact"
                ),
            )
    if outcome == _EXIT_LOOP_GUARD:
        trip = next((w for w in result.warnings if w.get("kind") == _loopguards.WARNING_KIND), {})
        note = _loopguards.summary_note(trip, len(result.steps))
        result.summary = f"{note} {last_sub}".strip() if last_sub else note
    if outcome == _EXIT_TOOL_PROTOCOL:
        note = (
            f"Stopped after {len(result.steps)} step(s): the tool-call channel is "
            "broken — consecutive unknown-tool calls that never reached a real tool "
            "(see incompletion)."
        )
        result.summary = f"{note} {last_sub}".strip() if last_sub else note


def _senses_finish_record(senses: "SensesBlock | None") -> "FinishRecord | None":
    """Derive the "senses" seat's :class:`FinishRecord`, or ``None`` (t1, c4/h4/c30).

    :class:`SensesRecord` carries no raw wire ``finish_reason`` — senses.py's
    completion call sites never thread one through (unlike the main loop's
    ``ModelResponse``) — so ``degraded`` is the honest, already-existing proxy:
    a degraded senses call fell back / never completed against the senses
    model (dead endpoint, request error, overflow), the same "nothing usable
    produced" fact ``FINISH_EMPTY`` represents elsewhere; a clean completion is
    ``FINISH_DELIBERATE`` (the tools-off senses lane has no
    truncation/stop/timeout concept of its own today — a finer classification
    is future work for whichever task enriches ``SensesRecord`` itself, not
    this one). Returns ``None`` when no senses config ran (``senses`` is
    ``None`` or carries zero records), so an unconfigured/cortex-only run's
    ``finish_states`` carries only the "main" seat.
    """
    if senses is None or not senses.records:
        return None
    degraded = senses.records[-1].degraded
    state = FINISH_EMPTY if degraded else FINISH_DELIBERATE
    return FinishRecord(seat="senses", finish_reason="", state=state, truncated=False)


def _finalize_finish_states(
    ctx: "_Work", outcome: str, *, aborted: Exception | None = None
) -> None:
    """Populate ``result.finish_states`` — ALWAYS-on, every exit path (t1, c4/h4/c30).

    Called from TWO places in :func:`run`: the aborted (:class:`WorkAborted`)
    path (right before it raises, ``aborted`` set) and the normal exit path
    (after :func:`_resolve_terminal_summary` has finalized ``result.summary``,
    ``aborted`` left ``None``) — mirroring how ``stats``/``WorkStats`` is
    finalized on every exit (#106). The "main" seat is always recorded from
    the last-tracked ``ctx._last_finish_reason``; a "senses" seat record is
    appended too when :func:`_senses_finish_record` finds one.

    A real ``timeout`` classification (:func:`colleague.context.classify_degradable`
    on ``str(aborted)``) takes precedence even on the aborted path; any other
    abort (a non-timeout engine exception, or a degradation give-up at the
    floor) maps to ``FINISH_EMPTY`` — ``result.summary`` on that path is
    already a diagnostic fallback note, never a real deliverable.
    """
    timed_out = aborted is not None and classify_degradable(str(aborted)) == "timeout"
    main_finish_reason = ctx._last_finish_reason[0] if ctx._last_finish_reason else ""
    main_state = classify_finish_state(
        summary=ctx.result.summary,
        finish_reason=main_finish_reason,
        outcome=outcome,
        timed_out=timed_out,
        aborted=aborted is not None,
    )
    finish_states = [
        FinishRecord(
            seat="main",
            finish_reason=main_finish_reason,
            state=main_state,
            truncated=main_state == FINISH_TRUNCATED,
        )
    ]
    senses_record = _senses_finish_record(ctx.result.senses)
    if senses_record is not None:
        finish_states.append(senses_record)
    ctx.result.finish_states = finish_states


def _maybe_flag_incompletion(ctx: "_Work", outcome: str) -> None:
    """Honest-incompletion detector (colleague#313): a run that produced no
    expected deliverable comes back non-ok with an advisory
    {reason, evidence, recommendation}. Runtime-owned so every backend inherits
    it (all-engines); omit-when-None keeps a delivering run byte-identical.
    """
    result = ctx.result
    if outcome == _EXIT_STALLED and result.incompletion is not None:
        return  # the step-stall record (#400) names the cause; keep it
    cell = ctx._unknown_tool_streak
    protocol_detail = ""
    if outcome == _EXIT_TOOL_PROTOCOL and cell:
        protocol_detail = (
            f"{cell[0]} consecutive unknown-tool call(s), last {cell[1]!r} — "
            "not one reached a real tool"
        )
    record = classify_incompletion(
        outcome=outcome,
        write_intent=not is_read_only(result.role),
        changed_files=len(result.changed_files),
        summary=result.summary or "",
        step_count=result.stats.step_count,
        protocol_detail=protocol_detail,
    )
    if record is None:
        return
    result.incompletion = record
    if result.status == OK:  # downgrade a clean-finish no-deliverable (the #313 core)
        result.status = INCOMPLETE


def _resolve_nudge_cap(context: "ContextControls") -> int:
    """The continue-working nudge cap (#142 + colleague PR #198).

    Defaults to ``_MAX_FINISH_NUDGES`` when a :class:`ContextControls` omits it
    (direct :func:`run` callers / back-compat). Extracted to keep ``run`` under the
    S3776 cognitive-complexity threshold.
    """
    cap = context.max_continue_nudges
    return cap if cap is not None else _MAX_FINISH_NUDGES


def _resolve_reading_budget(context: "ContextControls", max_steps: int) -> int:
    """The reading-step budget after the synthesis reserve (#197).

    Hold back ``context.synthesis_reserve`` steps from the reading budget so a
    read-heavy run stops reading early and the forced-synthesis verdict (#191)
    runs with fresher context. Clamped to leave at least one reading step; a
    0/``None`` reserve is byte-identical (the full budget is spent reading). The
    full ``max_steps`` is still what the partial-warning hint reports. Extracted
    to keep ``run`` under the S3776 cognitive-complexity threshold.
    """
    reserve = context.synthesis_reserve or 0
    if reserve > 0:
        return max(1, max_steps - reserve)
    return max_steps
