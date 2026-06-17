"""The bounded agentic tool-loop (R3).

The loop is engine-agnostic: it is handed a ``complete`` callable that performs
*one* model turn (given the running message list, return the assistant's reply
and any tool calls) and drives it in a loop — executing each requested tool
against the repo via :class:`~colleague.tools.ToolExecutor`, feeding results
back, until the model calls ``finish`` (or stops requesting tools) or the
``max_steps`` budget is reached.

Termination is guaranteed (honesty condition h3): every path out of the loop is
either a model-signalled finish, an empty tool-call turn, or the step budget.
The mock engine supplies a scripted ``complete``; the vLLM engine supplies one
that POSTs to an OpenAI-compatible endpoint. The loop never knows the difference.

Hook lifecycle (R4). The loop fires repo-shipped hooks at four lifecycle events
— ``task_start`` (once, before the loop), ``pre_tool`` (before each tool
executes), ``post_tool`` (after a tool executes), and ``finish`` (once, on any
loop exit). The config is loaded by default from ``task.repo_path`` via
:func:`colleague.hooks.load_hooks`, so *every* engine inherits the lifecycle
for free — engines call :func:`run` unchanged (the all-engines rule). With no
hooks config nothing fires and behavior is byte-identical to a hook-free loop.

Only ``pre_tool`` is control-bearing: the first decisive decision wins — ``deny``
skips the tool (the reason is fed back to the model as the tool result) and
``rewrite`` swaps the call's arguments before execution. ``task_start`` /
``post_tool`` / ``finish`` are observe-only this increment (they run side-effects
and are recorded, but never alter control flow). Every firing is appended to
``TaskResult.hook_firings`` in order. Termination is unaffected: hooks add no new
exit path and cannot extend the step budget.
"""

from __future__ import annotations

import datetime
import json
import sys
import time
from collections import Counter
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any, Callable

from colleague import autosplit as _autosplit
from colleague import escalation as _escalation
from colleague import fillline as _fillline
from colleague import flight as flightmod
from colleague import lint as _lint
from colleague import testintegrity as _testintegrity
from colleague.capacity import assess_capacity
from colleague.config import MAX_SUBAGENT_FANOUT
from colleague.context import classify_degradable, window_messages
from colleague.contract import (
    DECISION_DENY,
    DECISION_REWRITE,
    ERROR,
    INCOMPLETE,
    NO_RESULT_PRODUCED,
    OK,
    CapacityDecision,
    HookFiring,
    Step,
    Task,
    TaskResult,
)
from colleague.hooks import HookConfig, HookDecision, hook_approval_verdict, load_hooks, run_hook
from colleague.neighbours import NeighbourManager
from colleague.policy import Policy, load_policy
from colleague.telemetry import Telemetry, load_telemetry
from colleague.tools import ToolError, ToolExecutor, ToolOutcome
from colleague.tui.from_work import progress_target as _progress_target

_DEFAULT_SYSTEM = (
    "You are a coding agent working inside a repository. Use the provided tools "
    "to inspect and edit files, then call finish with a short summary. Make the "
    "smallest change that satisfies the task. "
    "To change part of an existing file, prefer the edit_file tool (an exact-string "
    "replace that only needs the changed text) over write_file; reach for write_file "
    "only to create a new file or do a wholesale rewrite. Rewriting a large file with "
    "write_file is slow and may time out, so edit_file is the right tool for a scoped edit."
    "\n\n"
    "Destination (optional). When a task is vague or new enough to benefit from a "
    "clear goal-frame, you MAY use the devague tool to open or update one — this is "
    "advisory and entirely your own judgement. A clear, well-scoped task needs no "
    "destination; never set one just to set one. Convergence is advisory: you can "
    "call converge or status to see gaps, but you CANNOT confirm or reject your own "
    "claims (those are user-only moves the tool does not offer). Authoritative "
    "convergence belongs to the operator, not to you. When the work reaches the "
    "goal, declare arrival by passing destination (the frame slug) and announcement "
    "(the goal-frame's arrival announcement) to the finish tool."
    "\n\n"
    "Subagents (optional). When a task naturally splits into independent, well-scoped "
    "pieces, you MAY delegate them to nested child work items. Use the subagent tool to hand "
    "ONE scoped piece to a child (optionally on a different engine/model — for example a "
    "mechanical chunk a cheaper model can do). Use the subagents tool to fan out a BATCH "
    "of independent pieces that run in PARALLEL, each isolated in its own git worktree, "
    "with a final merge child that integrates their branches and surfaces any conflict "
    "(never force-merging). A good fit: a task that asks for two or more changes in "
    "separate files that do not depend on each other — fan them out with subagents. Each "
    "child runs the same bounded tool-loop (no git handoff); its result summary returns "
    "to you and any files it writes are merged into your changed set. This is advisory and "
    "entirely your own judgement: a simple, single-file task needs none, so never delegate "
    "just to delegate. Delegation is bounded (a capped depth and per-work-item fan-out), so it "
    "always terminates."
    "\n\n"
    "Culture tools (optional). Two operator-installed AgentCulture CLIs are reachable "
    "through the culture tool, with your agent identity auto-injected and the working "
    "directory pinned at the repo root. Use cli='agtag' to READ the mesh issue tracker "
    "(e.g. fetch issues from a sibling repo) and cli='devex' to inspect a repo's "
    "agent-first surface (e.g. explain/overview/learn). Reach for them only when the task "
    "explicitly calls for the mesh or another repo's surface; a MUTATING action (e.g. "
    "posting an issue) needs the operator's explicit instruction, never your own "
    "initiative. Only agtag and devex are permitted, and identity is injected for you, so "
    "you never pass it yourself. This is advisory and entirely your own judgement: a "
    "self-contained in-repo task needs neither."
    "\n\n"
    "Test integrity (advisory). When you write code test-first, derive the test's "
    "fixtures and assertions from the REAL external API shape, not from your own "
    "implementation — a test that merely mirrors the code's own assumption passes even "
    "when both are wrong. You MAY call check_test_integrity to self-check for that "
    "mirror signature. (This is only a hint: a code-locked harness gate runs the same "
    "check after you finish regardless, so ignoring this line changes nothing.)"
)


# Bounded reactive degradation: how many times the loop may shrink the budget and
# retry a single ``complete`` call after a *context-overflow* error before giving
# up and re-raising. Bounded AND each retry strictly shrinks the budget, so the
# retry inside one turn always terminates (the outer ``max_steps`` loop is
# unchanged). 0.6 is the shrink factor applied per retry.
_MAX_OVERFLOW_RETRIES = 3
_OVERFLOW_SHRINK_FACTOR = 0.6
# A request timeout (vs an instant context-overflow 400) costs a full
# ``COLLEAGUE_TIMEOUT`` window per attempt, so it gets its own, lower retry cap:
# one shrink-and-retry — where almost all the value is (a bloated context makes
# each completion slow, and one 0.6× shrink already sheds ~40% of the tokens),
# not the overflow cap. A genuinely-unreachable server therefore wastes at most
# this many bounded retries before the partial is preserved (#154).
_MAX_TIMEOUT_RETRIES = 1

# How a work item's turn loop ended (return values of ``_work_loop``). The model may
# end a turn with no tool call instead of calling ``finish`` — usually trailing off
# mid-task — so the loop distinguishes a clean finish from that stop, and from a
# step-budget exhaustion, and ``run`` maps each to the right TaskResult flag.
_EXIT_FINISHED = "finished"  # the finish tool was called -> authoritative result
_EXIT_STOPPED = "stopped"  # ended on a no-tool-call turn without ever finishing
_EXIT_BUDGET = "budget"  # ran out of model turns (max_steps) without finishing
_EXIT_PILOT_STOP = "pilot_stop"  # a pilot wrote a cooperative `stop` to the flight control file

# Recovery for the trail-off (colleague#142): when the model ends a turn with no
# tool call and has not called ``finish``, nudge it ONCE to finish before giving up.
# Bounded so the loop still terminates; one reminder is enough for a capable model
# that merely forgot the closing ``finish`` call.
_MAX_FINISH_NUDGES = 1
_FINISH_NUDGE = (
    "You ended your turn without calling the `finish` tool and without requesting "
    "another tool. If your work is complete, call `finish` now with your result as "
    "the summary. Otherwise, continue by calling a tool — do not reply with prose alone."
)
# Forced final synthesis (colleague#191): injected once when the loop exhausts its
# step budget (or stops) after reading context but never answering, to turn a
# wasted full-token run into a usable partial.
_SYNTHESIS_PROMPT = (
    "You are out of steps. Stop using tools and answer the original request NOW, "
    "directly, from what you have already read. Do not request any more tools — write "
    "the most complete, useful answer you can from the context gathered so far."
)
# Empty-finish synthesis (colleague#202): the model called `finish` but gave no
# usable summary — for a read-only verb (review/explore) the summary IS the
# deliverable, so a blank finish is a silent no-op (worse than an error: status
# reads ok). Force ONE no-tools turn to produce the answer from what was read,
# rather than falling back to the last planning line.
_EMPTY_FINISH_PROMPT = (
    "You called `finish` without a summary, but the summary IS your deliverable. "
    "Write your complete result NOW, directly, from what you have already read — for "
    "a review, the concrete findings and verdict you gathered. Do not request any "
    "more tools."
)

# Pre-completion phase notices (colleague#206) — fired through the progress sink
# right BEFORE a model completion so a long single turn (above all the final
# no-tools synthesis turn) is visibly "working, not stalled" on a slow backend. A
# single completion emits no per-step progress, so for ~minutes a slow but healthy
# run is indistinguishable from a hang. Each notice is encoded as a progress event
# with an EMPTY tool name — a reserved sentinel, since a real tool always has a
# name — so a sink renders it as a standalone phase line, never a `step N:` line.
# Observability only; runtime-owned, so every backend inherits it (all-engines rule).
_PHASE_THINKING = "thinking… (waiting on the model — this can be slow on a large model)"
_PHASE_SYNTHESIZING = (
    "synthesizing the final answer from what was read — this can take a while on a "
    "slow backend; it is working, not stalled…"
)
_PHASE_COMPACTING = "compacting the conversation to free context — this can take a moment…"


@dataclass
class ToolCall:
    """A single tool invocation requested by the model."""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class ModelResponse:
    """One model turn: free text, reasoning, any tool calls, and token usage.

    ``reasoning`` is the model's chain-of-thought when the server returns it as a
    separate field (OpenAI-compatible ``message.reasoning`` / ``reasoning_content``),
    distinct from ``content`` (the final answer). It is generated but never saved
    to a file, so the loop measures it as the "thought" portion of a work item
    (char/byte lengths in :class:`~colleague.contract.WorkStats`). Empty for
    servers/models that do not emit a reasoning field.
    """

    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning: str = ""


# A ``complete`` performs one model turn given the running message list.
CompleteFn = Callable[[list[dict[str, Any]]], ModelResponse]

# A progress sink: (step_index, tool, target, ok) -> None. Default ``None`` in the
# loop is a strict no-op; the CLI wires one that writes a line per step to stderr
# (#38). Lives in the loop, fired per tool call, so every backend inherits it
# identically (the all-engines rule), exactly like hooks and telemetry.
ProgressFn = Callable[[int, str, str, bool], None]


class WorkAborted(Exception):
    """An engine raised mid-loop; carries the partial result (#37).

    The bounded loop catches the engine's exception, finalizes the partial
    :class:`~colleague.contract.TaskResult` (``status=error`` plus the
    ``steps`` / ``usage`` / ``changed_files`` accumulated so far) and raises this
    so the shared work path can persist that partial artifact + non-empty trace
    before surfacing the error to the operator. The original exception is the
    ``__cause__``.
    """

    def __init__(self, result: TaskResult) -> None:
        super().__init__(result.error or "drive aborted")
        self.result = result


def _arguments_json(arguments: Any) -> str:
    """OpenAI wire format wants function.arguments as a JSON *string*.

    The loop carries arguments as dicts for execution; serialize only on the way
    back into the message list so strict OpenAI-compatible servers accept replayed
    turns. A value that is already a string is passed through unchanged.
    """
    if isinstance(arguments, str):
        return arguments
    return json.dumps(arguments, ensure_ascii=False)


def _assistant_message(resp: ModelResponse) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": resp.content,
        "tool_calls": [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": _arguments_json(tc.arguments)},
            }
            for tc in resp.tool_calls
        ],
    }


def _tool_message(call_id: str, content: str) -> dict[str, Any]:
    return {"role": "tool", "tool_call_id": call_id, "content": content}


