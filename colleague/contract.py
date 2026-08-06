"""Colleague task contract — the shared task runtime.

Every engine driver consumes a :class:`Task` and produces a :class:`TaskResult`
of the *same shape*, regardless of which model ran underneath. That uniformity
is the whole point of Colleague: the caller assigns repo work without caring
which engine executed it.

The types are plain dataclasses with explicit ``to_dict`` / ``from_dict`` so a
result round-trips through JSON unchanged — the handoff artifact written by
:mod:`colleague.artifact` is simply ``TaskResult.to_dict()`` serialized, and
reloading it yields an equal object.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional, Sequence

from colleague.configevents import (
    EVENT_KIND_APPLIED,
    EVENT_KIND_BASELINE,
    EVENT_KIND_PROPOSED,
    EVENT_KIND_REFUSED,
    ConfigEvent,
    effective_digest,
)

if TYPE_CHECKING:
    from colleague.affectedtests import AffectedTestsReport
    from colleague.testintegrity import TestIntegrityReport

# TaskResult.status values.
OK = "ok"
ERROR = "error"
INCOMPLETE = "incomplete"

# HookFiring.decision values.
DECISION_ALLOW = "allow"
DECISION_DENY = "deny"
DECISION_REWRITE = "rewrite"
DECISION_OBSERVE = "observe"

# Sentinel assigned to TaskResult.summary when a work item ended without calling
# ``finish`` and produced no substantive model content.  Callers compare
# ``result.summary == NO_RESULT_PRODUCED`` to detect the empty case without
# string-matching a step-count fallback such as "completed in N step(s)".
# The loop (loop.py, task t2) is responsible for assigning this value; the
# contract owns the stable string so every backend and every caller share one
# importable reference.
#
# The value is a deliberately machine-oriented marker (sentinel affixes + a
# token unlikely in prose) rather than a plain-English phrase: the sentinel
# lives in ``summary``, a free-form *model text* field, so if it read like
# normal output the model could legitimately emit it as its last substantive
# content and a caller would misclassify a real result as the empty case.
NO_RESULT_PRODUCED = "__COLLEAGUE_NO_RESULT_PRODUCED__"

# Five distinguishable finish states (plan task t1, covers c4/h4/c30) — the
# loop's OWN classification of how one seat's work concluded, independent of
# any one backend's raw wire vocabulary (a vLLM ``finish_reason`` of
# ``"stop"``/``"tool_calls"``/``"length"``/... is the wire-level signal these
# are normalized FROM; see :func:`colleague.finishstate.classify_finish_state`
# for the mapping). ``FINISH_EMPTY`` is the one state guaranteed to apply
# whenever ``summary == NO_RESULT_PRODUCED`` — the sentinel must never be
# reported as ``FINISH_DELIBERATE`` (a completed answer).
FINISH_DELIBERATE = "deliberate"
FINISH_TRUNCATED = "truncated"
FINISH_STOPPED = "stopped"
FINISH_TIMEOUT = "timeout"
FINISH_EMPTY = "empty"

#: Every valid :class:`FinishRecord` ``state`` value, in the fixed reading
#: order used above — importable so a caller/test can assert exhaustiveness
#: without hand-listing the five strings again.
FINISH_STATES = (FINISH_DELIBERATE, FINISH_TRUNCATED, FINISH_STOPPED, FINISH_TIMEOUT, FINISH_EMPTY)


@dataclass
class FinishRecord:
    """One seat's finish-state classification for a work item (t1, c4/h4/c30).

    ``seat`` distinguishes WHICH acting mind produced this record — today
    always ``"main"`` (the single acting mind's own turns, driven by
    :func:`colleague.loop.run`) or ``"senses"`` (a senses-lane completion, see
    :class:`SensesRecord`) — a free-form string (not a closed enum) so a
    future seat (e.g. the three-tier ``worker``) can be distinguished without
    a shape change (see docs/plans/2026-08-05-three-tier-execution.md task
    t1's "per-seat" design note).

    ``finish_reason`` is the raw value a backend's wire format reported for
    the LAST completion on this seat (``""`` when the backend/engine never
    reports the field — the mock engine's deliberate finishes still set a
    representative value; a degraded/tools-off seat like ``senses`` has none
    to report and stays ``""``). ``state`` is the loop's classification onto
    one of the five :data:`FINISH_STATES` — the single normalized source of
    truth a caller should branch on, never re-derived by re-inspecting
    ``finish_reason`` (one raw wire value can mean different things on
    different backends). ``truncated`` is ``True`` iff
    ``state == FINISH_TRUNCATED``, kept as its own boolean (not re-derived at
    read time) so a caller filtering on truncation alone need not know the
    full state vocabulary.
    """

    seat: str
    finish_reason: str = ""
    state: str = FINISH_DELIBERATE
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "seat": self.seat,
            "finish_reason": self.finish_reason,
            "state": self.state,
            "truncated": self.truncated,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FinishRecord":
        return cls(
            seat=str(data.get("seat", "")),
            finish_reason=str(data.get("finish_reason", "")),
            state=str(data.get("state", FINISH_DELIBERATE)),
            truncated=bool(data.get("truncated", False)),
        )


@dataclass
class HookFiring:
    """A record of one hook invocation during a work item.

    Hooks fire at lifecycle events (e.g. "pre_tool", "post_tool",
    "task_start", "finish").  The loop populates these; the contract
    defines the shape only.

    Fields
    ------
    event:
        The lifecycle event that triggered the hook.  Conventional values:
        ``"task_start"``, ``"pre_tool"``, ``"post_tool"``, ``"finish"``.
    tool:
        The tool the hook fired around, if applicable (``None`` for
        non-tool events such as ``"task_start"``).
    command:
        The shell command the hook ran (``None`` when the hook did not
        execute a subprocess, e.g. an in-process observe hook).
    decision:
        The outcome of the hook.  One of ``"allow"``, ``"deny"``,
        ``"rewrite"``, ``"observe"`` (default).
    exit_code:
        The exit code of the hook subprocess (``None`` when no subprocess
        was run).
    reason:
        Human-readable explanation — populated with the deny reason,
        stderr, or rewrite description; empty string for plain observe/allow.
    """

    event: str
    tool: Optional[str] = None
    command: Optional[str] = None
    decision: str = DECISION_OBSERVE
    exit_code: Optional[int] = None
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "event": self.event,
            "tool": self.tool,
            "command": self.command,
            "decision": self.decision,
            "exit_code": self.exit_code,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HookFiring":
        raw_exit = data.get("exit_code")
        return cls(
            event=str(data["event"]),
            tool=data.get("tool") or None,
            command=data.get("command") or None,
            decision=str(data.get("decision", DECISION_OBSERVE)),
            exit_code=int(raw_exit) if raw_exit is not None else None,
            reason=str(data.get("reason", "")),
        )


@dataclass
class Usage:
    """Token accounting for a work item, summed across the loop's model calls."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def add(self, prompt: int, completion: int) -> None:
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.total_tokens += prompt + completion

    def to_dict(self) -> dict[str, int]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Usage":
        return cls(
            prompt_tokens=int(data.get("prompt_tokens", 0)),
            completion_tokens=int(data.get("completion_tokens", 0)),
            total_tokens=int(data.get("total_tokens", 0)),
        )


@dataclass
class WorkStats:
    """Always-on per-work-item statistics — the cost+shape record of one work item.

    Sits alongside :class:`Usage` (which holds the exact API-reported token
    counts) and captures everything else worth knowing about a work item so a caller
    can compute the **ROI of outsourcing**: how long it took, what it did, and
    how much it produced. Populated runtime-side by :func:`colleague.loop.run`
    (the all-engines rule), so every backend fills it identically.

    Token honesty (decision c11/c17): tokens live on :class:`Usage` and are taken
    *verbatim* from the model response ``usage`` — never estimated. This model
    reports no reasoning-token breakdown, so "thought vs written" is measured here
    as exact **chars/bytes**, not tokens: ``reasoning_*`` is the model's
    chain-of-thought (the separate ``message.reasoning`` field, generated but not
    saved to a file), ``answer_*`` is ``message.content`` (the final answer), and
    ``bytes_written`` is the exact UTF-8 byte count written to files via
    ``write_file``. There is no tokenizer (zero runtime deps), so a reasoning /
    written *token* count is deliberately not synthesised.

    Fields
    ------
    request:
        The originating task instruction (the request the work item answered).
    engine:
        The backend that ran the work item (e.g. ``mock`` / ``vllm-openai``) —
        ``task.engine``. With ``model`` it makes the ROI block self-describing:
        a caller comparing two artifacts knows which mind produced each.
    model:
        The model id the engine was configured to call. This is the configured
        id even for the no-op ``mock`` backend (which calls no model); read it
        alongside ``engine`` to disambiguate. Empty when no model was threaded.
    started_at:
        ISO-8601 UTC timestamp of when the loop began.
    duration_seconds:
        Wall-clock loop duration (monotonic delta), seconds.
    model_turns:
        Number of model turns (``complete`` calls) the loop ran.
    step_count:
        Number of tool-call steps recorded (mirrors ``len(steps)``).
    tool_counts:
        Per-tool call counts aggregated from ``steps`` (tool name → count).
    files_changed:
        Number of distinct files the work item wrote (mirrors ``len(changed_files)``).
    bytes_written:
        Total UTF-8 bytes written to files via ``write_file``, summed over the work item.
    reasoning_chars / reasoning_bytes:
        Length of all ``message.reasoning`` text generated (chain-of-thought
        "thought" not saved to a file), in Unicode chars and UTF-8 bytes.
    answer_chars / answer_bytes:
        Length of all ``message.content`` text generated (the final answer), in
        Unicode chars and UTF-8 bytes.
    """

    request: str = ""
    engine: str = ""
    model: str = ""
    started_at: str = ""
    duration_seconds: float = 0.0
    model_turns: int = 0
    step_count: int = 0
    tool_counts: dict[str, int] = field(default_factory=dict)
    files_changed: int = 0
    bytes_written: int = 0
    reasoning_chars: int = 0
    reasoning_bytes: int = 0
    answer_chars: int = 0
    answer_bytes: int = 0

    def add_generated(self, *, reasoning: str = "", answer: str = "") -> None:
        """Accumulate one turn's generated text into the char/byte counters.

        Called once per model turn by the loop with that turn's
        ``message.reasoning`` and ``message.content``. Char counts are Unicode
        code points (``len``); byte counts are UTF-8 (``len(.encode("utf-8"))``).
        """
        self.reasoning_chars += len(reasoning)
        self.reasoning_bytes += len(reasoning.encode("utf-8"))
        self.answer_chars += len(answer)
        self.answer_bytes += len(answer.encode("utf-8"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "request": self.request,
            "engine": self.engine,
            "model": self.model,
            "started_at": self.started_at,
            "duration_seconds": self.duration_seconds,
            "model_turns": self.model_turns,
            "step_count": self.step_count,
            "tool_counts": dict(self.tool_counts),
            "files_changed": self.files_changed,
            "bytes_written": self.bytes_written,
            "reasoning_chars": self.reasoning_chars,
            "reasoning_bytes": self.reasoning_bytes,
            "answer_chars": self.answer_chars,
            "answer_bytes": self.answer_bytes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkStats":
        return cls(
            request=str(data.get("request", "")),
            engine=str(data.get("engine", "")),
            model=str(data.get("model", "")),
            started_at=str(data.get("started_at", "")),
            duration_seconds=float(data.get("duration_seconds", 0.0)),
            model_turns=int(data.get("model_turns", 0)),
            step_count=int(data.get("step_count", 0)),
            tool_counts={str(k): int(v) for k, v in (data.get("tool_counts") or {}).items()},
            files_changed=int(data.get("files_changed", 0)),
            bytes_written=int(data.get("bytes_written", 0)),
            reasoning_chars=int(data.get("reasoning_chars", 0)),
            reasoning_bytes=int(data.get("reasoning_bytes", 0)),
            answer_chars=int(data.get("answer_chars", 0)),
            answer_bytes=int(data.get("answer_bytes", 0)),
        )


@dataclass
class SubResult:
    """The result of one delegated sub-task driven by a nested child work item.

    A work item may delegate a scoped sub-task to a nested child work item; each child
    produces a ``SubResult`` recorded on the parent ``TaskResult.sub_results``.

    Cost attribution is **nested-only**: the child carries its OWN ``usage`` and
    the parent ``TaskResult.usage`` is NOT summed with its children's — a reader
    sums them explicitly if a roll-up is wanted.
    """

    task_id: str
    engine: str
    model: str
    status: str
    summary: str = ""
    changed_files: list[str] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    role: Optional[str] = None
    """The typed-subagent role this child ran as, or ``None`` for the default
    full-surface delegation (#t4). Omitted from ``to_dict`` when None so a
    role-less child serializes byte-identically to the pre-role contract."""
    parent: Optional[str] = None
    """The parent work item's ``task_id`` (lineage), or ``None`` when the child
    was not recorded with a parent link (spec R6 / plan t14 / #259). Lets a
    subagent tree be walked from artifacts alone — child artifacts name their
    parent so a tree of delegated work items is reconstructable without external
    bookkeeping. Populated structurally by the caller that mints the child
    (plan t16), never inferred. Omitted from ``to_dict`` when ``None`` so a
    child recorded without lineage serializes byte-identically to today."""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "task_id": self.task_id,
            "engine": self.engine,
            "model": self.model,
            "status": self.status,
            "summary": self.summary,
            "changed_files": list(self.changed_files),
            "usage": self.usage.to_dict(),
        }
        # Omit-when-None: a role-less child is byte-identical to the pre-role shape.
        if self.role is not None:
            d["role"] = self.role
        # Same omit-when-None treatment for lineage (spec R6): a child recorded
        # without a parent link serializes byte-identically to today.
        if self.parent is not None:
            d["parent"] = self.parent
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SubResult":
        return cls(
            task_id=str(data["task_id"]),
            engine=str(data["engine"]),
            model=str(data["model"]),
            status=str(data["status"]),
            summary=str(data.get("summary", "")),
            changed_files=list(data.get("changed_files", [])),
            usage=Usage.from_dict(data.get("usage", {})),
            role=data.get("role"),
            parent=data.get("parent"),
        )


@dataclass
class CapacityDecision:
    """The one declared fill-line move colleague made for a work item (#156).

    When the running context crosses the fill-line threshold, the runtime asks the
    backend to declare ONE opinionated move and records it here: ``kind`` is one of
    ``"compact"`` (summarize its own working history to itself), ``"split"`` (fan
    out to child instances), or ``"finish-with-handoff"`` (stop with a continuation
    summary); ``reason`` is a short human note (e.g. the capacity numbers that
    tripped the threshold). ``None`` on ``TaskResult.capacity_decision`` means no
    fill-line event occurred — the key is then omitted from the artifact entirely,
    so a work item that never filled its context serializes byte-identically to today.
    """

    kind: str
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "reason": self.reason}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CapacityDecision":
        return cls(kind=str(data["kind"]), reason=str(data.get("reason", "")))


@dataclass
class CoherenceReport:
    """Report from the coherence pre-finish gate (#294, colleague#291 S3).

    ``status`` is ``"scored"`` (the gate ran; per-file records in ``files``)
    or ``"skipped"`` (the coherence CLI is not installed — ``reason`` says so).
    ``embed_url``/``embed_model`` record the measurement's **frame provenance**
    (coherence-cli#10): the embedding endpoint + model the subprocess saw —
    a meaning score is a model-relative, anchor-defined measurement, never
    universal meaning. Each ``files`` record carries ``path`` plus either the
    CLI's payload (``meaning_score``/``subdimensions``/``diagnostics`` and any
    future keys verbatim) or an ``error`` string. Advisory only: nothing here
    ever blocks the handoff or flips a run's status.
    """

    status: str = "scored"
    reason: Optional[str] = None
    embed_url: Optional[str] = None
    embed_model: Optional[str] = None
    files: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"status": self.status}
        if self.reason is not None:
            d["reason"] = self.reason
        if self.embed_url is not None:
            d["embed_url"] = self.embed_url
        if self.embed_model is not None:
            d["embed_model"] = self.embed_model
        if self.files:
            d["files"] = [dict(f) for f in self.files]
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CoherenceReport":
        return cls(
            status=str(data.get("status", "scored")),
            reason=data.get("reason"),
            embed_url=data.get("embed_url"),
            embed_model=data.get("embed_model"),
            files=[dict(f) for f in data.get("files", [])],
        )


