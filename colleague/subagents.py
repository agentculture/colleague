"""The subagent launcher — nested in-process child work items, depth-bounded.

Split (hard-1000-line-file-limit, task t7) into three siblings so this module
stays under the 1000-line file-length gate: the seat/binding resolution surface
(:class:`~colleague.subagents_binding.ChildSpec`, the delegation-bounds check,
the cross-role lobes binding) lives in :mod:`colleague.subagents_binding`; most
of the parallel batch orchestration (the worktree lifecycle, the merge child,
the batch entry point) lives in :mod:`colleague.subagents_batch`. This module
keeps the two synchronous single-child entry points (:func:`make_spawn` /
:func:`run_subagent`), the armed child-config builders that assign the
per-seat thinking-effort rung (:func:`_child_config_for_profile` /
:func:`_build_child_config` — the ``tests/test_thinking_effort_boundary.py``
sanctioned-assign-files list still names only this file), and
:func:`_spawn_children` — the ONE function anywhere in the batch lane that
actually instantiates a ``ThreadPoolExecutor``, kept here on purpose: this is
the sole module ``tests/test_boundary.py``'s two-sided ``_THREADS_ALLOWED``
check (mirrored byte-for-byte in ``tests/test_agents_boundary.py`` and
``tests/test_chain_e2e.py``) permits to import ``concurrent.futures``, and
moving that one call site would have forced edits to all three. Every name
this module used to define directly is still reachable at
``colleague.subagents.<name>`` — re-exported here — so all 18 existing
importers, and every ``colleague.subagents.registry.load`` monkeypatch, still
resolve unchanged.

Mid-work, an engine can delegate a scoped sub-task to a NESTED child work item on a
chosen engine/model. This module is the launcher. It offers two paths:

**Single child (``run_subagent`` / ``make_spawn``).** Runs ONE nested child work item
and returns its :class:`~colleague.contract.SubResult`. A child work item is exactly
*a work item without handoff*: the git/PR handoff lives only in the CLI
``execute_work`` path, never in :meth:`Engine.work`, so calling
``engine.work(child_task, child_config)`` runs the bounded tool-loop and returns
a uniform ``TaskResult`` with **no** branch, commit, or PR side effects. This
single-child launch is SYNCHRONOUS: a plain function call — no thread, process,
asyncio, or socket.

**Parallel batch (``batch_spawn`` / ``make_batch_spawn``).** Runs a BATCH of child
drives and integrates them. Each child work items inside its OWN throwaway git
worktree on branch ``sub/<child_id>`` (via :mod:`colleague.worktrees`), so
concurrent writes never touch the shared working tree. The concurrency width is
``effective_concurrency(parent_config.subagent_concurrency)``:

- **width == 1** (the default) — children run SEQUENTIALLY and **no**
  ``ThreadPoolExecutor`` is ever instantiated: opt-in concurrency is off unless
  the operator sets ``COLLEAGUE_SUBAGENT_CONCURRENCY > 1``.
- **width > 1** — children run CONCURRENTLY via
  ``concurrent.futures.ThreadPoolExecutor(max_workers=width)``, confined to THIS
  module (the one sanctioned concurrency consumer; threads are forbidden else).

Results are collected AFTER the executor join, in the MAIN thread, via
``future.result()`` — no shared mutable list is mutated from worker threads, so
the concurrent phase has no shared-state race. After the join a SEQUENTIAL
**merge-subagent** ("child C") git-merges each ``sub/<child_id>`` branch back into
the working branch (via :func:`colleague.worktrees.merge_branch`). A CLEAN merge is
kept; a CONFLICT is surfaced in the merge child's ``SubResult`` (status + the
conflicted paths in the summary) — never force-merged and never silently dropped.
``batch_spawn`` returns a FLAT ``list[SubResult]``: the N child results in input
order followed by exactly one merge child. Per-child worktrees/branches are torn
down on EVERY exit path (success, partial, or exception).

Termination is structural for both paths via TWO caps, both checked *first, before
any work* (no drive, no worktree). (1) The per-path **depth** cap: a child at
``depth > MAX_SUBAGENT_DEPTH`` is refused. (2) The shared **global agent budget**
(#t4, :class:`_AgentBudget`): a single :data:`~colleague.config.MAX_SUBAGENT_TOTAL`
cap on the TOTAL agents spawned under one top-level work item, regardless of
nesting shape — charged atomically (thread-safe) so concurrent batch children
cannot race past it. The budget is created once by the loop wiring and threaded
down every level; each child is handed its OWN spawn AND batch-spawn callbacks
bound to ``depth + 1`` and the same budget, so nested batches are now PERMITTED
yet the total stays bounded. ``counter=None``, or a read-only purpose child
(``ChildSpec.charges_budget=False``, c34), skips the budget — only depth applies.

The engine/model switch is pure configuration: the launcher resolves the child
engine by name through :func:`colleague.registry.load` and inherits the parent's
:class:`~colleague.config.EngineConfig` with only the model overridden
(``dataclasses.replace``) — no engine's own code is touched, a config-level switch.
"""

from __future__ import annotations

import concurrent.futures
import dataclasses
import threading
from typing import Callable, List, Optional, cast

