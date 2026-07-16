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
import os
import re as _re
import shlex
import sys
import time
from collections import Counter
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from colleague import affectedtests as _affectedtests
from colleague import autosplit as _autosplit
from colleague import backpressure
from colleague import coherence as _coherencemod
from colleague import escalation as _escalation
from colleague import fillline as _fillline
from colleague import flight as flightmod
from colleague import lint as _lint
from colleague import media
from colleague import memory as _memorymod
from colleague import testintegrity as _testintegrity
from colleague.capacity import assess_capacity
from colleague.chain import declared_capacity_handoff
from colleague.config import MAX_SUBAGENT_FANOUT
from colleague.context import (
    classify_degradable,
    count_tokens_chars,
    is_media_rejection,
    window_messages,
)
from colleague.contract import (
    DECISION_DENY,
    DECISION_REWRITE,
    ERROR,
    INCOMPLETE,
    NO_RESULT_PRODUCED,
    OK,
    CapacityDecision,
    ContextPacket,
    HookFiring,
    SensesBlock,
    SensesRecord,
    Step,
    Task,
    TaskResult,
)
from colleague.hooks import HookConfig, HookDecision, hook_approval_verdict, load_hooks, run_hook
from colleague.incompletion import classify_incompletion
from colleague.neighbours import NeighbourManager
from colleague.policy import Policy, load_policy
from colleague.roles import is_read_only
from colleague.selfknowledge import build_guide_index, build_self_facts, classify_selfknowledge
from colleague.telemetry import Telemetry, load_telemetry
from colleague.tools import ToolError, ToolExecutor, ToolOutcome, UnknownToolError
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
    "\n\n"
    "AgentFront surface (reflex). Before the FIRST real use of a CLI or tool you "
    "have not used before in this run, check its agent-facing surface first — run "
    "its learn / explain / --help / --json affordance (or an overview / usage verb) "
    "and read what it reports, THEN act on what you found instead of guessing its "
    "flags or output shape. A tool you have already used needs no re-probe. This is "
    "advisory and your own judgement; reading a surface is read-only — it never "
    "installs, approves, or trusts the tool."
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
_EXIT_TOOL_PROTOCOL = "tool_protocol"  # consecutive unknown-tool calls -> channel is broken (#321)

# Consecutive UnknownToolError steps tolerated before the loop stops the run as
# ``_EXIT_TOOL_PROTOCOL`` (#321). Three failed self-corrections (each fed back the
# valid-tool list) is decisive evidence the tool-call channel itself is broken —
# e.g. a serving-side --tool-call-parser / template mismatch (#320) — and every
# further turn would burn budget on calls that can never exist. Operators tune the
# cap with ``COLLEAGUE_MAX_UNKNOWN_TOOL`` (int >= 1; a missing or invalid value
# falls back here) — read per-check by ``_unknown_tool_cap``.
_UNKNOWN_TOOL_STREAK_CAP = 3

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
# Thin-finish synthesis (#248 mode A): the model *called* finish after a read-heavy,
# zero-write run but its summary is only a headline (the observed 130k-token run
# that returned one sentence — the completion budget went to tool-call args). The
# empty-finish guard (#202) misses it because the summary is non-empty, so the
# forced-synthesis path also fires on a THIN finish, with a prompt that names the
# failure. Thresholds are deliberately conservative: a short summary is legitimate
# for a run that wrote files ("wrote out.txt"), so the trigger requires many steps
# AND zero write/edit calls — the findings-run signature.
_THIN_FINISH_CHARS = 160
_THIN_FINISH_MIN_STEPS = 8
_THIN_FINISH_PROMPT = (
    "Your `finish` summary was only a headline, but for a read-heavy run the summary "
    "IS the deliverable. Write the complete findings NOW from what you actually read — "
    "specific and self-contained (files, behaviors, conclusions). Do not request any "
    "more tools; reply with the findings themselves as plain text."
)
# Meta-description finish (#231): the model *called* finish after a read-heavy,
# zero-write run with a summary that DESCRIBES a report ("Report covers all three
# features with file:line references…") that is nowhere in the return value — the
# observed run d0c20c8c2e54 shape. Too long for the thin guard, so a pattern match
# catches the claim-of-coverage language; the length cap keeps a real (long) report
# that merely *says* "analysis complete" out of reach, and the read-heavy/zero-write
# gate (shared with the thin guard) protects write-run summaries.
_META_FINISH_CHARS = 600
_META_FINISH_RE = _re.compile(
    r"\b(report|analysis|review|summary|findings|writeup|write-up)\b[^.]{0,80}?"
    r"\b(covers|includes|contains|provides|documents)\b"
    r"|\b(reconnaissance|analysis|review|survey|investigation|exploration)\s+complete\b"
    r"|\bsee (the )?(full )?(report|analysis|findings)\b",
    _re.IGNORECASE,
)
_META_FINISH_PROMPT = (
    "Your `finish` summary DESCRIBED a report but did not include it — the summary IS "
    "the deliverable, and a description of findings is not the findings. Write the "
    "report itself NOW from what you actually read: the concrete findings, file "
    "references, and conclusions you promised. Do not request any more tools; reply "
    "with the report as plain text."
)

# Literal finish-markup recovery (#248 mode B): a served model sometimes emits its
# finish as literal tool-call MARKUP inside message content (observed shape below,
# including a mangled ``function=finish>`` missing its ``<``) instead of a structured
# tool call. The report exists — only the transport failed — so the loop re-parses
# that shape and treats it as the finish payload instead of losing it to the
# nudge/stop path. Tolerant by design: optional ``<tool_call>`` wrapper, optional
# ``<`` on the function tag, summary = everything between ``<parameter=summary>``
# and the next ``</parameter>``. Parsed with linear ``str.find`` scans (not a
# regex) so a large adversarial content string cannot trigger super-linear
# backtracking (SonarCloud S8786).
#
#   <tool_call>
#   function=finish>
#   <parameter=summary>
#   ...the full report...
#   </parameter>
#   </function>
#   </tool_call>
_SUMMARY_OPEN = "<parameter=summary>"
_SUMMARY_CLOSE = "</parameter>"


def _parse_literal_finish(content: str) -> str | None:
    """Recover a finish summary from literal tool-call markup in message content.

    Returns the summary text, or ``None`` when the content is ordinary prose (the
    cheap substring guards keep the scan off the hot path). #248 mode B.
    """
    marker = content.find("function=finish")
    if marker == -1:
        return None
    start = content.find(_SUMMARY_OPEN, marker)
    if start == -1:
        return None
    start += len(_SUMMARY_OPEN)
    end = content.find(_SUMMARY_CLOSE, start)
    if end == -1:
        return None
    return content[start:end].strip() or None


# Markup-shaped synthesis guard (#264): the forced-synthesis turn's OWN output can
# itself be literal tool-call markup (the same served-model failure mode #248
# recovers for `finish`) — used verbatim it garbles the terminal summary (live:
# work item 55859cb1d605). The guard detects the markup shape, retries ONCE with
# an explicit plain-prose instruction (the bounded-retry precedent of
# `_final_degraded_attempt`; stays on the MAIN model like every synthesis turn),
# and otherwise salvages the prose prefix before the first marker; when nothing
# substantive survives, the summary is left unset so `_resolve_terminal_summary`
# falls through to its next rung (compaction self-summary → last-substantive).
# Markers are LINE-ANCHORED (a marker mid-sentence is prose *about* markup, not
# markup — this repo's own docs discuss these tokens) and scanned with linear
# `str.find` (no regex — SonarCloud S8786).
_TOOL_MARKUP_MARKERS = (
    "<tool_call",
    "</tool_call>",
    "<parameter=",
    "</parameter>",
    "</function>",
)
_MARKUP_SALVAGE_CHARS = 80
_MARKUP_SYNTHESIS_PROMPT = (
    "Your reply was tool-call markup, but there are no tools on this turn — markup "
    "is ignored. Reply again NOW with the answer itself as plain prose only: no "
    "<tool_call>, no <parameter=...> syntax, just the findings/summary text."
)


