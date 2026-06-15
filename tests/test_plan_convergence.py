"""Tests for colleague.plan.convergence — native convergence gate."""

from __future__ import annotations

from colleague.plan.convergence import ConvergenceResult, converge
from colleague.plan.frame import Claim, HonestyCondition, PlanFrame, Step


# ── helpers ──────────────────────────────────────────────────────────────────

def _claim(kind: str, state: str = "confirmed", id: str = "") -> Claim:
    return Claim(id=id or kind, kind=kind, text=f"{kind} text", state=state)


def _honesty(claim_id: str, state: str = "confirmed", id: str = "") -> HonestyCondition:
    return HonestyCondition(id=id or f"hc-{claim_id}", claim_id=claim_id, text=f"hc for {claim_id}", state=state)


def _step(id: str, mandatory: bool) -> Step:
    return Step(id=id, kind="implement", mandatory=mandatory)


# ── missing mandatory kinds ─────────────────────────────────────────────────

def test_empty_frame_blocks_with_all_missing_kinds():
    frame = PlanFrame()
    result = converge(frame)
    assert result.passed is False
    assert result.missing_kinds == [
        "announcement",
        "audience",
        "after_state",
        "boundary",
        "success_signal",
        "before_state_or_why_it_matters",
    ]
    assert result.claims_missing_honesty == []
    assert result.skipped_optional == []


def test_unconfirmed_mandatory_kind_still_missing():
    """A proposed (not confirmed) mandatory claim still counts as missing."""
    frame = PlanFrame(claims=[_claim("announcement", state="proposed")])
    result = converge(frame)
    assert result.passed is False
    assert "announcement" in result.missing_kinds


def test_all_mandatory_kinds_confirmed_but_no_honesty_blocks():
    """All mandatory kinds present and confirmed, but no honesty conditions → blocks."""
    claims = [
        _claim("announcement"),
        _claim("audience"),
        _claim("after_state"),
        _claim("boundary"),
        _claim("success_signal"),
        _claim("before_state"),
    ]
    frame = PlanFrame(claims=claims)
    result = converge(frame)
    assert result.passed is False
    assert result.missing_kinds == []
    # All spec-affecting confirmed claims need a confirmed honesty condition
    assert result.claims_missing_honesty == [
        "announcement",
        "audience",
        "after_state",
        "boundary",
        "success_signal",
        "before_state",
    ]


# ── passed case ──────────────────────────────────────────────────────────────

def test_all_mandatory_confirmed_with_honesty_passes():
    """All mandatory kinds confirmed + every spec-affecting claim has confirmed honesty → passes."""
    claims = [
        _claim("announcement"),
        _claim("audience"),
        _claim("after_state"),
        _claim("boundary"),
        _claim("success_signal"),
        _claim("before_state"),
    ]
    honesty = [_honesty(c.id) for c in claims]
    frame = PlanFrame(claims=claims, honesty_conditions=honesty)
    result = converge(frame)
    assert result.passed is True
    assert result.missing_kinds == []
    assert result.claims_missing_honesty == []
    assert result.skipped_optional == []


def test_why_it_matters_satisfies_before_state_or_why_it_matters():
    """why_it_matters alone satisfies the before_state OR why_it_matters requirement."""
    claims = [
        _claim("announcement"),
        _claim("audience"),
        _claim("after_state"),
        _claim("boundary"),
        _claim("success_signal"),
        _claim("why_it_matters"),
    ]
    honesty = [_honesty(c.id) for c in claims]
    frame = PlanFrame(claims=claims, honesty_conditions=honesty)
    result = converge(frame)
    assert result.passed is True
    assert "before_state_or_why_it_matters" not in result.missing_kinds


def test_both_before_state_and_why_it_matters_passes():
    """Having both before_state and why_it_matters is fine."""
    claims = [
        _claim("announcement"),
        _claim("audience"),
        _claim("after_state"),
        _claim("boundary"),
        _claim("success_signal"),
        _claim("before_state"),
        _claim("why_it_matters"),
    ]
    honesty = [_honesty(c.id) for c in claims]
    frame = PlanFrame(claims=claims, honesty_conditions=honesty)
    result = converge(frame)
    assert result.passed is True


# ── honesty condition checks ────────────────────────────────────────────────

def test_unconfirmed_honesty_blocks():
    """A confirmed claim with only a proposed honesty condition still blocks."""
    claims = [
        _claim("announcement"),
        _claim("audience"),
        _claim("after_state"),
        _claim("boundary"),
        _claim("success_signal"),
        _claim("before_state"),
    ]
    # All honesty conditions are proposed, not confirmed
    honesty = [_honesty(c.id, state="proposed") for c in claims]
    frame = PlanFrame(claims=claims, honesty_conditions=honesty)
    result = converge(frame)
    assert result.passed is False
    assert result.missing_kinds == []
    assert result.claims_missing_honesty == [
        "announcement",
        "audience",
        "after_state",
        "boundary",
        "success_signal",
        "before_state",
    ]


def test_rejected_honesty_does_not_satisfy():
    """A rejected honesty condition does not count as confirmed."""
    claims = [
        _claim("announcement"),
        _claim("audience"),
        _claim("after_state"),
        _claim("boundary"),
        _claim("success_signal"),
        _claim("before_state"),
    ]
    honesty = [_honesty(c.id, state="rejected") for c in claims]
    frame = PlanFrame(claims=claims, honesty_conditions=honesty)
    result = converge(frame)
    assert result.passed is False
    assert result.claims_missing_honesty == [
        "announcement",
        "audience",
        "after_state",
        "boundary",
        "success_signal",
        "before_state",
    ]


