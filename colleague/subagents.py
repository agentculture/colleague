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
worktree on branch ``sub/<child_id>`` (created via :mod:`colleague.worktrees`), so
concurrent writes never touch the shared working tree. The concurrency width is
``effective_concurrency(parent_config.subagent_concurrency)``:

- **width == 1** (the default) — children run SEQUENTIALLY and **no**
  ``ThreadPoolExecutor`` is ever instantiated. This is the byte-identical-to-today
  path: opt-in concurrency is off unless the operator sets
  ``COLLEAGUE_SUBAGENT_CONCURRENCY > 1``.
- **width > 1** — children run CONCURRENTLY via
  ``concurrent.futures.ThreadPoolExecutor(max_workers=width)``. The
  ``ThreadPoolExecutor`` is confined to THIS module (the one sanctioned
  concurrency consumer in colleague; threads are forbidden everywhere else).

Results are collected AFTER the executor join, in the MAIN thread, via
``future.result()`` — no shared mutable list is mutated from worker threads, so
the concurrent phase has no shared-state race. After the join a SEQUENTIAL
**merge-subagent** ("child C") git-merges each ``sub/<child_id>`` branch back into
the working branch (via :func:`colleague.worktrees.merge_branch`). A CLEAN merge is
kept; a CONFLICT is surfaced in the merge child's ``SubResult`` (status + the
conflicted paths in the summary) — never force-merged and never silently dropped.
``batch_spawn`` returns a FLAT ``list[SubResult]``: the N child results in input
order followed by exactly one merge child. Per-child worktrees/branches are torn
down on EVERY exit path (success, partial, or exception) so nothing leaks.

