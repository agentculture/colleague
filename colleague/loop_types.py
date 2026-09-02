"""The loop's leaf value types: :class:`_Work` and :class:`ContextControls`.

Extracted from ``colleague/loop.py`` (plan hard-1000-line-file-limit, t15) as a
**true leaf**: this module imports no other ``loop_*`` sibling and never imports
``colleague.loop``, so there is no cycle back into the loop. Every lane helper
takes ``ctx: _Work``, which is why this had to move first.

A pure move — no behavior change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from colleague import backpressure
from colleague import configlifecycle as _configlifecycle
from colleague import effort as _effort
from colleague import effortrecord as _effortrecord
from colleague import flight as flightmod
from colleague import tae_loop as _tae
from colleague.agents import runtime as _agents_runtime
from colleague.contract import Task, TaskResult
from colleague.hooks import HookConfig
from colleague.policy import Policy
from colleague.telemetry import Telemetry
from colleague.tools import ToolExecutor

# Recovery for the trail-off (colleague#142): when the model ends a turn with no
# tool call and has not called ``finish``, nudge it ONCE to finish before giving up.
# Bounded so the loop still terminates; one reminder is enough for a capable model
# that merely forgot the closing ``finish`` call.
_MAX_FINISH_NUDGES = 1

# A progress sink: (step_index, tool, target, ok) -> None. Default ``None`` in the
# loop is a strict no-op; the CLI wires one that writes a line per step to stderr
# (#38). Lives in the loop, fired per tool call, so every backend inherits it
# identically (the all-engines rule), exactly like hooks and telemetry.
ProgressFn = Callable[[int, str, str, bool], None]


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
    associate_complete: Any = None  # t19 seat-completion factory, None = unarmed
    # Pre-mutation decision barrier (#484 t8): the bound barrier seat factory
    # (``loop_barrier.make_barrier_complete``); ``None`` = the spike opt-in is
    # unset, so ``loop_barrier.intercept`` is a strict no-op.
    barrier_complete: Any = None
    # Repeated-gate / fill-line effort spikes (#484 t9): the bound
    # ``loop_gateescalation.SeatEscalator`` over the LIVE acting config;
    # ``None`` = the ``COLLEAGUE_EFFORT_SPIKES`` opt-in is unset, so every
    # function in that module is a strict no-op.
    gate_escalation: Any = None
    # Effort decay clock (spec 2026-09-02-effort-floor-and-decay-arms): the
    # bound ``effortdecay.DecayState``; ``None`` = ``COLLEAGUE_EFFORT_DECAY``
    # (or the spike opt-in) unset, so ``decayed_turn`` is a strict no-op.
    effort_decay: Any = None
    # Single-element/append-only cells the frozen ``_Work`` flips through the
    # binding (the ``_split_recommended`` pattern): ``_effort_spikes_fired``
    # holds the at-most-once keys of the t9 spikes that already fired
    # ("gate:<gate>", "fillline") — needed because the artifact record shape
    # ``(point, rung, seat)`` cannot distinguish one gate from the other;
    # ``_fillline_escalated`` marks that a declaring-turn escalation is
    # currently pushed and must be popped when the declaration is recorded.
    _effort_spikes_fired: list[str] = field(default_factory=list)
    # stall.no_write marks (model-turn counts at which a spike fired) — the
    # count-keyed stall decision turn measures from the latest of these.
    _stall_marks: list[int] = field(default_factory=list)
    _fillline_escalated: list[bool] = field(default_factory=list)
    # Recorded seat rungs (effort-v4 t5) — threaded verbatim from the
    # ContextControls fields of the same names; see their contract there.
    reasoning_effort_main: "str | None" = None
    reasoning_effort_senses: "str | None" = None
    reasoning_effort_deepthink: "str | None" = None
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
    # Reactive auto-split (#151): when armed (a positive ``context_budget`` AND a positive
    # ``autosplit_target``), an EXHAUSTED context-overflow injects ONE split recommendation —
    # pointing the model at the existing ``subagents`` tool — *before* the error would propagate
    # to run()'s abort+escalate path. ``None``/0 leaves the feature dormant (a strict no-op).
    # Backend-judged: the loop only recommends; the model decides whether to split.
    autosplit_target: int | None = None
    # Single-element mutable cell: holds ``True`` once the reactive recommendation
    # has been injected, so it is offered at most ONCE per work item (the model then
    # gets bounded extra turns under ``max_steps``). Mutable so the frozen ``_Work``
    # can flip it through the binding (same pattern as ``_last_substantive``).
    _split_recommended: list[bool] = field(default_factory=list)
    # Single-element mutable cell carrying the floored budget from an EXHAUSTED degradation
    # give-up into the *next* turn (#154). When the shrink-and-retry gives up it re-raises, and
    # ``_work_loop`` may inject the auto-split/INCOMPLETE recommendation and grant one bounded
    # extra turn — that turn must run against the SAME small window the give-up reached, not the
    # full budget, or it would just overflow / time out again before the model can act. Consumed
    # once (read then cleared) by the next ``_complete_with_degradation`` call, so only the
    # recommendation turn is throttled; everything after returns to the full budget. Empty = no
    # carry (window to the full budget, the default). Mutable for ``_split_recommended``'s reason.
    _degraded_budget: list[int] = field(default_factory=list)
    # Last non-empty ``resp.content`` seen across ALL turns (including turns that
    # also made tool calls).  Updated in ``_work_loop`` unconditionally whenever
    # ``resp.content`` is non-empty — this is the t2 "last-substantive-content"
    # candidate used as the no-finish summary fallback in ``run``.  Stored as a
    # mutable list[str] (single element) so the frozen ``_Work`` dataclass can
    # still update it through the binding.
    _last_substantive: list[str] = field(default_factory=list)
    # Last ``resp.finish_reason`` seen across ALL turns (plan task t1, covers
    # c4/h4) — updated unconditionally on every ``_account_turn`` call
    # (including a "" value), mirroring the ``_last_substantive`` mutable-cell
    # pattern above so the frozen ``_Work`` dataclass can still update it
    # through the binding. Read by ``_finalize_finish_states`` at every exit
    # path to classify the "main" seat's terminal ``FINISH_*`` state.
    _last_finish_reason: list[str] = field(default_factory=list)
    _served_model: list[str] = field(default_factory=list)  # first served id (t18)
    # Reasoning sidecar (effort-v4 t6, c16/h7): ``seat`` is the acting-seat label stamped on every
    # sidecar record — run()'s ``seat`` param threaded verbatim (the append_run_start precedent);
    # display/disk only, never model context. ``_reasoning_ordinal`` is the within-turn
    # dispatch-ordinal cell (the ``_last_substantive`` mutable-cell pattern): reset to ``[0]`` as
    # each turn is accounted (the completion itself is ordinal 0), then ONE increment per tool
    # dispatch — a parallel batch consumes one ordinal shared by its N records, a sequential call
    # consumes its own (c34).
    seat: str = "cortex"
    _reasoning_ordinal: list[int] = field(default_factory=list)
    # Step-stall watchdog (#400): ``_last_progress`` is the monotonic time the last
    # step completed (the loop start until one does); ``_stalled`` holds the elapsed
    # seconds once the bound was crossed — a single-element cell the frozen ``_Work``
    # flips through the binding (the ``_last_substantive`` pattern).
    _last_progress: list[float] = field(default_factory=list)
    _stalled: list[float] = field(default_factory=list)
    # Model-bound agents runtime (#411, t15): the bound ``AgentsRun`` (identity, ledger, invocation
    # records, the TaskResult.agents fold) — ``None`` when the mode is unarmed; every seam call is
    # then a strict no-op (byte-identical).
    agents: Any = None
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
    # Wall-clock minutes after which a finished run leaves a split-next-time record (#416).
    too_long_min: int = 20
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
    # Whether the LAST completion's transport was actually stream-guarded (#438
    # guidance 3, Qodo #450): the proactive raise is suppressed only when the
    # guards really bound this turn, never merely because the env defaults arm
    # them. ``None`` (direct ``run`` callers, and any backend that records
    # nothing) keeps the env-only decision — byte-identical.
    transport_guarded: Callable[[], bool] | None = None
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
    # Rung-2 distillation seam + kill switch (t9) — see ContextControls.
    memory_distill: bool = True
    distill_fn: Callable[..., Any] | None = None
    # The from_config-resolved distillation author (t16): when set and no
    # explicit distill_fn was injected, the remember seam builds the detaching
    # child fn against the durable memory repo. None = rung-1 floor.
    distill_author: Any | None = None
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
    # Episode-boundary config lifecycle (three-tier-execution plan task t6,
    # decisions c8/h8/c26/h22): the WORKER episode's
    # ``configlifecycle.EpisodeConfigLifecycle``, threaded from
    # ``ContextControls.config_lifecycle``. The loop is a READ-ONLY consumer:
    # ``_work_loop`` calls ``observe_turn()`` once per completed model turn
    # (proving the effective-config digest is pinned constant within the
    # episode — nothing here ever calls ``apply_window``, which is reachable
    # ONLY through ``colleague.chain.apply_config_window`` at a sanctioned
    # window), and ``run()`` calls ``end_episode()`` exactly once, on EVERY
    # exit path (the T1 regression fix: a no-tool episode end counts as a
    # boundary exactly like a tool-driven one). ``None`` (the default — a
    # direct ``run`` caller, or a config object predating this field via
    # ``getattr``) is a strict no-op: byte-identical to the pre-t6 loop.
    config_lifecycle: "_configlifecycle.EpisodeConfigLifecycle | None" = None
    # Thought->action->evaluation control loop (post-#387, plan task t13): the
    # armed mode's one seam object (:class:`colleague.tae_loop.TaeSession`),
    # threaded from ``ContextControls.tae_session``. ``None`` (the default, and
    # every unarmed run) is a strict no-op: each of the four call sites below
    # is guarded by ``ctx.tae is not None``, so an unarmed loop is
    # byte-identical. The pure control logic lives in
    # :mod:`colleague.tae_control` / :mod:`colleague.tae_loop` — the loop only
    # calls it.
    tae: "_tae.TaeSession | None" = None


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


def _resolve_distill_author_safe(config: Any) -> Any | None:
    """Resolve the rung-2 distillation author from *config*, never raising (t16).

    Lazy-imports :mod:`colleague.distill` (which pulls background/memory) so a
    memory-less direct ``run`` caller loads nothing extra; any failure is the
    rung-1 floor (``None``), degrade-never-raise like every memory seam.
    """
    try:
        from colleague import distill as _distillmod

        return _distillmod.resolve_distill_author_from_config(config)
    except Exception:
        return None


def _too_long_min_of(config: Any) -> int:
    """``config.too_long_min`` as an int, keeping an explicit ``0`` (= disabled,
    Qodo #419 r3) — only an ABSENT/``None`` knob falls back to the default 20."""
    value = getattr(config, "too_long_min", None)
    return 20 if value is None else int(value)


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
    # Too-long wall-clock threshold in minutes for the split-next-time record (#416 c15).
    too_long_min: int = 20
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
    # Per-turn transport-guardedness probe (#438 guidance 3 / Qodo PR #450):
    # built by :func:`_make_transport_guard_probe` in :meth:`from_config` (the
    # all-engines single source). It reads back what the backend recorded on the
    # engine config for the turn just sent, so the proactive raise is suppressed
    # only for a turn the stream guards really bound. A backend that records
    # nothing reads as guarded — the pre-#450 env-only decision, byte-identical.
    transport_guarded: Callable[[], bool] | None = field(default=None, compare=False, repr=False)
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
    # Model-bound agents runtime (#411, t15): ``runtime.make_agents_run(config)`` —
    # ``None`` unarmed. Bound here (the deepthink_run/senses_run precedent) so the
    # loop never sees the config itself.
    agents_run: Any = field(default=None, compare=False, repr=False)
    senses_media_bridge: bool = False
    # Synthesis reserve (#197): steps held back from the reading budget so a read-heavy run (a
    # big-diff review) stops reading early and the forced-synthesis verdict turn (#191) runs with
    # fresher, less-windowed context instead of being starved after the budget is spent reading.
    # ``None``/<= 0 reserves nothing — a strict no-op (the full ``max_steps`` is spent reading, as
    # before). Forwarded by every backend from ``config.synthesis_reserve_steps``; the caller
    # (review) sets it. Clamped so at least one reading step always remains.
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
    # Rung-2 lesson distillation (self-learning t9). ``distill_fn`` is the
    # injectable seam — a callable ``(result, request_head) -> raw model text``
    # whose output is parsed + schema-validated (colleague/lessons.py) before a
    # lesson may ride the remember-after record. ``None`` (the default) is the
    # rung-1 floor: byte-identical record, no counters (spec c16/h13). The
    # ``memory_distill`` knob is the independent kill switch (spec c29/h24) —
    # off = byte-identical rung-1 even with a seam present.
    memory_distill: bool = True
    distill_fn: Callable[..., Any] | None = None
    # The resolved distillation author (t16) — set by from_config via
    # ``distill.resolve_distill_author_from_config`` (deepthink > armed-lobes
    # main > None). Only consulted when ``distill_fn`` is None; the remember
    # seam builds the detaching child fn lazily against the memory repo.
    distill_author: Any | None = None
    # Test-integrity gate (#203): when truthy (the default) the runtime runs the mirror-detection
    # heuristic on the changed files after the loop and records the findings on
    # ``result.test_integrity_report``. Advisory + non-blocking — never blocks the handoff, makes no
    # network call, and a no-finding run is byte-identical (omit-when-None). Defaults ON so the gate
    # fires for every backend without each backend opting in; ``False`` disables (env/config feeds).
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
    # (``config.senses.model``) and the ARMED lobes gateway origin (``config.lobes_gateway_url``,
    # set by ``EngineConfig.resolve`` — ``None`` when unarmed OR degraded-unreachable, so it names
    # the state the run ACTUALLY resolved with). Read ONLY by the self-knowledge advisory so an
    # armed session renders the REAL senses id + gateway URL instead of a false ``not
    # configured``/``not armed``; ``""`` (the default — direct ``run`` callers, or genuinely
    # absent) keeps the honest absent lines. Forwarded by every backend via :meth:`from_config`
    # (all-engines rule); not otherwise load-bearing — byte-identical when empty.
    senses_model: str = ""
    lobes_gateway: str = ""
    # Episode-boundary config lifecycle (three-tier-execution plan task t6, decisions
    # c8/h8/c26/h22): the WORKER episode's ``configlifecycle.EpisodeConfigLifecycle`` — queues
    # cortex-authored lattice proposals and applies them ONLY at the two sanctioned windows
    # (``colleague/chain.py``'s ``apply_config_window``, before episode 1 / between episodes),
    # never mid-episode. ``None`` (the default) is a strict no-op: no digest tracking, no boundary
    # counting, byte-identical to the pre-t6 loop. Not yet forwarded by ``EngineConfig`` (that is a
    # later task's wiring, e.g. t11's cortex configurator) — ``from_config`` reads it via
    # ``getattr`` so a config object predating this field stays byte-identical, exactly like
    # ``chain_prior_changed`` above.
    config_lifecycle: "_configlifecycle.EpisodeConfigLifecycle | None" = field(
        default=None, compare=False, repr=False
    )
    # Thought->action->evaluation control loop (t13): the armed mode's one seam object, built by
    # :func:`colleague.tae_loop.make_tae_session` from the t12 ``thought_action_evaluation`` /
    # ``evaluation_seats`` arming. ``None`` (the default, and every unarmed config) leaves all four
    # loop call sites dormant — byte-identical. compare=False: it holds live seats, i.e. behavior,
    # not comparable config (the ``deepthink_run``/``senses_run`` precedent).
    tae_session: "_tae.TaeSession | None" = field(default=None, compare=False, repr=False)
    #: The associate seat-completion factory (adopt-from-qwen-code t19) — every
    #: backend passes ``associate_seats.make_associate_complete(config, name)``;
    #: ``None`` (unarmed) keeps the acting completion for every seat.
    associate_complete: Any = field(default=None, compare=False, repr=False)
    #: The pre-mutation decision barrier's seat factory (#484 t8) — built in
    #: ``from_config`` from the live config, ``None`` unless the
    #: ``COLLEAGUE_EFFORT_SPIKES`` opt-in is armed (byte-identical default).
    barrier_complete: Any = field(default=None, compare=False, repr=False)
    #: The repeated-gate / fill-line seat escalator (#484 t9) — built in
    #: ``from_config`` over the SAME live config object the backend's acting
    #: completion closed over, ``None`` unless the ``COLLEAGUE_EFFORT_SPIKES``
    #: opt-in is armed (byte-identical default).
    gate_escalation: Any = field(default=None, compare=False, repr=False)
    #: The effort-decay clock (spec 2026-09-02-effort-floor-and-decay-arms) —
    #: ``None`` unless ``COLLEAGUE_EFFORT_DECAY=1`` AND the spike opt-in are
    #: armed (byte-identical default).
    effort_decay: Any = field(default=None, compare=False, repr=False)
    #: The acting (main) seat's resolved thinking-effort rung (effort-v4 t5,
    #: c6/h5) — ``effort.effort_of(config)``, exactly what the wire sends
    #: (``vllm_openai._effort_for``'s value), resolved ONCE in ``from_config``
    #: and recorded on ``finish_states`` + the artifact ``effort`` block.
    #: ``None`` (a direct ``run()`` caller, or send-nothing) records nothing.
    reasoning_effort_main: "str | None" = None
    #: The senses seat's rung when a senses config is armed — the SAME
    #: ``effortrecord.seat_effort`` formula the senses seat builder uses, so
    #: record and wire can never diverge. ``None`` = no senses config.
    reasoning_effort_senses: "str | None" = None
    reasoning_effort_deepthink: "str | None" = None
    #: In-flight liveness binder (#483): ``loop_deltaheartbeat.arm`` chained the
    #: heartbeat onto ``config.on_delta`` here; ``run`` binds its ctx into it.
    #: ``None`` = nothing armed (the blocking path, or a hand-built controls).
    delta_binder: Any = field(default=None, compare=False, repr=False)

    @classmethod
    def from_config(
        cls,
        config,
        *,
        count_tokens=None,
        deepthink_run=None,
        senses_run=None,
        tae_session=None,
        associate_complete=None,
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

        This is also where the in-flight delta heartbeat is armed (#483): the
        ONE seam where a live config meets loop-owned code. Imported lazily so
        this module stays the import leaf its own docstring promises.
        """
        from colleague import loop_barrier as _loopbarrier
        from colleague import loop_deltaheartbeat as _deltaheartbeat
        from colleague import loop_gateescalation as _gateescalation

        return cls(
            delta_binder=_deltaheartbeat.arm(config),
            # #484 t8: ``None`` (and nothing built) unless the spike opt-in is armed.
            barrier_complete=_loopbarrier.make_barrier_complete(config),
            # #484 t9: likewise ``None`` unless the SAME opt-in is armed.
            gate_escalation=_gateescalation.make_escalator(config),
            # decay: likewise ``None`` unless BOTH opt-ins are armed.
            effort_decay=_gateescalation.make_decay(config),
            budget=config.context_budget_tokens,
            count_tokens=count_tokens,
            agents_run=_agents_runtime.make_agents_run(config),
            autosplit_target=config.autosplit_target_tokens,
            fillline_threshold=config.fillline_threshold,
            too_long_min=_too_long_min_of(config),
            fanout_files=config.fanout_files,
            review_fanout_folders=config.review_fanout_folders,
            plan_offer_tokens=config.plan_offer_tokens,
            max_continue_nudges=config.max_continue_nudges,
            synthesis_reserve=config.synthesis_reserve_steps,
            request_timeout=config.timeout,
            throttle_fanout=_make_fanout_throttle(config),
            escalate_timeout=_make_timeout_escalator(config),
            transport_guarded=_make_transport_guard_probe(config),
            lint=config.lint,
            lint_fix_retries=config.lint_fix_retries,
            coherence=bool(getattr(config, "coherence", True)),
            memory=config.memory,
            memory_distill=bool(getattr(config, "memory_distill", True)),
            distill_author=_resolve_distill_author_safe(config),
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
            associate_complete=associate_complete,
            # Recorded seat rungs (effort-v4 t5, c6/c14): resolved ONCE here —
            # the acting seat via effort_of (exactly the wire's value, an
            # operator --effort override included), the senses seat via the
            # shared builder formula, only when a senses config is armed.
            reasoning_effort_main=_effort.effort_of(config),
            reasoning_effort_senses=(
                _effortrecord.seat_effort(config, "senses")
                if getattr(config, "senses", None) is not None
                else None
            ),
            # The deepthink seat's rung, resolved with the SAME formula its
            # seat builder applies (deepthink.py) — recorded onto the effort
            # block only if an escalation actually fired (review-2 c22 fix).
            reasoning_effort_deepthink=(
                _effortrecord.seat_effort(config, "deepthink")
                if getattr(config, "deepthink", None) is not None
                else None
            ),
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
            # Episode-boundary config lifecycle (t6): forward-compatible via
            # getattr — no EngineConfig field exists yet (a later task, e.g.
            # t11's cortex configurator, adds one), so today every backend
            # reads back ``None`` and stays byte-identical (the
            # ``chain_prior_changed`` precedent above).
            config_lifecycle=getattr(config, "config_lifecycle", None),
            # Thought->action->evaluation session (t13): every backend passes
            # ``make_tae_session(config, self.name)`` — the same single source
            # as deepthink_run/senses_run, so mock and vllm-openai behave
            # identically (all-engines rule). ``None`` when unarmed.
            tae_session=tae_session,
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


#: The attribute a backend sets on its ``EngineConfig`` to report, per turn,
#: whether the transport it just used was read through the stream guards. The
#: same reassign-a-plain-attribute convention ``config.base_timeout`` and
#: ``config.reasoning_effort_warnings`` already use for call-time state.
TRANSPORT_GUARDED_ATTR = "transport_stream_guarded"


def _make_transport_guard_probe(config) -> Callable[[], bool]:
    """Build the per-turn transport-guardedness probe bound to *config* (#450).

    The vLLM adapter records ``config.transport_stream_guarded`` on every
    dispatch — ``True`` only when the turn actually went out on the guarded SSE
    reader, ``False`` for a blocking (``COLLEAGUE_STREAM=0``) completion whose
    body the guards never see. A backend that records nothing (``mock``, whose
    turns never touch a socket) reads as ``True``, which keeps the pre-#450
    env-only suppression — byte-identical.

    ``config`` is left untyped for the same reason
    :func:`_make_timeout_escalator` leaves it untyped: no import cycle with
    :mod:`colleague.config`.
    """

    def probe() -> bool:
        return bool(getattr(config, TRANSPORT_GUARDED_ATTR, True))

    return probe


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