from colleague import associate_seats as _associate_seats
from colleague import (  # noqa: F401 - re-exported: tests patch colleague.subagents.worktrees
    registry,
    web_schemas,
    worktrees,
)
from colleague.config import (
    MAX_SUBAGENT_DEPTH,
    MAX_SUBAGENT_TOTAL,
    EngineConfig,
    _role_dial_base_url,
    _same_origin,
)
from colleague.configlifecycle import EpisodeConfigSnapshot
from colleague.contract import SubResult, Task
from colleague.subagents_batch import (  # noqa: F401
    _MIN_CHILD_CONTEXT_BUDGET,
    _MIN_CHILD_MAX_STEPS,
    _build_child_spec,
    _child_budget_share,
    _resolve_batch_width,
    _run_batch,
    _run_child_in_worktree,
    make_batch_spawn,
)

# Re-exported below (not referenced by name in this file's own code) so every
# existing importer of a name this module used to define directly still
# resolves at colleague.subagents.<name> after the t7 split — including the
# `colleague.subagents.registry.load` monkeypatch targets and every private
# helper tests import or patch directly.
from colleague.subagents_binding import (  # noqa: F401
    BINDABLE_ROLES,
    ChildSpec,
    SubagentError,
    _child_purpose,
    _child_requested_tools,
    _ChildBinding,
    _delegate_event_data,
    _delegation_bounds,
    _enforce_delegation_bounds,
    _requested_role,
    _resolve_child_binding,
    _seat_purpose,
    decomposition_seat_config,
    default_parent_profile,
)


@dataclasses.dataclass(frozen=True)
class FrozenChildConfigLifecycle:
    """An immutable, read-only view of a parent's config plane, for ONE child.

    Change-content consumption lane (plan task t10, spec c35/h28): a spawned
    child never receives the parent's REAL
    :class:`~colleague.configlifecycle.EpisodeConfigLifecycle` — children
    never propose changes and never observe turns on the top-level task's
    config plane, only the top-level ``run()`` loop does that (the r2 rule,
    extended). This frozen adapter QUACKS LIKE the lifecycle's READ surface:
    ``snapshot`` is a **property** so both ``colleague/engine.py``'s bare
    ``getattr`` (t7) and the engines' ``callable()`` check (t3) resolve it;
    ``child_snapshot()`` returns the SAME frozen snapshot one level deeper, so
    a grandchild inherits exactly like a depth-1 child (acceptance criterion 1).

    Nothing else: no ``propose``/``apply_window``. ``observe_turn``/
    ``end_episode`` no-ops exist only because ``colleague/loop.py`` calls both
    unconditionally on ANY attached ``config_lifecycle`` — a bare stub without
    them would raise ``AttributeError`` on the child's first turn; both touch
    no parent state.

    A frozen dataclass over an already-frozen
    :class:`~colleague.configlifecycle.EpisodeConfigSnapshot` — safe to read
    from a ``ThreadPoolExecutor`` worker thread (``batch_spawn`` width > 1),
    no lock needed.
    """

    frozen_snapshot: EpisodeConfigSnapshot

    @property
    def snapshot(self) -> EpisodeConfigSnapshot:
        """The frozen snapshot — read as a PROPERTY (t3's callable() check and
        t7's plain getattr both resolve it correctly this way)."""
        return self.frozen_snapshot

    def child_snapshot(self) -> EpisodeConfigSnapshot:
        """The SAME frozen snapshot, for a grandchild's own spawn to inherit."""
        return self.frozen_snapshot

    def observe_turn(self) -> str:
        """No-op: answers ``loop.py``'s per-turn call without recording
        anything or touching parent state; returns the snapshot's own digest."""
        return self.frozen_snapshot.digest()

    def end_episode(self) -> int:
        """No-op: answers ``loop.py``'s per-exit call without advancing any
        parent boundary count (there is none reachable from here). Always 0."""
        return 0


def _child_config_lifecycle(
    parent_config: EngineConfig,
) -> Optional[FrozenChildConfigLifecycle]:
    """Derive the frozen adapter a spawned child inherits — never the real thing.

    ``parent_config.config_lifecycle`` may be the REAL
    :class:`~colleague.configlifecycle.EpisodeConfigLifecycle` or already a
    :class:`FrozenChildConfigLifecycle` (a grandchild spawn). Both expose
    ``child_snapshot()``, preferred over ``snapshot``: it is the lifecycle's
    OWN "what does a spawned child inherit" answer (the r2 rule lives there,
    keeping a future third attachment shape honest by construction);
    ``snapshot`` is the fallback for an attachment lacking ``child_snapshot``.

    Returns ``None`` when nothing is attached — the caller leaves the
    child's own ``config_lifecycle`` at ``None``, byte-identical to today."""
    lifecycle = getattr(parent_config, "config_lifecycle", None)
    if lifecycle is None:
        return None
    child_snapshot_fn = getattr(lifecycle, "child_snapshot", None)
    if callable(child_snapshot_fn):
        snapshot = child_snapshot_fn()
    else:
        snapshot = getattr(lifecycle, "snapshot", None)
    if snapshot is None:
        return None
    return FrozenChildConfigLifecycle(snapshot)


#: A spawn callback: ``spawn(instruction, engine=None, model=None, role=None)
#: -> SubResult``. Bound to a repo/parent-config/parent-engine/depth/budget by
#: :func:`make_spawn` and assigned to ``EngineConfig.subagent_spawn`` so the loop
#: can offer delegation. ``role`` (optional) types the child (#t4).
SpawnFn = Callable[..., SubResult]