def test_non_spec_affecting_claim_ignored_for_honesty():
    """assumption claims are not spec-affecting, so they don't need honesty."""
    claims = [
        _claim("announcement"),
        _claim("audience"),
        _claim("after_state"),
        _claim("boundary"),
        _claim("success_signal"),
        _claim("before_state"),
        _claim("assumption", id="assumption"),
    ]
    # Only spec-affecting claims get honesty conditions
    spec_affecting = [c for c in claims if c.kind != "assumption"]
    honesty = [_honesty(c.id) for c in spec_affecting]
    frame = PlanFrame(claims=claims, honesty_conditions=honesty)
    result = converge(frame)
    assert result.passed is True
    assert "assumption" not in result.claims_missing_honesty


def test_confirmed_requirement_needs_honesty():
    """requirement is spec-affecting and needs a confirmed honesty condition."""
    claims = [
        _claim("announcement"),
        _claim("audience"),
        _claim("after_state"),
        _claim("boundary"),
        _claim("success_signal"),
        _claim("before_state"),
        _claim("requirement", id="req-1"),
    ]
    # Spec-affecting claims without honesty for req-1
    spec_affecting = [c for c in claims if c.kind in {
        "announcement", "audience", "after_state", "before_state",
        "why_it_matters", "boundary", "success_signal", "requirement",
    }]
    honesty = [_honesty(c.id) for c in spec_affecting if c.id != "req-1"]
    frame = PlanFrame(claims=claims, honesty_conditions=honesty)
    result = converge(frame)
    assert result.passed is False
    assert "req-1" in result.claims_missing_honesty


def test_unconfirmed_spec_affecting_claim_ignored_for_honesty():
    """A proposed requirement claim is not checked for honesty."""
    claims = [
        _claim("announcement"),
        _claim("audience"),
        _claim("after_state"),
        _claim("boundary"),
        _claim("success_signal"),
        _claim("before_state"),
        _claim("requirement", id="req-1", state="proposed"),
    ]
    spec_affecting = [c for c in claims if c.kind in {
        "announcement", "audience", "after_state", "before_state",
        "why_it_matters", "boundary", "success_signal", "requirement",
    } and c.state == "confirmed"]
    honesty = [_honesty(c.id) for c in spec_affecting]
    frame = PlanFrame(claims=claims, honesty_conditions=honesty)
    result = converge(frame)
    assert result.passed is True
    assert "req-1" not in result.claims_missing_honesty


# ── optional steps ───────────────────────────────────────────────────────────

def test_optional_step_skipped_and_recorded():
    """Skipping an optional step is permitted and the id is recorded."""
    claims = [
        _claim("announcement"),
        _claim("audience"),
        _claim("after_state"),
        _claim("boundary"),
        _claim("success_signal"),
        _claim("before_state"),
    ]
    honesty = [_honesty(c.id) for c in claims]
    steps = [_step("opt-1", mandatory=False)]
    frame = PlanFrame(claims=claims, honesty_conditions=honesty, steps=steps)
    result = converge(frame)
    assert result.passed is True
    assert "opt-1" in result.skipped_optional


def test_mandatory_step_not_skipped():
    """Mandatory steps are not recorded as skipped."""
    claims = [
        _claim("announcement"),
        _claim("audience"),
        _claim("after_state"),
        _claim("boundary"),
        _claim("success_signal"),
        _claim("before_state"),
    ]
    honesty = [_honesty(c.id) for c in claims]
    steps = [_step("mandatory-1", mandatory=True)]
    frame = PlanFrame(claims=claims, honesty_conditions=honesty, steps=steps)
    result = converge(frame)
    assert result.passed is True
    assert "mandatory-1" not in result.skipped_optional


def test_mixed_steps_only_optional_recorded():
    """Only optional steps appear in skipped_optional."""
    claims = [
        _claim("announcement"),
        _claim("audience"),
        _claim("after_state"),
        _claim("boundary"),
        _claim("success_signal"),
        _claim("before_state"),
    ]
    honesty = [_honesty(c.id) for c in claims]
    steps = [
        _step("mandatory-1", mandatory=True),
        _step("opt-1", mandatory=False),
        _step("opt-2", mandatory=False),
    ]
    frame = PlanFrame(claims=claims, honesty_conditions=honesty, steps=steps)
    result = converge(frame)
    assert result.passed is True
    assert result.skipped_optional == ["opt-1", "opt-2"]


# ── ConvergenceResult dataclass ──────────────────────────────────────────────

def test_convergence_result_fields():
    """ConvergenceResult has the expected fields."""
    result = ConvergenceResult(
        passed=False,
        missing_kinds=["announcement"],
        claims_missing_honesty=["c1"],
        skipped_optional=["opt-1"],
    )
    assert result.passed is False
    assert result.missing_kinds == ["announcement"]
    assert result.claims_missing_honesty == ["c1"]
    assert result.skipped_optional == ["opt-1"]


def test_convergence_result_passed_true():
    """ConvergenceResult with empty lists is passed."""
    result = ConvergenceResult(
        passed=True,
        missing_kinds=[],
        claims_missing_honesty=[],
        skipped_optional=[],
    )
    assert result.passed is True
