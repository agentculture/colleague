"""Escalation: continuation-record builder + gating / idempotency (t1 + t2).

Two public surfaces live here:

**build_continuation** (t1) — a **pure** function that renders a structured
five-section markdown body describing where a partial drive got to and how to
continue it.  The output is intended to be filed as the body of an agtag issue
by the escalation path (t3); this module owns only the rendering.

**should_escalate / mark_escalated** (t2) — the gating predicate and
idempotency marker for the agtag escalation outward side-effect.
``should_escalate`` returns ``True`` ONLY when ALL conditions hold:

1. **opt-in**: ``COLLEAGUE_ESCALATE`` env flag (falling back to the legacy
   ``CONVERTIBLE_ESCALATE``) is set to a truthy value.
2. **online / non-CI**: a git remote is configured (``handoff.has_remote``) AND
   the ``gh`` CLI is on PATH (``handoff.gh_available``).  Both are imported from
   :mod:`colleague.handoff` — this module does NOT import subprocess itself.
3. **main checkout, not a throwaway worktree**: a linked git worktree
   (colleague's subagent worktrees and outsource explore/review worktrees) has
   ``.git`` as a *file* (a gitdir pointer); the main checkout has ``.git`` as a
   *directory*.  We return False when ``(repo / ".git").is_file()``.  Pure
   filesystem check — no subprocess.
4. **approval gate**: the ``agtag`` program token must be allowed by the
   policy loaded via :func:`colleague.policy.load_policy`.
5. **idempotent**: if this ``task_id`` has already escalated (its marker file
   exists), return False.

``mark_escalated(repo, task_id, issue_url)`` writes the idempotency marker
``<task_id>.escalation.json`` beside the drive artifact (same directory as the
feedback record — resolved via :func:`colleague.artifact.artifact_dir`).

No I/O, no subprocess, no network — stdlib only (``json``, ``os``, ``pathlib``).
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Callable, Sequence

from colleague.artifact import artifact_dir
from colleague.contract import DriveStats, TaskResult
from colleague.culture import run_culture
from colleague.handoff import gh_available, has_remote
from colleague.policy import load_policy

__all__ = ["build_continuation", "escalate", "mark_escalated", "run_culture", "should_escalate"]

# ---------------------------------------------------------------------------
# Env-flag helpers
# ---------------------------------------------------------------------------

#: Primary env flag; legacy ``CONVERTIBLE_ESCALATE`` honored as fallback.
_ESCALATE_FLAG = "COLLEAGUE_ESCALATE"
_ESCALATE_FLAG_LEGACY = "CONVERTIBLE_ESCALATE"

#: Marker filename suffix, mirroring the feedback store pattern.
_MARKER_SUFFIX = ".escalation.json"


def _escalate_enabled() -> bool:
    """Return True when the COLLEAGUE_ESCALATE (or legacy) env flag is truthy."""
    raw = os.environ.get(_ESCALATE_FLAG) or os.environ.get(_ESCALATE_FLAG_LEGACY) or ""
    return raw.strip().lower() not in ("", "0", "false", "no")


# ---------------------------------------------------------------------------
# Idempotency marker
# ---------------------------------------------------------------------------


def _marker_path(repo: Path, task_id: str) -> Path:
    """Return the write path for this task's escalation marker."""
    return artifact_dir(repo) / f"{task_id}{_MARKER_SUFFIX}"


def mark_escalated(repo: str | Path, task_id: str, issue_url: str) -> None:
    """Write the idempotency marker for *task_id* beside the drive artifact.

    The marker is a small JSON file ``<task_id>.escalation.json`` in
    ``<repo>/.colleague/`` (the same directory the feedback store uses).  A
    second call for the same ``task_id`` silently overwrites the first record —
    the marker is idempotent by content; the important invariant is existence.

    Parameters
    ----------
    repo:
        The repo root (used to resolve the artifact directory).
    task_id:
        The drive's task identifier — used as the filename stem.
    issue_url:
        The URL of the agtag issue that was opened.  Stored in the marker so
        the operator can inspect which issue was filed for a given drive.
    """
    path = _marker_path(Path(repo).resolve(), task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"task_id": task_id, "issue_url": issue_url}
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _already_escalated(repo: Path, task_id: str) -> bool:
    """Return True when the escalation marker for *task_id* already exists.

    An absent or malformed marker is a clean no-op (returns False — treat as
    "not yet escalated", never raise).
    """
    try:
        return _marker_path(repo, task_id).is_file()
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Gating predicate
# ---------------------------------------------------------------------------


