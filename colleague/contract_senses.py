"""Senses-lane record dataclasses split out of :mod:`colleague.contract`
(task t13, hard-1000-line-file-limit): :class:`ContextPacket`,
:class:`SensesRecord`, :class:`SensesDirectRecord`, and :class:`SensesBlock`
— the cortex/senses front-door records nested on ``TaskResult.senses`` (and
``Task.context_packet``). Re-exported from ``colleague.contract`` so every
existing ``from colleague.contract import ...`` call site resolves
unmodified.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from colleague.contract_coerce import _coerce_ack, _coerce_omissions

# Conventional ``chat[]`` entry ``"kind"`` values (talking-to-one arc, task t5;
# reaffirmed by the presence-default-everywhere arc, task t3): the ONE closed
# vocabulary every front draws from — ``"talk"`` (implied when the key is
# absent, today's pre-arc shape), ``"ack"`` (the intake acknowledgment),
# ``"update"`` (a proactive progress narration), and ``"clarify"`` (a
# clarifying question/answer exchange before dispatch). The senses
# coordination loop (``colleague/senses_moves.py``, tasks t1/t5) reuses this
# SAME set for its operator-facing moves — ``reply_to_operator`` folds as
# ``"talk"``, ``dispatch_to_cortex`` as ``"ack"``, ``clarify`` as
# ``"clarify"`` — rather than inventing a fifth kind. Its ``guide_cortex``
# move (a guidance relay) is NOT a chat entry at all; it folds into
# ``SensesBlock.injections`` instead, matching how the live-presence talk
# lane already records applied guidance. Its ``read_flight``/``wait`` moves
# are internal bookkeeping only — a ``SensesRecord`` (below), no chat entry.
# No front may grow its own record schema; import this constant rather than
# re-typing the literal strings.
SENSES_CHAT_KINDS: tuple[str, ...] = ("talk", "ack", "update", "clarify")

# Point-label prefix for the senses coordination loop's per-turn records
# (presence-default-everywhere arc, task t3, for tasks t1/t5 to consume): each
# loop turn is recorded as one ``SensesRecord`` with
# ``point=f"{SENSES_LOOP_POINT_PREFIX}{move}"`` (e.g.
# ``"senses-loop:dispatch_to_cortex"``) — no new field, no new record shape,
# just a naming convention that keeps per-move loop turns distinguishable from
# the fixed-beat points (``"senses-intake"``, ``"senses-update"``,
# ``"senses-talk"``, ...) sharing this SAME ``SensesRecord`` shape.
SENSES_LOOP_POINT_PREFIX = "senses-loop:"


@dataclass
class ContextPacket:
    """The senses model's interpretation of an operator's request (cortex/senses, t2).

    The "senses" model is a tools-off front door that reads the operator's
    *verbatim* request and produces a structured interpretation before the
    "cortex" model drives the loop. The packet rides the task contract as the
    optional ``Task.context_packet`` and is echoed back (serialized) inside the
    :class:`SensesBlock` on ``TaskResult.senses``.

    Fields
    ------
    original:
        The operator's verbatim original text. This must round-trip through
        JSON **byte-for-byte** — no normalization, no trimming — because it is
        the audit-trail record of exactly what was asked. (Only ``interpretation``
        is a derived/normalized reading; ``original`` is sacrosanct.)
    interpretation:
        What the senses model believes the request means — a normalized,
        possibly reworded reading of ``original``.
    confidence:
        The senses model's confidence in ``interpretation`` (typically 0.0-1.0).
    task_type:
        A short classification of the request (e.g. ``"bugfix"``, ``"feature"``,
        ``"docs"``).
    omissions:
        What the senses model judged the request left implicit or omitted —
        one short string per gap (e.g. ``"which file"``, ``"acceptance criteria"``).
    ack:
        The senses-authored acknowledgment line for this request — produced in
        the SAME intake completion as the rest of the packet (talking-to-one
        arc, task t5; the spec's ack-shape decision: zero extra calls, zero
        extra latency), rendered before cortex's first step. ``None`` when no
        ack was produced (a degraded intake, or a run that predates this
        field) — omitted from ``to_dict`` so a packet without an
        acknowledgment serializes byte-identically to before this field
        existed.
    """

    original: str
    interpretation: str = ""
    confidence: float = 0.0
    task_type: str = ""
    omissions: list[str] = field(default_factory=list)
    ack: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "original": self.original,
            "interpretation": self.interpretation,
            "confidence": self.confidence,
            "task_type": self.task_type,
            "omissions": list(self.omissions),
        }
        # ack gets the same omit-when-None treatment as the rest of the
        # contract's optional fields (talking-to-one arc, task t5): a packet
        # without an acknowledgment serializes byte-identically to before
        # this field existed.
        if self.ack is not None:
            data["ack"] = self.ack
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ContextPacket":
        """Coerce a raw ``ContextPacket``-shaped mapping read back from an artifact.

        ``original`` is kept **verbatim**: ``str()`` on an already-string value
        is identity, so the operator's exact text (whitespace, newlines,
        unicode) survives byte-for-byte. ``confidence`` is a best-effort numeric
        coercion — a value that cannot be parsed as ``float`` (e.g. a malformed
        artifact entry) falls back to ``0.0`` rather than raising, matching the
        codebase's best-effort stance on optional structured payloads read back
        from JSON (see :class:`colleague.contract_records.DeepthinkCall`).
        ``ack`` is defensively coerced via
        :func:`colleague.contract_coerce._coerce_ack` (talking-to-one arc,
        task t5): a non-string value (absent, explicit ``null``, a number, or
        a dict from a malformed artifact) degrades to ``None``; a string is
        stripped of surrounding whitespace (an empty/whitespace-only result
        also degrading to ``None``) and hard-capped to
        :data:`colleague.contract_coerce._MAX_ACK_LEN` characters.
        """
        raw_confidence = data.get("confidence")
        try:
            confidence = float(raw_confidence) if raw_confidence is not None else 0.0
        except (TypeError, ValueError):
            confidence = 0.0
        return cls(
            original=str(data.get("original", "")),
            interpretation=str(data.get("interpretation", "")),
            confidence=confidence,
            task_type=str(data.get("task_type", "")),
            omissions=_coerce_omissions(data.get("omissions")),
            ack=_coerce_ack(data.get("ack")),
        )


@dataclass
class SensesRecord:
    """One senses-model invocation record (cortex/senses, t2).

    The senses lobe's structural sibling of
    :class:`colleague.contract_records.DeepthinkCall`: a single per-invocation
    record collected inside the :class:`SensesBlock` on ``TaskResult.senses``.
    Mirrors ``DeepthinkCall``'s ``{point, tokens, duration, degraded}`` shape
    field-for-field, with ``latency`` in place of ``duration`` (the
    senses-side naming), and gets the same best-effort numeric coercion in
    :meth:`from_dict`.

    Fields
    ------
    point:
        Which senses invocation point fired (a free-form label, e.g.
        ``"interpret"``).
    latency:
        Wall-clock seconds the call took, or ``None`` when not measured.
    tokens:
        Total tokens used by the completion, or ``None`` when not reported
        (e.g. a degraded call that never reached the wire).
    degraded:
        ``True`` iff the senses call fell back / never completed against the
        senses model (a dead endpoint, request error, or overflow) instead of
        actually completing. Default ``False``.
    verbatim_presence:
        ``True`` iff this record's presented text was checked against an
        acting-mind ("worker") answer and was found to CONTAIN it verbatim —
        the structural containment guarantee (three-tier-execution arc, task
        t2). Additive: ``False`` by default, and a record produced from a
        call that carried no worker answer to check leaves this at its
        default. See :func:`colleague.senses._enforce_fidelity`.
    knowledge_repetition:
        ``True`` iff, on a fidelity failure, the presented text was found to
        verbatim-reproduce a meaningful chunk of background/"knowledge"
        content (rolling history, curated facts) instead of the current
        worker answer — the structural signature of the embodiment failure
        this field is named for ("senses recited its knowledge block instead
        of relaying the current answer"). Only ever set alongside
        ``fallback=True``. Default ``False``.
    fallback:
        ``True`` iff a fidelity failure (the presented text did NOT contain
        the worker answer verbatim) forced the caller to fall back to
        presenting the raw worker answer instead of the model's shaped
        reply. A fallback always also sets ``degraded=True`` — a fidelity
        failure IS a degradation, even though the completion itself may have
        succeeded. Default ``False``.
    truncated:
        ``True`` iff the prompt sent for this invocation had to be
        truncated to fit the senses model's own send budget (the existing
        :data:`colleague.senses._TRUNCATION_NOTE` windowing marker was
        applied). Default ``False``.

    ``verbatim_presence``/``knowledge_repetition``/``fallback``/``truncated``
    are OMITTED from :meth:`to_dict` while at their ``False`` default, so a
    record from before this field existed — or one that never exercised
    fidelity-tracking — serializes to the exact pre-existing
    ``{point, latency, tokens, degraded}`` shape (the same
    omit-when-default convention as :attr:`ContextPacket.ack`).
    """

    point: str
    latency: Optional[float] = None
    tokens: Optional[int] = None
    degraded: bool = False
    verbatim_presence: bool = False
    knowledge_repetition: bool = False
    fallback: bool = False
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "point": self.point,
            "latency": self.latency,
            "tokens": self.tokens,
            "degraded": self.degraded,
        }
        # Additive counters (task t2): omitted while False so a pre-arc /
        # fidelity-inactive record stays byte-identical to the old 4-key shape.
        if self.verbatim_presence:
            d["verbatim_presence"] = True
        if self.knowledge_repetition:
            d["knowledge_repetition"] = True
        if self.fallback:
            d["fallback"] = True
        if self.truncated:
            d["truncated"] = True
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SensesRecord":
        """Coerce a raw ``SensesRecord``-shaped mapping read back from an artifact.

        ``latency``/``tokens`` are best-effort numeric coercions: a value that
        cannot be parsed as ``float``/``int`` falls back to ``None`` rather than
        raising and aborting the whole ``TaskResult.from_dict`` call — exactly
        as :meth:`colleague.contract_records.DeepthinkCall.from_dict` handles
        ``duration``/``tokens``. ``point``/``degraded`` still survive from the
        rest of the entry. The four fidelity counters default to ``False``
        when absent — tolerant of a legacy artifact recorded before this
        field existed.
        """
        raw_latency = data.get("latency")
        raw_tokens = data.get("tokens")
        try:
            latency = float(raw_latency) if raw_latency is not None else None
        except (TypeError, ValueError):
            latency = None
        try:
            tokens = int(raw_tokens) if raw_tokens is not None else None
        except (TypeError, ValueError):
            tokens = None
        return cls(
            point=str(data.get("point", "")),
            latency=latency,
            tokens=tokens,
            degraded=bool(data.get("degraded", False)),
            verbatim_presence=bool(data.get("verbatim_presence", False)),
            knowledge_repetition=bool(data.get("knowledge_repetition", False)),
            fallback=bool(data.get("fallback", False)),
            truncated=bool(data.get("truncated", False)),
        )


@dataclass
class SensesDirectRecord:
    """A standalone, auditable record of ONE senses-direct front-door turn (#311).

    A senses-direct turn (the front door answering a confidently non-repo turn
    itself — a greeting, a question about colleague, general conversation)
    produces NO ``Task``/``TaskResult`` by design (there is no work item), so
    the dispatched path's ``TaskResult.senses.records`` audit trail has no
    counterpart for it. This is that counterpart: a lightweight
    ``{route, text, answer, latency, tokens, degraded, at}`` record written
    beside the ``.colleague/`` artifacts (``.colleague/senses-direct/<id>.json``)
    so direct answers AND misroutes are measurable from artifacts alone.

    Same *shape family* as :class:`SensesRecord` (best-effort numeric coercion
    on read-back), extended with the fields a standalone turn needs and the
    dispatched-path record already implies elsewhere: the classifier ``route``,
    the operator's VERBATIM ``text`` (never derived from model output — the v1
    verbatim invariant), the senses ``answer``, and a wall-clock ``at`` stamp.

    Fields
    ------
    route:
        The deterministic :func:`colleague.frontdoor.classify_frontdoor`
        verdict for this turn (e.g. ``"senses_direct"``).
    text:
        The operator's VERBATIM message — never normalized or derived from
        model output.
    answer:
        The senses-direct answer text (or the degraded-fallback text when
        senses could not answer and the turn fell back to cortex).
    latency:
        Wall-clock seconds the senses completion took, or ``None``.
    tokens:
        Total tokens the completion used, or ``None`` (e.g. a degraded call
        that never reached the wire).
    degraded:
        ``True`` iff the senses-direct attempt fell back / degraded. Default
        ``False``.
    at:
        Wall-clock timestamp (float seconds) the turn was recorded, or ``None``.
    """

    route: str
    text: str
    answer: str = ""
    latency: Optional[float] = None
    tokens: Optional[int] = None
    degraded: bool = False
    at: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "route": self.route,
            "text": self.text,
            "answer": self.answer,
            "latency": self.latency,
            "tokens": self.tokens,
            "degraded": self.degraded,
            "at": self.at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SensesDirectRecord":
        """Coerce a raw ``SensesDirectRecord``-shaped mapping read back from an
        artifact. ``latency``/``tokens``/``at`` are best-effort numeric coercions
        (a value that cannot be parsed falls back to ``None`` rather than raising),
        exactly as :meth:`SensesRecord.from_dict` handles ``latency``/``tokens``.
        ``route``/``text``/``answer``/``degraded`` survive from the rest of the
        entry — ``text`` verbatim.
        """
        raw_latency = data.get("latency")
        raw_tokens = data.get("tokens")
        raw_at = data.get("at")
        try:
            latency = float(raw_latency) if raw_latency is not None else None
        except (TypeError, ValueError):
            latency = None
        try:
            tokens = int(raw_tokens) if raw_tokens is not None else None
        except (TypeError, ValueError):
            tokens = None
        try:
            at = float(raw_at) if raw_at is not None else None
        except (TypeError, ValueError):
            at = None
        return cls(
            route=str(data.get("route", "")),
            text=str(data.get("text", "")),
            answer=str(data.get("answer", "")),
            latency=latency,
            tokens=tokens,
            degraded=bool(data.get("degraded", False)),
            at=at,
        )


@dataclass
class SensesBlock:
    """The cortex/senses front-door record for a work item (cortex/senses, t2).

    A block of shape ``{mode, packet, records}`` recorded on
    ``TaskResult.senses``: ``mode`` names how the cortex/senses split resolved
    (e.g. ``"split"`` when the senses model interpreted the request, or
    ``"cortex-only"`` when it did not), ``packet`` is the :class:`ContextPacket`
    the senses model produced (or ``None``), and ``records`` is the ordered list
    of per-invocation :class:`SensesRecord` entries.

    This is the same *shape family* as ``TaskResult.deepthink`` — an optional,
    omit-when-None payload whose nested records mirror
    :class:`colleague.contract_records.DeepthinkCall`. A run with no senses
    involvement leaves ``TaskResult.senses`` at ``None``, so the key is
    omitted entirely and the artifact is byte-identical to today.

    ONE SHARED SHAPE ACROSS EVERY FRONT (presence-default-everywhere arc, task
    t3): the interactive session, the ``colleague talk`` attach, a background
    run, the mesh resident, and one-shot ``colleague work`` all record their
    middle-manager beats (ack, proactive updates, clarify, guidance relay, the
    senses coordination loop's turns) into this SAME dataclass — the SAME
    ``records``/``chat``/``injections`` fields, the SAME :data:`SENSES_CHAT_KINDS`
    vocabulary, the SAME :data:`SENSES_LOOP_POINT_PREFIX` point convention. No
    front defines its own record type or its own chat/point shape; a front that
    needs a genuinely new beat extends THIS shape (and this drift-tested doc),
    never a parallel one.
    """

    mode: str
    packet: Optional[ContextPacket] = None
    records: list[SensesRecord] = field(default_factory=list)
    # Live-presence arc (task t5), both omit-when-empty so a run that never used
    # the live talk lane stays byte-identical (a cortex/senses split run today has
    # neither key). ``injections`` records every APPLIED operator-to-cortex
    # guidance injection (``{text, at, source}``, ``at`` a wall-clock float — never
    # estimated); ``chat`` folds the talk-lane exchanges (``{message, answer,
    # relay, relay_text, latency, degraded, at}``) read from the flight chat log at
    # finish, so the operator's mid-run conversation + relays are reconstructable
    # from the artifact alone (h8 awareness invariant).
    #
    # Talking-to-one arc, task t5 (a LATER arc, distinct from the "task t5"
    # label above): each ``chat`` entry MAY also carry an optional ``"kind"``
    # key naming which exchange produced it — ``"talk"`` (the live-presence
    # shape just described; IMPLIED when ``kind`` is absent, so every
    # pre-existing entry keeps its meaning unchanged), ``"ack"`` (the intake
    # acknowledgment), ``"update"`` (a proactive progress narration), or
    # ``"clarify"`` (a clarifying question/answer exchange before dispatch).
    # This folds ack/update/clarify exchanges into the SAME ordered list as
    # talk-lane exchanges so the whole operator-senses conversation is
    # reconstructable from one place. It is a documented convention pinned by
    # round-trip tests, not a schema change: ``chat`` stays a list of plain
    # dicts and (de)serialization passes every entry through verbatim
    # regardless of whether it carries ``kind`` — see :data:`SENSES_CHAT_KINDS`
    # for the closed vocabulary (reused identically by every front, presence-
    # default-everywhere arc, task t3) and :data:`SENSES_LOOP_POINT_PREFIX` for
    # the senses coordination loop's ``records[].point`` naming convention.
    injections: list[dict[str, Any]] = field(default_factory=list)
    chat: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "mode": self.mode,
            "packet": self.packet.to_dict() if self.packet is not None else None,
            "records": [r.to_dict() for r in self.records],
        }
        # Omit-when-empty: keeps a senses block with no live lane byte-identical to
        # the pre-t5 shape (the e2e/cortex-senses artifact pins compare exact keys).
        if self.injections:
            out["injections"] = [dict(entry) for entry in self.injections]
        if self.chat:
            out["chat"] = [dict(entry) for entry in self.chat]
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SensesBlock":
        """Coerce a raw ``SensesBlock``-shaped mapping read back from an artifact.

        ``packet`` is parsed only when it is a mapping (a malformed non-dict
        packet degrades to ``None``); malformed (non-dict) ``records`` entries
        are dropped rather than raising, matching the best-effort stance of
        :func:`colleague.contract_coerce._coerce_deepthink_calls` /
        :func:`colleague.contract_coerce._coerce_acceptance_outcomes`.
        """
        raw_packet = data.get("packet")
        return cls(
            mode=str(data.get("mode", "")),
            packet=ContextPacket.from_dict(raw_packet) if isinstance(raw_packet, dict) else None,
            records=[
                SensesRecord.from_dict(entry)
                for entry in data.get("records", [])
                if isinstance(entry, dict)
            ],
            # Best-effort like ``records``: absent keys default to [] (a pre-t5
            # artifact has neither), malformed non-dict entries are dropped.
            injections=[
                dict(entry) for entry in data.get("injections", []) if isinstance(entry, dict)
            ],
            chat=[dict(entry) for entry in data.get("chat", []) if isinstance(entry, dict)],
        )
