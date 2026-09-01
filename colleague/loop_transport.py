"""The transport lane: one guarded model turn, graceful degradation, stall and
timeout guards, agent attribution.

Extracted from ``colleague/loop.py`` (plan hard-1000-line-file-limit, t15).
A pure move — the bounded overflow shrink-and-retry, the timeout survival path
(#268) and the adaptive backpressure (#255) are unchanged.
"""

from __future__ import annotations

import os
import sys
import time
from contextlib import suppress
from typing import Any

from colleague import backpressure, media, repetitionguard, stallguard, streamguards
from colleague.context import TruncatedTurn, classify_degradable, is_media_rejection
from colleague.loop_accounting import _account_turn
from colleague.loop_constants import (
    _MAX_OVERFLOW_RETRIES,
    _MAX_TIMEOUT_RETRIES,
    _MEDIA_DROPPED,
    _OVERFLOW_SHRINK_FACTOR,
    _PHASE_THINKING,
    _RETRY_IMMEDIATE,
    _STALL_ENV,
    _STALL_FLOOR_SECONDS,
)
from colleague.loop_context import _autosplit_armed, _inject_split_recommendation, _window_in_place
from colleague.loop_progress import _emit_phase
from colleague.loop_types import _Work
from colleague.loop_wire import CompleteFn, ModelResponse


def _handle_degradable_exhaustion(ctx: _Work, exc: Exception) -> bool:
    """Reactive auto-split (#151) on an EXHAUSTED degradable error; return continue?.

    Returns ``True`` (inject ONE split recommendation, caller continues) when armed,
    not yet recommended, and the error is degradable — BEFORE it would propagate to
    run()'s abort+escalate path. Returns ``False`` otherwise so the caller re-raises,
    byte-identical to the pre-feature loop. Extracted from :func:`_work_loop` to keep
    its cognitive complexity within budget (SonarCloud S3776).
    """
    if (
        _autosplit_armed(ctx)
        and not ctx._split_recommended
        and classify_degradable(str(exc)) is not None
    ):
        _inject_split_recommendation(ctx)
        return True
    return False


def _remember_degraded_floor(ctx: _Work, budget: int) -> None:
    """Carry the floored budget from an exhausted give-up into the next turn (#154).

    Records the small window the shrink-and-retry bottomed out at so the auto-split /
    INCOMPLETE recommendation turn :func:`_work_loop` is about to grant runs against
    it instead of re-expanding to the full budget (which would just overflow / time
    out again). Set once on give-up; consumed-and-cleared by the next
    :func:`_complete_with_degradation` call, so only the recommendation turn is
    throttled. No-op cell when degradation is off (it is only ever read with a budget).
    """
    ctx._degraded_budget[:] = [max(1, budget)]


def _open_degradation_window(ctx: _Work, budget: int) -> int:
    """Window the history to the starting budget, honouring a carried-forward floor (#154).

    A prior exhausted give-up may have carried a floored budget forward so this turn —
    the auto-split / INCOMPLETE recommendation turn — stays small; honour it once, then
    clear it so later turns return to the full budget. Returns the effective starting
    budget the first ``complete`` attempt runs against.
    """
    start = budget
    if ctx._degraded_budget:
        start = min(budget, ctx._degraded_budget[0])
        ctx._degraded_budget.clear()
    _window_in_place(ctx, start)
    return start


def _shrink_for_retry(ctx: _Work, effective: int) -> int | None:
    """Shrink the budget one step and re-window; return the new budget, or ``None`` at the floor.

    Each retry strictly shrinks the budget (``* _OVERFLOW_SHRINK_FACTOR``, floored to
    ≥ 1) AND must reduce the message count. ``None`` means the floor was hit — neither
    the budget nor the message list (only system + first user + last turn remain) can
    shrink further — so retrying cannot help and the caller must give up. This pairing
    is what guarantees the reactive loop always terminates.
    """
    shrunk = max(1, int(effective * _OVERFLOW_SHRINK_FACTOR))
    before = len(ctx.messages)
    _window_in_place(ctx, shrunk)
    if shrunk >= effective and len(ctx.messages) >= before:
        return None
    return shrunk


