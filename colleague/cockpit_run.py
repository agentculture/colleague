"""Pure run-state + ledger module for cockpit UX.

Folds progress events into a :class:`RunState` and reconciles an authoritative
post-run :class:`Ledger` from a :class:`TaskResult`.  No I/O, no threads, no
clock reads — all timestamps and elapsed values are passed in by the caller.
"""

from __future__ import annotations

import re
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

    NOTE (#285 / agentfront#51): ``step``, ``max_steps`` and ``elapsed_seconds``
    are caller-INJECTED because agentfront's ``WorkItem`` carries only
    ``step_count`` today — not the step cap nor a start stamp — and the session is
    thread-free (elapsed is event-stamped at sink boundaries, never a clock
    thread). Upstream ask to make ``step N/max`` + elapsed structural on
    ``WorkItem``: https://github.com/agentculture/agentfront/issues/51
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


# ── Delta tail (feels-alive arc, task t6) ───────────────────────────

# Deliberately NOT importing ``agentfront.taui.colors.strip_ansi`` here even
# though it does the same job (``_tui_sink.py`` already imports it): this
# module is pinned agentfront-free by ``tests/test_cockpit_run.py``'s
# ``TestModuleBoundary.test_no_agentfront_import`` (a genuine "pure module"
# boundary, predating this task), so the escape-stripper regex is duplicated
# here rather than forking/depending on agentfront's renderer layer.
#
# Terminal-control injection is NOT limited to CSI (Qodo #318 review, comment
# 3560546638): a model-emitted OSC (``ESC]52;…`` writes the CLIPBOARD; title
# changes, hyperlinks) or a bare Fe escape must never reach the operator's
# terminal through the streamed tail. The stripper removes, in one pass:
# CSI (``ESC[…final``, incl. the 8-bit ``\x9b`` form), OSC (``ESC]…`` up to
# BEL or ST), and single-character Fe escapes (``ESC @-_``). Belt-and-braces,
# ``sanitize_delta_chunk`` then drops any RESIDUAL C0 control byte (a
# sequence split across two delta chunks leaves a dangling ``ESC`` that no
# complete-sequence regex can classify) — no control byte ever survives.
_ANSI_RE = re.compile(
    r"(?:\x1b\[|\x9b)[0-9;?]*[ -/]*[@-~]"  # CSI (7-bit and 8-bit forms)
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?"  # OSC, BEL/ST-terminated or dangling
    r"|\x1b[@-_]"  # single-character Fe escapes
)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\x9b]")
_NEWLINE_RE = re.compile(r"[\r\n]+")

#: Trailing window of streamed text kept for display (characters). Display
#: only — never the full accumulated turn, never persisted.
DELTA_TAIL_CHARS = 80

#: Repaint throttle: fold+redraw at most once per this many accumulated
#: characters — never a per-token/per-chunk full-screen repaint.
DELTA_REPAINT_THRESHOLD = 48


@dataclass(frozen=True)
class DeltaTail:
    """Accumulated in-progress generation text for ONE completion turn.

    Display-only: a trailing window of the current turn's streamed answer.
    Reset (a fresh ``DeltaTail()``) whenever the next real step/phase event
    arrives — a delta never becomes a work step or a feed line (the same
    #206 invariant ``fold_phase`` holds for a phase notice), and a fresh
    completion always starts a fresh tail.
    """

    text: str = ""
    pending_chars: int = 0


def sanitize_delta_chunk(chunk: str) -> str:
    """Sanitize ONE streamed delta chunk for safe single-line display.

    Strips terminal escape sequences — CSI (7- and 8-bit), OSC (clipboard/
    title/hyperlink injection), and single-character Fe escapes — collapses
    any run of CR/LF into a single space (a raw newline would visually break
    the one-line STATUS surface), then drops any residual C0 control byte so
    a sequence split across chunk boundaries can never leak a live ``ESC``
    to the terminal. Pure — no I/O.
    """
    return _CONTROL_RE.sub("", _NEWLINE_RE.sub(" ", _ANSI_RE.sub("", chunk)))


def fold_delta(tail: DeltaTail, chunk: str, *, width: int = DELTA_TAIL_CHARS) -> DeltaTail:
    """Fold ONE streamed delta chunk onto *tail* (pure — never mutates *tail*).

    Sanitizes *chunk* first (:func:`sanitize_delta_chunk`), appends it, and
    keeps only the trailing *width* characters — a display "tail", not an
    accumulating log. ``pending_chars`` counts characters folded since the
    last repaint (:func:`should_repaint_delta`); cleared separately by
    :func:`mark_delta_rendered` so a caller can throttle repaints without
    losing already-accumulated tail text.
    """
    sanitized = sanitize_delta_chunk(chunk)
    combined = (tail.text + sanitized)[-width:] if width > 0 else ""
    return DeltaTail(text=combined, pending_chars=tail.pending_chars + len(sanitized))


def should_repaint_delta(tail: DeltaTail, *, threshold: int = DELTA_REPAINT_THRESHOLD) -> bool:
    """Whether *tail* has accumulated enough pending characters to repaint.

    Count-based throttling only — no clock, no timer (the feels-alive arc's
    constraint: a slow/fast stream repaints at the same CADENCE of
    characters, never a wall-clock cadence).
    """
    return tail.pending_chars >= threshold


def mark_delta_rendered(tail: DeltaTail) -> DeltaTail:
    """Return *tail* with its repaint counter cleared (pure) — a repaint just
    happened, so the next one waits for another *threshold* worth of chars."""
    return DeltaTail(text=tail.text, pending_chars=0)


def delta_status_message(tail: DeltaTail) -> str:
    """Compose the STATUS-surface message for a live-generating *tail*.

    Reads ``generating… <tail text>`` (or the bare prefix while the tail is
    still empty) — folded onto the SAME status surface a phase notice uses
    (:func:`fold_phase` in ``colleague/cli/_commands/_tui_sink.py``), never a
    new renderer surface.
    """
    return f"generating… {tail.text}" if tail.text else "generating…"
