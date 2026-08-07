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
from colleague.senses import (
    _FIDELITY_CLAUSE,
    _GROUNDING_CLAUSE,
    _TRUNCATION_NOTE,
    _enforce_fidelity,
    _fold_history,
    _TokenMeter,
    _window_text,
)
from colleague.senses_moves import (
    MOVE_CLARIFY,
    MOVE_DISPATCH_TO_CORTEX,
    MOVE_GUIDE_CORTEX,
    MOVE_NARRATE,
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
#: bounded by the cap. ``narrate`` is terminal (ssv t6, c23): a narration IS the
#: boundary's beat, so one boundary never issues a second completion for it —
#: the completion count stays exactly one per narrated boundary beat.
_TERMINAL_MOVES = frozenset(
    {MOVE_DISPATCH_TO_CORTEX, MOVE_REPLY_TO_OPERATOR, MOVE_CLARIFY, MOVE_WAIT, MOVE_NARRATE}
)

#: The verbatim user-facing narration label (ssv t6, c12/h9) — rendered by the
#: presence engine ahead of a ``narrate`` move's senses-authored text, on the
#: SAME feed-line surface presence lines use. Deliberately distinct from the
#: ``senses:`` prefix so the operator can always tell narration from senses'
#: own conversational replies (h9). This literal must NEVER be fed into any
#: model-bound prompt or stored on any artifact-bound record (c14/h11) — it is
#: display vocabulary only.
NARRATION_LABEL = "<<higher self thought>>"

#: The three-tier sibling of :data:`NARRATION_LABEL` (ssv t7, c13/h10). In
#: three-tier mode the acting seat is the WORKER (worker acts / senses relays /
#: cortex configures), so a ``narrate`` move describes worker activity — the
#: presence engine picks this label over the higher-self one at RENDER time,
#: from the config's three-tier state, mirroring its ``→ worker:`` relay-target
#: selection. Same discipline as NARRATION_LABEL (c14/h11): this literal must
#: NEVER be fed into any model-bound prompt or stored on any artifact-bound
#: record — display vocabulary only. Choosing it changes NOTHING about routing
#: or authority: narrate stays terminal + display-only either way.
WORKER_NARRATION_LABEL = "<subconscious thought/actions>"

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
    "plainly when you don't know. " + _GROUNDING_CLAUSE + " " + _FIDELITY_CLAUSE
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
    ``task_state`` a short caller-supplied snapshot. ``worker_answer`` (task
    t2) is the acting mind's ("today cortex's; the seat name is never
    hard-coded") current result for the current message, when the caller has
    one — CURRENT content, never folded history's "optional background".
    When present, a ``reply_to_operator`` move's displayed text is checked
    structurally to CONTAIN it verbatim (:func:`colleague.senses.
    _enforce_fidelity`), falling back to the raw ``worker_answer`` on a
    fidelity failure. ``None`` (the default) is byte-identical to before this
    field existed.

    ``delta_tail`` (ssv t6 — cortex narration) is a WINDOWED excerpt of the
    acting mind's live streamed output, captured by the front's ``on_delta``
    callback (buffering only — never a completion, c23) and handed to the beat
    as prompt-input for THIS boundary only: it is never accumulated into
    senses' history (stateless per beat, c14), and the assembled prompt is
    still windowed against senses' own budget. ``""`` (the default) is
    byte-identical to before this field existed and disables the ``narrate``
    move's rendering (nothing to describe).
    """

    kind: str
    operator_input: Optional[str] = None
    feed_tail: Any = ""
    packet: Optional[ContextPacket] = None
    task_state: Any = None
    worker_answer: Optional[str] = None
    delta_tail: str = ""


@dataclass
class LoopTurn:
    """The outcome of one loop turn — the SensesRecord plus any surfaced entry.

    ``record`` is always present (the artifact fact). ``chat_entry`` is a kind-ed
    chat dict (t3 mapping) for a move that speaks to the operator (ack / talk /
    clarify), else ``None``. ``injection`` is a ``{text, at, source}`` guidance
    dict for ``guide_cortex``, else ``None``. ``read_flight`` / ``wait`` carry
    neither — a record alone.

    ``narration`` (ssv t6) is a ``narrate`` move's senses-authored text —
    USER-DISPLAY ONLY (c14/h11): :meth:`SensesLoopDriver._absorb` deliberately
    never stores it (no chat entry, no injection, nothing artifact-bound), the
    presence engine renders it labeled and nothing else consumes it. ``None``
    for every other move.
    """

    move: str
    record: SensesRecord
    chat_entry: Optional[dict] = None
    injection: Optional[dict] = None
    outcome: Any = None
    refused: bool = False
    degraded: bool = False
    narration: Optional[str] = None


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
            move_obj, latency, tokens, degraded, truncated = self._one_completion(
                boundary, scratch, history
            )
            if degraded:
                record = SensesRecord(
                    point=f"{SENSES_LOOP_POINT_PREFIX}degraded",
                    latency=latency,
                    tokens=None,
                    degraded=True,
                    truncated=truncated,
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
                truncated=truncated,
            )
            turn = self._build_turn(move, move_obj, result, record, boundary, history)
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
    ) -> "tuple[Optional[dict[str, Any]], float, Optional[int], bool, bool]":
        """Issue ONE tools-off senses completion; return (move_obj, latency,
        tokens, degraded, truncated). Never raises: any failure degrades to
        ``(None, latency, None, True, False)``. ``truncated`` (task t2) is
        ``True`` iff the assembled prompt for THIS completion had to be
        windowed down to fit the send budget (:data:`colleague.senses.
        _TRUNCATION_NOTE` marker present)."""
        start = time.monotonic()
        meter = _TokenMeter()
        try:
            user_prompt = self._build_prompt(boundary, scratch, history)
            truncated = _TRUNCATION_NOTE in user_prompt
            # Tools-off ALWAYS: an explicit empty tool list, never ``None`` — a
            # senses loop turn structurally cannot carry a tool schema on the wire.
            complete = self._make_complete(self._senses_config, tools=[])
            simple = robust_simple_complete(meter.wrap(complete))
            raw = simple(_LOOP_SYSTEM_PROMPT, user_prompt)
            if not raw.strip():
                raise ValueError("empty senses loop completion")
            move_obj = parse_move(raw)  # never raises
            return move_obj, time.monotonic() - start, meter.value, False, truncated
        except Exception:
            return None, time.monotonic() - start, None, True, False

    @staticmethod
    def _boundary_steering(boundary: BoundaryContext) -> str:
        """Boundary-aware steering preamble (surfaced by the live rig proof):
        at a cadence tick / feed change the operator did NOT speak and cortex
        is ALREADY working the dispatched task — senses must narrate progress,
        never re-dispatch (a smaller senses model otherwise re-picks
        dispatch_to_cortex every boundary and the operator only ever hears
        the dispatch notice instead of real progress)."""
        if boundary.kind == BOUNDARY_OPERATOR_INPUT:
            return (
                "The operator just spoke. If this is a new task, dispatch it to cortex; "
                "if it is a question or guidance about the running work, reply or guide."
            )
        return (
            "Cortex is ALREADY working on the dispatched task (no new operator message). "
            "Narrate its current progress to the operator with reply_to_operator, grounded "
            "in the recent feed below — or wait if nothing new has happened. Do NOT dispatch "
            "again and do NOT invent progress."
        )

    def _build_prompt(
        self,
        boundary: BoundaryContext,
        scratch: "list[tuple[str, str]]",
        history: "Optional[list[dict[str, str]]]",
    ) -> str:
        counter = self._count_tokens if self._count_tokens is not None else count_tokens_chars
        budget = self._senses_config.context_budget_tokens  # type: ignore[union-attr]

        parts: "list[str]" = [self._boundary_steering(boundary)]
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
        if boundary.worker_answer:
            # CURRENT content (task t2), never folded history's "optional
            # background" — the result a reply_to_operator move must answer
            # from FIRST, enforced structurally after the completion returns
            # (see _apply_fidelity), not left to this wording alone.
            parts.append(
                "Current result from the acting mind (answer from this "
                f"first): {boundary.worker_answer}"
            )
        if boundary.delta_tail:
            # Cortex narration input (ssv t6, c12/h9): a windowed excerpt of the
            # acting mind's live streamed output — prompt-input for THIS beat
            # only (never folded into history, c14). The narrate steering rides
            # here, gated on the excerpt's presence, so a boundary with nothing
            # to describe never prompts senses toward an invented narration.
            # NOTE (h11): no rendered-label literal in this wording — this text
            # is model-bound.
            parts.append(
                "Live output from the acting mind — a raw, windowed excerpt of "
                f"what it is generating RIGHT NOW: {boundary.delta_tail}"
            )
            parts.append(
                "You may use the narrate move to describe, in your OWN words, "
                "what this live output shows the acting mind doing — never copy "
                "or relabel the raw output itself."
            )
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
        history: "Optional[list[dict[str, str]]]" = None,
    ) -> LoopTurn:
        at = time.time()
        if result.refused:
            return LoopTurn(move=move, record=record, refused=True)

        chat_entry, injection, narration = self._move_effects(
            move, move_obj, boundary, history, record, at
        )
        return LoopTurn(
            move=move,
            record=record,
            chat_entry=chat_entry,
            injection=injection,
            outcome=result.outcome,
            degraded=record.degraded,
            narration=narration,
        )

    def _move_effects(
        self,
        move: str,
        move_obj: "dict[str, Any]",
        boundary: BoundaryContext,
        history: "Optional[list[dict[str, str]]]",
        record: SensesRecord,
        at: float,
    ) -> "tuple[Optional[dict[str, Any]], Optional[dict[str, Any]], Optional[str]]":
        """The operator-facing effects of one move (S3776 extraction of
        ``_build_turn``'s ladder): ``(chat_entry, injection, narration)``.
        ``MOVE_READ_FLIGHT`` / ``MOVE_WAIT`` -> record only, all three None."""
        if move == MOVE_DISPATCH_TO_CORTEX:
            raw_ack = str(move_obj.get("ack") or "").strip()
            ack = raw_ack or _DISPATCH_ACK_NOTICE
            return {"kind": "ack", "text": ack, "fixed": not raw_ack, "at": at}, None, None
        if move == MOVE_REPLY_TO_OPERATOR:
            text = str(move_obj.get("text") or "").strip()
            # Structural relay fidelity (task t2): when the boundary carries a
            # worker answer, the DISPLAYED text must contain it verbatim —
            # enforced here in code, never left to the prompt alone.
            text = self._apply_fidelity(text, boundary, history, record)
            # kind omitted -> implied "talk" (t3 mapping), the flight-talk shape.
            return {"message": boundary.operator_input or "", "answer": text, "at": at}, None, None
        if move == MOVE_CLARIFY:
            question = str(move_obj.get("question") or "").strip()
            return {"kind": "clarify", "role": "senses", "text": question, "at": at}, None, None
        if move == MOVE_GUIDE_CORTEX:
            guidance = str(move_obj.get("guidance") or "").strip()
            return None, {"text": guidance, "at": at, "source": "senses-loop"}, None
        if move == MOVE_NARRATE:
            # Cortex narration (ssv t6, c12/c14/h9): senses-AUTHORED description
            # of the acting mind's live output — USER-DISPLAY ONLY, carried on
            # ``LoopTurn.narration`` which ``_absorb`` deliberately never stores:
            # no chat entry (artifact-bound), no injection, no history. Without a
            # live-output excerpt at this boundary there is nothing to describe,
            # so the move degrades to record-only — a narration then would be
            # invention (h9), and on a front whose render surface persists (the
            # watched run's flight chat) an excerpt-less narrate could otherwise
            # leak a narration line into an artifact-bound channel (h11).
            text = str(move_obj.get("text") or "").strip()
            if text and str(boundary.delta_tail or "").strip():
                return None, None, text
        return None, None, None

    def _apply_fidelity(
        self,
        text: str,
        boundary: BoundaryContext,
        history: "Optional[list[dict[str, str]]]",
        record: SensesRecord,
    ) -> str:
        """Structural containment for a ``reply_to_operator`` move (task t2).

        A no-op (returns *text* unchanged, *record* untouched) when
        ``boundary.worker_answer`` is absent — the byte-identical path for
        every boundary that predates this arc. Otherwise delegates to
        :func:`colleague.senses._enforce_fidelity` and mutates *record* IN
        PLACE with the four additive counters
        (``verbatim_presence``/``knowledge_repetition``/``fallback``/
        ``degraded``) — the literal ``SensesRecord`` surface AC2 requires,
        not a side dict. "Knowledge" here is the boundary's folded rolling
        ``history`` text entries, mirroring :func:`run_senses_talk`'s use of
        the same signal.
        """
        knowledge_snippets = [
            entry.get("text") for entry in (history or []) if isinstance(entry, dict)
        ]
        final_text, verbatim_presence, knowledge_repetition, fallback = _enforce_fidelity(
            text, boundary.worker_answer, knowledge_snippets
        )
        record.verbatim_presence = verbatim_presence
        record.knowledge_repetition = knowledge_repetition
        record.fallback = fallback
        if fallback:
            # A fidelity failure IS a degradation, even though the move's own
            # callback may have succeeded (task t2, AC2).
            record.degraded = True
        return final_text

    def _absorb(self, turn: LoopTurn) -> None:
        # ``turn.narration`` is deliberately NOT absorbed (ssv t6, c14/h11):
        # narration is user-display only — it never lands in the driver's chat /
        # injections (both artifact-bound) nor anywhere a model prompt reads.
        # Only the text-free record (point ``senses-loop:narrate``) is kept.
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