def should_escalate(
    repo: str | Path,
    task_id: str,
    *,
    model: str | None = None,
) -> bool:
    """Return True only when ALL escalation gates are open.

    Gates (ALL must hold):

    1. **opt-in**: ``COLLEAGUE_ESCALATE`` (or ``CONVERTIBLE_ESCALATE``) is set
       to a truthy value.
    2. **online / non-CI**: ``handoff.has_remote(repo)`` is True AND
       ``handoff.gh_available()`` is True.  These helpers are imported from
       :mod:`colleague.handoff`; no subprocess is called directly here.
    3. **main checkout**: ``(repo / ".git").is_file()`` must be False — a file
       indicates a linked git worktree (subagent worktree or outsource throwaway);
       the main checkout always has ``.git`` as a directory.
    4. **approval gate**: ``check_run_command("agtag ...")`` on the repo policy
       must return ``Verdict(allowed=True)``.
    5. **idempotent**: no escalation marker for *task_id* exists yet.

    Parameters
    ----------
    repo:
        The repository root path.
    task_id:
        The drive's task identifier.
    model:
        Optional model name; forwarded to ``load_policy`` so per-model overlays
        are respected.

    Returns
    -------
    bool
        ``True`` only when every gate passes, ``False`` on any failure.  With
        the env flag unset this is always ``False`` — a strict no-op so tests,
        CI, offline runs, and worktrees never escalate by default.
    """
    # Gate 1 — opt-in: env flag must be explicitly enabled.
    if not _escalate_enabled():
        return False

    repo_path = Path(repo).resolve()

    # Gate 2 — online / non-CI: remote + gh CLI must be available.
    if not has_remote(repo_path) or not gh_available():
        return False

    # Gate 3 — main checkout only: a linked worktree has .git as a FILE.
    if (repo_path / ".git").is_file():
        return False

    # Gate 4 — approval gate: agtag must be in the run_command allow-list.
    policy = load_policy(repo_path, model=model)
    verdict = policy.check_run_command("agtag escalate")
    if not verdict.allowed:
        return False

    # Gate 5 — idempotent: skip if already escalated for this task.
    if _already_escalated(repo_path, task_id):
        return False

    return True


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
    if changed:
        overflow = " …" if len(changed) > 5 else ""
        files_summary = ", ".join(f"`{f}`" for f in changed[:5]) + overflow
    else:
        files_summary = "_none_"

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
# Escalation orchestrator (t3)
# ---------------------------------------------------------------------------

# Type alias matching the run_culture signature for injection.
_RunFn = Callable[[str, Sequence[str]], str]


def escalate(
    result: TaskResult,
    stats: DriveStats,
    repo: str | Path,
    *,
    model: str | None = None,
    run: Callable | None = None,
) -> str | None:
    """Orchestrate one escalation attempt for a partial drive result.

    Returns the issue URL string (or the raw output if no URL is parseable) on
    success, or ``None`` when the gate is closed, the post fails, or posting
    raises.  On a non-zero exit or any exception the idempotency marker is NOT
    written so a future drive may retry.

    Parameters
    ----------
    result:
        The :class:`~colleague.contract.TaskResult` from the interrupted drive.
    stats:
        The :class:`~colleague.contract.DriveStats` attached to the same drive.
    repo:
        The repo root path.
    model:
        Optional model name; forwarded to :func:`should_escalate` so per-model
        overlays are respected.
    run:
        Callable with the same signature as :func:`colleague.culture.run_culture`
        — injected in tests to avoid network/subprocess calls.  When ``None``
        (the default), the module-level :data:`run_culture` is used at call time
        so test patches to ``escalation_mod.run_culture`` are honoured.

    Returns
    -------
    str | None
        The issue URL / raw output on success, ``None`` otherwise.
    """
    # Resolve the run callable at call time so module-level patches work.
    _run = run if run is not None else run_culture

    repo_path = Path(repo).resolve()

    if not should_escalate(repo_path, result.task_id, model=model):
        return None

    body = build_continuation(result, stats)

    # Write body to a tempfile — agtag has no stdin mode (mirrors post-issue.sh).
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".md",
        prefix="colleague-escalation-",
        delete=False,
        encoding="utf-8",
    ) as tmp:
        tmp.write(body)
        tmp_path = tmp.name

    try:
        title = f"colleague: continuation needed for drive {result.task_id}"
        raw = _run(
            "agtag",
            ["issue", "post", "--title", title, "--body-file", tmp_path],
            root=repo_path,
        )
    finally:
        # Best-effort cleanup of the tempfile.
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    # Success iff the output starts with "exit=0".
    if not raw.startswith("exit=0"):
        return None

    # Best-effort URL extraction: scan for a line that looks like an https:// URL.
    url: str = raw
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("https://"):
            url = line
            break

    mark_escalated(repo_path, result.task_id, url)
    return url


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
