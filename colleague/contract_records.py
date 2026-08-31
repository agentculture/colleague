"""Small standalone record dataclasses split out of :mod:`colleague.contract`
(task t13, hard-1000-line-file-limit): :class:`FinishRecord`,
:class:`HookFiring`, :class:`Usage`, :class:`WorkStats`, :class:`SubResult`,
:class:`DeepthinkCall`, :class:`Step`, and :class:`ChainView` — the per-turn
and per-work-item bookkeeping records ``TaskResult`` composes over. Each is a
self-contained ``to_dict``/``from_dict`` dataclass (``SubResult`` composes
``Usage``; ``ChainView`` needs its own tiny ``_coerce_count`` helper, kept
local here rather than in ``contract_coerce`` to avoid a dependency cycle
with that module's own use of :class:`DeepthinkCall`). This module is also
the ONE definition of the ``DECISION_*``/``FINISH_*`` string constants
(:class:`HookFiring`/:class:`FinishRecord` default onto them) — moved here
rather than duplicated, so ``colleague.contract`` imports and re-exports
them rather than re-declaring. Re-exported from ``colleague.contract`` so
every existing ``from colleague.contract import ...`` call site resolves
unmodified.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

# HookFiring.decision values.
DECISION_ALLOW = "allow"
DECISION_DENY = "deny"
DECISION_REWRITE = "rewrite"
DECISION_OBSERVE = "observe"

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
    :class:`colleague.contract_senses.SensesRecord`) — a free-form string (not
    a closed enum) so a future seat (e.g. the three-tier ``worker``) can be
    distinguished without a shape change (see docs/plans/2026-08-05-three-tier-
    execution.md task t1's "per-seat" design note).

    ``finish_reason`` is the raw value a backend's wire format reported for
    the LAST completion on this seat (``""`` when the backend/engine never
    reports the field — the mock engine's deliberate finishes still set a
    representative value; a degraded/tools-off seat like ``senses`` has none
    to report and stays ``""``). ``state`` is the loop's classification onto
    one of the five finish states — the single normalized source of
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

    Token honesty (c11/c17): tokens live on :class:`Usage`, verbatim from the
    response ``usage`` — never estimated. "Thought vs written" is exact
    **chars/bytes**, not tokens: ``reasoning_*`` = ``message.reasoning``,
    ``answer_*`` = ``message.content``, ``bytes_written`` = UTF-8 bytes written
    via ``write_file``; no tokenizer, so no synthesised token counts.

    Fields
    ------
    request / engine / model:
        The originating task instruction; the backend that ran it
        (``task.engine``); the model id the engine was configured to call
        (the configured id even for ``mock``, empty when none was threaded) —
        together the self-describing ROI block.
    counts:
        Exact harness counters (plan t20, :mod:`colleague.runcounts`) —
        emitted only when non-empty, so an untouched run keeps its shape.
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
    web_calls / web_failed:
        The web-call budget (colleague/webbudget.py, plan t9): total ``web``
        tool calls this work item made, and how many of those failed. Old
        artifacts (pre-t9) load with both at 0.
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
    web_calls: int = 0  # t9: web-call budget — colleague/webbudget.py
    web_failed: int = 0
    counts: dict[str, int] = field(default_factory=dict)

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
        data = {
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
            "web_calls": self.web_calls,
            "web_failed": self.web_failed,
        }
        if self.counts:  # t20: omit-when-zero keeps the pre-arc 14-key shape
            data["counts"] = {k: int(v) for k, v in self.counts.items()}
        return data

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
            web_calls=int(data.get("web_calls", 0)),
            web_failed=int(data.get("web_failed", 0)),
            counts={str(k): int(v) for k, v in (data.get("counts") or {}).items()},
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
    agent_id: Optional[str] = None
    """The model-bound agent identity this child ran as (#411 plan task t14) —
    set ONLY when the parent's ``agents`` mode is armed and the child carried a
    ``profile``; ``None`` otherwise and omitted from ``to_dict`` so an unarmed
    child serializes byte-identically to today."""
    resolved_model: Optional[str] = None
    """The served model id the child's profile RESOLVED to (trace data from the
    lobes advert, or the parent's main model under the no-gateway degrade) —
    armed-only, omit-when-None like ``agent_id``."""
    fallback_from_role: Optional[str] = None
    """The lobes role the child's profile was carried FROM when it fell back to
    the cortex/main model (absent, not-ready, dormant per d3, or no gateway) —
    a RECORDED fallback, never silent. ``None`` when the child ran on its own
    ready role (or unarmed); omitted from ``to_dict`` when ``None``."""

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
        # Armed-only identity fields (#411 t14): omit-when-None, same convention.
        if self.agent_id is not None:
            d["agent_id"] = self.agent_id
        if self.resolved_model is not None:
            d["resolved_model"] = self.resolved_model
        if self.fallback_from_role is not None:
            d["fallback_from_role"] = self.fallback_from_role
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
            agent_id=data.get("agent_id"),
            resolved_model=data.get("resolved_model"),
            fallback_from_role=data.get("fallback_from_role"),
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
    def accumulate(cls, prior: Optional["ChainView"], result: Any) -> "ChainView":
        """The chain view for the episode that produced ``result``.

        ``prior`` is the view stamped on the previous episode's artifact
        (``None`` for the first episode). Every total is the prior total plus
        this episode's exact number read verbatim off ``result.usage`` /
        ``result.stats`` — sums of exacts, never estimates (h19).

        ``result`` is a :class:`colleague.contract.TaskResult` (typed loosely
        here, as ``Any``, to avoid importing that module — the only remaining
        importer of this one — and creating a cycle; every attribute access
        below matches ``TaskResult``'s real shape).
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