def _fire_hooks(
    hooks: HookConfig,
    result: TaskResult,
    *,
    event: str,
    task: Task,
    tool: str | None = None,
    arguments: dict[str, Any] | None = None,
    policy: Policy | None = None,
) -> HookDecision | None:
    """Run every matching hook for *event*, record a firing per hook, in order.

    Returns the first control-bearing :class:`HookDecision` (a ``deny`` or
    ``rewrite``) seen, or ``None``. Only ``pre_tool`` callers act on the return;
    for the observe-only events (``task_start`` / ``post_tool`` / ``finish``) the
    caller ignores it. ``allow`` / ``observe`` decisions are recorded but never
    control-bearing, so scanning continues past them.

    A firing is appended for *every* hook that runs — including the allow/observe
    ones leading up to a decisive one — so the run report sees the full sequence.

    When *policy* is given and its ``hooks`` section is present, each entry's
    command is checked via :func:`~colleague.hooks.hook_approval_verdict` before
    being run.  An unapproved entry is recorded as a ``HookFiring(decision=
    "skipped")`` and skipped — it does NOT set the decisive deny/rewrite and does
    NOT block the tool for ``pre_tool``.  With no ``hooks`` section (the default)
    every entry fires exactly as before (strict no-op).
    """
    entries = hooks.hooks_for(event, tool=tool)
    if not entries:
        return None

    payload = {
        "event": event,
        "tool": tool,
        "arguments": arguments,
        "task_id": task.id,
        "repo_path": task.repo_path,
    }

    decisive = None
    for entry in entries:
        # --- Content-approval gate (r1) ---
        # Check the hook's referenced repo files against the policy before running.
        # A skip is NON-control-bearing: it does NOT set decisive and does NOT
        # block the tool for pre_tool.  With no hooks section this is a strict no-op.
        if policy is not None:
            approval = hook_approval_verdict(entry.command, policy, task.repo_path)
            if not approval.allowed:
                result.hook_firings.append(
                    HookFiring(
                        event=event,
                        tool=tool,
                        command=entry.command,
                        decision="skipped",
                        exit_code=None,
                        reason=approval.reason,
                    )
                )
                continue

        # A hook must never abort the work item. run_hook already maps timeouts /
        # launch failures to a deny; this net catches any other unexpected error
        # and records it as a fail-closed deny firing rather than propagating.
        try:
            decision = run_hook(entry, payload, cwd=task.repo_path)
        # BLE001 justified: fail-closed — any hook error becomes a deny (see the
        # note above), never propagated, so a crashing hook cannot abort the work item.
        except Exception as exc:  # noqa: BLE001
            decision = HookDecision(
                decision=DECISION_DENY, reason=f"hook error: {exc}", exit_code=None
            )
        result.hook_firings.append(
            HookFiring(
                event=event,
                tool=tool,
                command=entry.command,
                decision=decision.decision,
                exit_code=decision.exit_code,
                reason=decision.reason,
            )
        )
        # The first deny/rewrite wins; allow/observe are non-decisive — keep going.
        if decisive is None and decision.decision in (DECISION_DENY, DECISION_REWRITE):
            decisive = decision
            # A decisive pre_tool verdict short-circuits the rest of the chain.
            if event == "pre_tool":
                break
    return decisive


@dataclass(frozen=True)
class _Work:
    """The fixed collaborators threaded through one work item's tool-loop helpers.

    Grouped so the per-call helpers take one ``ctx`` instead of a long parameter
    list. ``result`` and ``messages`` are mutated *through* these references
    during the loop — ``frozen`` fixes the bindings, not the objects they hold.
    """

    executor: ToolExecutor
    hooks: HookConfig
    telemetry: Telemetry
    task: Task
    result: TaskResult
    messages: list[dict[str, Any]]
    policy: Policy = field(default_factory=Policy)
    progress: ProgressFn | None = None
    # Proactive context-window management (t4): when ``context_budget`` is a
    # positive int the running history is trimmed to it (via ``count_tokens``,
    # defaulting to the char estimate in ``window_messages``) before each turn,
    # and a context-overflow from ``complete`` triggers a bounded shrink-and-retry.
    # ``None`` (the default) is a strict no-op — no windowing, no reactive retry.
    context_budget: int | None = None
    count_tokens: Callable[[list[dict[str, Any]]], int] | None = None
    # Reactive auto-split (#151): when armed (a positive ``context_budget`` AND a
    # positive ``autosplit_target``), an EXHAUSTED context-overflow injects ONE
    # split recommendation — pointing the model at the existing ``subagents`` tool
    # — *before* the error would propagate to run()'s abort+escalate path.
    # ``None``/0 leaves the feature dormant (a strict no-op). Backend-judged: the
    # loop only recommends; the model decides whether to split.
    autosplit_target: int | None = None
    # Single-element mutable cell: holds ``True`` once the reactive recommendation
    # has been injected, so it is offered at most ONCE per work item (the model then
    # gets bounded extra turns under ``max_steps``). Mutable so the frozen ``_Work``
    # can flip it through the binding (same pattern as ``_last_substantive``).
    _split_recommended: list[bool] = field(default_factory=list)
    # Single-element mutable cell carrying the floored budget from an EXHAUSTED
    # degradation give-up into the *next* turn (#154). When the shrink-and-retry
    # gives up it re-raises, and ``_work_loop`` may inject the auto-split/INCOMPLETE
    # recommendation and grant one bounded extra turn — that turn must run against
    # the SAME small window the give-up reached, not the full budget, or it would
    # just overflow / time out again before the model can act. Consumed once (read
    # then cleared) by the next ``_complete_with_degradation`` call, so only the
    # recommendation turn is throttled; everything after returns to the full budget.
    # Empty = no carry (window to the full budget, the default). Mutable for the
    # same reason as ``_split_recommended``.
    _degraded_budget: list[int] = field(default_factory=list)
    # Last non-empty ``resp.content`` seen across ALL turns (including turns that
    # also made tool calls).  Updated in ``_work_loop`` unconditionally whenever
    # ``resp.content`` is non-empty — this is the t2 "last-substantive-content"
    # candidate used as the no-finish summary fallback in ``run``.  Stored as a
    # mutable list[str] (single element) so the frozen ``_Work`` dataclass can
    # still update it through the binding.
    _last_substantive: list[str] = field(default_factory=list)
    # auto-compact-on-finish (t3): the model-authored summary produced by the last
    # fill-line compaction, kept on a dedicated cell so a later stall cannot
    # overwrite it (unlike ``_last_substantive``); used as the FALLBACK clean summary
    # at a stop/budget exit when forced synthesis yields nothing — never preferred
    # over a fresh synthesis, which reflects any post-compaction work (Qodo PR #198).
    # Empty (a strict no-op) for a run that never compacted.
    _compacted_summary: list[str] = field(default_factory=list)
    # Proactive fill-line decision (#156). ``capacity_threshold`` is the fraction of
    # ``context_budget`` at which the runtime offers the one capacity decision; armed
    # only when degradation is active and the threshold is in ``(0, 1]``.
    # ``_fillline_offered`` / ``_fillline_resolved`` are single-element mutable cells
    # (the ``_split_recommended`` pattern) so the decision is offered + recorded at
    # most once per work item through the frozen binding.
    capacity_threshold: float | None = None
    _fillline_offered: list[bool] = field(default_factory=list)
    _fillline_resolved: list[bool] = field(default_factory=list)
    # The prompt-token count that tripped the fill line — captured when the decision
    # is OFFERED so the recorded reason matches the number named in the prompt (not
    # the slightly different count of the declaring turn).
    _fillline_used: list[int] = field(default_factory=list)
    # Mapping fan-out advisory (#188): ``mapping_fanout_files`` is the files-read count
    # at which the runtime injects ONE advisory recommendation to fan a wide read-only
    # survey out across folders via the ``subagents`` tool (instead of grinding serially
    # through the step budget). ``None``/<= 0 leaves it dormant — a strict no-op.
    # ``_mapping_fanout_offered`` is a single-element mutable cell (the
    # ``_fillline_offered`` pattern) so the advisory fires at most once per work item.
    mapping_fanout_files: int | None = None
    _mapping_fanout_offered: list[bool] = field(default_factory=list)
    # Plan-mode auto-trigger (#t8): the instruction-token threshold at/above which
    # the runtime injects ONE advisory recommendation to enter plan mode. ``None``/
    # <= 0 is dormant. ``_plan_offered`` is the single-element fired-once cell (the
    # ``_mapping_fanout_offered`` pattern) so the advisory fires at most once.
    plan_offer_tokens: int | None = None
    _plan_offered: list[bool] = field(default_factory=list)
    # continue-working: max consecutive no-tool-call nudges before the loop gives up
    # and stops (replaces the hardcoded ``_MAX_FINISH_NUDGES``). Forwarded by every
    # backend from ``config.max_continue_nudges`` (all-engines rule); falls back to
    # ``_MAX_FINISH_NUDGES`` when a ContextControls omits it (back-compat / no-op).
    max_continue_nudges: int = _MAX_FINISH_NUDGES
    # Flight-control plane (the piloting feature): an armed ``FlightSession`` when the
    # task is a watchable flight (``task.watch``), else ``None`` — a strict no-op.
    # When set, the loop appends a live feed record per turn and reads the per-flight
    # control file at each turn boundary (cooperative ``stop`` + ``guidance``
    # injection). Runtime-owned, so every backend inherits it (the all-engines rule).
    flight: "flightmod.FlightSession | None" = None
    # Lint pre-finish gate (#200): ``lint_enabled`` arms the gate (run the repo's
    # configured linters on the changed files + auto-fix before handoff);
    # ``lint_fix_retries`` caps the bounded model fix-turn for residual violations
    # (0 = deterministic fixers only). Both default OFF so a direct ``run`` caller
    # (no ContextControls) is byte-identical; the backends forward ``config.lint`` /
    # ``config.lint_fix_retries`` (all-engines rule).
    lint_enabled: bool = False
    lint_fix_retries: int = 0
    # Test-integrity gate (#203): when ``testintegrity_enabled`` the runtime runs the
    # mirror-detection heuristic on the work item's changed files after the loop and
    # records any findings on ``result.test_integrity_report``. Defaults ON — unlike
    # lint, a no-finding run is byte-identical via omit-when-None (the report stays
    # None), so the gate fires for every backend (the all-engines rule) without a
    # behavior change for findings-free runs. Forwarded from ``_context.testintegrity``.
    testintegrity_enabled: bool = True
    # Caps the bounded model re-examine turn for a flagged symbol (0 = detect-and-record
    # only). Forwarded from ``_context.testintegrity_fix_retries`` (all-engines rule).
    testintegrity_fix_retries: int = 0
    # The DIFFERENT model id for the diverse reviewer subagent; "" degrades to
    # record-only. Forwarded from ``_context.testintegrity_reviewer_model``.
    testintegrity_reviewer_model: str = ""


def _apply_finish(result: TaskResult, outcome: ToolOutcome) -> None:
    """Record a finish on ``result`` — summary, then optional destination/announcement.

    Same order and truthiness guards as the inline finish path it replaced: the
    destination/announcement are set only when the engine declared them, so a
    finish without a goal-frame leaves those keys off the artifact (the e2e shape
    test pins this).
    """
    result.summary = outcome.finish_summary or result.summary
    if outcome.destination:
        result.destination = outcome.destination
    if outcome.announcement:
        result.announcement = outcome.announcement


def _finalize_stats(
    result: TaskResult,
    task: Task,
    executor: ToolExecutor,
    *,
    started_at: str,
    duration_seconds: float,
) -> None:
    """Fill the work item-level :class:`WorkStats` fields known only at loop exit.

    The per-turn fields (``model_turns`` and the generated reasoning/answer sizes)
    are accumulated in :func:`_work_loop`; this fills the rest from the finished
    result + executor. Called on EVERY exit path (model finish / empty turn /
    budget / mid-loop abort) so a partial drive still gets populated stats.
    """
    stats = result.stats
    stats.request = task.instruction
    stats.started_at = started_at
    stats.duration_seconds = duration_seconds
    stats.step_count = len(result.steps)
    stats.tool_counts = dict(Counter(step.tool for step in result.steps))
    stats.files_changed = len(result.changed_files)
    stats.bytes_written = executor.bytes_written


