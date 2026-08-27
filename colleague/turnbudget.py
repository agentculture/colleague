"""Per-turn output budget + microcompaction decisions (adopt-from-qwen-code, plan t16).

Two decisions the loop and the vLLM adapter make on every model turn, kept
out of ``loop.py`` / ``engines/vllm_openai.py`` so both stay under the
file-length ratchet and so the arithmetic is unit-testable on its own:

* **The output-token clamp** (spec c4/h2, c48/h35): every main-loop
  ``/chat/completions`` payload carries ``max_tokens`` =
  :func:`colleague.outputclamp.clamp_output_tokens` (seat ceiling, window,
  last prompt tokens). The window comes from the run-start ``/tokenize``
  probe (:class:`colleague.tokenestimate.TokenEstimator`, t12) — the
  lobes-advertised context wins when present — and falls back to
  ``COLLEAGUE_CONTEXT_BUDGET``. The prompt count is the estimator's
  ``usage``-anchored estimate (turn 1: its exact probe). ``COLLEAGUE_MAX_OUTPUT_TOKENS=0``
  (:func:`colleague.outputclamp.seat_ceiling` → ``None``) omits the key
  entirely — byte-identical to the pre-arc payload.
  A ``finish_reason=length`` turn is retried ONCE with the budget escalated
  toward the seat ceiling (:func:`escalate_on_length`, qwen-code's
  ``geminiChat.ts:1064`` escalate-on-MAX_TOKENS) before the loop's existing
  truncated-turn handling (``TRUNCATED_TURN_MARKER``) takes over.
* **Microcompaction before the fill-line offer** (spec c11/h9): once the last
  reported ``prompt_tokens`` reaches 0.85 of the context budget
  (:func:`colleague.microcompact.should_microcompact`), OLD tool results are
  blanked in place (:func:`colleague.microcompact.microcompact`, no model
  call) BEFORE the model-authored fill-line ``compact`` is offered — which
  then fires only if the history is still over the line afterwards.
  ``COLLEAGUE_MICROCOMPACT=0`` disables the floor (today's path).

The seat vocabulary is :data:`colleague.effort.SEAT_TABLE`'s: a seat builder
that wants the high ceiling stamps a plain ``output_seat`` attribute
(``"deepthink"`` / ``"design"``) on its replaced config; every other config
is the acting seat (``worker`` in three-tier mode, else ``cortex``).

adapted-from: qwen-code packages/core/src/core/tokenLimits.ts:66-77 (the
clamp invariant), core/geminiChat.ts:1064 (escalate on MAX_TOKENS),
services/microcompaction/microcompact.ts (the rule-based floor).
"""

from __future__ import annotations

import os
from typing import Any, Optional

from colleague import microcompact as _microcompact
from colleague import outputclamp
from colleague.context import count_tokens_chars

ENV_MICROCOMPACT = "COLLEAGUE_MICROCOMPACT"
LEDGER_EVENT_KIND = "evidence"  # the closed #411 kind set has no room; evidence is replay-inert
LEDGER_EVENT_SUBJECT = "microcompaction"
WARNING_KIND = "microcompaction"
#: Mirrors ``colleague.config._DEFAULT_CONTEXT_BUDGET`` (pinned equal by a test) —
#: the window floor when neither the probe nor the config names one.
DEFAULT_WINDOW = 131_072


def acting_seat(config: Any) -> str:
    """The :data:`colleague.effort.SEAT_TABLE` seat this config's completions belong to."""
    stamped = getattr(config, "output_seat", None)
    if isinstance(stamped, str) and stamped in outputclamp.SEAT_TABLE:
        return stamped
    return "worker" if getattr(config, "worker", None) is not None else "cortex"


def window_for(config: Any) -> int:
    """The served context window: the run-start probe's answer, else the budget."""
    est = getattr(config, "token_estimator", None)
    window = getattr(est, "window", None)
    if isinstance(window, int) and window > 0:
        return window
    budget = getattr(config, "context_budget_tokens", None)
    return int(budget) if isinstance(budget, int) and budget > 0 else DEFAULT_WINDOW


def prompt_tokens_for(config: Any, messages: list[dict[str, Any]]) -> int:
    """The prompt size the clamp subtracts: the estimator's answer, else chars/4."""
    est = getattr(config, "token_estimator", None)
    if est is not None:
        try:
            return int(est(messages))
        except Exception:  # noqa: BLE001 - a broken estimator never loses the turn
            return count_tokens_chars(messages)
    return count_tokens_chars(messages)


def max_tokens_for(config: Any, messages: list[dict[str, Any]]) -> Optional[int]:
    """``max_tokens`` for this payload, or ``None`` under the kill-switch (omit the key)."""
    ceiling = outputclamp.seat_ceiling(acting_seat(config))
    if ceiling is None:
        return None
    return outputclamp.clamp_output_tokens(
        ceiling, window_for(config), prompt_tokens_for(config, messages)
    )