@dataclass
class LintReport:
    """Report from the lint pre-finish gate.

    ``fixed`` lists human-readable notes of what was auto-fixed
    (e.g. "black reformatted 2 file(s)").  ``residual`` lists remaining
    violations surfaced after auto-fix (e.g. "flake8 F811 colleague/x.py:10").
    ``skipped`` lists linters configured but skipped because the binary was
    missing (e.g. "ruff: not installed").
    """

    fixed: list[str] = field(default_factory=list)
    residual: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fixed": list(self.fixed),
            "residual": list(self.residual),
            "skipped": list(self.skipped),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LintReport":
        return cls(
            fixed=list(data.get("fixed", [])),
            residual=list(data.get("residual", [])),
            skipped=list(data.get("skipped", [])),
        )


@dataclass
class DeepthinkCall:
    """One escalation call to the "deepthink" model during a work item.

    Dual-model colleague (plan task t3, spec covers c14/h6) optionally pairs a
    fast wide-window main model that does the driving with a second
    "deepthink" model escalated to for hard reasoning. Every escalation —
    whether it actually completed against the deepthink model or degraded
    back to the main model — is recorded as one ``DeepthinkCall`` on
    ``TaskResult.deepthink`` (see :mod:`colleague.contract` and, for the
    seam that produces these records, ``colleague.deepthink.run_deepthink``,
    task t2).

    Fields
    ------
    point:
        Which escalation point fired (a free-form label, e.g. ``"tool"`` for
        the model-callable ``deepthink`` loop tool, ``"acceptance_selfcheck"``
        for the pre-finish acceptance self-check, or ``"plan_proposal"`` for a
        plan-mode proposal completion).
    tokens:
        Total tokens used by the completion, or ``None`` when not reported
        (e.g. a degraded call that never reached the wire).
    duration:
        Wall-clock seconds the call took, or ``None`` when not measured.
    degraded:
        ``True`` iff the escalation fell back to the main model (a dead
        port, request error, or context overflow on the deepthink endpoint)
        instead of actually completing against the deepthink model. Default
        ``False``.
    """

    point: str
    tokens: Optional[int] = None
    duration: Optional[float] = None
    degraded: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "point": self.point,
            "tokens": self.tokens,
            "duration": self.duration,
            "degraded": self.degraded,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DeepthinkCall":
        """Coerce a raw ``DeepthinkCall``-shaped mapping read back from an artifact.

        ``tokens``/``duration`` are best-effort numeric coercions: a value that
        cannot be parsed as ``int``/``float`` (e.g. a malformed artifact entry
        like ``{"tokens": "n/a"}``) falls back to ``None`` rather than raising
        and aborting the whole ``TaskResult.from_dict`` call — matching the
        codebase's best-effort stance on optional structured payloads read back
        from JSON (see ``_coerce_acceptance_outcomes``). ``point``/``degraded``
        still survive from the rest of the entry.
        """
        raw_tokens = data.get("tokens")
        raw_duration = data.get("duration")
        try:
            tokens = int(raw_tokens) if raw_tokens is not None else None
        except (TypeError, ValueError):
            tokens = None
        try:
            duration = float(raw_duration) if raw_duration is not None else None
        except (TypeError, ValueError):
            duration = None
        return cls(
            point=str(data.get("point", "")),
            tokens=tokens,
            duration=duration,
            degraded=bool(data.get("degraded", False)),
        )


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
        from JSON (see :class:`DeepthinkCall`). ``ack`` is defensively coerced
        via :func:`_coerce_ack` (talking-to-one arc, task t5): a non-string
        value (absent, explicit ``null``, a number, or a dict from a
        malformed artifact) degrades to ``None``; a string is stripped of
        surrounding whitespace (an empty/whitespace-only result also
        degrading to ``None``) and hard-capped to :data:`_MAX_ACK_LEN`
        characters.
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
class SensesRecord:
    """One senses-model invocation record (cortex/senses, t2).

    The senses lobe's structural sibling of :class:`DeepthinkCall`: a single
    per-invocation record collected inside the :class:`SensesBlock` on
    ``TaskResult.senses``. Mirrors ``DeepthinkCall``'s
    ``{point, tokens, duration, degraded}`` shape field-for-field, with
    ``latency`` in place of ``duration`` (the senses-side naming), and gets the
    same best-effort numeric coercion in :meth:`from_dict`.

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
        as :meth:`DeepthinkCall.from_dict` handles ``duration``/``tokens``.
        ``point``/``degraded`` still survive from the rest of the entry. The
        four fidelity counters default to ``False`` when absent — tolerant of
        a legacy artifact recorded before this field existed.
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


@dataclass(frozen=True)
class IncompletionRecord:
    """Record of why a work item was incomplete.

    Fields
    ------
    reason:
        Human-readable explanation of why the work item did not complete.
    evidence:
        Supporting detail (e.g. last tool-call output, error text).
    recommendation:
        Suggested next step for the operator or a follow-up work item.
    """

    reason: str
    evidence: str
    recommendation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "reason": self.reason,
            "evidence": self.evidence,
            "recommendation": self.recommendation,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "IncompletionRecord":
        """Best-effort coercion: each field coerced to str, empty string on failure.

        Robust to a malformed payload (a non-dict, or an explicit ``null`` field):
        a non-dict ``data`` yields an all-empty record, and ``data.get(...) or ""``
        turns a ``None`` value into ``""`` rather than the string ``"None"``. Mirrors
        the type-guarded best-effort parsing the other optional structured fields use.
        """
        if not isinstance(data, dict):
            return cls("", "", "")
        return cls(
            reason=str(data.get("reason") or ""),
            evidence=str(data.get("evidence") or ""),
            recommendation=str(data.get("recommendation") or ""),
        )


def _coerce_count(value: Any) -> int:
    """Coerce one raw chain-view counter to a non-negative-ish int, 0 on failure.

    Best-effort like :meth:`IncompletionRecord.from_dict`: a missing key, an
    explicit ``null``, or a non-numeric value from a malformed artifact degrades
    to ``0`` rather than raising — a chained artifact must stay readable even
    when a field was corrupted."""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


@dataclass(frozen=True)
class ChainView:
    """Chain-of-episodes accounting stamped on a chained work item's artifact (c20).

    A chained run (``--until-done``) drives one work item per episode; each
    episode keeps its OWN exact :class:`Usage` / :class:`WorkStats` (never
    merged), and this record adds the running view of the chain so far. The
    totals are **sums of per-episode exact usage** taken verbatim from each
    episode's result — never estimated, never re-counted (the tokens-are-exact
    rule, honesty condition h19). The caller (the chain dispatch loop) supplies
    the sums, canonically via :meth:`accumulate`.

    Fields
    ------
    episode_index:
        1-based position of THIS episode in the chain.
    episode_count:
        Number of episodes in the chain so far, including this one (equals
        ``episode_index`` on the episode's own artifact; on the final episode
        it is the chain length).
    total_steps:
        Sum of per-episode ``stats.step_count`` across episodes 1..this one.
    total_prompt_tokens / total_completion_tokens / total_tokens:
        Sums of the per-episode exact :class:`Usage` fields (same names,
        ``total_`` prefixed) across episodes 1..this one.
    deferred_gate_episodes:
        Task ids of the episodes (1..this one, in chain order) that deferred
        their pre-finish gates to the chain (#335 exits, recorded via
        ``TaskResult.gates_deferred`` — #341). ``()`` — no deferral so far —
        is omitted from the artifact, so an all-gated chain stays
        byte-identical.
    """

    episode_index: int
    episode_count: int
    total_steps: int
    total_prompt_tokens: int
    total_completion_tokens: int
    total_tokens: int
    deferred_gate_episodes: tuple[str, ...] = ()

    @classmethod
    def accumulate(cls, prior: Optional["ChainView"], result: "TaskResult") -> "ChainView":
        """The chain view for the episode that produced ``result``.

        ``prior`` is the view stamped on the previous episode's artifact
        (``None`` for the first episode). Every total is the prior total plus
        this episode's exact number read verbatim off ``result.usage`` /
        ``result.stats`` — sums of exacts, never estimates (h19).
        """
        index = (prior.episode_index if prior else 0) + 1
        deferred = prior.deferred_gate_episodes if prior else ()
        # getattr: accumulate is a public seam and a caller may pass a minimal
        # result stand-in predating the #341 marker.
        if getattr(result, "gates_deferred", False):
            deferred = deferred + (result.task_id,)
        return cls(
            episode_index=index,
            episode_count=index,
            total_steps=(prior.total_steps if prior else 0) + result.stats.step_count,
            total_prompt_tokens=(
                (prior.total_prompt_tokens if prior else 0) + result.usage.prompt_tokens
            ),
            total_completion_tokens=(
                (prior.total_completion_tokens if prior else 0) + result.usage.completion_tokens
            ),
            total_tokens=(prior.total_tokens if prior else 0) + result.usage.total_tokens,
            deferred_gate_episodes=deferred,
        )

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "episode_index": self.episode_index,
            "episode_count": self.episode_count,
            "total_steps": self.total_steps,
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_tokens": self.total_tokens,
        }
        # Omit-when-empty (#341): an all-gated chain's artifact is byte-identical.
        if self.deferred_gate_episodes:
            data["deferred_gate_episodes"] = list(self.deferred_gate_episodes)
        return data

    @classmethod
    def from_dict(cls, data: Any) -> "ChainView":
        """Best-effort coercion: each counter coerced to int, 0 on failure.

        Robust to a malformed payload (a non-dict, explicit ``null`` fields,
        non-numeric values) — mirrors :meth:`IncompletionRecord.from_dict`'s
        never-raises stance on optional structured payloads read back from an
        artifact."""
        if not isinstance(data, dict):
            return cls(0, 0, 0, 0, 0, 0)
        raw_deferred = data.get("deferred_gate_episodes")
        # Best-effort like the counters: a non-list payload degrades to (),
        # non-string entries are dropped — never raises (#341).
        deferred: tuple[str, ...] = ()
        if isinstance(raw_deferred, (list, tuple)):
            deferred = tuple(item for item in raw_deferred if isinstance(item, str))
        return cls(
            episode_index=_coerce_count(data.get("episode_index")),
            episode_count=_coerce_count(data.get("episode_count")),
            total_steps=_coerce_count(data.get("total_steps")),
            total_prompt_tokens=_coerce_count(data.get("total_prompt_tokens")),
            total_completion_tokens=_coerce_count(data.get("total_completion_tokens")),
            total_tokens=_coerce_count(data.get("total_tokens")),
            deferred_gate_episodes=deferred,
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
    omit-when-None payload whose nested records mirror :class:`DeepthinkCall`.
    A run with no senses involvement leaves ``TaskResult.senses`` at ``None``,
    so the key is omitted entirely and the artifact is byte-identical to today.

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
        :func:`_coerce_deepthink_calls` / :func:`_coerce_acceptance_outcomes`.
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


@dataclass
class Step:
    """One iteration of the agentic tool-loop: a tool call and its result."""

    index: int
    tool: str
    arguments: dict[str, Any] = field(default_factory=dict)
    result: str = ""
    ok: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "tool": self.tool,
            "arguments": self.arguments,
            "result": self.result,
            "ok": self.ok,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Step":
        return cls(
            index=int(data["index"]),
            tool=str(data["tool"]),
            arguments=dict(data.get("arguments", {})),
            result=str(data.get("result", "")),
            ok=bool(data.get("ok", True)),
        )


@dataclass
class Task:
    """A unit of repo work handed to an engine.

    ``engine`` names the driver to run it through (e.g. ``mock`` or
    ``vllm-openai``); swapping it is the only change needed to run the identical
    task on a different model.
    """

    id: str
    repo_path: str
    instruction: str
    context: str = ""
    constraints: list[str] = field(default_factory=list)
    engine: str = "mock"
    watch: bool = False
    """When True the work item is a *watchable flight*: the runtime arms a
    file-based flight-control plane under ``.colleague/flight/<id>.*`` so a
    pilot can read the live feed and inject ``stop``/``guidance`` directives
    (see :mod:`colleague.flight`). Default ``False`` is a strict no-op and is
    omitted from ``to_dict`` so an unwatched task serializes byte-identically."""
    goal: Optional[str] = None
    """The pre-execution goal for this work item — a one-line, human-readable
    statement of what "done" looks like, set before the loop runs (spec R6 /
    plan t14 / #259). ``None`` is the default (a bare ``colleague work
    "<instruction>"`` carries no separate goal). Omitted from ``to_dict`` when
    ``None`` so a goal-less task serializes byte-identically to today."""
    acceptance: Optional[list[str]] = None
    """Machine-readable acceptance criteria for this work item — one short
    string per criterion. The loop's bounded pre-finish self-check turn (plan
    t15) evaluates these into ``TaskResult.acceptance_outcomes``; setting a
    goal without acceptance criteria is fine (no self-check runs). ``None`` is
    the default. Omitted from ``to_dict`` when ``None`` so a task without
    acceptance criteria serializes byte-identically to today."""
    attachments: Optional[list[dict[str, Any]]] = None
    """Optional media attachments for this work item — each entry is a
    ``{"path": str, "media_type": str}`` mapping (e.g. an image or audio file
    to route into a multimodal completion). ``None`` is the default (a bare
    ``colleague work "<instruction>"`` carries no attachments). Omitted from
    ``to_dict`` when ``None`` so an attachment-less task serializes
    byte-identically to today (task t1)."""
    context_packet: Optional["ContextPacket"] = None
    """The senses model's structured interpretation of this request (cortex/senses,
    t2), or ``None`` when no senses front door ran (a bare ``colleague work
    "<instruction>"`` carries no packet). A :class:`ContextPacket`
    (``{original, interpretation, confidence, task_type, omissions}``) whose
    ``original`` field preserves the operator's verbatim text. Omitted from
    ``to_dict`` when ``None`` — mirroring ``goal``/``acceptance``/``attachments``
    — so a packet-less task serializes byte-identically to today."""
    flight_repo_path: Optional[str] = None
    """The OPERATOR-repo path the flight-control plane is armed at, distinct from
    ``repo_path`` (the work CWD). Set by ``_setup_isolation`` on an isolated run
    (#310) so the flight feed/control live in the operator repo — reachable by
    ``colleague talk`` / ``colleague flight`` and surviving worktree cleanup —
    while the loop still executes in the throwaway worktree at ``repo_path``.
    ``None`` (the default, and the in-place session path) means "arm at
    ``repo_path``" — the pre-#310 behaviour, byte-identical. Omitted from
    ``to_dict`` when ``None`` so a non-isolated task serializes byte-identically
    to today."""

    @classmethod
    def new(
        cls,
        repo_path: str,
        instruction: str,
        *,
        engine: str = "mock",
        context: str = "",
        constraints: list[str] | None = None,
        watch: bool = False,
        goal: str | None = None,
        acceptance: list[str] | None = None,
        attachments: list[dict[str, Any]] | None = None,
        context_packet: Optional["ContextPacket"] = None,
        flight_repo_path: str | None = None,
    ) -> "Task":
        """Create a task with a fresh short id."""
        return cls(
            id=uuid.uuid4().hex[:12],
            repo_path=repo_path,
            instruction=instruction,
            engine=engine,
            context=context,
            constraints=list(constraints or []),
            watch=watch,
            goal=goal,
            acceptance=list(acceptance) if acceptance is not None else None,
            attachments=(
                [dict(entry) for entry in attachments] if attachments is not None else None
            ),
            context_packet=context_packet,
            flight_repo_path=flight_repo_path,
        )

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "repo_path": self.repo_path,
            "instruction": self.instruction,
            "context": self.context,
            "constraints": list(self.constraints),
            "engine": self.engine,
        }
        # Omit when False so an unwatched task serializes byte-identically to pre-flight.
        if self.watch:
            data["watch"] = True
        # goal/acceptance get the same omit-when-None treatment (spec R6): a task
        # authored without them serializes byte-identically to today.
        if self.goal is not None:
            data["goal"] = self.goal
        if self.acceptance is not None:
            data["acceptance"] = list(self.acceptance)
        # attachments gets the same omit-when-None treatment (task t1): a task
        # authored without attachments serializes byte-identically to today.
        if self.attachments is not None:
            data["attachments"] = [dict(entry) for entry in self.attachments]
        # context_packet gets the same omit-when-None treatment (cortex/senses,
        # t2): a task authored without a senses packet serializes byte-identically
        # to today.
        if self.context_packet is not None:
            data["context_packet"] = self.context_packet.to_dict()
        # flight_repo_path gets the same omit-when-None treatment (#310): a
        # non-isolated task (in-place session, or any run whose plane arms at
        # repo_path) serializes byte-identically to today.
        if self.flight_repo_path is not None:
            data["flight_repo_path"] = self.flight_repo_path
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Task":
        raw_acceptance = data.get("acceptance")
        # Only a list-shaped payload is acceptance criteria: a bare string
        # would explode into per-character "criteria" via list() and corrupt
        # the loop's acceptance self-check (Qodo PR #260 review). Malformed
        # shapes degrade to None — the best-effort from_dict stance.
        acceptance = (
            [str(criterion) for criterion in raw_acceptance]
            if isinstance(raw_acceptance, list)
            else None
        )
        raw_attachments = data.get("attachments")
        # Only a list of dict-shaped entries is a valid attachments payload: a
        # bare string would explode into per-character entries via list() (the
        # same bare-string corruption class as acceptance, Qodo PR #260), and a
        # bare dict has no list shape at all. A non-dict entry anywhere in the
        # list has no "path"/"media_type" to coerce, so the whole payload
        # degrades to None rather than partially dropping entries — the
        # best-effort from_dict stance.
        attachments = (
            [
                {
                    "path": str(entry.get("path", "")),
                    "media_type": str(entry.get("media_type", "")),
                }
                for entry in raw_attachments
            ]
            if isinstance(raw_attachments, list)
            and all(isinstance(entry, dict) for entry in raw_attachments)
            else None
        )
        # Only a mapping is a valid context_packet: a bare string / list has no
        # packet shape to coerce, so it degrades to None rather than raising —
        # the best-effort from_dict stance (cortex/senses, t2).
        raw_packet = data.get("context_packet")
        context_packet = (
            ContextPacket.from_dict(raw_packet) if isinstance(raw_packet, dict) else None
        )
        return cls(
            id=str(data["id"]),
            repo_path=str(data["repo_path"]),
            instruction=str(data["instruction"]),
            context=str(data.get("context", "")),
            constraints=list(data.get("constraints", [])),
            engine=str(data.get("engine", "mock")),
            watch=bool(data.get("watch", False)),
            goal=data.get("goal"),
            acceptance=acceptance,
            attachments=attachments,
            context_packet=context_packet,
            flight_repo_path=(
                str(data["flight_repo_path"]) if data.get("flight_repo_path") is not None else None
            ),
        )


@dataclass
class TaskResult:
    """The shape every backend produces for a driven task.

    ``branch`` / ``pr_url`` are populated by the git/PR handoff; ``pr_url`` is
    ``None`` when the run stays local (``--no-pr`` or no remote). ``error`` is
    set only when ``status == ERROR``.
    """

    task_id: str
    status: str
    summary: str = ""
    changed_files: list[str] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    stats: WorkStats = field(default_factory=WorkStats)
    """Always-on per-work-item statistics (timing, tools used, bytes/chars produced).
    Sits beside ``usage`` (exact API token counts); together they make a work item's
    cost — and, with a feedback record, its ROI — readable from the artifact.
    Unlike destination/sub_results this key is ALWAYS serialized (it is never
    empty for a real drive); the e2e shape test pins it on every backend."""
    finish_states: list[FinishRecord] = field(default_factory=list)
    """Per-seat finish-state + truncation record for this work item (plan task
    t1, covers c4/h4, decision c30) — a :class:`FinishRecord` per seat that
    completed at least one turn (today: ``"main"`` always, plus ``"senses"``
    when a cortex/senses split ran). Like ``stats``, this key is ALWAYS
    serialized on EVERY run — unconfigured runs included (decision c30: the
    one sanctioned unconditional artifact addition, a recorded convention
    change exactly like always-on ``WorkStats`` and #313's ``incompletion``
    detector) — never omit-when-None/empty, so a caller can always read
    ``result.finish_states[0].state`` without a presence check. Populated by
    the loop (:func:`colleague.loop.run`) on every exit path, including the
    aborted (:class:`WorkAborted`) path, so even a crashed/timed-out partial
    artifact carries an honest finish state."""
    artifacts_path: Optional[str] = None
    error: Optional[str] = None
    branch: Optional[str] = None
    pr_url: Optional[str] = None
    hook_firings: list[HookFiring] = field(default_factory=list)
    """Every hook invocation that fired during this drive (populated by the loop)."""
    sub_results: list[SubResult] = field(default_factory=list)
    """Results of any sub-tasks delegated to nested child work items, in order; empty
    when this drive delegated nothing. Like destination/announcement, the
    serialized key is OMITTED (not null) when the list is empty, so a
    no-subagent result is byte-identical to today. Cost is nested-only — the
    parent ``usage`` is NOT summed with these children's."""
    command: Optional[str] = None
    """The command-template name that originated this task, or ``None`` for
    an ad-hoc instruction (e.g. plain ``colleague work "<text>"``).
    Populated by the CLI driver; ``None`` when the task was constructed
    programmatically without a named command."""
    destination: Optional[str] = None
    """The devague goal-frame slug the work item aimed at, or ``None`` when no
    destination was set (plain ``colleague work`` without ``--destination``)."""
    announcement: Optional[str] = None
    """The announcement text declared on arrival at the destination, or ``None``
    when no destination was set or no announcement was produced."""
    capacity_decision: Optional[CapacityDecision] = None
    """The one declared fill-line move (compact | split | finish-with-handoff) the
    runtime recorded when the running context crossed the fill-line threshold, or
    ``None`` when no fill-line event occurred (#156). Like destination/announcement,
    the serialized key is OMITTED (not null) when ``None`` so a work item that never
    filled its context is byte-identical to today's artifact shape."""
    capacity_warning: Optional[str] = None
    """The warn-only "too big for one repo" caller warning, set when the capacity
    assessment exceeds even the in-repo split capacity (#156), else ``None``. The
    operator performs the cross-repo split; colleague only warns. Omitted from the
    artifact (not null) when ``None``."""
    gates_deferred: bool = False
    """True when this chain episode deferred its pre-finish gates to the chain's
    final episode (#335 exit shapes) — the structured marker (#341) recorded by
    the loop alongside the ``capacity_warning`` deferral note, so chain
    accounting and artifact consumers never string-match prose. ``False`` is
    OMITTED from the artifact (a non-deferring run stays byte-identical)."""
    lint_report: Optional[LintReport] = None
    """The lint pre-finish gate's report, or ``None`` when linting did not run
    (disabled, or no linters configured). Like destination/capacity_decision,
    the serialized key is OMITTED (not null) when ``None``, so a work item that
    ran no lint gate is byte-identical to today."""
    coherence_report: Optional[CoherenceReport] = None
    """The coherence pre-finish gate's report (#294), or ``None`` when the gate
    did not run (disabled, or no changed ``.md`` files). Like lint_report, the
    serialized key is OMITTED (not null) when ``None``, so a run with no
    coherence finding is byte-identical."""
    test_integrity_report: Optional["TestIntegrityReport"] = None
    """The test-integrity mirror-detection report, or ``None`` when the gate
    produced no findings. Like lint_report, the serialized key is OMITTED
    (not null) when ``None``, so a work item with no mirror findings is
    byte-identical to pre-t1 artifacts."""
    affected_tests_report: Optional["AffectedTestsReport"] = None
    """The affected-tests pre-handoff gate report, or ``None`` when the gate
    produced no findings. Like lint_report, the serialized key is OMITTED
    (not null) when ``None``, so a work item with no affected-tests findings is
    byte-identical to pre-artifacts."""
    not_finished: bool = False
    """True iff the work item exhausted the step budget without calling ``finish`` AND
    without raising :class:`WorkAborted` (i.e. the model ran out of turns but the
    engine itself did not error).  False on a clean finish (finish tool called), a
    no-tool-call terminating answer, or the aborted path.  Set by :func:`loop.run`
    from the return value of ``_work_loop``; never inferred from
    ``stats.step_count`` (which counts tool calls, not model turns)."""
    stopped_without_finish: bool = False
    """True iff the work item ended on a **no-tool-call turn** and — even after the
    loop's one-shot finish nudge — never called ``finish`` (colleague#142). The
    ``summary`` then holds the model's trailing prose, so a caller must treat it as
    a *partial*, not an authoritative result. Orthogonal to ``not_finished`` (the
    step-budget case) and to the aborted path; a clean finish leaves both False.
    Set by :func:`loop.run` from the ``_work_loop`` return value."""
    role: Optional[str] = None
    """The typed-subagent role this work item ran as, or ``None`` for the default
    full-surface behavior (#t4). Set by :func:`loop.run` from
    ``ContextControls.role`` (the engine forwards ``config.role``). Omitted from
    ``to_dict`` when ``None``, so a role-less work item serializes byte-identically
    to the pre-role artifact shape."""
    mode: Optional[str] = None
    """The driving mode (auto|work|plan|explore|review) this work item ran under,
    or ``None`` when no mode was selected (plain ``colleague work`` without
    ``--mode`` / session mode selection) (spec R3 / plan t7 / #256). Set by
    :func:`colleague.cli._commands.work.execute_work`, NOT by the engine/loop —
    the mode concept lives at the CLI/session entry doors, so
    ``registry.load(...).work(...)`` called directly (as the e2e mock shape
    test does) never sets it. Like role/destination, the serialized key is
    OMITTED (not null) when ``None``, so a mode-less work item serializes
    byte-identically to the pre-mode artifact shape."""
    acceptance_outcomes: Optional[list[dict[str, Any]]] = None
    """Per-``Task.acceptance``-criterion self-check outcomes, or ``None`` when the
    work item carried no acceptance criteria (no self-check ran) (spec R6 / plan
    t14+t15 / #259). Each entry is a plain
    ``{"criterion": str, "met": bool, "evidence": str}`` record populated by the
    loop's bounded pre-finish self-check turn. These are ADVISORY only — they
    never flip ``status``; operator confirmation stays authoritative (matching
    the devague-tool convention). Like lint_report/destination, the serialized
    key is OMITTED (not null) when ``None``, so a work item with no acceptance
    criteria serializes byte-identically to today's artifact. ``from_dict``
    tolerates malformed (non-dict) entries by dropping them rather than
    raising, matching the codebase's best-effort stance on optional structured
    payloads read back from an artifact."""
    deepthink: Optional[list[DeepthinkCall]] = None
    """Every escalation call to the "deepthink" model fired during this work
    item, in order, or ``None`` when no dual-model config was present / no
    escalation occurred (plan task t3, spec covers c14/h6). Each record is a
    :class:`DeepthinkCall` (``{point, tokens, duration, degraded}``). Like
    ``lint_report``/``capacity_decision``/``acceptance_outcomes``, the
    serialized key is OMITTED (not null) when ``None``, so a single-model
    work item serializes byte-identically to today's artifact. Populated by
    the loop (plan task t5) each time it escalates via the deepthink seam
    (:mod:`colleague.deepthink`)."""
    finish_recovered: Optional[str] = None
    """How the summary was recovered when the model's finish *transport* failed
    (#248), or ``None`` when the finish arrived intact. ``"literal-markup"``:
    the model emitted its finish as literal tool-call text in message content
    and the loop re-parsed it as the finish payload. ``"thin-finish-synthesis"``:
    the finish carried only a headline after a read-heavy zero-write run, so one
    forced synthesis turn (#191) produced the real report. The honest degradation
    marker required by the best-colleague-arc spec (h8): a recovered report is
    diagnosable from the artifact, never silent. Omit-when-None like
    role/mode/deepthink, so an intact-finish run serializes byte-identically."""
    memory: Optional[dict[str, Any]] = None
    """The memory-informed-runtime exchange for this work item (spec R1 / plan
    t2), or ``None`` when memory never armed (no ``.eidetic/`` store, no eidetic
    CLI, or disabled). A plain ``{"query", "recalled", "injected_chars",
    "lesson_recorded"}`` record populated by the loop: what was recalled and
    injected before work (h7: token-capped and diagnosable from the artifact —
    a misleading memory is traceable, never silent) and whether the post-run
    lesson landed in the store. Omit-when-None, so a memory-less run serializes
    byte-identically."""
    media: Optional[dict[str, Any]] = None
    """Delivery record for the task's media attachments (t9, decision c25), or
    ``None`` for an attachment-less run. Shape: ``{"attachments": [{"path",
    "status"}]}`` where ``status`` is ``"delivered"``, ``"dropped"``,
    ``"unknown"`` (no usage reported), or ``"bridged"`` (the main model is
    declared text-only and a multimodal second model delivered a description
    via the media bridge, t8) — the token-contribution verdict, which proves
    the media ENTERED a prompt, never that the model *understood* it
    (comprehension is claimed only by the livecheck red-pixel proof). Populated
    by the loop after the first media-bearing completion (or preset by a
    successful bridge); omit-when-None so an attachment-less run serializes
    byte-identically."""
    senses: Optional[SensesBlock] = None
    """The cortex/senses front-door record for this work item (cortex/senses,
    t2), or ``None`` when no senses model ran (a plain cortex-only drive). A
    :class:`SensesBlock` of shape ``{mode, packet, records}`` where ``packet`` is
    the :class:`ContextPacket` the senses model produced and ``records`` is the
    list of per-invocation :class:`SensesRecord` (``{point, latency, tokens,
    degraded}``). This is the same shape family as ``deepthink`` — an optional
    payload with nested records mirroring :class:`DeepthinkCall`. Like
    ``deepthink``/``lint_report``/``acceptance_outcomes``, the serialized key is
    OMITTED (not null) when ``None``, so a run with no senses involvement
    serializes byte-identically to today's artifact. The packet's ``original``
    text round-trips verbatim."""
    incompletion: Optional[IncompletionRecord] = None
    """Record of why a work item was incomplete, or ``None`` when the work item
    completed normally. A :class:`IncompletionRecord` of shape
    ``{reason, evidence, recommendation}``. Like ``senses``/``deepthink``,
    the serialized key is OMITTED (not null) when ``None``, so a completed
    work item serializes byte-identically to today's artifact."""
    continued_from: Optional[str] = None
    """The task id of the prior work item this run CONTINUES (#167), or ``None``
    for an ordinary run. Set by the CLI/session continue path when the new
    Task was seeded from a persisted artifact's continuation record — one-way
    lineage (the old artifact is never mutated). Like ``incompletion``, the
    serialized key is OMITTED (not null) when ``None``, so a non-continued run
    serializes byte-identically."""
    chain: Optional[ChainView] = None
    """Chain-of-episodes accounting for a chained run (``--until-done``, c20),
    or ``None`` for an ordinary single-episode run. A :class:`ChainView` of
    shape ``{episode_index, episode_count, total_steps, total_prompt_tokens,
    total_completion_tokens, total_tokens}`` where every total is a SUM of
    per-episode exact usage — never estimated (the tokens-are-exact rule,
    h19); ``usage``/``stats`` on this result stay this episode's own exact
    numbers, never merged. Set by the chain dispatch loop, not by the
    engine/loop. Like ``continued_from``, the serialized key is OMITTED (not
    null) when ``None``, so a non-chained run serializes byte-identically."""
    config_events: list[ConfigEvent] = field(default_factory=list)
    """The append-only config event stream for this work item (plan task t7,
    covers c9/h9) — the ordered ``baseline``/``proposed``/``refused``/
    ``verified``/``applied``/``reverted`` moves recorded by
    :mod:`colleague.configevents`. BASELINE IS AN EVENT KIND (the T8 trap): a
    seeded starting config must appear here as an ordinary event, never as an
    invisible constructor default, because ``config_digest`` is a pure
    function of THIS list alone (see :func:`colleague.configevents.effective_digest`).
    Empty when no config-event activity occurred (today's common case — the
    t11 configurator that populates this in earnest is a later task). Like
    ``sub_results``, the serialized key is OMITTED (not an empty list) when
    this list is empty, so a run with no recorded config events serializes
    byte-identically to today's artifact."""
    config_digest: Optional[str] = None
    """The deterministic sha256 digest of ``config_events``
    (:func:`colleague.configevents.effective_digest`), recomputed from the
    REPLAYED event sequence alone — no ambient state. ``None`` when
    ``config_events`` is empty (nothing to digest). Like
    ``continued_from``/``chain``, the serialized key is OMITTED (not null)
    when ``None``, so a run with no config-event activity serializes
    byte-identically to today's artifact."""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "task_id": self.task_id,
            "status": self.status,
            "summary": self.summary,
            "changed_files": list(self.changed_files),
            "steps": [s.to_dict() for s in self.steps],
            "usage": self.usage.to_dict(),
            "stats": self.stats.to_dict(),
            # ALWAYS serialized, like "stats" above — decision c30 (t1): the one
            # sanctioned unconditional artifact addition, never omit-when-empty.
            "finish_states": [f.to_dict() for f in self.finish_states],
            "artifacts_path": self.artifacts_path,
            "error": self.error,
            "branch": self.branch,
            "pr_url": self.pr_url,
            "hook_firings": [h.to_dict() for h in self.hook_firings],
            "command": self.command,
            "not_finished": self.not_finished,
            "stopped_without_finish": self.stopped_without_finish,
        }
        # destination and announcement are OMITTED (not emitted as null) when
        # None.  This preserves byte-identical output for the no-destination
        # path — a work item without a destination must serialize identically to
        # today (honesty conditions c8/h8).  This intentionally deviates from
        # the convention used by command/pr_url/etc. which always emit their
        # key even as null; only these two new keys get omit-when-None treatment.
        if self.destination is not None:
            d["destination"] = self.destination
        if self.announcement is not None:
            d["announcement"] = self.announcement
        # capacity_decision / capacity_warning get the same omit-when-None
        # treatment (#156): a work item that never crossed the fill-line threshold
        # serializes byte-identically to today (no extra keys).
        if self.capacity_decision is not None:
            d["capacity_decision"] = self.capacity_decision.to_dict()
        if self.capacity_warning is not None:
            d["capacity_warning"] = self.capacity_warning
        # gates_deferred gets omit-when-False treatment (#341): only a chain
        # episode that actually deferred its gates carries the key.
        if self.gates_deferred:
            d["gates_deferred"] = True
        if self.lint_report is not None:
            d["lint_report"] = self.lint_report.to_dict()
        if self.coherence_report is not None:
            d["coherence_report"] = self.coherence_report.to_dict()
        if self.test_integrity_report is not None:
            d["test_integrity_report"] = self.test_integrity_report.to_dict()
        # role gets the same omit-when-None treatment (#t4): a role-less work item
        # serializes byte-identically to the pre-role artifact (no extra key).
        if self.role is not None:
            d["role"] = self.role
        d.update(self._extra_fields_to_dict())
        # sub_results is OMITTED (not emitted as an empty list) when no sub-task
        # was delegated — mirroring the destination/announcement omit-when-None
        # pattern above so a no-subagent drive serializes byte-identically to
        # today's contract.
        if self.sub_results:
            d["sub_results"] = [s.to_dict() for s in self.sub_results]
        return d

    def _extra_fields_to_dict(self) -> dict[str, Any]:
        """The omit-when-None extras added after the original destination/lint
        convention — ``mode``, ``affected_tests_report``, ``acceptance_outcomes``,
        ``deepthink``, ``finish_recovered``, ``memory``, ``media``, ``senses``.

        Split out of :meth:`to_dict` purely to hold its cognitive complexity
        under the SonarCloud S3776 ceiling (15) — pure extraction, no behavior
        change; the returned partial dict is merged into ``to_dict``'s result in
        the SAME key order these were previously inserted in.
        """
        extra: dict[str, Any] = {}
        # mode gets the same omit-when-None treatment (spec R3 / plan t7): a
        # mode-less work item serializes byte-identically to the pre-mode artifact
        # (no extra key).
        if self.mode is not None:
            extra["mode"] = self.mode
        if self.affected_tests_report is not None:
            extra["affected_tests_report"] = self.affected_tests_report.to_dict()
        # acceptance_outcomes gets the same omit-when-None treatment (spec R6): a
        # work item with no acceptance criteria serializes byte-identically to
        # today's artifact (no extra key).
        if self.acceptance_outcomes is not None:
            extra["acceptance_outcomes"] = [dict(entry) for entry in self.acceptance_outcomes]
        # deepthink gets the same omit-when-None treatment (plan task t3): a
        # single-model work item (or one that never escalated) serializes
        # byte-identically to today's artifact (no extra key).
        if self.deepthink is not None:
            extra["deepthink"] = [c.to_dict() for c in self.deepthink]
        # finish_recovered gets the same omit-when-None treatment (#248): an
        # intact-finish work item serializes byte-identically (no extra key).
        if self.finish_recovered is not None:
            extra["finish_recovered"] = self.finish_recovered
        # memory gets the same omit-when-None treatment (spec R1 / plan t2): a
        # memory-less work item serializes byte-identically (no extra key).
        if self.memory is not None:
            extra["memory"] = dict(self.memory)
        # media gets the same omit-when-None treatment (t9): an attachment-less
        # work item serializes byte-identically (no extra key).
        if self.media is not None:
            extra["media"] = {
                "attachments": [dict(entry) for entry in self.media.get("attachments", [])]
            }
        # senses gets the same omit-when-None treatment as deepthink (cortex/senses,
        # t2): a run with no senses front door serializes byte-identically to
        # today's artifact (no extra key).
        if self.senses is not None:
            extra["senses"] = self.senses.to_dict()
        # incompletion gets the same omit-when-None treatment: a completed
        # work item serializes byte-identically (no extra key).
        if self.incompletion is not None:
            extra["incompletion"] = self.incompletion.to_dict()
        # continued_from gets the same omit-when-None treatment (#167): a
        # non-continued run serializes byte-identically (no extra key).
        if self.continued_from is not None:
            extra["continued_from"] = self.continued_from
        # chain gets the same omit-when-None treatment (c20): a non-chained
        # run serializes byte-identically (no extra key).
        if self.chain is not None:
            extra["chain"] = self.chain.to_dict()
        # config_events/config_digest get the same omit-when-empty/None
        # treatment as sub_results/continued_from (plan task t7): a run with
        # no recorded config-event activity serializes byte-identically to
        # today's artifact (no extra keys).
        if self.config_events:
            extra["config_events"] = [e.to_dict() for e in self.config_events]
        if self.config_digest is not None:
            extra["config_digest"] = self.config_digest
        return extra

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskResult":
        return cls(
            task_id=str(data["task_id"]),
            status=str(data["status"]),
            summary=str(data.get("summary", "")),
            changed_files=list(data.get("changed_files", [])),
            steps=[Step.from_dict(s) for s in data.get("steps", [])],
            usage=Usage.from_dict(data.get("usage", {})),
            stats=WorkStats.from_dict(data.get("stats", {})),
            finish_states=[
                FinishRecord.from_dict(f)
                for f in data.get("finish_states", [])
                if isinstance(f, dict)
            ],
            artifacts_path=data.get("artifacts_path"),
            error=data.get("error"),
            branch=data.get("branch"),
            pr_url=data.get("pr_url"),
            hook_firings=[HookFiring.from_dict(h) for h in data.get("hook_firings", [])],
            sub_results=[SubResult.from_dict(s) for s in data.get("sub_results", [])],
            command=data.get("command"),
            destination=data.get("destination"),
            announcement=data.get("announcement"),
            capacity_decision=(
                CapacityDecision.from_dict(data["capacity_decision"])
                if data.get("capacity_decision")
                else None
            ),
            capacity_warning=data.get("capacity_warning"),
            # gates_deferred parses strictly (#341): artifacts are external
            # inputs, so only the JSON boolean ``true`` reads True — any other
            # type/value (a "false" string, an int, a dict) degrades to False,
            # never guessed (the ChainView.from_dict degrade-to-empty stance).
            gates_deferred=data.get("gates_deferred") is True,
            lint_report=(
                LintReport.from_dict(data["lint_report"]) if data.get("lint_report") else None
            ),
            coherence_report=(
                CoherenceReport.from_dict(data["coherence_report"])
                if data.get("coherence_report")
                else None
            ),
            test_integrity_report=(
                _get_test_integrity_report_class().from_dict(data["test_integrity_report"])
                if data.get("test_integrity_report")
                else None
            ),
            affected_tests_report=(
                _get_affected_tests_report_class().from_dict(data["affected_tests_report"])
                if data.get("affected_tests_report")
                else None
            ),
            not_finished=bool(data.get("not_finished", False)),
            stopped_without_finish=bool(data.get("stopped_without_finish", False)),
            role=data.get("role"),
            mode=data.get("mode"),
            acceptance_outcomes=_coerce_acceptance_outcomes(data.get("acceptance_outcomes")),
            deepthink=_coerce_deepthink_calls(data.get("deepthink")),
            finish_recovered=data.get("finish_recovered"),
            memory=data.get("memory"),
            media=data.get("media") if isinstance(data.get("media"), dict) else None,
            senses=(
                SensesBlock.from_dict(data["senses"])
                if isinstance(data.get("senses"), dict)
                else None
            ),
            incompletion=(
                IncompletionRecord.from_dict(data["incompletion"])
                if isinstance(data.get("incompletion"), dict)
                else None
            ),
            continued_from=(
                str(data["continued_from"]) if data.get("continued_from") is not None else None
            ),
            chain=(
                ChainView.from_dict(data["chain"]) if isinstance(data.get("chain"), dict) else None
            ),
            config_events=_coerce_config_events(data.get("config_events")),
            config_digest=data.get("config_digest"),
        )


