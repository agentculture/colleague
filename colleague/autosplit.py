"""Pure autosplit helpers — estimate, split count, and recommendation builders.

Four public functions (plus ``__all__``) used by the loop when an assignment
is judged too large for one context window:

- :func:`estimate_instruction_tokens` — coarse up-front token estimate of the
  task instruction text.
- :func:`child_count` — number of child hand-over assignments for a split;
  thin pass-through to :func:`colleague.config.autosplit_children`.
- :func:`build_split_recommendation` — structured REACTIVE message body injected
  after context overflow cannot be recovered.
- :func:`build_upfront_hint` — softer ADVISORY message body used before the loop
  when the up-front estimate already looks too large.

All stdlib only — zero runtime dependencies; no subprocess, threading, sockets,
or network calls.
"""

from __future__ import annotations

from typing import Callable, Optional

from colleague.config import autosplit_children
from colleague.context import count_tokens_chars

__all__ = [
    "estimate_instruction_tokens",
    "child_count",
    "build_split_recommendation",
    "build_upfront_hint",
]


def estimate_instruction_tokens(
    instruction: Optional[str],
    count_tokens: Optional[Callable[[list], int]] = None,
) -> int:
    """Coarse up-front token estimate of the task instruction text.

    Wraps the instruction as a single user message and counts it with the given
    counter (the loop's ``count_tokens`` seam) or :func:`colleague.context.count_tokens_chars`
    as fallback.  Returns 0 for empty/None instruction.

    Args:
        instruction: The task instruction string to estimate.
        count_tokens: Optional callable ``(messages: list[dict]) -> int``.  When
            provided, it is called in place of the built-in char heuristic.

    Returns:
        Estimated token count (>= 0).
    """
    if not instruction:
        return 0

    messages = [{"role": "user", "content": instruction}]

    if count_tokens is not None:
        return count_tokens(messages)

    return count_tokens_chars(messages)


def child_count(target_tokens: int, per_child_budget_tokens: int) -> int:
    """Number of child hand-over assignments for a split.

    Thin pass-through to :func:`colleague.config.autosplit_children`, which
    structurally clamps the result to ``[1, MAX_SUBAGENT_FANOUT - 1]``.

    Args:
        target_tokens: The effective total token capacity to cover (e.g.
            ``EngineConfig.autosplit_target_tokens``).
        per_child_budget_tokens: Each child's context budget.

    Returns:
        Number of child assignments in ``[1, MAX_SUBAGENT_FANOUT - 1]``.
    """
    return autosplit_children(target_tokens, per_child_budget_tokens)


def build_split_recommendation(
    *,
    per_child_budget_tokens: int,
    max_children: int,
) -> str:
    """Render the ONE structured REACTIVE recommendation message body the loop
    injects after context overflow cannot be recovered.

    The returned string is advice to the model: it names the problem, points
    at the ``subagents`` tool, and gives the concrete numbers (per-child budget
    and child cap) so the model can compose a well-sized delegation call.

    Requirements (honesty condition h2):
    - Mentions that the assignment is too large for one context window.
    - Names the literal tool ``subagents``.
    - Includes the concrete ``per_child_budget_tokens`` number.
    - Includes the concrete ``max_children`` number.
    - Advises that each child must be a coherent, independently-scoped
      sub-assignment that fits one context window.

    Args:
        per_child_budget_tokens: Each child's token budget.
        max_children: Maximum number of children to delegate (fanout cap - 1).

    Returns:
        A deterministic, non-empty string (no randomness, no timestamps).
    """
    return (
        f"This assignment is too large to complete in one context window. "
        f"The current context has overflowed and cannot be recovered by trimming alone.\n\n"
        f"Consider splitting the work into at most {max_children} coherent, "
        f"independently-scoped sub-assignments, each sized to fit within "
        f"{per_child_budget_tokens} tokens per child context window.\n\n"
        f"Use the `subagents` tool to delegate these sub-assignments. "
        f"Each child must be a self-contained task that fits one window — "
        f"do not carry over implicit state between children. "
        f"The `subagents` tool accepts up to {max_children} children "
        f"(per-child budget: {per_child_budget_tokens} tokens)."
    )


def build_upfront_hint(
    *,
    estimate_tokens: int,
    per_child_budget_tokens: int,
    max_children: int,
) -> str:
    """Render the SOFTER early ADVISORY hint message body.

    Used before the loop when the up-front estimate already looks too large —
    this is a proactive suggestion, not a post-overflow recovery.  The model
    may choose to proceed as-is if it believes the estimate is pessimistic.

    Requirements:
    - Names the literal tool ``subagents``.
    - Includes the ``estimate_tokens`` number.
    - Includes the ``per_child_budget_tokens`` number.
    - Includes the ``max_children`` number.
    - Is clearly framed as an optional early suggestion, not a hard block.

    Args:
        estimate_tokens: The up-front token estimate of the instruction.
        per_child_budget_tokens: Each child's token budget.
        max_children: Maximum number of children to delegate (fanout cap - 1).

    Returns:
        A deterministic, non-empty string (no randomness, no timestamps).
    """
    return (
        f"Early advisory (optional): the instruction estimates roughly "
        f"{estimate_tokens} tokens, which may exceed one context window "
        f"(per-child budget: {per_child_budget_tokens} tokens).\n\n"
        f"You may consider splitting this assignment early using the `subagents` "
        f"tool (up to {max_children} children, each scoped to fit within "
        f"{per_child_budget_tokens} tokens). This is an early suggestion — "
        f"if you believe the estimate is pessimistic, you can proceed as a "
        f"single work item and the loop will degrade gracefully if needed."
    )
