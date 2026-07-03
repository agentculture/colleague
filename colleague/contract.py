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
from typing import TYPE_CHECKING, Any, Optional

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
    """

    original: str
    interpretation: str = ""
    confidence: float = 0.0
    task_type: str = ""
    omissions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "original": self.original,
            "interpretation": self.interpretation,
            "confidence": self.confidence,
            "task_type": self.task_type,
            "omissions": list(self.omissions),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ContextPacket":
        """Coerce a raw ``ContextPacket``-shaped mapping read back from an artifact.

        ``original`` is kept **verbatim**: ``str()`` on an already-string value
        is identity, so the operator's exact text (whitespace, newlines,
        unicode) survives byte-for-byte. ``confidence`` is a best-effort numeric
        coercion — a value that cannot be parsed as ``float`` (e.g. a malformed
        artifact entry) falls back to ``0.0`` rather than raising, matching the
        codebase's best-effort stance on optional structured payloads read back
        from JSON (see :class:`DeepthinkCall`).
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
        )


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
    """

    point: str
    latency: Optional[float] = None
    tokens: Optional[int] = None
    degraded: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "point": self.point,
            "latency": self.latency,
            "tokens": self.tokens,
            "degraded": self.degraded,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SensesRecord":
        """Coerce a raw ``SensesRecord``-shaped mapping read back from an artifact.

        ``latency``/``tokens`` are best-effort numeric coercions: a value that
        cannot be parsed as ``float``/``int`` falls back to ``None`` rather than
        raising and aborting the whole ``TaskResult.from_dict`` call — exactly
        as :meth:`DeepthinkCall.from_dict` handles ``duration``/``tokens``.
        ``point``/``degraded`` still survive from the rest of the entry.
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
    lint_report: Optional[LintReport] = None
    """The lint pre-finish gate's report, or ``None`` when linting did not run
    (disabled, or no linters configured). Like destination/capacity_decision,
    the serialized key is OMITTED (not null) when ``None``, so a work item that
    ran no lint gate is byte-identical to today."""
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

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "task_id": self.task_id,
            "status": self.status,
            "summary": self.summary,
            "changed_files": list(self.changed_files),
            "steps": [s.to_dict() for s in self.steps],
            "usage": self.usage.to_dict(),
            "stats": self.stats.to_dict(),
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
        if self.lint_report is not None:
            d["lint_report"] = self.lint_report.to_dict()
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
            lint_report=(
                LintReport.from_dict(data["lint_report"]) if data.get("lint_report") else None
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