def _coerce_omissions(value: Any) -> list[str]:
    """Coerce a raw ``omissions`` payload read back from an artifact.

    Mirrors :func:`colleague.senses._coerce_omissions` (kept as a standalone
    copy, not an import, to avoid a circular import: ``colleague.senses``
    already imports :class:`ContextPacket` from this module). A malformed
    artifact's ``omissions`` may be missing, ``None``, a non-string scalar
    (e.g. an int), or a bare string — none of those should crash or
    misbehave (a bare string previously iterated per-character via
    ``[str(o) for o in "abc"]``, Qodo finding #1 on the cortex/senses PR
    #281). A list/tuple becomes ``[str(x) for x in value]``; a bare string
    becomes a single-element list; anything else (``None``, a number, a
    dict) becomes ``[]`` — tolerant of a malformed artifact, never raises.
    """
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(x) for x in value]
    return []


#: Hard cap on ``ContextPacket.ack`` length, mirroring
#: :data:`colleague.senses._MAX_ACK_LEN` (kept as a standalone literal, not an
#: import, for the same circular-import reason as :func:`_coerce_ack` below).
_MAX_ACK_LEN = 500


def _coerce_ack(value: Any) -> Optional[str]:
    """Coerce a raw ``ack`` payload read back from an artifact.

    Mirrors :func:`colleague.senses._coerce_ack` (kept as a standalone copy,
    not an import, to avoid a circular import: ``colleague.senses`` already
    imports :class:`ContextPacket` from this module). A non-string value
    (e.g. a number or dict from a malformed artifact) degrades to ``None``
    rather than raising downstream — ``session.py``'s ``_render_ack`` does
    ``(ack or "").strip()``, which would raise ``AttributeError`` on a
    truthy non-string ack. A string is stripped of surrounding whitespace
    and hard-capped to :data:`_MAX_ACK_LEN` characters; an empty/whitespace-only
    result degrades to ``None`` (matching :func:`colleague.senses._coerce_ack`'s
    "no usable ack is simply absent" stance).
    """
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return stripped[:_MAX_ACK_LEN]


