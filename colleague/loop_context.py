"""The context lane: windowing, compaction, the fill-line, and the advisory
fan-out offers.

Extracted from ``colleague/loop.py`` (plan hard-1000-line-file-limit, t15).
A pure move — the capacity standard (#156) and its compaction validation are
unchanged.
"""

from __future__ import annotations

from colleague import autosplit as _autosplit
from colleague import fillline as _fillline
from colleague import turnbudget as _turnbudget
from colleague.config import MAX_SUBAGENT_FANOUT
from colleague.context import classify_degradable, window_messages
from colleague.contract import CapacityDecision
from colleague.loop_accounting import _account_turn
from colleague.loop_constants import _PHASE_COMPACTING
from colleague.loop_progress import _emit_phase
from colleague.loop_types import _Work
from colleague.loop_wire import CompleteFn, ModelResponse


def _window_in_place(ctx: _Work, budget: int) -> None:
    """Trim ``ctx.messages`` in place to *budget* tokens (preserves head + tail).

    Mutating in place (``[:]``) keeps the trimmed history across turns — dropping
    old context is intended. This is the lossy-windowing FLOOR: as of v1 (#156) the
    fill-line ``compact`` move replaces the elided turns with a model-authored
    summary, and this drop-oldest windowing is the fallback when the summary turn
    itself cannot fit. ``window_messages`` defaults ``count_tokens`` to the char
    estimate when ``ctx.count_tokens`` is ``None``.
    """
    ctx.messages[:] = window_messages(ctx.messages, budget, ctx.count_tokens)


def _autosplit_armed(ctx: _Work) -> bool:
    """True when reactive auto-split (#151) is armed for this work item.

    Armed iff degradation is active (a positive ``context_budget``) AND a positive
    ``autosplit_target`` is configured. Dormant (``False``) otherwise — a strict
    no-op identical to the pre-feature loop, so a caller that never sets the target
    (or sets it to 0) sees byte-identical behavior.
    """
    return (
        isinstance(ctx.context_budget, int)
        and ctx.context_budget > 0
        and isinstance(ctx.autosplit_target, int)
        and ctx.autosplit_target > 0
    )


def _inject_split_recommendation(ctx: _Work) -> None:
    """Append ONE structured split recommendation to the (windowed) history (#151).

    Names the per-child token budget (the ``context_budget`` — each child runs the
    same bounded loop under the same budget) and the child cap (derived + clamped to
    ``MAX_SUBAGENT_FANOUT - 1`` by :func:`colleague.autosplit.child_count`) and
    points the model at the existing ``subagents`` tool. Records the firing on
    ``_split_recommended`` so it is offered at most once per work item. The original
    assignment survives in ``messages[:2]`` (windowing never drops the head), so the
    model authoring the children always sees the full task.
    """
    per_child = int(ctx.context_budget)
    max_children = _autosplit.child_count(int(ctx.autosplit_target), per_child)
    body = _autosplit.build_split_recommendation(
        per_child_budget_tokens=per_child, max_children=max_children
    )
    ctx.messages.append({"role": "user", "content": body})
    ctx._split_recommended.append(True)


def _fillline_armed(ctx: _Work) -> bool:
    """True when the proactive fill-line decision (#156) is armed for this work item.

    Armed iff degradation is active (a positive ``context_budget``) AND a usable
    ``capacity_threshold`` fraction is configured. Dormant otherwise — a strict no-op
    byte-identical to the pre-feature loop.
    """
    return _fillline.armed(ctx.context_budget, ctx.capacity_threshold)


def _offer_fillline(ctx: _Work, prompt_tokens: int) -> None:
    """Inject the ONE structured fill-line decision prompt; mark it offered (#156).

    Names the three moves + the capacity numbers (reusing the autosplit child-count
    maths for the split option) and points the model at how to declare each by its
    next action. Offered at most once per CROSSING via ``_fillline_offered``
    (re-armed by :func:`_maybe_offer_fillline` once a resolved crossing drops back
    under the line — indefinite-run t1).
    """
    budget = int(ctx.context_budget)
    target = ctx.autosplit_target if isinstance(ctx.autosplit_target, int) else budget
    max_children = _autosplit.child_count(max(target, budget), budget)
    body = _fillline.build_decision_prompt(
        used_tokens=prompt_tokens,
        budget_tokens=budget,
        per_child_budget_tokens=budget,
        max_children=max_children,
    )
    ctx.messages.append({"role": "user", "content": body})
    ctx._fillline_offered.append(True)
    ctx._fillline_used.append(prompt_tokens)


