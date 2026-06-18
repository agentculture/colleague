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
    MAX_SUBAGENT_TOTAL,
    EngineConfig,
    effective_concurrency,
)
from colleague.contract import ERROR, OK, SubResult, Task, Usage

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
    "SpawnFn",
    "BatchSpawnFn",
    "SubagentError",
    "make_spawn",
    "run_subagent",
    "make_batch_spawn",
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


def make_spawn(
    repo_path: str,
    parent_config: EngineConfig,
    parent_engine: str,
    depth: int = 1,
    *,
    counter: Optional["_AgentBudget"] = None,
) -> SpawnFn:
    """Build a depth-bound spawn callback over :func:`run_subagent`.

    The returned closure captures ``repo_path``, ``parent_config``,
    ``parent_engine``, this ``depth`` (the nesting level of the child it will
    launch — top-level children are ``depth=1``), and the shared global
    ``counter`` (#t4). The loop wiring (t6) calls
    ``make_spawn(task.repo_path, config, task.engine, counter=budget)`` and
    assigns the result to ``config.subagent_spawn``; the tool executor then calls
    ``spawn(instruction, engine, model, role)`` per delegation.

    Each launched child is itself handed a spawn callback bound to ``depth + 1``
    and the SAME ``counter`` inside :func:`run_subagent`, so both the depth bound
    and the global agent budget are carried down every level structurally.
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
) -> SubResult:
    """Run one nested child work item and return its :class:`SubResult`.

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
    ``subagent_batch_spawn`` bound to ``depth + 1`` and the SAME ``counter`` so it
    can delegate further (nested batches now permitted), still globally bounded.

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

    # (b) Resolve + load the child engine by name. A bad name surfaces as a clean
    # SubagentError (never an unrelated crash upstream).
    child_engine = engine or parent_engine
    try:
        eng = registry.load(child_engine)
    except registry.UnknownEngine as exc:
        raise SubagentError(str(exc)) from exc

    # (c) Inherit the parent's config, overriding ONLY the model and the typed role
    # when provided. dataclasses.replace keeps base_url/api_key/max_steps/... intact
    # and leaves the parent object untouched. The cast is purely for the static
    # analyser (Sonar models replace()'s return as a generic DataclassInstance).
    child_config = cast(
        EngineConfig,
        dataclasses.replace(
            parent_config,
            model=(model or parent_config.model),
            role=role,
        ),
    )

    # (d) Give the child its OWN spawn + batch-spawn callbacks bound to depth + 1
    # and the SAME global budget, so it can delegate further (single OR batch),
    # still bounded by both the depth cap and the shared agent budget. Nested
    # batches are now PERMITTED (#t4): the child's batch closure is bound to the
    # CHILD's repo_path/depth/counter, so a child batch runs against the correct
    # worktree, increments depth, and counts against the one global budget.
    child_config.subagent_spawn = make_spawn(
        repo_path, child_config, child_engine, depth + 1, counter=counter
    )
    child_config.subagent_batch_spawn = make_batch_spawn(
        repo_path, child_config, child_engine, depth + 1, counter=counter
    )

    # (e) Build + run the nested child work item. engine.work runs the bounded loop
    # and never hands off; the call is synchronous (no thread/process/socket).
    child_task = Task.new(repo_path, instruction, engine=child_engine)
    result = eng.work(child_task, child_config)

    # (f) Project the child's TaskResult onto the nested-only SubResult shape.
    return SubResult(
        task_id=result.task_id,
        engine=child_engine,
        model=child_config.model,
        status=result.status,
        summary=result.summary,
        changed_files=list(result.changed_files),
        usage=result.usage,
    )


# ---------------------------------------------------------------------------
# Parallel batch orchestration: per-worktree children + sequential merge child.
# ---------------------------------------------------------------------------


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
    )
    return merge_child, conflicted


def make_batch_spawn(
    repo_path: str,
    parent_config: EngineConfig,
    parent_engine: str,
    depth: int = 1,
    *,
    counter: Optional["_AgentBudget"] = None,
) -> BatchSpawnFn:
    """Build a batch spawn callback that fans children out and merges them back.

    Analogous to :func:`make_spawn`, but for a BATCH: the returned closure takes a
    list of items (``{"instruction", "engine", "model"}``) and returns a FLAT
    ``list[SubResult]`` — the N child results in INPUT ORDER followed by exactly
    one merge child ("child C"). The loop wiring (t5) calls
    ``make_batch_spawn(task.repo_path, config, task.engine)`` and the
    ``subagents`` tool (t4) folds the whole returned list into
    ``TaskResult.sub_results``.

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
        )

    return batch_spawn


def _run_batch(
    items: List[dict],
    *,
    repo_path: str,
    parent_config: EngineConfig,
    parent_engine: str,
    depth: int,
    role: Optional[str] = None,
    counter: Optional["_AgentBudget"] = None,
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

    # (b) Resolve the effective concurrency width. Width 1 (the default) is the
    # sequential path that NEVER touches ThreadPoolExecutor — byte-identical to the
    # pre-concurrency behavior. Also defensively clamp workers to the item count.
    width = effective_concurrency(parent_config.subagent_concurrency)
    width = min(width, len(items))

    # (c) Assign a deterministic-within-batch token + per-child ids up front (main
    # thread), so the branch names are stable relative to each other.
    batch_token = Task.new(repo_path, "batch").id  # a fresh short id seeds the batch
    child_ids = [_child_id(batch_token, i) for i in range(len(items))]

    child_results: List[Optional[SubResult]] = [None] * len(items)
    # Children whose merge CONFLICTED — their sub/<id> branch must survive
    # teardown so the work can be integrated manually. Empty unless _merge_children
    # runs and reports conflicts; on an exceptional exit (a worker raised before
    # the merge) it stays empty and the normal full cleanup applies.
    conflicted_ids: set[str] = set()

    try:
        if width <= 1:
            # SEQUENTIAL path — no executor, no thread. Each child runs to
            # completion in order; results are collected directly.
            for i, item in enumerate(items):
                child_results[i] = _run_child_in_worktree(
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
                )
        else:
            # CONCURRENT path — ThreadPoolExecutor confined to this module. Each
            # worker returns its own SubResult; we COLLECT after the join in the
            # main thread (no shared mutable accumulation during the parallel
            # phase). future_index maps each future back to its input position so
            # the final list stays in INPUT ORDER regardless of completion order.
            with concurrent.futures.ThreadPoolExecutor(max_workers=width) as pool:
                future_index = {}
                for i, item in enumerate(items):
                    fut = pool.submit(
                        _run_child_in_worktree,
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
                    )
                    future_index[fut] = i
                # Join: collect every result AFTER the threads finish. future.result()
                # re-raises a worker exception here, in the main thread, where the
                # finally below still tears worktrees down.
                for fut in concurrent.futures.as_completed(future_index):
                    child_results[future_index[fut]] = fut.result()

        # (d) SEQUENTIAL merge child, AFTER the join — never races child writes.
        merge_child, conflicted = _merge_children(
            repo_path,
            child_ids,
            merge_engine=parent_engine,
            merge_model=parent_config.model,
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