def _coerce_acceptance_outcomes(
    raw: Optional[list[Any]],
) -> Optional[list[dict[str, Any]]]:
    """Coerce a raw ``acceptance_outcomes`` payload read back from an artifact.

    ``None`` in, ``None`` out (no acceptance criteria were set — the common
    case). When a list is present, each entry is expected to be a
    ``{"criterion": str, "met": bool, "evidence": str}`` mapping; a malformed
    (non-dict) entry is dropped rather than raising, matching the codebase's
    best-effort stance elsewhere on optional structured payloads read back
    from JSON (e.g. :class:`TestIntegrityReport`'s "never raises" contract).
    """
    if raw is None:
        return None
    outcomes: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        outcomes.append(
            {
                "criterion": str(entry.get("criterion", "")),
                "met": bool(entry.get("met", False)),
                "evidence": str(entry.get("evidence", "")),
            }
        )
    return outcomes


def _coerce_deepthink_calls(
    raw: Optional[list[Any]],
) -> Optional[list[DeepthinkCall]]:
    """Coerce a raw ``deepthink`` payload read back from an artifact.

    ``None`` in, ``None`` out (no dual-model config was present / no
    escalation occurred — the common case). When a list is present, each
    entry is expected to be a :class:`DeepthinkCall`-shaped mapping; a
    malformed (non-dict) entry is dropped rather than raising, matching the
    codebase's best-effort stance on optional structured payloads read back
    from JSON (see :func:`_coerce_acceptance_outcomes`).
    """
    if raw is None:
        return None
    calls: list[DeepthinkCall] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        calls.append(DeepthinkCall.from_dict(entry))
    return calls