#: A batch spawn callback: ``batch_spawn(items, role=None) -> list[SubResult]``
#: where each item is ``{"instruction": str, "engine": Optional[str], "model":
#: Optional[str], "role": Optional[str]}``. Bound by :func:`make_batch_spawn`;
#: consumed by the ``subagents`` (plural) loop tool and wired by the loop. The
#: batch-level ``role`` applies to every child unless an item carries its own.
BatchSpawnFn = Callable[..., List[SubResult]]

__all__ = [
    "BINDABLE_ROLES",
    "ChildSpec",
    "FrozenChildConfigLifecycle",
    "SpawnFn",
    "BatchSpawnFn",
    "SubagentError",
    "default_parent_profile",
    "make_spawn",
    "run_subagent",
    "make_batch_spawn",
    "new_agent_budget",
]


class _AgentBudget:
    """A thread-safe global agent counter shared across ONE top-level work item.

    Every spawned child (single or batch, at ANY nesting depth) charges this
    budget exactly once before it does work, so the TOTAL number of agents
    spawned under one top-level work item is bounded by ``limit`` for every
    nesting shape — the structural termination guarantee for "agents of agents".

    Charging is guarded by a lock because concurrent batch children (and their
    own nested delegations) run in ``ThreadPoolExecutor`` worker threads — the one
    place in colleague where shared mutable state is touched off the main thread.
    The budget is created ONCE per top-level work item (by the loop wiring, t6)
    and threaded down every level. With no budget threaded (``counter=None``),
    or for a read-only purpose child (``ChildSpec.charges_budget=False``, c34),
    charging is skipped entirely — only the depth cap applies.
    """

    def __init__(self, limit: int = MAX_SUBAGENT_TOTAL) -> None:
        self._lock = threading.Lock()
        self.limit = limit
        self.count = 0

    def charge(self) -> int:
        """Account for one more spawned agent; raise past the cap (zero work done).

        Checks BEFORE incrementing so ``count`` never exceeds ``limit`` even across
        repeated refused attempts: the (limit+1)-th charge raises without bumping
        the count, so ``count`` is exactly the number of agents that actually ran.
        """
        with self._lock:
            if self.count >= self.limit:
                raise SubagentError(f"global agent budget ({self.limit}) exceeded")
            self.count += 1
            return self.count

    def remaining(self) -> int:
        """A snapshot of how many more agents may be spawned (best-effort, for pre-checks)."""
        with self._lock:
            return max(0, self.limit - self.count)


def new_agent_budget(config: Optional[EngineConfig] = None) -> "_AgentBudget":
    """Create ONE shared global agent budget for a top-level work item (#t4).

    The wiring that builds the top-level spawn callbacks (``execute_work``, the
    plan workforce) MUST create one budget here and pass it as ``counter=`` to BOTH
    :func:`make_spawn` and :func:`make_batch_spawn`, so every spawned child — single
    or batch, at any nesting depth — charges the SAME counter and the global
    ``MAX_SUBAGENT_TOTAL`` cap is actually enforced in production. Honors the
    env-tunable ``config.subagent_total`` when a config is given.
    """
    limit = getattr(config, "subagent_total", MAX_SUBAGENT_TOTAL) if config else MAX_SUBAGENT_TOTAL
    return _AgentBudget(limit)


