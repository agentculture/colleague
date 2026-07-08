"""Watched-run presence — background presence at the work-path progress sink
(presence-default-everywhere arc, task t9).

``colleague work --background`` (and any other watched, non-session work item —
plain ``colleague work --watch``) has no local operator: no TTY, no session
loop. Today an armed senses config on such a run produces NO presence beats at
all — an attached ``colleague talk`` REPL sees only the raw cortex feed. This
module wires the front-agnostic :class:`~colleague.presence_engine.PresenceEngine`
(task t6) onto the SAME per-step progress-sink boundary every work item already
fires through (``colleague/loop.py``'s ``_emit_progress``/``_emit_phase``, #38 /
#206) — the identical boundary :class:`~colleague.cli._commands._tui_sink.
CockpitProgressSink` and the session's ``_WorkSink`` already consume — so an
armed run's acknowledgment + cadence-gated proactive updates land on the
file-based flight plane (:mod:`colleague.flight`) and are recorded on
``TaskResult.senses`` at finish.

``colleague/loop.py`` is UNCHANGED: every beat rides the existing progress-sink
callback, composed alongside whatever sink :func:`~colleague.cli._commands.
_tui_sink.build_progress` already produced (:func:`compose_presence_sink`, a
thin wrapper around that module's ``make_fanout``). No new thread, socket, or
subprocess consumer — the flight-plane writes are plain file I/O
(:mod:`colleague.flight`), the same primitive ``colleague talk`` already uses.

Gated on TWO conditions (both required, resolved once by :func:`build_watch_presence`):

1. senses is armed and not disarmed — :func:`colleague.config.resolve_presence_rung`
   resolves to something other than ``"off"`` (covers ``config.senses is None``,
   an explicit ``COLLEAGUE_PRESENCE=off``, and ``--cortex-only`` — which nulls
   ``config.senses`` before ``execute_work`` ever sees it).
2. the work item is a flight — ``task.watch`` is ``True`` (a background child
   force-arms this; a plain ``colleague work --watch`` gets it too).

A THIRD gate lives in the caller (``colleague/cli/_commands/work.py``
``execute_work``): this module is only invoked when no external cockpit sink was
supplied (i.e. NOT the interactive ``session``, which already runs its own
middle-manager lane — see the session's own presence methods in
``colleague/cli/_commands/session.py``). Wiring a second presence engine
there would double every ack/update, so ``execute_work`` only calls
:func:`build_watch_presence` when its own ``progress_sink`` parameter is
``None``.

Only the LOOP rung is implemented here (background has no fixed-beat-lane
equivalent — that lane is the session's own ack/update/talk methods, which stay
session-owned). An operator who explicitly configured ``COLLEAGUE_PRESENCE=beats``
still gets the loop-based engine on a watched background run rather than a
silent no-op; :data:`colleague.senses_loop.RUNG_OFF` is the only value this
module treats as genuinely off.

Honest limit (discovered building this task, pre-existing and NOT introduced
here): ``colleague work``/``drive`` always run worktree-isolated (#196/#201),
so every flight file this module reads/writes is keyed off ``task.repo_path``
— the throwaway ``.colleague/worktrees/iso-<id>/`` checkout, NOT the operator's
outer repo. That is also where ``colleague/loop.py``'s own ``_arm_flight`` /
``_fold_flight_chat`` already resolve, so this module's beats DO fold onto the
artifact correctly. But it means an operator running ``colleague flight
status``/``colleague talk`` against their OWN top-level ``--repo`` will not
find the live feed/chat files during the run (they are nested one level
down) — a gap in the flight-piloting <-> write-isolation interaction that
predates this task and is not fixed here (out of scope for t9); see the
task-t9 report for the concrete repro.

Sibling for the UN-watched foreground case (task t10): :func:`build_foreground_presence`
is the mirror image for a plain ``colleague work "<task>"`` invocation — no
``--watch``, no session — which has no flight plane at all to render onto
(there is nothing for ``colleague flight``/``colleague talk`` to attach to). It
shares the senses-armed gate above but is invoked only when ``task.watch`` is
``False`` (the exact inverse of :func:`build_watch_presence`'s gate, so the two
builders are mutually exclusive by construction — a work item is never
double-presenced), and renders every ack/update line through a caller-supplied
callback straight to stderr (``colleague/cli/_commands/work.py`` wires
``emit_diagnostic``) instead of the flight chat log. Because presence rides
stderr and a work item's machine-parseable result always rides stdout
(``colleague/cli/_output.py``'s stdout/stderr split), a ``--json`` invocation's
stdout stays byte-for-byte parseable regardless of whether this lane fires.
"""