def _emit_progress(ctx: _Work, step_index: int, tool: str, arguments: Any, ok: bool) -> None:
    """Fire the per-step progress sink, if one is wired (#38). No-op otherwise.

    A progress sink is observability, never control: a raising sink must never
    abort the work item, so its failure is suppressed (the same fail-safe as hooks
    and neighbour clones).
    """
    if ctx.progress is None:
        return
    with suppress(Exception):
        ctx.progress(step_index, tool, _progress_target(arguments), ok)


def _emit_phase(ctx: _Work, detail: str) -> None:
    """Announce, through the progress sink, that a model completion is in flight (#206).

    A long single turn — above all the final no-tools synthesis turn — emits no
    per-step progress, so on a slow backend it is indistinguishable from a stall.
    Fire a phase notice via the SAME progress sink (#38), encoded with an EMPTY tool
    name so a sink renders it as a standalone line, never a step (the CLI sinks
    special-case the empty tool). Observability is never control: a missing sink is a
    no-op and a raising sink is suppressed, exactly like :func:`_emit_progress`. The
    step index carries the LIVE step count — ``len(result.steps)``, the same
    expression the per-step counter uses (#206 review: ``stats.step_count`` is only
    populated at loop exit by ``_finalize_stats``, so it would report a stale 0
    mid-run) — but the empty tool is the signal that this is a phase, not a step.
    """
    if ctx.progress is None:
        return
    step_index = len(ctx.result.steps)  # live count; stats.step_count is 0 until finalize
    with suppress(Exception):
        ctx.progress(step_index, "", detail, True)


def _deny_by_policy(ctx: _Work, call: ToolCall, span: Any, step_index: int) -> bool:
    """Check the approval policy for ``run_command``; record and return True on deny.

    Returns ``True`` when the call is denied (the caller must return False from
    the tool-call helper). Returns ``False`` when the policy allows the call.
    Only ``run_command`` is gated — all other tools pass through unchanged.
    """
    if call.name != "run_command":
        return False
    verdict = ctx.policy.check_run_command(str(call.arguments.get("command", "")))
    if verdict.allowed:
        return False
    # Denied — mirror the pre_tool DENY shape (span, Step, tool message, progress).
    span.set(ok=False, denied=True, reason=verdict.reason)
    ctx.result.steps.append(Step(step_index, call.name, call.arguments, verdict.reason, ok=False))
    ctx.messages.append(_tool_message(call.id, verdict.reason))
    _emit_progress(ctx, step_index, call.name, call.arguments, ok=False)
    return True


def _run_tool_call(ctx: _Work, call: ToolCall) -> bool:
    """Run one tool call inside its own telemetry span; return whether it finished.

    Owns the per-call lifecycle: the ``pre_tool`` hook (first deny/rewrite wins),
    execution, the ``post_tool`` hook, and finish detection. Kept as a single
    ``with tool_span`` block so exactly one step/tool-call metric is recorded per
    call — including the deny and error paths, which still close the span on the
    way out (they ``return False``, replacing the loop's old ``continue``).
    """
    step_index = len(ctx.result.steps)

    # One span per tool-call iteration, auto-nesting under the work item span. A
    # ``return False`` still runs the span's exit (so its metrics — one step +
    # one tool call — are recorded for deny/error paths too).
    with ctx.telemetry.tool_span(tool=call.name, step_index=step_index) as span:
        # pre_tool — the only control-bearing event. The first deny/rewrite
        # wins; allow/observe pass through. arguments may be swapped here.
        arguments = call.arguments
        decision = _fire_hooks(
            ctx.hooks,
            ctx.result,
            event="pre_tool",
            task=ctx.task,
            tool=call.name,
            arguments=arguments,
            policy=ctx.policy,
        )
        kind = decision.decision if decision is not None else None
        if kind == DECISION_DENY:
            # Skip execution entirely; feed the reason back so the model can
            # adapt. Recorded as a non-ok Step (the firing is already recorded
            # by _fire_hooks).
            reason = (decision and decision.reason) or "denied by a pre_tool hook"
            span.set(ok=False, denied=True, reason=reason)
            ctx.telemetry.on_hook_denial()
            ctx.result.steps.append(Step(step_index, call.name, arguments, reason, ok=False))
            ctx.messages.append(_tool_message(call.id, reason))
            _emit_progress(ctx, step_index, call.name, arguments, ok=False)
            return False
        if kind == DECISION_REWRITE and decision is not None and decision.arguments is not None:
            # Execute with the hook-supplied arguments instead.
            arguments = decision.arguments

        # Policy gate: check run_command against the operator-declared allow/deny
        # policy AFTER hooks (so a hook rewrite is still gated), BEFORE execution.
        # All other tools pass through unchanged. When denied, mirrors the hook-deny
        # shape — non-ok Step + tool message — but does NOT increment the hook-denial
        # telemetry counter (this is a policy denial, not a hook denial).
        if _deny_by_policy(ctx, ToolCall(call.id, call.name, arguments), span, step_index):
            return False

        try:
            outcome = ctx.executor.execute(call.name, arguments)
        except ToolError as exc:
            span.set(ok=False, error=str(exc))
            ctx.result.steps.append(
                Step(step_index, call.name, arguments, f"error: {exc}", ok=False)
            )
            ctx.messages.append(_tool_message(call.id, f"error: {exc}"))
            _emit_progress(ctx, step_index, call.name, arguments, ok=False)
            # post_tool still fires after a tool *attempt*; observe-only.
            _fire_hooks(
                ctx.hooks,
                ctx.result,
                event="post_tool",
                task=ctx.task,
                tool=call.name,
                arguments=arguments,
                policy=ctx.policy,
            )
            return False

        span.set(ok=True, bytes=len(outcome.result), changed_file=outcome.changed_file)
        ctx.result.steps.append(Step(step_index, call.name, arguments, outcome.result, ok=True))
        ctx.messages.append(_tool_message(call.id, outcome.result))
        _emit_progress(ctx, step_index, call.name, arguments, ok=True)

        # post_tool — after the tool executed. Observe-only: the decision does
        # not alter the already-executed result this increment.
        _fire_hooks(
            ctx.hooks,
            ctx.result,
            event="post_tool",
            task=ctx.task,
            tool=call.name,
            arguments=arguments,
            policy=ctx.policy,
        )

        if not outcome.finished:
            return False
        span.set(finished=True)
        _apply_finish(ctx.result, outcome)
        return True


def _run_tool_calls(ctx: _Work, calls: list[ToolCall]) -> bool:
    """Run every tool call in one model turn; return whether any finished.

    A finish does *not* stop the turn — the remaining calls in the same response
    still run (matching the original loop, where ``finished`` was set but the
    inner ``for`` kept iterating; only the outer step loop broke afterwards).
    """
    finished = False
    for call in calls:
        if _run_tool_call(ctx, call):
            finished = True
    return finished


def _window_in_place(ctx: _Work, budget: int) -> None:
    """Trim ``ctx.messages`` in place to *budget* tokens (preserves head + tail).

    Mutating in place (``[:]``) keeps the trimmed history across turns — dropping
    old context is intended. This is the lossy-windowing FLOOR: as of v1 (#156) the
    fill-line ``compact`` move replaces the elided turns with a model-authored
    summary, and this drop-oldest windowing is the fallback when the summary turn
    itself cannot fit. ``window_messages`` defaults ``count_tokens`` to the char
    estimate when ``ctx.count_tokens`` is ``None``.
    """
    ctx.messages[:] = window_messages(ctx.messages, budget, ctx.count_tokens)


def _autosplit_armed(ctx: _Work) -> bool:
    """True when reactive auto-split (#151) is armed for this work item.

    Armed iff degradation is active (a positive ``context_budget``) AND a positive
    ``autosplit_target`` is configured. Dormant (``False``) otherwise — a strict
    no-op identical to the pre-feature loop, so a caller that never sets the target
    (or sets it to 0) sees byte-identical behavior.
    """
    return (
        isinstance(ctx.context_budget, int)
        and ctx.context_budget > 0
        and isinstance(ctx.autosplit_target, int)
        and ctx.autosplit_target > 0
    )


def _inject_split_recommendation(ctx: _Work) -> None:
    """Append ONE structured split recommendation to the (windowed) history (#151).

    Names the per-child token budget (the ``context_budget`` — each child runs the
    same bounded loop under the same budget) and the child cap (derived + clamped to
    ``MAX_SUBAGENT_FANOUT - 1`` by :func:`colleague.autosplit.child_count`) and
    points the model at the existing ``subagents`` tool. Records the firing on
    ``_split_recommended`` so it is offered at most once per work item. The original
    assignment survives in ``messages[:2]`` (windowing never drops the head), so the
    model authoring the children always sees the full task.
    """
    per_child = int(ctx.context_budget)
    max_children = _autosplit.child_count(int(ctx.autosplit_target), per_child)
    body = _autosplit.build_split_recommendation(
        per_child_budget_tokens=per_child, max_children=max_children
    )
    ctx.messages.append({"role": "user", "content": body})
    ctx._split_recommended.append(True)


def _fillline_armed(ctx: _Work) -> bool:
    """True when the proactive fill-line decision (#156) is armed for this work item.

    Armed iff degradation is active (a positive ``context_budget``) AND a usable
    ``capacity_threshold`` fraction is configured. Dormant otherwise — a strict no-op
    byte-identical to the pre-feature loop.
    """
    return _fillline.armed(ctx.context_budget, ctx.capacity_threshold)


def _offer_fillline(ctx: _Work, prompt_tokens: int) -> None:
    """Inject the ONE structured fill-line decision prompt; mark it offered (#156).

    Names the three moves + the capacity numbers (reusing the autosplit child-count
    maths for the split option) and points the model at how to declare each by its
    next action. Offered at most once per work item via ``_fillline_offered``.
    """
    budget = int(ctx.context_budget)
    target = ctx.autosplit_target if isinstance(ctx.autosplit_target, int) else budget
    max_children = _autosplit.child_count(max(target, budget), budget)
    body = _fillline.build_decision_prompt(
        used_tokens=prompt_tokens,
        budget_tokens=budget,
        per_child_budget_tokens=budget,
        max_children=max_children,
    )
    ctx.messages.append({"role": "user", "content": body})
    ctx._fillline_offered.append(True)
    ctx._fillline_used.append(prompt_tokens)


def _record_fillline_decision(ctx: _Work, kind: str) -> None:
    """Record the declared fill-line move on the result (#156); mark it resolved.

    The reason names the offer-time token count (``_fillline_used``) so it matches the
    number stated in the decision prompt, not the declaring turn's slightly different
    prompt size.
    """
    budget = int(ctx.context_budget)
    used = ctx._fillline_used[0] if ctx._fillline_used else 0
    reason = f"context at {used} of {budget} budgeted tokens (fill line)"
    ctx.result.capacity_decision = CapacityDecision(kind=kind, reason=reason)
    ctx._fillline_resolved.append(True)


def _compact_history(ctx: _Work, complete: CompleteFn) -> None:
    """Compact the working history into a model-authored summary (compact branch, #156).

    Runs ONE bounded summarization turn over the windowed history and replaces the
    working history (after the preserved head ``messages[:2]``) with the summary, so
    the model continues from a compact note instead of losing older context silently.
    The summary turn is accounted like any other turn (counts against the step
    budget). If it raises a *degradable* error (the summary itself cannot fit), the
    loop falls back to today's lossy windowing — the documented floor.
    """
    budget = int(ctx.context_budget)
    request = _fillline.build_compaction_request(ctx.messages, budget, ctx.count_tokens)
    # Phase notice (#206): a compaction is a no-tools model turn that emits no step
    # line, so announce it before the (possibly slow) summarization completion.
    _emit_phase(ctx, _PHASE_COMPACTING)
    try:
        resp = complete(request)
    except Exception as exc:  # noqa: BLE001
        # The summary turn itself could not fit / timed out → fall back to the
        # lossy-windowing floor (degradation unchanged); never abort on a compaction.
        if classify_degradable(str(exc)) is not None:
            _window_in_place(ctx, budget)
            return
        raise
    _account_turn(ctx, resp)
    ctx.messages[:] = _fillline.apply_compaction(ctx.messages, resp.content)
    # auto-compact-on-finish (t3): preserve the compaction summary on its own cell so
    # it survives later turns and can serve as the FALLBACK clean summary at a
    # stop/budget exit when forced synthesis yields nothing (_resolve_terminal_summary).
    if resp.content:
        ctx._compacted_summary[:] = [resp.content]


