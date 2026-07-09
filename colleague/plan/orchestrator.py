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

from contextlib import suppress
from dataclasses import dataclass, field, replace
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
    steering:
        Operator steering applied mid-run through the flight lane (#309): each
        guidance line drained at a stage/wave boundary, plus a ``"stopped at
        <boundary>"`` marker when a cooperative stop halted the run. Empty for a
        run with no flight plane (byte-identical to a pre-#309 plan run).
    """

    spec_result: SpecStageResult
    converged: bool
    plan_items: list[PlanItem] = field(default_factory=list)
    waves: list[list[str]] = field(default_factory=list)
    sub_results: list[SubResult] = field(default_factory=list)
    conflicts: list[SubResult] = field(default_factory=list)
    steering: list[str] = field(default_factory=list)


# ── steering (mid-run flight guidance, #309) ────────────────────────────────


def _drain_steering(flight: Any) -> tuple[bool, list[str]]:
    """Read the flight control at a cooperative boundary: ``(stop, [guidance])``.

    A strict no-op — ``(False, [])`` — when ``flight`` is None (no plane armed),
    so a plan run with no pilot is byte-identical to a pre-#309 run.
    ``FlightSession.read_control`` advances its own cursor, so each guidance line
    drains exactly once.
    """
    if flight is None:
        return False, []
    control = flight.read_control()
    return bool(control.stop), list(control.guidance)


def _record_steering(flight: Any, steering: list[str], guidance: list[str]) -> None:
    """Record each drained guidance line onto ``steering`` and the flight feed.

    The feed record (``tool="steering"``) makes the applied guidance visible to a
    pilot / ``flight status`` — a REAL step record (no ``type`` marker), distinct
    from the #308 liveness heartbeats.
    """
    for line in guidance:
        steering.append(line)
        if flight is not None:
            with suppress(Exception):
                flight.append_feed(step_index=len(steering), tool="steering", intent=line, stats={})


def _inject_frame_steering(frame: PlanFrame, guidance: list[str]) -> None:
    """Thread post-spec operator guidance into plan-item proposal (#309).

    ``propose_plan_items`` prompts from the frame's CONFIRMED claims
    (``cli_driver.make_propose_plan_items`` reads ``c.state == "confirmed"``), so
    appending the guidance as confirmed requirement claims makes mid-run steering
    actually REACH the plan-item proposal — not merely get recorded (the Qodo #312
    "guidance ignored" fix). A strict no-op with no guidance.
    """
    existing = sum(1 for c in frame.claims if c.id.startswith("steer-"))
    for offset, line in enumerate(guidance, start=1):
        frame.claims.append(
            Claim(
                id=f"steer-{existing + offset}",
                kind="requirement",
                text=f"[operator steering]: {line}",
                state="confirmed",
            )
        )


def _apply_wave_steering(wave_items: list[PlanItem], guidance: list[str]) -> list[PlanItem]:
    """Thread accumulated pre-wave operator guidance into each child's instruction
    (#309): ``build_workforce_items`` maps ``PlanItem.summary`` -> the child work
    item's instruction, so augmenting the summary steers the workforce children.
    Returns the items unchanged when there is no guidance (byte-identical).
    """
    if not guidance:
        return wave_items
    note = "\n\n" + "\n".join(f"[operator steering]: {line}" for line in guidance)
    return [replace(item, summary=item.summary + note) for item in wave_items]


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
    workforce: bool = True,
    flight: Any = None,
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
        proposal.  The plan-level gate (``decide``) is invoked on the
        proposed plan items before any workforce execution.
    workforce:
        When ``True`` (default), fan the plan out to the subagent workforce.
        When ``False`` (plan-only / ``--no-workforce``, #215), return right
        after the plan items are proposed (and gated, in ``quick`` mode):
        no wave is computed, ``batch_spawn`` is never called, and no subagent
        worktree is created.  ``OrchestratorResult`` keeps its shape (empty
        ``waves``/``sub_results``/``conflicts``).

    Returns
    -------
    OrchestratorResult
        The full plan-mode outcome.

    Raises
    ------
    ValueError:
        When ``validate_items`` finds problems in the proposed plan items.
    """

    steering: list[str] = []

    # ── steering checkpoint 0 (before the spec stage, #309) ────────────
    # Drain any guidance the operator wrote before/at the start of the run:
    # record it, and thread it into the model context by augmenting the request
    # the spec stage will propose from. A cooperative stop here halts before any
    # stage runs. A strict no-op when no flight plane is armed.
    stop, guidance = _drain_steering(flight)
    _record_steering(flight, steering, guidance)
    if guidance:
        request = request + "\n\n" + "\n".join(f"[operator steering]: {g}" for g in guidance)
    if stop:
        steering.append("stopped at spec")
        return OrchestratorResult(
            spec_result=SpecStageResult(transcript=[], result=ConvergenceResult(passed=False)),
            converged=False,
            steering=steering,
        )

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
                request=request,
            ),
            repo_path,
        )

    # ── d. Early return if not converged ──────────────────────────────
    if not converged:
        return OrchestratorResult(
            spec_result=spec_result,
            converged=False,
            steering=steering,
        )

    # ── steering checkpoint 1 (after the spec stage, before plan items) ─
    stop, guidance = _drain_steering(flight)
    _record_steering(flight, steering, guidance)
    if stop:
        steering.append("stopped at plan")
        return OrchestratorResult(
            spec_result=spec_result,
            converged=True,
            steering=steering,
        )
    # Apply it: thread post-spec guidance into the frame so propose_plan_items
    # (which reads confirmed claims) is actually steered by it (#309).
    _inject_frame_steering(frame, guidance)

    # ── e. Propose and validate plan items ───────────────────────────
    plan_items = propose_plan_items(frame)
    problems = validate_items(plan_items)
    if problems:
        raise ValueError("; ".join(problems))

    # ── e1. Quick path: gate the proposed plan before workforce ──────
    if quick:
        decision = decide(plan_items, "quick-plan")
        if decision != "confirm":
            return OrchestratorResult(
                spec_result=spec_result,
                converged=True,
                plan_items=plan_items,
                steering=steering,
            )

    # ── f. Compute waves — also VALIDATES the dependency graph: it raises
    # ValueError on a cycle or a dangling dep. Run this BEFORE the plan-only
    # return so --no-workforce cannot report a cyclic plan as converged
    # (Qodo #230 F1): validate_items above checks dup ids / acceptance /
    # dangling deps but does NOT detect cycles — only compute_waves does.
    waves = compute_waves(plan_items)

    # ── e2. Plan-only mode: stop before the workforce fan-out (#215) ──
    # A caller who said "plan this" wants the spec+plan, not the long,
    # side-effecting implementation fan-out (which times out at 120s on the
    # served 27B). The graph is validated above; keep waves empty in the result
    # per the spec (h9: no fan-out, no waves executed, no subagent worktree).
    if not workforce:
        return OrchestratorResult(
            spec_result=spec_result,
            converged=True,
            plan_items=plan_items,
            steering=steering,
        )

    # ── g. Run workforce waves ───────────────────────────────────────
    item_map = {item.id: item for item in plan_items}
    sub_results: list[SubResult] = []
    # Accumulate pre-wave guidance across waves so guidance dropped before an
    # early wave still steers every later wave's children (#309).
    wave_guidance: list[str] = []

    for wave_ids in waves:
        # ── steering checkpoint 2 (before each wave, #309) ──────────
        stop, guidance = _drain_steering(flight)
        _record_steering(flight, steering, guidance)
        if stop:
            steering.append("stopped at wave")
            return OrchestratorResult(
                spec_result=spec_result,
                converged=True,
                plan_items=plan_items,
                waves=waves,
                sub_results=sub_results,
                conflicts=surface_conflicts(sub_results),
                steering=steering,
            )
        wave_guidance.extend(guidance)

        # Apply it: thread accumulated pre-wave guidance into this wave's child
        # instructions so mid-run steering reaches the workforce (#309).
        wave_items = _apply_wave_steering([item_map[wid] for wid in wave_ids], wave_guidance)
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
                    request=request,
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
        steering=steering,
    )
