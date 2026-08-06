"""Review-input assembler — pure functions that compose ConfiguratorReviewInput
digests from Task and TaskResult objects.

Two public functions:
  - assemble_before_episode(task) — digest from Task instruction + goal/acceptance
  - assemble_between_episodes(task, result) — digest from TaskResult terminal facts

Both return ConfiguratorReviewInput with a hard size bound on the digest.
No I/O. No conversation history. Structural pin 1: accept only Task/TaskResult,
never a message list.
"""

from __future__ import annotations

from colleague.configurator import ConfiguratorReviewInput
from colleague.contract import Task, TaskResult

#: Default maximum digest length — large enough for typical instructions and
#: result summaries, small enough to keep the configurator prompt lean.
_DEFAULT_MAX_CHARS = 4096

#: Maximum number of changed files to list before truncating with "+N more".
_MAX_FILES_LISTED = 20


def _truncate(text: str, max_chars: int) -> str:
    """Truncate *text* to *max_chars*, appending an ellipsis if cut."""
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"


def _format_file_list(files: list[str], max_listed: int = _MAX_FILES_LISTED) -> str:
    """Format a list of file paths, truncating with '+N more' when long."""
    if not files:
        return "(none)"
    if len(files) <= max_listed:
        return ", ".join(files)
    shown = files[:max_listed]
    remaining = len(files) - max_listed
    return ", ".join(shown) + f", +{remaining} more"


def assemble_before_episode(
    task: Task, *, max_chars: int = _DEFAULT_MAX_CHARS
) -> ConfiguratorReviewInput:
    """Compose a digest from a Task's instruction, goal, and acceptance criteria.

    Used before episode 1 to give the configurator context about what the work
    item is supposed to accomplish. Pure: no I/O, no side effects.

    Args:
        task: The Task being driven.
        max_chars: Hard upper bound on the digest length.

    Returns:
        A ConfiguratorReviewInput with the composed digest.
    """
    lines: list[str] = []
    lines.append(f"Instruction: {task.instruction}")

    if task.goal is not None:
        lines.append(f"Goal: {task.goal}")

    if task.acceptance is not None:
        criteria = "\n".join(f"  - {c}" for c in task.acceptance)
        lines.append(f"Acceptance criteria:\n{criteria}")

    digest = "\n".join(lines)
    return ConfiguratorReviewInput(digest=_truncate(digest, max_chars))


def assemble_between_episodes(
    task: Task,
    result: TaskResult,
    *,
    max_chars: int = _DEFAULT_MAX_CHARS,
) -> ConfiguratorReviewInput:
    """Compose a digest from a TaskResult's terminal facts.

    Used between episodes to give the configurator context about what happened
    in the prior episode. Pure: no I/O, no side effects.

    Args:
        task: The Task that was driven.
        result: The TaskResult from the prior episode.
        max_chars: Hard upper bound on the digest length.

    Returns:
        A ConfiguratorReviewInput with the composed digest.

    Raises:
        TypeError: If *result* is not a TaskResult (structural pin — no message
            lists accepted).
    """
    if not isinstance(result, TaskResult):
        raise TypeError(
            f"expected TaskResult, got {type(result).__name__!r} — "
            "only TaskResult objects accepted, never a message list"
        )

    lines: list[str] = []
    lines.append(f"Instruction: {task.instruction}")
    lines.append(f"Status: {result.status}")
    lines.append(f"Summary: {result.summary}")
    lines.append(f"Steps: {len(result.steps)}")
    lines.append(
        f"Changed files ({len(result.changed_files)}): {_format_file_list(result.changed_files)}"
    )

    # Gate outcomes
    if result.lint_report is not None:
        lint = result.lint_report
        lint_parts: list[str] = []
        if lint.fixed:
            lint_parts.append(f"fixed: {', '.join(lint.fixed)}")
        if lint.residual:
            lint_parts.append(f"residual: {', '.join(lint.residual)}")
        if lint.skipped:
            lint_parts.append(f"skipped: {', '.join(lint.skipped)}")
        if lint_parts:
            lines.append(f"Lint: {', '.join(lint_parts)}")
        else:
            lines.append("Lint: clean")

    if result.test_integrity_report is not None:
        tir = result.test_integrity_report
        lines.append(f"Test integrity: {tir}")

    if result.affected_tests_report is not None:
        atr = result.affected_tests_report
        lines.append(f"Affected tests: {atr}")

    if result.coherence_report is not None:
        cr = result.coherence_report
        lines.append(f"Coherence: {cr.status}")

    # Finish state
    if result.finish_states:
        states = ", ".join(f"{fs.seat}:{fs.state}" for fs in result.finish_states)
        lines.append(f"Finish states: {states}")

    # Sub-results
    if result.sub_results:
        sub_summaries = [f"{sr.task_id}: {sr.status}" for sr in result.sub_results]
        lines.append(f"Sub-results: {', '.join(sub_summaries)}")

    # Acceptance outcomes
    if result.acceptance_outcomes is not None:
        outcomes = []
        for ao in result.acceptance_outcomes:
            if isinstance(ao, dict):
                criterion = ao.get("criterion", "?")
                met = ao.get("met", "?")
                outcomes.append(f"{criterion}: {'met' if met else 'not met'}")
        if outcomes:
            lines.append(f"Acceptance: {'; '.join(outcomes)}")

    digest = "\n".join(lines)
    return ConfiguratorReviewInput(digest=_truncate(digest, max_chars))