def _record_fillline_decision(ctx: _Work, kind: str) -> None:
    """Record the declared fill-line move on the result (#156); mark it resolved.

    The reason names the offer-time token count (``_fillline_used``) so it matches the
    number stated in the decision prompt, not the declaring turn's slightly different
    prompt size. With the per-crossing re-arm (indefinite-run t1) a run can declare
    more than once; the singular contract field keeps the LATEST declaration (the
    contract shape is unchanged here — earlier moves stay visible as their effects:
    compaction notes in the history, subagent results, usage).
    """
    budget = int(ctx.context_budget)
    used = ctx._fillline_used[0] if ctx._fillline_used else 0
    reason = f"context at {used} of {budget} budgeted tokens (fill line)"
    ctx.result.capacity_decision = CapacityDecision(kind=kind, reason=reason)
    ctx._fillline_resolved.append(True)


def _seat_complete(ctx: _Work, seat: str, complete: CompleteFn) -> CompleteFn:
    """*complete* on the associate seat when armed (t19, c33), else *complete* itself.

    Unarmed (no factory) the acting completion is returned unchanged — byte-
    identical to main. Armed, the factory's completion runs the seat on the
    associate model and falls to cortex@low with a warning on
    ``TaskResult.warnings``; a backend without one-shot completions hands the
    acting completion back (also warned). See :mod:`colleague.associate_seats`.
    """
    factory = ctx.associate_complete
    if factory is None:
        return complete
    # Qodo #464 / #460: the lane's own counter + budget let the seat completion
    # window its request to the associate's SERVED window before dispatch.
    seat_complete = factory(
        seat,
        ctx.result.warnings.append,
        count_tokens=ctx.count_tokens,
        lane_budget=ctx.context_budget,
    )
    return seat_complete if seat_complete is not None else complete


def _compact_history(ctx: _Work, complete: CompleteFn) -> None:
    """Compact the working history into a validated model-authored summary (#156, t2/c4).

    Runs ONE bounded summarization turn over the windowed history, cross-checks the
    note against the run's own evidence (goal/original request + changed-file paths —
    :func:`fillline.validate_compaction`, pure and deterministic: the MAIN model's
    summary only, no second-model call, non-goal c12), and replaces the working
    history (after the preserved head ``messages[:2]``) with the validated note, so
    the model continues from a compact note instead of losing older context silently.
    The summary turn is accounted like any other turn (counts against the step
    budget).

    Two floors, never an abort:

    - a *degradable* completion error (the summary turn itself cannot fit / timed
      out) → today's lossy windowing, unchanged;
    - an UNREPAIRABLE note (empty/whitespace, rejected by the validator — it never
      replaces history; the old ``(no summary produced)`` silent-amnesia placeholder
      is gone from this path, h4) → :func:`_reject_compaction` (armed:
      finish-with-handoff, decision c23; unarmed: the lossy-windowing floor).
    """
    complete = _seat_complete(ctx, "compact", complete)  # t19: the associate compact author
    budget = int(ctx.context_budget)
    request = _fillline.build_compaction_request(ctx.messages, budget, ctx.count_tokens)
    # Phase notice (#206): a compaction is a no-tools model turn that emits no step
    # line, so announce it before the (possibly slow) summarization completion.
    _emit_phase(ctx, _PHASE_COMPACTING)
    try:
        resp = complete(request)
    except Exception as exc:  # noqa: BLE001
        # The summary turn itself could not fit / timed out → fall back to the
        # lossy-windowing floor (degradation unchanged); never abort on a compaction.
        if classify_degradable(str(exc)) is not None:
            _window_in_place(ctx, budget)
            return
        raise
    _account_turn(ctx, resp)
    # Validate against the run's own evidence (t2, c4). Changed-file paths come from
    # the live ``executor.changed`` set — the same set the end-of-run
    # ``result.changed_files`` snapshot is taken from (mid-run the snapshot is still
    # empty, so the populated field is honoured first, then the live set).
    changed = ctx.result.changed_files or sorted(ctx.executor.changed)
    text, ok = _fillline.validate_compaction(
        resp.content, ctx.task.goal or ctx.task.instruction, changed
    )
    if not ok:
        _reject_compaction(ctx, budget)
        return
    ctx.messages[:] = _fillline.apply_compaction(ctx.messages, text)
    # auto-compact-on-finish (t3): preserve the compaction summary on its own cell so
    # it survives later turns and can serve as the FALLBACK clean summary at a
    # stop/budget exit when forced synthesis yields nothing (_resolve_terminal_summary).
    # The RAW model text, not the repaired note: the evidence block protects the
    # continuation context; the terminal-summary fallback stays byte-identical.
    if resp.content:
        ctx._compacted_summary[:] = [resp.content]