def _child_config_for_profile(
    parent_config: EngineConfig,
    spec: ChildSpec,
    binding: Optional[_ChildBinding] = None,
    *,
    role: Optional[str] = None,
    depth: int = 1,
) -> EngineConfig:
    """Build the ARMED child's :class:`EngineConfig` for its resolved profile.

    A SMALL local seam owned by this module. The intended single seat builder
    is plan task t9's ``colleague.agents.runtime.agent_engine_config(config,
    profile, roles)`` (the one builder ``tae_loop.seat_engine_config``,
    ``deepthink_engine_config`` and ``senses_engine_config`` will also
    delegate to); t9 lands in parallel with this task, so this helper builds
    the SAME shape locally and SHOULD delegate to ``agent_engine_config`` once
    t9 is merged — a follow-up fold, not part of t14.

    The shape (the t9 contract, applied here):

    - ``model`` ← the binding's resolved model;
    - ``base_url`` ← the role's OWN dial target
      (:func:`colleague.config._role_dial_base_url` over
      :func:`colleague.lobes.resolve_role_base_url`, ``/v1``-shaped like every
      lobes-derived base_url) when a role advert is present, else the
      parent's base_url (no-gateway degrade);
    - ``api_key`` ← the parent's key ONLY when the dial origin
      (scheme+host+port) equals the parent's origin — **same-origin key
      hygiene (#348)**: a different origin gets ``None``, never the parent's
      credential forwarded to a host a wire payload advertised;
    - ``context_budget_tokens`` ← the role advert's ``context`` when present
      (the bigger sliding window is intended, t9), unless the spec carries an
      explicit budget (a per-item override or the t12 width share — explicit
      beats derived);
    - ``refresh_seat=None`` / ``on_delta=None`` (no stale-pin refresh for a
      seat that is not the main seat; no delta sink — the parent's belongs to
      the parent's cockpit);
    - ``role`` ← the typed subagent role; ``chain_episode`` /
      ``chain_prior_changed`` / ``until_done`` reset and ``config_lifecycle``
      frozen exactly as the unarmed path does (see :func:`run_subagent`).

    ``binding=None`` resolves it here (one gateway call); callers that already
    resolved pass it in. Never mutates ``parent_config``.
    """
    if binding is None:
        binding = _resolve_child_binding(parent_config, spec)
    if binding is None:  # pragma: no cover - guarded by the caller's armed check
        raise ValueError("_child_config_for_profile needs an armed parent + a profile")
    base_url = parent_config.base_url
    context_budget = parent_config.context_budget_tokens
    if binding.role_info is not None and binding.gateway_url:
        base_url = _role_dial_base_url(binding.role_info, binding.gateway_url)
        context_budget = int(
            getattr(binding.role_info, "context", context_budget) or context_budget
        )
    api_key = parent_config.api_key if _same_origin(base_url, parent_config.base_url) else None
    replace_kwargs: dict = {
        "model": binding.resolved_model,
        "base_url": base_url,
        "api_key": api_key,
        "context_budget_tokens": (
            spec.context_budget_tokens if spec.context_budget_tokens is not None else context_budget
        ),
        "refresh_seat": None,
        "on_delta": None,
        "role": role,
        "chain_episode": False,
        "chain_prior_changed": (),
        "until_done": False,
        "config_lifecycle": _child_config_lifecycle(parent_config),
    }
    if spec.max_steps is not None:
        replace_kwargs["max_steps"] = spec.max_steps
    child = cast(EngineConfig, dataclasses.replace(parent_config, **replace_kwargs))
    setattr(child, "child_depth", depth)  # q9: never a purpose tool below depth 0
    # #411 t15: a purpose-bearing child carries its purpose so the child engine's
    # resolve_role narrows BOTH halves of its tool surface by purpose (the dormant
    # worker never sees write_file/edit_file); a bare role name carries none.
    from colleague.agents.tools import PURPOSE_TOOLS

    if spec.profile in PURPOSE_TOOLS:
        setattr(child, "agents_profile", spec.profile)
    else:
        # A BARE lobes role name (``cortex``/``muse``/…) switches the child's MODEL,
        # never its tool surface. Carry the PARENT's purpose explicitly: ``agents_profile``
        # is a dynamic attribute, so ``dataclasses.replace`` does not copy it, and an unset
        # child would fall back to ``DEFAULT_ACTING_PURPOSE`` (the FULL thinker_coder
        # surface) in the child's own ``resolve_role`` — a narrow parent would silently
        # widen its child. Inheriting keeps the child's surface == the parent's.
        setattr(child, "agents_profile", _seat_purpose(parent_config))
    # Per-seat thinking effort (#416 t5, c13/h8/c28): the child's own rung is resolved
    # fresh — keyed on the CHILD's role + the CHILD's seat (``binding.model_role``, the
    # resolved lobes role) — never inherited from the parent: ``dataclasses.replace``
    # above already dropped the parent's own ``reasoning_effort_seat`` (a dynamic
    # attribute), so a parent at "off" delegating to a cortex/thinker child does NOT
    # carry that "off" forward (c28) — the child gets the role/seat table's own rung
    # instead, unless the spec carries an explicit per-child override (the highest
    # precedence input, above the tables).
    from colleague import effort as _effort

    setattr(
        child,
        "reasoning_effort_seat",
        _effort.resolve_effort(
            kill_switch=(parent_config.reasoning_effort == "default"),
            parent_override=spec.effort,
            seat_override=parent_config.reasoning_effort_seats.get(binding.model_role),
            role=role,
            seat=binding.model_role,
        ),
    )
    return child


def _parent_ledger(parent_config: EngineConfig):
    """The parent's :class:`~colleague.agents.state.ledger.TaskLedger` when the
    loop wiring (t15) attached an ``agents_ledger_path`` to the armed parent
    config; ``None`` otherwise (events are then skipped silently)."""
    if not getattr(parent_config, "agents", False):
        return None
    path = getattr(parent_config, "agents_ledger_path", None)
    if not path:
        return None
    from colleague.agents.state.ledger import TaskLedger

    return TaskLedger(path)


def _append_ledger_event(ledger, kind: str, data: dict) -> None:
    """Append one delegate/return event; a bookkeeping failure (a torn or
    foreign ledger, an over-size line, an I/O error) never fails the child
    work item — the ledger writer is fail-closed on its own terms, the spawn
    is not the place to lose a child's work over it."""
    if ledger is None:
        return
    from colleague.agents.state.ledger import LedgerUnreadable

    try:
        ledger.append(kind, data)
    except (ValueError, LedgerUnreadable, OSError):
        return


def _minimal_handover(instruction: str) -> str:
    return "\n".join(
        [
            "# Handover summary",
            "",
            "## Objective",
            instruction,
            "",
            "(no task ledger readable — minimal handover: the objective above is "
            "the whole packet)",
        ]
    )


def _child_context(ledger, instruction: str) -> str:
    """The ``context_mode=clear`` packet: t10's handover summary over the
    parent's ledger when one is readable, else the minimal handover."""
    if ledger is None:
        return _minimal_handover(instruction)
    from colleague.agents.state.context import build_handover_summary
    from colleague.agents.state.ledger import LedgerUnreadable

    try:
        read = ledger.read()
    except LedgerUnreadable:
        return _minimal_handover(instruction)
    return build_handover_summary(read.snapshot, read.events)


