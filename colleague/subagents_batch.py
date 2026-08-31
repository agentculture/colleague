"""Parallel batch orchestration — split out of ``subagents.py``
(hard-1000-line-file-limit, task t7) to keep the launcher module under the
1000-line file-length gate.

Owns everything about running a BATCH of child drives and integrating them
that does not itself touch ``concurrent.futures``: the per-child worktree
lifecycle (:func:`_run_child_in_worktree`), the sequential post-join merge
(:func:`_merge_children`), the width-scaled budget share (t12,
:func:`_child_budget_share`), and the batch entry point
(:func:`make_batch_spawn`) plus its top-level driver (:func:`_run_batch`).

``_spawn_children`` — the ONE function in the whole batch lane that actually
instantiates a ``ThreadPoolExecutor`` — deliberately stays in
``colleague/subagents.py``: that is the sole module ``tests/test_boundary.py``'s
two-sided ``_THREADS_ALLOWED`` check permits to import ``concurrent.futures``,
and the whole point of this split is to leave that allow-list (mirrored
byte-for-byte in ``tests/test_agents_boundary.py`` and
``tests/test_chain_e2e.py``) untouched. :func:`_run_batch` below calls it via a
function-local import — ``colleague.subagents`` imports this module at load
time (for :func:`make_batch_spawn`), so a top-level import here of anything
from ``colleague.subagents`` would cycle; the lazy imports below (for
``_spawn_children`` and ``run_subagent``) resolve fine because by the time
``_run_batch``/``_run_child_in_worktree`` actually RUN, ``colleague.subagents``
has already finished loading.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

from colleague import worktrees
from colleague.config import (
    MAX_SUBAGENT_DEPTH,
    MAX_SUBAGENT_FANOUT,
    EngineConfig,
    effective_concurrency,
)
from colleague.contract import ERROR, OK, SubResult, Task, Usage
from colleague.roles import is_read_only
from colleague.subagents_binding import ChildSpec, SubagentError, _enforce_delegation_bounds

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids a load-time cycle
    from colleague.subagents import BatchSpawnFn, _AgentBudget

# Floors for the width-scaled child budget share (t12 / spec R5): a child's
# share is clamped so scaling can never hand a child an unworkable budget —
# and never MORE than the parent's own value (a tiny parent budget stays the
# ceiling, floors notwithstanding).
_MIN_CHILD_MAX_STEPS = 10
_MIN_CHILD_CONTEXT_BUDGET = 16000


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
    counter: "Optional[_AgentBudget]" = None,
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
    2. Run the nested child work item via
       :func:`~colleague.subagents.run_subagent`, with its ``repo_path``
       set to the worktree path so all its file writes land on the child branch.
       ``goal``/``acceptance`` (t16) are forwarded unchanged onto the child's
       ``Task``; ``parent_task_id`` (t16) is recorded on the returned
       ``SubResult.parent``.
    3. Commit the child's changes onto its branch via
       :func:`colleague.worktrees.commit_all` (an empty diff is a no-op, not an
       error).

    Returns the child's :class:`~colleague.contract.SubResult` (the merge
    happens later, in the main thread, after the join). The worktree itself is
    NOT removed here — teardown is centralised in
    :func:`~colleague.subagents.make_batch_spawn`'s ``finally`` so a worker
    thread never races cleanup.
    """
    # Lazy import: colleague.subagents imports THIS module at load time (for
    # make_batch_spawn), so a top-level import here would cycle; by the time a
    # worker actually runs this function, colleague.subagents has finished
    # loading.
    from colleague.subagents import run_subagent

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
    counter: "Optional[_AgentBudget]" = None,
    parent_task_id: Optional[str] = None,
    parent_profile: Optional[str] = None,
) -> "BatchSpawnFn":
    """Build a batch spawn callback that fans children out and merges them back.

    Analogous to :func:`~colleague.subagents.make_spawn`, but for a BATCH: the
    returned closure takes a list of items (``{"instruction", "engine",
    "model"}``, optionally carrying ``"goal"``/``"acceptance"`` per item, t16,
    and ``"profile"``/``"context_mode"`` per item, #411 t14 — ``parent_profile``
    is recorded on every child's delegate event exactly as ``make_spawn`` does)
    and returns a FLAT ``list[SubResult]`` — the N child results in INPUT ORDER
    followed by exactly one merge child ("child C"). The loop wiring (t5) calls
    ``make_batch_spawn(task.repo_path, config, task.engine, parent_task_id=task.id)``
    and the ``subagents`` tool (t4) folds the whole returned list into
    ``TaskResult.sub_results``. ``parent_task_id`` (t16) is recorded on every
    child's (and the merge child's) ``SubResult.parent``; ``None`` (the default)
    omits it, byte-identical to the pre-t16 behavior.

    Concurrency is governed by
    ``effective_concurrency(parent_config.subagent_concurrency)``:
    width 1 runs children sequentially with NO ``ThreadPoolExecutor``; width > 1
    runs them concurrently via a ``ThreadPoolExecutor`` confined to
    ``colleague/subagents.py``'s ``_spawn_children``. Per-child
    worktrees/branches are torn down on every exit path.
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
    """Build one batch child's :class:`~colleague.subagents_binding.ChildSpec`
    from its raw *item* dict.

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


def _run_batch(
    items: List[dict],
    *,
    repo_path: str,
    parent_config: EngineConfig,
    parent_engine: str,
    depth: int,
    role: Optional[str] = None,
    counter: "Optional[_AgentBudget]" = None,
    parent_task_id: Optional[str] = None,
    parent_profile: Optional[str] = None,
) -> List[SubResult]:
    """Fan a batch of children out concurrently, then merge their branches.

    See :func:`make_batch_spawn` for the contract. Termination is structural: the
    depth cap AND the global agent budget are enforced FIRST, before any worktree
    is created.
    """
    # Lazy import: colleague.subagents imports THIS module at load time (for
    # make_batch_spawn), so a top-level import here would cycle; by the time
    # this function actually runs, colleague.subagents has finished loading.
    from colleague.subagents import _spawn_children

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
        # ThreadPoolExecutor live in colleague.subagents's _spawn_children to keep
        # this function's cognitive complexity in budget (S3776) AND keep the one
        # ThreadPoolExecutor call site in the one module the thread-confinement
        # guard permits.
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