from __future__ import annotations

import json
import os
import time
from contextlib import suppress
from pathlib import Path
from typing import Any, Callable, Optional

from colleague import flight
from colleague.cli._commands._tui_sink import ProgressSink, make_fanout
from colleague.config import EngineConfig, resolve_presence_rung
from colleague.contract import ContextPacket, SensesBlock, SensesRecord, Task, TaskResult
from colleague.presence import UpdateCadence, cadence_from_env
from colleague.presence_engine import PresenceEngine, PresenceIO, build_presence_executor
from colleague.senses import senses_engine_config
from colleague.senses_loop import RUNG_LOOP, SensesLoopDriver

_FEED_TAIL_LINES = 40
#: Mode recorded on a freshly-created SensesBlock when this module is the
#: first to touch ``result.senses`` — mirrors ``colleague/loop.py``'s
#: ``_fold_flight_chat`` (``mode="cortex-only"``): a background run does not
#: run text intake (one-shot ``work`` bypasses that, per the cortex/senses arc's
#: q1 decision), so it is never ``"split"``.
_BLOCK_MODE = "cortex-only"


def _feed_tail(repo: Path, task_id: str, lines: int = _FEED_TAIL_LINES) -> str:
    """Return the last *lines* lines of the flight feed, or ``""`` if absent.

    Mirrors ``colleague/cli/_commands/talk.py``'s ``_tail_feed`` — the same
    read a live ``colleague talk`` attach uses to ground a turn.
    """
    fp = flight.feed_path(repo, task_id)
    if not fp.exists():
        return ""
    try:
        content = fp.read_text().splitlines()
    except OSError:
        return ""
    return "\n".join(content[-lines:])


def _last_task_state(repo: Path, task_id: str) -> "Optional[dict[str, Any]]":
    """A short ``{step_index, tool}`` snapshot from the last parseable feed record.

    ``None`` when the feed is absent/empty/unparseable throughout — mirrors
    ``colleague/cli/_commands/talk.py``'s ``_last_task_state``.
    """
    fp = flight.feed_path(repo, task_id)
    if not fp.exists():
        return None
    try:
        lines = fp.read_text().splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError:  # json.JSONDecodeError is a ValueError subclass
            continue
        if isinstance(record, dict):
            return {"step_index": record.get("step_index"), "tool": record.get("tool")}
    return None


def _render_to_flight(repo: Path, task_id: str, line: str) -> None:
    """Append one presence beat to the flight chat log (readable by an attach).

    Best-effort: a write failure must never disturb the run (the caller also
    wraps every presence call in ``suppress``, but this stays defensive on its
    own since it is the one place doing real file I/O per beat).
    """
    with suppress(Exception):
        flight.append_chat(repo, task_id, {"text": line, "at": time.time()})


def _guide_cortex(repo: Path, task_id: str, text: str) -> None:
    """Relay a ``guide_cortex`` move's text into the real flight guidance channel.

    The running cortex loop applies pending guidance at its next tool-call
    boundary (``colleague/loop.py``'s ``_apply_pending_guidance``) — the SAME
    channel an attached ``colleague talk`` operator's relay uses.
    """
    with suppress(Exception):
        flight.append_guidance(repo, task_id, text)


def ack_packet_for_task(task: Task) -> ContextPacket:
    """The :class:`ContextPacket` fed to the ack boundary before cortex's first step.

    Reuses ``task.context_packet`` when the run already carries one (senses
    intake ran on this task); otherwise synthesizes a minimal packet from the
    operator's verbatim instruction — a one-shot ``colleague work`` bypasses
    text intake (q1), so there is usually no packet yet, but the ack still needs
    the real request to acknowledge.
    """
    packet = getattr(task, "context_packet", None)
    if packet is not None:
        return packet
    return ContextPacket(original=task.instruction)


