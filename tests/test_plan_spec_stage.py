"""Tests for colleague.plan.spec_stage — the SPEC STAGE micro-cycle.

Covers:
  (a) GateRecord dataclass with to_dict / from_dict round-trip.
  (b) SpecStageResult dataclass.
  (c) run_spec_stage: per-item gating, deterministic order, transcript fidelity.
  (d) Confirm-all path → convergence passes.
  (e) Reject-mandatory path → convergence fails.
  (f) reviewer_enabled=False → no critique in records.
  (g) reviewer_enabled=True → critique populated from complete callable.
"""

from __future__ import annotations

from colleague.plan.convergence import ConvergenceResult, converge
from colleague.plan.frame import Claim, HonestyCondition, PlanFrame
from colleague.plan.spec_stage import GateRecord, SpecStageResult, run_spec_stage

# ── helpers ──────────────────────────────────────────────────────────────────


def _claim(kind: str, state: str = "proposed", id: str = "") -> Claim:
    return Claim(id=id or kind, kind=kind, text=f"{kind} text", state=state)


def _honesty(claim_id: str, state: str = "proposed", id: str = "") -> HonestyCondition:
    return HonestyCondition(
        id=id or f"hc-{claim_id}",
        claim_id=claim_id,
        text=f"hc for {claim_id}",
        state=state,
    )


def _full_frame() -> PlanFrame:
    """Build a PlanFrame with all mandatory kinds as proposed claims,
    plus a confirmed-honesty path (one already-confirmed honesty condition
    attached to a proposed claim)."""
    claims = [
        _claim("announcement"),
        _claim("audience"),
        _claim("after_state"),
        _claim("boundary"),
        _claim("success_signal"),
        _claim("before_state"),
    ]
    # One honesty condition already confirmed (attached to "announcement")
    # The rest are proposed.
    honesty = [
        _honesty("announcement", state="confirmed"),
        _honesty("audience"),
        _honesty("after_state"),
        _honesty("boundary"),
        _honesty("success_signal"),
        _honesty("before_state"),
    ]
    return PlanFrame(claims=claims, honesty_conditions=honesty)


def _always_confirm(item, critique) -> str:
    return "confirm"


def _reject_first(item, critique) -> str:
    """Reject the first item, confirm the rest."""
    if not hasattr(_reject_first, "_called"):
        _reject_first._called = True
        return "reject"
    return "confirm"


# ── (a) GateRecord ───────────────────────────────────────────────────────────


class TestGateRecord:
    def test_fields(self):
        rec = GateRecord(
            item_id="c1",
            item_kind="claim",
            critique="too broad",
            decision="confirm",
        )
        assert rec.item_id == "c1"
        assert rec.item_kind == "claim"
        assert rec.critique == "too broad"
        assert rec.decision == "confirm"

    def test_fields_none_critique(self):
        rec = GateRecord(
            item_id="h1",
            item_kind="honesty",
            critique=None,
            decision="reject",
        )
        assert rec.critique is None
        assert rec.decision == "reject"

    def test_to_dict(self):
        rec = GateRecord("c1", "claim", "weak", "confirm")
        d = rec.to_dict()
        assert d == {
            "item_id": "c1",
            "item_kind": "claim",
            "critique": "weak",
            "decision": "confirm",
        }

    def test_from_dict(self):
        d = {
            "item_id": "c1",
            "item_kind": "claim",
            "critique": "weak",
            "decision": "confirm",
        }
        rec = GateRecord.from_dict(d)
        assert rec.item_id == "c1"
        assert rec.item_kind == "claim"
        assert rec.critique == "weak"
        assert rec.decision == "confirm"

    def test_from_dict_none_critique(self):
        d = {
            "item_id": "h1",
            "item_kind": "honesty",
            "critique": None,
            "decision": "reject",
        }
        rec = GateRecord.from_dict(d)
        assert rec.critique is None

    def test_round_trip(self):
        original = GateRecord("x", "claim", None, "confirm")
        restored = GateRecord.from_dict(original.to_dict())
        assert original == restored


# ── (b) SpecStageResult ──────────────────────────────────────────────────────


class TestSpecStageResult:
    def test_fields(self):
        result = SpecStageResult(
            transcript=[GateRecord("c1", "claim", None, "confirm")],
            result=ConvergenceResult(passed=True),
        )
        assert len(result.transcript) == 1
        assert result.result.passed is True

    def test_empty_transcript(self):
        result = SpecStageResult(
            transcript=[],
            result=ConvergenceResult(passed=False),
        )
        assert result.transcript == []
        assert result.result.passed is False


# ── (c) run_spec_stage: per-item gating ─────────────────────────────────────


