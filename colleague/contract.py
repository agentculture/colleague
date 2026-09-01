"""Colleague task contract — the shared task runtime.

Every engine driver consumes a :class:`Task` and produces a :class:`TaskResult`
of the *same shape*, regardless of which model ran underneath. That uniformity
is the whole point of Colleague: the caller assigns repo work without caring
which engine executed it.

The types are plain dataclasses with explicit ``to_dict`` / ``from_dict`` so a
result round-trips through JSON unchanged — the handoff artifact written by
:mod:`colleague.artifact` is simply ``TaskResult.to_dict()`` serialized, and
reloading it yields an equal object.

This module is the STAR CENTER of a star-shaped split (task t13,
hard-1000-line-file-limit): the many small record dataclasses ``TaskResult``
composes over live in sibling modules —
:mod:`colleague.contract_records` (turn/work-item bookkeeping: ``Usage``,
``WorkStats``, ``HookFiring``, ``FinishRecord``, ``Step``, ``SubResult``,
``DeepthinkCall``, ``ChainView``), :mod:`colleague.contract_senses`
(``ContextPacket``, ``SensesRecord``, ``SensesDirectRecord``, ``SensesBlock``),
:mod:`colleague.contract_reports` (``CapacityDecision``, ``CoherenceReport``,
``LintReport``, ``IncompletionRecord``), :mod:`colleague.contract_configevents`
(``ConfigEventRecord`` + the lifecycle→event mapper + the two digest helpers),
:mod:`colleague.contract_coerce` (the best-effort artifact-read coercers), and
:mod:`colleague.contract_taskresult_io` (``TaskResult``'s own
``to_dict``/``from_dict`` bodies, which reference nearly every one of the
above). Every name a caller could previously import from ``colleague.contract``
is re-exported here unchanged — this module stays the ONE stable import
surface; only its internal organization changed.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

from colleague.configevents import ConfigEvent
from colleague.contract_configevents import (
    ConfigEventRecord,
    config_digest_for,
    map_configlifecycle_events,
    prompt_digest_for,
)
from colleague.contract_records import (
    DECISION_ALLOW,
    DECISION_DENY,
    DECISION_OBSERVE,
    DECISION_REWRITE,
    FINISH_DELIBERATE,
    FINISH_EMPTY,
    FINISH_STATES,
    FINISH_STOPPED,
    FINISH_TIMEOUT,
    FINISH_TRUNCATED,
    ChainView,
    DeepthinkCall,
    FinishRecord,
    HookFiring,
    Step,
    SubResult,
    Usage,
    WorkStats,
)
from colleague.contract_reports import (
    CapacityDecision,
    CoherenceReport,
    IncompletionRecord,
    LintReport,
)
from colleague.contract_senses import (
    SENSES_CHAT_KINDS,
    SENSES_LOOP_POINT_PREFIX,
    ContextPacket,
    SensesBlock,
    SensesDirectRecord,
    SensesRecord,
)
from colleague.contract_taskresult_io import task_result_from_dict, task_result_to_dict

if TYPE_CHECKING:
    from colleague.affectedtests import AffectedTestsReport
    from colleague.importcheck import ImportCheckReport
    from colleague.testintegrity import TestIntegrityReport

__all__ = [
    "OK",
    "ERROR",
    "INCOMPLETE",
    "DECISION_ALLOW",
    "DECISION_DENY",
    "DECISION_REWRITE",
    "DECISION_OBSERVE",
    "NO_RESULT_PRODUCED",
    "FINISH_DELIBERATE",
    "FINISH_TRUNCATED",
    "FINISH_STOPPED",
    "FINISH_TIMEOUT",
    "FINISH_EMPTY",
    "FINISH_STATES",
    "FinishRecord",
    "HookFiring",
    "Usage",
    "WorkStats",
    "SubResult",
    "CapacityDecision",
    "CoherenceReport",
    "LintReport",
    "DeepthinkCall",
    "ContextPacket",
    "SENSES_CHAT_KINDS",
    "SENSES_LOOP_POINT_PREFIX",
    "SensesRecord",
    "SensesDirectRecord",
    "IncompletionRecord",
    "ChainView",
    "SensesBlock",
    "Step",
    "Task",
    "TaskResult",
    "ConfigEvent",
    "ConfigEventRecord",
    "map_configlifecycle_events",
    "config_digest_for",
    "prompt_digest_for",
]

# TaskResult.status values.
OK = "ok"
ERROR = "error"
INCOMPLETE = "incomplete"

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
    reasoning_repo_path: Optional[str] = None
    """The repo the reasoning sidecar (:mod:`colleague.reasoninglog`) is
    appended at, distinct from ``repo_path`` (the work CWD) — the
    ``flight_repo_path`` pattern carried one hop further (effort-v4 t6, h20):
    set by the spawn plumbing on a subagent child so the child's sidecar lands
    beside the parent artifact in the OPERATOR repo's ``.colleague/`` and
    survives child-worktree removal. ``None`` (the default) means "append at
    ``flight_repo_path or repo_path``". Omitted from ``to_dict`` when ``None``
    so an untagged task serializes byte-identically to today."""
    reasoning_parent_id: Optional[str] = None
    """The PARENT task id a subagent child's sidecar is tagged under: when set,
    the sidecar filename is ``<reasoning_parent_id>.<id>.reasoning.jsonl`` (the
    t3 module's ``child_id`` tag), so an observer can group a subagent tree's
    sidecars beside the parent's own. ``None`` (the default, and every
    top-level run) keeps the untagged ``<id>.reasoning.jsonl``. Omitted from
    ``to_dict`` when ``None``."""

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
        # The reasoning-sidecar pair gets the same treatment (effort-v4 t6): an
        # untagged task serializes byte-identically to today.
        if self.reasoning_repo_path is not None:
            data["reasoning_repo_path"] = self.reasoning_repo_path
        if self.reasoning_parent_id is not None:
            data["reasoning_parent_id"] = self.reasoning_parent_id
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
            reasoning_repo_path=(
                str(data["reasoning_repo_path"])
                if data.get("reasoning_repo_path") is not None
                else None
            ),
            reasoning_parent_id=(
                str(data["reasoning_parent_id"])
                if data.get("reasoning_parent_id") is not None
                else None
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
    hires: list[dict[str, Any]] = field(default_factory=list)
    """The run's hire roster + assignments block (plan
    delegation-follow-ups-a7-p3-hire, task t13, covers c38/h22), in roster
    order: each entry is one Hire's ``to_dict`` — the authored prompt TEXT
    rides here (the ledger carries only its digest) — plus an ``assignments``
    list of ``{task_id, status, changed_files}`` per finished
    ``assign_to_colleague`` child. Built by
    :func:`colleague.hire_assign.hires_block`. Like ``sub_results``, the
    serialized key is OMITTED (not an empty list) when empty, so a hire-less
    run serializes byte-identically to today."""
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
    warnings: list[dict[str, str]] = field(default_factory=list)
    """Structured stale-pin refresh warnings folded into the run artifact (t11).
    Each entry is a plain dict with keys ``role``, ``stale_id``, ``source``,
    ``refreshed_id``, ``point`` — mirroring
    :class:`~colleague.lobes.ModelRefreshWarning.to_dict``. Always serialized
    (like ``steps``), so a background/one-shot artifact is greppable with no TTY
    (h21). An artifact written before this field still loads with
    ``warnings == []`` (back-compat)."""
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
    importcheck_report: Optional["ImportCheckReport"] = None
    """The importability-check pre-finish gate's report (#482/#480 t6), or
    ``None`` when the gate did not run at all (``COLLEAGUE_IMPORT_CHECK=0``, no
    changed ``.py`` files, or an aborted run — ``status="skipped"`` degrades to
    ``None`` here too). Unlike ``test_integrity_report``/``affected_tests_report``
    (which stay ``None`` on a clean PASS with no findings), this field is set on
    BOTH ``"passed"`` and ``"failed"`` so a clean import-check run is still
    visible on the artifact — mirroring ``lint_report``/``coherence_report``.
    Runs on EVERY exit outcome (finished, budget-exhausted, stalled, ...), never
    only ``_EXIT_FINISHED`` — the h4 fix (row 67 shipped a non-importing branch
    on a budget-exhausted outcome that told no one). Like the sibling gate
    reports, the serialized key is OMITTED (not null) when ``None``, so a
    pre-t6 artifact stays byte-identical."""
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
    lesson landed in the store.

    Retrieval-precision instrumentation (post-#387, spec c9/h8/h24) adds four
    more keys on an armed, scoreable run — ``class_key``, ``precision_rule``,
    ``class_relevant_recalled``, ``class_relevant_in_top_k``, plus
    ``class_relevant_rank`` only when something matched: did the
    class-relevant lesson actually surface in the recalled top-k? They are
    computed from the artifact-recorded recall results by the PRE-DECLARED,
    deterministic rule ``memory.CLASS_KEY_RULE`` (documented in
    ``docs/features/memory.md``) — never an LLM judgment at record time,
    never a post-hoc call. An unscoreable work item (empty assignment text)
    adds none of them.

    Recall thresholding + supersedes hygiene (plan t6, spec c10/h9) adds
    ``recall_excluded`` — a list of ``{"id", "reason"}`` for every recalled
    record ``memory.filter_for_injection`` dropped from the INJECTED block
    (below-threshold on eidetic's returned ``score``/``signal`` fields, or
    superseded by a sibling hit's ``supersedes`` field) — present ONLY when
    at least one record was excluded, so a run that excludes nothing (or has
    hygiene env-disabled) serializes byte-identically. The precision fields
    above are scored over the full recalled set BEFORE this filtering, so an
    excluded record still counts toward them — see ``memory.py``'s recall
    thresholding module comment for the composition rule.

    Omit-when-None, so a memory-less run serializes byte-identically."""
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
    evaluation_ledger: Optional[dict[str, Any]] = None
    """The append-only evaluation ledger for the thought-action-evaluation mode
    (#397, t11), or ``None`` when the ledger was not populated. Shape:
    ``{"version": int, "entries": [...]}`` where each entry is a
    :class:`colleague.ledger.LedgerEntry` dict (``kind``, ``thought_id``,
    ``action_id``, ``detail``, ``seat``, ``model``, ``seq``). Like
    ``media``/``lint_report``, the serialized key is OMITTED (not null) when
    ``None``, so a work item with no ledger serializes byte-identically to
    today's artifact."""
    agents: Optional[dict[str, Any]] = None
    """The model-bound-agents block for this work item (#411, plan t13; spec
    c17/h24), or ``None`` when the ``agents`` increment never armed. A plain
    dict of shape ``{"version", "invocations", "messages", "fallbacks",
    "ledger_path", "ledger_digest"}`` built by
    :func:`colleague.agents.artifact_block.build_agents_block` — the
    invocation records (``InvocationRecord.to_dict()``), the agent-to-agent
    messages (``AgentMessage.to_dict()``), the recorded role fallbacks
    (``{"purpose", "from_role", "resolved_model"}``) and the task-ledger
    pointer + state digest. Kept SMALL: the ledger is the authority, this is
    the read-side mirror the ROI/feedback readers consume from the artifact.
    An ARMED run always carries the key (the engine-level fold supplies the
    empty-lists floor when the loop authored nothing) with the SAME shape on
    every backend (all-engines rule). Like ``evaluation_ledger``/``senses``,
    the serialized key is OMITTED (not null) when ``None``, so an unarmed run
    serializes byte-identically to today's artifact."""
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
    effort: Optional[dict[str, str]] = None
    """Top-level ``{seat: rung}`` thinking-effort block (effort-v4 t5, c6/h5):
    every seat BUILT during the run whose rung resolved — ``"main"`` (the
    acting seat, matching its finish record's seat name), ``"senses"`` when
    the senses lane ran, each delegated child under its role name (a
    scout/purpose child included), and ``"distill"`` when the rung-2 pass
    launched. A seat that resolved ``"off"`` records ``"off"``; a
    never-resolved seat (``None`` = send nothing) is simply absent. Populated
    by the loop from the ONE resolved value the wire sends
    (:func:`colleague.effort.effort_of` / the child seat's built
    ``reasoning_effort_seat``) — never recomputed per consumer. Like
    ``incompletion``, the serialized key is OMITTED (not null) when ``None``,
    so a run predating this field serializes byte-identically."""

    sampling: Optional[list[dict[str, Any]]] = None
    """Top-level sampling block (#479 t9): one entry per seat whose sampling
    profile RESOLVED, mirroring :mod:`colleague.effortrecord`'s presence rule -
    a seat that resolved records, a seat that did not is simply ABSENT, never
    an invented row. The serialized key is OMITTED (not null) when ``None``, so
    a run whose model matched no table row serializes byte-identically to a
    pre-#479 artifact, and absence reads as "nothing was sent" rather than "we
    forgot to record it".

    Each entry carries ``{seat, half, row, wire}``. ``row`` is what the model
    CARD says; ``wire`` is what actually went out - the row minus every key
    already at the server default
    (:data:`colleague.samplingwire.SERVER_DEFAULT_SAMPLING`). They are labelled
    apart deliberately: showing only the row would tell a reader that
    ``min_p``/``repetition_penalty`` reached the server when they did not - the
    same misstatement this arc had to fix in ``config show`` (deviation d4)."""
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
    prompt_digest: Optional[str] = None
    """The sha256 digest of the system prompt this work item ACTUALLY ran with
    (plan task t7, covers c49/h36) — computed by
    :func:`prompt_digest_for` over the composed string each backend hands
    ``loop.run`` as ``system_prompt`` (so an operator overlay under
    ``.colleague/agents/<role>.md`` is inside the digest, never a
    re-derivation of what the prompt *should* have been). This is what lets a
    live-testing row cite the prompt arm read back off the artifact instead of
    trusting the overlay file the operator believes was in place. ``None``
    when the backend composed no system prompt at all. Like
    ``config_digest``/``role``, the serialized key is OMITTED (not null) when
    ``None``, so a prompt-less run serializes byte-identically to the
    pre-``prompt_digest`` artifact shape."""
    offered_tools: Optional[list[str]] = None
    """The depth-0 OFFERED tool names this work item ACTUALLY ran with (plan
    delegation-follow-ups-a7-p3-hire, task t2, covers c34/h18) — the curated
    schema list handed to the backend, in schema order, so a live-testing row
    reads the acting seat's surface off the artifact instead of trusting the
    env knobs the operator believes were set (neither
    ``COLLEAGUE_ACTING_DROP_TOOLS`` nor the add knob was persisted anywhere
    before this field). ``None`` when no surface was curated. Like
    ``prompt_digest``, the serialized key is OMITTED (not null) when ``None``,
    so a pre-field artifact loads and serializes byte-identically."""
    task_text: Optional[str] = None
    """The task's own instruction text, verbatim, as it actually ran (#481) —
    ``prompt_digest`` proves WHICH prompt arm ran; this is WHAT brief the run
    itself was given, so a measurement rerun never has to trust what the
    operator remembers typing. Capped at
    :data:`colleague.tasktext.MAX_CHARS` (16 KiB) via
    :func:`colleague.tasktext.prepare_task_text` — an over-cap brief is
    truncated with a literal, discoverable marker, never a silent cut.
    Recording is ON by default (decision c15); ``COLLEAGUE_RECORD_TASK_TEXT=0``
    (see :func:`colleague.tasktext.recording_enabled`) leaves this ``None``.
    Like ``prompt_digest``, the serialized key is OMITTED (not null) when
    ``None``, so a disabled/pre-field run serializes byte-identically."""
    tip_sha: Optional[str] = None
    """The ``colleague/<id>`` work branch's tip commit SHA after a successful
    handoff (plan task t5, covers c5), or ``None`` when the handoff produced no
    commit (nothing to hand off, gating off, or the handoff didn't run — e.g. a
    read-only role). Populated by the CLI handoff
    (:func:`colleague.cli._commands.work._handoff_result`) from
    :attr:`colleague.handoff.HandoffResult.tip_sha`. Like
    ``config_digest``/``continued_from``, the serialized key is OMITTED (not
    null) when ``None``, so a commit-less run serializes byte-identically to
    the pre-``tip_sha`` artifact shape."""

    def to_dict(self) -> dict[str, Any]:
        return task_result_to_dict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskResult":
        return task_result_from_dict(cls, data)


# ── lazy import helper (avoids circular import at module level) ─────────


def _get_test_integrity_report_class():
    """Return the TestIntegrityReport class via a lazy import.

    ``colleague.testintegrity`` imports ``colleague.contract`` (for the
    type annotation on ``TaskResult.test_integrity_report``), so we cannot
    import it at the top of this module.  This helper defers the import to
    the point where it is actually needed (``from_dict``, called from
    :mod:`colleague.contract_taskresult_io`).
    """
    from colleague.testintegrity import TestIntegrityReport

    return TestIntegrityReport


def _get_affected_tests_report_class():
    """Return the AffectedTestsReport class via a lazy import.

    ``colleague.affectedtests`` imports ``colleague.contract`` (for the
    type annotation on ``TaskResult.affected_tests_report``), so we cannot
    import it at the top of this module.  This helper defers the import to
    the point where it is actually needed (``from_dict``, called from
    :mod:`colleague.contract_taskresult_io`).
    """
    from colleague.affectedtests import AffectedTestsReport

    return AffectedTestsReport


def _get_import_check_report_class():
    """Return the ImportCheckReport class via a lazy import.

    ``colleague.importcheck`` does not import ``colleague.contract`` today, but
    the lazy-getter pattern is kept identical to its two siblings above for one
    reason: consistency for whoever reads/edits this trio next, and to leave
    the door open if importcheck ever needs a contract type later without a
    surprise cycle.
    """
    from colleague.importcheck import ImportCheckReport

    return ImportCheckReport
