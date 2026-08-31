"""The subagent launcher — nested in-process child work items, depth-bounded.

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
from colleague import registry, web_schemas, worktrees
from colleague.agents.profile import DORMANT_PURPOSES, PURPOSE_ROLE, PURPOSES
from colleague.agents.state.context import CONTEXT_MODES
from colleague.config import (
    MAX_SUBAGENT_DEPTH,
    MAX_SUBAGENT_FANOUT,
    MAX_SUBAGENT_TOTAL,
    EngineConfig,
    _role_dial_base_url,
    _same_origin,
    effective_concurrency,
)
from colleague.configlifecycle import EpisodeConfigSnapshot
from colleague.contract import ERROR, OK, SubResult, Task, Usage
from colleague.design import design_seat_config as _design_seat_config
from colleague.roles import is_read_only

# Floors for the width-scaled child budget share (t12 / spec R5): a child's
# share is clamped so scaling can never hand a child an unworkable budget —
# and never MORE than the parent's own value (a tiny parent budget stays the
# ceiling, floors notwithstanding).
_MIN_CHILD_MAX_STEPS = 10
_MIN_CHILD_CONTEXT_BUDGET = 16000


@dataclasses.dataclass(frozen=True)
class ChildSpec:
    """Per-child delegation extras for ONE nested child work item.

    Bundles the switches that accreted beyond the original engine/model/role
    trio — the explicit t12 budget, the t16 goal contract, and t16 lineage —
    so the launcher signatures stay under the S107 parameter ceiling (the
    ``ContextControls`` precedent). Every field defaults to ``None``: an
    empty spec is byte-identical to the pre-t12/t16 behavior."""

    max_steps: Optional[int] = None
    context_budget_tokens: Optional[int] = None
    goal: Optional[str] = None
    acceptance: Optional[List[str]] = None
    parent_task_id: Optional[str] = None
    #: Model-bound agents (#411, plan task t14): the child's *profile* — a purpose
    #: name from :data:`colleague.agents.profile.PURPOSES` (``talker`` / ``worker`` /
    #: ``thinker_coder`` / ``associate``) or a bare bindable lobes role name
    #: (:data:`BINDABLE_ROLES`). ``None`` (the default) = no profile: the child
    #: inherits the parent seat exactly as today; INERT unless ``agents`` is armed.
    profile: Optional[str] = None
    #: ``inherit`` (the default, today's behaviour) or ``clear`` (the child
    #: receives the handover summary — t10 — as its ``Task.context`` instead
    #: of the parent's transcript). Anything else is refused whole.
    context_mode: str = "inherit"
    #: The PARENT's own profile/purpose (lineage one hop up), recorded on the
    #: child's ``delegate`` event as ``from_profile``; threaded by
    #: :func:`make_spawn` / :func:`make_batch_spawn`'s ``parent_profile``.
    parent_profile: Optional[str] = None
    #: An explicit per-child thinking-effort override (#416 t5, c28/h19) — one
    #: of :data:`colleague.effort.LADDER` or the kill-switch sentinel
    #: ``"default"``. ``None`` (the default) means "no override": the child's
    #: builder resolves its effort from the role/seat tables instead. Threaded
    #: from the ``subagent``/``subagents`` tool args (:mod:`colleague.tools`)
    #: as ``resolve_effort``'s ``parent_override`` — the HIGHEST-precedence
    #: input, above the role/seat tables.
    effort: Optional[str] = None
    #: Whether this child consumes a slot of the shared delegation budget
    #: (``MAX_SUBAGENT_FANOUT`` / ``MAX_SUBAGENT_TOTAL``). ``True`` (the
    #: default) is every manual delegation — byte-identical. ``False`` is
    #: the purpose-tool arithmetic exemption
    #: (purpose-tools-associate-seat, c34). The DEPTH cap always applies.
    charges_budget: bool = True
    #: The ONE work-item-wide web budget this child inherits (t7, c33/h32):
    #: ``COLLEAGUE_WEB_MAX_CALLS - parent.web_calls`` at spawn time, or
    #: ``None`` (the default) - today's per-executor budget, byte-identical
    #: for every manual ``subagent``/``subagents`` call.
    web_calls_remaining: Optional[int] = None
    #: The purpose-tool name (t8, q3) when spawned BY a purpose tool — exempts
    #: the armed ``⊆``-parent check for its FIXED child surface; ``None`` for
    #: a manual ``subagent``/``subagents`` delegation, which stays subject to it.
    purpose: Optional[str] = None

    def __post_init__(self) -> None:
        if self.context_mode not in CONTEXT_MODES:
            raise ValueError(
                f"unknown context_mode: {self.context_mode!r} (expected one of {CONTEXT_MODES})"
            )
        if self.profile is not None and (
            self.profile not in PURPOSES and self.profile not in BINDABLE_ROLES
        ):
            raise ValueError(
                f"unknown profile: {self.profile!r} (expected a purpose in "
                f"{sorted(PURPOSES)} or a lobes role in {sorted(BINDABLE_ROLES)})"
            )
        if self.effort is not None:
            from colleague import effort as _effort

            _effort.validate_effort(self.effort)


#: The lobes roles a child ``profile`` may name DIRECTLY (a bare role name
#: instead of a purpose). Chat-capable seats only — ``stt``/``tts``/
#: ``embedder`` are not seats a child work item can run on.
BINDABLE_ROLES = frozenset({"cortex", "senses", "worker", "muse", "associate"})

#: The floor role every profile falls back to (spec q1: cortex runs ALL roles
#: for now) — mirrors ``colleague.agents.profile._FALLBACK_ROLE``.
_FALLBACK_ROLE = "cortex"


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


class SubagentError(Exception):
    """A subagent launch was refused — e.g. the depth or global-budget cap was exceeded."""


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


def decomposition_seat_config(config: EngineConfig) -> EngineConfig:
    """The 'subagents.decompose' design call-site seat (#416 t6, c14/h9): xhigh.

    Honest limit: this module dispatches each child as a full ``Task`` through
    ``Engine.work`` (:func:`make_spawn`/:func:`make_batch_spawn`), so a child's
    OWN completion is built by the engine at the child's own role/seat effort
    (t5) — there is no separate "decide how to decompose" completion in this
    module to route through the design seat instead. This builder is pinned
    here, ready for a future dedicated decomposition-planning call; it is
    unit-tested at the builder level (``tests/test_design_call_site.py``), not
    exercised end-to-end.
    """
    return _design_seat_config(config, "subagents.decompose")


# ---------------------------------------------------------------------------
# Cross-role dial (#411, plan task t14): a child may bind a different lobes role.
# ---------------------------------------------------------------------------


def default_parent_profile(config: EngineConfig) -> Optional[str]:
    """The profile the TOP-LEVEL spawn wiring hands to :func:`make_spawn` /
    :func:`make_batch_spawn` as ``parent_profile``.

    Unarmed (``config.agents`` False) → ``None`` — byte-identical to today.
    Armed → an explicit ``config.agents_profile`` attribute when the loop
    wiring (t15) set one, else ``thinker_coder`` (cortex runs the acting seat
    today, spec q1). Every caller passes this so every spawn path carries the
    parent's purpose.
    """
    if not getattr(config, "agents", False):
        return None
    explicit = getattr(config, "agents_profile", None)
    return str(explicit) if explicit else "thinker_coder"


def _seat_purpose(config: EngineConfig) -> str:
    """The purpose whose tool surface THIS seat's own loop narrows itself to.

    Read back from the same place the loop's ``resolve_role`` reads it (t15):
    an explicit ``agents_profile`` attribute, else the acting default
    (``thinker_coder``, the full surface). Parent and child are therefore
    always ranked on the SAME rule.
    """
    from colleague.agents.runtime import DEFAULT_ACTING_PURPOSE

    return str(getattr(config, "agents_profile", None) or DEFAULT_ACTING_PURPOSE)


def _child_purpose(parent_config: EngineConfig, spec: ChildSpec) -> str:
    """The purpose the CHILD seat will actually run on.

    Its own when ``spec.profile`` names one; otherwise the PARENT's — a bare
    lobes role name switches the model, never the tool surface, and a spawn
    with NO profile inherits the parent's seat (the ``subagent`` tool's own
    documented contract). Never ``DEFAULT_ACTING_PURPOSE``: defaulting there
    would silently widen a narrow parent's child to the full surface.
    """
    from colleague.agents.tools import PURPOSE_TOOLS

    if spec.profile in PURPOSE_TOOLS:
        return str(spec.profile)
    return _seat_purpose(parent_config)


def _child_requested_tools(
    spec: ChildSpec,
    child_purpose: str,
    role: Optional[str],
    parent_config: Optional[EngineConfig] = None,
) -> tuple[str, ...]:
    """Requested tools for the ``⊆`` check (t8, q3): a purpose spawn's FIXED
    role-allowlist-∩-environment surface (via ``curate_schemas``, the same
    filter ``web``'s presence check applies) — else today's profile tools."""
    if spec.purpose:
        from colleague.tools import curate_schemas

        return tuple(sorted(s["function"]["name"] for s in curate_schemas(role)))
    from colleague.agents.tools import tools_for_purpose

    return tuple(sorted(tools_for_purpose(child_purpose, parent_config)))


def _delegation_bounds(
    parent_config: EngineConfig,
    spec: ChildSpec,
    *,
    instruction: str,
    depth: int,
    role: Optional[str],
) -> tuple[str, str, tuple[str, ...], "object"]:
    """``(child_purpose, child_ceiling, requested_tools, verdict)`` for one delegation."""
    from colleague.agents.delegation import DelegationRequest, validate_delegation
    from colleague.agents.runtime import seat_ceiling
    from colleague.agents.tools import tools_for_purpose

    parent_purpose = _seat_purpose(parent_config)
    child_purpose = _child_purpose(parent_config, spec)
    # The child inherits the parent's publish intent; only its ROLE can lower
    # the ceiling further, so the child's ceiling is ranked off the parent's
    # config with the CHILD's role applied.
    child_ceiling = seat_ceiling(parent_config, role)
    requested_tools = _child_requested_tools(spec, child_purpose, role)
    request = DelegationRequest(
        delegation_id="",  # validation only — nothing is recorded from here
        from_agent=spec.parent_profile or parent_purpose,
        requested_agent_profile=spec.profile or child_purpose,
        objective=instruction,
        acceptance="",
        requested_tools=requested_tools,
        authority_ceiling=child_ceiling,
        context_mode=spec.context_mode,
        depth=depth,
        purpose=spec.purpose,
    )
    verdict = validate_delegation(
        request,
        parent_effective_tools=tools_for_purpose(parent_purpose),
        parent_ceiling=seat_ceiling(parent_config, getattr(parent_config, "role", None)),
    )
    return child_purpose, child_ceiling, requested_tools, verdict


def _enforce_delegation_bounds(
    parent_config: EngineConfig,
    spec: ChildSpec,
    *,
    instruction: str,
    depth: int,
    role: Optional[str],
) -> tuple[tuple[str, ...], str]:
    """Validate ONE armed delegation against the parent's bounds — refuse whole.

    Returns the ``(requested_tools, authority_ceiling)`` the delegation was
    ranked on, for the ``delegate`` event to record (empty when unarmed).

    The enforcement half of t11 (Qodo, PR #414): ``validate_delegation`` owned
    the arithmetic — child tools ``⊆`` parent tools, child ceiling ``≤``
    parent ceiling, depth/fanout/total within the ``MAX_SUBAGENT_*`` caps,
    ``context_mode`` in the closed set — but nothing on the spawn path called
    it, so a narrow parent could hand a child a WIDER surface by naming a
    different profile (a ``worker`` seat, which holds no ``write_file`` /
    ``edit_file``, delegating a ``thinker_coder`` child that does).

    Called on EVERY armed spawn — gated on ``config.agents``, NOT on a
    declared profile: a delegation that omits ``profile`` inherits the
    parent's seat, and gating on the profile would have let the model skip the
    check by simply not naming one. Runs BEFORE the global budget charge,
    before the ``delegate`` event and before the child engine runs, so a
    refused delegation costs nothing, records nothing and spawns nothing.
    Refusal surfaces as :class:`SubagentError` — the same clean, model-visible
    refusal as the depth and budget caps. Because a non-subset REFUSES, the
    child's surface is a subset of the parent's by construction.

    Two bounds are deliberately NOT re-derived here: ``fanout``/``total`` (the
    shared ``_AgentBudget`` charges and refuses them upstream, before any work —
    and a ``charges_budget=False`` purpose child is exempt from exactly those
    two, c34) and the ``_NOT_INHERITABLE`` tool classes (nested delegation is
    explicitly permitted — a child gets its own depth-bound spawn callbacks).
    Alignment is not permission: the host's policy/approval gate still gates
    every route this allows.
    """
    if not getattr(parent_config, "agents", False):
        return (), ""  # unarmed: no purposes, no bounds — byte-identical today
    child_purpose, ceiling, requested_tools, verdict = _delegation_bounds(
        parent_config, spec, instruction=instruction, depth=depth, role=role
    )
    if not verdict.allowed:
        raise SubagentError(
            f"delegation refused: {child_purpose!r} under "
            f"{_seat_purpose(parent_config)!r} — {verdict.reason}"
        )
    return requested_tools, ceiling


@dataclasses.dataclass(frozen=True)
class _ChildBinding:
    """How ONE child's ``profile`` resolved — the trace record behind the armed
    child config and the ``SubResult.agent_id`` / ``resolved_model`` /
    ``fallback_from_role`` fields.

    ``role_info`` is the lobes ``RoleInfo`` the child dials (``None`` when the
    gateway was absent/unreachable — the child then stays on the parent's
    main endpoint). ``gateway_url`` is the gateway the roles came from.
    """

    profile: str
    requested_role: str
    model_role: str
    resolved_model: str
    fallback_from_role: Optional[str]
    role_info: object
    gateway_url: Optional[str]


def _requested_role(profile: str) -> str:
    """The lobes role a profile names: a purpose maps through the enumerated
    :data:`~colleague.agents.profile.PURPOSE_ROLE` table; a bare role name is
    itself."""
    return PURPOSE_ROLE[profile] if profile in PURPOSES else profile


def _resolve_child_binding(parent_config: EngineConfig, spec: ChildSpec) -> Optional[_ChildBinding]:
    """Resolve ``spec.profile`` against the lobes gateway — ``None`` when unarmed.

    Armed (``parent_config.agents`` True) AND ``spec.profile`` set, the roles
    come from :func:`colleague.lobes.resolve_roles` over the parent's
    ``lobes_gateway_url``; the requested role binds when present AND ready,
    else the child is carried on the cortex model under a RECORDED fallback
    (``fallback_from_role`` = the requested role — the
    :func:`colleague.agents.profile.resolve_profile` doctrine: fallback, never
    refusal, never silent). Two further rules:

    - **d3 dormancy**: a DORMANT purpose (``worker``) is NEVER bound even when
      its role is ready — it resolves to the cortex floor, fallback recorded.
    - **no gateway** (unarmed lobes, or unreachable): the child degrades to
      the parent's MAIN model/endpoint with the fallback recorded; a
      ``thinker_coder``/``cortex`` profile on the main seat records no
      fallback (it IS the floor).

    Pure except for the one GET :func:`colleague.lobes.resolve_roles` issues
    (which never raises — it degrades to ``None``).
    """
    profile = spec.profile
    if not getattr(parent_config, "agents", False) or profile is None:
        return None
    # Lazy import: keeps the unarmed import graph of this module byte-identical
    # (lobes pulls urllib) and lets tests monkeypatch the gateway resolver.
    from colleague import lobes as _lobes

    requested = _requested_role(profile)
    gateway = getattr(parent_config, "lobes_gateway_url", None)
    roles = _lobes.resolve_roles(gateway) if gateway else None
    if roles is None:
        # Gateway absent/unreachable: the parent's main seat IS the floor.
        return _ChildBinding(
            profile=profile,
            requested_role=requested,
            model_role=_FALLBACK_ROLE,
            resolved_model=parent_config.model,
            fallback_from_role=(requested if requested != _FALLBACK_ROLE else None),
            role_info=None,
            gateway_url=None,
        )
    role = getattr(roles, requested, None)
    dormant = profile in DORMANT_PURPOSES or requested in DORMANT_PURPOSES
    if role is not None and getattr(role, "ready", False) and not dormant:
        return _ChildBinding(
            profile=profile,
            requested_role=requested,
            model_role=requested,
            resolved_model=role.model,
            fallback_from_role=None,
            role_info=role,
            gateway_url=gateway,
        )
    floor = getattr(roles, _FALLBACK_ROLE)
    return _ChildBinding(
        profile=profile,
        requested_role=requested,
        model_role=_FALLBACK_ROLE,
        resolved_model=floor.model,
        fallback_from_role=(requested if requested != _FALLBACK_ROLE else None),
        role_info=floor,
        gateway_url=gateway,
    )


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


def _delegate_event_data(
    child_task_id: str,
    spec: ChildSpec,
    binding: "_ChildBinding",
    agent_id: Optional[str],
    bounds: tuple[tuple[str, ...], str] = ((), ""),
    resolved_effort: Optional[str] = None,
) -> dict:
    """The ``delegate`` ledger event payload for an armed child (#411 t14).

    ``resolved_effort`` (#416 t5, c28/h19) is the CHILD's resolved thinking-
    effort rung (the same value :func:`_child_config_for_profile` set as the
    child config's ``reasoning_effort_seat``) — recorded beside
    ``effort_override`` (``True`` when ``spec.effort`` named an explicit
    per-child override, the highest-precedence input) so a ledger replay can
    audit not just the tools/ceiling a delegation was ranked on but the
    effort it actually ran with.
    """
    return {
        "id": child_task_id,
        "delegation_id": child_task_id,
        "child_ref": f"sub/{child_task_id}",
        "profile": binding.profile,
        "context_mode": spec.context_mode,
        "from_profile": spec.parent_profile,
        "agent_id": agent_id,
        "model_role": binding.model_role,
        "resolved_model": binding.resolved_model,
        "fallback_from_role": binding.fallback_from_role,
        # What the t11 bounds check ranked this delegation on, so a ledger
        # replay can audit the decision instead of taking it on trust.
        "requested_tools": list(bounds[0]),
        "authority_ceiling": bounds[1],
        "effort": resolved_effort,
        "effort_override": spec.effort is not None,
    }


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
    )
    # t13: raw incompletion reason (dynamic attr) — purpose_schemas keys its marker on it.
    sub.incompletion_reason = getattr(getattr(result, "incompletion", None), "reason", None)
    # t7 (c33/h32): dynamic attrs, no contract.py field — the child's web-call
    # counters (fold onto the parent's executor) and its fetched urls (the
    # parent's 'urls fetched:' report block), read off the child's OWN
    # TaskResult, which SubResult otherwise never carries.
    web_schemas.attach_web_report(sub, result)
    return sub


# ---------------------------------------------------------------------------
# Parallel batch orchestration: per-worktree children + sequential merge child.
# ---------------------------------------------------------------------------


def _positive_int_or_none(value: object) -> Optional[int]:
    """A positive int, or None (bools and non-ints are not budgets)."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value > 0 else None


def _child_budget_share(
    parent_config: EngineConfig, width: int
) -> tuple[Optional[int], Optional[int]]:
    """The per-child ``(max_steps, context_budget_tokens)`` share at *width*.

    ``(None, None)`` at width <= 1 — the sequential path inherits the parent's
    full budget unchanged (byte-identical, h5). At width > 1 each concurrent
    child gets ``parent // width``, floored at the ``_MIN_CHILD_*`` constants
    but never above the parent's own value, so W concurrent children stop
    scheduling W full parent budgets against one served model (spec R5).
    """
    if width <= 1:
        return None, None
    steps = min(
        parent_config.max_steps,
        max(_MIN_CHILD_MAX_STEPS, parent_config.max_steps // width),
    )
    budget = min(
        parent_config.context_budget_tokens,
        max(
            _MIN_CHILD_CONTEXT_BUDGET,
            parent_config.context_budget_tokens // width,
        ),
    )
    return steps, budget


def _batch_all_read_only(items: List[dict], batch_role: Optional[str]) -> bool:
    """True when every child's effective role is a read-only builtin.

    The effective role mirrors ``_spawn_children``: the item's own ``role``,
    falling back to the batch-level role. Read-only children provably cannot
    write (role-withheld tools), so the batch's merge child is structurally a
    no-op over empty diffs.
    """
    if not items:
        return False
    return all(is_read_only(item.get("role") or batch_role) for item in items)


def _resolve_batch_width(
    parent_config: EngineConfig, items: List[dict], batch_role: Optional[str]
) -> int:
    """Effective concurrency width for a batch (t12).

    Normally ``effective_concurrency`` clamps to ``MAX_SUBAGENT_FANOUT - 1`` —
    one fan-out slot stays reserved for the merge child. A batch whose children
    are ALL read-only roles frees that reservation (its merge is a no-op), so
    its width may use the full ``MAX_SUBAGENT_FANOUT``. Always clamped to the
    item count; width 1 (the default) never touches a thread pool.
    """
    if _batch_all_read_only(items, batch_role):
        width = min(max(1, parent_config.subagent_concurrency), MAX_SUBAGENT_FANOUT)
    else:
        width = effective_concurrency(parent_config.subagent_concurrency)
    return min(width, len(items))


def _child_id(batch_token: str, index: int) -> str:
    """Derive a stable, unique child id from a per-batch token and the child index.

    Stable WITHIN a batch (token fixed once, index is the input position) so the
    ``sub/<child_id>`` branches are deterministic relative to one another — no
    ``random``/``time``-based id that would make a test flaky.
    """
    return f"{batch_token}-{index}"


def _run_child_in_worktree(
    repo_path: str,
    child_id: str,
    instruction: str,
    *,
    parent_config: EngineConfig,
    parent_engine: str,
    depth: int,
    engine: Optional[str] = None,
    model: Optional[str] = None,
    role: Optional[str] = None,
    counter: Optional["_AgentBudget"] = None,
    spec: Optional[ChildSpec] = None,
) -> SubResult:
    """Drive ONE batch child inside its own git worktree, then commit its branch.

    This is the unit of work each ThreadPoolExecutor worker runs (or the
    sequential loop calls directly when width == 1). It is a MODULE-LEVEL function
    (not a closure) so tests can monkeypatch it to inject delay / deterministic
    output without spinning up a real engine.

    Steps:
    1. Create the worktree on branch ``sub/<child_id>`` via
       :func:`colleague.worktrees.worktree_add`.
    2. Run the nested child work item via :func:`run_subagent`, with its ``repo_path``
       set to the worktree path so all its file writes land on the child branch.
       ``goal``/``acceptance`` (t16) are forwarded unchanged onto the child's
       ``Task``; ``parent_task_id`` (t16) is recorded on the returned
       ``SubResult.parent``.
    3. Commit the child's changes onto its branch via
       :func:`colleague.worktrees.commit_all` (an empty diff is a no-op, not an
       error).

    Returns the child's :class:`SubResult` (the merge happens later, in the main
    thread, after the join). The worktree itself is NOT removed here — teardown is
    centralised in :func:`make_batch_spawn`'s ``finally`` so a worker thread never
    races cleanup.
    """
    worktree_path = worktrees.worktree_add(repo_path, child_id)
    sub = run_subagent(
        instruction,
        repo_path=worktree_path,
        parent_config=parent_config,
        parent_engine=parent_engine,
        depth=depth,
        engine=engine,
        model=model,
        role=role,
        counter=counter,
        spec=spec,
    )
    # Commit whatever the child wrote onto its sub/<child_id> branch so the
    # post-join merge has something to integrate. An empty diff is fine.
    worktrees.commit_all(worktree_path, f"subagent {child_id}: {instruction[:60]}")
    return sub


def _merge_children(
    repo_path: str,
    child_ids: List[str],
    *,
    merge_engine: str,
    merge_model: str,
    parent_task_id: Optional[str] = None,
) -> tuple[SubResult, List[str]]:
    """Sequentially merge each child branch into the working branch (the merge child).

    Runs in the MAIN thread after the parallel join, so it never races child
    writes. Each ``sub/<child_id>`` branch is merged via
    :func:`colleague.worktrees.merge_branch`. A clean merge (or a harmless no-op)
    is kept; a CONFLICT is recorded and SURFACED in the returned ``SubResult`` —
    the branch is left intact (its work is not dropped), the working tree is
    restored to a clean state by ``merge_branch``'s abort, and the conflicted paths
    are named in the summary. The merge child is the final element of the batch's
    returned list and COUNTS against ``MAX_SUBAGENT_FANOUT`` (the batch reserves a
    slot for it).

    Returns a ``(merge_child, conflicted_child_ids)`` pair. ``conflicted_child_ids``
    is the list of children whose merge conflicted; the caller MUST preserve those
    children's ``sub/<id>`` branches during teardown (do not delete them) so the
    "integrate manually" instruction in the summary is honoured.

    ``parent_task_id`` (t16), when given, is recorded on the merge child's
    ``SubResult.parent`` too, for consistency with its sibling children —
    ``None`` (the default) omits it, byte-identical to before.
    """
    merged: List[str] = []
    noop: List[str] = []
    conflicted: List[str] = []
    conflicted_paths: List[str] = []

    for child_id in child_ids:
        outcome = worktrees.merge_branch(repo_path, child_id)
        if outcome.status == worktrees.MergeOutcome.MERGED:
            merged.append(child_id)
        elif outcome.status == worktrees.MergeOutcome.NOOP:
            noop.append(child_id)
        else:  # CONFLICT
            conflicted.append(child_id)
            conflicted_paths.extend(outcome.conflicted_paths or [])

    # Summary describes exactly what merged and what conflicted.
    parts: List[str] = []
    if merged:
        parts.append(f"merged {len(merged)} branch(es): {', '.join(merged)}")
    if noop:
        parts.append(f"{len(noop)} no-op (nothing to integrate)")
    if conflicted:
        paths = ", ".join(sorted(set(conflicted_paths))) or "(unspecified paths)"
        parts.append(
            f"CONFLICT on {len(conflicted)} branch(es) "
            f"({', '.join(conflicted)}); conflicted paths: {paths}. "
            "These children's work was NOT force-merged or dropped — resolve "
            "the conflict and integrate their sub/<id> branches manually."
        )
    summary = "; ".join(parts) if parts else "nothing to merge"

    status = ERROR if conflicted else OK
    merge_child = SubResult(
        task_id="merge-" + (child_ids[0] if child_ids else "empty"),
        engine=merge_engine,
        model=merge_model,
        status=status,
        summary=summary,
        changed_files=[],
        usage=Usage(),
        parent=parent_task_id,
    )
    return merge_child, conflicted


def make_batch_spawn(
    repo_path: str,
    parent_config: EngineConfig,
    parent_engine: str,
    depth: int = 1,
    *,
    counter: Optional["_AgentBudget"] = None,
    parent_task_id: Optional[str] = None,
    parent_profile: Optional[str] = None,
) -> BatchSpawnFn:
    """Build a batch spawn callback that fans children out and merges them back.

    Analogous to :func:`make_spawn`, but for a BATCH: the returned closure takes a
    list of items (``{"instruction", "engine", "model"}``, optionally carrying
    ``"goal"``/``"acceptance"`` per item, t16, and ``"profile"``/
    ``"context_mode"`` per item, #411 t14 — ``parent_profile`` is recorded on
    every child's delegate event exactly as :func:`make_spawn` does) and returns a FLAT
    ``list[SubResult]`` — the N child results in INPUT ORDER followed by exactly
    one merge child ("child C"). The loop wiring (t5) calls
    ``make_batch_spawn(task.repo_path, config, task.engine, parent_task_id=task.id)``
    and the ``subagents`` tool (t4) folds the whole returned list into
    ``TaskResult.sub_results``. ``parent_task_id`` (t16) is recorded on every
    child's (and the merge child's) ``SubResult.parent``; ``None`` (the default)
    omits it, byte-identical to the pre-t16 behavior.

    Concurrency is governed by
    ``effective_concurrency(parent_config.subagent_concurrency)``:
    width 1 runs children sequentially with NO ``ThreadPoolExecutor``; width > 1
    runs them concurrently via a ``ThreadPoolExecutor`` confined to this module.
    Per-child worktrees/branches are torn down on every exit path.
    """

    def batch_spawn(items: List[dict], role: Optional[str] = None) -> List[SubResult]:
        """Run a batch of child subagents, each in its own isolated worktree.

        Children run sequentially by default, or concurrently when
        COLLEAGUE_SUBAGENT_CONCURRENCY > 1 (bounded by MAX_SUBAGENT_FANOUT). The
        batch-level ``role`` (#t4) types every child unless an item carries its
        own ``"role"``. Returns the list of their
        :class:`~colleague.contract.SubResult` objects.
        """
        return _run_batch(
            items,
            repo_path=repo_path,
            parent_config=parent_config,
            parent_engine=parent_engine,
            depth=depth,
            role=role,
            counter=counter,
            parent_task_id=parent_task_id,
            parent_profile=parent_profile,
        )

    return batch_spawn


def _build_child_spec(
    item: dict,
    *,
    share_steps: Optional[int],
    share_budget: Optional[int],
    parent_task_id: Optional[str],
    parent_profile: Optional[str],
) -> ChildSpec:
    """Build one batch child's :class:`ChildSpec` from its raw *item* dict.

    Extracted from ``_spawn_children``'s ``_run_one`` closure (SonarCloud
    S3776) — pure translation, no behaviour change. An explicit per-item
    ``max_steps``/``context_budget_tokens`` wins over the width-scaled
    *share_steps*/*share_budget*; ``goal``/``acceptance`` are structural,
    programmatic-only (t16); ``profile``/``context_mode`` are the cross-role
    dial (#411 t14); ``effort`` is the per-child thinking-effort override
    (#416 t5) — an invalid value in any of these is refused whole by
    ``ChildSpec`` itself.
    """
    item_steps = _positive_int_or_none(item.get("max_steps"))
    item_budget = _positive_int_or_none(item.get("context_budget_tokens"))
    return ChildSpec(
        max_steps=(item_steps if item_steps is not None else share_steps),
        context_budget_tokens=(item_budget if item_budget is not None else share_budget),
        goal=(item.get("goal") or None),
        acceptance=(item.get("acceptance") or None),
        parent_task_id=parent_task_id,
        profile=(item.get("profile") or None),
        context_mode=str(item.get("context_mode") or "inherit"),
        parent_profile=parent_profile,
        effort=(item.get("effort") or None),
    )


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


def _run_batch(
    items: List[dict],
    *,
    repo_path: str,
    parent_config: EngineConfig,
    parent_engine: str,
    depth: int,
    role: Optional[str] = None,
    counter: Optional["_AgentBudget"] = None,
    parent_task_id: Optional[str] = None,
    parent_profile: Optional[str] = None,
) -> List[SubResult]:
    """Fan a batch of children out concurrently, then merge their branches.

    See :func:`make_batch_spawn` for the contract. Termination is structural: the
    depth cap AND the global agent budget are enforced FIRST, before any worktree
    is created.
    """
    # (a) Depth cap FIRST — before any worktree or thread is created, so a refused
    # level does zero work (mirrors run_subagent's guarantee for the batch path).
    if depth > MAX_SUBAGENT_DEPTH:
        raise SubagentError(f"subagent depth limit ({MAX_SUBAGENT_DEPTH}) exceeded")

    if not items:
        # An empty batch still returns a (no-op) merge child so the shape is
        # uniform: callers always get the children + exactly one merge child.
        empty_merge, _ = _merge_children(
            repo_path,
            [],
            merge_engine=parent_engine,
            merge_model=parent_config.model,
            parent_task_id=parent_task_id,
        )
        return [empty_merge]

    # (a2) Global agent budget PRE-CHECK — before any worktree is created, refuse the
    # whole batch when it obviously cannot fit (#t4), so an over-budget batch does zero
    # work and leaks no worktree. This is a best-effort snapshot; each child is also
    # charged authoritatively (thread-safe) inside run_subagent, which catches the
    # deep-nested-concurrent race the snapshot cannot.
    # (a2b) Delegation bounds PRE-CHECK — same reason, same place: every item's bounds
    # are ranked BEFORE the first worktree exists, so one widening item refuses the
    # WHOLE batch cleanly instead of aborting midway (the batch's ``finally`` removes
    # every child worktree with delete_branch=True, discarding siblings' committed work).
    for index, item in enumerate(items):
        item_spec = ChildSpec(
            profile=(item.get("profile") or None),
            context_mode=str(item.get("context_mode") or "inherit"),
            parent_profile=parent_profile,
        )
        try:
            _enforce_delegation_bounds(
                parent_config,
                item_spec,
                instruction=str(item.get("instruction", "")),
                depth=depth,
                role=(item.get("role") or role),
            )
        except SubagentError as exc:
            raise SubagentError(f"batch item {index}: {exc}") from exc

    if counter is not None and counter.remaining() < len(items):
        raise SubagentError(
            f"global agent budget ({counter.limit}) exceeded: batch of "
            f"{len(items)} exceeds {counter.remaining()} remaining"
        )

    # (b) Resolve the effective concurrency width (t12: an all-read-only batch
    # frees the merge-child reservation). Width 1 (the default) is the
    # sequential path that NEVER touches ThreadPoolExecutor — byte-identical to
    # the pre-concurrency behavior.
    width = _resolve_batch_width(parent_config, items, role)

    # (c) Assign a deterministic-within-batch token + per-child ids up front (main
    # thread), so the branch names are stable relative to each other.
    batch_token = Task.new(repo_path, "batch").id  # a fresh short id seeds the batch
    child_ids = [_child_id(batch_token, i) for i in range(len(items))]

    # Children whose merge CONFLICTED — their sub/<id> branch must survive
    # teardown so the work can be integrated manually. Empty unless _merge_children
    # runs and reports conflicts; on an exceptional exit (a worker raised before
    # the merge) it stays empty and the normal full cleanup applies.
    conflicted_ids: set[str] = set()

    try:
        # (c2) Run all children (sequential or concurrent) — the dispatch + the
        # ThreadPoolExecutor live in _spawn_children to keep this function's
        # cognitive complexity in budget (S3776).
        child_results = _spawn_children(
            items,
            child_ids,
            width,
            repo_path=repo_path,
            parent_config=parent_config,
            parent_engine=parent_engine,
            depth=depth,
            role=role,
            counter=counter,
            parent_task_id=parent_task_id,
            parent_profile=parent_profile,
        )

        # (d) SEQUENTIAL merge child, AFTER the join — never races child writes.
        merge_child, conflicted = _merge_children(
            repo_path,
            child_ids,
            merge_engine=parent_engine,
            merge_model=parent_config.model,
            parent_task_id=parent_task_id,
        )
        conflicted_ids = set(conflicted)

        # (e) Flat list: children in input order + the single merge child.
        ordered = [r for r in child_results if r is not None]
        ordered.append(merge_child)
        return ordered
    finally:
        # (f) Teardown on EVERY exit path (success, partial, exception): remove each
        # per-child worktree so no worktree dir leaks. The per-child branch is deleted
        # too — EXCEPT for children whose merge CONFLICTED, whose sub/<id> branch is
        # PRESERVED (delete_branch=False) so their committed work survives for manual
        # integration (the merge child's summary points at it). teardown_all then
        # sweeps only worktrees under our own root (never a branch with no worktree,
        # so the retained conflicted branches stay put).
        for child_id in child_ids:
            worktrees.worktree_remove(
                repo_path, child_id, delete_branch=(child_id not in conflicted_ids)
            )
        worktrees.teardown_all(repo_path)