def _maybe_offer_fillline(ctx: _Work, last_prompt_tokens: int) -> None:
    """Offer the fill-line decision once, when the last turn's context crossed it (#156).

    A strict no-op when dormant (not armed), already offered, or still under the
    threshold — so a work item that never fills its context is byte-identical to today.
    """
    if (
        _fillline_armed(ctx)
        and not ctx._fillline_offered
        and _fillline.crossed(
            last_prompt_tokens, int(ctx.context_budget), float(ctx.capacity_threshold)
        )
    ):
        _offer_fillline(ctx, last_prompt_tokens)


def _files_read(ctx: _Work) -> int:
    """Count the read-only mapping tool calls so far (``read_file`` + ``list_dir``)."""
    return sum(1 for step in ctx.result.steps if step.tool in ("read_file", "list_dir"))


def _maybe_offer_mapping_fanout(ctx: _Work) -> None:
    """Offer the per-folder fan-out advisory once a wide survey has read many files (#188).

    A strict no-op when dormant (``mapping_fanout_files`` unset / <= 0), already
    offered, or still under the threshold — so a normal task that reads a handful of
    files is byte-identical to today. Backend-judged + advisory: the loop injects ONE
    recommendation pointing at the existing ``subagents`` tool (no new fan-out/merge
    code) and the model decides whether to act. Offered at most once per work item via
    ``_mapping_fanout_offered``. Runtime-owned, so it fires identically for every
    backend (the all-engines rule).
    """
    threshold = ctx.mapping_fanout_files
    if not isinstance(threshold, int) or threshold <= 0:
        return
    if ctx._mapping_fanout_offered:
        return
    files = _files_read(ctx)
    if files <= threshold:
        return
    ctx.messages.append(
        {
            "role": "user",
            "content": _autosplit.build_mapping_fanout_recommendation(
                files_read=files, max_children=MAX_SUBAGENT_FANOUT - 1
            ),
        }
    )
    ctx._mapping_fanout_offered.append(True)


def _maybe_offer_plan_mode(ctx: _Work) -> None:
    """Offer the plan-mode advisory once, up front, for a complex task (#t8).

    A strict no-op when dormant (``plan_offer_tokens`` unset / <= 0) or already
    offered — so a normal task is byte-identical to today. Backend-judged +
    advisory: the loop injects ONE recommendation pointing at the ``colleague
    plan`` verb and the model decides whether to act. Offered at most once per
    work item. Runtime-owned, so it fires identically for every backend (the
    all-engines rule). Detection lives in :mod:`colleague.plan.trigger`.
    """
    threshold = ctx.plan_offer_tokens
    if not isinstance(threshold, int) or threshold <= 0:
        return
    if ctx._plan_offered:
        return
    from colleague.plan import trigger as _plan_trigger

    if not _plan_trigger.should_offer_plan_mode(
        ctx.task.instruction, already_offered=False, threshold_tokens=threshold
    ):
        return
    ctx.messages.append({"role": "user", "content": _plan_trigger.build_plan_recommendation()})
    ctx._plan_offered.append(True)


def _resolve_fillline(ctx: _Work, resp: ModelResponse, complete: CompleteFn) -> str:
    """Classify + record the model's declaring turn, acting on a compact move (#156).

    Maps the declaring turn to one move: a ``subagents`` call → ``split`` (the
    existing fan-out machinery then runs it), a ``finish`` call →
    ``finish-with-handoff`` (the existing finish path records the continuation
    summary), anything else → ``compact`` (this runs the self-summary now). Returns
    the move kind so the caller knows whether the compact branch already consumed the
    turn.
    """
    tool_names = [tc.name for tc in (resp.tool_calls or [])]
    kind = _fillline.classify_declaration(tool_names)
    _record_fillline_decision(ctx, kind)
    if kind == _fillline.MOVE_COMPACT:
        _compact_history(ctx, complete)
    return kind


def _consume_fillline_declaration(ctx: _Work, resp: ModelResponse, complete: CompleteFn) -> bool:
    """Resolve a pending fill-line declaration; return whether the loop should ``continue``.

    Returns ``True`` only for a *pure* compact declaration (no tool calls) — the
    history was compacted and the model continues from the summary next turn. For a
    compact-with-tool-calls turn (the model kept working) or a split/finish
    declaration, returns ``False`` so the caller still runs the declaring turn's tool
    calls (they are NOT discarded). A no-op (returns ``False``) when no declaration is
    pending.
    """
    if not (ctx._fillline_offered and not ctx._fillline_resolved):
        return False
    kind = _resolve_fillline(ctx, resp, complete)
    return kind == _fillline.MOVE_COMPACT and not resp.tool_calls


def _handle_degradable_exhaustion(ctx: _Work, exc: Exception) -> bool:
    """Reactive auto-split (#151) on an EXHAUSTED degradable error; return continue?.

    Returns ``True`` (inject ONE split recommendation, caller continues) when armed,
    not yet recommended, and the error is degradable — BEFORE it would propagate to
    run()'s abort+escalate path. Returns ``False`` otherwise so the caller re-raises,
    byte-identical to the pre-feature loop. Extracted from :func:`_work_loop` to keep
    its cognitive complexity within budget (SonarCloud S3776).
    """
    if (
        _autosplit_armed(ctx)
        and not ctx._split_recommended
        and classify_degradable(str(exc)) is not None
    ):
        _inject_split_recommendation(ctx)
        return True
    return False


def _remember_degraded_floor(ctx: _Work, budget: int) -> None:
    """Carry the floored budget from an exhausted give-up into the next turn (#154).

    Records the small window the shrink-and-retry bottomed out at so the auto-split /
    INCOMPLETE recommendation turn :func:`_work_loop` is about to grant runs against
    it instead of re-expanding to the full budget (which would just overflow / time
    out again). Set once on give-up; consumed-and-cleared by the next
    :func:`_complete_with_degradation` call, so only the recommendation turn is
    throttled. No-op cell when degradation is off (it is only ever read with a budget).
    """
    ctx._degraded_budget[:] = [max(1, budget)]


def _open_degradation_window(ctx: _Work, budget: int) -> int:
    """Window the history to the starting budget, honouring a carried-forward floor (#154).

    A prior exhausted give-up may have carried a floored budget forward so this turn —
    the auto-split / INCOMPLETE recommendation turn — stays small; honour it once, then
    clear it so later turns return to the full budget. Returns the effective starting
    budget the first ``complete`` attempt runs against.
    """
    start = budget
    if ctx._degraded_budget:
        start = min(budget, ctx._degraded_budget[0])
        ctx._degraded_budget.clear()
    _window_in_place(ctx, start)
    return start


def _shrink_for_retry(ctx: _Work, effective: int) -> int | None:
    """Shrink the budget one step and re-window; return the new budget, or ``None`` at the floor.

    Each retry strictly shrinks the budget (``* _OVERFLOW_SHRINK_FACTOR``, floored to
    ≥ 1) AND must reduce the message count. ``None`` means the floor was hit — neither
    the budget nor the message list (only system + first user + last turn remain) can
    shrink further — so retrying cannot help and the caller must give up. This pairing
    is what guarantees the reactive loop always terminates.
    """
    shrunk = max(1, int(effective * _OVERFLOW_SHRINK_FACTOR))
    before = len(ctx.messages)
    _window_in_place(ctx, shrunk)
    if shrunk >= effective and len(ctx.messages) >= before:
        return None
    return shrunk


def _plan_degraded_retry(
    ctx: _Work, exc: Exception, effective: int, saw_overflow: bool
) -> tuple[int, int, bool] | None:
    """Classify a caught error and prepare the next degraded retry.

    Returns ``(new_effective, new_cap, saw_overflow)`` to retry, or ``None`` to stop
    (the caller re-raises). Two stop cases collapse to ``None`` because both end the
    same way — the caller re-raises the in-flight exception: a *non-degradable* error
    (nothing to carry) and a degradable *floor* give-up (the floored budget is carried
    forward here via :func:`_remember_degraded_floor` before returning). The cap honours
    overflow precedence: once ANY overflow is seen it is the higher ``_MAX_OVERFLOW_RETRIES``,
    else the lower ``_MAX_TIMEOUT_RETRIES`` (#157).
    """
    signal = classify_degradable(str(exc))
    if signal is None:
        return None  # non-degradable: propagate immediately (unchanged)
    saw_overflow = saw_overflow or signal == "overflow"
    cap = _MAX_OVERFLOW_RETRIES if saw_overflow else _MAX_TIMEOUT_RETRIES
    shrunk = _shrink_for_retry(ctx, effective)
    if shrunk is None:
        _remember_degraded_floor(ctx, effective)  # at the floor: carry it, then give up
        return None
    return shrunk, cap, saw_overflow


def _final_degraded_attempt(ctx: _Work, complete: CompleteFn, effective: int) -> ModelResponse:
    """One last ``complete`` after the retry cap was exhausted while still making progress.

    A success returns normally and must NOT throttle the next (normal) turn; a
    degradable give-up carries the floored budget forward (#154) before re-raising so
    :func:`run` preserves the partial. A non-degradable error just re-raises.
    """
    try:
        return complete(ctx.messages)
    except Exception as exc:  # noqa: BLE001
        # Carry the floor only on a degradable give-up, then re-raise either way.
        if classify_degradable(str(exc)) is not None:
            _remember_degraded_floor(ctx, effective)
        raise


def _complete_with_degradation(
    ctx: _Work, complete: CompleteFn, *, phase: str = _PHASE_THINKING
) -> ModelResponse:
    """Window the history, call ``complete``, and degrade-on-overflow-or-timeout if budgeted.

    Owns the proactive window + the bounded reactive shrink-and-retry so
    :func:`_work_loop` stays shallow (SonarCloud S3776). With no positive
    ``context_budget`` this is a thin pass-through: no windowing, ``complete`` is
    called once and whatever it raises propagates unchanged.

    With a budget set: the history is windowed before the call. If ``complete``
    raises a *degradable* error — a context-overflow OR a request timeout
    (:func:`colleague.context.classify_degradable`) — the budget is shrunk and the
    call retried (see :func:`_shrink_for_retry`). The retry cap is per-signal and
    honours overflow precedence: a timeout alone is bounded by the lower
    ``_MAX_TIMEOUT_RETRIES`` (each attempt costs a full request-timeout window, #154),
    but ANY overflow seen in the sequence restores the higher ``_MAX_OVERFLOW_RETRIES``
    (an instant 400 is ~free to retry) — so a timeout earlier in a mixed
    timeout→overflow run never starves the later cheap overflow retries (#157, matching
    :func:`classify_degradable`'s overflow-takes-precedence rule). Retrying stops (and
    the original error re-raises, so :func:`run` preserves the partial) when the cap is
    reached OR :func:`_shrink_for_retry` reports the floor. On give-up the floored
    budget is carried to the next turn — the recommendation turn — via
    :func:`_remember_degraded_floor`. Non-degradable errors are never retried — they
    propagate immediately.
    """
    # Phase notice (#206): announce the model turn is in flight BEFORE the (possibly
    # long) completion — fired here, the one chokepoint every model turn passes
    # through, so the notice reaches the operator whether or not the context-budget
    # feature is on. Observability only; a no-op without a progress sink.
    _emit_phase(ctx, phase)
    budget = ctx.context_budget
    if not isinstance(budget, int) or budget <= 0:
        # Feature off: strict pass-through, byte-identical to the pre-feature loop.
        return complete(ctx.messages)

    effective = _open_degradation_window(ctx, budget)
    # The first attempt plus up to ``cap`` reactive retries. ``cap`` tracks the
    # highest-precedence signal seen so far (see :func:`_plan_degraded_retry`): it stays
    # at the overflow cap unless ONLY timeouts have been seen, and an overflow at any
    # point restores it (#157). The loop always terminates: each retry strictly shrinks
    # the budget and the message count (the floor), and the cap bounds the attempts.
    saw_overflow = False
    cap = _MAX_OVERFLOW_RETRIES
    attempt = 0
    while attempt <= cap:
        try:
            return complete(ctx.messages)
        except Exception as exc:  # noqa: BLE001
            plan = _plan_degraded_retry(ctx, exc, effective, saw_overflow)
            if plan is None:
                raise
            effective, cap, saw_overflow = plan
            attempt += 1
    return _final_degraded_attempt(ctx, complete, effective)