def _coerce_config_events(raw: Optional[list[Any]]) -> list[ConfigEvent]:
    """Coerce a raw ``config_events`` payload read back from an artifact.

    ``None``/absent in, ``[]`` out (no config-event activity — the common
    case, matching ``sub_results``'s own default-empty-list stance rather
    than ``deepthink``'s default-``None`` stance, since ``config_events`` is
    itself list-shaped and omit-when-**empty**, not omit-when-None). A
    malformed (non-dict) entry is dropped rather than raising, matching the
    codebase's best-effort stance on optional structured payloads read back
    from JSON (see :func:`_coerce_deepthink_calls`).

    An entry carrying a non-empty ``"content"`` key (t8) is parsed via
    :meth:`ConfigEventRecord.from_dict` instead of the bare
    :class:`ConfigEvent`'s own ``from_dict`` — every OTHER entry (the common
    case: an old artifact predating ``content``, or any event this fold never
    attaches content to) stays a plain :class:`ConfigEvent`, so
    ``restored.config_events == original_events`` keeps holding for every
    pre-t8 round-trip test that compares against hand-built
    :class:`ConfigEvent` instances (dataclass equality requires the SAME
    class). Content-bearing entries opt into the richer subclass; everything
    else round-trips byte-for-byte and class-for-class exactly as before.
    """
    if not raw:
        return []
    events: list[ConfigEvent] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        if entry.get("content"):
            events.append(ConfigEventRecord.from_dict(entry))
        else:
            events.append(ConfigEvent.from_dict(entry))
    return events


