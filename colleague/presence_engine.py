"""Front-agnostic presence engine (presence-default-everywhere arc, task t6).

ONE pump every surface shares. The interactive session, the ``colleague talk``
attach, a background run's progress sink, and the mesh resident all drive the
SAME middle-manager beats — acknowledge, proactive update, clarify, relay
guidance, converse — through this engine, so the "talking to one colleague" feel
is identical on every front (c4). It assumes NO TTY, NO thread, and NO clock: all
I/O rides injected callbacks (:class:`PresenceIO`), and the update cadence is
step/phase-based (:mod:`colleague.presence`), never timer-based.

Both lanes of the degradation ladder live BEHIND the engine, but the engine does
not route between them itself — it hands every boundary to the t5
:class:`~colleague.senses_loop.SensesLoopDriver`, which owns the rung state
machine (``loop`` → ``beats`` → ``off``, selected per the t4 config at
construction and degraded internally). The engine only:

- polls the operator for input at a boundary and, when they spoke, routes it as
  an operator turn (their words reach cortex verbatim via the driver);
- otherwise cadence-gates a proactive update (the capped-is-recorded rule lives
  here, h4);
- renders each returned :class:`~colleague.senses_loop.LoopTurn` to the operator
  through the injected renderer (the guidance injection / cortex dispatch / flight
  read happen inside the executor callbacks, bound to the same IO).

The engine imports NO front module (session / talk / resident) — the adapters
depend on it, never the reverse (pinned by an import-graph test), so the fronts
never import each other through it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from colleague.contract import ContextPacket, SensesRecord
from colleague.presence import UpdateCadence, should_update
from colleague.senses_loop import (
    BOUNDARY_CADENCE_TICK,
    BOUNDARY_OPERATOR_INPUT,
    LoopTurn,
    SensesLoopDriver,
    SensesMoveExecutor,
)


def _noop_render(_line: str) -> None:  # pragma: no cover - trivial default
    return None


def _noop_poll() -> Optional[str]:  # pragma: no cover - trivial default
    return None


def _noop_narrate(_line: str) -> None:  # pragma: no cover - trivial default
    return None


@dataclass
class PresenceIO:
    """The injected I/O surface a front supplies to the engine.

    Every field is a plain callable — no TTY, thread, socket, or clock is
    implied. A front that lacks a capability leaves the default no-op in place
    (an unarmed / watch-only surface stays a strict no-op).

    - ``dispatch_to_cortex(instruction)`` — hand a work instruction to cortex
      (the front starts / continues the cortex work item; senses never acts).
    - ``append_guidance(text)`` — inject relay guidance into the running cortex
      loop (the flight-plane guidance appender; the c19 operator-only call site).
    - ``read_flight()`` — return the run's current status / feed for a
      ``read_flight`` move.
    - ``render(line)`` — display one senses line to the operator (a labeled
      ``senses:`` line, a mesh reply, a stderr line — the front decides).
    - ``poll_operator_input()`` — return any pending operator text (non-blocking),
      else ``None``.
    - ``feed_tail()`` — the recent flight-feed tail to ground a boundary.
    - ``task_state()`` — a short run snapshot (step / phase / last tool).
    - ``narrate(line)`` — OPTIONAL text-to-speech narration of a rendered
      presence line (ack / update / reply — task t12, decision c17). The
      default is a no-op, so an unwired front stays byte-identical. A front
      that wants voice builds this callable via
      :func:`colleague.voice.build_presence_narrator` (or its own thin
      wrapper — e.g. the resident's file-link variant) and passes it in; the
      ENGINE is the only thing that ever calls it, right after ``render``, so
      no front needs its own "narrate after render" glue. Narration is
      STRICTLY ADDITIVE: the engine swallows any exception this raises, so a
      failed/absent synthesis (the reference rig's tts proxy currently 502s)
      can never alter the rendered text path.
    """

    dispatch_to_cortex: Callable[[str], Any] = lambda _instruction: None
    append_guidance: Callable[[str], Any] = lambda _text: None
    read_flight: Callable[[], Any] = lambda: ""
    render: Callable[[str], None] = _noop_render
    poll_operator_input: Callable[[], Optional[str]] = _noop_poll
    feed_tail: Callable[[], Any] = lambda: ""
    task_state: Callable[[], Any] = lambda: None
    narrate: Callable[[str], None] = _noop_narrate


def build_presence_executor(io: PresenceIO) -> SensesMoveExecutor:
    """Bind the six coordination callbacks to *io* (task t6).

    ``dispatch_to_cortex`` / ``guide_cortex`` / ``read_flight`` perform the real
    IO side-effects; ``reply_to_operator`` / ``clarify`` are no-ops here because
    the ENGINE renders their operator-facing text from the move's chat entry (so
    a reply is displayed exactly once). ``wait`` defaults to a no-op inside the
    executor.
    """
    return SensesMoveExecutor(
        dispatch_to_cortex=io.dispatch_to_cortex,
        guide_cortex=io.append_guidance,
        read_flight=io.read_flight,
        reply_to_operator=lambda _text: None,
        clarify=lambda _question: None,
    )


class PresenceEngine:
    """Drive the middle-manager beats for one work item, front-agnostically.

    Constructed with the resolved :class:`~colleague.senses_loop.SensesLoopDriver`
    (whose rung was chosen per the t4 config and whose ``fixed_beat_handler`` the
    front wired for the ``beats`` rung), the injected :class:`PresenceIO`, and the
    update :class:`~colleague.presence.UpdateCadence`. Optional
    ``history_provider`` threads the session's rolling history into every senses
    call.

    Every method is a strict no-op when the driver's rung is ``off`` (senses
    unarmed / ``--cortex-only``) — byte-identical to a pre-arc front.
    """

    def __init__(
        self,
        *,
        driver: SensesLoopDriver,
        io: PresenceIO,
        cadence: Optional[UpdateCadence] = None,
        history_provider: "Optional[Callable[[], Optional[list[dict[str, str]]]]]" = None,
    ) -> None:
        self._driver = driver
        self._io = io
        self._cadence = cadence if cadence is not None else UpdateCadence()
        self._history_provider = history_provider
        self._packet: Optional[ContextPacket] = None

        # Cadence bookkeeping (step/phase-based — no clock).
        self._last_update_step = 0
        self._updates_sent = 0
        self._capped_recorded = False
        # Engine-level artifact entries (the capped notice), merged in snapshot.
        self._engine_chat: "list[dict[str, Any]]" = []

    @property
    def active(self) -> bool:
        """True iff the presence lane is armed (the driver is not on the off rung)."""
        return self._driver.rung != "off"

    @property
    def rung(self) -> str:
        return self._driver.rung

    # ── the beats ─────────────────────────────────────────────────────────────
    def acknowledge(self, packet: Optional[ContextPacket]) -> "list[LoopTurn]":
        """The acknowledgment beat — runs before cortex's first step.

        Feeds the operator's original request as an operator-input boundary so the
        armed lane acknowledges (and, on the loop rung, hands the verbatim
        instruction to cortex via the dispatch callback). A no-op when inactive.
        """
        self._packet = packet
        if not self.active:
            return []
        spoken = getattr(packet, "original", "") if packet is not None else ""
        boundary = self._boundary(BOUNDARY_OPERATOR_INPUT, operator_input=spoken or None)
        return self._drive(boundary)

    def on_operator_message(self, text: str) -> "list[LoopTurn]":
        """Route an explicit operator message (their words reach cortex verbatim)."""
        if not self.active or not (text or "").strip():
            return []
        boundary = self._boundary(BOUNDARY_OPERATOR_INPUT, operator_input=text)
        return self._drive(boundary)

    def on_progress_boundary(
        self, *, step_count: int = 0, phase_changed: bool = False
    ) -> "list[LoopTurn]":
        """Process one cortex progress boundary: poll input, else cadence-gate.

        Operator input takes priority (a live message is answered immediately);
        otherwise a proactive update fires only when the cadence says so, bounded
        by the per-run cap. Hitting the cap is recorded ONCE, never silent (h4).
        """
        if not self.active:
            return []
        # 1. A live operator message wins over a proactive update.
        pending = self._io.poll_operator_input()
        if pending is not None and pending.strip():
            return self.on_operator_message(pending)

        # 2. Cadence-gated proactive update.
        fire, reason = should_update(
            self._cadence,
            step_count=step_count,
            last_update_step=self._last_update_step,
            phase_changed=phase_changed,
            updates_sent=self._updates_sent,
        )
        if reason == "cap":
            if not self._capped_recorded:
                self._capped_recorded = True
                self._engine_chat.append({"kind": "update", "capped": True, "at": time.time()})
                self._io.render(
                    "senses: (update cap reached — staying quiet now; "
                    "COLLEAGUE_SENSES_UPDATE_CAP raises it)"
                )
            return []
        if not fire:
            return []
        # A fired attempt consumes budget whether or not it produces text — count
        # it either way (honest cadence accounting, mirroring the session).
        self._updates_sent += 1
        self._last_update_step = step_count
        boundary = self._boundary(BOUNDARY_CADENCE_TICK)
        return self._drive(boundary)

    # ── artifact ──────────────────────────────────────────────────────────────
    def snapshot(self) -> "dict[str, Any]":
        """The accumulated SensesBlock fields for this work item.

        Merges the driver's records/chat/injections with the engine-level entries
        (the capped notice). Shapes match the shared SensesBlock (t3) so any front
        folds them identically.
        """
        return {
            "records": list(self._driver.records),
            "chat": list(self._driver.chat) + list(self._engine_chat),
            "injections": list(self._driver.injections),
        }

    @property
    def records(self) -> "list[SensesRecord]":
        return list(self._driver.records)

    # ── internals ─────────────────────────────────────────────────────────────
    def _boundary(self, kind: str, *, operator_input: Optional[str] = None):
        from colleague.senses_loop import BoundaryContext  # local: avoid a cycle at import

        return BoundaryContext(
            kind=kind,
            operator_input=operator_input,
            feed_tail=self._io.feed_tail(),
            packet=self._packet,
            task_state=self._io.task_state(),
        )

    def _history(self) -> "Optional[list[dict[str, str]]]":
        if self._history_provider is None:
            return None
        try:
            return self._history_provider()
        except Exception:
            return None

    def _drive(self, boundary) -> "list[LoopTurn]":
        turns = self._driver.process_boundary(boundary, history=self._history())
        for turn in turns:
            self._render_turn(turn)
        return turns

    def _render_turn(self, turn: LoopTurn) -> None:
        """Display one turn's operator-facing text (side-effects already applied).

        The cortex dispatch / guidance injection / flight read happened inside the
        executor callbacks; here the engine only renders what the operator sees.
        """
        entry = turn.chat_entry
        if entry is not None:
            # ack / clarify carry "text"; a talk entry carries "answer".
            text = str(entry.get("text") or entry.get("answer") or "").strip()
            if text:
                self._io.render(f"senses: {text}")
                self._narrate(text)
        if turn.injection is not None:
            relay = str(turn.injection.get("text") or "").strip()
            if relay:
                self._io.render(f"→ cortex: {relay}")

    def _narrate(self, text: str) -> None:
        """Best-effort tts narration of one rendered presence line (task t12).

        Runs strictly AFTER ``render`` and is deliberately over-defensive: any
        exception the injected ``narrate`` callback raises is swallowed here,
        on top of whatever degrade-never-raise contract the callback itself
        already carries (e.g. :func:`colleague.voice.synthesize`'s own
        never-raise guarantee) — so a failed/absent synthesis (the reference
        rig's tts proxy currently 502s) can NEVER disturb the text path this
        narrates, and the default no-op keeps every front that hasn't wired
        voice byte-identical.
        """
        try:
            self._io.narrate(text)
        except Exception:  # noqa: BLE001 - narration must never disturb the run
            pass