class TestRunSpecStage:
    def test_transcript_length_matches_proposed_items(self):
        """Exactly one GateRecord per proposed item."""
        frame = _full_frame()
        # 6 proposed claims + 6 proposed honesty conditions = 12
        proposed_claims = [c for c in frame.claims if c.state == "proposed"]
        proposed_honesty = [h for h in frame.honesty_conditions if h.state == "proposed"]
        expected_count = len(proposed_claims) + len(proposed_honesty)

        result = run_spec_stage(frame, _always_confirm)
        assert len(result.transcript) == expected_count

    def test_order_claims_before_honesty(self):
        """Claims come before honesty conditions in the transcript."""
        frame = _full_frame()
        result = run_spec_stage(frame, _always_confirm)

        # Find the boundary: last claim record should come before first honesty record
        claim_indices = [i for i, r in enumerate(result.transcript) if r.item_kind == "claim"]
        honesty_indices = [i for i, r in enumerate(result.transcript) if r.item_kind == "honesty"]

        assert len(claim_indices) > 0
        assert len(honesty_indices) > 0
        assert max(claim_indices) < min(honesty_indices)

    def test_list_order_preserved(self):
        """Within claims, original list order is preserved."""
        frame = _full_frame()
        # Capture expected IDs before mutation
        expected_claim_ids = [c.id for c in frame.claims if c.state == "proposed"]
        expected_honesty_ids = [h.id for h in frame.honesty_conditions if h.state == "proposed"]

        result = run_spec_stage(frame, _always_confirm)

        claim_records = [r for r in result.transcript if r.item_kind == "claim"]
        claim_ids = [r.item_id for r in claim_records]
        assert claim_ids == expected_claim_ids

        honesty_records = [r for r in result.transcript if r.item_kind == "honesty"]
        honesty_ids = [r.item_id for r in honesty_records]
        assert honesty_ids == expected_honesty_ids

    def test_decide_called_once_per_proposed_item(self):
        """The decide callable is invoked exactly once per proposed item."""
        frame = _full_frame()
        # Capture expected count before mutation
        proposed_claims = [c for c in frame.claims if c.state == "proposed"]
        proposed_honesty = [h for h in frame.honesty_conditions if h.state == "proposed"]
        expected_count = len(proposed_claims) + len(proposed_honesty)

        call_count = 0

        def counting_decide(item, critique) -> str:
            nonlocal call_count
            call_count += 1
            return "confirm"

        run_spec_stage(frame, counting_decide)
        assert call_count == expected_count

    def test_item_states_updated_on_confirm(self):
        """After confirming all, all proposed items become confirmed."""
        frame = _full_frame()
        run_spec_stage(frame, _always_confirm)

        for c in frame.claims:
            assert c.state == "confirmed"
        for h in frame.honesty_conditions:
            assert h.state == "confirmed"

    def test_item_states_updated_on_reject(self):
        """Rejected items get state='rejected'."""
        frame = _full_frame()

        def reject_all(item, critique) -> str:
            return "reject"

        run_spec_stage(frame, reject_all)

        # Only the proposed items should be rejected; already-confirmed stays confirmed
        for c in frame.claims:
            assert c.state == "rejected"
        # The already-confirmed honesty stays confirmed (not proposed)
        for h in frame.honesty_conditions:
            if h.state == "confirmed":
                pass  # stays confirmed
            else:
                assert h.state == "rejected"


# ── (d) Confirm-all path → convergence passes ──────────────────────────────


class TestConfirmAllPath:
    def test_all_confirmed_convergence_passes(self):
        """Confirming all mandatory items + honesty → convergence passes."""
        frame = _full_frame()
        result = run_spec_stage(frame, _always_confirm)
        assert result.result.passed is True
        assert result.result.missing_kinds == []
        assert result.result.claims_missing_honesty == []

    def test_result_is_converge_output(self):
        """SpecStageResult.result equals converge(frame) after processing."""
        frame = _full_frame()
        result = run_spec_stage(frame, _always_confirm)
        expected = converge(frame)
        assert result.result.passed == expected.passed
        assert result.result.missing_kinds == expected.missing_kinds
        assert result.result.claims_missing_honesty == expected.claims_missing_honesty


# ── (e) Reject-mandatory path → convergence fails ──────────────────────────


class TestRejectMandatoryPath:
    def test_rejecting_mandatory_claim_fails_convergence(self):
        """Rejecting a mandatory claim → result.passed is False."""
        frame = _full_frame()

        def reject_announcement(item, critique) -> str:
            if hasattr(item, "id") and item.id == "announcement":
                return "reject"
            return "confirm"

        result = run_spec_stage(frame, reject_announcement)
        assert result.result.passed is False
        assert "announcement" in result.result.missing_kinds

    def test_rejecting_one_mandatory_kind_blocks(self):
        """Rejecting boundary → boundary is missing."""
        frame = _full_frame()

        def reject_boundary(item, critique) -> str:
            if hasattr(item, "id") and item.id == "boundary":
                return "reject"
            return "confirm"

        result = run_spec_stage(frame, reject_boundary)
        assert result.result.passed is False
        assert "boundary" in result.result.missing_kinds


