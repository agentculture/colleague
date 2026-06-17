"""Plan-mode orchestrator for colleague.

Drives the full plan-mode lifecycle end to end:

    spec stage -> plan stage -> workforce stage

gated at every step.  The orchestrator **never self-confirms** — confirmation
happens *only* inside :func:`run_spec_stage` via the injected ``decide``
callable (the operator's decision).  Planning and implementation are
forbidden until the spec converges.

Pure stdlib only; no devague import.  Composes the already-built sibling
modules via **injected callables** (dependency injection) so the orchestrator
is testable without a real model, operator, or subagents.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from colleague.contract import SubResult
from colleague.plan.checkpoint import Checkpoint, save
from colleague.plan.convergence import ConvergenceResult
from colleague.plan.frame import Claim, HonestyCondition, PlanFrame
from colleague.plan.plan_stage import PlanItem, compute_waves, validate_items
from colleague.plan.spec_stage import SpecStageResult, run_spec_stage
from colleague.plan.workforce import run_wave, surface_conflicts

# ── OrchestratorResult ──────────────────────────────────────────────────────


@dataclass
class OrchestratorResult:
    """Outcome of a full plan-mode run.

    Fields
    ------
    spec_result:
        The :class:`SpecStageResult` from the spec stage (always present).
    converged:
        Whether the spec stage converged (``True``) or not (``False``).
    plan_items:
        The validated plan items (empty when spec did not converge).
    waves:
        Dependency-wave layering of plan items (empty when spec did not converge).
    sub_results:
        All :class:`SubResult` objects from workforce execution
        (empty when spec did not converge).
    conflicts:
        Sub-results with ERROR status (conflicted merge children).
    """

    spec_result: SpecStageResult
    converged: bool
    plan_items: list[PlanItem] = field(default_factory=list)
    waves: list[list[str]] = field(default_factory=list)
    sub_results: list[SubResult] = field(default_factory=list)
    conflicts: list[SubResult] = field(default_factory=list)


# ── run_plan_mode ───────────────────────────────────────────────────────────


def run_plan_mode(
    request: str,
    *,
    propose_claims: Callable[[str], tuple[list[Claim], list[HonestyCondition]]],
    decide: Callable[[Any, str | None], str],
    propose_plan_items: Callable[[PlanFrame], list[PlanItem]],
    batch_spawn: Callable[[list[dict]], list[SubResult]],
    engine: str,
    model: str,
    complete: Callable[[str, str], str] | None = None,
    reviewer_enabled: bool = False,
    repo_path: str | None = None,
    plan_id: str = "plan",
    quick: bool = False,
) -> OrchestratorResult:
    """Drive the full plan-mode lifecycle end to end.

    Logic (in exact order):

    a. Create a :class:`PlanFrame` and populate it with claims + honesty
       conditions from ``propose_claims(request)``.
    b. Run the spec stage: ``run_spec_stage(frame, decide, ...)``.
       ``converged = spec_result.result.passed``.
    c. If ``repo_path`` is not ``None``, save a checkpoint recording the
       resolved gates and recommending ``"plan"`` (if converged) or
       ``"spec"`` (if not).
    d. If **not** converged: return immediately with empty plan/workforce
       fields — planning and implementation must not run before convergence.
    d. ``plan_items = propose_plan_items(frame)``.
       Validate with ``validate_items``; raise ``ValueError`` on problems.
    e. ``waves = compute_waves(plan_items)``.
    f. For each wave (in order): build the wave's ``PlanItem`` list, call
       ``run_wave``, extend ``sub_results``.  If ``repo_path`` is set, save
       a checkpoint advancing ``recommended_move="workforce"``.
    g. ``conflicts = surface_conflicts(sub_results)``.
    h. Return :class:`OrchestratorResult`.

    Parameters
    ----------
    request:
        The originating task instruction.
    propose_claims:
        Returns ``(claims, honesty_conditions)`` — all items have
        ``state="proposed"``.
    decide:
        The **operator's** decision callable.  Must return ``"confirm"`` or
        ``"reject"``.  This is the **only** thing that may confirm.
    propose_plan_items:
        Returns a list of :class:`PlanItem` objects derived from the frame.
    batch_spawn:
        The colleague subagents fan-out closure.
    engine:
        Engine name for workforce items.
    model:
        Model name for workforce items.
    complete:
        Injected model callable (``system_prompt, user_prompt -> str``).
        Passed through to ``run_spec_stage`` when ``reviewer_enabled=True``.
    reviewer_enabled:
        When ``True``, enable the reviewer in the spec stage.
    repo_path:
        When not ``None``, persist checkpoints to disk.
    plan_id:
        Identifier for checkpoint files (default ``"plan"``).
    quick:
        When ``True``, skip the spec stage entirely and build a minimal
        frame from the request text, proceeding straight to plan-item
        proposal.  The plan-level gate (``decide``) is still invoked.

    Returns
    -------
    OrchestratorResult
        The full plan-mode outcome.

    Raises
    ------
    ValueError:
        When ``validate_items`` finds problems in the proposed plan items.
    """

    # ── a. Build frame from proposed claims + honesty ──────────────────
    if quick:
        # Quick path: skip the spec stage entirely. Build a minimal frame
        # whose single confirmed claim carries the request text, so the
        # existing propose_plan_items (which reads confirmed claims) has
        # the request as its input.
        frame = PlanFrame(
            claims=[Claim(id="request", kind="requirement", text=request, state="confirmed")],
        )
        spec_result = SpecStageResult(
            transcript=[],
            result=ConvergenceResult(passed=True),
        )
        converged = True
    else:
        claims, honesty = propose_claims(request)
        frame = PlanFrame(claims=claims, honesty_conditions=honesty)

        # ── b. Run spec stage ──────────────────────────────────────────
        spec_result = run_spec_stage(
            frame,
            decide,
            complete=complete,
            reviewer_enabled=reviewer_enabled,
        )
        converged = spec_result.result.passed

    # ── c. Checkpoint after spec stage ─────────────────────────────────
    if repo_path is not None:
        gate_ids = [g.item_id for g in spec_result.transcript]
        recommended = "plan" if converged else "spec"
        save(
            Checkpoint(
                plan_id=plan_id,
                proposed_item="",
                recommended_move=recommended,
                resolved_gates=gate_ids,
            ),
            repo_path,
        )

    # ── d. Early return if not converged ──────────────────────────────
    if not converged:
        return OrchestratorResult(
            spec_result=spec_result,
            converged=False,
        )

    # ── e. Propose and validate plan items ───────────────────────────
    plan_items = propose_plan_items(frame)
    problems = validate_items(plan_items)
    if problems:
        raise ValueError("; ".join(problems))

    # ── f. Compute waves ──────────────────────────────────────────────
    waves = compute_waves(plan_items)

    # ── g. Run workforce waves ───────────────────────────────────────
    item_map = {item.id: item for item in plan_items}
    sub_results: list[SubResult] = []

    for wave_ids in waves:
        wave_items = [item_map[wid] for wid in wave_ids]
        wave_results = run_wave(
            wave_items,
            batch_spawn,
            engine=engine,
            model=model,
        )
        sub_results.extend(wave_results)

        # Checkpoint after each wave
        if repo_path is not None:
            save(
                Checkpoint(
                    plan_id=plan_id,
                    proposed_item="",
                    recommended_move="workforce",
                    resolved_gates=[g.item_id for g in spec_result.transcript],
                ),
                repo_path,
            )

    # ── h. Surface conflicts ────────────────────────────────────────
    conflicts = surface_conflicts(sub_results)

    # ── i. Return result ─────────────────────────────────────────────
    return OrchestratorResult(
        spec_result=spec_result,
        converged=True,
        plan_items=plan_items,
        waves=waves,
        sub_results=sub_results,
        conflicts=conflicts,
    )
