"""Senses' bounded coordination loop core (presence-default-everywhere, task t5).

Colleague drives with two lobes: **cortex** (drives the bounded tool loop — the
ONLY mind that touches the repo) and **senses** (a tools-off front door). This
arc gives senses its own bounded *agentic* loop so the operator converses with
it continuously while cortex works — the FOURTH sanctioned router-exclusion
increment. This module is that loop's CORE: a front-agnostic, I/O-free turn pump
driven entirely through injected callbacks. It wires nothing into any surface
(the presence engine — task t6 — and the fronts — t7–t11 — do that); it only
processes ONE boundary's worth of senses turns and records them.

The loop is "agentic" WITHOUT ever touching a tool schema on the wire: each turn
is one tools-off completion (``make_complete(senses_config, tools=[])``) whose
reply is a prompted-JSON coordination move (:mod:`colleague.senses_moves`).
Because the reference rig's served model has no server-side tool parser, "calling a
move" means the model writes a small JSON object — nothing tool-shaped ever goes
on the wire, preserving the structural pin every other senses call upholds.

The bounded pump, per boundary:

- A **per-boundary completion cap** (:data:`DEFAULT_LOOP_CAP`, env-tunable
  ``COLLEAGUE_SENSES_LOOP_CAP``) — senses may take at most that many moves at a
  boundary (e.g. read_flight → reply_to_operator), so a single boundary can never
  run away.
- Each completion is **windowed to senses' OWN context budget** via the existing
  ``count_tokens`` seam (reusing :func:`colleague.senses._window_text` /
  ``_fold_history``), exactly like :func:`colleague.senses.run_senses_talk`.
- Every move is **executed by the t1 executor** and **recorded** as a
  :class:`~colleague.contract.SensesRecord` (``point`` prefixed
  :data:`~colleague.contract.SENSES_LOOP_POINT_PREFIX`) plus a kind-ed chat entry
  (t3's move→shape mapping); a run where the loop never fires leaves the artifact
  byte-identical (records/chat/injections all empty → omit-when-empty).

The **degradation ladder** (c22 / h15) is a state machine held here:
``loop`` (this pump, default when armed) → ``beats`` (the fixed-beat lane —
intake/ack/update/talk as shipped, injected as ``fixed_beat_handler``) →
``off`` (cortex-only). A boundary whose loop turns all degrade (a dead/empty
senses endpoint) transitions ``loop → beats`` for the NEXT boundary and records
the transition (never silent). ``senses_config is None`` forces ``off`` at
construction — the cortex-only rung, byte-identical.

The **verbatim-to-cortex invariant** (h10): when the operator actually spoke at a
boundary, a ``dispatch_to_cortex`` / ``guide_cortex`` move carries their words
VERBATIM to cortex — senses' own phrasing is folded in as an appended refinement,
never a rewrite. The verbatim text is always present and first.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional

from colleague.config import EngineConfig
from colleague.context import count_tokens_chars
from colleague.contract import SENSES_LOOP_POINT_PREFIX, ContextPacket, SensesRecord
from colleague.plan.cli_driver import robust_simple_complete
from colleague.senses import _fold_history, _TokenMeter, _window_text
from colleague.senses_moves import (
    MOVE_CLARIFY,
    MOVE_DISPATCH_TO_CORTEX,
    MOVE_GUIDE_CORTEX,
    MOVE_READ_FLIGHT,
    MOVE_REPLY_TO_OPERATOR,
    MOVE_WAIT,
    SensesMoveExecutor,
    build_moves_instruction,
    parse_move,
)

# ── ladder rungs ────────────────────────────────────────────────────────────
RUNG_LOOP = "loop"
RUNG_BEATS = "beats"
RUNG_OFF = "off"
_RUNGS = (RUNG_LOOP, RUNG_BEATS, RUNG_OFF)

# ── boundary kinds ──────────────────────────────────────────────────────────
BOUNDARY_OPERATOR_INPUT = "operator_input"
BOUNDARY_CADENCE_TICK = "cadence_tick"
BOUNDARY_FEED_CHANGE = "feed_change"

#: Default per-boundary completion cap: at most this many senses moves per
#: boundary (e.g. read_flight then reply). Env-tunable via
#: :func:`loop_cap_from_env`.
DEFAULT_LOOP_CAP = 2

#: A move that concludes a boundary (nothing more to do this turn). ``read_flight``
#: and ``guide_cortex`` are NON-terminal — senses reads/guides then may reply,
#: bounded by the cap.
_TERMINAL_MOVES = frozenset(
    {MOVE_DISPATCH_TO_CORTEX, MOVE_REPLY_TO_OPERATOR, MOVE_CLARIFY, MOVE_WAIT}
)

#: Honest fixed acknowledgment when a dispatch move authored no operator-facing
#: ``ack`` — mirrors the session's ``_ACK_DISPATCH_NOTICE`` (never a fabricated
#: understanding, exactly the talking-to-one arc's honesty rail).
_DISPATCH_ACK_NOTICE = "taking your request to cortex now."

_LOOP_SYSTEM_PROMPT = (
    "You are the senses lobe for colleague — the coordinating front the operator "
    "talks to WHILE the cortex model does the actual repo work. You NEVER touch "
    "the repo yourself; cortex is the only mind that acts. Read the run context "
    "below and choose exactly ONE coordination move.\n\n"
    + build_moves_instruction()
    + "\n\nGuidance: when the operator hands you work, dispatch it to cortex "
    "carrying THEIR words — and include a short first-person 'ack' field "
    "acknowledging in your own words what you are handing off (no new claim, "
    "nothing the request does not already say). When they ask about the run, "
    "read the flight status and reply. Ground every move strictly in the given "
    "context — the operator's words, the task state, and the recent flight feed. "
    "Never invent progress, files, or results not present in the feed; say "
    "plainly when you don't know."
)


def loop_cap_from_env(env: Mapping[str, str]) -> int:
    """Resolve the per-boundary completion cap from the environment.

    Reads ``COLLEAGUE_SENSES_LOOP_CAP`` (positive int; absent or invalid falls
    back to :data:`DEFAULT_LOOP_CAP`). Never raises on a malformed value —
    mirrors :func:`colleague.presence.cadence_from_env`.
    """
    raw = env.get("COLLEAGUE_SENSES_LOOP_CAP")
    if raw is not None:
        try:
            val = int(raw)
            if val > 0:
                return val
        except (ValueError, OverflowError):
            pass
    return DEFAULT_LOOP_CAP


@dataclass
class BoundaryContext:
    """One boundary the loop is asked to process.

    ``kind`` is one of :data:`BOUNDARY_OPERATOR_INPUT` (the operator just spoke —
    ``operator_input`` carries their verbatim words), :data:`BOUNDARY_CADENCE_TICK`
    (a proactive-update tick), or :data:`BOUNDARY_FEED_CHANGE` (the run's feed
    advanced). ``feed_tail`` is the recent flight-feed lines (a string or a list),
    ``packet`` the run's :class:`~colleague.contract.ContextPacket`, and
    ``task_state`` a short caller-supplied snapshot.
    """

    kind: str
    operator_input: Optional[str] = None
    feed_tail: Any = ""
    packet: Optional[ContextPacket] = None
    task_state: Any = None


@dataclass
class LoopTurn:
    """The outcome of one loop turn — the SensesRecord plus any surfaced entry.

    ``record`` is always present (the artifact fact). ``chat_entry`` is a kind-ed
    chat dict (t3 mapping) for a move that speaks to the operator (ack / talk /
    clarify), else ``None``. ``injection`` is a ``{text, at, source}`` guidance
    dict for ``guide_cortex``, else ``None``. ``read_flight`` / ``wait`` carry
    neither — a record alone.
    """

    move: str
    record: SensesRecord
    chat_entry: Optional[dict] = None
    injection: Optional[dict] = None
    outcome: Any = None
    refused: bool = False
    degraded: bool = False


def _feed_to_text(feed: Any) -> str:
    if feed is None:
        return ""
    if isinstance(feed, str):
        return feed
    try:
        return "\n".join(str(line) for line in feed)
    except TypeError:
        return str(feed)


def _merge_verbatim(verbatim: str, refinement: str) -> str:
    """Return *verbatim* with *refinement* appended as an advisory note.

    The operator's words are always present and FIRST (h10: relay refines, never
    rewrites). A refinement equal to (or empty vs.) the verbatim text is dropped,
    so an echo never doubles the message.
    """
    verbatim = (verbatim or "").strip()
    refinement = (refinement or "").strip()
    if refinement and refinement != verbatim:
        return f"{verbatim}\n\n[senses refinement: {refinement}]"
    return verbatim


def _short(value: Any, limit: int = 80) -> str:
    text = str(value if value is not None else "")
    return text if len(text) <= limit else text[: limit - 1] + "…"


class SensesLoopDriver:
    """Bounded, front-agnostic senses coordination loop.

    Constructed once per work item with the resolved senses config, a
    ``make_complete`` factory (``make_complete(senses_config, tools=[])`` — the
    tools-off seam), a bound :class:`~colleague.senses_moves.SensesMoveExecutor`
    (its coordination callbacks are the front's I/O), and optional injected
    seams: ``make_count_tokens`` (the budget seam), ``fixed_beat_handler`` (the
    ladder's ``beats`` rung — a ``BoundaryContext -> list[LoopTurn]`` callable the
    front supplies, wrapping today's intake/ack/update lane), and
    ``on_rung_change`` (a ``(old, new, reason) -> None`` notice hook).

    :meth:`process_boundary` NEVER raises and never touches the repo. A
    ``senses_config`` of ``None`` pins the driver to :data:`RUNG_OFF` (cortex-only,
    byte-identical). Accumulated ``records`` / ``chat`` / ``injections`` mirror
    the :class:`~colleague.contract.SensesBlock` fields the caller folds onto
    ``TaskResult.senses`` at finish.
    """

    def __init__(
        self,
        *,
        senses_config: Optional[EngineConfig],
        make_complete: "Callable[..., Callable[[list[dict[str, Any]]], Any]]",
        executor: SensesMoveExecutor,
        make_count_tokens: "Optional[Callable[[list[dict[str, Any]]], int]]" = None,
        per_boundary_cap: int = DEFAULT_LOOP_CAP,
        fixed_beat_handler: "Optional[Callable[[BoundaryContext], list[LoopTurn]]]" = None,
        on_rung_change: "Optional[Callable[[str, str, str], None]]" = None,
        initial_rung: str = RUNG_LOOP,
    ) -> None:
        self._senses_config = senses_config
        self._make_complete = make_complete
        self._executor = executor
        self._count_tokens = make_count_tokens
        self._cap = max(1, int(per_boundary_cap))
        self._fixed_beat_handler = fixed_beat_handler
        self._on_rung_change = on_rung_change
        # senses unarmed forces off, whatever rung was requested (h1/h15).
        if senses_config is None:
            self._rung = RUNG_OFF
        else:
            self._rung = initial_rung if initial_rung in _RUNGS else RUNG_LOOP

        self.records: "list[SensesRecord]" = []
        self.chat: "list[dict[str, Any]]" = []
        self.injections: "list[dict[str, Any]]" = []

    @property
    def rung(self) -> str:
        return self._rung

    # ── ladder ──────────────────────────────────────────────────────────────
    def _transition(self, new_rung: str, reason: str) -> None:
        old = self._rung
        if old == new_rung:
            return
        self._rung = new_rung
        # The transition is an artifact fact (never silent, h15): a SensesRecord
        # tagged with the rung change; degraded when we fell to a lower rung.
        self.records.append(
            SensesRecord(
                point=f"senses-ladder:{old}->{new_rung}",
                degraded=(new_rung in (RUNG_BEATS, RUNG_OFF)),
            )
        )
        if self._on_rung_change is not None:
            try:
                self._on_rung_change(old, new_rung, reason)
            except Exception:  # nosec B110 - a notice hook must never disturb the run
                pass

    # ── entry point ──────────────────────────────────────────────────────────
    def process_boundary(
        self,
        boundary: BoundaryContext,
        *,
        history: "Optional[list[dict[str, str]]]" = None,
    ) -> "list[LoopTurn]":
        """Process one boundary; never raises, never touches the repo."""
        if self._rung == RUNG_OFF:
            return []
        if self._rung == RUNG_BEATS:
            return self._process_beats(boundary)
        return self._process_loop(boundary, history)

    def _process_beats(self, boundary: BoundaryContext) -> "list[LoopTurn]":
        if self._fixed_beat_handler is None:
            return []
        try:
            turns = self._fixed_beat_handler(boundary) or []
        except Exception:
            return []
        for turn in turns:
            self._absorb(turn)
        return list(turns)

    def _process_loop(
        self,
        boundary: BoundaryContext,
        history: "Optional[list[dict[str, str]]]",
    ) -> "list[LoopTurn]":
        turns: "list[LoopTurn]" = []
        scratch: "list[tuple[str, str]]" = []
        produced_success = False
        boundary_degraded = False

        for _ in range(self._cap):
            move_obj, latency, tokens, degraded = self._one_completion(boundary, scratch, history)
            if degraded:
                record = SensesRecord(
                    point=f"{SENSES_LOOP_POINT_PREFIX}degraded",
                    latency=latency,
                    tokens=None,
                    degraded=True,
                )
                self.records.append(record)
                turns.append(LoopTurn(move="degraded", record=record, degraded=True))
                boundary_degraded = not produced_success
                break

            assert move_obj is not None  # degraded is False here
            move = str(move_obj.get("move", MOVE_REPLY_TO_OPERATOR))
            # Enforce the verbatim-to-cortex invariant BEFORE executing, so the
            # injected dispatch/guide callback receives the operator's words.
            self._apply_verbatim(move_obj, boundary, move)
            result = self._executor.execute(move_obj)

            point_move = move if not result.refused else "refused"
            record = SensesRecord(
                point=f"{SENSES_LOOP_POINT_PREFIX}{point_move}",
                latency=latency,
                tokens=tokens,
                degraded=result.degraded,
            )
            turn = self._build_turn(move, move_obj, result, record, boundary)
            self._absorb(turn)
            turns.append(turn)

            if not (result.refused or result.degraded):
                produced_success = True
            scratch.append((move, self._summarize(move, result)))
            if move in _TERMINAL_MOVES and not result.refused:
                break

        if boundary_degraded:
            # The loop could not produce a usable move at this boundary — drop to
            # the fixed-beat lane for the NEXT boundary (never silent).
            self._transition(RUNG_BEATS, "loop-degraded")
        return turns

    # ── one tools-off completion ─────────────────────────────────────────────
    def _one_completion(
        self,
        boundary: BoundaryContext,
        scratch: "list[tuple[str, str]]",
        history: "Optional[list[dict[str, str]]]",
    ) -> "tuple[Optional[dict[str, Any]], float, Optional[int], bool]":
        """Issue ONE tools-off senses completion; return (move_obj, latency,
        tokens, degraded). Never raises: any failure degrades to
        ``(None, latency, None, True)``."""
        start = time.monotonic()
        meter = _TokenMeter()
        try:
            user_prompt = self._build_prompt(boundary, scratch, history)
            # Tools-off ALWAYS: an explicit empty tool list, never ``None`` — a
            # senses loop turn structurally cannot carry a tool schema on the wire.
            complete = self._make_complete(self._senses_config, tools=[])
            simple = robust_simple_complete(meter.wrap(complete))
            raw = simple(_LOOP_SYSTEM_PROMPT, user_prompt)
            if not raw.strip():
                raise ValueError("empty senses loop completion")
            move_obj = parse_move(raw)  # never raises
            return move_obj, time.monotonic() - start, meter.value, False
        except Exception:
            return None, time.monotonic() - start, None, True

    def _build_prompt(
        self,
        boundary: BoundaryContext,
        scratch: "list[tuple[str, str]]",
        history: "Optional[list[dict[str, str]]]",
    ) -> str:
        counter = self._count_tokens if self._count_tokens is not None else count_tokens_chars
        budget = self._senses_config.context_budget_tokens  # type: ignore[union-attr]

        parts: "list[str]" = []
        # Boundary-aware steering (surfaced by the live rig proof): at a cadence
        # tick / feed change the operator did NOT speak and cortex is ALREADY
        # working the dispatched task — so senses must narrate progress, never
        # re-dispatch. Without this, a smaller senses model re-picks
        # dispatch_to_cortex every boundary and the operator only ever hears the
        # dispatch notice instead of real progress.
        if boundary.kind == BOUNDARY_OPERATOR_INPUT:
            parts.append(
                "The operator just spoke. If this is a new task, dispatch it to cortex; "
                "if it is a question or guidance about the running work, reply or guide."
            )
        else:
            parts.append(
                "Cortex is ALREADY working on the dispatched task (no new operator message). "
                "Narrate its current progress to the operator with reply_to_operator, grounded "
                "in the recent feed below — or wait if nothing new has happened. Do NOT dispatch "
                "again and do NOT invent progress."
            )
        if boundary.operator_input:
            parts.append(f"Operator's live message (verbatim): {boundary.operator_input}")
        pkt = boundary.packet
        if pkt is not None:
            original = getattr(pkt, "original", "") or ""
            interpretation = getattr(pkt, "interpretation", "") or ""
            if original:
                parts.append(f"Operator's original request: {original}")
            if interpretation:
                parts.append(f"Senses' prior interpretation: {interpretation}")
        if boundary.task_state:
            parts.append(f"Current task state: {boundary.task_state}")
        if scratch:
            taken = "; ".join(f"{move}->{outcome}" for move, outcome in scratch)
            parts.append(f"Moves you already took this turn: {taken}")
        fixed_context = "\n".join(parts)

        # Window the WHOLE assembled body (fixed_context + feed) to the senses
        # budget, not just the feed: fixed_context can carry a large operator
        # message / interpretation / scratch, and _fold_history never trims the
        # primary body — so budgeting only the feed can't stop an oversized
        # prompt. This mirrors run_senses_update (which windows about+feed
        # together) and the #301 "budget the full prompt, not just the feed"
        # fix. Then fold history (which drops old history entries to fit).
        assembled = (
            f"{fixed_context}\n\nRecent flight feed (most recent last):\n"
            f"{_feed_to_text(boundary.feed_tail) or '(no feed yet)'}"
        )
        user_prompt = _window_text(
            assembled,
            system_prompt=_LOOP_SYSTEM_PROMPT,
            budget=budget,
            count_tokens=counter,
        )
        user_prompt = _fold_history(
            user_prompt,
            history,
            system_prompt=_LOOP_SYSTEM_PROMPT,
            budget=budget,
            count_tokens=counter,
        )
        return user_prompt

    # ── verbatim invariant + surfacing ───────────────────────────────────────
    def _apply_verbatim(
        self, move_obj: "dict[str, Any]", boundary: BoundaryContext, move: str
    ) -> None:
        """Rewrite the cortex-bound param to carry the operator's verbatim words.

        Applied only when the operator actually spoke at this boundary
        (``operator_input`` present). The model's own phrasing is folded in as an
        appended refinement (h10) — the verbatim words stay first and intact.
        """
        spoken = boundary.operator_input
        if not spoken:
            return
        if move == MOVE_DISPATCH_TO_CORTEX:
            move_obj["instruction"] = _merge_verbatim(spoken, str(move_obj.get("instruction", "")))
        elif move == MOVE_GUIDE_CORTEX:
            move_obj["guidance"] = _merge_verbatim(spoken, str(move_obj.get("guidance", "")))

    def _build_turn(
        self,
        move: str,
        move_obj: "dict[str, Any]",
        result: Any,
        record: SensesRecord,
        boundary: BoundaryContext,
    ) -> LoopTurn:
        at = time.time()
        if result.refused:
            return LoopTurn(move=move, record=record, refused=True)

        chat_entry: "Optional[dict[str, Any]]" = None
        injection: "Optional[dict[str, Any]]" = None

        if move == MOVE_DISPATCH_TO_CORTEX:
            raw_ack = str(move_obj.get("ack") or "").strip()
            ack = raw_ack or _DISPATCH_ACK_NOTICE
            chat_entry = {"kind": "ack", "text": ack, "fixed": not raw_ack, "at": at}
        elif move == MOVE_REPLY_TO_OPERATOR:
            text = str(move_obj.get("text") or "").strip()
            # kind omitted → implied "talk" (t3 mapping), the flight-talk shape.
            chat_entry = {"message": boundary.operator_input or "", "answer": text, "at": at}
        elif move == MOVE_CLARIFY:
            question = str(move_obj.get("question") or "").strip()
            chat_entry = {"kind": "clarify", "role": "senses", "text": question, "at": at}
        elif move == MOVE_GUIDE_CORTEX:
            guidance = str(move_obj.get("guidance") or "").strip()
            injection = {"text": guidance, "at": at, "source": "senses-loop"}
        # MOVE_READ_FLIGHT / MOVE_WAIT → record only, no operator-facing entry.

        return LoopTurn(
            move=move,
            record=record,
            chat_entry=chat_entry,
            injection=injection,
            outcome=result.outcome,
            degraded=result.degraded,
        )

    def _absorb(self, turn: LoopTurn) -> None:
        self.records.append(turn.record)
        if turn.chat_entry is not None:
            self.chat.append(turn.chat_entry)
        if turn.injection is not None:
            self.injections.append(turn.injection)

    @staticmethod
    def _summarize(move: str, result: Any) -> str:
        if result.refused:
            return "refused"
        if result.degraded:
            return "degraded"
        if move == MOVE_READ_FLIGHT:
            return f"flight={_short(result.outcome)}"
        return "ok"