def _reject_compaction(ctx: _Work, budget: int) -> None:
    """Handle an UNREPAIRABLE (empty) compaction note — it never replaces history (c4/h4).

    Armed (``chain_armed`` — continuation chaining, decision c23): inject the
    deterministic FINISH-WITH-HANDOFF instruction as ONE user message, so the model
    finishes with a continuation summary the next episode resumes from (the per-turn
    windowing still bounds the next completion). Unarmed: keep today's
    lossy-windowing floor, exactly like the degradable-error fallback. Either way the
    rejection is announced as a phase notice (#206) — observable on the feeds, never
    silent, and a phase notice never advances ``step_count``.
    """
    move = (
        "taking finish-with-handoff (chaining armed)"
        if ctx.chain_armed
        else "lossy windowing remains the floor"
    )
    _emit_phase(
        ctx,
        f"compaction produced an empty summary — rejected (history not replaced); {move}",
    )
    if ctx.chain_armed:
        ctx.messages.append({"role": "user", "content": _fillline.build_handoff_instruction()})
        return
    _window_in_place(ctx, budget)


def _fillline_cap_reached(ctx: _Work) -> bool:
    """True when this run's compaction turns exhausted the per-run cap (t1).

    Reads the RESOLVED cap — ``ctx.compaction_cap`` (threaded from
    ``ContextControls.compaction_cap`` / ``EngineConfig.compaction_cap``, the
    operator-tunable knob landed by #334) — falling back to
    ``fillline.DEFAULT_COMPACTION_CAP`` when unset (a direct ``run`` caller with no
    config). ``cap_reached`` already treats ``cap <= 0`` as unlimited.
    """
    count = ctx._fillline_compactions[0] if ctx._fillline_compactions else 0
    cap = ctx.compaction_cap if ctx.compaction_cap is not None else _fillline.DEFAULT_COMPACTION_CAP
    return _fillline.cap_reached(count, cap)


def _record_fillline_cap(ctx: _Work) -> None:
    """Record ONCE that the compaction cap suppressed further fill-line offers (t1).

    Follows the backpressure-advisory precedent (:func:`_record_turn_latency`):
    append the note to ``result.capacity_warning`` (the artifact) and fire a phase
    notice (the stderr/cockpit/flight feeds), so the suppression is observable on
    the trace rather than silent. Lossy windowing remains the floor for the rest of
    the run. ``_fillline_capped`` guards the once — later capped crossings no-op.
    The note names the RESOLVED cap (``ctx.compaction_cap``, #334), falling back to
    ``fillline.DEFAULT_COMPACTION_CAP`` when unset, mirroring :func:`_fillline_cap_reached`.
    """
    if ctx._fillline_capped:
        return
    ctx._fillline_capped[:] = [True]
    cap = ctx.compaction_cap if ctx.compaction_cap is not None else _fillline.DEFAULT_COMPACTION_CAP
    note = (
        f"fill-line compaction cap reached ({cap} compaction turns this run) — "
        "no further capacity offers; lossy windowing remains the floor"
    )
    existing = ctx.result.capacity_warning
    ctx.result.capacity_warning = f"{existing}; {note}" if existing else note
    _emit_phase(ctx, note)


