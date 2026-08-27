"""Context-window management primitives for the agentic loop.

Provides three public functions:

- :func:`count_tokens_chars` — zero-dependency heuristic token estimator
  (characters / 4, minimum 1 when any text is present).
- :func:`window_messages` — trim a growing OpenAI-format message list to a
  token budget, preserving the system prompt and first user message, dropping
  the oldest droppable history as matched units (assistant-tool_calls +
  tool replies), inserting a single placeholder note, and keeping the most
  recent turns.
- :func:`is_context_overflow` — detect context-overflow error phrases from
  OpenAI-compatible servers via case-insensitive substring match.

All stdlib only — zero runtime dependencies.
"""

from __future__ import annotations

from typing import Callable

from colleague.media import IMAGE_TOKEN_ESTIMATE, flatten_parts

# ---------------------------------------------------------------------------
# Public constant
# ---------------------------------------------------------------------------

_PLACEHOLDER_TEXT = "[earlier steps elided to fit the context budget]"


# ---------------------------------------------------------------------------
# count_tokens_chars
# ---------------------------------------------------------------------------


def _content_chars(content) -> int:
    """Char-equivalent size of a message ``content`` (str or parts list, t6).

    A media part charges ``IMAGE_TOKEN_ESTIMATE * 4`` chars — the token
    estimate expressed in the same chars/4 currency the heuristic divides by —
    so a parts message is never sized ``len(list)`` (the part COUNT, the bug
    the t4 report named) and never zero.
    """
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        total = 0
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "text":
                total += len(part.get("text") or "")
            else:
                total += IMAGE_TOKEN_ESTIMATE * 4
        return total
    return 0