def _plan_degraded_retry(
    ctx: _Work, exc: Exception, effective: int, saw_overflow: bool
) -> tuple[int, int, bool] | None:
    """Classify a caught error and prepare the next degraded retry.

    Returns ``(new_effective, new_cap, saw_overflow)`` to retry, or ``None`` to stop
    (the caller re-raises). Two stop cases collapse to ``None`` because both end the
    same way — the caller re-raises the in-flight exception: a *non-degradable* error
    (nothing to carry) and a degradable *floor* give-up (the floored budget is carried
    forward here via :func:`_remember_degraded_floor` before returning). The cap honours
    overflow precedence: once ANY overflow is seen it is the higher ``_MAX_OVERFLOW_RETRIES``,
    else the lower ``_MAX_TIMEOUT_RETRIES`` (#157).
    """
    signal = classify_degradable(str(exc))
    if signal is None:
        return None  # non-degradable: propagate immediately (unchanged)
    saw_overflow = saw_overflow or signal in ("overflow", "truncated")
    if signal == "timeout":
        # #268 ask 1: raise the per-turn timeout (bounded, once) BEFORE the retry
        # so the retry gets real headroom — a shrunken window alone cannot help
        # when the server itself is saturated (the observed irc-lens abort: both
        # attempts hit the same 120s wall). A no-op when already raised by the
        # proactive backpressure trigger or when no escalator is wired.
        _escalate_request_timeout(ctx, "a turn timeout")
    cap = _MAX_OVERFLOW_RETRIES if saw_overflow else _MAX_TIMEOUT_RETRIES
    shrunk = _shrink_for_retry(ctx, effective)
    if shrunk is None:
        _remember_degraded_floor(ctx, effective)  # at the floor: carry it, then give up
        return None
    return shrunk, cap, saw_overflow


def _final_degraded_attempt(ctx: _Work, complete: CompleteFn, effective: int) -> ModelResponse:
    """One last ``complete`` after the retry cap was exhausted while still making progress.

    A success returns normally and must NOT throttle the next (normal) turn; a
    degradable give-up carries the floored budget forward (#154) before re-raising so
    :func:`run` preserves the partial. A non-degradable error just re-raises.
    """
    try:
        return _timed_complete(ctx, complete)
    except Exception as exc:  # noqa: BLE001
        # Carry the floor only on a degradable give-up, then re-raise either way.
        if classify_degradable(str(exc)) is not None:
            _remember_degraded_floor(ctx, effective)
        raise


def _effective_timeout(ctx: _Work) -> float | None:
    """The live per-turn timeout: the #268-escalated value when raised, else the
    configured one — so backpressure classifies against the cap actually in force."""
    return ctx._escalated_timeout[0] if ctx._escalated_timeout else ctx.request_timeout


def _current_backpressure(ctx: _Work) -> str:
    """The loop's current backpressure state (CLEAR when the feature is dormant)."""
    return ctx._backpressure_state[0] if ctx._backpressure_state else backpressure.CLEAR


def _agents_begin(ctx: _Work, model: str, executor: Any) -> None:
    """Seam (#411 t15): begin the agents runtime; append its static system addendum."""
    if ctx.agents is None:
        return
    # The executor's REAL allow-list (``_allowlist``: a set, or None when the
    # surface is unrestricted) — the manifest must record what the loop
    # actually offered, not the purpose's nominal set. The former
    # ``_allowlist_names`` never existed, so this was always None and the
    # digest always over-/under-claimed.
    allow = getattr(executor, "_allowlist", None)
    ctx.agents.begin(
        ctx.task, model=model, role_tools=(sorted(allow) if allow is not None else None)
    )
    with suppress(Exception):
        addendum = ctx.agents.system_addendum()
        if addendum and ctx.messages and ctx.messages[0].get("role") == "system":
            ctx.messages[0]["content"] = f"{ctx.messages[0]['content']}\n\n{addendum}"


def _agents_record(ctx: _Work, resp: ModelResponse | None) -> None:
    """Seam (#411 t15): one invocation record per model call (truncation flagged)."""
    if ctx.agents is None:
        return
    with suppress(Exception):
        truncated = resp is not None and _is_truncated_turn(resp)
        ctx.agents.record_invocation(
            ctx.messages, truncated=truncated, count_tokens=ctx.count_tokens
        )


def _agents_end(ctx: _Work) -> None:
    """Seam (#411 t15): fold changed paths + the TaskResult.agents block (every exit)."""
    if ctx.agents is None:
        return
    with suppress(Exception):
        ctx.agents.end(ctx.result)