def _maybe_microcompact(ctx: _Work, last_prompt_tokens: int) -> int:
    """Rule-based floor (t16, c11/h9): blank OLD tool results at 0.85 of the budget
    BEFORE the fill-line offer; returns the re-estimated prompt size so the offer
    fires only if still over the line (:func:`colleague.turnbudget.microcompact_turn`)."""
    return _turnbudget.microcompact_turn(
        ctx.messages,
        last_prompt_tokens,
        ctx.context_budget,
        ctx.result,
        ctx.agents,
        ctx.count_tokens,
    )


def _maybe_offer_fillline(ctx: _Work, last_prompt_tokens: int) -> None:
    """Offer the fill-line decision at each crossing of the line (#156, t1).

    Per-crossing, not once-per-run (indefinite-run t1 supersedes the v1 "fires at
    most once per work item" line): a RESOLVED offer re-arms once the run drops back
    under the line — a resolved-but-still-over boundary never immediately re-offers,
    because the declaring turn's own prompt is naturally still over the line — so a
    long run can compact repeatedly. Total compaction turns are bounded by the
    per-run cap: the cap reached = no further offers, recorded once on the trace
    (:func:`_record_fillline_cap`). A strict no-op when dormant (not armed), pending,
    or under the threshold — a work item that never fills its context is
    byte-identical to today.
    """
    if not _fillline_armed(ctx):
        return
    over = _fillline.crossed(
        last_prompt_tokens, int(ctx.context_budget), float(ctx.capacity_threshold)
    )
    if ctx._fillline_resolved and not over:
        # The declaration was consumed and the run dropped back under the line —
        # this crossing is spent. Clear the per-crossing cells so the NEXT crossing
        # offers again (clearing ``_fillline_used`` keeps the next decision's
        # recorded reason naming its own crossing's token count).
        ctx._fillline_offered.clear()
        ctx._fillline_resolved.clear()
        ctx._fillline_used.clear()
        return
    if ctx._fillline_offered or not over:
        return
    if _fillline_cap_reached(ctx):
        _record_fillline_cap(ctx)
        return
    _offer_fillline(ctx, last_prompt_tokens)


def _files_read(ctx: _Work) -> int:
    """Count the read-only mapping tool calls so far (``read_file`` + ``list_dir``)."""
    return sum(1 for step in ctx.result.steps if step.tool in ("read_file", "list_dir"))


def _maybe_offer_mapping_fanout(ctx: _Work) -> None:
    """Offer the per-folder fan-out advisory once a wide survey has read many files (#188).

    A strict no-op when dormant (``mapping_fanout_files`` unset / <= 0), already
    offered, or still under the threshold — so a normal task that reads a handful of
    files is byte-identical to today. Backend-judged + advisory: the loop injects ONE
    recommendation pointing at the existing ``subagents`` tool (no new fan-out/merge
    code) and the model decides whether to act. Offered at most once per work item via
    ``_mapping_fanout_offered``. Runtime-owned, so it fires identically for every
    backend (the all-engines rule).
    """
    threshold = ctx.mapping_fanout_files
    if not isinstance(threshold, int) or threshold <= 0:
        return
    if ctx._mapping_fanout_offered:
        return
    files = _files_read(ctx)
    if files <= threshold:
        return
    ctx.messages.append(
        {
            "role": "user",
            "content": _autosplit.build_mapping_fanout_recommendation(
                files_read=files, max_children=MAX_SUBAGENT_FANOUT - 1
            ),
        }
    )
    ctx._mapping_fanout_offered.append(True)


def _distinct_folders_read(ctx: _Work) -> int:
    """Count distinct parent folders among the ``read_file`` steps so far.

    The folder is the repo-relative posix dirname of each read path; a path with
    no ``/`` (a repo-root file) folds to the same ``""`` bucket. Used by the review
    fan-out advisory (#220b) to gauge how many folders the review has spread across.
    """
    folders: set[str] = set()
    for step in ctx.result.steps:
        if step.tool != "read_file":
            continue
        path = step.arguments.get("path")
        if not isinstance(path, str) or not path:
            continue
        folders.add(path.rsplit("/", 1)[0] if "/" in path else "")
    return len(folders)