# ---------------------------------------------------------------------------
# Config event fold (three-tier-execution plan task t8, covers c6/h6/c36/h29)
# ---------------------------------------------------------------------------
#
# colleague.configlifecycle.EpisodeConfigLifecycle keeps its OWN small,
# in-memory event log (kind in {"proposed", "refused", "applied", "boundary"}
# — a deliberate subset of the full configevents vocabulary; see that
# module's own docstring) plus a per-window application history. Neither of
# those lifecycle-native shapes is what TaskResult.config_events carries —
# this section is the ONE mapper that turns the lifecycle's own records into
# durable configevents.ConfigEvent entries, reusing the vocabulary
# configevents.py already owns rather than inventing a parallel one here.
# configevents.py itself belongs to a sibling task (t6) this wave and is
# never touched by this mapper or by ConfigEventRecord below — both are
# contract.py's own compatible extension of ConfigEvent's shape.


#: Lifecycle kind -> the honest configevents.py kind it maps onto.
#: "proposed"/"refused"/"applied" share their literal string with
#: configevents' own EVENT_KIND_* constants (imported, not re-typed here, so
#: a rename on either side cannot silently drift the mapping out of sync).
#: "boundary" has no durable counterpart of its own in configevents.py: an
#: episode boundary marks a RESTING config STATE observed at that instant
#: (never a change action) — which is exactly what EVENT_KIND_BASELINE
#: already means in that module's vocabulary (a "starting config, seeded"
#: checkpoint the T8-trap guard requires to be explicit). Every OTHER kind in
#: EVENT_KINDS (proposed/refused/verified/applied/reverted/degraded)
#: describes a mutation, so baseline is the one honest existing kind a
#: boundary can map onto without inventing a new one.
_LIFECYCLE_KIND_TO_CONFIG_EVENT_KIND: dict[str, str] = {
    "proposed": EVENT_KIND_PROPOSED,
    "refused": EVENT_KIND_REFUSED,
    "applied": EVENT_KIND_APPLIED,
    "boundary": EVENT_KIND_BASELINE,
}

