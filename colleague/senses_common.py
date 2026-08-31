"""Shared plumbing for the senses invocation layer (:mod:`colleague.senses`).

Split out of ``colleague/senses.py`` (fl-t6, hard-1000-line-file-limit) to
keep that module under the 1000-line ceiling. Pure computation — text
windowing, history folding, exact token metering, and best-effort field
coercion — with NO model/engine/network surface of its own; every name here
is re-exported from :mod:`colleague.senses` (and imported directly by
:mod:`colleague.senses_loop`) so callers see no difference from before the
split.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

#: Appended to a prompt truncated to fit the senses model's send budget — a
#: visible marker so whoever reads the digest knows content was cut (mirrors
#: :data:`colleague.deepthink._TRUNCATION_NOTE`). Only the prompt SENT to the
#: senses model is ever truncated; ``ContextPacket.original`` always carries the
#: caller's full verbatim input regardless.
_TRUNCATION_NOTE = "[senses digest truncated to fit budget]"

#: The grounding clause (structural senses relay fidelity, three-tier-execution
#: arc, task t2): composed into every prompt-bearing senses surface (every
#: system prompt in :mod:`colleague.senses` plus
#: :data:`colleague.senses_loop._LOOP_SYSTEM_PROMPT`) so the model is told, in
#: every call, that its view is bounded to exactly what this prompt hands it —
#: never the wider run, never its own general knowledge, as if it had eyes on
#: anything else.
_GROUNDING_CLAUSE = (
    "You can see only the status block you are given below — nothing else about the run."
)

#: The fidelity clause (task t2): composed alongside :data:`_GROUNDING_CLAUSE`
#: into every prompt-bearing senses surface. Names the exact failure this arc
#: guards against structurally (in code, via
#: :func:`colleague.senses._enforce_fidelity` /
#: :func:`colleague.senses._repeats_background` — this clause is prompt
#: hygiene, never the sole guarantee): a live embodiment session once had
#: senses recite its background "knowledge" block on 6 of 6 turns instead of
#: relaying the current answer.
_FIDELITY_CLAUSE = (
    "Answer the current message from the current result first; background "
    "knowledge never replaces it."
)


def _window_text(
    text: str,
    *,
    system_prompt: str,
    budget: int,
    count_tokens: "Callable[[list[dict[str, Any]]], int]",
) -> str:
    """Return *text* truncated so ``[system, user=text]`` fits the send budget.

    Mirrors :func:`colleague.deepthink.window_messages`' arithmetic: reserve one
    quarter of *budget* for the completion, so the prompt must measure at or
    under ``budget - budget // 4``. A prompt that already fits passes through
    byte-identical. Otherwise the user text is binary-searched down (bounded
    number of ``count_tokens`` calls) with :data:`_TRUNCATION_NOTE` appended so
    the cut is always visible. The senses model's OWN counter/budget are used
    (the caller passes ``engine.make_count_tokens(senses_config)`` and
    ``senses_config.context_budget_tokens``).
    """
    reserve = max(1, budget // 4)
    send_budget = max(1, budget - reserve)

    def _messages(body: str) -> "list[dict[str, Any]]":
        msgs: "list[dict[str, Any]]" = []
        if system_prompt:
            msgs.append({"role": "system", "content": system_prompt})
        msgs.append({"role": "user", "content": body})
        return msgs

    if count_tokens(_messages(text)) <= send_budget:
        return text

    lo, hi = 0, len(text)
    best = _TRUNCATION_NOTE
    while lo <= hi:
        mid = (lo + hi) // 2
        prefix = text[:mid]
        candidate = f"{prefix}\n\n{_TRUNCATION_NOTE}" if prefix else _TRUNCATION_NOTE
        if count_tokens(_messages(candidate)) <= send_budget:
            best = candidate
            lo = mid + 1
        else:
            hi = mid - 1
    return best


#: The only two valid ``role`` values on a history entry (talking-to-one arc,
#: task t4) — the session-side rolling record of prior senses exchanges.
_VALID_HISTORY_ROLES = ("operator", "senses")


def _history_lines(history: "Optional[list[dict[str, str]]]") -> "list[str]":
    """Format *history* into ordered ``"role: text"`` lines (oldest first).

    Defensive, never raises: an entry that is not a ``dict``, carries a
    ``role`` other than ``"operator"``/``"senses"``, or has a missing/blank/
    non-string ``text`` is silently skipped — a malformed history entry never
    breaks a senses call. ``history`` being ``None`` or empty returns ``[]``,
    the caller's byte-identical no-history signal.
    """
    if not history:
        return []
    lines: "list[str]" = []
    for entry in history:
        if not isinstance(entry, dict):
            continue
        role = entry.get("role")
        if role not in _VALID_HISTORY_ROLES:
            continue
        text = entry.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        lines.append(f"{role}: {text.strip()}")
    return lines


#: The label prefixing a folded history block (task t2): explicitly names it
#: as OPTIONAL BACKGROUND, never authoritative for the current turn — the
#: knowledge-entries-labeled-and-ordered half of the structural fidelity fix
#: (the other half is :func:`colleague.senses._enforce_fidelity`'s code-level
#: containment check). Kept in exactly ONE place so every prompt-bearing
#: senses surface that folds history (every invocation function plus the
#: senses coordination loop) gets the SAME label, never a re-typed variant.
_BACKGROUND_LABEL = "Optional background (may not relate to the current message):"


def _fold_history(
    primary_body: str,
    history: "Optional[list[dict[str, str]]]",
    *,
    system_prompt: str,
    budget: int,
    count_tokens: "Callable[[list[dict[str, Any]]], int]",
) -> str:
    """Prefix *primary_body* with a windowed, labeled background block (t4/t2).

    Folds *history* (oldest first) into a clearly-delimited block, headed
    :data:`_BACKGROUND_LABEL`, placed BEFORE *primary_body* — the caller's
    already-assembled request/feed/summary payload — so the model reads
    prior exchanges before the current turn, but is told plainly that they
    are optional background, not a substitute for answering the current
    message (structural senses relay fidelity, task t2). Participates in the
    SAME budget accounting as :func:`_window_text` (identical
    quarter-of-budget completion reserve): when the combined ``[system,
    user=block+primary_body]`` prompt would exceed the send budget, the
    OLDEST history entries are dropped first (whole entries, never sliced
    mid-entry) until it fits.

    *primary_body* is NEVER trimmed here — callers window it via
    :func:`_window_text` first, so it already fits the send budget alone;
    dropping every history entry always recovers that guarantee (the
    function's existing payload always wins over history).

    Returns *primary_body* completely UNCHANGED when *history* is ``None``,
    empty, or every entry is defensively skipped by :func:`_history_lines` —
    the byte-identical no-history path pinned by the existing senses tests.
    """
    lines = _history_lines(history)
    if not lines:
        return primary_body

    reserve = max(1, budget // 4)
    send_budget = max(1, budget - reserve)

    def _messages(body: str) -> "list[dict[str, Any]]":
        msgs: "list[dict[str, Any]]" = []
        if system_prompt:
            msgs.append({"role": "system", "content": system_prompt})
        msgs.append({"role": "user", "content": body})
        return msgs

    def _combine(remaining: "list[str]") -> str:
        if not remaining:
            return primary_body
        block = f"{_BACKGROUND_LABEL}\n" + "\n".join(remaining)
        return f"{block}\n\n{primary_body}"

    remaining = list(lines)
    candidate = _combine(remaining)
    while remaining and count_tokens(_messages(candidate)) > send_budget:
        remaining = remaining[1:]  # drop the OLDEST entry first.
        candidate = _combine(remaining)
    return candidate


class _TokenMeter:
    """Accumulates exact prompt+completion tokens across a call's completions.

    :func:`colleague.plan.cli_driver.robust_simple_complete` may issue more than
    one completion (an empty-content follow-up turn), so tokens are SUMMED
    across every completion the invocation actually paid for. Tokens are read
    verbatim from each response's ``prompt_tokens``/``completion_tokens`` —
    never estimated (the token-honesty rule; the senses-side mirror of
    :func:`colleague.deepthink._call_tokens`). ``value`` is ``None`` until at
    least one completion is seen, so a degraded call (which never reached the
    wire) records ``tokens=None``.
    """

    def __init__(self) -> None:
        self._total = 0
        self._seen = False

    def wrap(
        self, complete: "Callable[[list[dict[str, Any]]], Any]"
    ) -> "Callable[[list[dict[str, Any]]], Any]":
        def recording(messages: "list[dict[str, Any]]") -> Any:
            response = complete(messages)
            prompt = getattr(response, "prompt_tokens", 0) or 0
            completion = getattr(response, "completion_tokens", 0) or 0
            self._total += int(prompt) + int(completion)
            self._seen = True
            return response

        return recording

    @property
    def value(self) -> Optional[int]:
        return self._total if self._seen else None


def _coerce_confidence(value: Any) -> float:
    """Best-effort float coercion for the model's ``confidence`` (default 0.0).

    Mirrors :meth:`colleague.contract.ContextPacket.from_dict`'s handling — a
    value that cannot be parsed as ``float`` (e.g. the model wrote ``"high"``)
    degrades to ``0.0`` rather than raising, since a bad confidence is
    advisory, not fatal.
    """
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _coerce_omissions(value: Any) -> list[str]:
    """Coerce the model's ``omissions`` into a list of short strings.

    A list/tuple becomes ``[str(x) for x in value]``; a bare string becomes a
    single-element list; anything else (``None``, a number, a dict) becomes
    ``[]`` — tolerant of model hallucination, never a crash.
    """
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(x) for x in value]
    return []


#: Hard cap on ``ContextPacket.ack`` length (talking-to-one arc, task t1). A
#: one/two-sentence acknowledgment never needs more; an over-long reply is
#: hard-truncated in place — never a second completion, never invented filler.
_MAX_ACK_LEN = 500


def _coerce_ack(value: Any) -> Optional[str]:
    """Best-effort extraction of the model's ``ack`` field (task t1).

    A non-empty string is stripped of surrounding whitespace and hard-capped to
    :data:`_MAX_ACK_LEN` characters. Anything else — missing, ``None``, an
    empty/whitespace-only string, or a non-string value (a number, list, dict)
    from a hallucinating model — degrades to ``None``: a reply with no usable
    ack is simply absent, never fabricated.
    """
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return stripped[:_MAX_ACK_LEN]