def _maybe_offer_review_fanout(ctx: _Work) -> None:
    """Offer the per-folder review fan-out advisory once a review spans many folders (#220b).

    A strict no-op when dormant (``review_fanout_folders`` unset / <= 0), already
    offered, or the review has not yet read across more than the threshold of folders
    — so a normal run is byte-identical. Backend-judged + advisory: the loop injects
    ONE recommendation pointing at the existing ``subagents`` tool with the read-only
    ``reviewer`` role (no new fan-out/merge code) and the model decides whether to act.
    Offered at most once per work item via ``_review_fanout_offered``. Runtime-owned,
    so it fires identically for every backend (the all-engines rule).
    """
    threshold = ctx.review_fanout_folders
    if not isinstance(threshold, int) or threshold <= 0:
        return
    if ctx._review_fanout_offered:
        return
    folders = _distinct_folders_read(ctx)
    if folders <= threshold:
        return
    ctx.messages.append(
        {
            "role": "user",
            "content": _autosplit.build_review_fanout_recommendation(
                folders=folders, max_children=MAX_SUBAGENT_FANOUT - 1
            ),
        }
    )
    ctx._review_fanout_offered.append(True)


def _maybe_offer_plan_mode(ctx: _Work) -> None:
    """Offer the plan-mode advisory once, up front, for a complex task (#t8).

    A strict no-op when dormant (``plan_offer_tokens`` unset / <= 0) or already
    offered — so a normal task is byte-identical to today. Backend-judged +
    advisory: the loop injects ONE recommendation pointing at the ``colleague
    plan`` verb and the model decides whether to act. Offered at most once per
    work item. Runtime-owned, so it fires identically for every backend (the
    all-engines rule). Detection lives in :mod:`colleague.plan.trigger`.
    """
    threshold = ctx.plan_offer_tokens
    if not isinstance(threshold, int) or threshold <= 0:
        return
    if ctx._plan_offered:
        return
    from colleague.plan import trigger as _plan_trigger

    if not _plan_trigger.should_offer_plan_mode(
        ctx.task.instruction, already_offered=False, threshold_tokens=threshold
    ):
        return
    ctx.messages.append({"role": "user", "content": _plan_trigger.build_plan_recommendation()})
    ctx._plan_offered.append(True)


def _resolve_fillline(ctx: _Work, resp: ModelResponse, complete: CompleteFn) -> str:
    """Classify + record the model's declaring turn, acting on a compact move (#156).

    Maps the declaring turn to one move: a ``subagents`` call → ``split`` (the
    existing fan-out machinery then runs it), a ``finish`` call →
    ``finish-with-handoff`` (the existing finish path records the continuation
    summary), anything else → ``compact`` (this runs the self-summary now). Returns
    the move kind so the caller knows whether the compact branch already consumed the
    turn.
    """
    tool_names = [tc.name for tc in (resp.tool_calls or [])]
    kind = _fillline.classify_declaration(tool_names)
    _record_fillline_decision(ctx, kind)
    if kind == _fillline.MOVE_COMPACT:
        # Count the compaction turn against the per-run cap (indefinite-run t1)
        # BEFORE running it: a compaction that falls back to lossy windowing (the
        # summary turn overflowed) still spent a model call, so it still counts.
        # Only compact declarations count — split/handoff moves are bounded by
        # their own machinery (subagent caps / the finish path).
        count = ctx._fillline_compactions[0] if ctx._fillline_compactions else 0
        ctx._fillline_compactions[:] = [count + 1]
        _compact_history(ctx, complete)
    return kind


def _consume_fillline_declaration(ctx: _Work, resp: ModelResponse, complete: CompleteFn) -> bool:
    """Resolve a pending fill-line declaration; return whether the loop should ``continue``.

    Returns ``True`` only for a *pure* compact declaration (no tool calls) — the
    history was compacted and the model continues from the summary next turn. For a
    compact-with-tool-calls turn (the model kept working) or a split/finish
    declaration, returns ``False`` so the caller still runs the declaring turn's tool
    calls (they are NOT discarded). A no-op (returns ``False``) when no declaration is
    pending.
    """
    if not (ctx._fillline_offered and not ctx._fillline_resolved):
        return False
    kind = _resolve_fillline(ctx, resp, complete)
    return kind == _fillline.MOVE_COMPACT and not resp.tool_calls