def _account_turn(ctx: _Work, resp: ModelResponse) -> None:
    """Per-turn bookkeeping (always-on): usage, telemetry, stats, last-substantive.

    Counts the turn and accumulates the generated reasoning/answer sizes (chars +
    bytes), mirrored into the optional telemetry as a strict no-op when off. Also
    tracks the last non-empty ``resp.content`` across ALL turns (including
    tool-call turns) — the t2 candidate ``run`` falls back to for the summary —
    via the mutable proxy so the frozen ``_Work`` binding stays intact.
    """
    ctx.result.usage.add(resp.prompt_tokens, resp.completion_tokens)
    ctx.telemetry.on_completion(resp.prompt_tokens, resp.completion_tokens)
    ctx.result.stats.model_turns += 1
    ctx.result.stats.add_generated(reasoning=resp.reasoning, answer=resp.content)
    ctx.telemetry.on_generated(reasoning=resp.reasoning, answer=resp.content)
    if resp.content:
        ctx._last_substantive[:] = [resp.content]


def _handle_no_tool_turn(ctx: _Work, resp: ModelResponse, nudges: int) -> tuple[int, str | None]:
    """Handle a turn that requested no tool — nudge up to the cap, else stop (#142).

    The contract is to call ``finish``; a bare prose turn is usually the model
    trailing off mid-task. Returns ``(nudges, exit)``: while under the configurable
    cap (``ctx.max_continue_nudges``, colleague PR #198) it appends the model's prose
    + a one-line finish reminder and returns ``(nudges + 1, None)`` (caller continues
    the loop); once the cap is reached it returns ``(nudges, _EXIT_STOPPED)`` WITHOUT
    setting ``result.summary`` — the trailing prose is often a mid-thought trail-off
    ("Let me check:"), so leaving the summary empty lets :func:`_maybe_force_synthesis`
    (#191) produce a clean summary from what was read; the prose still survives as the
    ``_last_substantive`` floor when synthesis (and the compaction fallback) yield
    nothing (auto-compact-on-finish, t3).
    """
    if nudges < ctx.max_continue_nudges:
        if resp.content:
            ctx.messages.append({"role": "assistant", "content": resp.content})
        ctx.messages.append({"role": "user", "content": _FINISH_NUDGE})
        return nudges + 1, None
    # Do NOT pre-set the trailing prose as the summary (auto-compact-on-finish, t3):
    # a context-rich stop is usually a mid-thought trail-off ("Let me check:") — the
    # t5 failure. Leaving ``result.summary`` empty lets ``_maybe_force_synthesis``
    # (#191) produce a clean summary from what was read; the prose still survives as
    # the ``_last_substantive`` floor when synthesis (and compaction) yield nothing.
    return nudges, _EXIT_STOPPED


def _advance_turn(ctx: _Work, resp: ModelResponse, nudges: int) -> tuple[int, str | None]:
    """Process a normal (non-fill-line) turn; return ``(nudges, exit_reason_or_None)``.

    Either handles a no-tool-call turn (nudge once, else stop) or runs the turn's tool
    calls (a finish ends the work item). Extracted from :func:`_work_loop` so that
    function's cognitive complexity stays within budget (SonarCloud S3776).
    """
    if not resp.tool_calls:
        return _handle_no_tool_turn(ctx, resp, nudges)
    ctx.messages.append(_assistant_message(resp))
    # Run the turn's tool calls; a finish on any of them ends the work item once the
    # turn completes (the remaining calls in the turn still run).
    if _run_tool_calls(ctx, resp.tool_calls):
        return nudges, _EXIT_FINISHED
    return nudges, None


def _flight_stop_requested(ctx: _Work) -> bool:
    """Read the flight control file at a turn boundary; inject guidance, report stop.

    A strict no-op (returns ``False``) when the work item is not a watchable flight.
    Each unconsumed guidance message is injected as a user-role turn so the model
    incorporates it on its NEXT turn; a ``stop`` directive asks the loop to end
    cooperatively. Both take effect only HERE, at the boundary — never mid-turn
    (cooperative, not preemptive).
    """
    if ctx.flight is None:
        return False
    control = ctx.flight.read_control()
    for message in control.guidance:
        ctx.messages.append({"role": "user", "content": f"[pilot guidance] {message}"})
    return bool(control.stop)


def _flight_record(ctx: _Work, resp: ModelResponse) -> None:
    """Append one live-feed record for the turn just processed (no-op when unwatched)."""
    if ctx.flight is None:
        return
    tool = ctx.result.steps[-1].tool if ctx.result.steps else None
    intent = (resp.content or "").strip()[:200] or (f"tool:{tool}" if tool else None)
    ctx.flight.append_feed(
        step_index=ctx.result.stats.step_count,
        tool=tool,
        intent=intent,
        stats=ctx.result.stats.to_dict(),
    )


def _arm_flight(task: Task) -> "flightmod.FlightSession | None":
    """Arm the flight-control plane for a watchable work item, else ``None`` (no-op).

    Built from the existing ``task`` so :func:`run` needs no new parameter (it sits
    near the S107 ceiling); ``arm`` creates the empty feed so a pilot can attach.
    """
    return flightmod.arm(task.repo_path, task.id) if task.watch else None


def _reap_flight(ctx: _Work) -> None:
    """Reap the live flight feed/control on finish (a no-op when not a flight).

    The authoritative result lives in the artifact, not the feed, so the live
    plane stays ephemeral — mirroring the neighbour cleanup. A reap failure must
    never mask the task result.
    """
    if ctx.flight is not None:
        with suppress(Exception):
            ctx.flight.reap()


def _apply_outcome_flags(result: TaskResult, outcome: str, last_sub: str) -> None:
    """Map the loop's exit reason onto the result's partial-state flags, status, + summary.

    A pilot's cooperative ``stop`` is a PARTIAL, not an authoritative result, so it
    is flagged like a no-finish stop (never a bare ``ok`` with no result; composes
    with the honest-status work, colleague#192) and its summary names the cause.

    Honest status (colleague#192): any non-``_EXIT_FINISHED`` outcome that did not
    already become ``ERROR`` (the aborted path in :func:`run` handles that, before
    this is called) is ``INCOMPLETE``; a clean finish stays ``OK``. Orthogonal to
    the ``not_finished`` / ``stopped_without_finish`` flags. Folded in here (rather
    than a separate ``if`` in :func:`run`) to keep ``run`` under the S3776
    cognitive-complexity threshold.
    """
    result.not_finished = outcome == _EXIT_BUDGET
    result.stopped_without_finish = outcome in (_EXIT_STOPPED, _EXIT_PILOT_STOP)
    if outcome != _EXIT_FINISHED:
        result.status = INCOMPLETE
    if outcome == _EXIT_PILOT_STOP:
        note = f"Stopped by pilot after {len(result.steps)} step(s) (partial)."
        result.summary = f"{note} {last_sub}".strip() if last_sub else note


def _maybe_force_synthesis(ctx: _Work, outcome: str, complete: CompleteFn) -> None:
    """Force ONE no-tools synthesis turn when a context-rich run produced no summary.

    Fires on three exits, all guarded on ``not ctx.result.summary`` (an answered run
    is never touched) and ``step_count > 0`` (nothing read, nothing to synthesise):

    - **budget / stopped** (colleague#191) — the loop exhausted its step budget or
      stopped without finishing, the most expensive failure mode (full token spend,
      zero output); turn it into a usable partial.
    - **finish with an empty summary** (colleague#202) — the model *called* ``finish``
      but gave no usable summary. For a read-only verb the summary IS the deliverable,
      so a blank finish is a silent no-op (status reads ``ok``); synthesise the answer
      from what was read instead of falling back to the last planning line.

    Best-effort: any error or an empty answer leaves ``summary`` untouched so the
    caller falls back to the last-substantive content or the ``NO_RESULT_PRODUCED``
    sentinel. Mirrors the retry-cap precedent (:func:`_final_degraded_attempt`) and
    reuses :func:`_complete_with_degradation` so the synthesis turn is windowed to the
    context budget like any other. A finish that carries a real summary, a pilot stop
    (already carries one), or a run that already answered is byte-identical to before.
    Runtime-owned: fires identically for every backend (all-engines rule).
    """
    if outcome not in (_EXIT_BUDGET, _EXIT_STOPPED, _EXIT_FINISHED):
        return
    if ctx.result.summary or ctx.result.stats.step_count <= 0:
        return
    prompt = _EMPTY_FINISH_PROMPT if outcome == _EXIT_FINISHED else _SYNTHESIS_PROMPT
    ctx.messages.append({"role": "user", "content": prompt})
    try:
        # The synthesis turn is the worst case for #206: a single no-tools completion
        # that emits no step line, so a slow backend looks wedged. Announce it loudly.
        resp = _complete_with_degradation(ctx, complete, phase=_PHASE_SYNTHESIZING)
    except Exception:  # noqa: BLE001 - best-effort; a finalize-time turn never raises
        return
    _account_turn(ctx, resp)
    if resp.content:
        ctx.result.summary = resp.content


def _resolve_terminal_summary(
    ctx: _Work, outcome: str, complete: CompleteFn, last_sub: str
) -> None:
    """Resolve ``result.summary`` on a non-finish exit; a finish/pilot summary is kept.

    Order is the point (it fixes the stale-compaction-summary regression, Qodo
    PR #198): force ONE no-tools synthesis turn (#191) **first** so the summary
    reflects everything read — INCLUDING any tool work the model did *after* a
    mid-run compaction. A run's own compaction self-summary (auto-compact-on-finish,
    t3) predates that later work, so it is only the **fallback** when synthesis
    yields nothing (it still survives to the exit — its reason for being captured),
    never preferred over a fresh synthesis. Final fallback: the last substantive
    prose, else the ``NO_RESULT_PRODUCED`` sentinel.

    A clean ``finish`` (or a pilot stop) already set ``result.summary``, so
    ``_maybe_force_synthesis`` and both fallbacks no-op — byte-identical to before.
    Extracted from :func:`run` so that function stays under the S3776
    cognitive-complexity threshold.
    """
    _maybe_force_synthesis(ctx, outcome, complete)
    if not ctx.result.summary and ctx._compacted_summary:
        ctx.result.summary = ctx._compacted_summary[0]
    if not ctx.result.summary:
        ctx.result.summary = last_sub or NO_RESULT_PRODUCED


def _resolve_nudge_cap(context: "ContextControls") -> int:
    """The continue-working nudge cap (#142 + colleague PR #198).

    Defaults to ``_MAX_FINISH_NUDGES`` when a :class:`ContextControls` omits it
    (direct :func:`run` callers / back-compat). Extracted to keep ``run`` under the
    S3776 cognitive-complexity threshold.
    """
    cap = context.max_continue_nudges
    return cap if cap is not None else _MAX_FINISH_NUDGES


def _work_loop(ctx: _Work, complete: CompleteFn, max_steps: int) -> str:
    """Run the bounded turn loop; return how it ended (one of the ``_EXIT_*`` constants).

    Each turn: window the history to the context budget (if set), call
    ``complete`` (with a bounded overflow shrink-and-retry), account usage, then
    either run the turn's tool calls or handle a no-tool-call turn. Whatever
    ``complete`` raises (after the bounded retry) propagates to :func:`run`, which
    turns it into a preserved partial result (#37). Pulled out of :func:`run` so
    the loop body lives in one focused function and ``run`` keeps its cognitive
    complexity under the threshold (SonarCloud S3776).

    Returns ``_EXIT_FINISHED`` (the finish tool was called), ``_EXIT_STOPPED`` (the
    model ended a turn with no tool call and — even after one nudge — never called
    finish; colleague#142), or ``_EXIT_BUDGET`` (``max_steps`` *model turns* taken
    without finishing).

    The budget counts *successful model turns* (``stats.model_turns``), not raw
    loop iterations: an exhausted-overflow iteration that only injects the
    auto-split recommendation (no ``complete`` returned, so no turn accounted) must
    NOT consume the budget — otherwise an overflow on the final iteration would
    leave the model zero turns to act on the recommendation (#151 review). Still
    bounded: the one-time injection aside, every iteration either accounts a turn
    (advancing toward the cap) or re-raises (exiting the loop), so it runs at most
    ``max_steps + 1`` iterations.
    """
    nudges = 0
    last_prompt_tokens = 0
    budget = max(1, max_steps)
    while ctx.result.stats.model_turns < budget:
        # Flight-control checkpoint (piloting): at this turn boundary honor a pilot's
        # cooperative `stop` and inject any new `guidance` BEFORE the next model call.
        # A strict no-op when the work item is not a watchable flight.
        if _flight_stop_requested(ctx):
            return _EXIT_PILOT_STOP
        # Proactive fill-line decision (#156): when the last turn's context crossed the
        # threshold, offer the one capacity decision (compact | split | handoff) BEFORE
        # this turn completes, so the model declares it by its next action. No-op when
        # dormant / already offered / under the line.
        _maybe_offer_fillline(ctx, last_prompt_tokens)
        # Mapping fan-out advisory (#188): once a wide read-only survey has read many
        # files serially, nudge the model ONCE to fan out per-folder via `subagents`
        # rather than spend the rest of its step budget reading. No-op when dormant /
        # already offered / under the files-read threshold.
        _maybe_offer_mapping_fanout(ctx)
        try:
            resp = _complete_with_degradation(ctx, complete)
        except Exception as exc:  # noqa: BLE001
            # An EXHAUSTED degradable error may trigger the reactive auto-split (#151,
            # #154) — inject ONE recommendation and continue BEFORE the error would
            # reach run()'s abort+escalate path; otherwise re-raise unchanged so
            # escalation remains the fallback (byte-identical to the pre-feature loop).
            if _handle_degradable_exhaustion(ctx, exc):
                continue
            raise
        _account_turn(ctx, resp)
        last_prompt_tokens = resp.prompt_tokens

        # If a fill-line decision is pending (#156), this turn is the model's
        # declaration: record it and, on a pure compact declaration, summarize +
        # continue from the compact note. A compact-with-tool-calls turn or a
        # split/finish declaration falls through so the declaring turn's tool calls
        # still run (never discarded).
        if _consume_fillline_declaration(ctx, resp, complete):
            continue

        nudges, exit_reason = _advance_turn(ctx, resp, nudges)
        # Record this turn on the live flight feed (no-op when unwatched) — placed
        # after _advance_turn so the step trace + stats already reflect the turn, and
        # before the exit return so a finishing turn is still recorded.
        _flight_record(ctx, resp)
        if exit_reason is not None:
            return exit_reason
    return _EXIT_BUDGET


