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
    "build_mapping_fanout_recommendation",
    "build_review_fanout_recommendation",
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


def build_mapping_fanout_recommendation(*, files_read: int, max_children: int) -> str:
    """Render the ONE structured ADVISORY message body for a read-only mapping run
    that is spending its step budget on serial file reads (issue #188).

    Unlike :func:`build_split_recommendation` (a token-overflow recovery), this is a
    *step-budget*-relative nudge: a wide codebase map should fan out across folders
    rather than read every file in series. It names the literal ``subagents`` tool
    and a concrete per-folder partition so the model can compose a delegation call.

    Requirements (honesty condition h4):
    - States the run has read many files serially.
    - Names the literal tool ``subagents``.
    - Includes the concrete ``files_read`` number.
    - Includes the concrete ``max_children`` number.
    - Frames the children as per-folder / per-subtree sub-surveys whose findings
      the parent synthesizes — advisory, not a hard block.

    Args:
        files_read: How many files the run has read so far (the trigger count).
        max_children: Maximum number of children to delegate (fanout cap - 1).

    Returns:
        A deterministic, non-empty string (no randomness, no timestamps).
    """
    return (
        f"You have read {files_read} files one at a time and are spending your step "
        f"budget on serial reads. For a wide codebase map this is slow and may run "
        f"out of steps before you can answer.\n\n"
        f"Consider fanning the survey out: partition the unmapped surface into at most "
        f"{max_children} coherent per-folder (or per-subtree) sub-surveys and delegate "
        f"them with the `subagents` tool, then synthesize their findings into your "
        f"answer. Each child should map ONE folder/subtree and return its findings — "
        f"read-only, nothing to write. This is an optional suggestion; if the remaining "
        f"surface is small you may keep reading directly."
    )


def build_review_fanout_recommendation(*, folders: int, max_children: int) -> str:
    """Render the ONE structured ADVISORY message body for a review spread across
    many folders (issue #220b).

    A review that reads a multi-folder diff one file at a time is turn-bound. This
    nudges the model to partition the diff per-folder and delegate concurrent
    READ-ONLY ``reviewer`` subagents (the #221 typed role) via the existing
    ``subagents`` tool, then synthesize their findings — reusing the fan-out/merge
    machinery, adding no new worktree/merge code. Advisory, not a hard block.

    Honesty (h12/h13): names the literal ``subagents`` tool and the read-only
    ``reviewer`` role, includes the concrete ``folders`` and ``max_children``
    numbers, frames children as per-folder diff reviews, and states the honest
    limit that on a single serializing backend (one GPU) this does NOT reduce
    wall-clock time — the win needs a concurrent-capable backend; front-loading the
    diff is the speedup that holds on a serializing rig.

    Args:
        folders: How many distinct folders the review has read across (the trigger).
        max_children: Maximum number of children to delegate (fanout cap - 1).

    Returns:
        A deterministic, non-empty string (no randomness, no timestamps).
    """
    return (
        f"This review spans {folders} folders and you are reading them one file at a "
        f"time, which is slow and may run out of steps before you can write the "
        f"review.\n\n"
        f"Consider fanning the review out: partition the diff into at most "
        f"{max_children} coherent per-folder slices and delegate them with the "
        f"`subagents` tool using the read-only `reviewer` role. Each child reviews ONE "
        f"folder's diff (read-only, nothing to write) and returns its findings, which "
        f"you then synthesize into one review.\n\n"
        f"This is an optional suggestion. Honest limit: on a single serializing "
        f"backend (one GPU) the children run effectively one at a time, so fanning out "
        f"will NOT reduce wall-clock time — the parallelism win needs a "
        f"concurrent-capable backend. If the diff is small, just keep reviewing "
        f"directly."
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