def escalate_on_length(payload: dict[str, Any], config: Any, resp: Any) -> bool:
    """Raise ``payload["max_tokens"]`` toward the seat ceiling after a ``length`` cut.

    Returns ``True`` (and mutates *payload*) exactly when a retry is worth it:
    the turn ended ``finish_reason=length``, the payload was clamped, and the
    window still has room above the clamped value — the retry drops the
    safety margin (``window - prompt``, with ``prompt`` the cut turn's EXACT
    ``usage.prompt_tokens``) but never exceeds the seat ceiling or the window.
    ``False`` when the clamp already sat at the ceiling / the window edge, so a
    second identical request is never sent.
    """
    if getattr(resp, "finish_reason", "") != "length" or "max_tokens" not in payload:
        return False
    ceiling = outputclamp.seat_ceiling(acting_seat(config))
    if ceiling is None:
        return False
    prompt = int(getattr(resp, "prompt_tokens", 0) or 0)
    room = window_for(config) - prompt
    escalated = min(ceiling, room)
    if escalated <= int(payload["max_tokens"]):
        return False
    payload["max_tokens"] = escalated
    return True


def microcompact_enabled() -> bool:
    """``COLLEAGUE_MICROCOMPACT=0`` (or ``false``/``off``/``no``) disables the floor."""
    raw = os.environ.get(ENV_MICROCOMPACT, "").strip().lower()
    return raw not in {"0", "false", "off", "no"}


def blank_old_results(
    messages: list[dict[str, Any]], last_prompt_tokens: int, budget: Optional[int]
) -> tuple[int, list[int]]:
    """Blank old tool results IN PLACE when due; return ``(blanked, step_indices)``.

    Due = the floor is enabled, a positive budget is set, and the last reported
    prompt reached 0.85 of it. ``step_indices`` are the ordinals of the blanked
    ``tool``-role messages — one tool message is appended per recorded
    :class:`colleague.contract.Step`, in order, so the ordinal IS the step
    index (batched tool calls keep request order, plan t15). ``(0, [])`` when
    nothing was due or nothing was old enough to blank.
    """
    if not microcompact_enabled() or not budget or budget <= 0:
        return 0, []
    if not _microcompact.should_microcompact(last_prompt_tokens, int(budget)):
        return 0, []
    blanked, _replaced = _microcompact.microcompact(messages)
    # Count only results whose content actually changed: a marker left by an
    # earlier pass is "replaced" again by microcompact but blanks nothing new.
    indices: list[int] = []
    ordinal = 0
    for before, after in zip(messages, blanked):
        if before.get("role") == "tool":
            if before.get("content") != after.get("content"):
                indices.append(ordinal)
            ordinal += 1
    if not indices:
        return 0, []
    messages[:] = blanked
    return len(indices), indices


def microcompact_turn(
    messages: list[dict[str, Any]],
    last_prompt_tokens: int,
    budget: Optional[int],
    result: Any,
    agents: Any,
    count_tokens: Any,
) -> int:
    """One loop-boundary pass: blank when due, record it, re-estimate the prompt.

    Records each pass as a ``microcompaction`` warning on *result* (the
    artifact) and — agents armed — as one ledger event; returns
    ``count_tokens(messages)`` (the engine's usage-anchored estimator) after a
    blanking so the fill-line offer that follows sees the SMALLER history, or
    *last_prompt_tokens* unchanged when nothing was blanked. Bookkeeping
    failures never lose the turn.
    """
    count, indices = blank_old_results(messages, last_prompt_tokens, budget)
    if not count:
        return last_prompt_tokens
    warnings = result.warnings
    prior = sum(int(w.get("blanked", 0)) for w in warnings if w.get("kind") == WARNING_KIND)
    warnings.append(blanking_warning(count, indices, prior + count))
    try:
        ledger_blanking(agents, count, indices)
    except Exception:  # noqa: BLE001 - bookkeeping never loses the turn
        warnings.append({"kind": "microcompaction-ledger-failed", "blanked": count})
    if callable(count_tokens):
        try:
            return int(count_tokens(messages))
        except Exception:  # noqa: BLE001
            return last_prompt_tokens
    return last_prompt_tokens


def blanking_warning(count: int, indices: list[int], total: int) -> dict[str, Any]:
    """The artifact record of one blanking pass (``TaskResult.warnings`` entry)."""
    return {
        "kind": WARNING_KIND,
        "blanked": count,
        "blanked_total": total,
        "step_indices": list(indices),
        "keep_recent": _microcompact.DEFAULT_KEEP_RECENT,
    }


def ledger_blanking(agents: Any, count: int, indices: list[int]) -> bool:
    """Append ONE ``evidence`` ledger event (subject ``microcompaction``) when armed.

    The #411 task ledger's event-kind set is CLOSED (sixteen kinds, pinned), so
    the pass rides the replay-inert ``evidence`` kind with ``subject`` naming
    it. The event carries the count, the blanked step indices and ``keep_recent``
    — enough for :func:`rehydrate_blanking` to reproduce the blanked history
    from the original messages, so the ledger digest and the reconstruction
    manifest stay truthful about what the model saw (spec c42/h31). Returns
    ``True`` when an event was appended; ``False`` when unarmed (no ledger).
    """
    ledger = getattr(agents, "ledger", None)
    if ledger is None:
        return False
    ledger.append(
        LEDGER_EVENT_KIND,
        {
            "subject": LEDGER_EVENT_SUBJECT,
            "count": count,
            "step_indices": list(indices),
            "keep_recent": _microcompact.DEFAULT_KEEP_RECENT,
        },
    )
    return True


def rehydrate_blanking(
    messages: list[dict[str, Any]], event_data: dict[str, Any]
) -> list[dict[str, Any]]:
    """Reproduce a recorded blanking pass over *messages* (the pre-blanking history)."""
    keep = int(event_data.get("keep_recent", _microcompact.DEFAULT_KEEP_RECENT))
    blanked, _count = _microcompact.microcompact(messages, keep_recent=keep)
    return blanked