@dataclass(frozen=True)
class Spawns:
    """The two optional delegation callbacks injected into the tool executor.

    ``single`` backs the ``subagent`` tool (built by
    :func:`colleague.subagents.make_spawn`); ``batch`` backs the ``subagents``
    (plural) tool (built by :func:`colleague.subagents.make_batch_spawn`).
    Bundling the pair keeps :func:`run`'s signature within the parameter budget
    while preserving the convenience path for callers that do not build their own
    executor. Both default ``None`` (the tool is simply unavailable).
    """

    single: Callable | None = None
    batch: Callable | None = None


@dataclass(frozen=True)
class ContextControls:
    """Optional context-window-management knobs injected into :func:`run`.

    Bundles the three settings that govern how the loop manages the context window
    — mirroring :class:`Spawns` — so ``run``'s signature stays within the parameter
    budget:

    - ``budget`` — proactive token budget (t4): the running history is windowed to
      it before every turn and a context-overflow triggers a bounded
      shrink-and-retry. ``None`` (the default) disables windowing — a strict no-op.
    - ``count_tokens`` — the token counter handed to :func:`window_messages`;
      ``None`` falls back to the char-based estimate.
    - ``autosplit_target`` — arms reactive auto-split (#151): with ``budget`` also
      positive, an exhausted overflow recommends splitting via the ``subagents``
      tool *before* escalating, and a coarse up-front instruction estimate adds an
      early hint. ``None``/0 leaves it dormant.

    All fields default ``None`` → byte-identical to the pre-feature loop. Runtime-
    owned: every backend forwards ``config.context_budget_tokens`` /
    ``config.autosplit_target_tokens`` here (the all-engines rule).
    """

    budget: int | None = None
    count_tokens: Callable[[list[dict[str, Any]]], int] | None = None
    autosplit_target: int | None = None
    # Fill-line decision threshold (#156): the fraction of ``budget`` at which the
    # proactive capacity decision (compact | split | finish-with-handoff) is offered.
    # ``None`` or out of ``(0, 1]`` leaves the proactive decision dormant — a strict
    # no-op (degradation + reactive auto-split still apply).
    fillline_threshold: float | None = None
    # Mapping fan-out advisory (#188): the files-read count at which the runtime
    # injects ONE advisory recommendation to fan a wide read-only survey out across
    # folders via the ``subagents`` tool. ``None``/<= 0 leaves it dormant — a strict
    # no-op. Forwarded by every backend from ``config.fanout_files`` (all-engines rule).
    fanout_files: int | None = None
    # Plan-mode auto-trigger (#t8): the instruction-token threshold at/above which a
    # normal work item injects ONE advisory recommendation to enter plan mode
    # (``colleague plan``). ``None``/<= 0 leaves it dormant — a strict no-op (opt-in).
    # Forwarded by every backend from ``config.plan_offer_tokens`` (all-engines rule).
    plan_offer_tokens: int | None = None
    # continue-working: max consecutive no-tool-call nudges before the loop gives up.
    # Forwarded by every backend from ``config.max_continue_nudges`` (all-engines
    # rule); ``None`` falls back to ``_MAX_FINISH_NUDGES`` (back-compat / strict no-op).
    max_continue_nudges: int | None = None
    # Synthesis reserve (#197): steps held back from the reading budget so a
    # read-heavy run (a big-diff review) stops reading early and the forced-synthesis
    # verdict turn (#191) runs with fresher, less-windowed context instead of being
    # starved after the budget is spent reading. ``None``/<= 0 reserves nothing — a
    # strict no-op (the full ``max_steps`` is spent reading, as before). Forwarded by
    # every backend from ``config.synthesis_reserve_steps``; the caller (review) sets
    # it. Clamped so at least one reading step always remains.
    synthesis_reserve: int | None = None
    # Lint pre-finish gate (#200): when ``lint`` is truthy the runtime runs the repo's
    # configured linters on the work item's changed files before handoff and auto-fixes
    # what it can; ``lint_fix_retries`` caps the bounded model fix-turn for residual
    # violations (0 = fixers only). ``None`` (the default) leaves the gate OFF — a strict
    # no-op for direct ``run`` callers. Forwarded by every backend from ``config.lint`` /
    # ``config.lint_fix_retries`` (all-engines rule).
    lint: bool | None = None
    lint_fix_retries: int | None = None
    # Test-integrity gate (#203): when truthy (the default) the runtime runs the
    # mirror-detection heuristic on the changed files after the loop and records the
    # findings on ``result.test_integrity_report``. Advisory + non-blocking — never
    # blocks the handoff, makes no network call, and a no-finding run is byte-identical
    # (omit-when-None). Defaults ON so the gate fires for every backend without each
    # backend opting in; pass ``False`` to disable (the env/config opt-out feeds it).
    testintegrity: bool = True
    # Caps the bounded model re-examine turn for a flagged symbol (0 = detect-and-record
    # only, the conservative default). ``None`` leaves it at 0. Forwarded by every
    # backend from ``config.testintegrity_fix_retries`` (all-engines rule).
    testintegrity_fix_retries: int | None = None
    # The DIFFERENT model id for the diverse reviewer subagent (the robust guard). When
    # set, a flagged finding auto-spawns a reviewer on this model to independently
    # re-derive the real API shape; empty/None degrades to record-only. Forwarded from
    # ``config.testintegrity_reviewer_model`` (all-engines rule).
    testintegrity_reviewer_model: str | None = None


def _build_user_message(task: Task) -> str:
    """Compose the first user turn from the instruction + optional context/constraints.

    Extracted from :func:`run` (a pure string build, no behavior change) so that
    function's cognitive complexity stays within budget.
    """
    user = task.instruction
    if task.context:
        user += f"\n\nContext:\n{task.context}"
    if task.constraints:
        user += "\n\nConstraints:\n" + "\n".join(f"- {c}" for c in task.constraints)
    return user


def _maybe_inject_upfront_hint(ctx: _Work) -> None:
    """Append the up-front advisory split hint when armed and the task looks big (#151).

    A COARSE estimate of the instruction alone (it cannot see the repo surface the
    work will touch — the parked limit r2): when armed and that estimate already
    exceeds one context window, append ONE optional early suggestion to split via
    the ``subagents`` tool. Advisory only — it never blocks and adds NO model turn
    (just context the first turn sees). It almost never fires for a normal-sized
    task, so the default path stays byte-identical. Extracted from :func:`run` to
    keep that function's cognitive complexity within budget.
    """
    if not _autosplit_armed(ctx):
        return
    budget = int(ctx.context_budget)
    estimate = _autosplit.estimate_instruction_tokens(ctx.task.instruction, ctx.count_tokens)
    if estimate <= budget:
        return
    ctx.messages.append(
        {
            "role": "user",
            "content": _autosplit.build_upfront_hint(
                estimate_tokens=estimate,
                per_child_budget_tokens=budget,
                max_children=_autosplit.child_count(int(ctx.autosplit_target), budget),
            ),
        }
    )


def _maybe_warn_too_big(ctx: _Work) -> None:
    """Set the warn-only "too big for one repo" caller warning (#156, t7).

    A coarse up-front capacity assessment (deps/folders/files + an instruction token
    estimate via :mod:`colleague.capacity`) that judges the assignment to exceed even
    the in-repo split capacity records a caller-visible warning on
    ``result.capacity_warning`` — surfaced (CLI prints it to stderr; it is recorded in
    the artifact), never silent. Colleague performs NO cross-repo write: the operator
    splits the work across repos/instances (neighbours stay read-only). A strict no-op
    for a normal-sized job (verdict != over_split_capacity → warning stays ``None`` →
    omitted from the artifact). Gated on a positive budget like the other context
    features. The estimate is coarse (it cannot see the repo surface the work will
    touch — the parked limit r2)."""
    budget = ctx.context_budget
    if not isinstance(budget, int) or budget <= 0:
        return
    # Pass the REAL split capacity (the autosplit target = max children × per-child
    # budget) so the verdict isn't a magic 4× proxy; the assessment folds the repo's
    # complexity (deps/folders/files) into the effective size it judges.
    split_capacity = ctx.autosplit_target if isinstance(ctx.autosplit_target, int) else None
    verdict = assess_capacity(
        ctx.task.repo_path,
        ctx.task.instruction,
        budget,
        ctx.count_tokens,
        split_capacity_tokens=split_capacity,
    )
    if verdict.verdict == "over_split_capacity":
        ceiling = split_capacity if split_capacity else budget * 4
        ctx.result.capacity_warning = (
            f"This assignment looks too big to hold in one repo: an estimated "
            f"{verdict.effective_tokens} effective tokens (instruction + repo complexity) "
            f"exceeds even the in-repo split capacity (~{ceiling} tokens across child "
            f"instances). Consider splitting it across multiple repositories or colleague "
            f"instances — colleague will not write across repos (warn-only)."
        )


# Bounded extra model turns granted to ONE lint fix-turn (#200). Small — the fix-turn
# only needs to read/edit a few files and finish; the per-work-item cap is
# ``ctx.lint_fix_retries`` fix-turns, each running up to this many model turns.
_LINT_FIX_STEPS = 6

_LINT_FIX_PROMPT = (
    "The pre-finish lint gate ran the repo's configured linters and auto-fixed what it "
    "could, but these violations remain and the auto-fixers cannot resolve them. Fix "
    "ONLY these, using read_file/edit_file/write_file, then call finish:\n"
)


def _maybe_run_lint_gate(
    ctx: _Work, complete: CompleteFn, outcome: str, aborted: Exception | None
) -> None:
    """Run the pre-finish lint gate: auto-fix changed files, then surface residual (#200).

    Deterministic fixers (black/isort/ruff) run first; if reporter (flake8 / ruff
    check) violations remain AND the main loop finished cleanly AND a fix-turn budget
    is left, ONE bounded model fix-turn is injected per remaining retry (capped by
    ``ctx.lint_fix_retries``), re-running the gate after each. Non-blocking: the
    handoff always proceeds; the final :class:`~colleague.contract.LintReport` is
    attached to ``result.lint_report``. A strict no-op when the loop aborted, lint is
    disabled, no files changed, or no linters are configured (the gate returns
    ``None``). The model fix-turn is held to a clean finish — an incomplete run
    (budget/stop) should not spend extra turns chasing lint nits, and its INCOMPLETE
    status must stand.

    Best-effort + fail-safe (#209 review): the body is wrapped in ``suppress`` so a
    linter that hangs/errors past :mod:`colleague.lint`'s own guards can NEVER abort
    ``run()`` (which calls this AFTER its main try/except, before the changed_files
    snapshot). Mirrors the neighbour-clone / hook fail-safes.
    """
    if aborted is not None or not ctx.lint_enabled:
        return
    with suppress(Exception):
        changed = sorted(ctx.executor.changed)
        if not changed:
            return
        report = _lint.run_lint_gate(ctx.task.repo_path, changed)
        if report is None:
            return
        retries = ctx.lint_fix_retries if outcome == _EXIT_FINISHED else 0
        while report.residual and retries > 0:
            _run_lint_fix_turn(ctx, complete, report.residual)
            retries -= 1
            next_report = _lint.run_lint_gate(ctx.task.repo_path, sorted(ctx.executor.changed))
            if next_report is None:
                break
            report = next_report
        ctx.result.lint_report = report