def _strip_tool_markup(text: str) -> str:
    """Return *text* truncated at the first line-anchored tool-markup marker.

    Returns the stripped input unchanged when no marker starts a line — the
    cheap substring scans keep this off the hot path (#264).
    """
    cut = len(text)
    for marker in _TOOL_MARKUP_MARKERS:
        start = 0
        while True:
            idx = text.find(marker, start)
            if idx == -1 or idx >= cut:
                break
            if idx == 0 or text[idx - 1] == "\n":
                cut = idx
                break
            start = idx + 1
    return text[:cut].strip()


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
    # The resolved cortex (main) model id, threaded from ``run(model=…)`` by every
    # backend (all-engines rule). Read only by the self-knowledge advisory (t9) to
    # render the ``cortex:`` self-fact; ``""`` (a direct ``run`` caller that passed
    # no model) degrades that advisory to the guide index alone — never a fabricated
    # facts block. Not otherwise load-bearing, so ``""`` is byte-identical.
    model: str = ""
    # Self-knowledge facts plumbing (t9 / #306), threaded from the ContextControls
    # fields of the same names (see their contract there): the resolved senses
    # model id and the ARMED lobes gateway origin, so an armed session's facts
    # block renders the REAL values; ``""`` = genuinely absent → the honest
    # ``not configured``/``not armed`` lines. Read only by the self-knowledge
    # advisory — not otherwise load-bearing.
    senses_model: str = ""
    lobes_gateway: str = ""
    # Proactive context-window management (t4): when ``context_budget`` is a
    # positive int the running history is trimmed to it (via ``count_tokens``,
    # defaulting to the char estimate in ``window_messages``) before each turn,
    # and a context-overflow from ``complete`` triggers a bounded shrink-and-retry.
    # ``None`` (the default) is a strict no-op — no windowing, no reactive retry.
    context_budget: int | None = None
    count_tokens: Callable[[list[dict[str, Any]]], int] | None = None
    # Dual-model deepthink escalation seam (t5): the bound ``DeepthinkRun`` from
    # ContextControls, ``None`` for a single-model run (escalation points dormant).
    deepthink_run: Callable[..., Any] | None = None
    # Media-comprehension bridge (t8, c24): armed only when the operator declared
    # the SECOND model multimodal (deepthink.multimodal). False = strict no-op.
    media_bridge: bool = False
    # Cortex/senses media bridge (t6): the bound ``SensesRun`` seam
    # (:func:`colleague.senses.make_senses_run`), ``None`` when no senses config is
    # present. ``senses_media_bridge`` arms it — True only when the operator
    # declared the senses model multimodal (config.senses.multimodal). When armed
    # it is PREFERRED over the deepthink bridge (bridge point recorded under
    # ``TaskResult.senses``); absent → the deepthink path is byte-identical.
    senses_run: Callable[..., Any] | None = None
    senses_media_bridge: bool = False
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
    # (the ``_split_recommended`` pattern) holding PER-CROSSING state (indefinite-run
    # t1, superseding v1's at-most-once-per-work-item): the decision is offered +
    # recorded once per crossing, and ``_maybe_offer_fillline`` clears the cells once
    # the declaration is consumed AND the run drops back under the line, re-arming
    # the next crossing.
    capacity_threshold: float | None = None
    # Continuation chaining armed (indefinite-run t2, decision c23), threaded from
    # ``ContextControls.chain_armed``: read ONLY by the unrepairable-compaction-note
    # policy (:func:`_reject_compaction`) — armed routes an empty compaction note to
    # FINISH-WITH-HANDOFF; unarmed (the default) keeps the lossy-windowing floor.
    chain_armed: bool = False
    # Chain-episode gate deferral (#335, c8/c10): ``chain_episode`` marks THIS run
    # as one dispatched episode of an armed ``--until-done`` chain (threaded from
    # ``ContextControls.chain_episode`` — dispatch-keyed, never derived from
    # ``until_done``/``chain_armed``, so a subagent child or a plain armed run
    # never carries it, c22). On a continuation-shaped exit
    # (:func:`_gates_deferred_to_chain`) the four pre-finish gates are deferred to
    # the chain's FINAL episode instead of grading an intermediate tree the next
    # episode immediately rewrites. ``chain_prior_changed`` is the accumulated
    # union of every PRIOR episode's changed files (from
    # ``ContextControls.chain_prior_changed``) the final episode's gates union in
    # (:func:`_gate_changed_set`, c23); ``()`` — a non-chained run or the chain's
    # first episode — is byte-identical to today.
    chain_episode: bool = False
    chain_prior_changed: tuple[str, ...] = ()
    # Single-element fired-once cell (the ``_fillline_capped`` pattern) guarding
    # the deferral note against a double append — recorded ONCE per episode.
    _gate_deferral_noted: list[bool] = field(default_factory=list)
    # Same pattern for the union dropped-paths note (#342): _gate_changed_set is
    # called by all four gates (up to twice each), the note records ONCE.
    _gate_drop_noted: list[bool] = field(default_factory=list)
    _fillline_offered: list[bool] = field(default_factory=list)
    _fillline_resolved: list[bool] = field(default_factory=list)
    # The prompt-token count that tripped the fill line — captured when the decision
    # is OFFERED so the recorded reason matches the number named in the prompt (not
    # the slightly different count of the declaring turn). Cleared with the re-arm so
    # each crossing's decision records its own numbers.
    _fillline_used: list[int] = field(default_factory=list)
    # Per-run compaction cap (indefinite-run t1, resolved knob #334):
    # ``_fillline_compactions`` is a counted cell ([n], the ``_unknown_tool_streak``
    # pattern) tallying compaction turns; at ``compaction_cap`` (threaded from
    # ``ContextControls.compaction_cap`` / ``EngineConfig.compaction_cap``, falling
    # back to ``fillline.DEFAULT_COMPACTION_CAP`` when unset — a direct ``run`` caller
    # with no config) further offers are suppressed (anti-thrash — lossy windowing
    # remains the floor). ``_fillline_capped`` marks the suppression recorded once on
    # the trace (never re-noted per crossing).
    _fillline_compactions: list[int] = field(default_factory=list)
    _fillline_capped: list[bool] = field(default_factory=list)
    compaction_cap: int | None = None
    # Mapping fan-out advisory (#188): ``mapping_fanout_files`` is the files-read count
    # at which the runtime injects ONE advisory recommendation to fan a wide read-only
    # survey out across folders via the ``subagents`` tool (instead of grinding serially
    # through the step budget). ``None``/<= 0 leaves it dormant — a strict no-op.
    # ``_mapping_fanout_offered`` is a single-element mutable cell (the
    # ``_fillline_offered`` pattern) so the advisory fires at most once per work item.
    mapping_fanout_files: int | None = None
    _mapping_fanout_offered: list[bool] = field(default_factory=list)
    # Review fan-out advisory (#220b): the distinct-folders-read count at which a
    # review run is nudged ONCE to fan out per-folder read-only ``reviewer`` subagents
    # via the ``subagents`` tool. ``None``/<= 0 leaves it dormant — a strict no-op, so
    # a normal run is byte-identical. ``_review_fanout_offered`` mirrors
    # ``_mapping_fanout_offered`` so the advisory fires at most once per work item.
    review_fanout_folders: int | None = None
    _review_fanout_offered: list[bool] = field(default_factory=list)
    # Plan-mode auto-trigger (#t8): the instruction-token threshold at/above which
    # the runtime injects ONE advisory recommendation to enter plan mode. ``None``/
    # <= 0 is dormant. ``_plan_offered`` is the single-element fired-once cell (the
    # ``_mapping_fanout_offered`` pattern) so the advisory fires at most once.
    plan_offer_tokens: int | None = None
    _plan_offered: list[bool] = field(default_factory=list)
    # Unknown-tool streak guard (#321): a mutable ``[count, last_name]`` cell (the
    # ``_last_substantive`` pattern). Consecutive :class:`UnknownToolError` steps
    # increment it; any step that reached a REAL tool (ok or not) resets it. At
    # ``_UNKNOWN_TOOL_STREAK_CAP`` the turn loop exits ``_EXIT_TOOL_PROTOCOL``
    # instead of burning the remaining budget on a broken tool-call channel.
    _unknown_tool_streak: list = field(default_factory=list)
    # continue-working: max consecutive no-tool-call nudges before the loop gives up
    # and stops (replaces the hardcoded ``_MAX_FINISH_NUDGES``). Forwarded by every
    # backend from ``config.max_continue_nudges`` (all-engines rule); falls back to
    # ``_MAX_FINISH_NUDGES`` when a ContextControls omits it (back-compat / no-op).
    max_continue_nudges: int = _MAX_FINISH_NUDGES
    # Adaptive compute backpressure (t6 / spec R2 / #255): ``request_timeout`` is the
    # caller's per-completion timeout (``config.timeout``) — the reference the rolling
    # per-turn wall-clock latency is classified against (``colleague.backpressure``).
    # ``None``/<= 0 leaves the feature dormant — a strict no-op (no timing, no shrink,
    # no throttle), so direct ``run`` callers are byte-identical. ``fanout_throttle``
    # is the state-driven subagent-concurrency setter built by
    # :func:`_make_fanout_throttle` (CLEAR restores the operator's configured width —
    # backpressure only ever *tightens*, never re-plans; the no-router scope line).
    # The trailing cells follow the ``_split_recommended`` mutable-cell pattern:
    # per-turn latencies, the current CLEAR/ARMED/ESCALATED state, and whether the
    # once-per-work-item advisory was recorded.
    request_timeout: float | None = None
    fanout_throttle: Callable[[str], None] | None = None
    # Bounded one-time request-timeout raise (#268): the backend-built escalator
    # (:func:`_make_timeout_escalator` via ``ContextControls.from_config``) that
    # doubles the engine's per-turn timeout ONCE per work item. ``None`` (direct
    # ``run`` callers) leaves the feature dormant — byte-identical behavior.
    escalate_timeout: Callable[[], float | None] | None = None
    # The raised per-turn timeout after a #268 escalation — a list cell because
    # ``_Work`` is frozen (the ``_turn_latencies``/``_backpressure_state``
    # precedent). Read through :func:`_effective_timeout` so backpressure
    # classification runs against the raised cap.
    _escalated_timeout: list[float] = field(default_factory=list)
    _turn_latencies: list[float] = field(default_factory=list)
    _backpressure_state: list[str] = field(default_factory=list)
    _backpressure_advised: list[bool] = field(default_factory=list)
    # Flight-control plane (the piloting feature): an armed ``FlightSession`` when the
    # task is a watchable flight (``task.watch``), else ``None`` — a strict no-op.
    # When set, the loop appends a live feed record per turn and reads the per-flight
    # control file at each turn boundary (cooperative ``stop`` + ``guidance``
    # injection). Runtime-owned, so every backend inherits it (the all-engines rule).
    flight: "flightmod.FlightSession | None" = None
    # #308 liveness: the model-turn budget (for the pilot's "step N/max" heartbeat
    # display) and a single-element mutable cell holding the loop's monotonic start
    # (set once the drive timing is captured), so ``_emit_phase`` can stamp a
    # heartbeat's elapsed against it. Both a strict no-op when ``flight`` is None.
    max_steps: int = 0
    _flight_started_monotonic: list[float] = field(default_factory=list)
    # Lint pre-finish gate (#200): ``lint_enabled`` arms the gate (run the repo's
    # configured linters on the changed files + auto-fix before handoff);
    # ``lint_fix_retries`` caps the bounded model fix-turn for residual violations
    # (0 = deterministic fixers only). Both default OFF so a direct ``run`` caller
    # (no ContextControls) is byte-identical; the backends forward ``config.lint`` /
    # ``config.lint_fix_retries`` (all-engines rule).
    lint_enabled: bool = False
    lint_fix_retries: int = 0
    # Coherence pre-finish gate (#294, colleague#291 S3): score the changed .md
    # files with the coherence CLI and record result.coherence_report. Advisory
    # + warn-only (no fix-turn); default OFF so a direct ``run`` caller is
    # byte-identical; the backends forward ``config.coherence`` (all-engines).
    coherence_enabled: bool = False
    # Memory-informed runtime (spec R1 / plan t2): recall-before + remember-after
    # via the eidetic CLI adapter. Armed only when True AND the repo has a
    # .eidetic/ store AND the CLI is installed (see _memory_armed) — otherwise a
    # strict no-op, byte-identical to the pre-memory loop.
    memory_enabled: bool = False
    memory_root: str | None = None
    # Embedder env overrides (S2, task t19): forwarded from
    # ``ContextControls.embed_env``; merged into the eidetic subprocess env by
    # ``colleague/memory.py`` (operator-set env vars always win). ``{}``
    # (the default) is a strict no-op — byte-identical to pre-S2 behavior.
    embed_env: dict[str, str] = field(default_factory=dict)
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
    # Affected-tests gate (#213): when ``affectedtests_enabled`` the runtime selects the
    # test files whose bounded-depth transitive import closure reaches a changed module
    # (or the explicit ``--test`` override), runs pytest on them, and records the
    # AffectedTestsReport on ``result.affected_tests_report``. Defaults OFF so a direct
    # ``run`` caller (no ContextControls) is byte-identical; the backends forward
    # ``config.affected_tests`` (all-engines rule). ``affectedtests_fix_retries`` caps the
    # bounded model fix-turn on failures (0 = detect-and-record only); depth/max_files
    # tune the scan; ``override`` is the explicit ``--test`` pytest-args selection.
    affectedtests_enabled: bool = False
    affectedtests_fix_retries: int = 0
    affectedtests_depth: int = 3
    affectedtests_max_files: int = 20
    affectedtests_override: "str | None" = None


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
    model: str = "",
) -> None:
    """Fill the work item-level :class:`WorkStats` fields known only at loop exit.

    The per-turn fields (``model_turns`` and the generated reasoning/answer sizes)
    are accumulated in :func:`_work_loop`; this fills the rest from the finished
    result + executor. Called on EVERY exit path (model finish / empty turn /
    budget / mid-loop abort) so a partial drive still gets populated stats.

    ``engine``/``model`` make the ROI block self-describing (which mind ran it):
    ``engine`` is ``task.engine``; ``model`` is the id the engine was configured
    to call (threaded from :func:`run`'s ``model`` param, ``""`` when not given).
    """
    stats = result.stats
    stats.request = task.instruction
    stats.engine = task.engine
    stats.model = model
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
    step_index = len(ctx.result.steps)  # live count; stats.step_count is 0 until finalize
    # #308: fold the phase notice onto the FLIGHT FEED too (not just the stderr /
    # cockpit sinks), so `colleague talk` / senses grounding / `flight status` have
    # a liveness signal during a long completion instead of an empty feed. A
    # ``type="heartbeat"`` record — it NEVER advances step_count and is filtered out
    # of the step-only tui replay/snapshot (a different sink). Strict no-op when not
    # a watchable flight; suppressed like every observability write.
    if ctx.flight is not None:
        started = ctx._flight_started_monotonic
        elapsed = (time.monotonic() - started[0]) if started else 0.0
        with suppress(Exception):
            ctx.flight.append_heartbeat(
                phase=detail, elapsed=elapsed, step_index=step_index, max_steps=ctx.max_steps
            )
    if ctx.progress is None:
        return
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
        except (ToolError, KeyError, TypeError, ValueError) as exc:
            # ToolError is the tools' own contract. KeyError/TypeError/ValueError
            # are the argument-shaped residue of a malformed MODEL tool call that
            # slipped past per-tool validation (live: work item 4c6a96107269 died
            # mid-run on a bare KeyError('path') the old ToolError-only catch let
            # escape as an engine failure). Either way it costs ONE non-ok step
            # with a self-correcting message — never the run. Anything else
            # (AttributeError, OSError, …) is a genuine harness bug and still
            # aborts loudly.
            msg = (
                str(exc)
                if isinstance(exc, ToolError)
                else f"bad tool arguments: {type(exc).__name__}: {exc}"
            )
            _track_unknown_tool(ctx, call.name, exc)
            span.set(ok=False, error=msg)
            ctx.result.steps.append(
                Step(step_index, call.name, arguments, f"error: {msg}", ok=False)
            )
            ctx.messages.append(_tool_message(call.id, f"error: {msg}"))
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

        _track_unknown_tool(ctx, call.name, None)
        span.set(ok=True, bytes=len(outcome.result), changed_file=outcome.changed_file)
        ctx.result.steps.append(Step(step_index, call.name, arguments, outcome.result, ok=True))
        ctx.messages.append(_tool_message(call.id, outcome.result))
        if outcome.media_part is not None:
            # view_media fold (t5): the tool message above stays a plain string
            # (the wire-safe convention); the image itself rides a follow-up
            # user parts message the next turn sees.
            ctx.messages.append(
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": f"[{call.name}] {outcome.result}"},
                        outcome.media_part,
                    ],
                }
            )
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


def _track_unknown_tool(ctx: _Work, name: str, exc: Exception | None) -> None:
    """Advance or reset the unknown-tool streak cell (#321).

    ``exc`` is the failure the call raised — an :class:`UnknownToolError` extends
    the streak; anything else (including ``None``, a call that reached a real
    tool) resets it, because a real dispatch proves the protocol still works.
    """
    cell = ctx._unknown_tool_streak
    if isinstance(exc, UnknownToolError):
        if cell:
            cell[0] += 1
            cell[1] = name
        else:
            cell.extend([1, name])
    elif cell:
        cell[0] = 0


def _unknown_tool_cap() -> int:
    """Operator-tunable unknown-tool streak cap (#321).

    ``COLLEAGUE_MAX_UNKNOWN_TOOL`` overrides ``_UNKNOWN_TOOL_STREAK_CAP`` when it
    parses as an int >= 1; a missing or invalid value falls back to the default,
    so an unset environment stays byte-identical.
    """
    try:
        cap = int(os.environ.get("COLLEAGUE_MAX_UNKNOWN_TOOL", ""))
    except ValueError:
        return _UNKNOWN_TOOL_STREAK_CAP
    return cap if cap >= 1 else _UNKNOWN_TOOL_STREAK_CAP


def _tool_protocol_broken(ctx: _Work) -> bool:
    """True when the unknown-tool streak has hit the cap (#321)."""
    cell = ctx._unknown_tool_streak
    return bool(cell) and cell[0] >= _unknown_tool_cap()


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
    next action. Offered at most once per CROSSING via ``_fillline_offered``
    (re-armed by :func:`_maybe_offer_fillline` once a resolved crossing drops back
    under the line — indefinite-run t1).
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
    prompt size. With the per-crossing re-arm (indefinite-run t1) a run can declare
    more than once; the singular contract field keeps the LATEST declaration (the
    contract shape is unchanged here — earlier moves stay visible as their effects:
    compaction notes in the history, subagent results, usage).
    """
    budget = int(ctx.context_budget)
    used = ctx._fillline_used[0] if ctx._fillline_used else 0
    reason = f"context at {used} of {budget} budgeted tokens (fill line)"
    ctx.result.capacity_decision = CapacityDecision(kind=kind, reason=reason)
    ctx._fillline_resolved.append(True)


def _compact_history(ctx: _Work, complete: CompleteFn) -> None:
    """Compact the working history into a validated model-authored summary (#156, t2/c4).

    Runs ONE bounded summarization turn over the windowed history, cross-checks the
    note against the run's own evidence (goal/original request + changed-file paths —
    :func:`fillline.validate_compaction`, pure and deterministic: the MAIN model's
    summary only, no second-model call, non-goal c12), and replaces the working
    history (after the preserved head ``messages[:2]``) with the validated note, so
    the model continues from a compact note instead of losing older context silently.
    The summary turn is accounted like any other turn (counts against the step
    budget).

    Two floors, never an abort:

    - a *degradable* completion error (the summary turn itself cannot fit / timed
      out) → today's lossy windowing, unchanged;
    - an UNREPAIRABLE note (empty/whitespace, rejected by the validator — it never
      replaces history; the old ``(no summary produced)`` silent-amnesia placeholder
      is gone from this path, h4) → :func:`_reject_compaction` (armed:
      finish-with-handoff, decision c23; unarmed: the lossy-windowing floor).
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
    # Validate against the run's own evidence (t2, c4). Changed-file paths come from
    # the live ``executor.changed`` set — the same set the end-of-run
    # ``result.changed_files`` snapshot is taken from (mid-run the snapshot is still
    # empty, so the populated field is honoured first, then the live set).
    changed = ctx.result.changed_files or sorted(ctx.executor.changed)
    text, ok = _fillline.validate_compaction(
        resp.content, ctx.task.goal or ctx.task.instruction, changed
    )
    if not ok:
        _reject_compaction(ctx, budget)
        return
    ctx.messages[:] = _fillline.apply_compaction(ctx.messages, text)
    # auto-compact-on-finish (t3): preserve the compaction summary on its own cell so
    # it survives later turns and can serve as the FALLBACK clean summary at a
    # stop/budget exit when forced synthesis yields nothing (_resolve_terminal_summary).
    # The RAW model text, not the repaired note: the evidence block protects the
    # continuation context; the terminal-summary fallback stays byte-identical.
    if resp.content:
        ctx._compacted_summary[:] = [resp.content]


def _reject_compaction(ctx: _Work, budget: int) -> None:
    """Handle an UNREPAIRABLE (empty) compaction note — it never replaces history (c4/h4).

    Armed (``chain_armed`` — continuation chaining, decision c23): inject the
    deterministic FINISH-WITH-HANDOFF instruction as ONE user message, so the model
    finishes with a continuation summary the next episode resumes from (the per-turn
    windowing still bounds the next completion). Unarmed: keep today's
    lossy-windowing floor, exactly like the degradable-error fallback. Either way the
    rejection is announced as a phase notice (#206) — observable on the feeds, never
    silent, and a phase notice never advances ``step_count``.
    """
    move = (
        "taking finish-with-handoff (chaining armed)"
        if ctx.chain_armed
        else "lossy windowing remains the floor"
    )
    _emit_phase(
        ctx,
        f"compaction produced an empty summary — rejected (history not replaced); {move}",
    )
    if ctx.chain_armed:
        ctx.messages.append({"role": "user", "content": _fillline.build_handoff_instruction()})
        return
    _window_in_place(ctx, budget)


def _fillline_cap_reached(ctx: _Work) -> bool:
    """True when this run's compaction turns exhausted the per-run cap (t1).

    Reads the RESOLVED cap — ``ctx.compaction_cap`` (threaded from
    ``ContextControls.compaction_cap`` / ``EngineConfig.compaction_cap``, the
    operator-tunable knob landed by #334) — falling back to
    ``fillline.DEFAULT_COMPACTION_CAP`` when unset (a direct ``run`` caller with no
    config). ``cap_reached`` already treats ``cap <= 0`` as unlimited.
    """
    count = ctx._fillline_compactions[0] if ctx._fillline_compactions else 0
    cap = ctx.compaction_cap if ctx.compaction_cap is not None else _fillline.DEFAULT_COMPACTION_CAP
    return _fillline.cap_reached(count, cap)


def _record_fillline_cap(ctx: _Work) -> None:
    """Record ONCE that the compaction cap suppressed further fill-line offers (t1).

    Follows the backpressure-advisory precedent (:func:`_record_turn_latency`):
    append the note to ``result.capacity_warning`` (the artifact) and fire a phase
    notice (the stderr/cockpit/flight feeds), so the suppression is observable on
    the trace rather than silent. Lossy windowing remains the floor for the rest of
    the run. ``_fillline_capped`` guards the once — later capped crossings no-op.
    The note names the RESOLVED cap (``ctx.compaction_cap``, #334), falling back to
    ``fillline.DEFAULT_COMPACTION_CAP`` when unset, mirroring :func:`_fillline_cap_reached`.
    """
    if ctx._fillline_capped:
        return
    ctx._fillline_capped[:] = [True]
    cap = ctx.compaction_cap if ctx.compaction_cap is not None else _fillline.DEFAULT_COMPACTION_CAP
    note = (
        f"fill-line compaction cap reached ({cap} compaction turns this run) — "
        "no further capacity offers; lossy windowing remains the floor"
    )
    existing = ctx.result.capacity_warning
    ctx.result.capacity_warning = f"{existing}; {note}" if existing else note
    _emit_phase(ctx, note)