def _stall_bound(ctx: _Work) -> float | None:
    """The step-stall bound in seconds, or ``None`` when disabled (#400).

    ``COLLEAGUE_MAX_STEP_STALL`` (seconds) wins when set — ``0``/negative/unparsable
    disables the watchdog. Otherwise the bound is the fixed floor: the former
    ``6 x mean turn latency`` scaling was retired (adopt-from-qwen-code c12) —
    an alive-but-slow stream is bounded by :mod:`colleague.streamguards` instead.
    """
    raw = os.environ.get(_STALL_ENV)
    if raw is not None and raw.strip():
        try:
            value = float(raw)
        except ValueError:
            return None
        return value if value > 0 else None
    del ctx  # the bound no longer depends on measured latencies
    return _STALL_FLOOR_SECONDS


def _mark_progress(ctx: _Work) -> None:
    """Restart the step-stall clock: a step just completed (or the loop just began)."""
    ctx._last_progress[:] = [time.monotonic()]


def _record_stall(ctx: _Work, seconds: float, bound: float, guard: str = "step-stall") -> None:
    """Record a crossed stall bound honestly: warning (naming WHICH guard — the #400
    progress bound or a c12 stream guard) + phase notice + the ``step-stall`` exit cell."""
    ctx._stalled[:] = [seconds]
    ctx.result.warnings.append(
        {
            "kind": "step-stall",
            "guard": guard,
            "seconds": round(seconds, 1),
            "bound_seconds": round(bound, 1),
            "step_index": len(ctx.result.steps),
        }
    )
    if guard != "step-stall":
        _emit_phase(ctx, streamguards.stall_notice(guard, seconds, bound))
        return
    _emit_phase(
        ctx,
        f"step-stall: no completed step for {seconds:.0f}s (bound {bound:.0f}s) — "
        f"ending the episode with a partial; raise {_STALL_ENV} for longer turns",
    )


def _stalled_between_turns(ctx: _Work) -> bool:
    """Between turns: has the time since the last completed step crossed the bound?

    Covers transports that cannot consult :mod:`colleague.stallguard` mid-turn (a
    blocking request, the mock engine); the in-turn check lives in
    :func:`_timed_complete`.
    """
    if ctx._stalled:
        return True
    bound = _stall_bound(ctx)
    if bound is None or not ctx._last_progress:
        return False
    elapsed = time.monotonic() - ctx._last_progress[0]
    if elapsed <= bound:
        return False
    _record_stall(ctx, elapsed, bound)
    return True


def _timed_complete(ctx: _Work, complete: CompleteFn) -> ModelResponse:
    """Call ``complete`` measuring wall-clock latency for backpressure (t6/#255).

    Dormant (a plain call, no clock) unless ``ctx.request_timeout`` is a positive
    number. The latency is recorded in ``finally`` — a raising completion (above
    all a request TIMEOUT, which costs the full window) is precisely the slow
    turn the classifier must see.
    """
    # Step-stall watchdog (#400): arm the progress deadline (time since the LAST
    # completed step, not this turn's start) so a streaming transport can end a
    # turn that is alive but not progressing; disarmed in ``finally`` so nothing
    # leaks into the next call or a different context.
    bound = _stall_bound(ctx)
    since = ctx._last_progress[0] if ctx._last_progress else time.monotonic()
    token = stallguard.arm(since=since, bound=bound) if bound is not None else None
    resp: ModelResponse | None = None
    try:
        if not ctx.request_timeout or ctx.request_timeout <= 0:
            resp = complete(ctx.messages)
            return resp
        start = time.monotonic()
        try:
            resp = complete(ctx.messages)
            return resp
        finally:
            _record_turn_latency(ctx, time.monotonic() - start)
    finally:
        if token is not None:
            stallguard.disarm(token)
        _agents_record(ctx, resp)  # #411 t15: one invocation record per model call


def _record_turn_latency(ctx: _Work, seconds: float) -> None:
    """Fold one completion latency into the rolling backpressure classification.

    On a state TRANSITION the fan-out throttle (when wired) is retuned —
    ``throttled_concurrency`` maps CLEAR back to the operator's configured width,
    so recovery is automatic — and the first departure from CLEAR records a
    once-per-work-item advisory on ``result.capacity_warning`` (surfaced on
    stderr by the work CLI) plus a phase-notice line for live visibility.
    Advisory + tighten-only: never an error, never a different model/backend.
    """
    ctx._turn_latencies.append(seconds)
    previous = _current_backpressure(ctx)
    state = backpressure.assess(ctx._turn_latencies, float(_effective_timeout(ctx) or 0))
    ctx._backpressure_state[:] = [state]
    if state == previous:
        return
    if ctx.fanout_throttle is not None:
        with suppress(Exception):
            ctx.fanout_throttle(state)
    if state != backpressure.CLEAR and not ctx._backpressure_advised:
        ctx._backpressure_advised[:] = [True]
        note = (
            f"backpressure {state}: model turns are averaging "
            f"{sum(ctx._turn_latencies[-3:]) / len(ctx._turn_latencies[-3:]):.0f}s "
            f"toward the {(_effective_timeout(ctx) or 0):.0f}s request timeout — tightening the "
            f"context window (x{backpressure.shrink_fraction(state)}) and subagent "
            "fan-out until turns recover"
        )
        existing = ctx.result.capacity_warning
        ctx.result.capacity_warning = f"{existing}; {note}" if existing else note
        _emit_phase(ctx, note)
        # #268 ask 2 / #438 guidance 3: raise the per-turn timeout NOW (bounded,
        # once) — suppressed while this turn's transport is stream-guarded
        # (reactive raise unchanged).
        if not _turn_transport_guarded(ctx):
            _escalate_request_timeout(ctx, "turns drifting toward the request timeout")