def _run_lint_fix_turn(ctx: _Work, complete: CompleteFn, residual: list[str]) -> None:
    """Inject ONE bounded model turn to fix residual lint, preserving terminal state.

    Re-enters :func:`_work_loop` with a small extra step budget after appending a fix
    instruction listing the residual violations. The main work's terminal fields
    (``summary`` / ``status`` / the two outcome flags) are saved and restored so a
    fix-turn ``finish`` cannot clobber the work item's real summary or flip its status.
    Any fix-turn failure is suppressed — the lint gate is best-effort and must never
    abort the work item (the same fail-safe as hooks / neighbour clones).
    """
    saved = (
        ctx.result.summary,
        ctx.result.status,
        ctx.result.not_finished,
        ctx.result.stopped_without_finish,
    )
    ctx.messages.append({"role": "user", "content": _LINT_FIX_PROMPT + "\n".join(residual[:50])})
    budget = ctx.result.stats.model_turns + _LINT_FIX_STEPS
    with suppress(Exception):
        _work_loop(ctx, complete, budget)
    (
        ctx.result.summary,
        ctx.result.status,
        ctx.result.not_finished,
        ctx.result.stopped_without_finish,
    ) = saved


def _maybe_run_test_integrity_gate(
    ctx: _Work, complete: CompleteFn, outcome: str, aborted: Exception | None
) -> None:
    """Run the post-loop test-integrity gate: flag the mirror signature (#203).

    Deterministic and code-locked: on a non-aborted exit it runs the
    mirror-detection heuristic (:func:`colleague.testintegrity.detect_mirror`) on
    the work item's changed files REGARDLESS of model behaviour — the model cannot
    skip it — and records any findings on ``result.test_integrity_report`` plus a
    line on stderr. The mirror signature is a novel identifier (attribute access or
    string-literal dict key) co-introduced in BOTH a changed test file and a changed
    module-under-test yet found nowhere else in the repo — the mechanical signal that
    a test merely mirrors the implementation's own (possibly wrong) assumption (the
    #203 self-confirming false positive).

    Bounded re-examine turn (#203 t3): when findings remain after a CLEAN finish
    (``outcome == _EXIT_FINISHED``) and a fix-turn budget is left
    (``ctx.testintegrity_fix_retries``), ONE bounded model turn is injected per
    remaining retry asking the model to verify the flagged symbol against the REAL
    API shape and fix it if wrong, re-running the gate after each. Conservative by
    default (``testintegrity_fix_retries`` defaults to 0 — detect-and-record only).
    Effectively a no-op on ``mock`` (the replayed script has already finished, so the
    fix-turn does nothing) and the work item's terminal summary/status are saved and
    restored either way, so a fix-turn ``finish`` can never clobber the real result.

    Advisory + non-blocking: it NEVER blocks the git handoff and makes NO network
    call. A no-finding run is byte-identical — the report stays ``None`` and is
    omitted from the artifact (the h6 omit-when-None guarantee). A strict no-op when
    the loop aborted, the gate is disabled, or no files changed.

    Best-effort + fail-safe (mirrors the lint-gate / neighbour-clone / hook
    fail-safes): the body is wrapped in ``suppress`` so detection can NEVER abort
    ``run()`` (which calls this after its main try/except, before the changed_files
    snapshot). The diverse-model reviewer is layered on in #203 task t4.
    """
    if aborted is not None or not ctx.testintegrity_enabled:
        return
    with suppress(Exception):
        changed = sorted(ctx.executor.changed)
        if not changed:
            return
        report = _testintegrity.detect_mirror(ctx.task.repo_path, changed)
        if not report.findings:
            return
        ctx.result.test_integrity_report = report
        _surface_test_integrity(report)
        # Bounded re-examine turn(s) — only after a clean finish with budget left.
        retries = ctx.testintegrity_fix_retries if outcome == _EXIT_FINISHED else 0
        while report.findings and retries > 0:
            _run_test_integrity_fix_turn(ctx, complete, report.findings)
            retries -= 1
            report = _testintegrity.detect_mirror(ctx.task.repo_path, sorted(ctx.executor.changed))
            ctx.result.test_integrity_report = report if report.findings else None
        # Diverse-model reviewer — the robust guard: a same-model re-examine turn can
        # re-confirm its own mirror, so spawn a DIFFERENT model to re-derive the real
        # API shape independently. Only when findings remain and a reviewer is wired.
        if ctx.result.test_integrity_report is not None and report.findings:
            _maybe_spawn_test_integrity_reviewer(ctx, report.findings)


# A re-examine turn re-enters the loop for at most this many model turns.
_TESTINTEGRITY_FIX_STEPS = 6

_TESTINTEGRITY_FIX_PROMPT = (
    "The test-integrity gate flagged a possible self-confirming test: you and your "
    "test BOTH introduced the following symbol(s), found NOWHERE ELSE in the repo. "
    "This is the signature of a test that merely mirrors the implementation's own "
    "(possibly wrong) assumption about an external API. For each symbol, verify it "
    "against the REAL API shape (the actual library/SDK attribute name or dict key) "
    "and FIX it in BOTH the implementation and the test if it is wrong, using "
    "read_file/edit_file/write_file; if it is genuinely correct, leave it. Then call "
    "finish:\n"
)


def _run_test_integrity_fix_turn(
    ctx: _Work, complete: CompleteFn, findings: "list[_testintegrity.MirrorFinding]"
) -> None:
    """Inject ONE bounded model turn to re-examine a flagged symbol, preserving state.

    Re-enters :func:`_work_loop` with a small extra step budget after appending the
    re-examine instruction. The main work's terminal fields (summary / status / the
    two outcome flags) are saved and restored so a re-examine ``finish`` cannot
    clobber the work item's real result — the exact lint-fix-turn precedent. Any
    failure is suppressed (the gate is best-effort and must never abort the work item).
    """
    saved = (
        ctx.result.summary,
        ctx.result.status,
        ctx.result.not_finished,
        ctx.result.stopped_without_finish,
    )
    detail = "\n".join(
        f"- {f.symbol} ({f.kind}) in {f.test_file} & {f.impl_file}" for f in findings[:50]
    )
    ctx.messages.append({"role": "user", "content": _TESTINTEGRITY_FIX_PROMPT + detail})
    budget = ctx.result.stats.model_turns + _TESTINTEGRITY_FIX_STEPS
    with suppress(Exception):
        _work_loop(ctx, complete, budget)
    (
        ctx.result.summary,
        ctx.result.status,
        ctx.result.not_finished,
        ctx.result.stopped_without_finish,
    ) = saved


def _surface_test_integrity(report: "_testintegrity.TestIntegrityReport") -> None:
    """Write the mirror-signature findings to stderr (advisory; never raises)."""
    detail = "; ".join(
        f"{f.symbol} ({f.kind}) co-introduced in {f.test_file} & {f.impl_file}"
        for f in report.findings
    )
    with suppress(OSError):
        sys.stderr.write(
            "test-integrity: possible self-confirming test(s) — mirror signature "
            f"flagged: {detail}\n"
        )


_TESTINTEGRITY_REVIEWER_PROMPT = (
    "You are a DIFFERENT model reviewing another agent's work for a self-confirming "
    "test. An automated check flagged the following symbol(s) as a mirror signature — "
    "co-introduced in BOTH a test and its module-under-test and found nowhere else, "
    "which can mean the test merely mirrors the implementation's own (possibly wrong) "
    "assumption about an external API. INDEPENDENTLY determine the CORRECT real API "
    "shape for each symbol (the actual library/SDK attribute name or dict key) WITHOUT "
    "trusting the existing code, then report whether the code's usage is CORRECT or "
    "WRONG and, if wrong, what the right symbol is. This is a READ-ONLY review: do not "
    "modify files — read what you need and report your verdict via finish.\n\n"
    "Flagged symbol(s):\n"
)


def _maybe_spawn_test_integrity_reviewer(
    ctx: _Work, findings: "list[_testintegrity.MirrorFinding]"
) -> None:
    """Spawn a DIFFERENT-model reviewer subagent to vet a flagged mirror (#203 t4).

    The same-model re-examine turn can re-confirm its own mirror, so the robust guard
    is an independent second mind: when ``ctx.testintegrity_reviewer_model`` names a
    model AND a single-spawn callback is wired into the executor, spawn ONE reviewer
    subagent on that model (read-only) to re-derive the real API shape and report
    disagreement. Its :class:`~colleague.contract.SubResult` is appended to the
    executor's accumulator so the standard snapshot folds it into
    ``result.sub_results``; its changed files are intentionally NOT merged into the
    handoff (the review is read-only). Reuses the existing subagent launcher with NO
    new worktree/merge code, and is bounded by the existing fan-out cap.

    Degrades to record-only — a strict no-op — when no reviewer model is configured,
    no spawn callback is wired, or the per-work-item fan-out cap is already reached.
    Best-effort: any launcher/engine error is suppressed so the gate never aborts.
    """
    reviewer_model = (ctx.testintegrity_reviewer_model or "").strip()
    spawn = getattr(ctx.executor, "_spawn", None)
    if not reviewer_model or spawn is None:
        return
    if len(ctx.executor.sub_results) >= MAX_SUBAGENT_FANOUT:
        return
    detail = "\n".join(
        f"- {f.symbol} ({f.kind}) in {f.test_file} & {f.impl_file}" for f in findings[:50]
    )
    with suppress(Exception):
        sub = spawn(_TESTINTEGRITY_REVIEWER_PROMPT + detail, None, reviewer_model)
        if sub is not None:
            ctx.executor.sub_results.append(sub)


