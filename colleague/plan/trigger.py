"""Auto-trigger advisory for plan mode during a normal work item.

When a task looks too complex or lacks a clean implementation path, the runtime
may inject ONE advisory recommendation suggesting the model enter plan mode
(via the ``colleague plan`` verb).  This is **advisory only** — never forced.

Mirrors the style and tone of :mod:`colleague.autosplit` recommendation
builders.

Pure stdlib only — no devague import.
"""

from __future__ import annotations

from colleague.autosplit import estimate_instruction_tokens

__all__ = [
    "build_plan_recommendation",
    "should_offer_plan_mode",
]


def build_plan_recommendation() -> str:
    """Render the ONE structured ADVISORY message body suggesting plan mode.

    Used when a task looks too complex or may lack a clean implementation path.
    The message is advisory — the model decides whether to enter plan mode via
    the ``colleague plan`` verb to spec -> plan -> workforce the task.

    Requirements (honesty condition):
    - States the task looks complex or may lack a clean implementation path.
    - Names the ``colleague plan`` verb.
    - Frames plan mode as an optional path (spec -> plan -> workforce).
    - Is clearly advisory, never a forced gate.

    Returns:
        A deterministic, non-empty advisory string (no randomness, no timestamps).
    """
    return (
        "This task looks complex and may not have a clean implementation path "
        "as a single work item.\n\n"
        "You may consider entering plan mode via the `colleague plan` verb to "
        "work through a spec -> plan -> workforce flow: spec the idea, turn it "
        "into a buildable plan, and then assign waves to parallel agents. "
        "This is an optional suggestion — if you believe the task is straightforward "
        "enough, you can proceed as a normal work item."
    )


def should_offer_plan_mode(
    instruction: str,
    *,
    already_offered: bool,
    threshold_tokens: int,
) -> bool:
    """Decide whether to offer the plan-mode advisory recommendation.

    Returns ``True`` only when the instruction has not already been offered
    plan mode AND the instruction is complex enough (token estimate >= threshold).

    Args:
        instruction: The task instruction string to evaluate.
        already_offered: Whether plan mode was already suggested in this run.
        threshold_tokens: Minimum token estimate to trigger the advisory.

    Returns:
        ``True`` if the plan-mode advisory should be offered.
    """
    if already_offered:
        return False

    tokens = estimate_instruction_tokens(instruction)
    return tokens >= threshold_tokens