def build_watch_presence(
    *, task: Task, config: EngineConfig, engine: Any
) -> Optional[PresenceEngine]:
    """Build the presence engine for a watched work item, or ``None`` (byte-identical).

    ``None`` when senses is unarmed / disarmed (``resolve_presence_rung`` resolves
    to ``"off"`` — covers ``config.senses is None``, ``COLLEAGUE_PRESENCE=off``,
    and ``--cortex-only``) or the work item is not a flight (``task.watch`` is
    ``False``) — the two gates the arc requires. *engine* is the SAME engine
    plugin instance already loaded for the cortex work item (mirrors
    ``colleague/cli/_commands/session.py``'s ``_senses_engine`` / ``talk.py``'s
    ``default_engine_seam``): its ``make_complete``/``make_count_tokens`` are
    called against a senses-targeted :class:`~colleague.config.SensesConfig`
    (never the main model), so a degraded/unimplemented ``make_complete`` (e.g.
    the ``mock`` engine) degrades the loop turn instead of raising (the c13
    ladder — never a crash).

    Deliberately keyed off ``task.repo_path``, NOT the caller's outer ``repo``
    variable: ``colleague work``/``drive`` always run worktree-isolated
    (#196/#201), so by the time ``execute_work`` reaches this call
    ``task.repo_path`` has already been swapped to the throwaway
    ``.colleague/worktrees/iso-<id>/`` checkout — the SAME path
    ``colleague/loop.py``'s ``_arm_flight``/``_fold_flight_chat`` resolve
    ``task.repo_path`` against internally. Writing anywhere else (e.g. the
    operator's outer repo) would land in a directory the loop itself never
    reads, silently orphaning every beat instead of folding it into
    ``TaskResult.senses`` at finish.
    """
    if not task.watch:
        return None
    if resolve_presence_rung(config, repo_path=task.repo_path) == "off":
        return None
    senses_config = senses_engine_config(config)
    if senses_config is None:  # defensive: resolve_presence_rung already implies this
        return None

    repo_path = Path(task.repo_path)
    task_id = task.id
    io = PresenceIO(
        # Cortex is already being driven by the surrounding execute_work call —
        # there is nothing left to "dispatch"; the ack chat entry still renders
        # regardless of what this callback does (see PresenceEngine._build_turn).
        dispatch_to_cortex=lambda _instruction: None,
        append_guidance=lambda text: _guide_cortex(repo_path, task_id, text),
        read_flight=lambda: _feed_tail(repo_path, task_id),
        render=lambda line: _render_to_flight(repo_path, task_id, line),
        # No local operator — an attach happens externally via `colleague talk`,
        # which runs its own turns against the same flight plane.
        poll_operator_input=lambda: None,
        feed_tail=lambda: _feed_tail(repo_path, task_id),
        task_state=lambda: _last_task_state(repo_path, task_id),
    )
    driver = SensesLoopDriver(
        senses_config=senses_config,
        make_complete=engine.make_complete,
        executor=build_presence_executor(io),
        make_count_tokens=engine.make_count_tokens(senses_config),
        initial_rung=RUNG_LOOP,
    )
    cadence: UpdateCadence = cadence_from_env(os.environ)
    return PresenceEngine(driver=driver, io=io, cadence=cadence)


def build_foreground_presence(
    *, task: Task, config: EngineConfig, engine: Any, render: Callable[[str], None]
) -> Optional[PresenceEngine]:
    """Build the presence engine for a plain, non-watched foreground work item (t10).

    ``colleague work "<task>"`` with no ``--watch`` and no session — the
    ordinary one-shot invocation — has no flight plane at all (the loop's
    ``_arm_flight`` only arms one for ``task.watch``), so this is the SIBLING to
    :func:`build_watch_presence` for the un-watched case: same two gates
    (senses armed, not disarmed) MINUS the "is a flight" requirement (inverted:
    only builds when the task is **not** watched — a watched run stays on the
    flight-plane path above, never doubled), and an IO that renders straight to
    the caller-supplied *render* callback (``colleague/cli/_commands/work.py``
    passes ``emit_diagnostic``, so every beat is a labeled ``senses:`` line on
    **stderr** — never stdout, so ``--json``'s machine-parseable result stays
    untouched regardless of this lane).

    A one-shot foreground run has no flight file to read/guide/dispatch through
    (there is no attached pilot, no local operator stdin to poll mid-turn), so
    every :class:`~colleague.presence_engine.PresenceIO` callback besides
    ``render`` is a genuine no-op: ``dispatch_to_cortex``/``append_guidance`` do
    nothing (cortex is already being driven by the surrounding
    ``execute_work`` call, same as the watched case), ``poll_operator_input``
    always returns ``None`` (no live stdin to poll), and ``read_flight``/
    ``feed_tail``/``task_state`` return empty — there is no feed to read.

    Returns ``None`` (byte-identical) when the run IS a flight (``task.watch``)
    — that case is :func:`build_watch_presence`'s — or when senses is
    unarmed/disarmed (``resolve_presence_rung`` resolves to ``"off"``, which
    covers ``config.senses is None``, ``COLLEAGUE_PRESENCE=off``, and
    ``--cortex-only``).
    """
    if task.watch:
        return None
    if resolve_presence_rung(config, repo_path=task.repo_path) == "off":
        return None
    senses_config = senses_engine_config(config)
    if senses_config is None:  # defensive: resolve_presence_rung already implies this
        return None

    io = PresenceIO(
        # Cortex is already being driven by the surrounding execute_work call —
        # nothing left to "dispatch"; the ack chat entry still renders regardless.
        dispatch_to_cortex=lambda _instruction: None,
        append_guidance=lambda _text: None,
        read_flight=lambda: "",
        render=render,
        # No local operator stdin for a one-shot foreground run.
        poll_operator_input=lambda: None,
        feed_tail=lambda: "",
        task_state=lambda: None,
    )
    driver = SensesLoopDriver(
        senses_config=senses_config,
        make_complete=engine.make_complete,
        executor=build_presence_executor(io),
        make_count_tokens=engine.make_count_tokens(senses_config),
        initial_rung=RUNG_LOOP,
    )
    cadence: UpdateCadence = cadence_from_env(os.environ)
    return PresenceEngine(driver=driver, io=io, cadence=cadence)