def _turn_transport_guarded(ctx: _Work) -> bool:
    """Whether the turn just recorded ran on a genuinely stream-guarded transport.

    #438 guidance 3 suppresses the PROACTIVE backpressure timeout raise while the
    stream guards already bound an alive-but-slow turn. The env alone cannot
    answer that (Qodo PR #450): :meth:`streamguards.StreamGuards.from_env` is
    default-armed, but a blocking (non-SSE) completion — ``COLLEAGUE_STREAM=0``
    — never reads its body through the guards, so such a turn is unguarded and
    must keep its one-time raise. Both halves must hold: the guards armed in the
    environment AND the backend reporting a guarded transport for this turn.

    ``ctx.transport_guarded`` is ``None`` for a direct ``run`` caller and for a
    backend that reports nothing (``mock``), which keeps the original env-only
    decision — byte-identical. A probe that raises is treated as guarded for the
    same reason: never let advisory plumbing flip behavior on an error.
    """
    if streamguards.StreamGuards.from_env() is None:
        return False
    if ctx.transport_guarded is None:
        return True
    try:
        return bool(ctx.transport_guarded())
    except Exception:  # noqa: BLE001 - advisory plumbing must never break a turn
        return True


def _escalate_request_timeout(ctx: _Work, trigger: str) -> str | None:
    """Bounded one-time raise of the engine's per-turn request timeout (#268).

    Fired from two places — the backpressure departure-from-CLEAR advisory
    (proactive) and a timeout-classified degraded retry (reactive) — whichever
    comes first; the escalator closure itself enforces once-per-work-item and
    the x2 bound (see :func:`_make_timeout_escalator`), so double-firing is
    structurally impossible. Updates ``ctx.request_timeout`` so subsequent
    backpressure classification runs against the raised cap, records the raise
    on ``result.capacity_warning`` (artifact-visible), and emits a phase notice
    (operator-visible). Returns the note, or ``None`` when dormant / already
    raised / nothing to raise. Best-effort: an escalator error never breaks the
    turn.
    """
    if ctx.escalate_timeout is None:
        return None
    try:
        raised = ctx.escalate_timeout()
    except Exception:  # noqa: BLE001 - advisory plumbing must never break a turn
        return None
    if not raised:
        return None
    ctx._escalated_timeout[:] = [raised]
    note = (
        f"request timeout raised to {raised:.0f}s after {trigger} "
        f"(bounded one-time x2 — cheaper than losing the flight)"
    )
    existing = ctx.result.capacity_warning
    ctx.result.capacity_warning = f"{existing}; {note}" if existing else note
    _emit_phase(ctx, note)
    return note


# ── the repetition guard's turn-cut (t6, spec c10/h17, c13/h18, c33/h25, c54/h42)
#
# :mod:`colleague.repetitionguard` is the detector; the trip SEMANTICS are here,
# and they are deliberately NOT :mod:`colleague.loopguards`' — that guard ends the
# run outright, this one CUTS THE TURN into the tighter-window retry that
# demonstrably rescued run ``2bd306a6916a``. Only the
# ``ESCALATION_TRIP_LIMIT``-th trip of one run ends it.
#
# ONE trip = ONE TURN in which the detector fired, never one detector callback:
# once a buffer's tail is repeating, ``repetitionguard.check`` reports a trip on
# EVERY subsequent chunk (a 272k-char spiral fed in 500-char chunks reports ~703
# of them). Counting callbacks would end a run on its first spiral and the
# turn-cut recovery would never happen. The streaming call site therefore ABORTS
# on the first trip of a turn (so a turn can raise at most once) and the blocking
# call site runs the detector exactly once, post-turn.