Termination is structural for both paths via TWO caps, both checked *first, before
any work* (no drive, no worktree). (1) The per-path **depth** cap: a child at
``depth > MAX_SUBAGENT_DEPTH`` is refused. (2) The shared **global agent budget**
(#t4, :class:`_AgentBudget`): a single :data:`~colleague.config.MAX_SUBAGENT_TOTAL`
cap on the TOTAL agents spawned under one top-level work item, regardless of
nesting shape — charged atomically (thread-safe) so concurrent batch children
cannot race past it. The budget is created once by the loop wiring and threaded
down every level; each child is handed its OWN spawn AND batch-spawn callbacks
bound to ``depth + 1`` and the same budget, so nested batches are now PERMITTED
(agents of agents of agents) yet the total stays bounded. When no budget is
threaded (a direct call with ``counter=None``) the budget is skipped — byte-
identical to the pre-budget behavior, only the depth cap applies.

The engine/model switch is pure configuration: the launcher resolves the child
engine by name through :func:`colleague.registry.load` and inherits the parent's
:class:`~colleague.config.EngineConfig` with only the model overridden
(``dataclasses.replace``). No engine's own code is touched — selecting a
different model is a config-level switch, exactly the contract Colleague promises.
"""

from __future__ import annotations

import concurrent.futures
import dataclasses
import threading
from typing import Callable, List, Optional, cast

from colleague import registry, worktrees
from colleague.config import (
    MAX_SUBAGENT_DEPTH,
    MAX_SUBAGENT_FANOUT,
    MAX_SUBAGENT_TOTAL,
    EngineConfig,
    effective_concurrency,
)
from colleague.configlifecycle import EpisodeConfigSnapshot
from colleague.contract import ERROR, OK, SubResult, Task, Usage
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
    ``ContextControls`` precedent). Every field defaults to ``None``: an empty
    spec is byte-identical to the pre-t12/t16 behavior.
    """

    max_steps: Optional[int] = None
    context_budget_tokens: Optional[int] = None
    goal: Optional[str] = None
    acceptance: Optional[List[str]] = None
    parent_task_id: Optional[str] = None


@dataclasses.dataclass(frozen=True)
class FrozenChildConfigLifecycle:
    """An immutable, read-only view of a parent's config plane, for ONE child.

    Change-content consumption lane (plan task t10, spec c35/h28): a spawned
    child never receives the parent's REAL
    :class:`~colleague.configlifecycle.EpisodeConfigLifecycle` — children
    never propose changes and never observe turns on the top-level task's
    config plane, only the top-level ``run()`` loop does that (the r2 rule,
    extended). Instead this frozen adapter QUACKS LIKE the lifecycle's READ
    surface, exactly as far as the two engine consumers reach into it:

    - ``snapshot`` — a **property** (not a method). ``colleague/engine.py``'s
      ``system_prompt`` (t7) reads it ONLY via
      ``getattr(lifecycle, "snapshot", None)`` and then
      ``.strategist_sections`` off the result — never calling it. A
      method-only ``snapshot()`` would silently lose the strategist note at
      that seam. ``colleague/engines/{mock,vllm_openai}.py`` (t3) read the
      SAME attribute defensively via a ``callable()`` check, so a property
      satisfies both: the attribute access already yields the (non-callable)
      :class:`~colleague.configlifecycle.EpisodeConfigSnapshot`.
    - ``child_snapshot()`` — a method returning the SAME frozen snapshot, so
      a grandchild's own spawn (this child delegating further) re-derives
      the identical snapshot again, one level deeper — grandchildren inherit
      exactly like a depth-1 child (acceptance criterion 1).

    Nothing else: no ``propose``/``apply_window`` (a child can never queue or
    apply a config change). ``observe_turn``/``end_episode`` no-ops ARE
    present, out of technical necessity rather than the read surface itself:
    ``colleague/loop.py`` calls both unconditionally on ANY attached
    ``config.config_lifecycle`` object once per completed turn / on every
    loop exit — a bare read-only stub without them would raise
    ``AttributeError`` on the child's OWN first turn. Both are honest no-ops:
    they touch no parent state (there is none held here) and never mutate
    this frozen adapter.

    A frozen dataclass over an already-frozen
    :class:`~colleague.configlifecycle.EpisodeConfigSnapshot` — immutable end
    to end, so it is safe to read from a ``ThreadPoolExecutor`` worker thread
    (``colleague/subagents.py`` is one of the two sanctioned threading
    modules, ``batch_spawn`` at width > 1) with no lock needed.
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
        """No-op: a child never records turn digests on the parent's plane.

        ``colleague/loop.py`` calls this once per completed model turn on ANY
        attached ``config_lifecycle``, unconditionally — this answers it
        without raising, and without touching any parent state (there is
        none reachable from here). Returns the frozen snapshot's own digest
        (an honest, read-only answer) though nothing records it.
        """
        return self.frozen_snapshot.digest()

    def end_episode(self) -> int:
        """No-op: a child's own episode boundary is not the parent's.

        ``colleague/loop.py`` calls this once on every loop exit, on ANY
        attached ``config_lifecycle`` — this answers it without raising and
        without advancing any parent boundary count (there is none reachable
        from here). Always returns 0.
        """
        return 0


def _child_config_lifecycle(
    parent_config: EngineConfig,
) -> Optional[FrozenChildConfigLifecycle]:
    """Derive the frozen adapter a spawned child inherits — never the real thing.

    ``parent_config.config_lifecycle`` may be the REAL
    :class:`~colleague.configlifecycle.EpisodeConfigLifecycle` (a top-level
    task's own attachment) or already a :class:`FrozenChildConfigLifecycle`
    (this parent is itself a child — a grandchild spawn). Both expose
    ``child_snapshot()``, preferred here over the ``snapshot`` property: it
    is the lifecycle's OWN "what does a spawned child inherit" answer — the
    r2 rule ("never a queued-but-unapplied proposal") lives there, so reading
    it (rather than reimplementing the rule against ``snapshot`` here) keeps
    a future third attachment shape honest by construction. ``snapshot`` is
    the fallback for an attachment that has it but not ``child_snapshot``.

    Returns ``None`` when nothing is attached (three-tier unarmed, or armed
    with no lifecycle constructed) — the caller leaves the child's own
    ``config_lifecycle`` at ``None``, byte-identical to today.
    """
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
    "ChildSpec",
    "FrozenChildConfigLifecycle",
    "SpawnFn",
    "BatchSpawnFn",
    "SubagentError",
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
    and threaded down every level. When no budget is threaded (a direct
    ``run_subagent`` / ``make_spawn`` call with ``counter=None``), charging is
    skipped entirely — byte-identical to the pre-budget behavior (only the depth
    cap applies).
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


def make_spawn(
    repo_path: str,
    parent_config: EngineConfig,
    parent_engine: str,
    depth: int = 1,
    *,
    counter: Optional["_AgentBudget"] = None,
    parent_task_id: Optional[str] = None,
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
    pre-t16 behavior.

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
    ) -> SubResult:
        """Run one child subagent, optionally typed by ``role`` (#t4).

        Drives the given instruction through the same bounded tool-loop in an
        isolated throwaway git worktree on a ``sub/<id>`` branch, and returns the
        child's :class:`~colleague.contract.SubResult`.
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
            spec=ChildSpec(parent_task_id=parent_task_id),
        )

    return spawn


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
    zero work and starts no child work item, guaranteeing termination:

    - the per-path **depth** cap (:data:`~colleague.config.MAX_SUBAGENT_DEPTH`); and
    - the shared **global agent budget** (#t4): when a ``counter`` is threaded, it
      is charged once here, and a child that would push the TOTAL agents spawned
      under the top-level work item past :data:`~colleague.config.MAX_SUBAGENT_TOTAL`
      is refused. ``counter=None`` skips the budget (byte-identical to before).

    The child engine is ``engine or parent_engine``, resolved through
    :func:`colleague.registry.load`. The child config inherits the parent's
    unchanged except the model (switched when provided) and the typed ``role``
    (#t4) — both pure config-level switches with no engine code change. The engine
    builds the child's curated tool schema + role-composed prompt from
    ``config.role`` (t8). The child is given its own ``subagent_spawn`` AND
    ``subagent_batch_spawn`` bound to ``depth + 1``, the SAME ``counter``, and
    ``parent_task_id`` set to THIS child's own task id — so a grandchild records
    ITS immediate parent (this child), not the top-level root — so it can
    delegate further (nested batches now permitted), still globally bounded.

    The work item runs via ``engine.work`` — the bounded loop, **no** git handoff,
    fully synchronous.
    """
    # (a) Depth cap FIRST — before loading an engine or building any config, so a
    # refused level does zero work and starts no child work item.
    if depth > MAX_SUBAGENT_DEPTH:
        raise SubagentError(f"subagent depth limit ({MAX_SUBAGENT_DEPTH}) exceeded")

    # (a2) Global agent budget NEXT — also before any work. Charging is atomic
    # (thread-safe) so concurrent batch children can't race past the cap. When no
    # budget is threaded (counter is None) this is skipped entirely — byte-identical
    # to the pre-budget behavior.
    if counter is not None:
        counter.charge()

    spec = spec or ChildSpec()

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
    # and leaves the parent object untouched. The cast is purely for the static
    # analyser (Sonar models replace()'s return as a generic DataclassInstance).
    #
    # ``chain_episode``/``chain_prior_changed`` are reset UNCONDITIONALLY (#335,
    # c22): ``execute_work`` sets those runtime-only fields on ``parent_config``
    # IN PLACE (mutation, not replace) when the parent is one episode of an
    # armed ``--until-done`` chain, so a naive ``dataclasses.replace`` would
    # otherwise copy ``True``/the accumulated tuple onto every subagent child —
    # a child is never itself a chain episode, so it must never see the marker.
    # ``until_done`` is reset for the same reason (#337): the loop keys
    # ``ContextControls.chain_armed`` on it, so an inherited flag would arm the
    # fill-line chain consumers (budget-exhausted handoff instruction, the
    # unrepairable-compaction finish-with-handoff route) inside a child nobody
    # chains.
    #
    # ``config_lifecycle`` is ALSO reset UNCONDITIONALLY (plan t10, spec
    # c35/h28): the parent's attachment — the REAL
    # ``EpisodeConfigLifecycle`` at the top level, or an inherited
    # ``FrozenChildConfigLifecycle`` one level down — is never handed to a
    # child as-is; a naive ``dataclasses.replace`` would otherwise copy the
    # mutable real object straight onto the child, letting it (or something
    # holding its config) reach ``propose``/``apply_window``, which the r2
    # rule (children never propose, never observe turns) forbids. Always
    # explicitly set — even to ``None`` when the parent carries no
    # attachment — so a child's inherited value is never an accidental copy.
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
    child_config = cast(
        EngineConfig,
        dataclasses.replace(parent_config, **replace_kwargs),
    )

    # (d) Build the child's own Task FIRST (goal/acceptance carried structurally,
    # t16), so its id is known when we build ITS nested spawn/batch-spawn
    # callbacks below — a grandchild's SubResult.parent must name ITS immediate
    # parent (this child), never the top-level root.
    child_task = Task.new(
        repo_path,
        instruction,
        engine=child_engine,
        goal=spec.goal,
        acceptance=list(spec.acceptance) if spec.acceptance is not None else None,
    )

    # (e) Give the child its OWN spawn + batch-spawn callbacks bound to depth + 1
    # and the SAME global budget, so it can delegate further (single OR batch),
    # still bounded by both the depth cap and the shared agent budget. Nested
    # batches are now PERMITTED (#t4): the child's batch closure is bound to the
    # CHILD's repo_path/depth/counter, so a child batch runs against the correct
    # worktree, increments depth, and counts against the one global budget.
    # ``parent_task_id=child_task.id`` (t16) so a grandchild's lineage points at
    # THIS child, not the top-level root.
    child_config.subagent_spawn = make_spawn(
        repo_path,
        child_config,
        child_engine,
        depth + 1,
        counter=counter,
        parent_task_id=child_task.id,
    )
    child_config.subagent_batch_spawn = make_batch_spawn(
        repo_path,
        child_config,
        child_engine,
        depth + 1,
        counter=counter,
        parent_task_id=child_task.id,
    )

    # (f) Run the nested child work item. engine.work runs the bounded loop
    # and never hands off; the call is synchronous (no thread/process/socket).
    result = eng.work(child_task, child_config)

    # (g) Project the child's TaskResult onto the nested-only SubResult shape.
    return SubResult(
        task_id=result.task_id,
        engine=child_engine,
        model=child_config.model,
        status=result.status,
        summary=result.summary,
        changed_files=list(result.changed_files),
        usage=result.usage,
        role=role,
        parent=spec.parent_task_id,
    )


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
) -> BatchSpawnFn:
    """Build a batch spawn callback that fans children out and merges them back.

    Analogous to :func:`make_spawn`, but for a BATCH: the returned closure takes a
    list of items (``{"instruction", "engine", "model"}``, optionally carrying
    ``"goal"``/``"acceptance"`` per item, t16) and returns a FLAT
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
        )

    return batch_spawn


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
        item_steps = _positive_int_or_none(item.get("max_steps"))
        item_budget = _positive_int_or_none(item.get("context_budget_tokens"))
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
            spec=ChildSpec(
                # An explicit per-item budget wins over the width-scaled share.
                max_steps=(item_steps if item_steps is not None else share_steps),
                context_budget_tokens=(item_budget if item_budget is not None else share_budget),
                # Structural goal/acceptance (t16): programmatic-only, e.g. the
                # plan workforce's build_workforce_items — never model-facing
                # (the subagents tool's _parse_batch_items strips to its keys).
                goal=(item.get("goal") or None),
                acceptance=(item.get("acceptance") or None),
                parent_task_id=parent_task_id,
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

    # (a2) Global agent budget PRE-CHECK — before any worktree is created, refuse
    # the whole batch when it obviously cannot fit (#t4), so an over-budget batch
    # does zero work and leaks no worktree. This is a best-effort snapshot; each
    # child is also charged authoritatively (thread-safe) inside run_subagent, which
    # catches the deep-nested-concurrent race the snapshot cannot.
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
        # (f) Teardown on EVERY exit path (success, partial, exception): remove
        # each per-child worktree so no worktree dir leaks. The per-child branch
        # is deleted too — EXCEPT for children whose merge CONFLICTED, whose
        # sub/<id> branch is PRESERVED (delete_branch=False) so their committed
        # work survives for manual integration (the merge child's summary points
        # at it). teardown_all then sweeps only worktrees under our own root (it
        # never touches a branch that has no worktree, so the retained conflicted
        # branches stay put).
        for child_id in child_ids:
            worktrees.worktree_remove(
                repo_path, child_id, delete_branch=(child_id not in conflicted_ids)
            )
        worktrees.teardown_all(repo_path)
