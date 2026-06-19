"""Tests for plan-mode behaviours #215 (dedicated honesty call) and #224 (honesty-gap naming).

Covers:
  1. Dedicated honesty call fills missing honesty conditions (#215).
  2. Per-claim honesty fallback is bounded by _MAX_HONESTY_FALLBACK (#215).
  3. workforce=False skips fan-out (#215).
  4. _render_run names honesty gaps without '(none)' (#224).
  5. _run_payload always names a reason for non-convergence (#224).

All tests use scripted in-memory mocks — no network, no real engine.
"""

from __future__ import annotations

from colleague.contract import SubResult, Usage
from colleague.plan.cli_driver import (
    _MAX_HONESTY_FALLBACK,
    CLAIMS_HONESTY_SYSTEM_PROMPT,
    CLAIMS_MANDATORY_SYSTEM_PROMPT,
    CLAIMS_REQUIREMENTS_SYSTEM_PROMPT,
    make_propose_claims,
)
from colleague.plan.convergence import SPEC_AFFECTING_KINDS, ConvergenceResult
from colleague.plan.frame import Claim, HonestyCondition
from colleague.plan.orchestrator import OrchestratorResult, run_plan_mode
from colleague.plan.plan_stage import PlanItem
from colleague.plan.spec_stage import SpecStageResult

# ── helpers ──────────────────────────────────────────────────────────────────


def _claim(
    id: str = "",
    kind: str = "announcement",
    text: str = "",
    state: str = "proposed",
) -> Claim:
    return Claim(
        id=id or kind,
        kind=kind,
        text=text or f"{kind} text",
        state=state,
    )


def _honesty(
    id: str = "",
    claim_id: str = "",
    text: str = "",
    state: str = "proposed",
) -> HonestyCondition:
    return HonestyCondition(
        id=id or f"h-{claim_id}",
        claim_id=claim_id,
        text=text or f"hc for {claim_id}",
        state=state,
    )


def _subresult(task_id: str) -> SubResult:
    return SubResult(
        task_id=task_id,
        engine="mock",
        model="test-model",
        status="OK",
        summary=f"Result for {task_id}",
        usage=Usage(),
    )


# ── (1) Dedicated honesty call fills missing honesty conditions ─────────────


def test_dedicated_honesty_call_fills_missing() -> None:
    """Call 1 (mandatory) returns 2 claims; call 2 (requirements) returns 1
    requirement claim and NO honesty; the dedicated honesty call
    (CLAIMS_HONESTY_SYSTEM_PROMPT) returns honesty with one entry per claim
    BUT reusing id 'h1' for all of them.

    Assert every spec-affecting claim is covered (by claim_id) and all honesty
    ids are unique (the _ClaimAcc absorbs them with minted ids).
    """
    call_count = 0

    def simple(system: str, user: str) -> str:
        nonlocal call_count
        call_count += 1

        if system == CLAIMS_MANDATORY_SYSTEM_PROMPT:
            # Call 1: two mandatory claims
            return (
                '{"claims": '
                '[{"id": "c1", "kind": "announcement", "text": "ships"}, '
                '{"id": "c2", "kind": "audience", "text": "ops"}], '
                '"honesty": []}'
            )

        if system == CLAIMS_REQUIREMENTS_SYSTEM_PROMPT:
            # Call 2: one requirement claim, NO honesty
            return (
                '{"claims": '
                '[{"id": "c3", "kind": "requirement", "text": "fast"}], '
                '"honesty": []}'
            )

        if system == CLAIMS_HONESTY_SYSTEM_PROMPT:
            # Dedicated honesty call: one entry per spec-affecting claim,
            # reusing id "h1" for all of them (the weak-model failure mode).
            return (
                '{"honesty": '
                '[{"id": "h1", "claim_id": "c1", "text": "c1 is true"}, '
                '{"id": "h1", "claim_id": "c2", "text": "c2 is true"}, '
                '{"id": "h1", "claim_id": "c3", "text": "c3 is true"}]}'
            )

        # Per-claim fallback (should not be reached since batch covered all).
        return '{"honesty": []}'

    propose = make_propose_claims(simple)
    claims, honesty = propose("build a thing")

    # Three claims total
    assert [c.id for c in claims] == ["c1", "c2", "c3"]

    # All spec-affecting claims are covered by claim_id
    covered = {h.claim_id for h in honesty}
    spec_affecting_ids = {c.id for c in claims if c.kind in SPEC_AFFECTING_KINDS}
    assert spec_affecting_ids.issubset(covered)

    # All honesty ids are unique (minted by _ClaimAcc.absorb_honesty)
    honesty_ids = [h.id for h in honesty]
    assert len(honesty_ids) == len(set(honesty_ids))


# ── (2) Per-claim honesty fallback is bounded ───────────────────────────────