def run(
    complete: CompleteFn,
    task: Task,
    *,
    max_steps: int,
    executor: ToolExecutor | None = None,
    system_prompt: str | None = None,
    hooks: HookConfig | None = None,
    telemetry: Telemetry | None = None,
    model: str | None = None,
    progress: ProgressFn | None = None,
    policy: Policy | None = None,
    spawns: Spawns | None = None,
    context: ContextControls | None = None,
) -> TaskResult:
    """Drive ``complete`` against ``task`` until finish or the ``max_steps`` budget.

    ``executor`` defaults to one confined to ``task.repo_path``. ``hooks``
    defaults to the config loaded from ``task.repo_path`` (so engines that call
    :func:`run` unchanged still get the lifecycle); pass an explicit
    :class:`~colleague.hooks.HookConfig` (e.g. an empty one) to override or
    suppress repo loading. Returns a uniform :class:`TaskResult` with the
    per-step trace, accumulated usage, and every hook firing in order. The tool
    schemas live with each backend's ``complete`` closure, not here.

    ``model`` threads into per-model hook resolution: when given,
    :func:`~colleague.hooks.load_hooks` additionally loads the per-model
    overlay ``.colleague/<model>/hooks.json`` and prepends its entries ahead
    of the base entries (per-model fix takes priority). When ``None`` (the
    default) the call is identical to the base-only load — no behavior change
    for callers that do not pass a model.

    ``telemetry`` likewise defaults to :func:`~colleague.telemetry.load_telemetry`
    (a no-op unless ``COLLEAGUE_OTEL_ENABLED`` is set). When enabled, every
    tool call becomes a ``colleague.tool.*`` span and the loop records the
    per-step metrics (steps, tokens, tool latency, hook denials). This lives in
    the loop so *every* engine inherits it (the all-engines rule), exactly like
    hook firing.

    ``progress`` is an optional per-step sink ``(step_index, tool, target, ok)``
    fired after each tool call (#38); ``None`` (the default) is a strict no-op.
    Like hooks/telemetry it is runtime-owned — every backend forwards
    ``config.progress`` so the behavior is identical across backends.

    ``spawns`` is an optional :class:`Spawns` bundle of the two delegation
    callbacks. ``spawns.single`` ``(instruction, engine=None, model=None) ->
    SubResult`` (built by :func:`colleague.subagents.make_spawn`) backs the
    ``subagent`` tool; ``spawns.batch`` ``(items) -> list[SubResult]`` (built by
    :func:`colleague.subagents.make_batch_spawn`) backs the ``subagents`` (plural)
    parallel-batch tool. When given they are injected into the
    :class:`~colleague.tools.ToolExecutor` so the corresponding tool can delegate
    to nested child work items; ``None`` (the default), or a field left ``None``,
    leaves that tool unavailable (it reports so to the model). This is runtime-owned
    — backends build their own executor from ``config.subagent_spawn`` /
    ``config.subagent_batch_spawn`` (the ``executor`` seam), so the ``spawns``
    convenience path is for direct callers. Any nested results the executor
    accumulates are snapshotted onto ``result.sub_results`` on every exit path
    (alongside ``changed_files``).

    ``context`` is an optional :class:`ContextControls` bundle of the three
    context-window-management knobs (``budget`` / ``count_tokens`` /
    ``autosplit_target``) — see that class for the per-field contract. In short:
    ``budget`` windows the history before every turn and drives the bounded
    overflow shrink-and-retry; ``count_tokens`` is the counter handed to
    :func:`window_messages`; and ``autosplit_target`` (with ``budget`` also
    positive) arms reactive auto-split (#151) — an exhausted overflow recommends
    splitting via the ``subagents`` tool *before* escalating, plus a coarse up-front
    hint. ``None`` (the default), or any field left ``None``/0, is a strict no-op
    byte-identical to the pre-feature loop. Runtime-owned (the all-engines rule):
    every backend forwards its ``config`` budget + autosplit target here.

    If ``complete`` raises mid-loop (e.g. a per-request timeout, or a
    context-overflow the bounded retry could not recover), the partial work is
    *preserved*: the accumulated ``steps`` / ``usage`` / ``changed_files`` are
    finalized onto the result with ``status=error`` and re-raised as
    :class:`WorkAborted` carrying that result, so the work path can write a
    non-empty artifact + trace before surfacing the error (#37).
    """
    _spawns = spawns or Spawns()
    _context = context or ContextControls()
    executor = executor or ToolExecutor(
        task.repo_path, spawn=_spawns.single, batch_spawn=_spawns.batch
    )
    hooks = hooks if hooks is not None else load_hooks(task.repo_path, model=model)
    # Telemetry defaults like hooks do: resolved from the environment, a no-op
    # unless explicitly enabled. Tool spans auto-nest under the work item span the
    # shared work path opens (via the SDK's context propagation).
    telemetry = telemetry if telemetry is not None else load_telemetry()
    # Policy defaults like hooks: loaded from task.repo_path when not injected.
    # An absent or malformed approvals.json returns an empty Policy (no-op), so
    # callers that never set policy= keep byte-identical behavior.
    policy = policy if policy is not None else load_policy(task.repo_path, model=model)

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt or _DEFAULT_SYSTEM},
        {"role": "user", "content": _build_user_message(task)},
    ]

    result = TaskResult(task_id=task.id, status=OK)

    # Neighbour clone lifecycle — runtime-owned (all-engines rule).
    # clone_all() runs before the loop so allow-listed neighbours are available
    # to read during the work item. With no allow-list this is a safe no-op (verified
    # by NeighbourManager itself). cleanup() runs unconditionally after the loop
    # on EVERY exit path (model finish, empty turn, step-budget) to leave no
    # residue between drives.
    neighbours = NeighbourManager(task.repo_path)
    # A neighbour clone failure (unreachable remote, bad URL, timeout, bad name)
    # must never abort the work item — the loop proceeds without that neighbour. This
    # mirrors the "a hook must never abort the work item" fail-safe: neighbour clones
    # are best-effort context, not a precondition for the task.
    with suppress(Exception):
        neighbours.clone_all()

    # task_start — once, before the loop. Observe-only: side-effects only.
    _fire_hooks(hooks, result, event="task_start", task=task, policy=policy)

    # Arm the flight-control plane when this is a watchable flight (a strict no-op
    # otherwise); inherited by every backend (the all-engines rule).
    flight_session = _arm_flight(task)

    # The fixed collaborators for this drive — passed as one ``ctx`` to the
    # per-turn / per-call helpers so the loop body stays shallow.
    ctx = _Work(
        executor=executor,
        hooks=hooks,
        telemetry=telemetry,
        task=task,
        result=result,
        messages=messages,
        policy=policy,
        progress=progress,
        context_budget=_context.budget,
        count_tokens=_context.count_tokens,
        autosplit_target=_context.autosplit_target,
        capacity_threshold=_context.fillline_threshold,
        mapping_fanout_files=_context.fanout_files,
        plan_offer_tokens=_context.plan_offer_tokens,
        max_continue_nudges=_resolve_nudge_cap(_context),
        flight=flight_session,
        lint_enabled=bool(_context.lint),
        lint_fix_retries=_context.lint_fix_retries or 0,
        testintegrity_enabled=bool(_context.testintegrity),
        testintegrity_fix_retries=_context.testintegrity_fix_retries or 0,
        testintegrity_reviewer_model=_context.testintegrity_reviewer_model or "",
    )

    # Up-front advisory split hint (#151) — extracted to keep run()'s cognitive
    # complexity within budget; a strict no-op unless armed and the task looks big.
    _maybe_inject_upfront_hint(ctx)

    # Up-front plan-mode advisory (#t8) — injects ONE recommendation to enter plan
    # mode for a complex task; a strict no-op unless armed (plan_offer_tokens > 0).
    _maybe_offer_plan_mode(ctx)

    # Up-front "too big for one repo" caller warning (#156) — sets
    # result.capacity_warning when even a split can't hold the job; a strict no-op
    # for a normal-sized assignment.
    _maybe_warn_too_big(ctx)

    # Drive timing (always-on): an ISO start stamp + a monotonic clock bracketing
    # the loop. Captured here so the duration covers the model work; finalized onto
    # WorkStats on every exit path below.
    started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    start_monotonic = time.monotonic()

    # The engine call (`complete`) may raise mid-loop. Catch it here so the
    # partial work accumulated on `result` is preserved rather than discarded
    # (#37); the finish hook + neighbour cleanup + changed_files snapshot below
    # then run on *every* exit path, including this one.
    aborted: Exception | None = None
    outcome = _EXIT_BUDGET
    # Synthesis reserve (#197): hold back a few steps from the reading budget so a
    # read-heavy run stops reading early and the forced-synthesis verdict (#191) runs
    # with fresher context. Clamped to leave at least one reading step; 0/None is
    # byte-identical (the full budget is spent reading). The full ``max_steps`` is
    # still what the partial-warning hint reports.
    _reserve = _context.synthesis_reserve or 0
    reading_budget = max(1, max_steps - _reserve) if _reserve > 0 else max_steps
    try:
        outcome = _work_loop(ctx, complete, reading_budget)
    except Exception as exc:  # noqa: BLE001 - preserve partial work on any engine failure
        aborted = exc
        result.status = ERROR
        result.error = f"{type(exc).__name__}: {exc}"

    # finish — once, on every loop exit (model finish / empty turn / budget / error).
    # Observe-only this increment; requeue/re-drive is out of scope.
    _fire_hooks(hooks, result, event="finish", task=task, policy=policy)

    # Neighbour cleanup — runs on every loop exit, after the finish hook, so
    # no clone directory persists between drives. Safe even when no clones exist
    # (NeighbourManager.cleanup() is a no-op if the neighbours dir is absent).
    # Like clone_all above, a cleanup failure must never mask the task result.
    with suppress(Exception):
        neighbours.cleanup()

    # Flight cleanup — reap the live feed/control on finish so the plane stays
    # ephemeral (a no-op when the work item was not a flight).
    _reap_flight(ctx)

    # Pre-finish lint gate (#200): on a NON-aborted exit, run the repo's configured
    # linters on the changed files and auto-fix what they can; if reporter violations
    # remain after a clean finish, inject ONE bounded model fix-turn (capped by
    # lint_fix_retries). Runs BEFORE the changed_files snapshot + stats below so any
    # fix-turn edits are captured. Non-blocking: the handoff always proceeds. The
    # aborted guard + the best-effort wrapping live in the helper (so it can never
    # abort run(), #209 review) — call it unconditionally to keep run() flat.
    _maybe_run_lint_gate(ctx, complete, outcome, aborted)

    # Pre-finish test-integrity gate (#203): on a NON-aborted exit, flag the mirror
    # signature on the changed files and record it on result.test_integrity_report.
    # Advisory + non-blocking (never blocks the handoff, no network); the aborted
    # guard + best-effort wrapping live in the helper so it can never abort run().
    # Runs after the lint gate so it sees the lint-fixed changed set.
    _maybe_run_test_integrity_gate(ctx, complete, outcome, aborted)

    result.changed_files = sorted(executor.changed)
    # Snapshot any nested child work items the executor accumulated — captured here,
    # the single place that runs on EVERY exit path (model finish / empty turn /
    # budget / the aborted path below), so a delegation survives even a mid-loop
    # engine raise. Empty when nothing was delegated → omitted from the artifact.
    result.sub_results = list(executor.sub_results)
    # Finalize the always-on drive statistics — runs on every exit path (here,
    # the single place after changed_files is known), so even a partial/aborted
    # drive carries populated stats. The optional telemetry mirrors bytes_written.
    _finalize_stats(
        result,
        task,
        executor,
        started_at=started_at,
        duration_seconds=round(time.monotonic() - start_monotonic, 6),
    )
    telemetry.on_bytes_written(result.stats.bytes_written)

    # Resolve the last-substantive-content candidate from the work item loop.
    # ``ctx._last_substantive`` is a single-element list (or empty) updated
    # unconditionally on every turn — including turns that made tool calls.
    _last_sub = ctx._last_substantive[0] if ctx._last_substantive else ""

    if aborted is not None:
        # Carry the populated partial result out via WorkAborted; the work path
        # writes it (non-empty steps/usage/changed_files + trace) then re-surfaces
        # the failure to the operator (#37).
        # Prefer the model's last substantive content over the generic aborted
        # note so the escalation continuation (below) carries the real output
        # rather than an empty/placeholder summary (Qodo #114).
        result.summary = (
            result.summary
            or _last_sub
            or (f"aborted after {len(result.steps)} step(s): {result.error}")
        )
        # Escalation seam — aborted path (#106 t3): best-effort, observe-only.
        # A timeout / context-overflow / engine error is a limit worth escalating.
        # Wrapped in suppress so any escalation failure never masks the work item result.
        with suppress(Exception):
            _escalation.escalate(result, result.stats, task.repo_path, model=model)
        raise WorkAborted(result) from aborted

    # Outcome flags + honest status (#106 t5 + colleague#142 + colleague#192):
    # derived from the _work_loop return. We are in the non-aborted path here, so
    # WorkAborted is not raised — that is a different signal and the flags are left
    # False for it (the default covers it above). Two orthogonal non-clean exits:
    #   * not_finished           — step budget exhausted without finishing (#106 t5).
    #   * stopped_without_finish — the model ended on a no-tool-call turn and, even
    #     after the nudge cap, never called finish (colleague#142); a caller must
    #     treat the result as a partial, not authoritative.
    # A clean finish leaves both False + status OK; any other outcome is INCOMPLETE;
    # a pilot's cooperative stop is a partial too. Do NOT derive either flag from
    # stats.step_count: max_steps bounds model *turns* while step_count counts *tool
    # calls*. (Flags + status set in the helper to keep run() under the S3776
    # cognitive-complexity threshold.)
    _apply_outcome_flags(result, outcome, _last_sub)

    # Summary precedence (t2 #109 + #191 + auto-compact-on-finish t3 + Qodo PR #198) —
    # RESOLVED BEFORE the not-finished escalation below so build_continuation() sees
    # the finalized summary, not an empty placeholder (Qodo #114). The ordered
    # precedence (finish summary > fresh forced synthesis > compaction self-summary
    # fallback > last-substantive > NO_RESULT_PRODUCED sentinel) lives in
    # _resolve_terminal_summary — extracted so run() stays under the S3776 threshold
    # and so synthesis runs BEFORE the compaction fallback (the stale-summary fix).
    _resolve_terminal_summary(ctx, outcome, complete, _last_sub)

    # Escalation seam — not-finished path (#106 t3): step budget exhausted without
    # calling finish.  Runs AFTER summary resolution (above) so the continuation
    # record carries the real output.  Best-effort and observe-only; suppress so
    # it cannot mask the work item result.
    if result.not_finished:
        with suppress(Exception):
            _escalation.escalate(result, result.stats, task.repo_path, model=model)
    return result