#: The tier that trips: qwen-code's verbatim content repetition, never its
#: entropy tier (see :mod:`colleague.loopguards`' docstring).
_REPETITION_GUARD = "verbatim-tail"

#: What the artifact says about a STREAM-cut turn's tokens. Aborting the SSE read
#: discards the final ``usage`` frame, and CLAUDE.md is absolute that tokens are
#: exactly what ``usage`` reports and are NEVER estimated — so the turn is left
#: unaccounted (exactly what the existing :class:`streamguards.StreamGuardTripped`
#: path does with a cut turn) and the artifact SAYS SO, rather than carrying a
#: zero that reads as "this turn was free".
_USAGE_UNRECORDED = (
    "unrecorded: the SSE read was aborted before the final usage frame, so this "
    "turn's prompt/completion tokens are absent from the run totals — never estimated"
)
_USAGE_RECORDED = "recorded: the turn's usage frame arrived; its tokens are in the run totals"


class RepetitionTripped(Exception):
    """One turn's reasoning repeated verbatim past the detector's threshold.

    Raised by the vLLM streaming reader the moment
    :func:`colleague.repetitionguard.check` trips on an arriving reasoning delta
    (which aborts the SSE read), and constructed by the blocking path here for
    the post-turn check — so ONE warning shape reaches the artifact either way
    (spec c17: a LOOP-level warning, never an adapter-only artifact).

    ``reasoning_chars`` is the exact length of the reasoning seen when the trip
    fired; ``tokens_recorded`` is ``False`` when the turn's ``usage`` frame was
    discarded with the aborted read.
    """

    def __init__(
        self,
        trip: dict[str, Any],
        *,
        reasoning_chars: int,
        tokens_recorded: bool = False,
    ) -> None:
        self.trip = dict(trip or {})
        self.reasoning_chars = int(reasoning_chars)
        self.tokens_recorded = bool(tokens_recorded)
        super().__init__(
            f"repetition guard: a {self.trip.get('period')}-character unit repeated "
            f"{self.trip.get('repeats')} times verbatim in this turn's reasoning "
            f"({self.reasoning_chars} reasoning chars) — the turn was cut"
        )


def _repetition_warning(exc: RepetitionTripped, trips: int, *, step_index: int) -> dict[str, Any]:
    """The ONE warning a trip records — identical on the streaming and blocking paths."""
    return {
        "kind": repetitionguard.WARNING_KIND,
        "guard": _REPETITION_GUARD,
        "trip": trips,
        "limit": repetitionguard.ESCALATION_TRIP_LIMIT,
        "period": exc.trip.get("period"),
        "repeats": exc.trip.get("repeats"),
        "unit_preview": exc.trip.get("unit_preview"),
        "reasoning_chars": exc.reasoning_chars,
        "step_index": step_index,
        "tokens_recorded": exc.tokens_recorded,
        "usage": _USAGE_RECORDED if exc.tokens_recorded else _USAGE_UNRECORDED,
    }


def _record_repetition_trip(ctx: _Work, exc: RepetitionTripped) -> int:
    """Record ONE trip and return the run's trip count; RE-RAISE at the limit.

    The count is derived from the warnings already on the artifact (the
    :mod:`colleague.runcounts` rule: the counter and the record can never
    disagree), so no new ``_Work`` cell is needed and a continuation that
    rehydrates the warnings rehydrates the count with them. Raising at
    :data:`~colleague.repetitionguard.ESCALATION_TRIP_LIMIT` ends the run through
    :func:`colleague.loop.run`'s existing preserve-the-partial abort path — the
    warning is already recorded, so the run ends WITH it.
    """
    trips = (
        sum(
            1
            for w in ctx.result.warnings
            if isinstance(w, dict) and w.get("kind") == repetitionguard.WARNING_KIND
        )
        + 1
    )
    ctx.result.warnings.append(_repetition_warning(exc, trips, step_index=len(ctx.result.steps)))
    if trips >= repetitionguard.ESCALATION_TRIP_LIMIT:
        _emit_phase(
            ctx,
            f"repetition guard: trip {trips} of {repetitionguard.ESCALATION_TRIP_LIMIT} — "
            "the model keeps repeating itself verbatim; ending the run with the partial",
        )
        raise exc
    _emit_phase(
        ctx,
        f"repetition guard: the turn's reasoning repeated a "
        f"{exc.trip.get('period')}-character unit {exc.trip.get('repeats')} times verbatim "
        f"({exc.reasoning_chars} chars) — cutting the turn; retrying with a tighter window",
    )
    return trips


