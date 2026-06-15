"""Pushback on too-small tasks for plan mode.

When an operator invokes plan mode (`colleague plan`) on a task that is clearly
small or well-scoped, this module provides the judgment to DECLINE spinning up
the full spec -> plan -> workforce pipeline and instead recommend a plain
`colleague work`.  This avoids over-engineering a trivial task.

Mirrors the style of :mod:`colleague.plan.trigger` and :mod:`colleague.autosplit`.

Pure stdlib only — no devague import.
"""

from __future__ import annotations

from colleague.autosplit import estimate_instruction_tokens

__all__ = [
    "is_too_small",
    "build_pushback_message",
]


def is_too_small(instruction: str, *, threshold_tokens: int) -> bool:
    """Return True when the instruction is too small for the full pipeline.

    Uses :func:`colleague.autosplit.estimate_instruction_tokens` to get a
    coarse token estimate.  If the estimate is strictly less than
    ``threshold_tokens``, the task is considered too small for the full
    spec -> plan -> workforce pipeline.

    Args:
        instruction: The task instruction string to evaluate.
        threshold_tokens: Minimum token count for the full pipeline to be
            worthwhile.

    Returns:
        ``True`` if the task is too small for the full pipeline; ``False``
        otherwise.
    """
    tokens = estimate_instruction_tokens(instruction)
    return tokens < threshold_tokens


def build_pushback_message() -> str:
    """Render the pushback message recommending a plain `colleague work`.

    Used when a task is too small to justify the full spec -> plan -> workforce
    pipeline.  The message advises the operator to use a plain ``colleague work``
    instead.

    Requirements:
    - States the task is small enough to skip the full pipeline.
    - Recommends a plain ``colleague work``.
    - Mentions that the full spec -> plan -> workforce pipeline is unnecessary.
    - Is clearly advisory, never a forced gate.

    Returns:
        A deterministic, non-empty advisory string (no randomness, no timestamps).
    """
    return (
        "This task is small and well-scoped — the full spec -> plan -> workforce "
        "pipeline is unnecessary overhead.\n\n"
        "Instead of plan mode, run a plain `colleague work` to complete this "
        "task directly.  Reserve the full pipeline for tasks that genuinely "
        "benefit from spec-driven planning and parallel workforce assignment."
    )