def test_per_claim_honesty_fallback_bounded() -> None:
    """Dedicated batch honesty call returns unparseable text; each per-claim
    call (ONE_HONESTY_SYSTEM_PROMPT) returns one honesty.

    Assert remaining claims are covered and per-claim call count <=
    _MAX_HONESTY_FALLBACK.
    """
    call_count = 0
    per_claim_count = 0

    def simple(system: str, user: str) -> str:
        nonlocal call_count, per_claim_count
        call_count += 1

        if system == CLAIMS_MANDATORY_SYSTEM_PROMPT:
            # Call 1: three spec-affecting claims
            return (
                '{"claims": '
                '[{"id": "c1", "kind": "announcement", "text": "ships"}, '
                '{"id": "c2", "kind": "audience", "text": "ops"}, '
                '{"id": "c3", "kind": "boundary", "text": "safe"}], '
                '"honesty": []}'
            )

        if system == CLAIMS_REQUIREMENTS_SYSTEM_PROMPT:
            # Call 2: no claims, no honesty
            return '{"claims": [], "honesty": []}'

        if system == CLAIMS_HONESTY_SYSTEM_PROMPT:
            # Dedicated batch honesty: unparseable text
            return "not valid json at all"

        # Per-claim fallback: each returns one honesty
        # The system prompt has CLAIM_ID replaced with the actual claim id,
        # so we check for the distinctive "Propose ONE honesty" prefix.
        if "Propose ONE honesty" in system:
            nonlocal per_claim_count
            per_claim_count += 1
            # Extract claim id from user prompt: "Claim <id> (<kind>): <text>"
            claim_id = user.split(" ")[1]  # "Claim c1 ..."
            return '{"honesty": [{"id": "h1", "claim_id": "' + claim_id + '", "text": "ok"}]}'

        return '{"honesty": []}'

    propose = make_propose_claims(simple)
    claims, honesty = propose("build a thing")

    # Three claims total
    assert [c.id for c in claims] == ["c1", "c2", "c3"]

    # All spec-affecting claims covered
    covered = {h.claim_id for h in honesty}
    spec_affecting_ids = {c.id for c in claims if c.kind in SPEC_AFFECTING_KINDS}
    assert spec_affecting_ids.issubset(covered)

    # Per-claim call count bounded
    assert per_claim_count <= _MAX_HONESTY_FALLBACK


# ── (3) workforce=False skips fan-out ───────────────────────────────────────


def test_no_workforce_skips_fanout() -> None:
    """run_plan_mode(quick=True, workforce=False) with an injected batch_spawn
    recording calls; assert batch_spawn never called, result.waves==[] and
    result.sub_results==[], result.plan_items non-empty, result.converged True.
    """
    batch_spawn_calls: list[list[dict]] = []

    def batch_spawn(items: list[dict]) -> list[SubResult]:
        batch_spawn_calls.append(items)
        return [_subresult("child-0")]

    result = run_plan_mode(
        "plan this",
        propose_claims=lambda r: ([], []),
        decide=lambda item, critique: "confirm",
        propose_plan_items=lambda frame: [
            PlanItem(id="t1", summary="do A", acceptance=["A works"]),
        ],
        batch_spawn=batch_spawn,
        engine="mock",
        model="test-model",
        quick=True,
        workforce=False,
    )

    # batch_spawn never called
    assert len(batch_spawn_calls) == 0

    # Result shape
    assert result.waves == []
    assert result.sub_results == []
    assert len(result.plan_items) >= 1
    assert result.converged is True


# ── (4) _render_run and _run_payload name honesty gaps (#224) ───────────────


def test_render_and_payload_name_honesty_gap() -> None:
    """A result whose spec_result.result is ConvergenceResult(passed=False,
    missing_kinds=[], claims_missing_honesty=['c1','c2']); assert _render_run
    output has no '(none)' and names c1 and c2, and _run_payload
    ['claims_missing_honesty']==['c1','c2'].
    """
    from colleague.cli._commands.plan import _render_run, _run_payload

    conv = ConvergenceResult(
        passed=False,
        missing_kinds=[],
        claims_missing_honesty=["c1", "c2"],
    )
    spec_result = SpecStageResult(transcript=[], result=conv)
    result = OrchestratorResult(
        spec_result=spec_result,
        converged=False,
        plan_items=[],
        waves=[],
        sub_results=[],
        conflicts=[],
    )

    # _render_run must not contain '(none)'
    rendered = _render_run(result)
    assert "(none)" not in rendered
    assert "c1" in rendered
    assert "c2" in rendered

    # _run_payload must carry claims_missing_honesty
    payload = _run_payload(result)
    assert payload["claims_missing_honesty"] == ["c1", "c2"]


# ── (5) Non-converged result always names a reason ──────────────────────────


def test_non_converged_always_names_a_reason() -> None:
    """For a non-converged result assert _run_payload has a non-empty
    missing_kinds OR claims_missing_honesty.
    """
    from colleague.cli._commands.plan import _run_payload

    # Case 1: missing_kinds non-empty
    conv1 = ConvergenceResult(
        passed=False,
        missing_kinds=["announcement"],
        claims_missing_honesty=[],
    )
    result1 = OrchestratorResult(
        spec_result=SpecStageResult(transcript=[], result=conv1),
        converged=False,
    )
    payload1 = _run_payload(result1)
    assert payload1["missing_kinds"] or payload1["claims_missing_honesty"]

    # Case 2: claims_missing_honesty non-empty
    conv2 = ConvergenceResult(
        passed=False,
        missing_kinds=[],
        claims_missing_honesty=["c1"],
    )
    result2 = OrchestratorResult(
        spec_result=SpecStageResult(transcript=[], result=conv2),
        converged=False,
    )
    payload2 = _run_payload(result2)
    assert payload2["missing_kinds"] or payload2["claims_missing_honesty"]

    # Case 3: both non-empty
    conv3 = ConvergenceResult(
        passed=False,
        missing_kinds=["audience"],
        claims_missing_honesty=["c2"],
    )
    result3 = OrchestratorResult(
        spec_result=SpecStageResult(transcript=[], result=conv3),
        converged=False,
    )
    payload3 = _run_payload(result3)
    assert payload3["missing_kinds"] or payload3["claims_missing_honesty"]