def _response_repetition(resp: ModelResponse) -> RepetitionTripped | None:
    """The blocking path's post-turn check: run the SAME detector ONCE over the
    finished reasoning text. Tokens are recorded here — the response carried its
    own ``usage`` frame, nothing was aborted."""
    text = resp.reasoning or ""
    if not text:
        return None
    _state, trip = repetitionguard.check(text, repetitionguard.new_state())
    if trip is None:
        return None
    return RepetitionTripped(trip, reasoning_chars=len(text), tokens_recorded=True)


def _is_truncated_turn(resp: ModelResponse) -> bool:
    """An empty-content, tool-less turn the server cut at ``finish_reason=length`` (#411 t8)."""
    return not resp.content and not resp.tool_calls and resp.finish_reason == "length"


def _record_truncated_turn(ctx: _Work, resp: ModelResponse, *, account: bool) -> None:
    """Record a truncated turn honestly (warning + phase notice; tokens exact).

    The turn DID cost prompt + completion tokens (the completion was reasoning that
    never reached an answer), so it is never dropped: ``account=True`` accounts it
    here because the caller discards ``resp`` for a retry; ``account=False`` when
    ``resp`` flows on to ``_work_loop`` (which accounts every returned turn itself)
    — never both. Recorded on ``TaskResult.warnings`` (the per-invocation record
    takes over once the agents runtime lands, plan t15).
    """
    if account:
        _account_turn(ctx, resp)
    ctx.result.warnings.append(
        {
            "kind": "truncated-turn",
            "finish_reason": resp.finish_reason,
            "reasoning_chars": len(resp.reasoning or ""),
            "step_index": len(ctx.result.steps),
        }
    )
    _emit_phase(
        ctx,
        "truncated turn: the model hit its output budget (finish_reason=length) before "
        "any answer — recorded; retrying with a tighter window",
    )


def _attempt_completion_or_retry_plan(
    ctx: _Work,
    complete: CompleteFn,
    effective: int,
    saw_overflow: bool,
) -> tuple[ModelResponse | None, object]:
    """Run one reactive-retry-loop attempt; on failure, decide how to continue.

    Extracted from :func:`_complete_with_degradation` (SonarCloud S3776) so the
    loop's own body stays a flat dispatch. Returns ``(resp, None)`` on success.
    On a caught error, returns ``(None, _RETRY_IMMEDIATE)`` when
    :func:`_flatten_on_media_rejection` handled it (retry now, don't count
    against the attempt cap — structurally bounded since the flatten removes
    every part, so it cannot fire twice) or ``(None, plan)`` with the
    ``(new_effective, new_cap, new_saw_overflow)`` tuple from
    :func:`_plan_degraded_retry` to retry with the updated windowing state.
    Re-raises the original exception unchanged when :func:`_plan_degraded_retry`
    reports ``None`` (non-degradable, or the degradable floor was reached) —
    the give-up path, so :func:`run` preserves the partial.
    """
    try:
        resp = _timed_complete(ctx, complete)
    except RepetitionTripped as trip:
        # t6: the streaming reader cut this turn. Record ONE warning (the call
        # re-raises at the escalation limit, ending the run) and ride the SAME
        # shrink-and-retry plan a truncated turn does. At the floor there is no
        # tighter window left, so the retry is immediate and uncounted — bounded
        # by the escalation limit, which every trip advances.
        _record_repetition_trip(ctx, trip)
        plan = _plan_degraded_retry(ctx, TruncatedTurn(), effective, saw_overflow)
        return None, plan if plan is not None else _RETRY_IMMEDIATE
    except Exception as exc:  # noqa: BLE001
        if _flatten_on_media_rejection(ctx, exc):
            return None, _RETRY_IMMEDIATE
        plan = _plan_degraded_retry(ctx, exc, effective, saw_overflow)
        if plan is None:
            raise
        return None, plan
    repeated = _response_repetition(resp)
    if repeated is not None:
        # t6 / criterion 5: the incident's blocking shape satisfies BOTH this and
        # ``_is_truncated_turn``; the repetition warning is the specific one, so it
        # is recorded INSTEAD of ``truncated-turn`` — never a duplicate pair. The
        # turn's tokens are exact and are never dropped (the ``account=`` rule
        # ``_record_truncated_turn`` documents).
        _record_repetition_trip(ctx, repeated)
        plan = _plan_degraded_retry(ctx, TruncatedTurn(), effective, saw_overflow)
        if plan is not None:
            _account_turn(ctx, resp)
            return None, plan
        return resp, None  # at the floor: _work_loop accounts the returned turn
    if _is_truncated_turn(resp):
        # #411 t8: an empty-content finish_reason=length turn is a truncation, not an
        # answer — record it and ride the SAME shrink-and-retry plan; at the floor
        # the empty turn falls through to the ordinary no-tool handling (honest:
        # nothing left to shrink).
        plan = _plan_degraded_retry(ctx, TruncatedTurn(), effective, saw_overflow)
        _record_truncated_turn(ctx, resp, account=plan is not None)
        if plan is not None:
            return None, plan
    return resp, None