def make_spawn(
    repo_path: str,
    parent_config: EngineConfig,
    parent_engine: str,
    depth: int = 1,
    *,
    counter: Optional["_AgentBudget"] = None,
    parent_task_id: Optional[str] = None,
    parent_profile: Optional[str] = None,
) -> SpawnFn:
    """Build a depth-bound spawn callback over :func:`run_subagent`.

    The returned closure captures ``repo_path``, ``parent_config``,
    ``parent_engine``, this ``depth`` (the nesting level of the child it will
    launch — top-level children are ``depth=1``), the shared global
    ``counter`` (#t4), and ``parent_task_id`` (spec R6 / plan t16 / #259) — the
    task id every child launched through THIS closure records on its
    ``SubResult.parent``. The loop wiring (t6) calls
    ``make_spawn(task.repo_path, config, task.engine, counter=budget,
    parent_task_id=task.id)`` and assigns the result to
    ``config.subagent_spawn``; the tool executor then calls
    ``spawn(instruction, engine, model, role)`` per delegation.
    ``parent_task_id=None`` (the default) omits lineage — byte-identical to the
    pre-t16 behavior. ``parent_profile`` (#411 t14) is the PARENT's own
    profile/purpose, recorded on every delegate event this closure opens
    (:func:`default_parent_profile` is what the top-level wiring passes);
    ``None`` (the default) keeps callers byte-identical.

    Each launched child is itself handed a spawn callback bound to ``depth + 1``,
    the SAME ``counter``, and ITS OWN task id as ``parent_task_id`` inside
    :func:`run_subagent`, so the depth bound, the global agent budget, and
    lineage are all carried down every level structurally.
    """

    def spawn(
        instruction: str,
        engine: Optional[str] = None,
        model: Optional[str] = None,
        role: Optional[str] = None,
        profile: Optional[str] = None,
        context_mode: str = "inherit",
        effort: Optional[str] = None,
        max_steps: Optional[int] = None,
        context_budget_tokens: Optional[int] = None,
        charges_budget: bool = True,
        web_calls_remaining: Optional[int] = None,
        purpose: Optional[str] = None,
    ) -> SubResult:
        """Run one child subagent, optionally typed by ``role`` (#t4).

        Drives the given instruction through the same bounded tool-loop in an
        isolated throwaway git worktree on a ``sub/<id>`` branch, and returns the
        child's :class:`~colleague.contract.SubResult`. ``profile`` /
        ``context_mode`` (#411 t14) ride onto the :class:`ChildSpec`; both
        default to the pre-t14 shape (no profile, inherit). ``effort`` (#416
        t5) is an explicit per-child thinking-effort override — ``None`` (the
        default) lets the child resolve its rung from the role/seat tables.
        ``max_steps``/``charges_budget`` are the purpose-tool seam (c34) — an
        explicit child budget and the read-only exemption; both default to today.
        ``purpose`` (t8, q3) names the purpose tool this spawn came from,
        exempting the delegation-bounds ``⊆`` rule for its FIXED surface.
        """
        return run_subagent(
            instruction,
            repo_path=repo_path,
            parent_config=parent_config,
            parent_engine=parent_engine,
            depth=depth,
            engine=engine,
            model=model,
            role=role,
            counter=counter,
            spec=ChildSpec(
                parent_task_id=parent_task_id,
                profile=profile,
                context_mode=context_mode,
                parent_profile=parent_profile,
                effort=effort,
                max_steps=max_steps,
                context_budget_tokens=context_budget_tokens,
                purpose=purpose,
                charges_budget=charges_budget,
                web_calls_remaining=web_calls_remaining,
            ),
        )

    # No-wiring seam (mirrors editgate.continuation_id/webbudget.py's own doc):
    # the config THIS closure spawns against, reachable from any executor built
    # with it as ``executor._spawn.parent_config`` — t7 reads
    # ``reasoning_effort_purposes``/``reasoning_effort`` off it for purpose
    # children without threading a new ToolExecutor constructor kwarg.
    spawn.parent_config = parent_config
    # Same no-wiring seam, second reader (t12): the backend name the hire
    # negotiation's candidate completion loads (``colleague/hire_dispatch.py``
    # reads ``executor._spawn.parent_engine`` to bind the tools-off seam).
    spawn.parent_engine = parent_engine
    return spawn


def _build_child_config(
    parent_config: EngineConfig,
    spec: ChildSpec,
    binding: "Optional[_ChildBinding]",
    *,
    model: Optional[str],
    role: Optional[str],
    depth: int = 1,
) -> EngineConfig:
    """The child's EngineConfig: the armed cross-role dial (#411 t14) when a
    binding resolved, else the legacy ``dataclasses.replace`` (byte-identical)."""
    if binding is not None:
        child_config = _child_config_for_profile(
            parent_config, spec, binding, role=role, depth=depth
        )
        if model:
            # An explicit model override from the caller still wins (the
            # flag > env > config precedence, applied to the child seat).
            child_config.model = model
        child_config.web_calls_remaining = spec.web_calls_remaining  # t7
        return child_config
    replace_kwargs: dict = {
        "model": (model or parent_config.model),
        "role": role,
        "chain_episode": False,
        "chain_prior_changed": (),
        "until_done": False,
        "config_lifecycle": _child_config_lifecycle(parent_config),
    }
    if spec.max_steps is not None:
        replace_kwargs["max_steps"] = spec.max_steps
    if spec.context_budget_tokens is not None:
        replace_kwargs["context_budget_tokens"] = spec.context_budget_tokens
    child = cast(EngineConfig, dataclasses.replace(parent_config, **replace_kwargs))
    if getattr(parent_config, "agents", False):
        # ARMED, no binding (no profile named): the child inherits the PARENT's
        # purpose — ``agents_profile`` is dynamic, ``dataclasses.replace`` drops
        # it, and ``resolve_role`` would widen a narrow parent's child to the
        # full ``thinker_coder`` surface (a hole the bounds check never sees).
        setattr(child, "agents_profile", _seat_purpose(parent_config))
    # Per-seat thinking effort (#416 t5, c13/h8/c28): the bare-role build has
    # no lobes binding, so the child's seat is the cortex floor (the armed-
    # profile builder's rule with a fixed seat name); the rung is resolved
    # fresh (``dataclasses.replace`` dropped the parent's), keyed on the
    # CHILD's typed role, the spec's explicit override winning above the tables.
    from colleague import effort as _effort

    setattr(
        child,
        "reasoning_effort_seat",
        _effort.resolve_effort(
            kill_switch=(parent_config.reasoning_effort == "default"),
            parent_override=spec.effort,
            seat_override=parent_config.reasoning_effort_seats.get("cortex"),
            role=role,
            seat="cortex",
        ),
    )
    scouted = _associate_seats.scout_child_config(
        parent_config, child, role, effort_override=spec.effort
    )
    scouted.web_calls_remaining = spec.web_calls_remaining  # t7: c33/h32
    setattr(scouted, "child_depth", depth)  # q9: never a purpose tool below depth 0
    return scouted