#: The one lattice target string whose APPLIED unit carries content worth
#: folding onto the artifact. Mirrors
#: ``colleague.lattice.Target.WORKER_PROMPT_STRATEGIST.value`` — duck-typed
#: here (a plain string compare) rather than importing ``colleague.lattice``,
#: so this mapper stays exactly as decoupled from the lattice's typed surface
#: as ``colleague/configevents.py`` itself already is (that module's own
#: docstring: "target/origin are free-form strings here ... so this stream
#: stays usable by any future producer").
_STRATEGIST_TARGET_VALUE = "worker.prompt.strategist"


@dataclass
class ConfigEventRecord(ConfigEvent):
    """A :class:`~colleague.configevents.ConfigEvent` extended with the
    verbatim applied strategist ``content`` (plan task t8, decision q5).

    ``configevents.py`` belongs to a sibling task this wave and is not
    touched here — this subclass is contract.py's own COMPATIBLE extension
    of the base dataclass's ``to_dict``/``from_dict`` shape: ``content`` is
    OMITTED (not emitted as an empty string) whenever it is empty, so an
    ordinary proposed/refused/applied-non-strategist/baseline record
    serializes byte-identically to a plain :class:`ConfigEvent`, and an
    artifact written before this field existed loads with ``content=""``
    (falsy — round-trips right back to the same omitted shape old artifacts
    always had). Only an APPLIED ``worker.prompt.strategist`` record ever
    carries a non-empty ``content``; refused records stay reason-only
    (acceptance 2) — nothing here special-cases that, it simply follows from
    :func:`map_configlifecycle_events` never setting ``content`` on anything
    but an applied strategist record.

    A plain :class:`ConfigEvent` (e.g. one another producer like
    :mod:`colleague.configurator` appends directly onto a
    :class:`~colleague.configevents.ConfigEventStream`) is left completely
    alone by this subclass's existence — its own ``to_dict`` is unaffected,
    since Python dispatches on each instance's *actual* class.
    """

    content: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        if self.content:
            d["content"] = self.content
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ConfigEventRecord":
        base = ConfigEvent.from_dict(data)
        return cls(
            kind=base.kind,
            target=base.target,
            origin=base.origin,
            reason=base.reason,
            seq=base.seq,
            content=str(data.get("content", "") or ""),
        )