def _complete_without_budget(ctx: _Work, complete: CompleteFn) -> ModelResponse:
    """The budget-off pass-through of :func:`_complete_with_degradation`.

    Extracted purely to hold that function under the SonarCloud S3776 ceiling
    (#479 t6 added the repetition arms); behaviour is unchanged. Byte-identical
    to the pre-feature loop apart from the two recorded-only cases below and the
    ONE media-rejection retry (t9, c7), which must not depend on the budget
    feature being on.
    """
    while True:
        try:
            resp = _timed_complete(ctx, complete)
        except RepetitionTripped as trip:
            # t6: no budget = no tighter window, but the turn is still CUT
            # rather than fatal — record it and re-ask. Bounded: the call
            # re-raises at the escalation limit, which every trip advances.
            _record_repetition_trip(ctx, trip)
            continue
        except Exception as exc:  # noqa: BLE001
            if _flatten_on_media_rejection(ctx, exc):
                return _timed_complete(ctx, complete)
            raise
        repeated = _response_repetition(resp)
        if repeated is not None:
            # t6 / criterion 5: recorded INSTEAD of ``truncated-turn``; with no
            # budget there is nothing to shrink, so the turn flows on to the
            # existing no-tool handling (which accounts it) exactly as a
            # recorded truncation already does.
            _record_repetition_trip(ctx, repeated)
        elif _is_truncated_turn(resp):
            # no budget = nothing to shrink: recorded only; _work_loop accounts resp
            _record_truncated_turn(ctx, resp, account=False)
        return resp


def _complete_with_degradation(
    ctx: _Work, complete: CompleteFn, *, phase: str = _PHASE_THINKING
) -> ModelResponse:
    """Window the history, call ``complete``, and degrade-on-overflow-or-timeout if budgeted.

    Owns the proactive window + the bounded reactive shrink-and-retry so
    :func:`_work_loop` stays shallow (SonarCloud S3776). With no positive
    ``context_budget`` this is a thin pass-through: no windowing, ``complete`` is
    called once and whatever it raises propagates unchanged.

    With a budget set: the history is windowed before the call. If ``complete``
    raises a *degradable* error — a context-overflow OR a request timeout
    (:func:`colleague.context.classify_degradable`) — the budget is shrunk and the
    call retried (see :func:`_shrink_for_retry`). The retry cap is per-signal and
    honours overflow precedence: a timeout alone is bounded by the lower
    ``_MAX_TIMEOUT_RETRIES`` (each attempt costs a full request-timeout window, #154),
    but ANY overflow seen in the sequence restores the higher ``_MAX_OVERFLOW_RETRIES``
    (an instant 400 is ~free to retry) — so a timeout earlier in a mixed
    timeout→overflow run never starves the later cheap overflow retries (#157, matching
    :func:`classify_degradable`'s overflow-takes-precedence rule). Retrying stops (and
    the original error re-raises, so :func:`run` preserves the partial) when the cap is
    reached OR :func:`_shrink_for_retry` reports the floor. On give-up the floored
    budget is carried to the next turn — the recommendation turn — via
    :func:`_remember_degraded_floor`. Non-degradable errors are never retried — they
    propagate immediately.

    The per-attempt failure handling (media-rejection flatten vs. classify-and-shrink)
    is delegated to :func:`_attempt_completion_or_retry_plan`; this function stays the
    orchestrator over the retry accounting (``effective``/``cap``/``saw_overflow``/
    ``attempt``).
    """
    # Phase notice (#206): announce the model turn is in flight BEFORE the (possibly
    # long) completion — fired here, the one chokepoint every model turn passes
    # through, so the notice reaches the operator whether or not the context-budget
    # feature is on. Observability only; a no-op without a progress sink.
    _emit_phase(ctx, phase)
    budget = ctx.context_budget
    if not isinstance(budget, int) or budget <= 0:
        # Feature off: strict pass-through, byte-identical to the pre-feature loop
        # (latency is still measured when backpressure is armed — the advisory +
        # fan-out throttle work without windowing; only the shrink needs a budget).
        # ONE exception (t9, c7): a media-refusing endpoint still degrades to a
        # text-only retry — that handling must not depend on the budget feature.
        return _complete_without_budget(ctx, complete)

    # Adaptive backpressure (t6/#255): under ARMED/ESCALATED the next turn's
    # window is proactively tightened — smaller prompts make faster turns, the
    # #229 move — composing with (never replacing) the reactive shrink-on-error.
    state = _current_backpressure(ctx)
    if state != backpressure.CLEAR:
        budget = max(1, int(budget * backpressure.shrink_fraction(state)))

    effective = _open_degradation_window(ctx, budget)
    # The first attempt plus up to ``cap`` reactive retries. ``cap`` tracks the
    # highest-precedence signal seen so far (see :func:`_plan_degraded_retry`): it stays
    # at the overflow cap unless ONLY timeouts have been seen, and an overflow at any
    # point restores it (#157). The loop always terminates: each retry strictly shrinks
    # the budget and the message count (the floor), and the cap bounds the attempts.
    saw_overflow = False
    cap = _MAX_OVERFLOW_RETRIES
    attempt = 0
    while attempt <= cap:
        resp, plan = _attempt_completion_or_retry_plan(ctx, complete, effective, saw_overflow)
        if resp is not None:
            return resp
        if plan is _RETRY_IMMEDIATE:
            continue
        effective, cap, saw_overflow = plan
        attempt += 1
    return _final_degraded_attempt(ctx, complete, effective)


