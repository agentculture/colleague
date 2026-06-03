"""Escalation continuation-record builder.

Provides :func:`build_continuation`, a **pure** function that renders a
structured five-section markdown body describing where a partial drive got to
and how to continue it.  The output is intended to be filed as the body of an
agtag issue by the escalation path (t3); this module owns only the rendering.

No I/O, no subprocess, no network — stdlib only.
"""

from __future__ import annotations

from colleague.contract import DriveStats, TaskResult

__all__ = ["build_continuation"]


def build_continuation(result: TaskResult, stats: DriveStats) -> str:  # noqa: WPS231
    """Render a five-section continuation record from a partial drive result.

    Parameters
    ----------
    result:
        The :class:`~colleague.contract.TaskResult` produced by the interrupted
        drive.  Key fields consumed: ``task_id``, ``status``, ``summary``,
        ``changed_files``, ``error``.
    stats:
        The :class:`~colleague.contract.DriveStats` attached to the same drive
        (typically ``result.stats``).  Key fields consumed: ``started_at``,
        ``duration_seconds``, ``model_turns``, ``step_count``, ``tool_counts``,
        ``files_changed``, ``bytes_written``, ``request``.

    Returns
    -------
    str
        A markdown string with five ``##``-headed sections.  The body is
        self-contained — a reader can understand the drive state without
        consulting the artifact directly.

    Notes
    -----
    Pure function: no network, no subprocess, no filesystem I/O, no global
    state mutation.  Safe to call multiple times with the same inputs
    (idempotent).
    """
    # -----------------------------------------------------------------------
    # Section 1 — Continuation State
    # -----------------------------------------------------------------------
    changed = result.changed_files or []
    files_summary = (
        (", ".join(f"`{f}`" for f in changed[:5]) + (" …" if len(changed) > 5 else ""))
        if changed
        else "_none_"
    )

    tool_detail = (
        ", ".join(f"{tool}: {count}" for tool, count in sorted(stats.tool_counts.items()))
        if stats.tool_counts
        else "_no tool calls recorded_"
    )

    section_state = (
        "## Continuation State\n\n"
        f"**Task ID:** `{result.task_id}`  \n"
        f"**Started:** {stats.started_at}  \n"
        f"**Wall-clock duration:** {stats.duration_seconds:.1f}s  \n"
        f"**Model turns:** {stats.model_turns}  \n"
        f"**Steps completed:** {stats.step_count}  \n"
        f"**Files changed ({stats.files_changed}):** {files_summary}  \n"
        f"**Bytes written:** {stats.bytes_written}  \n"
        f"**Tool breakdown:** {tool_detail}  \n\n"
        f"**What the drive finished:**\n\n"
        f"{result.summary or '_No summary produced._'}\n"
    )

    # -----------------------------------------------------------------------
    # Section 2 — Remaining Work
    # -----------------------------------------------------------------------
    remaining_hint = _remaining_hint(result, stats)

    section_remaining = "## Remaining Work\n\n" f"{remaining_hint}\n"

    # -----------------------------------------------------------------------
    # Section 3 — What's Needed
    # -----------------------------------------------------------------------
    needs = _whats_needed(result, stats)

    section_needed = "## What's Needed\n\n" f"{needs}\n"

    # -----------------------------------------------------------------------
    # Section 4 — Suggested Split
    # -----------------------------------------------------------------------
    split = _suggested_split(result, stats)

    section_split = "## Suggested Split\n\n" f"{split}\n"

    # -----------------------------------------------------------------------
    # Section 5 — Why It Hit the Wall
    # -----------------------------------------------------------------------
    why = _why_it_stopped(result, stats)

    section_why = "## Why It Hit the Wall\n\n" f"{why}\n"

    return "\n".join(
        [
            section_state,
            section_remaining,
            section_needed,
            section_split,
            section_why,
        ]
    )


# ---------------------------------------------------------------------------
# Private helpers — pure, no I/O
# ---------------------------------------------------------------------------


def _remaining_hint(result: TaskResult, stats: DriveStats) -> str:
    """Describe what work is likely still outstanding."""
    original = stats.request or result.summary or "_original task unknown_"
    summary = result.summary or "_no progress recorded_"
    if original == summary:
        return (
            "The drive did not produce a summary distinct from the original request. "
            "The full task should be retried."
        )
    return (
        f"The original request was:\n\n> {original}\n\n"
        f"The drive reached:\n\n> {summary}\n\n"
        "Work that was not reached in this drive should be continued in a follow-up."
    )