def map_configlifecycle_events(
    events: Sequence[Any],
    *,
    applied_units: Sequence[Any] = (),
) -> list[ConfigEvent]:
    """Map one :meth:`~colleague.configlifecycle.EpisodeConfigLifecycle.events`
    replay (append-only, kind in ``{"proposed", "refused", "applied",
    "boundary"}``) onto durable :class:`ConfigEvent` entries — the shape
    :attr:`TaskResult.config_events` carries. A mapped event that carries
    applied strategist content (see *applied_units* below) is a
    :class:`ConfigEventRecord`; every other mapped event is a PLAIN
    :class:`ConfigEvent` — the same class-selection rule
    :func:`_coerce_config_events` uses reading an artifact back, so mapper
    output and a round-tripped artifact are indistinguishable.

    *events* is duck-typed (each item needs only ``.kind``/``.target``/
    ``.origin``/``.detail`` attributes) so this function never imports
    ``colleague.configlifecycle`` — mirroring ``colleague/configevents.py``'s
    own "free-form, usable by any future producer" stance. Kinds map
    honestly (see :data:`_LIFECYCLE_KIND_TO_CONFIG_EVENT_KIND`); an
    unrecognized kind passes through UNCHANGED rather than being invented
    into something new — unreachable today (the lifecycle emits only the
    four kinds named above), a signal that a future lifecycle kind needs its
    own deliberate mapping decision if this fallback ever actually fires.
    ``seq`` is assigned by THIS function from each event's position in
    *events* (the lifecycle's own ``ConfigEvent`` carries no ``seq`` of its
    own — only :class:`~colleague.configevents.ConfigEventStream` does).

    *applied_units* supplies the actual :class:`~colleague.lattice.ChangeUnit`
    objects that were applied — matched POSITIONALLY, one per "applied"-kind
    lifecycle event, in the same order
    :meth:`~colleague.configlifecycle.EpisodeConfigLifecycle.apply_window`
    drained its queue (a caller accumulates this across every sanctioned
    window it has run so far — e.g. ``colleague.chain.run_configurator_
    window``'s ``ConfiguratorWindowResult.review.verified`` units — since the
    applied CONTENT lives on neither the lifecycle event nor
    :class:`~colleague.configlifecycle.ConfigApplication`; only the
    originally-queued :class:`~colleague.lattice.ChangeUnit` carries it).
    Content rides the mapped record ONLY when the paired unit targets
    ``worker.prompt.strategist`` (the lattice's only content-bearing target
    this lifecycle ever applies — ``senses.*`` proposals are refused before
    they ever queue). Every other applied unit (worker.tools/
    worker.knowledge) contributes nothing to ``content``, matching the
    "refused records stay reason-only, content only on applied strategist
    records" acceptance (criterion 2). *applied_units* shorter than the
    number of "applied" events in *events* is tolerated (the trailing
    applied events simply get no content) — this function never raises.
    """
    applied_iter = iter(applied_units)
    mapped: list[ConfigEvent] = []
    for seq, event in enumerate(events):
        kind = str(getattr(event, "kind", ""))
        mapped_kind = _LIFECYCLE_KIND_TO_CONFIG_EVENT_KIND.get(kind, kind)
        # "refused records stay reason-only" (acceptance 2): every other kind
        # keeps reason empty, matching ConfigEvent's own stated convention
        # ("populated for a refused event ... empty for every other kind").
        reason = str(getattr(event, "detail", "")) if kind == "refused" else ""
        content = ""
        if kind == "applied":
            unit = next(applied_iter, None)
            if unit is not None:
                target = getattr(unit, "target", None)
                target_value = getattr(target, "value", target)
                unit_content = str(getattr(unit, "content", "") or "")
                if target_value == _STRATEGIST_TARGET_VALUE and unit_content:
                    content = unit_content.strip()
        base_kwargs: dict[str, Any] = {
            "kind": mapped_kind,
            "target": str(getattr(event, "target", "")),
            "origin": str(getattr(event, "origin", "")),
            "reason": reason,
            "seq": seq,
        }
        if content:
            mapped.append(ConfigEventRecord(content=content, **base_kwargs))
        else:
            mapped.append(ConfigEvent(**base_kwargs))
    return mapped


def config_digest_for(events: Sequence[ConfigEvent]) -> Optional[str]:
    """``TaskResult.config_digest`` for *events* — :func:`colleague.
    configevents.effective_digest` over the sequence, or ``None`` when
    *events* is empty.

    Mirrors ``config_digest``'s own omit-when-``None`` field convention, and
    exists so the "digest is a pure function of ``config_events``" invariant
    stays true from ONE call site — a caller that just changed
    ``config_events`` (the front folding a window, or
    :func:`colleague.artifact.update_config_events` rewriting an
    already-persisted artifact) recomputes ``config_digest`` from here rather
    than each re-deriving the omit-when-empty rule independently.
    """
    if not events:
        return None
    return effective_digest(list(events))


# ── lazy import helper (avoids circular import at module level) ─────────


def _get_test_integrity_report_class():
    """Return the TestIntegrityReport class via a lazy import.

    ``colleague.testintegrity`` imports ``colleague.contract`` (for the
    type annotation on ``TaskResult.test_integrity_report``), so we cannot
    import it at the top of this module.  This helper defers the import to
    the point where it is actually needed (``from_dict``).
    """
    from colleague.testintegrity import TestIntegrityReport

    return TestIntegrityReport


def _get_affected_tests_report_class():
    """Return the AffectedTestsReport class via a lazy import.

    ``colleague.affectedtests`` imports ``colleague.contract`` (for the
    type annotation on ``TaskResult.affected_tests_report``), so we cannot
    import it at the top of this module.  This helper defers the import to
    the point where it is actually needed (``from_dict``).
    """
    from colleague.affectedtests import AffectedTestsReport

    return AffectedTestsReport