def _flatten_on_media_rejection(ctx: _Work, exc: Exception) -> bool:
    """Flatten every parts message and record the drop after a media-refusal (c7).

    Returns ``True`` when a retry should happen — the error matched
    :func:`colleague.context.is_media_rejection` AND at least one parts
    message existed to flatten (so the retry is structurally different).
    The task's attachments are recorded ``dropped`` (unless a bridge already
    preset the record) with a stderr warning naming the cause; the run
    continues text-only instead of hard-failing on an attachment the serving
    model cannot take.
    """
    if not is_media_rejection(str(exc)):
        return False
    had_parts = False
    for i, m in enumerate(ctx.messages):
        if isinstance(m.get("content"), list):
            ctx.messages[i] = dict(m, content=media.flatten_parts(m["content"]))
            had_parts = True
    if not had_parts:
        return False
    if ctx.task.attachments and ctx.result.media is None:
        ctx.result.media = {
            "attachments": [
                {"path": str(a.get("path", "?")), "status": _MEDIA_DROPPED}
                for a in ctx.task.attachments
                if isinstance(a, dict)
            ]
        }
    print(
        "warning: the serving endpoint rejected media content parts "
        f"({exc}) — retrying text-only with placeholders; media recorded "
        "dropped on the artifact",
        file=sys.stderr,
    )
    return True


def _complete_turn_or_retry(ctx: _Work, complete: CompleteFn) -> ModelResponse | None:
    """Call ``complete`` for this turn, or signal "retry without accounting".

    Thin wrapper around :func:`_complete_with_degradation` that folds in the
    reactive-auto-split give-up handling: on an EXHAUSTED degradable error that
    :func:`_handle_degradable_exhaustion` turns into ONE injected split
    recommendation, returns ``None`` so the caller's ``continue`` re-enters the
    loop without accounting a turn; any other error re-raises unchanged
    (byte-identical to the pre-feature loop). Extracted from :func:`_work_loop`
    to keep its cognitive complexity within budget (SonarCloud S3776).
    """
    try:
        return _complete_with_degradation(ctx, complete)
    except stallguard.TurnStalled as exc:
        # Step-stall (#400): the turn was alive but no step completed within the
        # bound — record it and let _work_loop end the episode with a partial.
        _record_stall(ctx, exc.seconds, exc.bound, getattr(exc, "guard", "step-stall"))
        return None
    except Exception as exc:  # noqa: BLE001
        # An EXHAUSTED degradable error may trigger the reactive auto-split (#151,
        # #154) — inject ONE recommendation and continue BEFORE the error would
        # reach run()'s abort+escalate path; otherwise re-raise unchanged so
        # escalation remains the fallback (byte-identical to the pre-feature loop).
        if _handle_degradable_exhaustion(ctx, exc):
            return None
        raise