def count_tokens_chars(messages: list[dict]) -> int:
    """Estimate tokens from character count (chars / 4, minimum 1 if any text).

    Sums the ``content`` of every message (str, or a parts list sized via
    :func:`_content_chars` — text parts by length, media parts at the
    per-image estimate) plus the ``name`` and ``arguments`` text of every
    function in any ``tool_calls`` list, then divides by 4 (integer
    division).  Returns 0 for an empty/contentless list, and at least 1 when
    any text is found.
    """
    total = 0
    for m in messages:
        total += _content_chars(m.get("content"))
        for tc in m.get("tool_calls") or []:
            fn = tc.get("function") or {}
            name = fn.get("name") or ""
            args = fn.get("arguments") or ""
            total += len(name) + len(args)
    if total == 0:
        return 0
    return max(1, total // 4)


def media_aware_count(
    messages: list[dict],
    count_tokens: Callable[[list[dict]], int] | None,
) -> int:
    """Count *messages* with an exact counter that cannot see media parts (t6).

    ``count_tokens`` is the engine's exact counter (e.g. the vLLM ``/tokenize``
    closure) — a text endpoint that cannot tokenize an image part. A
    string-only history passes through UNTOUCHED (the original list object, so
    the media-less path stays zero-overhead and byte-identical). A
    parts-bearing history is counted as: exact count of a text-flattened copy
    (:func:`colleague.media.flatten_parts` — media parts become short
    placeholders) **plus** ``IMAGE_TOKEN_ESTIMATE`` per media part. The
    estimate is deliberately additive-conservative (the placeholder text also
    costs a few tokens): over-counting shrinks the window slightly, never
    overflows it. With ``count_tokens=None`` this is exactly
    :func:`count_tokens_chars` (itself part-aware).
    """
    if count_tokens is None:
        return count_tokens_chars(messages)
    media_parts = 0
    for m in messages:
        content = m.get("content")
        if isinstance(content, list):
            media_parts += sum(
                1 for part in content if isinstance(part, dict) and part.get("type") != "text"
            )
    if media_parts == 0 and not any(isinstance(m.get("content"), list) for m in messages):
        return count_tokens(messages)
    flattened = [
        dict(m, content=flatten_parts(m["content"])) if isinstance(m.get("content"), list) else m
        for m in messages
    ]
    return count_tokens(flattened) + IMAGE_TOKEN_ESTIMATE * media_parts


# ---------------------------------------------------------------------------
# _build_droppable_segments
# ---------------------------------------------------------------------------


def _build_droppable_segments(messages: list[dict]) -> list[list[dict]]:
    """Partition the *droppable* portion of the history into segments.

    The droppable portion is ``messages[2:]`` (everything after the mandatory
    system prompt at index 0 and the first user/task message at index 1), minus
    the final message (most-recent tail we always want to keep first).

    Segments are returned oldest-first.  Each segment is either:

    - A single non-tool message (plain assistant text, standalone tool result
      that has no pairing — though validity requires pairing, we handle it
      gracefully).
    - A matched pair: [assistant-with-tool_calls, …tool-reply messages].

    The caller drops segments from the front (oldest) until under budget.
    """
    if len(messages) <= 2:
        return []

    # Everything from index 2 onward is potentially droppable.
    # We preserve the very last element of `messages` as the most-recent tail
    # anchor (the loop always wants to keep at least one recent turn).
    # However, we build segments over the full droppable range and let
    # window_messages decide how far back to cut.
    droppable = messages[2:]

    segments: list[list[dict]] = []
    i = 0
    while i < len(droppable):
        m = droppable[i]
        role = m.get("role")
        tool_calls = m.get("tool_calls")

        if role == "assistant" and tool_calls:
            # Collect all matching tool-reply messages that immediately follow.
            expected_ids = {tc["id"] for tc in tool_calls}
            group = [m]
            j = i + 1
            while j < len(droppable) and droppable[j].get("role") == "tool":
                tid = droppable[j].get("tool_call_id", "")
                if tid in expected_ids:
                    group.append(droppable[j])
                    expected_ids.discard(tid)
                    j += 1
                else:
                    break
            segments.append(group)
            i = j
        else:
            segments.append([m])
            i += 1

    return segments


# ---------------------------------------------------------------------------
# window_messages (+ helpers)
# ---------------------------------------------------------------------------


def _seg_chars(seg: list[dict]) -> int:
    """Approximate character size of one segment (content + tool_call text)."""
    total = 0
    for m in seg:
        total += _content_chars(m.get("content"))
        for tc in m.get("tool_calls") or []:
            fn = tc.get("function") or {}
            total += len(fn.get("name") or "") + len(fn.get("arguments") or "")
    return total


def _proportional_cut(seg_sizes: list[int], chars_to_drop: int, max_drop: int) -> int:
    """Pick how many leading segments to drop to shed ~*chars_to_drop* chars.

    Single pass over segment sizes (no ``count_tokens`` calls); never drops the
    last segment (``cut <= max_drop``), so the most-recent turn is always kept.
    """
    dropped_chars = 0
    cut = 0
    while cut < max_drop and dropped_chars < chars_to_drop:
        dropped_chars += seg_sizes[cut]
        cut += 1
    return cut


def _drop_until_fit(
    head: list[dict],
    segments: list[list[dict]],
    start_cut: int,
    budget_tokens: int,
    count: Callable[[list[dict]], int],
) -> list[dict]:
    """Drop leading segments from *start_cut* onward until the candidate fits.

    Verifies with ``count`` at each cut (the only place this function calls it).
    Returns as soon as a candidate fits or the last segment is reached — so the
    minimal valid list (head + placeholder + most-recent segment) is the floor.
    """
    placeholder = {"role": "user", "content": _PLACEHOLDER_TEXT}
    max_drop = len(segments) - 1  # never drop the very last (most-recent) segment
    cut = start_cut
    while True:
        tail = [m for seg in segments[cut:] for m in seg]
        candidate = head + [placeholder] + tail
        if cut >= max_drop or count(candidate) <= budget_tokens:
            return candidate
        cut += 1


def window_messages(
    messages: list[dict],
    budget_tokens: int,
    count_tokens: Callable[[list[dict]], int] | None = None,
) -> list[dict]:
    """Return a trimmed copy of *messages* that fits within *budget_tokens*.

    Rules
    -----
    - ``count_tokens`` is the engine's :class:`colleague.tokenestimate.TokenEstimator`
      (a ``usage``-anchored estimate, adapted-from qwen-code
      services/tokenEstimation.ts; t12) or :func:`count_tokens_chars` when ``None``.
    - If the list already fits, it is returned unchanged (no copy overhead).
    - Otherwise the oldest droppable history is dropped in matched units:
      an assistant turn with ``tool_calls`` plus all its tool replies form
      one indivisible unit; a plain assistant text turn or lone tool message
      is a unit on its own.
    - The system message (``messages[0]``) and the first ``user`` message
      are always preserved.
    - The most-recent turns are retained.
    - Exactly one placeholder message ``{"role":"user","content":"[earlier
      steps elided to fit the context budget]"}`` is inserted after the
      preserved head and before the retained tail.
    - At most a small constant number of ``count_tokens`` calls are made (one
      check + one estimate + one or two verifications — never a per-segment loop).
    - If nothing can be dropped and still over budget: head + whatever tail fits.

    OpenAI validity is maintained: no assistant ``tool_calls`` turn without
    its matching tool replies, and no orphan ``tool`` message.
    """

    # Media-aware counting (t6): the exact counter gets a text-flattened copy
    # plus the per-media estimate; a string-only history passes through
    # untouched (and count_tokens_chars is itself part-aware).
    def _count(msgs: list[dict]) -> int:
        return media_aware_count(msgs, count_tokens)

    # Call 1: check if already under budget.
    if _count(messages) <= budget_tokens:
        return messages

    head = messages[:2]  # system + first user (always kept)
    segments = _build_droppable_segments(messages)
    if not segments:
        # Nothing droppable — return minimal list as-is.
        return list(messages)

    # Call 2: measure the overage, then estimate the cut point in one pass
    # (reverse the heuristic: tokens * 4 ≈ chars) so we avoid a per-segment
    # count_tokens loop.
    overage = _count(messages) - budget_tokens
    seg_sizes = [_seg_chars(s) for s in segments]
    max_drop = len(segments) - 1
    start_cut = _proportional_cut(seg_sizes, overage * 4, max_drop)

    # Calls 3+ (bounded): verify the candidate and drop more if still over.
    return _drop_until_fit(head, segments, start_cut, budget_tokens, _count)


def is_media_rejection(text: str) -> bool:
    """Detect an endpoint refusing media content parts outright (t9, spec c7).

    A text-only served model does not silently drop an image part the way the
    rig drops audio — it REJECTS the request (live probe 2026-07-02 against
    the served 27B: ``HTTP 400: At most 0 image(s) may be provided in one
    prompt``). The loop degrades this honestly: flatten the parts to
    placeholders, retry text-only once, record the media dropped — never a
    hard-failed run for an attachment the model cannot take (the c7
    degradation half). Conservative match: a media word plus a
    capability-refusal phrase; a context overflow or timeout never matches.
    """
    t = text.lower()
    if "image" not in t and "audio" not in t:
        return False
    return (
        "at most 0" in t
        or "does not support" in t
        or "not enabled" in t
        or "no image processor" in t
    )


# ---------------------------------------------------------------------------
# is_context_overflow
# ---------------------------------------------------------------------------

_OVERFLOW_PHRASES = (
    "maximum context length",
    "context window",
    "too many tokens",
    "reduce the length",
    "context_length_exceeded",
    "longer than the maximum",
)

_TIMEOUT_PHRASES = ("timed out",)


def is_context_overflow(text: str) -> bool:
    """Return True if *text* contains a known context-overflow error phrase.

    Case-insensitive substring match against a fixed set of phrases emitted by
    OpenAI-compatible servers when the prompt exceeds the model's context limit.
    Returns False for empty / ``None``-like input and for unrelated error text.
    """
    if not text:
        return False
    lower = text.lower()
    return any(phrase in lower for phrase in _OVERFLOW_PHRASES)


def is_request_timeout(text: str) -> bool:
    """Return True if *text* contains a known request-timeout error phrase.

    Case-insensitive substring match against a fixed set of phrases emitted by
    servers when a request times out (e.g. a server that "timed out").
    Returns False for empty / ``None``-like input and for unrelated error text.
    """
    if not text:
        return False
    lower = text.lower()
    return any(phrase in lower for phrase in _TIMEOUT_PHRASES)


# A model turn that returned EMPTY content, no tool calls and finish_reason="length"
# (#405 §3 / #411 t8): the output budget was consumed (on a reasoning-heavy
# checkpoint, by reasoning) before any answer — a truncation, not a valid empty
# answer. The loop raises this marker through the SAME degradable classification
# the error-text signals use, so the bounded shrink-and-retry lane handles it.
TRUNCATED_TURN_MARKER = "truncated turn: empty content with finish_reason=length"


class TruncatedTurn(Exception):
    """Internal signal for an empty-content ``finish_reason=length`` turn (#411 t8)."""

    def __init__(self) -> None:
        super().__init__(TRUNCATED_TURN_MARKER)


def is_truncated_turn(text: str) -> bool:
    """Does *text* carry the truncated-turn marker (see :data:`TRUNCATED_TURN_MARKER`)?"""
    return TRUNCATED_TURN_MARKER in text


def classify_degradable(text: str) -> str | None:
    """Classify a degradable engine error: 'overflow', 'timeout', 'truncated', or None.

    Overflow takes precedence over timeout; the truncated-turn marker (#411 t8) is
    its own signal — retried on the overflow cap, since each attempt is cheap.
    """
    if is_context_overflow(text):
        return "overflow"
    if is_request_timeout(text):
        return "timeout"
    if is_truncated_turn(text):
        return "truncated"
    return None