def _thread_sidecar_repo(
    parent_config: EngineConfig, spec: ChildSpec, child_task: Task, child_config: EngineConfig
) -> None:
    """Thread the operator-repo sidecar destination one hop (effort-v4 t6, h20).

    The child's reasoning sidecar lands TAGGED in the operator repo's
    ``.colleague/`` — surviving child-worktree removal — via the
    ``flight_repo_path`` pattern: ``_arm_delegation`` attached the operator
    repo to the parent config (a dynamic attr, the ``agents_ledger_path``
    precedent; ``replace`` drops it, so it is re-attached to the child config
    for grandchildren). Absent (a direct ``run_subagent`` caller), the child's
    sidecar stays under its own ``repo_path`` — model context is untouched
    either way (h7).
    """
    sidecar_repo = getattr(parent_config, "reasoning_repo_path", None)
    child_task.reasoning_repo_path = sidecar_repo
    child_task.reasoning_parent_id = spec.parent_task_id
    if sidecar_repo:
        setattr(child_config, "reasoning_repo_path", sidecar_repo)


def run_subagent(
    instruction: str,
    *,
    repo_path: str,
    parent_config: EngineConfig,
    parent_engine: str,
    depth: int,
    engine: Optional[str] = None,
    model: Optional[str] = None,
    role: Optional[str] = None,
    counter: Optional["_AgentBudget"] = None,
    spec: Optional[ChildSpec] = None,
) -> SubResult:
    """Run one nested child work item and return its :class:`SubResult`.

    ``spec`` (a :class:`ChildSpec`) bundles the per-child extras: the explicit
    t12 budget (``max_steps`` / ``context_budget_tokens`` — ``None`` inherits
    the parent's value unchanged, byte-identical to pre-scaling), the t16
    ``goal`` / ``acceptance`` (spec R6 / plan t16 / #259), threaded onto the
    child's own ``Task`` unchanged, so the loop's t15 goal/acceptance prompt
    block and the advisory acceptance self-check fire for this child exactly as
    they would for a top-level work item (``None`` — the pre-t16 behavior and
    the single-child ``subagent`` tool path — builds a byte-identical goal-less
    child ``Task``), and ``parent_task_id``, which when given is recorded on
    the returned ``SubResult.parent`` — the IMMEDIATE parent's task id (not
    necessarily the top-level root), so a subagent tree is walkable one hop at
    a time from artifacts alone. ``None`` (the default) omits ``parent`` from
    the serialized result, byte-identical to the pre-lineage behavior.

    ``depth`` is the nesting level of THIS child (top-level children = 1). Two
    structural caps are enforced *first, before any work* — a refused child does
    zero work and starts no child work item, guaranteeing termination: the
    per-path **depth** cap (:data:`~colleague.config.MAX_SUBAGENT_DEPTH`), and
    the shared **global agent budget** (#t4) — a threaded ``counter`` is charged
    once here, refusing a child that would push the TOTAL agents spawned under
    the top-level work item past :data:`~colleague.config.MAX_SUBAGENT_TOTAL`
    (``counter=None`` skips the budget, byte-identical to before).

    The child engine is ``engine or parent_engine``, resolved through
    :func:`colleague.registry.load`. The child config inherits the parent's
    unchanged except the model (switched when provided) and the typed ``role``
    (#t4) — both pure config-level switches with no engine code change. The
    engine builds the child's curated tool schema + role-composed prompt from
    ``config.role`` (t8). The child gets its own ``subagent_spawn``/
    ``subagent_batch_spawn`` bound to ``depth + 1``, the SAME ``counter``, and
    ``parent_task_id`` set to THIS child's own task id, so it can delegate
    further (nested batches permitted), still globally bounded.

    **Cross-role dial (#411 t14).** When the parent's ``agents`` mode is armed
    AND ``spec.profile`` is set, the child's config is built by
    :func:`_child_config_for_profile` instead (the role's own dial target,
    model and advertised context; the parent's api_key ONLY toward the same
    origin, #348; a recorded fallback to cortex/main when the role is absent,
    not ready, dormant, or the gateway is unreachable); the returned
    ``SubResult`` then carries ``agent_id``/``resolved_model``/
    ``fallback_from_role``; a ``delegate``/``return`` ledger event pair
    brackets the child run (when ``agents_ledger_path`` is attached; skipped
    silently otherwise); ``context_mode="clear"`` hands the child the t10
    handover summary as its ``Task.context`` (``inherit`` = today). Unarmed,
    or armed without a profile, is the EXISTING path byte-identical.

    The work item runs via ``engine.work`` — the bounded loop, **no** git handoff,
    fully synchronous.
    """
    # (a) Depth cap FIRST — before loading an engine or building any config, so a
    # refused level does zero work and starts no child work item.
    if depth > MAX_SUBAGENT_DEPTH:
        raise SubagentError(f"subagent depth limit ({MAX_SUBAGENT_DEPTH}) exceeded")

    # (a2) Global agent budget NEXT — also before any work. Charging is atomic
    # (thread-safe) so concurrent batch children can't race past the cap; it is
    # skipped with no counter, or for a read-only purpose child (c34).
    spec = spec or ChildSpec()

    # (a3) Delegation bounds (t11 enforcement) BEFORE the budget charge, so a
    # refused delegation never burns a slot the counter can't refund: a child
    # may only ever NARROW its parent's tool surface and authority ceiling.
    bounds = _enforce_delegation_bounds(
        parent_config, spec, instruction=instruction, depth=depth, role=role
    )

    if counter is not None and spec.charges_budget:
        counter.charge()

    # (b) Resolve + load the child engine by name. A bad name surfaces as a clean
    # SubagentError (never an unrelated crash upstream).
    child_engine = engine or parent_engine
    try:
        eng = registry.load(child_engine)
    except registry.UnknownEngine as exc:
        raise SubagentError(str(exc)) from exc

    # (c) Inherit the parent's config, overriding ONLY the model, the typed role,
    # and (t12) an explicit child budget when the caller provides one — the batch
    # path passes the width-scaled share here, and a per-item override wins over
    # that share upstream. dataclasses.replace keeps base_url/api_key/... intact
    # and leaves the parent object untouched (the cast is purely for the static
    # analyser: Sonar models replace()'s return as a generic DataclassInstance).
    #
    # ``chain_episode``/``chain_prior_changed``/``until_done`` are reset UNCONDITIONALLY
    # (#335/#337, c22): ``execute_work`` sets those runtime-only fields on
    # ``parent_config`` IN PLACE for an armed ``--until-done`` chain episode, so a naive
    # ``replace`` would otherwise copy the marker/flag onto every child — a child is
    # never itself a chain episode and must never arm the loop's fill-line consumers.
    #
    # ``config_lifecycle`` is ALSO reset UNCONDITIONALLY (plan t10, c35/h28): the parent's
    # attachment (the REAL ``EpisodeConfigLifecycle`` or an inherited
    # ``FrozenChildConfigLifecycle``) is never handed to a child as-is — that would let it
    # reach ``propose``/``apply_window``, which the r2 rule (children never propose, never
    # observe turns) forbids. Always set explicitly, even to ``None``, never an accident.
    #
    # (c2) ARMED cross-role dial (#411 t14): with ``agents`` armed and a
    # ``profile`` on the spec, the child config comes from
    # ``_child_config_for_profile`` instead — same resets, plus the role dial,
    # the per-role key hygiene and the advertised context. ``binding`` stays
    # ``None`` on the unarmed path, which is byte-identical to today.
    binding = _resolve_child_binding(parent_config, spec)
    child_config = _build_child_config(
        parent_config, spec, binding, model=model, role=role, depth=depth
    )

    # (c3) The parent's task ledger (armed + attached by the loop wiring, t15)
    # and the child's context packet: ``clear`` → the t10 handover summary (or
    # the minimal handover when no ledger is readable); ``inherit`` → "" today.
    ledger = _parent_ledger(parent_config) if binding is not None else None
    child_context = ""
    if binding is not None and spec.context_mode == "clear":
        child_context = _child_context(ledger, instruction)

    # (d) Build the child's own Task FIRST (goal/acceptance carried structurally,
    # t16), so its id is known when we build ITS nested spawn/batch-spawn
    # callbacks below — a grandchild's lineage names ITS parent, not the root.
    child_task = Task.new(
        repo_path,
        instruction,
        engine=child_engine,
        context=child_context,
        goal=spec.goal,
        acceptance=list(spec.acceptance) if spec.acceptance is not None else None,
    )
    # The child's agent identity (armed only): stable for the child's life,
    # derived from its task id so a SubResult/ledger reader can join the two.
    agent_id = f"agent-{child_task.id}" if binding is not None else None

    # (d2) Reasoning-sidecar threading (effort-v4 t6, h20): the child's sidecar
    # lands TAGGED in the operator repo's ``.colleague/`` — surviving
    # child-worktree removal — via the ``flight_repo_path`` pattern carried one
    # hop: ``_arm_delegation`` attached the operator repo to the parent config
    # (a dynamic attr, the ``agents_ledger_path`` precedent; ``replace`` drops
    # it, so it is re-attached to the child config for grandchildren below).
    # Absent (a direct ``run_subagent`` caller), the child's sidecar stays
    # under its own ``repo_path`` — model context is untouched either way (h7).
    _thread_sidecar_repo(parent_config, spec, child_task, child_config)

    # (e) Give the child its OWN spawn + batch-spawn callbacks bound to depth + 1
    # and the SAME global budget, so it can delegate further (single OR batch),
    # still bounded by both the depth cap and the shared agent budget. Nested
    # batches are PERMITTED (#t4): the child's batch closure is bound to the
    # CHILD's repo_path/depth/counter, so a child batch runs against the correct
    # worktree, increments depth, and counts against the one global budget.
    # ``parent_task_id=child_task.id`` (t16): a grandchild's lineage points at
    # THIS child, not the root.
    child_config.subagent_spawn = make_spawn(
        repo_path,
        child_config,
        child_engine,
        depth + 1,
        counter=counter,
        parent_task_id=child_task.id,
        parent_profile=spec.profile,
    )
    child_config.subagent_batch_spawn = make_batch_spawn(
        repo_path,
        child_config,
        child_engine,
        depth + 1,
        counter=counter,
        parent_task_id=child_task.id,
        parent_profile=spec.profile,
    )

    # (e2) ``delegate`` BEFORE the child runs (armed + ledger attached only):
    # the open loop the replayed snapshot shows until ``return`` closes it.
    if binding is not None:
        _append_ledger_event(
            ledger,
            "delegate",
            _delegate_event_data(
                child_task.id,
                spec,
                binding,
                agent_id,
                bounds,
                resolved_effort=getattr(child_config, "reasoning_effort_seat", None),
            ),
        )

    # (f) Run the nested child work item. engine.work runs the bounded loop
    # and never hands off; the call is synchronous (no thread/process/socket).
    result = eng.work(child_task, child_config)

    # (f2) ``return`` AFTER — closes the delegation on the parent's ledger.
    if binding is not None:
        _append_ledger_event(
            ledger,
            "return",
            {
                "id": child_task.id,
                "ref": f"task:{result.task_id}",
                "status": result.status,
                "changed_files": len(result.changed_files),
                "agent_id": agent_id,
            },
        )

    # (g) Project the child's TaskResult onto SubResult (armed-only fields omit-when-None).
    sub = SubResult(
        task_id=result.task_id,
        engine=child_engine,
        model=child_config.model,
        status=result.status,
        summary=result.summary,
        changed_files=list(result.changed_files),
        usage=result.usage,
        role=role,
        parent=spec.parent_task_id,
        agent_id=agent_id,
        resolved_model=(binding.resolved_model if binding is not None else None),
        fallback_from_role=(binding.fallback_from_role if binding is not None else None),
        # t5 (c6): the built child seat's resolved rung — read, never recomputed.
        reasoning_effort=getattr(child_config, "reasoning_effort_seat", None),
    )
    # t13: raw incompletion reason (dynamic attr) — purpose_schemas keys its marker on it.
    sub.incompletion_reason = getattr(getattr(result, "incompletion", None), "reason", None)
    # t7 (c33/h32): dynamic attrs, no contract.py field — the child's web-call
    # counters (fold onto the parent's executor) and its fetched urls (the
    # parent's 'urls fetched:' report block), read off the child's OWN
    # TaskResult, which SubResult otherwise never carries.
    web_schemas.attach_web_report(sub, result)
    return sub