def _whats_needed(result: TaskResult, stats: DriveStats) -> str:
    """Suggest the resource or configuration change that would unblock the drive."""
    error = (result.error or "").lower()
    lines: list[str] = []

    if "context" in error or "window" in error:
        lines.append(
            "- **Smaller context / context budget:** the model's context window was "
            "exhausted.  Consider reducing `COLLEAGUE_CONTEXT_BUDGET`, splitting the "
            "task into smaller scopes, or switching to a model with a larger context "
            "window."
        )
    if "timeout" in error or stats.duration_seconds >= 600.0:
        lines.append(
            f"- **Longer timeout:** the drive ran for {stats.duration_seconds:.1f}s "
            "before being interrupted.  Increase the per-drive timeout or break the "
            "task into shorter sub-tasks."
        )
    if "step" in error or "budget" in error:
        lines.append(
            f"- **Larger step budget:** the drive consumed all {stats.step_count} "
            "permitted steps.  Increase `COLLEAGUE_MAX_STEPS` or split the task so "
            "each part fits within the current budget."
        )
    if not lines:
        # Generic fallback when the error does not match a known pattern.
        lines.append(
            f"- **Review the error:** `{result.error or 'unknown'}`  \n"
            "  Consider more steps, a larger context budget, a longer timeout, or "
            "splitting the task."
        )

    return "\n".join(lines)


def _suggested_split(result: TaskResult, stats: DriveStats) -> str:
    """Suggest a concrete decomposition strategy."""
    changed = result.changed_files or []
    step_count = stats.step_count
    model_turns = stats.model_turns

    if step_count >= 20 or model_turns >= 10:
        strategy = (
            "The drive was large ({step_count} steps, {model_turns} model turns).  "
            "Consider splitting by **feature area** or **file group**:"
        ).format(step_count=step_count, model_turns=model_turns)
    else:
        strategy = (
            "The drive was small ({step_count} steps) but still hit a limit.  "
            "Consider splitting by **scope**:"
        ).format(step_count=step_count)

    bullets: list[str] = [strategy, ""]

    if changed:
        bullets.append(
            f"- **Part A (done):** Files already changed in this drive — "
            f"{', '.join(f'`{f}`' for f in changed[:3])}"
            + (" …" if len(changed) > 3 else "")
            + " — can be committed as-is."
        )
        bullets.append(
            "- **Part B (remaining):** Continue from where the drive stopped, "
            "starting a new drive with the continuation context."
        )
    else:
        bullets.append("- **Part A:** First batch of changes (break by file/module).")
        bullets.append("- **Part B:** Second batch continuing from Part A's result.")

    bullets.append("- **Integration:** A final short drive to wire together and run tests.")

    return "\n".join(bullets)


def _why_it_stopped(result: TaskResult, stats: DriveStats) -> str:
    """Explain the concrete reason the drive was interrupted."""
    error = result.error or ""
    error_lower = error.lower()
    lines: list[str] = []

    if error:
        lines.append(f"**Reported error:** `{error}`")
        lines.append("")

    if "context" in error_lower or "window" in error_lower:
        lines.append(
            f"The model's context window was filled after {stats.model_turns} turns "
            f"and {stats.step_count} steps "
            f"({stats.answer_chars} answer chars + {stats.reasoning_chars} reasoning chars "
            f"generated).  The conversation history grew too large to fit in one pass."
        )
    elif "timeout" in error_lower:
        lines.append(
            f"The drive exceeded the allowed wall-clock time "
            f"({stats.duration_seconds:.1f}s elapsed).  "
            f"It completed {stats.step_count} steps across {stats.model_turns} model turns "
            "before being cut short."
        )
    elif "step" in error_lower or "budget" in error_lower:
        lines.append(
            f"The step budget was exhausted: {stats.step_count} steps were taken across "
            f"{stats.model_turns} model turns in {stats.duration_seconds:.1f}s.  "
            "The drive ran out of permitted iterations before the task was complete."
        )
    else:
        lines.append(
            f"The drive ran for {stats.duration_seconds:.1f}s, completing "
            f"{stats.step_count} steps across {stats.model_turns} model turns, then "
            "stopped"
            + (f" with error: `{error}`" if error else " without producing a finish call")
            + "."
        )

    if stats.bytes_written:
        lines.append(
            f"\n{stats.bytes_written} bytes were written to {stats.files_changed} "
            "file(s) before the interruption."
        )

    return "\n".join(lines)