def _maybe_offer_fillline(ctx: _Work, last_prompt_tokens: int) -> None:
    """Offer the fill-line decision at each crossing of the line (#156, t1).

    Per-crossing, not once-per-run (indefinite-run t1 supersedes the v1 "fires at
    most once per work item" line): a RESOLVED offer re-arms once the run drops back
    under the line — a resolved-but-still-over boundary never immediately re-offers,
    because the declaring turn's own prompt is naturally still over the line — so a
    long run can compact repeatedly. Total compaction turns are bounded by the
    per-run cap: the cap reached = no further offers, recorded once on the trace
    (:func:`_record_fillline_cap`). A strict no-op when dormant (not armed), pending,
    or under the threshold — a work item that never fills its context is
    byte-identical to today.
    """
    if not _fillline_armed(ctx):
        return
    over = _fillline.crossed(
        last_prompt_tokens, int(ctx.context_budget), float(ctx.capacity_threshold)
    )
    if ctx._fillline_resolved and not over:
        # The declaration was consumed and the run dropped back under the line —
        # this crossing is spent. Clear the per-crossing cells so the NEXT crossing
        # offers again (clearing ``_fillline_used`` keeps the next decision's
        # recorded reason naming its own crossing's token count).
        ctx._fillline_offered.clear()
        ctx._fillline_resolved.clear()
        ctx._fillline_used.clear()
        return
    if ctx._fillline_offered or not over:
        return
    if _fillline_cap_reached(ctx):
        _record_fillline_cap(ctx)
        return
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


def _distinct_folders_read(ctx: _Work) -> int:
    """Count distinct parent folders among the ``read_file`` steps so far.

    The folder is the repo-relative posix dirname of each read path; a path with
    no ``/`` (a repo-root file) folds to the same ``""`` bucket. Used by the review
    fan-out advisory (#220b) to gauge how many folders the review has spread across.
    """
    folders: set[str] = set()
    for step in ctx.result.steps:
        if step.tool != "read_file":
            continue
        path = step.arguments.get("path")
        if not isinstance(path, str) or not path:
            continue
        folders.add(path.rsplit("/", 1)[0] if "/" in path else "")
    return len(folders)


def _maybe_offer_review_fanout(ctx: _Work) -> None:
    """Offer the per-folder review fan-out advisory once a review spans many folders (#220b).

    A strict no-op when dormant (``review_fanout_folders`` unset / <= 0), already
    offered, or the review has not yet read across more than the threshold of folders
    — so a normal run is byte-identical. Backend-judged + advisory: the loop injects
    ONE recommendation pointing at the existing ``subagents`` tool with the read-only
    ``reviewer`` role (no new fan-out/merge code) and the model decides whether to act.
    Offered at most once per work item via ``_review_fanout_offered``. Runtime-owned,
    so it fires identically for every backend (the all-engines rule).
    """
    threshold = ctx.review_fanout_folders
    if not isinstance(threshold, int) or threshold <= 0:
        return
    if ctx._review_fanout_offered:
        return
    folders = _distinct_folders_read(ctx)
    if folders <= threshold:
        return
    ctx.messages.append(
        {
            "role": "user",
            "content": _autosplit.build_review_fanout_recommendation(
                folders=folders, max_children=MAX_SUBAGENT_FANOUT - 1
            ),
        }
    )
    ctx._review_fanout_offered.append(True)


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
        # Count the compaction turn against the per-run cap (indefinite-run t1)
        # BEFORE running it: a compaction that falls back to lossy windowing (the
        # summary turn overflowed) still spent a model call, so it still counts.
        # Only compact declarations count — split/handoff moves are bounded by
        # their own machinery (subagent caps / the finish path).
        count = ctx._fillline_compactions[0] if ctx._fillline_compactions else 0
        ctx._fillline_compactions[:] = [count + 1]
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
    if signal == "timeout":
        # #268 ask 1: raise the per-turn timeout (bounded, once) BEFORE the retry
        # so the retry gets real headroom — a shrunken window alone cannot help
        # when the server itself is saturated (the observed irc-lens abort: both
        # attempts hit the same 120s wall). A no-op when already raised by the
        # proactive backpressure trigger or when no escalator is wired.
        _escalate_request_timeout(ctx, "a turn timeout")
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
        return _timed_complete(ctx, complete)
    except Exception as exc:  # noqa: BLE001
        # Carry the floor only on a degradable give-up, then re-raise either way.
        if classify_degradable(str(exc)) is not None:
            _remember_degraded_floor(ctx, effective)
        raise


def _effective_timeout(ctx: _Work) -> float | None:
    """The live per-turn timeout: the #268-escalated value when raised, else the
    configured one — so backpressure classifies against the cap actually in force."""
    return ctx._escalated_timeout[0] if ctx._escalated_timeout else ctx.request_timeout


def _current_backpressure(ctx: _Work) -> str:
    """The loop's current backpressure state (CLEAR when the feature is dormant)."""
    return ctx._backpressure_state[0] if ctx._backpressure_state else backpressure.CLEAR


def _timed_complete(ctx: _Work, complete: CompleteFn) -> ModelResponse:
    """Call ``complete`` measuring wall-clock latency for backpressure (t6/#255).

    Dormant (a plain call, no clock) unless ``ctx.request_timeout`` is a positive
    number. The latency is recorded in ``finally`` — a raising completion (above
    all a request TIMEOUT, which costs the full window) is precisely the slow
    turn the classifier must see.
    """
    if not ctx.request_timeout or ctx.request_timeout <= 0:
        return complete(ctx.messages)
    start = time.monotonic()
    try:
        return complete(ctx.messages)
    finally:
        _record_turn_latency(ctx, time.monotonic() - start)


def _record_turn_latency(ctx: _Work, seconds: float) -> None:
    """Fold one completion latency into the rolling backpressure classification.

    On a state TRANSITION the fan-out throttle (when wired) is retuned —
    ``throttled_concurrency`` maps CLEAR back to the operator's configured width,
    so recovery is automatic — and the first departure from CLEAR records a
    once-per-work-item advisory on ``result.capacity_warning`` (surfaced on
    stderr by the work CLI) plus a phase-notice line for live visibility.
    Advisory + tighten-only: never an error, never a different model/backend.
    """
    ctx._turn_latencies.append(seconds)
    previous = _current_backpressure(ctx)
    state = backpressure.assess(ctx._turn_latencies, float(_effective_timeout(ctx) or 0))
    ctx._backpressure_state[:] = [state]
    if state == previous:
        return
    if ctx.fanout_throttle is not None:
        with suppress(Exception):
            ctx.fanout_throttle(state)
    if state != backpressure.CLEAR and not ctx._backpressure_advised:
        ctx._backpressure_advised[:] = [True]
        note = (
            f"backpressure {state}: model turns are averaging "
            f"{sum(ctx._turn_latencies[-3:]) / len(ctx._turn_latencies[-3:]):.0f}s "
            f"toward the {(_effective_timeout(ctx) or 0):.0f}s request timeout — tightening the "
            f"context window (x{backpressure.shrink_fraction(state)}) and subagent "
            "fan-out until turns recover"
        )
        existing = ctx.result.capacity_warning
        ctx.result.capacity_warning = f"{existing}; {note}" if existing else note
        _emit_phase(ctx, note)
        # #268 ask 2: the harness saw the timeout coming — raise the per-turn
        # timeout NOW (bounded, once) instead of pushing "raise COLLEAGUE_TIMEOUT"
        # to the caller after the work is lost.
        _escalate_request_timeout(ctx, "turns drifting toward the request timeout")


def _escalate_request_timeout(ctx: _Work, trigger: str) -> str | None:
    """Bounded one-time raise of the engine's per-turn request timeout (#268).

    Fired from two places — the backpressure departure-from-CLEAR advisory
    (proactive) and a timeout-classified degraded retry (reactive) — whichever
    comes first; the escalator closure itself enforces once-per-work-item and
    the x2 bound (see :func:`_make_timeout_escalator`), so double-firing is
    structurally impossible. Updates ``ctx.request_timeout`` so subsequent
    backpressure classification runs against the raised cap, records the raise
    on ``result.capacity_warning`` (artifact-visible), and emits a phase notice
    (operator-visible). Returns the note, or ``None`` when dormant / already
    raised / nothing to raise. Best-effort: an escalator error never breaks the
    turn.
    """
    if ctx.escalate_timeout is None:
        return None
    try:
        raised = ctx.escalate_timeout()
    except Exception:  # noqa: BLE001 - advisory plumbing must never break a turn
        return None
    if not raised:
        return None
    ctx._escalated_timeout[:] = [raised]
    note = (
        f"request timeout raised to {raised:.0f}s after {trigger} "
        f"(bounded one-time x2 — cheaper than losing the flight)"
    )
    existing = ctx.result.capacity_warning
    ctx.result.capacity_warning = f"{existing}; {note}" if existing else note
    _emit_phase(ctx, note)
    return note


# Sentinel: a media-rejection flatten happened (#c7) — retry immediately, and
# this attempt must NOT count against the reactive retry cap (see
# :func:`_attempt_completion_or_retry_plan`).
_RETRY_IMMEDIATE = object()


