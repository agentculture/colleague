"""Incompletion classifier — pure, deterministic, IO-free.

Given a finished work item's terminal facts, decide whether it produced its
expected deliverable.  If not, return an :class:`IncompletionRecord` explaining
**why** and suggesting a caller-facing next move.

This module imports only from :mod:`colleague.contract` and the stdlib.  It
never touches subprocess, urllib, or any loop/engine module.
"""

from __future__ import annotations

from typing import Optional

from colleague.contract import NO_RESULT_PRODUCED, IncompletionRecord

# Substring markers that indicate a summary merely *describes* a report it
# never produced or admits it is unfinished.  Matched case-insensitively.
_META_MARKERS: tuple[str, ...] = (
    "need to continue",
    "remaining work",
    "i have read",
    "i will ",
    "next i ",
    "to be implemented",
    "not yet implemented",
    "need to implement",
)

# Fixed advice text keyed by reason.  Every reason produced by
# :func:`classify_incompletion` MUST have an entry here.
_REASON_ADVICE: dict[str, str] = {
    "write-no-changes": "re-scope or take over: colleague finished without changing any files.",
    "empty-deliverable": (
        "re-run with a tighter scope or take over: " "the finish produced no usable deliverable."
    ),
    "budget-exhausted": (
        "split the task or raise --max-steps: " "colleague ran out of steps before delivering."
    ),
    "no-progress-zero-steps": (
        "check backend tool-calling or escalate to another model: "
        "colleague made zero tool-calls."
    ),
}


def _is_meta(summary: str) -> bool:
    """Return True when *summary* is a meta-description rather than a deliverable."""
    lower = summary.lower()
    return any(marker in lower for marker in _META_MARKERS)


def classify_incompletion(
    *,
    outcome: str,
    write_intent: bool,
    changed_files: int,
    summary: str,
    step_count: int,
    finish_recovered: Optional[str] = None,
) -> Optional[IncompletionRecord]:
    """Classify a finished work item as complete or incomplete.

    Returns ``None`` when a deliverable is present, otherwise an
    :class:`IncompletionRecord` with reason, evidence, and recommendation.

    Parameters
    ----------
    outcome:
        The loop's terminal outcome label (e.g. ``"finished"``, ``"budget"``).
    write_intent:
        Whether the task expected file changes.
    changed_files:
        Number of distinct files the work item wrote.
    summary:
        The work item's finish summary text.
    step_count:
        Number of tool-call steps the loop recorded.
    finish_recovered:
        Optional recovery note (unused by the classifier; reserved for future
        disambiguation).
    """

    # --- Deliverable-present checks (return None) ---
    if write_intent and changed_files >= 1:
        return None  # files changed — even if wrong, that's not absence

    if not write_intent:
        stripped = summary.strip()
        if stripped and stripped != NO_RESULT_PRODUCED and not _is_meta(stripped):
            return None  # real text deliverable

    # --- Incomplete: pick reason by priority ---
    if step_count == 0:
        reason = "no-progress-zero-steps"
    elif outcome == "budget":
        reason = "budget-exhausted"
    elif write_intent and changed_files == 0:
        reason = "write-no-changes"
    else:
        reason = "empty-deliverable"

    evidence = (
        f"finished outcome={outcome!r} with {changed_files} changed file(s) "
        f"over {step_count} step(s)"
    )
    recommendation = _REASON_ADVICE[reason]

    return IncompletionRecord(
        reason=reason,
        evidence=evidence,
        recommendation=recommendation,
    )