# ── (f) reviewer_enabled=False ──────────────────────────────────────────────


class TestReviewerDisabled:
    def test_no_critique_in_records(self):
        """When reviewer_enabled=False, all GateRecord.critique are None."""
        frame = _full_frame()
        result = run_spec_stage(frame, _always_confirm, reviewer_enabled=False)

        for record in result.transcript:
            assert record.critique is None

    def test_works_without_complete(self):
        """reviewer_enabled=False works even when complete=None."""
        frame = _full_frame()
        result = run_spec_stage(frame, _always_confirm, complete=None, reviewer_enabled=False)
        for record in result.transcript:
            assert record.critique is None


# ── (g) reviewer_enabled=True ──────────────────────────────────────────────


class TestReviewerEnabled:
    def test_critique_populated_when_enabled(self):
        """When reviewer_enabled=True and complete is provided, critique is set."""

        def fake_complete(system: str, user: str) -> str:
            return "advisory concern"

        frame = _full_frame()
        result = run_spec_stage(
            frame, _always_confirm, complete=fake_complete, reviewer_enabled=True
        )

        for record in result.transcript:
            assert record.critique == "advisory concern"

    def test_complete_called_for_each_proposed_item(self):
        """complete is called once per proposed item when reviewer is enabled."""
        frame = _full_frame()
        # Capture expected count before mutation
        proposed_claims = [c for c in frame.claims if c.state == "proposed"]
        proposed_honesty = [h for h in frame.honesty_conditions if h.state == "proposed"]
        expected = len(proposed_claims) + len(proposed_honesty)

        call_count = 0

        def counting_complete(system: str, user: str) -> str:
            nonlocal call_count
            call_count += 1
            return "critique"

        run_spec_stage(frame, _always_confirm, complete=counting_complete, reviewer_enabled=True)

        assert call_count == expected

    def test_complete_not_called_when_disabled(self):
        """complete is never called when reviewer_enabled=False."""
        frame = _full_frame()

        def should_not_be_called(system: str, user: str) -> str:
            raise RuntimeError("complete should not be called")

        run_spec_stage(
            frame, _always_confirm, complete=should_not_be_called, reviewer_enabled=False
        )

    def test_complete_none_with_reviewer_enabled_is_noop(self):
        """When complete=None and reviewer_enabled=True, critique is None."""
        frame = _full_frame()
        result = run_spec_stage(frame, _always_confirm, complete=None, reviewer_enabled=True)
        for record in result.transcript:
            assert record.critique is None


# ── (h) Empty frame edge case ───────────────────────────────────────────────


class TestEmptyFrame:
    def test_empty_frame_produces_empty_transcript(self):
        """A frame with no proposed items produces an empty transcript."""
        frame = PlanFrame()
        result = run_spec_stage(frame, _always_confirm)
        assert result.transcript == []
        # Convergence of an empty frame fails (all mandatory kinds missing)
        assert result.result.passed is False

    def test_no_proposed_items_no_decide_calls(self):
        """If no items are proposed, decide is never called."""
        frame = PlanFrame(
            claims=[_claim("announcement", state="confirmed")],
            honesty_conditions=[_honesty("announcement", state="confirmed")],
        )
        call_count = 0

        def counting_decide(item, critique) -> str:
            nonlocal call_count
            call_count += 1
            return "confirm"

        run_spec_stage(frame, counting_decide)
        assert call_count == 0


# ── (i) Already-confirmed items skipped ─────────────────────────────────────


class TestAlreadyConfirmedSkipped:
    def test_confirmed_items_not_in_transcript(self):
        """Items already confirmed are not processed (not in transcript)."""
        frame = PlanFrame(
            claims=[
                _claim("announcement", state="confirmed"),
                _claim("audience", state="proposed"),
            ],
            honesty_conditions=[
                _honesty("announcement", state="confirmed"),
                _honesty("audience", state="proposed"),
            ],
        )
        result = run_spec_stage(frame, _always_confirm)

        # Only the proposed items should appear
        item_ids = [r.item_id for r in result.transcript]
        assert "audience" in item_ids
        assert "announcement" not in item_ids
        assert "hc-audience" in item_ids
        assert "hc-announcement" not in item_ids

    def test_confirmed_items_not_mutated(self):
        """Already-confirmed items keep their confirmed state."""
        frame = PlanFrame(
            claims=[
                _claim("announcement", state="confirmed"),
                _claim("audience", state="proposed"),
            ],
            honesty_conditions=[
                _honesty("announcement", state="confirmed"),
                _honesty("audience", state="proposed"),
            ],
        )
        run_spec_stage(frame, _always_confirm)

        ann = frame.claims[0]
        aud = frame.claims[1]
        assert ann.state == "confirmed"
        assert aud.state == "confirmed"

        hc_ann = frame.honesty_conditions[0]
        hc_aud = frame.honesty_conditions[1]
        assert hc_ann.state == "confirmed"
        assert hc_aud.state == "confirmed"