def _attempt_completion_or_retry_plan(
    ctx: _Work,
    complete: CompleteFn,
    effective: int,
    saw_overflow: bool,
) -> tuple[ModelResponse | None, object]:
    """Run one reactive-retry-loop attempt; on failure, decide how to continue.

    Extracted from :func:`_complete_with_degradation` (SonarCloud S3776) so the
    loop's own body stays a flat dispatch. Returns ``(resp, None)`` on success.
    On a caught error, returns ``(None, _RETRY_IMMEDIATE)`` when
    :func:`_flatten_on_media_rejection` handled it (retry now, don't count
    against the attempt cap — structurally bounded since the flatten removes
    every part, so it cannot fire twice) or ``(None, plan)`` with the
    ``(new_effective, new_cap, new_saw_overflow)`` tuple from
    :func:`_plan_degraded_retry` to retry with the updated windowing state.
    Re-raises the original exception unchanged when :func:`_plan_degraded_retry`
    reports ``None`` (non-degradable, or the degradable floor was reached) —
    the give-up path, so :func:`run` preserves the partial.
    """
    try:
        return _timed_complete(ctx, complete), None
    except Exception as exc:  # noqa: BLE001
        if _flatten_on_media_rejection(ctx, exc):
            return None, _RETRY_IMMEDIATE
        plan = _plan_degraded_retry(ctx, exc, effective, saw_overflow)
        if plan is None:
            raise
        return None, plan


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

    The per-attempt failure handling (media-rejection flatten vs. classify-and-shrink)
    is delegated to :func:`_attempt_completion_or_retry_plan`; this function stays the
    orchestrator over the retry accounting (``effective``/``cap``/``saw_overflow``/
    ``attempt``).
    """
    # Phase notice (#206): announce the model turn is in flight BEFORE the (possibly
    # long) completion — fired here, the one chokepoint every model turn passes
    # through, so the notice reaches the operator whether or not the context-budget
    # feature is on. Observability only; a no-op without a progress sink.
    _emit_phase(ctx, phase)
    budget = ctx.context_budget
    if not isinstance(budget, int) or budget <= 0:
        # Feature off: strict pass-through, byte-identical to the pre-feature loop
        # (latency is still measured when backpressure is armed — the advisory +
        # fan-out throttle work without windowing; only the shrink needs a budget).
        # ONE exception (t9, c7): a media-refusing endpoint still degrades to a
        # text-only retry — that handling must not depend on the budget feature.
        try:
            return _timed_complete(ctx, complete)
        except Exception as exc:  # noqa: BLE001
            if _flatten_on_media_rejection(ctx, exc):
                return _timed_complete(ctx, complete)
            raise

    # Adaptive backpressure (t6/#255): under ARMED/ESCALATED the next turn's
    # window is proactively tightened — smaller prompts make faster turns, the
    # #229 move — composing with (never replacing) the reactive shrink-on-error.
    state = _current_backpressure(ctx)
    if state != backpressure.CLEAR:
        budget = max(1, int(budget * backpressure.shrink_fraction(state)))

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
        resp, plan = _attempt_completion_or_retry_plan(ctx, complete, effective, saw_overflow)
        if resp is not None:
            return resp
        if plan is _RETRY_IMMEDIATE:
            continue
        effective, cap, saw_overflow = plan
        attempt += 1
    return _final_degraded_attempt(ctx, complete, effective)


def _flatten_on_media_rejection(ctx: _Work, exc: Exception) -> bool:
    """Flatten every parts message and record the drop after a media-refusal (c7).

    Returns ``True`` when a retry should happen — the error matched
    :func:`colleague.context.is_media_rejection` AND at least one parts
    message existed to flatten (so the retry is structurally different).
    The task's attachments are recorded ``dropped`` (unless a bridge already
    preset the record) with a stderr warning naming the cause; the run
    continues text-only instead of hard-failing on an attachment the serving
    model cannot take.
    """
    if not is_media_rejection(str(exc)):
        return False
    had_parts = False
    for i, m in enumerate(ctx.messages):
        if isinstance(m.get("content"), list):
            ctx.messages[i] = dict(m, content=media.flatten_parts(m["content"]))
            had_parts = True
    if not had_parts:
        return False
    if ctx.task.attachments and ctx.result.media is None:
        ctx.result.media = {
            "attachments": [
                {"path": str(a.get("path", "?")), "status": _MEDIA_DROPPED}
                for a in ctx.task.attachments
                if isinstance(a, dict)
            ]
        }
    print(
        "warning: the serving endpoint rejected media content parts "
        f"({exc}) — retrying text-only with placeholders; media recorded "
        "dropped on the artifact",
        file=sys.stderr,
    )
    return True


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
    # Literal finish-markup recovery (#248 mode B): the "no-tool turn" may actually
    # BE the finish — the model emitted it as literal tool-call text in content.
    # Re-parse it as the finish payload instead of nudging a model that already
    # answered (the nudge/stop path would lose the report from the artifact).
    recovered = _parse_literal_finish(resp.content or "")
    if recovered is not None:
        ctx.result.summary = recovered
        ctx.result.finish_recovered = "literal-markup"
        return nudges, _EXIT_FINISHED
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
        _record_applied_injection(ctx, message)
    return bool(control.stop)


def _record_applied_injection(ctx: _Work, message: str) -> None:
    """Record ONE applied operator-to-cortex guidance injection (live-presence, t5).

    Every guidance message applied at a turn boundary — from the pilot
    (``colleague flight guide``) or the senses talk lane's relay — is made visible
    on BOTH the ephemeral feed and the durable artifact, so the operator's mid-run
    steering is reconstructable from feed + artifact alone (h8 awareness invariant).

    The #206 invariant holds: the feed line carries the CURRENT ``step_count`` and
    adds no step (its ``tool`` is ``None`` — an injection marker, not a tool step),
    and the ``SensesRecord``/``injections`` write never touches ``step_count``. The
    ``at`` timestamp is a wall-clock float, never estimated.
    """
    with suppress(Exception):
        ctx.flight.append_feed(
            step_index=ctx.result.stats.step_count,
            tool=None,
            intent=f"[guidance applied] {message}",
            stats=ctx.result.stats.to_dict(),
        )
    _record_senses_injection(ctx.result, {"text": message, "at": time.time(), "source": "guidance"})


def _fold_flight_chat(ctx: _Work) -> None:
    """Fold the talk-lane chat log into ``TaskResult.senses`` at finish (t5).

    Reads the flight chat JSONL (written by the talk-lane clients — ``colleague
    talk`` and the session concurrent lane) BEFORE the reap deletes it, and appends
    each exchange onto ``result.senses.chat`` so the operator's mid-run conversation
    survives in the artifact. A strict no-op when the work item was not a flight or
    no talk lane was used (``read_chat`` -> ``[]``), so a run with no live lane stays
    byte-identical. Never masks the task result.
    """
    if ctx.flight is None:
        return
    with suppress(Exception):
        records = flightmod.read_chat(_flight_repo_path(ctx.task), ctx.task.id)
        if records:
            _ensure_senses_block(ctx.result, mode="cortex-only").chat.extend(records)


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


def _flight_repo_path(task: Task) -> str:
    """Resolve WHERE the flight plane lives for this task (#310).

    ``task.flight_repo_path`` (the OPERATOR repo, set by ``_setup_isolation`` on
    an isolated run) when present, else ``task.repo_path`` (the pre-#310
    behaviour — the in-place session path, byte-identical). The single source of
    truth so the arm side (``_arm_flight``) and every read side
    (``_fold_flight_chat``, the ``FlightSession`` methods it hands back) resolve
    to the SAME directory the operator's ``colleague talk`` / ``colleague flight``
    read and write.
    """
    return task.flight_repo_path or task.repo_path


def _arm_flight(task: Task) -> "flightmod.FlightSession | None":
    """Arm the flight-control plane for a watchable work item, else ``None`` (no-op).

    Built from the existing ``task`` so :func:`run` needs no new parameter (it sits
    near the S107 ceiling); ``arm`` creates the empty feed so a pilot can attach.
    Armed at :func:`_flight_repo_path` (the operator repo on an isolated run, #310)
    so the plane the loop writes is the plane the operator reads.
    """
    return flightmod.arm(_flight_repo_path(task), task.id) if task.watch else None


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
    result.stopped_without_finish = outcome in (
        _EXIT_STOPPED,
        _EXIT_PILOT_STOP,
        _EXIT_TOOL_PROTOCOL,
    )
    if outcome != _EXIT_FINISHED:
        result.status = INCOMPLETE
    if outcome == _EXIT_PILOT_STOP:
        note = f"Stopped by pilot after {len(result.steps)} step(s) (partial)."
        result.summary = f"{note} {last_sub}".strip() if last_sub else note
    if outcome == _EXIT_TOOL_PROTOCOL:
        note = (
            f"Stopped after {len(result.steps)} step(s): the tool-call channel is "
            "broken — consecutive unknown-tool calls that never reached a real tool "
            "(see incompletion)."
        )
        result.summary = f"{note} {last_sub}".strip() if last_sub else note


# Bounded eidetic-CLI wait for the two in-loop memory calls (t2): a recall/remember
# must never stall the loop the way a full COLLEAGUE_TIMEOUT completion may.
_MEMORY_TIMEOUT = 15.0


def _memory_armed(ctx: _Work) -> bool:
    """Memory fires only when enabled AND the repo opted in by carrying a store.

    The store check is what keeps the default-ON flag safe: a tmp test repo (or
    any repo without ``.eidetic/``) never spawns the CLI — a strict no-op. CLI
    absence is handled inside :mod:`colleague.memory` (t1's contract).
    """
    if not ctx.memory_enabled:
        return False
    return (Path(_memory_repo(ctx)) / ".eidetic").is_dir()


def _memory_repo(ctx: _Work) -> str:
    """The durable store root: the operator repo for isolated runs (t2 fix).

    An isolated run's ``task.repo_path`` is a throwaway worktree that is reaped
    after handoff — a lesson written there would be silently lost (caught live
    on the first mock smoke run). ``execute_work`` threads the real root via
    ``config.memory_root``; the in-place session path falls back to the task's
    own repo.
    """
    return ctx.memory_root or ctx.task.repo_path


def _maybe_recall_memory(ctx: _Work) -> None:
    """Recall-before (spec R1 / plan t2): prior lessons as ONE advisory message.

    The query derives from the task's goal (when set) or the instruction head;
    the injected block is char-capped (``memory.RECALL_BLOCK_CAP`` — h7's
    token-cap without a tokenizer) and the whole exchange is recorded on
    ``TaskResult.memory`` so a misleading recall is diagnosable from the
    artifact (h7). Best-effort: any failure leaves the run untouched.
    """
    if not _memory_armed(ctx):
        return
    query = (ctx.task.goal or ctx.task.instruction or "").strip()[:200]
    try:
        records = _memorymod.recall(
            _memory_repo(ctx),
            query,
            top_k=5,
            timeout=_MEMORY_TIMEOUT,
            env_overrides=ctx.embed_env,
        )
    except Exception:  # noqa: BLE001
        # Advisory context only, never a precondition — a recall failure must
        # not block the run.
        return
    block = _memorymod.build_recall_block(records) if records else ""
    if block:
        ctx.messages.append({"role": "user", "content": block})
    ctx.result.memory = {
        "query": query,
        "recalled": len(records),
        "injected_chars": len(block),
    }


def _maybe_remember_lesson(ctx: _Work) -> None:
    """Remember-after (spec R1 / plan t2): one deterministic lesson per work item.

    Composed from the finished result's own facts (status, steps, tool counts,
    honesty markers) — no extra model turn. Idempotent: the record id derives
    from the task id, so a re-run upserts. An INCOMPLETE run is recorded too —
    failures are the most valuable lessons. Best-effort: a store failure never
    masks the work item result; the outcome lands on ``TaskResult.memory``.
    """
    if not _memory_armed(ctx):
        return
    result = ctx.result
    stats = result.stats
    instruction = (ctx.task.instruction or "").strip()
    request_head = instruction.splitlines()[0][:120] if instruction else ""
    tools = ", ".join(f"{k}={v}" for k, v in sorted(stats.tool_counts.items()))
    text = (
        f"Work item {result.task_id} finished {result.status} on request: "
        f"{request_head}. steps={stats.step_count}, tools=({tools}), "
        f"files_changed={len(result.changed_files)}."
    )
    signals = []
    if result.finish_recovered:
        signals.append(f"finish_recovered={result.finish_recovered}")
    if result.capacity_warning:
        signals.append("capacity_warning")
    if result.not_finished:
        signals.append("step budget exhausted")
    if result.stopped_without_finish:
        signals.append("stopped without finish")
    if signals:
        text += " Signals: " + "; ".join(signals) + "."
    record = _memorymod.build_lesson_record(
        result.task_id,
        text,
        {"topic": "colleague-work-lesson", "status": result.status},
    )
    recorded = False
    with suppress(Exception):
        recorded = _memorymod.remember(
            _memory_repo(ctx),
            record,
            timeout=_MEMORY_TIMEOUT,
            env_overrides=ctx.embed_env,
        )
    if result.memory is None:
        result.memory = {}
    result.memory["lesson_recorded"] = bool(recorded)


def _read_heavy_zero_write(ctx: _Work) -> bool:
    """The findings-run signature shared by the thin and meta finish guards.

    Many steps spent reading, nothing written — for such a run the summary IS
    the deliverable. A run that wrote/edited files legitimately finishes short
    ("wrote out.txt"), so any write disarms both triggers; so does a short run
    (few steps = little context worth synthesizing).
    """
    stats = ctx.result.stats
    if stats.step_count < _THIN_FINISH_MIN_STEPS:
        return False
    writes = stats.tool_counts.get("write_file", 0) + stats.tool_counts.get("edit_file", 0)
    return writes == 0


def _finish_recovery_reason(ctx: _Work) -> str | None:
    """Why a *called* finish still needs a synthesis turn, or ``None`` if it doesn't.

    - ``"thin"`` (#248 mode A): the summary is a bare headline (under
      ``_THIN_FINISH_CHARS``) after a read-heavy zero-write run.
    - ``"meta"`` (#231): the summary DESCRIBES a report (claim-of-coverage
      language) without containing it — under ``_META_FINISH_CHARS`` so a real
      long report that merely says "analysis complete" is never re-opened.
    """
    summary = (ctx.result.summary or "").strip()
    if not summary or not _read_heavy_zero_write(ctx):
        return None
    if len(summary) < _THIN_FINISH_CHARS:
        return "thin"
    if len(summary) < _META_FINISH_CHARS and _META_FINISH_RE.search(summary):
        return "meta"
    return None


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
    - **finish with a thin or meta summary** (#248 mode A / #231) — the summary is a
      bare headline, or *describes* a report it never contains, after a read-heavy
      zero-write run (:func:`_finish_recovery_reason`); recovered via a dedicated
      prompt and recorded on ``TaskResult.finish_recovered``.

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
    # Finish-recovery reasons (#248 mode A + #231): a *called* finish whose summary
    # is only a headline ("thin") or a description of an unwritten report ("meta")
    # after a read-heavy zero-write run — non-empty, so the #202 empty-finish guard
    # alone would skip both.
    reason = _finish_recovery_reason(ctx) if outcome == _EXIT_FINISHED else None
    if (ctx.result.summary and reason is None) or ctx.result.stats.step_count <= 0:
        return
    if reason == "thin":
        prompt = _THIN_FINISH_PROMPT
    elif reason == "meta":
        prompt = _META_FINISH_PROMPT
    elif outcome == _EXIT_FINISHED:
        prompt = _EMPTY_FINISH_PROMPT
    else:
        prompt = _SYNTHESIS_PROMPT
    ctx.messages.append({"role": "user", "content": prompt})
    try:
        # The synthesis turn is the worst case for #206: a single no-tools completion
        # that emits no step line, so a slow backend looks wedged. Announce it loudly.
        resp = _complete_with_degradation(ctx, complete, phase=_PHASE_SYNTHESIZING)
    except Exception:  # noqa: BLE001 - best-effort; a finalize-time turn never raises
        return
    _account_turn(ctx, resp)
    content, markup_recovered = _plain_prose_synthesis(ctx, complete, resp)
    if content:
        if reason is not None:
            # Honest degradation marker (#248/#231, h8): the artifact records that
            # the summary came from a recovery turn, not the model's own finish.
            ctx.result.finish_recovered = f"{reason}-finish-synthesis"
        elif markup_recovered:
            # Honest marker (#264): the synthesis turn itself emitted tool markup
            # and the summary came from the recovery pass, not the first output.
            ctx.result.finish_recovered = "markup-synthesis"
        ctx.result.summary = content


def _plain_prose_synthesis(
    ctx: _Work, complete: CompleteFn, first: ModelResponse
) -> tuple[str, bool]:
    """Return ``(content, recovered)`` — plain-prose text from a synthesis turn (#264).

    ``recovered`` is True when the first synthesis output was markup-contaminated
    and a recovery pass produced the returned content: ONE bounded plain-prose
    retry, else the prose prefix before the first marker when substantive
    (>= ``_MARKUP_SALVAGE_CHARS``). An empty return means nothing usable survived —
    the caller leaves the summary unset so ``_resolve_terminal_summary`` falls
    through to its next rung instead of shipping garbled markup as the deliverable.
    """
    content = (first.content or "").strip()
    prefix = _strip_tool_markup(content)
    if prefix == content:
        return content, False
    ctx.messages.append({"role": "assistant", "content": first.content})
    ctx.messages.append({"role": "user", "content": _MARKUP_SYNTHESIS_PROMPT})
    try:
        retry = _complete_with_degradation(ctx, complete, phase=_PHASE_SYNTHESIZING)
    except Exception:  # noqa: BLE001 - best-effort; salvage what the first turn had
        return (prefix if len(prefix) >= _MARKUP_SALVAGE_CHARS else ""), True
    _account_turn(ctx, retry)
    retry_content = (retry.content or "").strip()
    retry_prefix = _strip_tool_markup(retry_content)
    if retry_content and retry_prefix == retry_content:
        return retry_content, True
    best = retry_prefix if len(retry_prefix) > len(prefix) else prefix
    return (best if len(best) >= _MARKUP_SALVAGE_CHARS else ""), True


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


def _maybe_flag_incompletion(ctx: "_Work", outcome: str) -> None:
    """Honest-incompletion detector (colleague#313): a run that produced no
    expected deliverable comes back non-ok with an advisory
    {reason, evidence, recommendation}. Runtime-owned so every backend inherits
    it (all-engines); omit-when-None keeps a delivering run byte-identical.
    """
    result = ctx.result
    cell = ctx._unknown_tool_streak
    protocol_detail = ""
    if outcome == _EXIT_TOOL_PROTOCOL and cell:
        protocol_detail = (
            f"{cell[0]} consecutive unknown-tool call(s), last {cell[1]!r} — "
            "not one reached a real tool"
        )
    record = classify_incompletion(
        outcome=outcome,
        write_intent=not is_read_only(result.role),
        changed_files=len(result.changed_files),
        summary=result.summary or "",
        step_count=result.stats.step_count,
        protocol_detail=protocol_detail,
    )
    if record is None:
        return
    result.incompletion = record
    if result.status == OK:  # downgrade a clean-finish no-deliverable (the #313 core)
        result.status = INCOMPLETE


def _resolve_nudge_cap(context: "ContextControls") -> int:
    """The continue-working nudge cap (#142 + colleague PR #198).

    Defaults to ``_MAX_FINISH_NUDGES`` when a :class:`ContextControls` omits it
    (direct :func:`run` callers / back-compat). Extracted to keep ``run`` under the
    S3776 cognitive-complexity threshold.
    """
    cap = context.max_continue_nudges
    return cap if cap is not None else _MAX_FINISH_NUDGES


def _resolve_reading_budget(context: "ContextControls", max_steps: int) -> int:
    """The reading-step budget after the synthesis reserve (#197).

    Hold back ``context.synthesis_reserve`` steps from the reading budget so a
    read-heavy run stops reading early and the forced-synthesis verdict (#191)
    runs with fresher context. Clamped to leave at least one reading step; a
    0/``None`` reserve is byte-identical (the full budget is spent reading). The
    full ``max_steps`` is still what the partial-warning hint reports. Extracted
    to keep ``run`` under the S3776 cognitive-complexity threshold.
    """
    reserve = context.synthesis_reserve or 0
    if reserve > 0:
        return max(1, max_steps - reserve)
    return max_steps


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
        # Unknown-tool streak guard (#321): stop a run whose tool-call channel is
        # provably broken rather than re-burning the remaining budget on it.
        if _tool_protocol_broken(ctx):
            return _EXIT_TOOL_PROTOCOL
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
        # Review fan-out advisory (#220b): once a review has read across many folders,
        # nudge the model ONCE to fan out per-folder read-only `reviewer` subagents
        # rather than keep reading serially. No-op when dormant / already offered /
        # under the distinct-folders threshold.
        _maybe_offer_review_fanout(ctx)
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
        # Delivered-vs-dropped verification (t9, decision c25): classify the
        # task's attachments from the FIRST media-bearing completion's
        # token-contribution signal; a strict no-op afterwards and for
        # attachment-less runs.
        _maybe_record_media_delivery(ctx, resp)

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
    # Continuation chaining armed (indefinite-run t2, decision c23): governs ONLY the
    # unrepairable-compaction-note policy in :func:`_compact_history` — when True, an
    # empty compaction summary (rejected by ``fillline.validate_compaction``; it never
    # replaces history) routes the run to FINISH-WITH-HANDOFF: the loop injects the
    # deterministic handoff instruction so the model finishes with a continuation
    # summary the next episode resumes from. False (the default) keeps today's
    # lossy-windowing floor — dormant, byte-identical. The chain driver (t5) threads
    # ``config.until_done`` here; nothing sets it from ``from_config`` yet.
    chain_armed: bool = False
    # Chain-episode dispatch marker (indefinite-run follow-up, issue #335, decision
    # c22): ``True`` exactly when THIS run is one episode of an armed
    # ``--until-done`` chain — keyed on the chain option's PRESENCE at dispatch
    # (``EngineConfig.chain_episode``, set by ``execute_work`` from its
    # ``chain: ChainEpisodeOptions | None`` parameter), NEVER on
    # ``config.until_done``/``chain_armed`` above: a plain run with
    # ``until_done=True`` but no chain dispatch leaves this ``False``. A subagent
    # child of a chained episode never carries it (``run_subagent`` resets the
    # marker on the child config — c22). Consumed by the NEXT task (t6, the
    # gate-skip guard); dormant today — reading it changes nothing yet.
    chain_episode: bool = False
    # The UNION of every prior episode's ``result.changed_files`` (sorted,
    # deduped) an armed chain has accumulated so far — ``()`` on the chain's
    # first episode and for every non-chained run. Forwarded from
    # ``EngineConfig.chain_prior_changed`` alongside ``chain_episode`` above;
    # same t6 consumer, same dormant-today caveat.
    chain_prior_changed: tuple[str, ...] = ()
    # Per-run compaction-turn cap (indefinite-run follow-up, issue #334): bounds
    # how many fill-line ``compact`` moves a single run may spend before further
    # compaction offers are suppressed (:func:`_fillline_cap_reached` /
    # :func:`_record_fillline_cap`). ``None`` (the default — a direct ``run`` caller
    # with no config) falls back to ``fillline.DEFAULT_COMPACTION_CAP``, byte-identical
    # to pre-#334 behavior; ``cap_reached`` already treats ``<= 0`` as unlimited.
    # Forwarded by every backend from ``config.compaction_cap`` (all-engines rule).
    compaction_cap: int | None = None
    # Mapping fan-out advisory (#188): the files-read count at which the runtime
    # injects ONE advisory recommendation to fan a wide read-only survey out across
    # folders via the ``subagents`` tool. ``None``/<= 0 leaves it dormant — a strict
    # no-op. Forwarded by every backend from ``config.fanout_files`` (all-engines rule).
    fanout_files: int | None = None
    # Review fan-out advisory (#220b): the distinct-folders-read count at which a review
    # run is nudged to fan out per-folder read-only ``reviewer`` subagents. ``None`` =
    # dormant (strict no-op). Forwarded by every backend from
    # ``config.review_fanout_folders`` (all-engines rule).
    review_fanout_folders: int | None = None
    # Plan-mode auto-trigger (#t8): the instruction-token threshold at/above which a
    # normal work item injects ONE advisory recommendation to enter plan mode
    # (``colleague plan``). ``None``/<= 0 leaves it dormant — a strict no-op (opt-in).
    # Forwarded by every backend from ``config.plan_offer_tokens`` (all-engines rule).
    plan_offer_tokens: int | None = None
    # continue-working: max consecutive no-tool-call nudges before the loop gives up.
    # Forwarded by every backend from ``config.max_continue_nudges`` (all-engines
    # rule); ``None`` falls back to ``_MAX_FINISH_NUDGES`` (back-compat / strict no-op).
    max_continue_nudges: int | None = None
    # Adaptive compute backpressure (t6 / spec R2 / #255): ``request_timeout`` is the
    # per-completion timeout the rolling turn latency is classified against;
    # ``None``/<= 0 leaves backpressure dormant — a strict no-op. ``throttle_fanout``
    # is the state-driven concurrency setter from :func:`_make_fanout_throttle`.
    # Both forwarded by every backend via :meth:`from_config` (all-engines rule).
    request_timeout: float | None = None
    # compare=False: a fresh closure per from_config call — behavior, not
    # comparable config (the EngineConfig.role/spawn-callback precedent); the
    # all-engines guarantee comes from from_config being the single source.
    throttle_fanout: Callable[[str], None] | None = field(default=None, compare=False, repr=False)
    # Bounded one-time request-timeout raise (#268): built by
    # :func:`_make_timeout_escalator` in :meth:`from_config` (the all-engines
    # single source). ``None`` (direct ``run`` callers) = dormant, byte-identical.
    escalate_timeout: Callable[[], float | None] | None = field(
        default=None, compare=False, repr=False
    )
    # Dual-model deepthink escalation (t5 / spec c10): the bound ``DeepthinkRun``
    # seam (:func:`colleague.deepthink.make_deepthink_run`), ``None`` when no
    # dual-model config is present — the runtime escalation points (acceptance
    # self-check) stay dormant, a strict no-op (byte-identical single-model run).
    # Both backends pass ``make_deepthink_run(config, self.name)`` — the SAME
    # binding they inject into the tool executor (all-engines rule).
    # compare=False: a closure — behavior, not comparable config.
    deepthink_run: Callable[..., Any] | None = field(default=None, compare=False, repr=False)
    # Media-comprehension bridge arming (t8, c24): True only when the operator
    # declared the second model multimodal (config.deepthink.multimodal); set by
    # from_config for every backend identically (all-engines rule).
    media_bridge: bool = False
    # Cortex/senses media bridge (t6): the bound ``SensesRun`` seam every backend
    # passes as ``make_senses_run(config, self.name)`` (the deepthink_run precedent),
    # ``None`` for a config without senses. ``senses_media_bridge`` (derived in
    # from_config from config.senses.multimodal) arms it; when armed it is PREFERRED
    # over the deepthink bridge. compare=False: a closure, not comparable config.
    senses_run: Callable[..., Any] | None = field(default=None, compare=False, repr=False)
    senses_media_bridge: bool = False
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
    # Coherence pre-finish gate (#294, colleague#291 S3): when truthy the runtime
    # scores the work item's changed .md files via the coherence CLI and records
    # ``result.coherence_report``. Advisory + warn-only, never blocks the handoff.
    # ``None`` (the default) leaves the gate OFF for direct ``run`` callers;
    # every backend forwards ``config.coherence`` (all-engines rule).
    coherence: bool | None = None
    # Memory-informed runtime (spec R1 / plan t2): recall-before + remember-after.
    # ``None``/False = dormant (strict no-op). Forwarded by every backend from
    # ``config.memory`` (all-engines rule); the loop additionally requires the
    # repo to carry a .eidetic/ store, so test repos never spawn a subprocess.
    memory: bool | None = None
    # The durable repo root the memory store lives in (execute_work sets it to
    # the operator repo for isolated runs); ``None`` falls back to the task's
    # own repo_path (the in-place session path).
    memory_root: str | None = None
    # Embedder env overrides (S2, task t19): forwarded from ``config.embed_env``
    # (all-engines rule) so the loop's recall/remember calls can inject them
    # into the eidetic subprocess env without ever overwriting an operator-set
    # variable (see ``colleague/memory.py``). ``{}`` (the default) is a strict
    # no-op — byte-identical to pre-S2 behavior.
    embed_env: dict[str, str] = field(default_factory=dict)
    # Test-integrity gate (#203): when truthy (the default) the runtime runs the
    # mirror-detection heuristic on the changed files after the loop and records the
    # findings on ``result.test_integrity_report``. Advisory + non-blocking — never
    # blocks the handoff, makes no network call, and a no-finding run is byte-identical
    # (omit-when-None). Defaults ON so the gate fires for every backend without each
    # backend opting in; pass ``False`` to disable (the env/config opt-out feeds it).
    testintegrity: bool = True
    # Caps the bounded model re-examine turn for a flagged symbol (0 = detect-and-record
    # only, the conservative default). Forwarded by every backend from
    # ``config.testintegrity_fix_retries`` (all-engines rule).
    testintegrity_fix_retries: int = 0
    # The DIFFERENT model id for the diverse reviewer subagent (the robust guard). When
    # set, a flagged finding auto-spawns a reviewer on this model to independently
    # re-derive the real API shape; empty ("") degrades to record-only. Forwarded from
    # ``config.testintegrity_reviewer_model`` (all-engines rule).
    testintegrity_reviewer_model: str = ""
    # Typed-subagent role NAME this work item runs as (#t4). The engine forwards
    # ``config.role`` here so the loop can RECORD it on the result/trace (the curated
    # tool schema + role prompt + role-aware executor are built by the engine from
    # ``config.role``). ``None`` (the default) records nothing — byte-identical.
    role: str | None = None
    # Affected-tests gate (#213): when truthy the runtime selects + runs the tests whose
    # bounded-depth transitive import closure reaches a changed module and records an
    # AffectedTestsReport on ``result.affected_tests_report``. Advisory + non-blocking.
    # Defaults None (off) for a direct caller — byte-identical; the backends forward
    # ``config.affected_tests`` (all-engines rule). ``_override`` is the explicit
    # ``--test`` pytest selection; depth/max_files tune the scan.
    affectedtests: bool | None = None
    affectedtests_fix_retries: int | None = None
    affectedtests_depth: int | None = None
    affectedtests_max_files: int | None = None
    affectedtests_override: str | None = None
    # Self-knowledge facts plumbing (t9 / #306): the resolved senses model id
    # (``config.senses.model``) and the ARMED lobes gateway origin
    # (``config.lobes_gateway_url``, set by ``EngineConfig.resolve`` — ``None``
    # when unarmed OR degraded-unreachable, so it names the state the run
    # ACTUALLY resolved with). Read ONLY by the self-knowledge advisory so an
    # armed session renders the REAL senses id + gateway URL instead of a false
    # ``not configured``/``not armed``; ``""`` (the default — direct ``run``
    # callers, or genuinely absent) keeps the honest absent lines. Forwarded by
    # every backend via :meth:`from_config` (all-engines rule); not otherwise
    # load-bearing — byte-identical when empty.
    senses_model: str = ""
    lobes_gateway: str = ""

    @classmethod
    def from_config(
        cls, config, *, count_tokens=None, deepthink_run=None, senses_run=None
    ) -> "ContextControls":
        """Build the controls a backend forwards from its :class:`EngineConfig`.

        Every backend forwards the *same* config fields here (the all-engines
        rule), so this is the single source for that mapping — a backend that
        diverges is a bug. The only per-backend variation is ``count_tokens``:
        the vLLM backend passes its exact ``/tokenize`` counter; the mock (and any
        backend without one) leaves it ``None`` for the char-based estimate.
        ``deepthink_run`` is the bound dual-model escalation seam — every backend
        passes ``make_deepthink_run(config, self.name)`` (the same object it
        injects into the tool executor), or ``None`` for a single-model config.

        ``config`` is left untyped to avoid an import cycle with
        :mod:`colleague.config` (same precedent as :func:`resolve_role`).
        """
        return cls(
            budget=config.context_budget_tokens,
            count_tokens=count_tokens,
            autosplit_target=config.autosplit_target_tokens,
            fillline_threshold=config.fillline_threshold,
            fanout_files=config.fanout_files,
            review_fanout_folders=config.review_fanout_folders,
            plan_offer_tokens=config.plan_offer_tokens,
            max_continue_nudges=config.max_continue_nudges,
            synthesis_reserve=config.synthesis_reserve_steps,
            request_timeout=config.timeout,
            throttle_fanout=_make_fanout_throttle(config),
            escalate_timeout=_make_timeout_escalator(config),
            lint=config.lint,
            lint_fix_retries=config.lint_fix_retries,
            coherence=bool(getattr(config, "coherence", True)),
            memory=config.memory,
            memory_root=getattr(config, "memory_root", None),
            embed_env=dict(getattr(config, "embed_env", None) or {}),
            testintegrity=config.testintegrity,
            testintegrity_fix_retries=config.testintegrity_fix_retries,
            testintegrity_reviewer_model=config.testintegrity_reviewer_model,
            role=config.role,
            affectedtests=config.affected_tests,
            affectedtests_fix_retries=config.affected_tests_fix_retries,
            affectedtests_depth=config.affected_tests_depth,
            affectedtests_max_files=config.affected_tests_max_files,
            affectedtests_override=config.affected_tests_override,
            deepthink_run=deepthink_run,
            # Continuation chaining armed (decision c23): an armed invocation's
            # episodes prefer finish-with-handoff over the lossy-windowing floor
            # when a compaction note is unrepairable — the chain driver restarts
            # from the clean artifact seed. Threaded from the SAME resolved
            # ``until_done`` the chain loop arms on (t10's integration catch:
            # nothing set this before, leaving the armed branch unreachable).
            chain_armed=bool(getattr(config, "until_done", False)),
            # Chain-episode dispatch marker + accumulated changed files (#335,
            # c22): threaded from the runtime-only ``EngineConfig.chain_episode``
            # / ``chain_prior_changed`` execute_work sets PER-CALL from the
            # PRESENCE of its ``chain`` parameter — deliberately NOT derived from
            # ``config.until_done`` (that stays ``chain_armed`` above). ``getattr``
            # defaults keep a direct ``run()`` caller (no config, or a config
            # object predating this field) byte-identical.
            chain_episode=bool(getattr(config, "chain_episode", False)),
            chain_prior_changed=tuple(getattr(config, "chain_prior_changed", None) or ()),
            # Per-run compaction cap (#334): the same resolved value every backend
            # sees (``EngineConfig.compaction_cap``, env > config.json > the
            # fillline default) — the single source for the all-engines guarantee.
            compaction_cap=getattr(config, "compaction_cap", None),
            media_bridge=bool(
                config.deepthink is not None and getattr(config.deepthink, "multimodal", False)
            ),
            senses_run=senses_run,
            senses_media_bridge=bool(
                getattr(config, "senses", None) is not None
                and getattr(config.senses, "multimodal", False)
            ),
            # Self-knowledge facts (t9): the real senses id + armed gateway when
            # present; "" keeps build_self_facts' honest absent lines.
            senses_model=(
                getattr(config.senses, "model", "") or ""
                if getattr(config, "senses", None) is not None
                else ""
            ),
            lobes_gateway=getattr(config, "lobes_gateway_url", None) or "",
        )


def _make_timeout_escalator(config) -> Callable[[], float | None]:
    """Build the bounded one-time request-timeout raise bound to *config* (#268).

    Every backend's completion closure reads ``config.timeout`` per call (the
    vLLM adapter passes it to ``_post_json`` on each turn; mock ignores it), so
    raising it here takes effect on the very next attempt — including the
    degraded retry of the turn that just timed out. Bounded and once-only by
    construction: a single x2 raise per work item, never repeated, so the
    documented worst case on a genuinely dead server grows from
    ``2 x timeout`` to ``timeout + 2 x timeout`` and no further. Returns the
    raised value once, ``None`` on every later call or when no positive
    timeout is configured.

    **Escalation never compounds across work items (Qodo PR #271):** the raise
    mutates ``config.timeout`` in place, and that instance is shared — a
    subagent child config derives via ``dataclasses.replace(parent_config, …)``
    (copying the escalated value), and the session reuses one config across
    palette work items. So the first escalation records the operator's value on
    ``config.base_timeout``, and every escalator BUILD (this function runs once
    per work item, parent and child alike, via ``ContextControls.from_config``)
    restores ``config.timeout`` from it first. A child or follow-up work item
    therefore always starts at the operator's timeout and can raise to at most
    2x that — never 4x.
    """
    base = getattr(config, "base_timeout", None)
    if base is not None and base > 0:
        config.timeout = base
    done = [False]

    def escalate() -> float | None:
        if done[0]:
            return None
        current = getattr(config, "timeout", None)
        if not current or current <= 0:
            return None
        done[0] = True
        config.base_timeout = float(current)
        config.timeout = float(current) * 2
        return config.timeout

    return escalate


def _make_fanout_throttle(config) -> Callable[[str], None]:
    """Build the backpressure fan-out throttle bound to *config* (t6/#255).

    The returned setter maps a backpressure state onto
    ``config.subagent_concurrency`` via
    :func:`colleague.backpressure.throttled_concurrency`, closing over the
    operator's ORIGINAL configured width — so CLEAR restores it exactly and
    the throttle can only ever tighten below it, never exceed it. Mutating the
    config object retunes the already-bound batch-spawn closures (they read
    ``subagent_concurrency`` at call time). ``config`` stays untyped to avoid
    the import cycle with :mod:`colleague.config` (the ``from_config``/
    ``resolve_role`` precedent).
    """
    configured = int(getattr(config, "subagent_concurrency", 1) or 1)

    def throttle(state: str) -> None:
        config.subagent_concurrency = backpressure.throttled_concurrency(state, configured)

    return throttle


def resolve_role(config, repo_path: str):
    """Resolve ``config.role`` (a role NAME) to a :class:`~colleague.roles.Role`,
    or ``None`` when no role is set or the name is unknown (#t4).

    Runtime-owned so every backend types a child identically (all-engines rule):
    both bundled engines call this in ``work()`` to build the child's curated tool
    schema (``curate_schemas(role)``) and a role-aware ``ToolExecutor``
    (``allowlist=role``). ``None`` → the caller keeps its full-surface defaults,
    byte-identical to the pre-role contract. The role's PROMPT is composed
    separately by the role-aware :meth:`colleague.engine.Engine.system_prompt`.
    """
    name = getattr(config, "role", None)
    if not name:
        return None
    from colleague.roles import load_role

    return load_role(name, repo_path, config.model)


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
    # Goal block (t15 / spec R6 / #259): a task that declares its goal/acceptance
    # carries them as a DISTINCT block, so `finish` has a concrete target (#231)
    # instead of re-deriving intent from prose. Absent fields → byte-identical.
    if task.goal:
        user += f"\n\nGoal:\n{task.goal}"
    if task.acceptance:
        user += (
            "\n\nAcceptance criteria (the work is done when each of these holds):\n"
            + "\n".join(f"- {c}" for c in task.acceptance)
        )
    return user


def _build_initial_content(task: Task) -> "str | list[dict[str, Any]]":
    """The first user turn's content: a plain string, or content parts with media.

    With ``task.attachments`` empty/None this returns :func:`_build_user_message`'s
    string UNCHANGED — the h8 baseline: downstream string-assuming code
    (windowing, markup re-parse, fill-line) must never meet a surprise list on
    an attachment-less run. With attachments it returns OpenAI content parts:
    one text part carrying the full task prompt, then one part per attachment
    in order (:func:`colleague.media.build_part`). An attachment whose file
    became unreadable between surface validation and here degrades to a text
    placeholder naming the path — a broken attachment must never abort the run
    (the delivered/dropped verification is the honest record, task t9).
    """
    text = _build_user_message(task)
    if not task.attachments:
        return text
    parts: list[dict[str, Any]] = [{"type": "text", "text": text}]
    for attachment in task.attachments:
        try:
            parts.append(media.build_part(attachment))
        except (OSError, ValueError, KeyError) as exc:
            path = attachment.get("path", "?") if isinstance(attachment, dict) else "?"
            parts.append({"type": "text", "text": f"[attachment {path} unreadable: {exc}]"})
    return parts


#: Per-part token-contribution floor for the delivered/dropped classification
#: (t9): half the measured per-tile estimate — any REAL image contributes at
#: least one full tile (~260 tokens, live probe 2026-07-02), so a genuinely
#: tiny image still clears the floor, while a silent drop contributes ~0.
_MEDIA_DELIVERY_FLOOR = media.IMAGE_TOKEN_ESTIMATE // 2

_MEDIA_DELIVERED = "delivered"
_MEDIA_DROPPED = "dropped"
_MEDIA_UNKNOWN = "unknown"


def _classify_media_delivery(prompt_tokens: int, text_only_tokens: int, n_parts: int) -> str:
    """Classify media delivery from the token-contribution signal (t9, c25).

    ``delivered`` iff the prompt's reported tokens exceed the text-only
    estimate by at least the per-part floor — the exact signal the live
    silent-drop probe exposed (an image contributes hundreds of prompt
    tokens; a drop contributes ~0). A server that reported NO usage
    (``prompt_tokens <= 0`` — e.g. a scripted mock) classifies ``unknown``:
    a drop is never claimed without evidence. The word is DELIVERED, never
    "understood" — comprehension is claimed only by the livecheck proof.
    """
    if prompt_tokens <= 0:
        return _MEDIA_UNKNOWN
    if prompt_tokens - text_only_tokens >= _MEDIA_DELIVERY_FLOOR * max(1, n_parts):
        return _MEDIA_DELIVERED
    return _MEDIA_DROPPED


def _maybe_record_media_delivery(ctx: _Work, resp: ModelResponse) -> None:
    """Record the delivered/dropped verdict for the task's attachments (t9).

    Fires once, on the first completion after the media-bearing initial
    message; strict no-op with no attachments or once recorded. Zero extra
    model turns: the text-only baseline is counted locally (the exact counter
    when bound — flattened messages are all-string, so it can count them —
    else the char estimate) and compared against the server-reported
    ``prompt_tokens``. A drop warns on stderr and is recorded on
    ``TaskResult.media``; it never blocks or aborts the run.
    """
    if not ctx.task.attachments or ctx.result.media is not None:
        return
    flattened = [
        (
            dict(m, content=media.flatten_parts(m["content"]))
            if isinstance(m.get("content"), list)
            else m
        )
        for m in ctx.messages
    ]
    counter = ctx.count_tokens if ctx.count_tokens is not None else count_tokens_chars
    try:
        text_only = counter(flattened)
    except Exception:  # noqa: BLE001 - a counter failure must never abort the run
        text_only = count_tokens_chars(flattened)
    initial = ctx.messages[1].get("content") if len(ctx.messages) > 1 else None
    n_parts = (
        sum(
            1
            for p in initial
            if isinstance(p, dict) and p.get("type") in ("image_url", "input_audio")
        )
        if isinstance(initial, list)
        else len(ctx.task.attachments)
    )
    status = _classify_media_delivery(resp.prompt_tokens, text_only, n_parts)
    ctx.result.media = {
        "attachments": [
            {"path": str(a.get("path", "?")), "status": status}
            for a in ctx.task.attachments
            if isinstance(a, dict)
        ]
    }
    if status == _MEDIA_DROPPED:
        print(
            f"warning: {n_parts} media attachment(s) were NOT delivered to the "
            "model (prompt token contribution below the per-part floor) — "
            "recorded on the artifact's media key",
            file=sys.stderr,
        )


_POINT_MEDIA_BRIDGE = "media-bridge"

_MEDIA_BRIDGE_QUESTION = (
    "You are the multimodal half of a dual-model rig. The MAIN model "
    "driving this task is text-only and cannot see the attached media. "
    "Describe the attached media precisely and completely as it relates "
    "to the task below, so a text-only model can act on your description "
    "alone.\n\nTask:\n"
)

#: The advisory companion message injected when a task carries a senses
#: ContextPacket (t6). The operator's ORIGINAL text is already the first user
#: message (cortex reads it verbatim); this adds the senses interpretation as ONE
#: advisory turn — never a replacement (the recall-before precedent).
_CONTEXT_PACKET_ADVISORY = (
    "[senses] A senses model read the operator's request and interpreted it as "
    "follows. This is ADVISORY: the operator's original request above is "
    "authoritative and unmodified — defer to it on any disagreement.\n"
)


def _ensure_senses_block(
    result: TaskResult, *, mode: str = "split", packet: "ContextPacket | None" = None
) -> SensesBlock:
    """Init-on-first the ``TaskResult.senses`` block (the senses twin of the
    deepthink init in :func:`_record_deepthink`).

    A run with no senses involvement never calls this, so ``result.senses``
    stays ``None`` and the artifact key is omitted (byte-identical). The first
    caller sets ``mode``/``packet``; a later caller (e.g. the media bridge after
    the packet injection) keeps the existing block and only fills a still-absent
    packet, so mode/packet are never clobbered.
    """
    if result.senses is None:
        result.senses = SensesBlock(mode=mode, packet=packet, records=[])
    elif packet is not None and result.senses.packet is None:
        result.senses.packet = packet
    return result.senses


def _record_senses_call(
    result: TaskResult,
    record: SensesRecord,
    *,
    mode: str = "split",
    packet: "ContextPacket | None" = None,
) -> None:
    """Append one :class:`SensesRecord` to ``result.senses`` (init-on-first)."""
    _ensure_senses_block(result, mode=mode, packet=packet).records.append(record)


def _record_senses_injection(result: TaskResult, entry: dict, *, mode: str = "cortex-only") -> None:
    """Append one applied-injection entry to ``result.senses.injections`` (t5).

    Mode defaults to ``cortex-only`` for the fresh-block case (an operator relayed
    guidance into a cortex-only run); ``_ensure_senses_block`` keeps an existing
    block's mode (e.g. ``split`` when senses also ran intake), so mode is never
    clobbered. Init-on-first — a run with no injection never touches ``senses``.
    """
    _ensure_senses_block(result, mode=mode).injections.append(entry)


def _maybe_inject_context_packet(ctx: _Work) -> None:
    """Inject the senses :class:`ContextPacket` as ONE advisory companion (t6).

    When the task carries a ``context_packet`` (the session/resident ran senses
    intake), cortex's first user message is ALREADY the operator's verbatim
    original (``_build_user_message`` uses ``task.instruction``) — the packet
    never replaces it. This appends the senses model's interpretation as ONE
    advisory user message (the recall-before precedent) and records the packet on
    ``TaskResult.senses`` (mode ``split``). Strict no-op with no packet
    (byte-identical): ``result.senses`` stays ``None``.
    """
    packet = getattr(ctx.task, "context_packet", None)
    if packet is None:
        return
    lines = [_CONTEXT_PACKET_ADVISORY]
    if packet.interpretation:
        lines.append(f"Interpretation: {packet.interpretation}")
    if packet.task_type:
        lines.append(f"Task type: {packet.task_type}")
    if packet.confidence:
        lines.append(f"Confidence: {packet.confidence}")
    if packet.omissions:
        lines.append("Possible omissions: " + "; ".join(packet.omissions))
    ctx.messages.append({"role": "user", "content": "\n".join(lines)})
    _ensure_senses_block(ctx.result, mode="split", packet=packet)


#: The advisory companion injected before the first cortex turn when the
#: operator's message is a *self-knowledge* question (t9 / #306). Mirrors
#: ``_CONTEXT_PACKET_ADVISORY``: cortex's first user message is ALREADY the
#: operator's verbatim question — this ADDS the live guide index + resolved
#: self-facts as ONE advisory turn so cortex answers about colleague from the
#: repo's OWN docs + runtime state instead of guessing. ADVISORY, never a
#: replacement (the recall-before precedent).
_SELF_KNOWLEDGE_ADVISORY = (
    "[self-knowledge] The operator is asking about colleague itself. Answer from "
    "colleague's OWN live documentation and resolved runtime state below — open a "
    "listed guide with read_file for detail rather than guessing. This is ADVISORY: "
    "the operator's original question above is authoritative.\n"
)

#: Cap on the number of guide-doc paths folded into the self-knowledge advisory
#: (t9). ``build_guide_index`` returns CLAUDE.md (always first) + every
#: ``docs/features/*.md`` — a set that grows unbounded as feature docs accumulate.
#: Capping keeps the ONE advisory a small, fixed fraction of the context budget
#: (each entry is one short repo-relative path line, so N paths ≈ N lines) rather
#: than letting it scale with the doc count; cortex reads any FULL doc on demand
#: via ``read_file``, so the index only needs to name enough entry points (CLAUDE.md
#: is the master index, so it is always kept — it heads the list). Overflow is
#: reported honestly as a "… and N more" line, never silently dropped.
_SELF_KNOWLEDGE_GUIDE_CAP = 40


class _SensesFact:
    """The minimal ``senses``-shaped holder ``build_self_facts`` duck-reads (t9):
    it checks ``senses is not None and senses.model`` — this carries exactly that
    one attribute (the ``_StubSenses`` shape the selfknowledge unit tests pin)."""

    def __init__(self, model: str) -> None:
        self.model = model


class _SelfFactsSource:
    """Adapt ``_Work`` to the duck-typed surface :func:`build_self_facts` reads (t9).

    The loop does NOT hold a resolved :class:`~colleague.config.EngineConfig` — it
    takes a curated :class:`ContextControls` (the deliberate import-cycle boundary
    ``from_config``/``resolve_role`` also observe), so a full config is not cheaply
    reachable here. This exposes exactly what the loop DOES know under the attribute
    names ``build_self_facts`` expects: the cortex ``model`` id (threaded onto
    ``_Work.model``), the five gate booleans, and — when armed — the resolved senses
    model id (``ContextControls.senses_model`` → ``_Work.senses_model``), so an
    armed session renders the REAL id and only a genuinely absent one renders
    ``build_self_facts``'s honest ``not configured`` default (never a fabricated
    id, and never a false absent line when the value is present). The armed lobes
    gateway travels the same way (``_Work.lobes_gateway``) but is passed as
    ``build_self_facts``'s ``gateway_url=`` parameter by the caller, not exposed
    here.
    """

    def __init__(self, ctx: "_Work") -> None:
        self.model = ctx.model
        self.senses = _SensesFact(ctx.senses_model) if ctx.senses_model else None
        self.lint = ctx.lint_enabled
        self.testintegrity = ctx.testintegrity_enabled
        self.affected_tests = ctx.affectedtests_enabled
        self.memory = ctx.memory_enabled
        self.coherence = ctx.coherence_enabled


def _maybe_inject_self_knowledge(ctx: _Work) -> None:
    """Inject the guide index + resolved self-facts on a self-knowledge turn (t9 / #306).

    Mirrors :func:`_maybe_inject_context_packet` in shape, gating, and placement:
    cortex's first user message is ALREADY the operator's verbatim instruction
    (``_build_initial_content``) — this appends ONE advisory user message so cortex
    answers questions ABOUT colleague from the LIVE guide docs + resolved runtime
    state instead of guessing. Gated on the deterministic
    :func:`colleague.selfknowledge.classify_selfknowledge`; an ordinary
    (non-self-knowledge) instruction is a STRICT no-op — no guide index, no
    self-facts, no extra message — so the guide docs are loaded ONLY when a
    self-knowledge turn triggers them and an ordinary run is byte-identical (#306).

    Facts-block plumbing (honest both ways): the loop reaches the cortex model id
    (``_Work.model``), the five gate booleans, and — threaded through
    ``ContextControls.from_config`` by every backend (all-engines rule) — the
    resolved senses model id (``config.senses.model``) plus the ARMED lobes gateway
    origin (``config.lobes_gateway_url``, set by ``EngineConfig.resolve``); it does
    NOT hold the full :class:`~colleague.config.EngineConfig` (see
    :class:`_SelfFactsSource`). An armed session therefore renders the REAL senses
    id + gateway URL; only a genuinely absent value renders ``build_self_facts``'s
    honest ``not configured`` / ``not armed`` defaults — a present value must never
    render as absent (that would be a FALSE fact), and an absent one is never
    fabricated. When even the cortex model id is absent (a direct ``run`` caller
    that passed no ``model``) the facts block is dropped entirely and the guide
    index alone is injected — the task's honest-degradation clause: never a
    fabricated facts block.

    The #206 invariant holds: this appends a companion user message but never fires
    the progress sink or advances ``step_count`` (it runs before the loop body, like
    the packet/recall injections).
    """
    if not classify_selfknowledge(ctx.task.instruction or ""):
        return
    lines = [_SELF_KNOWLEDGE_ADVISORY]

    guides = build_guide_index(ctx.task.repo_path)
    if guides:
        shown = guides[:_SELF_KNOWLEDGE_GUIDE_CAP]
        lines.append("colleague guide docs (open one with read_file for detail):")
        lines.extend(f"- {path}" for path in shown)
        if len(guides) > len(shown):
            lines.append(f"- … and {len(guides) - len(shown)} more")

    # Facts block only when the cortex model id is genuinely known — never a
    # fabricated facts block (guide index alone otherwise). gateway_url carries
    # the ARMED lobes origin ("" → None → the honest "not armed" line).
    if ctx.model:
        lines.append("")
        lines.append("resolved runtime state:")
        lines.append(build_self_facts(_SelfFactsSource(ctx), gateway_url=ctx.lobes_gateway or None))

    ctx.messages.append({"role": "user", "content": "\n".join(lines)})


def _maybe_run_senses_media_bridge(ctx: _Work) -> bool:
    """Run the cortex/senses media bridge if armed + PREFERRED (t6).

    The senses-lobe twin of the deepthink bridge in :func:`_maybe_run_media_bridge`,
    and PREFERRED over it: when the operator declared the senses model multimodal
    (``senses_media_bridge``) the real media parts ride ONE tools-off completion to
    the senses endpoint (the text-only cortex wire is flattened first), the record
    lands on ``TaskResult.senses`` (never ``deepthink``), and the description folds
    back as ONE advisory user message. Returns ``True`` when it HANDLED the bridge
    (so the deepthink path is skipped — senses is preferred, a degraded senses run
    does NOT fall back to deepthink), ``False`` to fall through (not armed, or no
    media parts present) leaving the deepthink path byte-identical.
    """
    if not ctx.senses_media_bridge or ctx.senses_run is None or not ctx.task.attachments:
        return False
    initial = ctx.messages[1].get("content") if len(ctx.messages) > 1 else None
    if not isinstance(initial, list):
        return False
    parts = [
        p for p in initial if isinstance(p, dict) and p.get("type") in ("image_url", "input_audio")
    ]
    if not parts:
        return False
    # The cortex (main) wire is DECLARED text-only — flatten it so the parts ride
    # ONLY the senses escalation (the deepthink-bridge invariant, t6/c24).
    ctx.messages[1] = dict(ctx.messages[1], content=media.flatten_parts(initial))
    question = _MEDIA_BRIDGE_QUESTION + (ctx.task.instruction or "")
    text, record = ctx.senses_run(question, parts)
    _record_senses_call(ctx.result, record)
    if getattr(record, "degraded", False) or not (text or "").strip():
        # Degraded senses bridge: nothing folds; the (now text-only) cortex turn
        # proceeds. Senses is preferred — no deepthink fallback (handled=True).
        return True
    ctx.messages.append(
        {
            "role": "user",
            "content": "[media bridge] A multimodal senses model examined the attached "
            "media and reports:\n" + text,
        }
    )
    # Delivery record (c25 vocabulary): cortex saw placeholders, the description
    # was delivered via the senses model — recorded as "bridged", mirroring the
    # deepthink bridge (the t9 verifier skips a set record).
    ctx.result.media = {
        "attachments": [
            {"path": str(a.get("path", "?")), "status": "bridged"}
            for a in ctx.task.attachments
            if isinstance(a, dict)
        ]
    }
    return True


def _maybe_run_media_bridge(ctx: _Work) -> None:
    """Escalate attached media to the declared multimodal second model (t8, c24).

    Fires ONCE, before the first turn, and only when ALL of: the task carries
    attachments, a dual-model config is bound (``deepthink_run``), and the
    operator declared the second model multimodal (``media_bridge`` — never
    probed or inferred). The escalation is one bounded tools-off completion
    (``run_media_bridge`` via the binding's ``media_parts`` path); its
    description folds back as exactly ONE advisory user message. A degraded
    bridge records honestly on ``TaskResult.deepthink`` and folds nothing —
    the run continues from the text alone (h18: degrade, never raise; the
    delivered/dropped record is task t9's).

    Cortex/senses (t6): a declared multimodal SENSES config is PREFERRED — the
    senses bridge runs first and, when it handles the bridge, records under
    ``TaskResult.senses`` and returns before the deepthink path below. When only
    deepthink is declared the senses branch is a strict no-op and the deepthink
    path is byte-identical to v1.34.0.
    """
    if _maybe_run_senses_media_bridge(ctx):
        return
    if not ctx.media_bridge or ctx.deepthink_run is None or not ctx.task.attachments:
        return
    initial = ctx.messages[1].get("content") if len(ctx.messages) > 1 else None
    if not isinstance(initial, list):
        return
    parts = [
        p for p in initial if isinstance(p, dict) and p.get("type") in ("image_url", "input_audio")
    ]
    if not parts:
        return
    # The main model is DECLARED text-only (that is what armed the bridge), so
    # the parts must not ride its wire at all — a text-only vLLM endpoint
    # typically rejects image parts outright rather than dropping them. The
    # main wire gets the flattened text (placeholders); the REAL parts travel
    # only on the bridge escalation below (h12/h18 extended to the main wire).
    ctx.messages[1] = dict(ctx.messages[1], content=media.flatten_parts(initial))
    question = (
        "You are the multimodal half of a dual-model rig. The MAIN model "
        "driving this task is text-only and cannot see the attached media. "
        "Describe the attached media precisely and completely as it relates "
        "to the task below, so a text-only model can act on your description "
        "alone.\n\nTask:\n" + (ctx.task.instruction or "")
    )
    res = ctx.deepthink_run(question, "", point=_POINT_MEDIA_BRIDGE, media_parts=parts)
    call = getattr(res, "call", None)
    if call is not None:
        _record_deepthink(ctx.result, call)
    text = (getattr(res, "text", "") or "").strip()
    if call is not None and getattr(call, "degraded", False) or not text:
        # Degraded bridge: nothing folds; the media record stays unset so the
        # t9 verifier classifies the (now text-only) first completion honestly
        # — dropped with real usage, unknown without.
        return
    ctx.messages.append(
        {
            "role": "user",
            "content": "[media bridge] A multimodal model examined the attached "
            "media and reports:\n" + text,
        }
    )
    # Delivery record (c25 vocabulary + the bridge case): the MAIN model saw
    # placeholders, the description was delivered via the second model —
    # recorded as "bridged" (preset here; the t9 verifier skips a set record).
    ctx.result.media = {
        "attachments": [
            {"path": str(a.get("path", "?")), "status": "bridged"}
            for a in ctx.task.attachments
            if isinstance(a, dict)
        ]
    }


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


def _gates_deferred_to_chain(ctx: _Work, outcome: str, aborted: Exception | None) -> bool:
    """True when this chain episode's exit is continuation-shaped — defer the gates (#335).

    The continuation shape is derived from the SAME signals the chain driver
    continues on (colleague/chain.py, imported — not mirrored): the budget
    outcome (``should_continue``'s allow-list is exactly the budget-exhausted
    reason, c24) or a declared fill-line finish-with-handoff
    (:func:`colleague.chain.declared_capacity_handoff`, deviation d1/c23). The
    next episode rewrites this tree, so mid-chain gates would burn per-episode
    budget grading an intermediate state; the chain's FINAL (finish-shaped)
    episode runs them over the accumulated union instead
    (:func:`_gate_changed_set`). Three arms, each honest on its own:

    - ``aborted`` never defers: an error/timeout exit is a chain HALT (never in
      the allow-list) — and run()'s ``outcome`` still holds its pre-try
      ``budget`` initial value on that path, the trap this arm exists for;
    - ``chain_episode`` keys on the DISPATCH marker (c22): a subagent child or
      a plain ``until_done`` run without a chain dispatch gates as today;
    - a chain that then HALTS anyway (cap / no-progress) keeps the skip —
      spec'd, no backfill; the deferral note on the episode artifact stays the
      honest record.
    """
    if aborted is not None or not ctx.chain_episode:
        return False
    return outcome == _EXIT_BUDGET or declared_capacity_handoff(ctx.result)


def _record_gate_deferral(ctx: _Work) -> None:
    """Record ONCE per episode that the pre-finish gates were deferred (#335).

    The :func:`_record_fillline_cap` precedent: append the note to
    ``result.capacity_warning`` (the artifact) and fire a phase notice (the
    stderr/cockpit/flight feeds — never a step, so ``step_count`` is untouched),
    so the skip is observable on the trace rather than silent.
    ``_gate_deferral_noted`` guards the once.
    """
    if ctx._gate_deferral_noted:
        return
    ctx._gate_deferral_noted[:] = [True]
    # The STRUCTURED marker (#341): chain accounting and artifact consumers
    # read this typed flag, never string-match the prose note below.
    ctx.result.gates_deferred = True
    note = (
        "chain-armed continuation exit — pre-finish gates (lint/coherence/"
        "test-integrity/affected-tests) deferred to the chain's final episode (#335)"
    )
    existing = ctx.result.capacity_warning
    ctx.result.capacity_warning = f"{existing}; {note}" if existing else note
    _emit_phase(ctx, note)


def _gate_changed_set(ctx: _Work) -> list[str]:
    """The changed-set the four pre-finish gates grade (#335, c23).

    A non-chained run (and the chain's first episode) has an empty
    ``chain_prior_changed`` and gets EXACTLY today's set — ``sorted(
    ctx.executor.changed)``, no filter — byte-identical. A chained final
    episode gates over union(this episode's changed, the accumulated
    ``prior_changed``), filtered to paths that exist in the episode worktree:
    prior episodes' files reach it via the chain's tree carry, while a path a
    later episode deleted (or that never survived) must not feed a linter a
    missing file. What the filter removes is never silent (#342): the dropped
    paths are recorded ONCE on the artifact via
    :func:`_record_gate_dropped_paths`.
    """
    changed = sorted(ctx.executor.changed)
    if not ctx.chain_prior_changed:
        return changed
    union = set(changed) | set(ctx.chain_prior_changed)
    root = Path(ctx.task.repo_path)
    kept = sorted(path for path in union if (root / path).exists())
    dropped = sorted(union.difference(kept))
    if dropped:
        _record_gate_dropped_paths(ctx, dropped)
    return kept


def _record_gate_dropped_paths(ctx: _Work, dropped: list[str]) -> None:
    """Record ONCE per run the union paths the existence filter removed (#342).

    The :func:`_record_gate_deferral` precedent: append one note to
    ``result.capacity_warning`` (the artifact) and fire a phase notice (the
    stderr/cockpit/flight feeds — never a step), so an operator sees exactly
    what went ungated (a deleted or renamed-away prior-episode file) instead
    of inferring it. ``_gate_drop_noted`` guards the once — all four gates
    call :func:`_gate_changed_set`, the note must not multiply.
    """
    if ctx._gate_drop_noted:
        return
    ctx._gate_drop_noted[:] = [True]
    note = (
        f"{len(dropped)} prior-episode path(s) no longer exist and were not "
        "graded: " + ", ".join(dropped)
    )
    existing = ctx.result.capacity_warning
    ctx.result.capacity_warning = f"{existing}; {note}" if existing else note
    _emit_phase(ctx, note)


def _run_pre_finish_gates(
    ctx: _Work, complete: CompleteFn, outcome: str, aborted: Exception | None
) -> None:
    """Run the four pre-finish gates — or record their chain deferral (#335, c8/c10).

    A chain episode exiting on a continuation shape (budget-exhausted, or a
    declared fill-line finish-with-handoff — the SAME signals
    ``colleague/chain.py`` continues on) skips the gates: the next episode
    rewrites this tree, so mid-chain gates would spend per-episode budget
    grading intermediate state. Recorded ONCE per episode on the artifact (the
    :func:`_record_fillline_cap` precedent) — never silent. The chain's FINAL
    (finish-shaped) episode runs them over union(this episode's changed,
    prior_changed) via :func:`_gate_changed_set` (c23), keeping the live-loop
    fix-turn / re-examine paths intact — the post-hoc gate shape was rejected
    for exactly that loss. A non-chained run never defers (byte-identical),
    incl. an ``until_done`` run without a chain dispatch and every subagent
    child (c22). Each gate keeps its own aborted guard + best-effort wrapping
    (it can never abort :func:`run`); ordering is load-bearing — coherence,
    test-integrity, and affected-tests all grade the lint-fixed changed set.
    Extracted from :func:`run` so the deferral branch keeps ``run()`` under
    the S3776 cognitive-complexity ceiling (the PR #338 Sonar catch).
    """
    if _gates_deferred_to_chain(ctx, outcome, aborted):
        _record_gate_deferral(ctx)
        return
    # Lint (#200): auto-fix changed files; residual reporter violations after a
    # clean finish get ONE bounded model fix-turn per remaining retry.
    _maybe_run_lint_gate(ctx, complete, outcome, aborted)
    # Coherence (#294, colleague#291 S3): score the changed .md files; warn-only.
    _maybe_run_coherence_gate(ctx, aborted)
    # Test-integrity (#203): flag the mirror signature; advisory + non-blocking.
    _maybe_run_test_integrity_gate(ctx, complete, outcome, aborted)
    # Affected-tests (#213): run the tests transitively importing the changed
    # module(s); advisory + non-blocking.
    _maybe_run_affected_tests_gate(ctx, complete, outcome, aborted)


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
        changed = _gate_changed_set(ctx)
        if not changed:
            return
        report = _lint.run_lint_gate(ctx.task.repo_path, changed)
        if report is None:
            return
        retries = ctx.lint_fix_retries if outcome == _EXIT_FINISHED else 0
        while report.residual and retries > 0:
            _run_lint_fix_turn(ctx, complete, report.residual)
            retries -= 1
            next_report = _lint.run_lint_gate(ctx.task.repo_path, _gate_changed_set(ctx))
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


def _maybe_run_coherence_gate(ctx: _Work, aborted: Exception | None) -> None:
    """Run the coherence pre-finish gate on the changed docs (#294, #291 S3).

    Shells ``coherence meaning score <file> --json`` per changed ``.md`` file
    (:func:`colleague.coherence.run_coherence_gate`), recording the result on
    ``result.coherence_report`` with the measurement's frame provenance (the
    embedder env the subprocess saw — the lobes-injected one when armed,
    ``ctx.embed_env``). Advisory + warn-only: no fix-turn, never blocks the
    handoff, and a run with no changed docs / no CLI / the gate disabled is
    byte-identical (omit-when-None). Best-effort + fail-safe like the lint
    gate: the body is wrapped so it can never abort ``run()``.
    """
    if aborted is not None or not ctx.coherence_enabled:
        return
    with suppress(Exception):
        changed = _gate_changed_set(ctx)
        if not changed:
            return
        report = _coherencemod.run_coherence_gate(
            ctx.task.repo_path, changed, env_overrides=ctx.embed_env
        )
        if report is None:
            return
        ctx.result.coherence_report = report


_ACCEPTANCE_CHECK_PROMPT = (
    "Before this work item closes: for EACH acceptance criterion listed below, state "
    "whether the work you just did meets it. Respond with ONLY a JSON array of "
    'objects, one per criterion IN ORDER, shaped {"criterion": "...", "met": '
    'true|false, "evidence": "one concrete sentence"}. No prose outside the JSON, '
    "no tool calls.\n\nCriteria:\n"
)


def _parse_acceptance_outcomes(text: str, criteria: list[str]) -> list[dict[str, object]]:
    """Parse the self-check turn's JSON into per-criterion outcome records.

    Tolerant by contract (the check is advisory and must never raise): any
    parse failure returns ``[]`` (nothing recorded). Entries are matched to the
    task's criteria BY POSITION and the criterion text is taken from the TASK
    (authoritative), so a model that paraphrases or hallucinates criteria can
    only ever grade the real ones; a missing entry reads as ``met=False`` with
    empty evidence — the conservative default.
    """
    try:
        start = text.index("[")
        end = text.rindex("]") + 1
        data = json.loads(text[start:end])
    except (ValueError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    outcomes: list[dict[str, object]] = []
    for index, criterion in enumerate(criteria):
        entry = data[index] if index < len(data) and isinstance(data[index], dict) else {}
        outcomes.append(
            {
                "criterion": criterion,
                "met": bool(entry.get("met", False)),
                "evidence": str(entry.get("evidence") or ""),
            }
        )
    return outcomes


def _maybe_run_acceptance_selfcheck(
    ctx: _Work, complete: CompleteFn, outcome: str, aborted: Exception | None
) -> None:
    """ONE bounded self-check turn recording per-criterion outcomes (t15 / R6 / #259).

    Fires only when the task declared ``acceptance`` criteria AND the loop
    finished cleanly (an incomplete/aborted run should not spend a turn grading
    itself; its honest status must stand untouched). The check is a SINGLE
    completion — never a re-entered tool loop — so it structurally cannot call
    ``finish`` and cannot clobber the work item's terminal summary/status (a
    stronger invariant than the lint fix-turn's save/restore, by construction).
    ADVISORY only: outcomes land on ``result.acceptance_outcomes`` for the
    feedback/ROI loop; ``met=False`` never flips the run status — operator
    judgment stays the authority (the devague-tool convention: the backend
    cannot self-confirm). Best-effort + fail-safe like the sibling gates.
    """
    if aborted is not None or outcome != _EXIT_FINISHED or not ctx.task.acceptance:
        return
    with suppress(Exception):
        criteria = [str(criterion) for criterion in ctx.task.acceptance]
        # Dual-model escalation (t5 / spec c10c): grading criteria is a judgment
        # call, so a dual-model run asks the DEEPTHINK model first — with a
        # self-contained digest (instruction + goal + summary + criteria), never
        # the full history, so the prompt fits the deepthink model's own smaller
        # window (the seam windows it besides). A degraded or unparseable
        # escalation FALLS BACK to the main-model turn below (spec c13/h5) — the
        # attempt is recorded either way, the run never fails because of it.
        if _selfcheck_via_deepthink(ctx, criteria):
            return
        ctx.messages.append(
            {
                "role": "user",
                "content": _ACCEPTANCE_CHECK_PROMPT
                + "\n".join(f"- {criterion}" for criterion in criteria),
            }
        )
        resp = _complete_with_degradation(ctx, complete)
        _account_turn(ctx, resp)
        outcomes = _parse_acceptance_outcomes(resp.content or resp.reasoning or "", criteria)
        if outcomes:
            ctx.result.acceptance_outcomes = outcomes


def _record_deepthink(result: TaskResult, call: object) -> None:
    """Append one DeepthinkCall record to ``result.deepthink`` (init-on-first)."""
    if result.deepthink is None:
        result.deepthink = []
    result.deepthink.append(call)


def _selfcheck_via_deepthink(ctx: _Work, criteria: list[str]) -> bool:
    """Grade the acceptance criteria via the deepthink model (t5 / spec c10c).

    Returns ``True`` when the escalation produced usable per-criterion outcomes
    (recorded on ``ctx.result.acceptance_outcomes``); ``False`` when there is no
    binding (single-model run) or the escalation degraded / returned nothing
    parseable — the caller then runs the existing main-model self-check turn,
    the c13 degradation ladder. The escalation attempt (including a degraded
    one) is recorded on ``result.deepthink`` — visible, never silent.
    """
    if ctx.deepthink_run is None:
        return False
    digest = (
        "You are grading a completed repo work item against its acceptance "
        "criteria. You see ONLY this digest — no repo, no conversation.\n\n"
        f"Task instruction:\n{ctx.task.instruction}\n\n"
        + (f"Goal: {ctx.task.goal}\n\n" if ctx.task.goal else "")
        + f"Result summary:\n{ctx.result.summary or '(no summary recorded)'}\n\n"
        + _ACCEPTANCE_CHECK_PROMPT
        + "\n".join(f"- {criterion}" for criterion in criteria)
    )
    res = ctx.deepthink_run(digest, "", point="acceptance_selfcheck")
    call = getattr(res, "call", None)
    if call is not None:
        _record_deepthink(ctx.result, call)
    if call is None or getattr(call, "degraded", False):
        return False
    outcomes = _parse_acceptance_outcomes(str(getattr(res, "text", "") or ""), criteria)
    if not outcomes:
        return False
    ctx.result.acceptance_outcomes = outcomes
    return True


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
        changed = _gate_changed_set(ctx)
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
            report = _testintegrity.detect_mirror(ctx.task.repo_path, _gate_changed_set(ctx))
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


# A failed-affected-tests fix-turn re-enters the loop for at most this many model turns.
_AFFECTEDTESTS_FIX_STEPS = 8

_AFFECTEDTESTS_FIX_PROMPT = (
    "The pre-finish affected-tests gate ran the tests that (transitively) import your "
    "changed module(s) and some FAILED — these tests live in files you did not run, but "
    "your change affects them. Investigate and fix the regression in the IMPLEMENTATION "
    "(do not weaken or delete the tests), using read_file/edit_file/write_file, then "
    "call finish. Failing selection:\n"
)


def _maybe_run_affected_tests_gate(
    ctx: _Work, complete: CompleteFn, outcome: str, aborted: Exception | None
) -> None:
    """Run the pre-finish affected-tests gate (#213): run the tests that (transitively)
    import the changed module(s), so a scoped edit can't hide a regression in another
    file the model never ran.

    Advisory + non-blocking: selects the test files whose bounded-depth transitive
    import closure reaches a changed module (or uses the explicit ``--test`` override),
    runs pytest on them, and records an
    :class:`~colleague.affectedtests.AffectedTestsReport` on
    ``result.affected_tests_report``. On a FAILED status after a clean finish with a
    fix-turn budget left (``ctx.affectedtests_fix_retries``), ONE bounded model fix-turn
    is injected per remaining retry, re-running the gate after each. The handoff ALWAYS
    proceeds (never blocks). A strict no-op when the loop aborted, the gate is disabled,
    no files changed, nothing is affected, or pytest is unavailable (the report stays
    None / is omitted, keeping the result byte-identical).

    Best-effort + fail-safe (mirrors the lint / test-integrity gates): the body is
    wrapped in ``suppress`` so a hung/erroring pytest can NEVER abort ``run()``.
    """
    if aborted is not None or not ctx.affectedtests_enabled:
        return
    with suppress(Exception):
        override = shlex.split(ctx.affectedtests_override) if ctx.affectedtests_override else None
        changed = _gate_changed_set(ctx)
        if not changed and override is None:
            return
        report = _affectedtests.run_affected_tests(
            ctx.task.repo_path,
            changed,
            depth=ctx.affectedtests_depth,
            max_files=ctx.affectedtests_max_files,
            pytest_args=override,
        )
        if report is None:
            return
        ctx.result.affected_tests_report = report
        _surface_affected_tests(report)
        retries = ctx.affectedtests_fix_retries if outcome == _EXIT_FINISHED else 0
        while report.status == "failed" and retries > 0:
            _run_affected_tests_fix_turn(ctx, complete, report)
            retries -= 1
            next_report = _affectedtests.run_affected_tests(
                ctx.task.repo_path,
                _gate_changed_set(ctx),
                depth=ctx.affectedtests_depth,
                max_files=ctx.affectedtests_max_files,
                pytest_args=override,
            )
            if next_report is None:
                break
            report = next_report
            ctx.result.affected_tests_report = report
            _surface_affected_tests(report)


def _run_affected_tests_fix_turn(
    ctx: _Work, complete: CompleteFn, report: "_affectedtests.AffectedTestsReport"
) -> None:
    """Inject ONE bounded model turn to fix a failing affected test, preserving state.

    Mirrors the lint / test-integrity fix-turn: saves & restores the work item's
    terminal fields so a fix-turn ``finish`` cannot clobber the real result; any failure
    is suppressed (the gate is best-effort and must never abort the work item).
    """
    saved = (
        ctx.result.summary,
        ctx.result.status,
        ctx.result.not_finished,
        ctx.result.stopped_without_finish,
    )
    ctx.messages.append(
        {
            "role": "user",
            "content": _AFFECTEDTESTS_FIX_PROMPT + "\n".join(report.selected[:50]),
        }
    )
    budget = ctx.result.stats.model_turns + _AFFECTEDTESTS_FIX_STEPS
    with suppress(Exception):
        _work_loop(ctx, complete, budget)
    (
        ctx.result.summary,
        ctx.result.status,
        ctx.result.not_finished,
        ctx.result.stopped_without_finish,
    ) = saved


def _surface_affected_tests(report: "_affectedtests.AffectedTestsReport") -> None:
    """Write the affected-tests summary to stderr (advisory; never raises)."""
    with suppress(OSError):
        sys.stderr.write(report.summary_line() + "\n")


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
    ``result.sub_results``. Reuses the existing subagent launcher with NO new
    worktree/merge code, and is bounded by the existing fan-out cap.

    Reviewer-write reconciliation (Qodo PR #211): the single-subagent launcher
    (``make_spawn`` → ``run_subagent``) runs the child **in-place** in the work
    item's tree (only the *batch* path uses isolated worktrees), and the handoff
    stages the whole tree (``git add -u``). So although the reviewer is prompted
    read-only, any file it nonetheless writes WOULD be committed — and would be
    *invisible* if left out of ``executor.changed``. We therefore merge the
    reviewer's ``changed_files`` into ``executor.changed`` (so they are tracked in
    ``TaskResult.changed_files`` and the artifact agrees with the commit) and emit a
    stderr warning, rather than letting a read-only-contract violation ship silently.

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
        if sub is None:
            return
        ctx.executor.sub_results.append(sub)
        # The reviewer should not write (read-only prompt), but the in-place spawn +
        # `git add -u` handoff mean any writes WOULD be committed; track them so they
        # are never silent/untracked, and warn on the contract violation.
        if sub.changed_files:
            ctx.executor.changed.update(sub.changed_files)
            with suppress(OSError):
                sys.stderr.write(
                    "test-integrity: reviewer subagent modified "
                    f"{len(sub.changed_files)} file(s) despite the read-only review "
                    "contract — tracked in changed_files (not silent): "
                    f"{', '.join(sorted(sub.changed_files)[:20])}\n"
                )


def _affectedtests_controls(controls: "ContextControls") -> dict[str, Any]:
    """The affected-tests gate kwargs for ``_Work``, defaulting each unset
    (``None``) ContextControls field. Kept out of ``run()`` so the per-field
    ``or``-defaults don't inflate its cognitive complexity (all-engines rule)."""
    return {
        "affectedtests_enabled": bool(controls.affectedtests),
        "affectedtests_fix_retries": controls.affectedtests_fix_retries or 0,
        "affectedtests_depth": controls.affectedtests_depth or 3,
        "affectedtests_max_files": controls.affectedtests_max_files or 20,
        "affectedtests_override": controls.affectedtests_override,
    }


def _resolve_runtime_defaults(
    task: Task,
    model: str | None,
    hooks: HookConfig | None,
    telemetry: Telemetry | None,
    policy: Policy | None,
) -> tuple[HookConfig, Telemetry, Policy]:
    """Default the three repo-resolved collaborators (hooks/telemetry/policy) when
    a caller didn't inject them. Kept out of ``run()`` so the per-field
    ``is not None`` ternaries don't inflate its cognitive complexity (mirrors
    ``_affectedtests_controls``). Byte-identical to the inline defaulting:
    hooks/policy resolve from ``task.repo_path`` (+ per-model overlay when
    ``model`` is given); telemetry resolves from the environment (a no-op
    unless ``COLLEAGUE_OTEL_ENABLED`` is set)."""
    return (
        hooks if hooks is not None else load_hooks(task.repo_path, model=model),
        telemetry if telemetry is not None else load_telemetry(),
        policy if policy is not None else load_policy(task.repo_path, model=model),
    )


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
    # hooks/telemetry/policy each default from the repo (or the environment, for
    # telemetry) when not injected — see _resolve_runtime_defaults for the
    # per-field contract (byte-identical to the prior inline defaulting).
    hooks, telemetry, policy = _resolve_runtime_defaults(task, model, hooks, telemetry, policy)

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt or _DEFAULT_SYSTEM},
        {"role": "user", "content": _build_initial_content(task)},
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
        model=model or "",
        senses_model=_context.senses_model,
        lobes_gateway=_context.lobes_gateway,
        max_steps=max_steps,
        context_budget=_context.budget,
        count_tokens=_context.count_tokens,
        deepthink_run=_context.deepthink_run,
        media_bridge=_context.media_bridge,
        senses_run=_context.senses_run,
        senses_media_bridge=_context.senses_media_bridge,
        autosplit_target=_context.autosplit_target,
        capacity_threshold=_context.fillline_threshold,
        chain_armed=_context.chain_armed,
        chain_episode=_context.chain_episode,
        # No or-() guard: ContextControls defaults it to () and from_config
        # normalizes — a bare tuple() keeps run() under the S3776 ceiling.
        chain_prior_changed=tuple(_context.chain_prior_changed),
        compaction_cap=_context.compaction_cap,
        mapping_fanout_files=_context.fanout_files,
        review_fanout_folders=_context.review_fanout_folders,
        plan_offer_tokens=_context.plan_offer_tokens,
        max_continue_nudges=_resolve_nudge_cap(_context),
        request_timeout=_context.request_timeout,
        fanout_throttle=_context.throttle_fanout,
        escalate_timeout=_context.escalate_timeout,
        flight=flight_session,
        lint_enabled=bool(_context.lint),
        lint_fix_retries=_context.lint_fix_retries or 0,
        coherence_enabled=bool(_context.coherence),
        memory_enabled=bool(_context.memory),
        memory_root=_context.memory_root,
        embed_env=dict(_context.embed_env or {}),
        testintegrity_enabled=bool(_context.testintegrity),
        testintegrity_fix_retries=_context.testintegrity_fix_retries,
        testintegrity_reviewer_model=_context.testintegrity_reviewer_model,
        **_affectedtests_controls(_context),
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

    # Recall-before (spec R1 / plan t2): inject prior lessons from the repo's
    # eidetic store as ONE advisory context message; a strict no-op unless armed.
    _maybe_recall_memory(ctx)

    # Cortex/senses packet (t6): when the task carries a senses ContextPacket,
    # inject the senses interpretation as ONE advisory companion message (cortex's
    # first message is already the operator's verbatim original) and record the
    # packet on TaskResult.senses; a strict no-op with no packet.
    _maybe_inject_context_packet(ctx)

    # Cortex-side self-knowledge (t9 / #306): when the operator's instruction is a
    # self-knowledge question (classify_selfknowledge), inject ONE advisory message
    # with the LIVE guide index + resolved self-facts so cortex answers about
    # colleague from its own docs, not a guess; a strict no-op for an ordinary turn
    # (the guide docs load ONLY on a self-knowledge turn).
    _maybe_inject_self_knowledge(ctx)

    # Media-comprehension bridge (t8, c24): with a text-only main + attached
    # media + an operator-declared multimodal second model, ONE tools-off
    # escalation describes the media and folds the answer back; strict no-op
    # otherwise. A declared multimodal senses config is preferred (t6).
    _maybe_run_media_bridge(ctx)

    # Drive timing (always-on): an ISO start stamp + a monotonic clock bracketing
    # the loop. Captured here so the duration covers the model work; finalized onto
    # WorkStats on every exit path below.
    started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    start_monotonic = time.monotonic()

    # #308 liveness: a run-start marker on the flight feed BEFORE the first
    # completion, so a pilot / senses can say "cortex started, working on <goal>"
    # instead of "I don't know" during a slow first turn. Record the monotonic
    # start so ``_emit_phase`` can stamp each heartbeat's elapsed. Strict no-op
    # (and no feed line) when this is not a watchable flight.
    if ctx.flight is not None:
        ctx._flight_started_monotonic.append(start_monotonic)
        with suppress(Exception):
            ctx.flight.append_run_start(goal=task.goal, max_steps=max_steps)

    # The engine call (`complete`) may raise mid-loop. Catch it here so the
    # partial work accumulated on `result` is preserved rather than discarded
    # (#37); the finish hook + neighbour cleanup + changed_files snapshot below
    # then run on *every* exit path, including this one.
    aborted: Exception | None = None
    outcome = _EXIT_BUDGET
    # Synthesis reserve (#197) — held back from the reading budget so the
    # forced-synthesis verdict (#191) runs with fresher context. A strict no-op
    # when no reserve is set (see _resolve_reading_budget).
    reading_budget = _resolve_reading_budget(_context, max_steps)
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

    # Live talk-lane fold (t5) — read the flight chat log into TaskResult.senses
    # BEFORE the reap deletes it, so the operator's mid-run conversation survives in
    # the artifact. A strict no-op when not a flight / no talk lane was used.
    _fold_flight_chat(ctx)

    # Flight cleanup — reap the live feed/control/chat on finish so the plane stays
    # ephemeral (a no-op when the work item was not a flight).
    _reap_flight(ctx)

    # Pre-finish gates — or their chain deferral (#335): the branch lives in
    # _run_pre_finish_gates (its docstring carries the full contract), keeping
    # run() flat under the S3776 ceiling. Runs BEFORE the changed_files
    # snapshot + stats below so any fix-turn edits are captured; the handoff
    # always proceeds.
    _run_pre_finish_gates(ctx, complete, outcome, aborted)

    # Deepthink tool-call records (t5 / spec c14): snapshot the executor's
    # accumulated records BEFORE the self-check (which may append its own), in
    # firing order. No records → result.deepthink stays None → the key is
    # omitted from the artifact (byte-identical single-model run). getattr:
    # run() is a public seam and a test may pass a minimal executor stand-in.
    _dt_calls = getattr(executor, "deepthink_calls", None)
    if _dt_calls:
        result.deepthink = list(_dt_calls)

    # Acceptance self-check (t15 / spec R6 / #259): on a CLEAN finish of a task
    # that declared acceptance criteria, ONE bounded completion records advisory
    # per-criterion {criterion, met, evidence} outcomes on
    # result.acceptance_outcomes. Runs after the gates so it grades the final
    # (lint-fixed) state; never flips status; strict no-op without criteria.
    # A dual-model run escalates the grading to the deepthink model first (t5).
    _maybe_run_acceptance_selfcheck(ctx, complete, outcome, aborted)

    result.changed_files = sorted(executor.changed)
    # Record the typed-subagent role this work item ran as (#t4), on every exit
    # path. ``None`` (no role) is omit-when-None in to_dict → byte-identical.
    result.role = _context.role
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
        model=model or "",
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

    # Honest-incompletion (colleague#313): flag a run that produced no expected
    # deliverable — after summary resolution so it composes with finish_recovered.
    _maybe_flag_incompletion(ctx, outcome)

    # Remember-after (spec R1 / plan t2): record this work item's lesson to the
    # repo's memory store; a strict no-op unless armed, best-effort always.
    _maybe_remember_lesson(ctx)

    # Escalation seam — not-finished path (#106 t3): step budget exhausted without
    # calling finish.  Runs AFTER summary resolution (above) so the continuation
    # record carries the real output.  Best-effort and observe-only; suppress so
    # it cannot mask the work item result.
    if result.not_finished:
        with suppress(Exception):
            _escalation.escalate(result, result.stats, task.repo_path, model=model)
    return result
