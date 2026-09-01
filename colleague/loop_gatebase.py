"""The pre-finish gates' shared base: the chain-deferral branch and the
changed-file set every gate grades.

Extracted from ``colleague/loop.py`` (plan hard-1000-line-file-limit, t15) into
its own module because BOTH gate lanes call ``_gate_changed_set`` — keeping it
here is what makes ``loop_gates`` and ``loop_testgates`` a DAG, not a cycle.
A pure move.
"""

from __future__ import annotations

from pathlib import Path

from colleague.chain import declared_capacity_handoff
from colleague.loop_constants import _EXIT_BUDGET
from colleague.loop_progress import _emit_phase
from colleague.loop_types import _Work


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
        "test-integrity/affected-tests/import-check) deferred to the chain's "
        "final episode (#335)"
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
