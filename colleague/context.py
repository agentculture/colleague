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

# ---------------------------------------------------------------------------
# Public constant
# ---------------------------------------------------------------------------

_PLACEHOLDER_TEXT = "[earlier steps elided to fit the context budget]"


# ---------------------------------------------------------------------------
# count_tokens_chars
# ---------------------------------------------------------------------------


def count_tokens_chars(messages: list[dict]) -> int:
    """Estimate tokens from character count (chars / 4, minimum 1 if any text).

    Sums the ``content`` string of every message plus the ``name`` and
    ``arguments`` text of every function in any ``tool_calls`` list, then
    divides by 4 (integer division).  Returns 0 for an empty/contentless list,
    and at least 1 when any text is found.
    """
    total = 0
    for m in messages:
        content = m.get("content")
        if content:
            total += len(content)
        for tc in m.get("tool_calls") or []:
            fn = tc.get("function") or {}
            name = fn.get("name") or ""
            args = fn.get("arguments") or ""
            total += len(name) + len(args)
    if total == 0:
        return 0
    return max(1, total // 4)


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
        total += len(m.get("content") or "")
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
    - When ``count_tokens`` is ``None``, :func:`count_tokens_chars` is used.
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
    - At most a small constant number of ``count_tokens`` calls are made
      (one initial check + one estimate + one or two verification calls —
      never a per-segment loop of calls).
    - If nothing can be dropped and the list is still over budget, the
      minimal valid list (head + whatever tail fits) is returned.

    OpenAI validity is maintained: no assistant ``tool_calls`` turn without
    its matching tool replies, and no orphan ``tool`` message.
    """
    _count = count_tokens if count_tokens is not None else count_tokens_chars

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


def classify_degradable(text: str) -> str | None:
    """Classify a degradable engine error: 'overflow', 'timeout', or None for neither.

    Overflow takes precedence over timeout.
    """
    if is_context_overflow(text):
        return "overflow"
    if is_request_timeout(text):
        return "timeout"
    return None
