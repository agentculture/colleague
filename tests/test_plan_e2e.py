"""E2E tests for colleague.plan.orchestrator.run_plan_mode.

Proves the orchestrator is ENGINE-AGNOSTIC and that planning/implementation
never runs before convergence.
"""

from colleague.contract import SubResult
from colleague.plan.frame import Claim, HonestyCondition
from colleague.plan.orchestrator import run_plan_mode
from colleague.plan.plan_stage import PlanItem

# ── helpers ──────────────────────────────────────────────────────────────────


def _make_claims(variant: str) -> tuple[list[Claim], list[HonestyCondition]]:
    """Build proposed claims covering all mandatory kinds with honesty conditions.

    *variant* is a string suffix so two different sets can be distinguished.
    Mandatory kinds: announcement, audience, after_state, boundary,
    success_signal, before_state.  Each spec-affecting claim gets an honesty
    condition.
    """
    claims = [
        Claim(id=f"c1_{variant}", kind="announcement", text=f"Announcement {variant}"),
        Claim(id=f"c2_{variant}", kind="audience", text=f"Audience {variant}"),
        Claim(id=f"c3_{variant}", kind="after_state", text=f"After state {variant}"),
        Claim(id=f"c4_{variant}", kind="boundary", text=f"Boundary {variant}"),
        Claim(id=f"c5_{variant}", kind="success_signal", text=f"Success signal {variant}"),
        Claim(id=f"c6_{variant}", kind="before_state", text=f"Before state {variant}"),
    ]
    honesty = [
        HonestyCondition(id=f"h1_{variant}", claim_id=f"c1_{variant}", text=f"Honesty {variant} 1"),
        HonestyCondition(id=f"h2_{variant}", claim_id=f"c2_{variant}", text=f"Honesty {variant} 2"),
        HonestyCondition(id=f"h3_{variant}", claim_id=f"c3_{variant}", text=f"Honesty {variant} 3"),
        HonestyCondition(id=f"h4_{variant}", claim_id=f"c4_{variant}", text=f"Honesty {variant} 4"),
        HonestyCondition(id=f"h5_{variant}", claim_id=f"c5_{variant}", text=f"Honesty {variant} 5"),
        HonestyCondition(id=f"h6_{variant}", claim_id=f"c6_{variant}", text=f"Honesty {variant} 6"),
    ]
    return claims, honesty


def _auto_confirm_decide(_item, _critique):
    """Decide callable that always confirms."""
    return "confirm"


def _make_plan_items(variant: str) -> list[PlanItem]:
    """Build plan items with acceptance criteria."""
    return [
        PlanItem(
            id=f"t1_{variant}",
            summary=f"Task one {variant}",
            acceptance=[f"Acceptance {variant} 1"],
        ),
        PlanItem(
            id=f"t2_{variant}",
            summary=f"Task two {variant}",
            acceptance=[f"Acceptance {variant} 2"],
            deps=[f"t1_{variant}"],
        ),
    ]


def _fake_batch_spawn(items):
    """Fake batch_spawn that returns SubResult objects."""
    results: list[SubResult] = []
    for i, item in enumerate(items):
        results.append(
            SubResult(
                task_id=f"sub-{i}",
                engine="mock",
                model="test",
                status="ok",
                summary=f"Sub-result {i}",
            )
        )
    return results


# ── test: engine-agnostic shape ─────────────────────────────────────────────


def test_orchestrator_engine_agnostic_same_shape():
    """Two different injected seam sets produce OrchestratorResult with same shape.

    Both runs cover mandatory claim kinds and auto-confirm, so both converge.
    The results must have the same set of attributes, both converged=True,
    and both with non-empty waves.
    """

    # ── Run 1: variant "alpha" ──────────────────────────────────────────
    def propose_claims_alpha(_request):
        return _make_claims("alpha")

    def propose_plan_items_alpha(_frame):
        return _make_plan_items("alpha")

    result_a = run_plan_mode(
        request="Build feature alpha",
        propose_claims=propose_claims_alpha,
        decide=_auto_confirm_decide,
        propose_plan_items=propose_plan_items_alpha,
        batch_spawn=_fake_batch_spawn,
        engine="engine-a",
        model="model-a",
    )

    # ── Run 2: variant "beta" ──────────────────────────────────────────
    def propose_claims_beta(_request):
        return _make_claims("beta")

    def propose_plan_items_beta(_frame):
        return _make_plan_items("beta")

    result_b = run_plan_mode(
        request="Build feature beta",
        propose_claims=propose_claims_beta,
        decide=_auto_confirm_decide,
        propose_plan_items=propose_plan_items_beta,
        batch_spawn=_fake_batch_spawn,
        engine="engine-b",
        model="model-b",
    )

    # Both results must have the same set of attributes.
    attrs_a = set(result_a.__dataclass_fields__.keys())
    attrs_b = set(result_b.__dataclass_fields__.keys())
    assert attrs_a == attrs_b, f"OrchestratorResult attribute mismatch: {attrs_a} vs {attrs_b}"

    # Both must be converged.
    assert result_a.converged is True, "Run A should be converged"
    assert result_b.converged is True, "Run B should be converged"

    # Both must have non-empty waves.
    assert len(result_a.waves) > 0, "Run A should have non-empty waves"
    assert len(result_b.waves) > 0, "Run B should have non-empty waves"

    # Both must have plan items.
    assert len(result_a.plan_items) > 0, "Run A should have plan items"
    assert len(result_b.plan_items) > 0, "Run B should have plan items"

    # Both must have sub_results (workforce ran).
    assert len(result_a.sub_results) > 0, "Run A should have sub-results"
    assert len(result_b.sub_results) > 0, "Run B should have sub-results"


# ── test: rejection blocks planning ─────────────────────────────────────────


def test_rejection_prevents_planning():
    """Rejecting a mandatory claim yields converged=False and never calls batch_spawn."""

    # Track whether batch_spawn was called.
    batch_spawn_calls: list[list[dict]] = []

    def _tracking_batch_spawn(items):
        batch_spawn_calls.append(items)
        return _fake_batch_spawn(items)

    # Reject the first item (a mandatory claim), confirm everything else.
    def _reject_first_decide(item, _critique):
        if getattr(item, "id", None) == "c1_reject":
            return "reject"
        return "confirm"

    claims, honesty = _make_claims("reject")

    def propose_claims_reject(_request):
        return claims, honesty

    result = run_plan_mode(
        request="Build feature reject",
        propose_claims=propose_claims_reject,
        decide=_reject_first_decide,
        propose_plan_items=lambda _frame: _make_plan_items("reject"),
        batch_spawn=_tracking_batch_spawn,
        engine="mock",
        model="test",
    )

    # Must not be converged.
    assert result.converged is False, (
        f"Expected converged=False when a mandatory claim is rejected, "
        f"got converged={result.converged}"
    )

    # batch_spawn must never have been called.
    assert len(batch_spawn_calls) == 0, (
        f"batch_spawn was called {len(batch_spawn_calls)} time(s) despite "
        "convergence failure — planning/implementation must not run before convergence"
    )

    # Plan items and waves must be empty.
    assert result.plan_items == [], "plan_items must be empty when not converged"
    assert result.waves == [], "waves must be empty when not converged"
    assert result.sub_results == [], "sub_results must be empty when not converged"
