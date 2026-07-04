"""Pure run-state + ledger module for cockpit UX.

Folds progress events into a :class:`RunState` and reconciles an authoritative
post-run :class:`Ledger` from a :class:`TaskResult`.  No I/O, no threads, no
clock reads — all timestamps and elapsed values are passed in by the caller.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from colleague.contract import TaskResult

# ── Activity ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class Activity:
    """One tool-call step folded into the run-state."""

    tool: str
    target: str
    ok: bool


# ── RunState ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class RunState:
    """Immutable snapshot of folded progress events."""

    activities: tuple[Activity, ...] = ()
    files_touched: frozenset[str] = frozenset()
    command_count: int = 0
    last_action: str = ""
    phase: str = ""
    step_count: int = 0


#: Default cap on retained activities (keep the most recent this-many).
ACTIVITY_CAP: int = 50

# File-mutating tools that add the target path to files_touched.
_FILE_MUTATING_TOOLS = frozenset({"write_file", "edit_file"})


# ── fold ──────────────────────────────────────────────────────────


def fold(
    state: RunState,
    tool: str,
    target: str,
    ok: bool,
    *,
    cap: int = ACTIVITY_CAP,
) -> RunState:
    """Return a NEW RunState with the event folded in (pure — never mutate *state*).

    Empty *tool* => a phase notice: return a new state with ``phase=target`` and
    everything else unchanged (no counter/activity change).

    Non-empty *tool* => a real step: append an :class:`Activity` (truncating
    ``activities`` to the most-recent *cap*), set ``last_action`` to
    ``"[{tool}] {target}"`` (or ``"[{tool}]"`` if target is empty), bump
    ``step_count``, and update ``files_touched`` / ``command_count`` per the
    categorization rules.
    """
    # Phase notice — tool is empty.
    if not tool:
        return RunState(
            activities=state.activities,
            files_touched=state.files_touched,
            command_count=state.command_count,
            last_action=state.last_action,
            phase=target,
            step_count=state.step_count,
        )

    # Real step.
    action = f"[{tool}] {target}" if target else f"[{tool}]"
    new_activity = Activity(tool=tool, target=target, ok=ok)

    new_activities = state.activities + (new_activity,)
    if len(new_activities) > cap:
        new_activities = new_activities[-cap:]

    new_files = state.files_touched
    if tool in _FILE_MUTATING_TOOLS:
        new_files = state.files_touched | {target}

    new_command_count = state.command_count
    if tool == "run_command":
        new_command_count += 1

    return RunState(
        activities=new_activities,
        files_touched=new_files,
        command_count=new_command_count,
        last_action=action,
        phase=state.phase,
        step_count=state.step_count + 1,
    )


# ── Ledger ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Ledger:
    """Mutation ledger for a work item."""

    files_changed: int
    commands_run: int
    commits: Optional[int]
    publish_state: str


def observed_ledger(state: RunState) -> Ledger:
    """Mid-run ledger derived ONLY from folded sink events.

    ``commits`` is ``None`` (mid-run commit detection from sink events is
    dishonest — resolves parked v3), ``publish_state`` is ``""`` (unknown
    mid-run).
    """
    return Ledger(
        files_changed=len(state.files_touched),
        commands_run=state.command_count,
        commits=None,
        publish_state="",
    )


def reconcile(result: TaskResult) -> Ledger:
    """Authoritative POST-run ledger, read verbatim from the TaskResult.

    Uses ``result.stats.files_changed`` for ``files_changed`` and the sum of
    ``run_command`` entries in ``result.stats.tool_counts`` for ``commands_run``
    (fall back to 0 if stats is None).

    Sets ``commits`` from the handoff/commit info available on the result — if
    the result exposes a branch (indicating a local commit), map presence to 1;
    otherwise 0.

    Derives ``publish_state``: if a PR url is present -> "pr"; elif branch
    committed -> "local"; else "none".

    Never raises: if a field is absent, degrade to 0 / "none".
    """
    stats = result.stats
    files_changed = 0
    commands_run = 0

    if stats is not None:
        files_changed = getattr(stats, "files_changed", 0) or 0
        tool_counts = getattr(stats, "tool_counts", None) or {}
        commands_run = tool_counts.get("run_command", 0)

    # Derive commits from branch presence (a branch implies at least one commit).
    branch = getattr(result, "branch", None)
    commits = 1 if branch else 0

    # Derive publish_state.
    pr_url = getattr(result, "pr_url", None)
    if pr_url:
        publish_state: str = "pr"
    elif branch:
        publish_state = "local"
    else:
        publish_state = "none"

    return Ledger(
        files_changed=files_changed,
        commands_run=commands_run,
        commits=commits,
        publish_state=publish_state,
    )


# ── status_line ───────────────────────────────────────────────────


def _format_elapsed(seconds: float) -> str:
    """Format elapsed seconds as a compact human string."""
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m{s:02d}s"
    if m:
        return f"{m}m{s:02d}s"
    return f"{total}s"


def status_line(
    state: RunState,
    *,
    step: int,
    max_steps: Optional[int],
    elapsed_seconds: Optional[float],
    phase: Optional[str] = None,
) -> str:
    """Compose the running status line.

    Segments joined with `` · ``:
    - phase (from *phase* arg if given, else ``state.phase``; omitted if empty)
    - step: ``"step {step}/{max_steps}"`` or ``"step {step}"`` when max_steps is None
    - current op: ``state.last_action`` if non-empty
    - elapsed: compact human string from *elapsed_seconds*; omitted if None
    """
    parts: list[str] = []

    # Phase segment.
    current_phase = phase if phase is not None else state.phase
    if current_phase:
        parts.append(current_phase)

    # Step segment.
    if max_steps is not None:
        parts.append(f"step {step}/{max_steps}")
    else:
        parts.append(f"step {step}")

    # Current op segment.
    if state.last_action:
        parts.append(state.last_action)

    # Elapsed segment.
    if elapsed_seconds is not None:
        parts.append(_format_elapsed(elapsed_seconds))

    return " · ".join(parts)
