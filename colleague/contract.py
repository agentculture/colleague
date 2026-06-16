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
from typing import Any, Optional

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

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "engine": self.engine,
            "model": self.model,
            "status": self.status,
            "summary": self.summary,
            "changed_files": list(self.changed_files),
            "usage": self.usage.to_dict(),
        }

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
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Task":
        return cls(
            id=str(data["id"]),
            repo_path=str(data["repo_path"]),
            instruction=str(data["instruction"]),
            context=str(data.get("context", "")),
            constraints=list(data.get("constraints", [])),
            engine=str(data.get("engine", "mock")),
            watch=bool(data.get("watch", False)),
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
        # sub_results is OMITTED (not emitted as an empty list) when no sub-task
        # was delegated — mirroring the destination/announcement omit-when-None
        # pattern above so a no-subagent drive serializes byte-identically to
        # today's contract.
        if self.sub_results:
            d["sub_results"] = [s.to_dict() for s in self.sub_results]
        return d

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
            not_finished=bool(data.get("not_finished", False)),
            stopped_without_finish=bool(data.get("stopped_without_finish", False)),
        )
