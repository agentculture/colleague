"""Workforce stage: map plan items onto the existing subagents fan-out.

Reuses :mod:`colleague.subagents` unchanged — no new worktree or merge code.
Pure stdlib; no devague import.
"""

from __future__ import annotations

from colleague.config import MAX_SUBAGENT_FANOUT
from colleague.contract import ERROR, SubResult
from colleague.plan.plan_stage import PlanItem

__all__ = [
    "build_workforce_items",
    "chunk",
    "run_wave",
    "surface_conflicts",
]


def build_workforce_items(
    items: list[PlanItem],
    *,
    engine: str,
    model: str,
) -> list[dict]:
    """Map each PlanItem to a batch-spawn item dict.

    The instruction embeds the summary plus acceptance criteria so the child
    subagent knows what to deliver.  Order is preserved.
    """
    result: list[dict] = []
    for item in items:
        lines = ["- " + c for c in item.acceptance]
        instruction = f"{item.summary}\n\nAcceptance criteria:\n" + "\n".join(lines)
        result.append(
            {
                "instruction": instruction,
                "engine": engine,
                "model": model,
            }
        )
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
        workforce_items = build_workforce_items(items_chunk, engine=engine, model=model)
        results.extend(batch_spawn(workforce_items))
    return results


def surface_conflicts(results: list[SubResult]) -> list[SubResult]:
    """Return the SubResults whose status is ERROR (conflicted merge children)."""
    return [r for r in results if r.status == ERROR]
