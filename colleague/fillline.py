"""Pure fill-line helpers — the proactive capacity-decision primitives (#156).

When the running context crosses a fill-line threshold (a fraction of the context
budget), the loop asks the backend to declare ONE opinionated move and acts on it:

- ``compact`` — summarize the working history to itself, replacing the elided turns
  with a model-authored summary (the new v1 capability; lossy windowing remains the
  fallback floor when the summary turn itself cannot fit).
- ``split`` — fan the work out to child instances via the existing ``subagents`` tool.
- ``finish-with-handoff`` — stop and hand the caller a continuation summary.

This module owns only the *pure* pieces (threshold maths, the decision-prompt text,
the declaration classifier, and the compaction request/apply transforms). The loop
(`colleague/loop.py`) owns the firing, the model calls, and recording the decision —
so every backend inherits the behaviour identically (the all-engines rule). All
stdlib only — zero runtime dependencies; no subprocess, threading, sockets, or network.
"""

from __future__ import annotations

from typing import Callable, Optional

from colleague.context import window_messages

__all__ = [
    "DEFAULT_THRESHOLD",
    "MOVE_COMPACT",
    "MOVE_SPLIT",
    "MOVE_HANDOFF",
    "armed",
    "crossed",
    "build_decision_prompt",
    "classify_declaration",
    "build_compaction_request",
    "apply_compaction",
]

# Fraction of the context budget at which the fill-line decision is offered.
# 0.8 leaves headroom for the decision prompt + the model's declaring turn before a
# hard overflow. Tunable per environment via COLLEAGUE_FILLLINE_THRESHOLD.
DEFAULT_THRESHOLD = 0.8

MOVE_COMPACT = "compact"
MOVE_SPLIT = "split"
MOVE_HANDOFF = "finish-with-handoff"

# The summarization instruction sent over the windowed history on the compact branch.
_COMPACTION_INSTRUCTION = (
    "You are running low on context. Summarize everything done so far in this work "
    "item — decisions made, files read/edited, what is known, and what remains — as a "
    "compact, self-contained note you can continue from. Write ONLY the summary; do "
    "not call any tool."
)

_COMPACTION_PREFIX = "[Compacted summary of earlier work in this work item]\n"


def armed(context_budget: Optional[int], threshold: Optional[float]) -> bool:
    """True when the fill-line decision is armed for this work item.

    Armed iff degradation is active (a positive ``context_budget``) AND a usable
    threshold fraction in ``(0, 1]`` is configured. Dormant (``False``) otherwise —
    a strict no-op identical to the pre-feature loop.
    """
    return (
        isinstance(context_budget, int)
        and context_budget > 0
        and isinstance(threshold, (int, float))
        and 0 < threshold <= 1
    )


def crossed(prompt_tokens: int, context_budget: int, threshold: float) -> bool:
    """True when the last turn's prompt token count crosses the fill-line threshold."""
    return prompt_tokens >= threshold * context_budget


def build_decision_prompt(
    *,
    used_tokens: int,
    budget_tokens: int,
    per_child_budget_tokens: int,
    max_children: int,
) -> str:
    """Render the ONE structured fill-line decision prompt (deterministic).

    Names the three moves and the concrete capacity numbers, and tells the model how
    to declare each move by its NEXT action so the runtime can record + act on it. No
    randomness, no timestamps.
    """
    return (
        f"Context check: this work item is now using about {used_tokens} of "
        f"{budget_tokens} budgeted context tokens — past the fill line. To keep "
        f"making durable progress instead of silently losing older context, declare "
        f"ONE move by your next action:\n"
        f"  - COMPACT: reply WITHOUT calling any tool. The runtime will summarize the "
        f"work so far into a compact note and you continue from it.\n"
        f"  - SPLIT: call the `subagents` tool to fan the remaining work out into at "
        f"most {max_children} coherent child assignments (per-child budget: "
        f"{per_child_budget_tokens} tokens).\n"
        f"  - FINISH-WITH-HANDOFF: call `finish` with a continuation summary (what is "
        f"done / what remains) so the caller can resume.\n"
        f"This is advisory — pick the move that best fits the remaining work."
    )


def classify_declaration(tool_names: list[str]) -> str:
    """Classify the model's declaring turn into one of the three moves.

    A ``subagents``/``subagent`` call declares SPLIT; a ``finish`` call declares
    FINISH-WITH-HANDOFF; anything else (a no-tool reply, or a plain working tool call)
    declares COMPACT — the default "summarize and keep going".
    """
    names = set(tool_names)
    if names & {"subagents", "subagent"}:
        return MOVE_SPLIT
    if "finish" in names:
        return MOVE_HANDOFF
    return MOVE_COMPACT


def build_compaction_request(
    messages: list[dict],
    budget_tokens: int,
    count_tokens: Optional[Callable[[list[dict]], int]] = None,
) -> list[dict]:
    """Build the windowed message list to send for the self-summary (compact branch).

    The history is windowed to the budget first (so the summarization call itself has
    room), then a final user turn carries the summarization instruction. The original
    assignment in ``messages[:2]`` is always preserved by :func:`window_messages`.
    """
    windowed = window_messages(messages, budget_tokens, count_tokens)
    return windowed + [{"role": "user", "content": _COMPACTION_INSTRUCTION}]


def apply_compaction(messages: list[dict], summary: str) -> list[dict]:
    """Replace the working history with the model-authored *summary*.

    Keeps the preserved head (``messages[:2]`` — system prompt + original assignment)
    verbatim and replaces everything after it with a single user message holding the
    summary. The result is always OpenAI-valid (no orphan tool messages): a finish /
    split / further work turn then proceeds from head + summary.
    """
    head = messages[:2]
    text = (summary or "").strip() or "(no summary produced)"
    return head + [{"role": "user", "content": _COMPACTION_PREFIX + text}]