def _spawn_children(
    items: List[dict],
    child_ids: List[str],
    width: int,
    *,
    repo_path: str,
    parent_config: EngineConfig,
    parent_engine: str,
    depth: int,
    role: Optional[str],
    counter: Optional["_AgentBudget"],
    parent_task_id: Optional[str] = None,
    parent_profile: Optional[str] = None,
) -> List[Optional[SubResult]]:
    """Run every batch child and return the results in INPUT ORDER.

    Sequential when ``width <= 1`` (no ``ThreadPoolExecutor`` ever — byte-identical
    to the pre-concurrency path); concurrent when ``width > 1`` via a
    module-confined ``ThreadPoolExecutor`` whose results are collected after the
    join. Extracted from :func:`_run_batch` to keep that function's cognitive
    complexity within budget (SonarCloud S3776) and to DRY the per-child args.
    """
    results: List[Optional[SubResult]] = [None] * len(items)

    # Width-scaled default budget share (t12): computed once for the batch;
    # (None, None) at width <= 1, so the sequential path stays byte-identical.
    share_steps, share_budget = _child_budget_share(parent_config, width)

    def _run_one(i: int) -> SubResult:
        item = items[i]
        return _run_child_in_worktree(
            repo_path,
            child_ids[i],
            str(item.get("instruction", "")),
            parent_config=parent_config,
            parent_engine=parent_engine,
            depth=depth,
            engine=(item.get("engine") or None),
            model=(item.get("model") or None),
            role=(item.get("role") or role),
            counter=counter,
            spec=_build_child_spec(
                item,
                share_steps=share_steps,
                share_budget=share_budget,
                parent_task_id=parent_task_id,
                parent_profile=parent_profile,
            ),
        )

    if width <= 1:
        for i in range(len(items)):
            results[i] = _run_one(i)
        return results

    with concurrent.futures.ThreadPoolExecutor(max_workers=width) as pool:
        future_index = {pool.submit(_run_one, i): i for i in range(len(items))}
        # Join: collect every result AFTER the threads finish. future.result()
        # re-raises a worker exception in the main thread, where _run_batch's
        # finally still tears worktrees down.
        for fut in concurrent.futures.as_completed(future_index):
            results[future_index[fut]] = fut.result()
    return results
