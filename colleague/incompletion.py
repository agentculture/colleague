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

#: The one reason string meaning "the loop ran out of steps before
#: delivering" — exposed as a named constant (rather than a magic string) so
#: OTHER modules (e.g. :mod:`colleague.memory`'s split-next-time record,
#: spec c15/h10) can compare against it without re-typing the literal.
REASON_BUDGET_EXHAUSTED = "budget-exhausted"

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
        "re-run with a tighter scope or take over: " + "the finish produced no usable deliverable."
    ),
    REASON_BUDGET_EXHAUSTED: (
        "split the task or raise --max-steps: " + "colleague ran out of steps before delivering."
    ),
    "no-progress-zero-steps": (
        "check backend tool-calling or escalate to another model: "
        "colleague made zero tool-calls."
    ),
    "tool-protocol-broken": (
        "check the served model's tool-call parser/template (e.g. vLLM "
        "--enable-auto-tool-choice + --tool-call-parser) before re-running: "
        "the model's tool calls never parsed as known tools, so the task "
        "itself was likely never attempted."
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
    protocol_detail: str = "",
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
    protocol_detail:
        Loop-supplied evidence for a ``"tool_protocol"`` outcome (#321) — the
        unknown-tool streak that stopped the run. Empty otherwise.
    """

    # --- Broken tool-call channel (#321): diagnosed before the deliverable
    # checks, because a run stopped for consecutive unknown-tool calls cannot
    # have a trustworthy deliverable — the finish tool itself never parsed. The
    # reason must point at the PROTOCOL, not the task, so the operator fixes
    # the serving-side parser instead of blaming the model's competence.
    if outcome == "tool_protocol":
        return IncompletionRecord(
            reason="tool-protocol-broken",
            evidence=protocol_detail
            or f"stopped after {step_count} step(s): consecutive unknown-tool calls",
            recommendation=_REASON_ADVICE["tool-protocol-broken"],
        )

    # --- Deliverable-present checks (return None) ---
    stripped = summary.strip()
    substantive = bool(stripped) and stripped != NO_RESULT_PRODUCED and not _is_meta(stripped)

    if write_intent:
        if changed_files >= 1:
            return None  # files changed — even if wrong, that's not absence
        # 0 changes: a CLEAN finish reporting a substantive, non-meta result is a
        # legitimate "no change needed" deliverable (colleague#313 soft rule); an
        # empty/meta finish, or a budget/stop exit, is a genuine no-deliverable
        # (falls through to reason classification below — write-no-changes catches
        # the #313 meta-finish, whose summary is not substantive).
        if outcome == "finished" and substantive:
            return None
    elif substantive:
        # Read intent: the summary IS the deliverable, regardless of outcome — a
        # forced-synthesis answer at budget exhaustion still delivered.
        return None

    # --- Incomplete: pick reason by priority ---
    if step_count == 0:
        reason = "no-progress-zero-steps"
    elif outcome == "budget":
        reason = REASON_BUDGET_EXHAUSTED
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
