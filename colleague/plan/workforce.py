"""Workforce stage: map plan items onto the existing subagents fan-out.

Reuses :mod:`colleague.subagents` unchanged — no new worktree or merge code.
Pure stdlib; no devague import.
"""

from __future__ import annotations

from colleague.config import MAX_SUBAGENT_FANOUT, EngineConfig
from colleague.contract import ERROR, SubResult
from colleague.design import design_seat_config as _design_seat_config
from colleague.plan.plan_stage import PlanItem

__all__ = [
    "build_workforce_items",
    "chunk",
    "run_wave",
    "surface_conflicts",
    "design_seat_config",
]


def design_seat_config(config: EngineConfig) -> EngineConfig:
    """The 'plan.workforce' design call-site seat (#416 t6, c14/h9): xhigh.

    Honest limit: this stage maps each :class:`PlanItem` to a batch-spawn
    child (:func:`build_workforce_items`) and dispatches through
    ``batch_spawn`` (:mod:`colleague.subagents`) — each child work item builds
    its OWN completion at its own role/seat effort (t5), so there is no
    dedicated "decompose the plan into a workforce" completion in this module
    to route through the design seat instead. This builder is pinned here,
    ready for a future dedicated decomposition-planning call; it is
    unit-tested at the builder level (``tests/test_design_call_site.py``), not
    exercised end-to-end.
    """
    return _design_seat_config(config, "plan.workforce")


def build_workforce_items(
    items: list[PlanItem],
    *,
    engine: str,
    model: str,
    role: str | None = None,
) -> list[dict]:
    """Map each PlanItem to a batch-spawn item dict.

    The acceptance criteria are carried STRUCTURALLY (a ``"acceptance"`` key)
    rather than flattened into the instruction prose (spec R6 / plan t16 /
    #259) — the instruction keeps only the task description. A ``"goal"`` key
    carries the PlanItem's summary too, so the batch path
    (:func:`colleague.subagents.make_batch_spawn`) can build each child's
    ``Task`` with ``goal=``/``acceptance=`` set, letting the existing t15 loop
    machinery (the goal/acceptance prompt block + the advisory self-check)
    fire for workforce children automatically. Order is preserved.
    """
    result: list[dict] = []
    for item in items:
        entry: dict = {
            "instruction": item.summary,
            "engine": engine,
            "model": model,
            "goal": item.summary,
            "acceptance": list(item.acceptance),
        }
        if role is not None:
            entry["role"] = role
        result.append(entry)
    return result


def chunk(items: list, size: int) -> list[list]:
    """Split *items* into consecutive sub-lists of at most *size*."""
    return [items[i : i + size] for i in range(0, len(items), size)]


def run_wave(
    wave_items: list[PlanItem],
    batch_spawn,
    *,
    engine: str,
    model: str,
    role: str | None = None,
) -> list[SubResult]:
    """Run *wave_items* through the injected *batch_spawn* in sized batches.

    Each batch is at most ``MAX_SUBAGENT_FANOUT - 1`` children (one slot is
    reserved for the merge child inside *batch_spawn*).  Returns ALL
    :class:`SubResult` objects across every batch call.
    """
    batch_size = MAX_SUBAGENT_FANOUT - 1
    chunks_list = chunk(wave_items, batch_size)
    results: list[SubResult] = []
    for items_chunk in chunks_list:
        workforce_items = build_workforce_items(items_chunk, engine=engine, model=model, role=role)
        results.extend(batch_spawn(workforce_items))
    return results


def surface_conflicts(results: list[SubResult]) -> list[SubResult]:
    """Return the SubResults whose status is ERROR (conflicted merge children)."""
    return [r for r in results if r.status == ERROR]
