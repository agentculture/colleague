"""Convertible task contract — the shared chassis.

Every engine driver consumes a :class:`Task` and produces a :class:`TaskResult`
of the *same shape*, regardless of which model ran underneath. That uniformity
is the whole point of Convertible: the caller assigns repo work without caring
which engine executed it.

The types are plain dataclasses with explicit ``to_dict`` / ``from_dict`` so a
result round-trips through JSON unchanged — the handoff artifact written by
:mod:`convertible.artifact` is simply ``TaskResult.to_dict()`` serialized, and
reloading it yields an equal object.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

# TaskResult.status values.
OK = "ok"
ERROR = "error"

# HookFiring.decision values.
DECISION_ALLOW = "allow"
DECISION_DENY = "deny"
DECISION_REWRITE = "rewrite"
DECISION_OBSERVE = "observe"


@dataclass
class HookFiring:
    """A record of one hook invocation during a drive.

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
    """Token accounting for a drive, summed across the loop's model calls."""

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
class SubResult:
    """The result of one delegated sub-task driven by a nested child drive.

    A drive may delegate a scoped sub-task to a nested child drive; each child
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

    @classmethod
    def new(
        cls,
        repo_path: str,
        instruction: str,
        *,
        engine: str = "mock",
        context: str = "",
        constraints: list[str] | None = None,
    ) -> "Task":
        """Create a task with a fresh short id."""
        return cls(
            id=uuid.uuid4().hex[:12],
            repo_path=repo_path,
            instruction=instruction,
            engine=engine,
            context=context,
            constraints=list(constraints or []),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "repo_path": self.repo_path,
            "instruction": self.instruction,
            "context": self.context,
            "constraints": list(self.constraints),
            "engine": self.engine,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Task":
        return cls(
            id=str(data["id"]),
            repo_path=str(data["repo_path"]),
            instruction=str(data["instruction"]),
            context=str(data.get("context", "")),
            constraints=list(data.get("constraints", [])),
            engine=str(data.get("engine", "mock")),
        )


@dataclass
class TaskResult:
    """The shape every engine produces for a driven task.

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
    artifacts_path: Optional[str] = None
    error: Optional[str] = None
    branch: Optional[str] = None
    pr_url: Optional[str] = None
    hook_firings: list[HookFiring] = field(default_factory=list)
    """Every hook invocation that fired during this drive (populated by the loop)."""
    sub_results: list[SubResult] = field(default_factory=list)
    """Results of any sub-tasks delegated to nested child drives, in order; empty
    when this drive delegated nothing. Like destination/announcement, the
    serialized key is OMITTED (not null) when the list is empty, so a
    no-subagent result is byte-identical to today. Cost is nested-only — the
    parent ``usage`` is NOT summed with these children's."""
    command: Optional[str] = None
    """The command-template name that originated this task, or ``None`` for
    an ad-hoc instruction (e.g. plain ``convertible drive "<text>"``).
    Populated by the CLI driver; ``None`` when the task was constructed
    programmatically without a named command."""
    destination: Optional[str] = None
    """The devague goal-frame slug the drive aimed at, or ``None`` when no
    destination was set (plain ``convertible drive`` without ``--destination``)."""
    announcement: Optional[str] = None
    """The announcement text declared on arrival at the destination, or ``None``
    when no destination was set or no announcement was produced."""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "task_id": self.task_id,
            "status": self.status,
            "summary": self.summary,
            "changed_files": list(self.changed_files),
            "steps": [s.to_dict() for s in self.steps],
            "usage": self.usage.to_dict(),
            "artifacts_path": self.artifacts_path,
            "error": self.error,
            "branch": self.branch,
            "pr_url": self.pr_url,
            "hook_firings": [h.to_dict() for h in self.hook_firings],
            "command": self.command,
        }
        # destination and announcement are OMITTED (not emitted as null) when
        # None.  This preserves byte-identical output for the no-destination
        # path — a drive without a destination must serialize identically to
        # today (honesty conditions c8/h8).  This intentionally deviates from
        # the convention used by command/pr_url/etc. which always emit their
        # key even as null; only these two new keys get omit-when-None treatment.
        if self.destination is not None:
            d["destination"] = self.destination
        if self.announcement is not None:
            d["announcement"] = self.announcement
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
            artifacts_path=data.get("artifacts_path"),
            error=data.get("error"),
            branch=data.get("branch"),
            pr_url=data.get("pr_url"),
            hook_firings=[HookFiring.from_dict(h) for h in data.get("hook_firings", [])],
            sub_results=[SubResult.from_dict(s) for s in data.get("sub_results", [])],
            command=data.get("command"),
            destination=data.get("destination"),
            announcement=data.get("announcement"),
        )