def presence_progress_sink(presence: PresenceEngine) -> ProgressSink:
    """Return a ``ProgressSink`` that drives *presence* at every sink boundary.

    Maintains its OWN monotonic step counter (incremented only on a REAL step —
    a phase notice, encoded with an empty ``tool`` name per #206, never advances
    it) so this composes with either the plain default sink or the live-cockpit
    sink without depending on either's internal state. Mirrors the session's
    own proactive-update phase-changed detection: a phase notice's
    ``target`` carries the phase label, and only a CHANGED label counts.

    Never raises: a presence failure must never disturb the surrounding work
    item (narration is observability, not control — the same fail-safe as
    every other progress sink).
    """
    state: "dict[str, Any]" = {"step_count": 0, "last_phase": None}

    def _sink(step_index: int, tool: str, target: str, ok: bool) -> None:  # noqa: ARG001
        with suppress(Exception):
            if not tool:
                phase_changed = target != state["last_phase"]
                state["last_phase"] = target
                presence.on_progress_boundary(
                    step_count=state["step_count"], phase_changed=phase_changed
                )
                return
            state["step_count"] += 1
            presence.on_progress_boundary(step_count=state["step_count"], phase_changed=False)

    return _sink


def compose_presence_sink(sink: ProgressSink, presence: PresenceEngine) -> ProgressSink:
    """Fan *sink* out alongside the presence progress sink, per-sink isolated.

    Thin wrapper around ``colleague.cli._commands._tui_sink.make_fanout`` so
    ``work.py`` need not import it directly for this one composition.
    """
    return make_fanout([sink, presence_progress_sink(presence)])


def fold_presence_snapshot(result: TaskResult, presence: PresenceEngine) -> None:
    """Fold *presence*'s cost/injection records onto ``result.senses`` (t9).

    Mirrors ``colleague/cli/_commands/session.py``'s ``_finalize_split_run``
    merge pattern: init-on-first (``SensesBlock(mode="cortex-only", ...)``),
    then extend rather than replace.

    Deliberately does NOT fold ``snapshot()["chat"]`` here: this module's
    ``render`` callback already appends every chat-shaped beat to the SAME
    flight chat log ``colleague/loop.py``'s existing ``_fold_flight_chat``
    reads at finish (before the reap) — folding it a second time here would
    duplicate every ack/update in the artifact. ``records`` (the cost/latency/
    degraded facts backing the "cap-bounded, always recorded" acceptance) and
    ``injections`` have no other path onto the artifact, so they ARE merged
    here, directly from :meth:`~colleague.presence_engine.PresenceEngine.snapshot`.

    A no-op (never raises) when *presence* produced nothing at all — a run
    where every completion degraded before producing even one record still
    calls this safely.
    """
    with suppress(Exception):
        snap = presence.snapshot()
        records: "list[SensesRecord]" = list(snap.get("records") or [])
        injections: "list[dict[str, Any]]" = list(snap.get("injections") or [])
        if not records and not injections:
            return
        if result.senses is None:
            result.senses = SensesBlock(mode=_BLOCK_MODE, packet=None, records=[])
        if records:
            result.senses.records = list(result.senses.records) + records
        if injections:
            result.senses.injections = list(result.senses.injections) + injections
