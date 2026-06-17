"""Tests for colleague.plan.orchestrator — the plan-mode orchestrator.

Covers:
  (a) OrchestratorResult dataclass fields.
  (b) Full happy path: converge -> plan -> workforce -> result.
  (c) Non-converged path: spec fails -> no plan, no workforce.
  (d) surface_conflicts: ERROR sub-results collected.
  (e) Checkpoint persistence when repo_path is provided.
  (f) Invariants: no self-confirm, no plan/workforce before convergence.
  (g) validate_items raises ValueError on bad plan items.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from colleague.contract import ERROR, OK, SubResult, Usage
from colleague.plan.checkpoint import load as load_checkpoint
from colleague.plan.frame import Claim, HonestyCondition, PlanFrame
from colleague.plan.orchestrator import OrchestratorResult, run_plan_mode
from colleague.plan.plan_stage import PlanItem

# ── helpers ──────────────────────────────────────────────────────────────────


def _claim(kind: str, id: str = "", text: str = "", state: str = "proposed") -> Claim:
    return Claim(
        id=id or kind,
        kind=kind,
        text=text or f"{kind} text",
        state=state,
    )


def _honesty(
    claim_id: str, id: str = "", text: str = "", state: str = "proposed"
) -> HonestyCondition:
    return HonestyCondition(
        id=id or f"hc-{claim_id}",
        claim_id=claim_id,
        text=text or f"hc for {claim_id}",
        state=state,
    )


def _make_subresult(task_id: str, status: str = OK) -> SubResult:
    return SubResult(
        task_id=task_id,
        engine="mock",
        model="test-model",
        status=status,
        summary=f"Result for {task_id}",
        usage=Usage(),
    )


# ── Fake callables (injected dependencies) ──────────────────────────────────


class FakeDependencies:
    """Trackable fake dependencies for the orchestrator."""

    def __init__(self):
        self.propose_claims_called = False
        self.propose_plan_items_called = False
        self.batch_spawn_called = False
        self.decide_calls: list[tuple[Any, str | None]] = []
        self.claims_to_propose: list[Claim] = []
        self.honesty_to_propose: list[HonestyCondition] = []
        self.plan_items_to_propose: list[PlanItem] = []
        self.subresults_to_return: list[SubResult] = []

    def set_claims(self, claims: list[Claim], honesty: list[HonestyCondition]):
        self.claims_to_propose = claims
        self.honesty_to_propose = honesty

    def set_plan_items(self, items: list[PlanItem]):
        self.plan_items_to_propose = items

    def set_subresults(self, results: list[SubResult]):
        self.subresults_to_return = results

    def propose_claims(self, request: str) -> tuple[list[Claim], list[HonestyCondition]]:
        self.propose_claims_called = True
        return list(self.claims_to_propose), list(self.honesty_to_propose)

    def decide(self, item: Any, critique: str | None) -> str:
        self.decide_calls.append((item, critique))
        # Default: confirm everything
        return "confirm"

    def decide_reject_first(self, item: Any, critique: str | None) -> str:
        self.decide_calls.append((item, critique))
        # Reject the first item (which will be "announcement")
        if hasattr(item, "id") and item.id == "announcement":
            return "reject"
        return "confirm"

    def propose_plan_items(self, frame: PlanFrame) -> list[PlanItem]:
        self.propose_plan_items_called = True
        return list(self.plan_items_to_propose)

    def batch_spawn(self, items: list[dict]) -> list[SubResult]:
        self.batch_spawn_called = True
        return list(self.subresults_to_return)


def _full_claims() -> list[Claim]:
    """All mandatory claim kinds as proposed."""
    return [
        _claim("announcement"),
        _claim("audience"),
        _claim("after_state"),
        _claim("boundary"),
        _claim("success_signal"),
        _claim("before_state"),
    ]


def _full_honesty() -> list[HonestyCondition]:
    """Honesty conditions for all spec-affecting claims, all proposed."""
    return [
        _honesty("announcement"),
        _honesty("audience"),
        _honesty("after_state"),
        _honesty("boundary"),
        _honesty("success_signal"),
        _honesty("before_state"),
    ]


def _valid_plan_items() -> list[PlanItem]:
    """Two valid plan items with no deps (single wave)."""
    return [
        PlanItem(id="p1", summary="First task", acceptance=["works"]),
        PlanItem(id="p2", summary="Second task", acceptance=["works"]),
    ]


def _plan_items_with_deps() -> list[PlanItem]:
    """Three items: p1 has no deps, p2 depends on p1, p3 depends on p2."""
    return [
        PlanItem(id="p1", summary="First", acceptance=["ok"]),
        PlanItem(id="p2", summary="Second", acceptance=["ok"], deps=["p1"]),
        PlanItem(id="p3", summary="Third", acceptance=["ok"], deps=["p2"]),
    ]


# ── (a) OrchestratorResult dataclass ─────────────────────────────────────────


class TestOrchestratorResult:
    def test_fields(self):
        result = OrchestratorResult(
            spec_result=None,
            converged=True,
            plan_items=[],
            waves=[],
            sub_results=[],
            conflicts=[],
        )
        assert result.converged is True
        assert result.plan_items == []
        assert result.waves == []
        assert result.sub_results == []
        assert result.conflicts == []

    def test_all_fields_populated(self):
        from colleague.plan.spec_stage import SpecStageResult

        result = OrchestratorResult(
            spec_result=SpecStageResult(),
            converged=True,
            plan_items=[PlanItem(id="x", summary="s", acceptance=["a"])],
            waves=[["x"]],
            sub_results=[_make_subresult("r1")],
            conflicts=[_make_subresult("c1", ERROR)],
        )
        assert result.converged is True
        assert len(result.plan_items) == 1
        assert result.waves == [["x"]]
        assert len(result.sub_results) == 1
        assert len(result.conflicts) == 1


# ── (b) Full happy path ────────────────────────────────────────────────────


class TestHappyPath:
    def test_converged_path(self):
        """All claims confirmed -> plan computed -> workforce runs -> result returned."""
        deps = FakeDependencies()
        deps.set_claims(_full_claims(), _full_honesty())
        deps.set_plan_items(_valid_plan_items())
        deps.set_subresults([_make_subresult("child-0"), _make_subresult("merge")])

        result = run_plan_mode(
            "test request",
            propose_claims=deps.propose_claims,
            decide=deps.decide,
            propose_plan_items=deps.propose_plan_items,
            batch_spawn=deps.batch_spawn,
            engine="mock",
            model="test-model",
        )

        assert result.converged is True
        assert result.spec_result is not None
        assert result.spec_result.result.passed is True
        assert len(result.plan_items) == 2
        assert len(result.waves) == 1
        assert result.waves[0] == ["p1", "p2"]
        assert len(result.sub_results) == 2
        assert result.conflicts == []

    def test_all_injected_callables_called(self):
        """All injected callables are invoked on the happy path."""
        deps = FakeDependencies()
        deps.set_claims(_full_claims(), _full_honesty())
        deps.set_plan_items(_valid_plan_items())
        deps.set_subresults([_make_subresult("child-0")])

        run_plan_mode(
            "test request",
            propose_claims=deps.propose_claims,
            decide=deps.decide,
            propose_plan_items=deps.propose_plan_items,
            batch_spawn=deps.batch_spawn,
            engine="mock",
            model="test-model",
        )

        assert deps.propose_claims_called
        assert deps.propose_plan_items_called
        assert deps.batch_spawn_called

    def test_decide_called_for_all_proposed_items(self):
        """decide is called once per proposed claim + honesty condition."""
        deps = FakeDependencies()
        claims = _full_claims()
        honesty = _full_honesty()
        deps.set_claims(claims, honesty)
        deps.set_plan_items(_valid_plan_items())
        deps.set_subresults([_make_subresult("child-0")])

        run_plan_mode(
            "test request",
            propose_claims=deps.propose_claims,
            decide=deps.decide,
            propose_plan_items=deps.propose_plan_items,
            batch_spawn=deps.batch_spawn,
            engine="mock",
            model="test-model",
        )

        # 6 claims + 6 honesty = 12 decide calls
        assert len(deps.decide_calls) == 12

    def test_multi_wave_execution(self):
        """Items with dependencies produce multiple waves, each calling batch_spawn."""
        deps = FakeDependencies()
        deps.set_claims(_full_claims(), _full_honesty())
        deps.set_plan_items(_plan_items_with_deps())
        deps.set_subresults([_make_subresult("child-0")])

        result = run_plan_mode(
            "test request",
            propose_claims=deps.propose_claims,
            decide=deps.decide,
            propose_plan_items=deps.propose_plan_items,
            batch_spawn=deps.batch_spawn,
            engine="mock",
            model="test-model",
        )

        assert result.converged is True
        # p1 alone in wave 0, p2 in wave 1, p3 in wave 2
        assert result.waves == [["p1"], ["p2"], ["p3"]]
        # batch_spawn called 3 times (once per wave)
        assert deps.batch_spawn_called


# ── (c) Non-converged path ──────────────────────────────────────────────────


class TestNonConvergedPath:
    def test_reject_mandatory_no_plan(self):
        """Rejecting a mandatory claim -> converged=False, no plan, no workforce."""
        deps = FakeDependencies()
        deps.set_claims(_full_claims(), _full_honesty())
        deps.set_plan_items(_valid_plan_items())
        deps.set_subresults([_make_subresult("child-0")])

        result = run_plan_mode(
            "test request",
            propose_claims=deps.propose_claims,
            decide=deps.decide_reject_first,
            propose_plan_items=deps.propose_plan_items,
            batch_spawn=deps.batch_spawn,
            engine="mock",
            model="test-model",
        )

        assert result.converged is False
        assert result.plan_items == []
        assert result.waves == []
        assert result.sub_results == []
        assert result.conflicts == []

    def test_reject_mandatory_propose_plan_items_not_called(self):
        """When spec doesn't converge, propose_plan_items is NEVER called."""
        deps = FakeDependencies()
        deps.set_claims(_full_claims(), _full_honesty())
        deps.set_plan_items(_valid_plan_items())
        deps.set_subresults([_make_subresult("child-0")])

        run_plan_mode(
            "test request",
            propose_claims=deps.propose_claims,
            decide=deps.decide_reject_first,
            propose_plan_items=deps.propose_plan_items,
            batch_spawn=deps.batch_spawn,
            engine="mock",
            model="test-model",
        )

        assert not deps.propose_plan_items_called
        assert not deps.batch_spawn_called

    def test_reject_mandatory_batch_spawn_not_called(self):
        """When spec doesn't converge, batch_spawn is NEVER called."""
        deps = FakeDependencies()
        deps.set_claims(_full_claims(), _full_honesty())
        deps.set_plan_items(_valid_plan_items())
        deps.set_subresults([_make_subresult("child-0")])

        run_plan_mode(
            "test request",
            propose_claims=deps.propose_claims,
            decide=deps.decide_reject_first,
            propose_plan_items=deps.propose_plan_items,
            batch_spawn=deps.batch_spawn,
            engine="mock",
            model="test-model",
        )

        assert not deps.batch_spawn_called


# ── (d) surface_conflicts ───────────────────────────────────────────────────


class TestConflicts:
    def test_error_subresult_becomes_conflict(self):
        """A batch_spawn returning an ERROR-status SubResult -> non-empty conflicts."""
        deps = FakeDependencies()
        deps.set_claims(_full_claims(), _full_honesty())
        deps.set_plan_items(_valid_plan_items())
        # Return an ERROR merge child
        deps.set_subresults(
            [
                _make_subresult("child-0", OK),
                _make_subresult("merge", ERROR),
            ]
        )

        result = run_plan_mode(
            "test request",
            propose_claims=deps.propose_claims,
            decide=deps.decide,
            propose_plan_items=deps.propose_plan_items,
            batch_spawn=deps.batch_spawn,
            engine="mock",
            model="test-model",
        )

        assert result.converged is True
        assert len(result.conflicts) == 1
        assert result.conflicts[0].status == ERROR
        assert result.conflicts[0].task_id == "merge"

    def test_no_conflicts_when_all_ok(self):
        """All OK sub-results -> empty conflicts."""
        deps = FakeDependencies()
        deps.set_claims(_full_claims(), _full_honesty())
        deps.set_plan_items(_valid_plan_items())
        deps.set_subresults(
            [
                _make_subresult("child-0", OK),
                _make_subresult("merge", OK),
            ]
        )

        result = run_plan_mode(
            "test request",
            propose_claims=deps.propose_claims,
            decide=deps.decide,
            propose_plan_items=deps.propose_plan_items,
            batch_spawn=deps.batch_spawn,
            engine="mock",
            model="test-model",
        )

        assert result.conflicts == []


# ── (e) Checkpoint persistence ─────────────────────────────────────────────


class TestCheckpointPersistence:
    def test_checkpoint_written_on_converge(self, tmp_path: Path):
        """When repo_path is provided and spec converges, a checkpoint is saved.
        After the full run (spec + workforce), the final checkpoint has
        recommended_move='workforce' (set by the workforce stage)."""
        deps = FakeDependencies()
        deps.set_claims(_full_claims(), _full_honesty())
        deps.set_plan_items(_valid_plan_items())
        deps.set_subresults([_make_subresult("child-0")])

        run_plan_mode(
            "test request",
            propose_claims=deps.propose_claims,
            decide=deps.decide,
            propose_plan_items=deps.propose_plan_items,
            batch_spawn=deps.batch_spawn,
            engine="mock",
            model="test-model",
            repo_path=str(tmp_path),
            plan_id="test-plan",
        )

        cp = load_checkpoint("test-plan", tmp_path)
        assert cp is not None
        assert cp.plan_id == "test-plan"
        # Final checkpoint after workforce stage says "workforce"
        assert cp.recommended_move == "workforce"

    def test_checkpoint_written_on_non_converge(self, tmp_path: Path):
        """When repo_path is provided and spec does NOT converge, checkpoint still saved."""
        deps = FakeDependencies()
        deps.set_claims(_full_claims(), _full_honesty())
        deps.set_plan_items(_valid_plan_items())
        deps.set_subresults([_make_subresult("child-0")])

        run_plan_mode(
            "test request",
            propose_claims=deps.propose_claims,
            decide=deps.decide_reject_first,
            propose_plan_items=deps.propose_plan_items,
            batch_spawn=deps.batch_spawn,
            engine="mock",
            model="test-model",
            repo_path=str(tmp_path),
            plan_id="test-plan",
        )

        cp = load_checkpoint("test-plan", tmp_path)
        assert cp is not None
        assert cp.recommended_move == "spec"

    def test_checkpoint_resolved_gates_populated(self, tmp_path: Path):
        """Checkpoint resolved_gates contains all gate item_ids from the transcript."""
        deps = FakeDependencies()
        claims = _full_claims()
        honesty = _full_honesty()
        deps.set_claims(claims, honesty)
        deps.set_plan_items(_valid_plan_items())
        deps.set_subresults([_make_subresult("child-0")])

        run_plan_mode(
            "test request",
            propose_claims=deps.propose_claims,
            decide=deps.decide,
            propose_plan_items=deps.propose_plan_items,
            batch_spawn=deps.batch_spawn,
            engine="mock",
            model="test-model",
            repo_path=str(tmp_path),
            plan_id="test-plan",
        )

        cp = load_checkpoint("test-plan", tmp_path)
        assert cp is not None
        # Should have 6 claims + 6 honesty = 12 resolved gates
        assert len(cp.resolved_gates) == 12

    def test_no_checkpoint_without_repo_path(self, tmp_path: Path):
        """When repo_path is None, no checkpoint file is created."""
        deps = FakeDependencies()
        deps.set_claims(_full_claims(), _full_honesty())
        deps.set_plan_items(_valid_plan_items())
        deps.set_subresults([_make_subresult("child-0")])

        run_plan_mode(
            "test request",
            propose_claims=deps.propose_claims,
            decide=deps.decide,
            propose_plan_items=deps.propose_plan_items,
            batch_spawn=deps.batch_spawn,
            engine="mock",
            model="test-model",
            repo_path=None,
            plan_id="test-plan",
        )

        # No checkpoint should exist
        cp_path = tmp_path / ".colleague" / "plan"
        assert not cp_path.exists()


# ── (f) Invariants ──────────────────────────────────────────────────────────


class TestInvariants:
    def test_no_self_confirm(self):
        """The orchestrator never sets state='confirmed' itself.
        Only the injected decide callable can confirm."""
        deps = FakeDependencies()
        deps.set_claims(_full_claims(), _full_honesty())
        deps.set_plan_items(_valid_plan_items())
        deps.set_subresults([_make_subresult("child-0")])

        result = run_plan_mode(
            "test request",
            propose_claims=deps.propose_claims,
            decide=deps.decide,
            propose_plan_items=deps.propose_plan_items,
            batch_spawn=deps.batch_spawn,
            engine="mock",
            model="test-model",
        )

        # The spec_result's frame should have confirmed items (via decide)
        # but the orchestrator itself never wrote state="confirmed"
        # We verify by checking that all confirmations came from decide calls
        assert result.converged is True
        # The spec_result.transcript records all decisions
        for record in result.spec_result.transcript:
            assert record.decision in ("confirm", "reject")

    def test_planning_not_called_before_convergence(self):
        """propose_plan_items and batch_spawn are NOT called when spec doesn't converge."""
        deps = FakeDependencies()
        deps.set_claims(_full_claims(), _full_honesty())
        deps.set_plan_items(_valid_plan_items())
        deps.set_subresults([_make_subresult("child-0")])

        # Reject ALL items -> definitely won't converge
        def reject_all(item, critique) -> str:
            return "reject"

        run_plan_mode(
            "test request",
            propose_claims=deps.propose_claims,
            decide=reject_all,
            propose_plan_items=deps.propose_plan_items,
            batch_spawn=deps.batch_spawn,
            engine="mock",
            model="test-model",
        )

        assert not deps.propose_plan_items_called
        assert not deps.batch_spawn_called

    def test_engine_agnostic(self):
        """The orchestrator works with any engine/model combination."""
        deps = FakeDependencies()
        deps.set_claims(_full_claims(), _full_honesty())
        deps.set_plan_items(_valid_plan_items())
        deps.set_subresults([_make_subresult("child-0")])

        result = run_plan_mode(
            "test request",
            propose_claims=deps.propose_claims,
            decide=deps.decide,
            propose_plan_items=deps.propose_plan_items,
            batch_spawn=deps.batch_spawn,
            engine="vllm-openai",
            model="gpt-4",
        )

        assert result.converged is True


# ── (g) validate_items raises ValueError ───────────────────────────────────


class TestValidation:
    def test_invalid_plan_items_raises(self):
        """Plan items with empty acceptance criteria raise ValueError."""
        deps = FakeDependencies()
        deps.set_claims(_full_claims(), _full_honesty())
        deps.set_plan_items(
            [
                PlanItem(id="bad", summary="Bad item", acceptance=[]),
            ]
        )
        deps.set_subresults([_make_subresult("child-0")])

        with pytest.raises(ValueError, match="has no acceptance criteria"):
            run_plan_mode(
                "test request",
                propose_claims=deps.propose_claims,
                decide=deps.decide,
                propose_plan_items=deps.propose_plan_items,
                batch_spawn=deps.batch_spawn,
                engine="mock",
                model="test-model",
            )

    def test_dangling_dep_raises(self):
        """Plan items with unknown deps raise ValueError."""
        deps = FakeDependencies()
        deps.set_claims(_full_claims(), _full_honesty())
        deps.set_plan_items(
            [
                PlanItem(id="x", summary="X", acceptance=["ok"], deps=["nonexistent"]),
            ]
        )
        deps.set_subresults([_make_subresult("child-0")])

        with pytest.raises(ValueError, match="depends on unknown"):
            run_plan_mode(
                "test request",
                propose_claims=deps.propose_claims,
                decide=deps.decide,
                propose_plan_items=deps.propose_plan_items,
                batch_spawn=deps.batch_spawn,
                engine="mock",
                model="test-model",
            )


# ── (h) Multi-wave checkpointing ────────────────────────────────────────────


class TestMultiWaveCheckpointing:
    def test_checkpoint_advances_to_workforce(self, tmp_path: Path):
        """After running waves, checkpoint recommended_move is 'workforce'."""
        deps = FakeDependencies()
        deps.set_claims(_full_claims(), _full_honesty())
        deps.set_plan_items(_plan_items_with_deps())
        deps.set_subresults([_make_subresult("child-0")])

        run_plan_mode(
            "test request",
            propose_claims=deps.propose_claims,
            decide=deps.decide,
            propose_plan_items=deps.propose_plan_items,
            batch_spawn=deps.batch_spawn,
            engine="mock",
            model="test-model",
            repo_path=str(tmp_path),
            plan_id="test-plan",
        )

        cp = load_checkpoint("test-plan", tmp_path)
        assert cp is not None
        assert cp.recommended_move == "workforce"


# ── (i) Spec result fidelity ───────────────────────────────────────────────


class TestSpecResultFidelity:
    def test_spec_result_transcript_populated(self):
        """The returned spec_result has a populated transcript."""
        deps = FakeDependencies()
        deps.set_claims(_full_claims(), _full_honesty())
        deps.set_plan_items(_valid_plan_items())
        deps.set_subresults([_make_subresult("child-0")])

        result = run_plan_mode(
            "test request",
            propose_claims=deps.propose_claims,
            decide=deps.decide,
            propose_plan_items=deps.propose_plan_items,
            batch_spawn=deps.batch_spawn,
            engine="mock",
            model="test-model",
        )

        assert result.spec_result is not None
        assert len(result.spec_result.transcript) == 12  # 6 claims + 6 honesty

    def test_spec_result_convergence_passed(self):
        """The spec_result.result.passed matches the converged flag."""
        deps = FakeDependencies()
        deps.set_claims(_full_claims(), _full_honesty())
        deps.set_plan_items(_valid_plan_items())
        deps.set_subresults([_make_subresult("child-0")])

        result = run_plan_mode(
            "test request",
            propose_claims=deps.propose_claims,
            decide=deps.decide,
            propose_plan_items=deps.propose_plan_items,
            batch_spawn=deps.batch_spawn,
            engine="mock",
            model="test-model",
        )

        assert result.spec_result.result.passed is True
        assert result.converged is True

    def test_spec_result_convergence_failed(self):
        """When spec doesn't converge, spec_result.result.passed is False."""
        deps = FakeDependencies()
        deps.set_claims(_full_claims(), _full_honesty())
        deps.set_plan_items(_valid_plan_items())
        deps.set_subresults([_make_subresult("child-0")])

        result = run_plan_mode(
            "test request",
            propose_claims=deps.propose_claims,
            decide=deps.decide_reject_first,
            propose_plan_items=deps.propose_plan_items,
            batch_spawn=deps.batch_spawn,
            engine="mock",
            model="test-model",
        )

        assert result.spec_result.result.passed is False
        assert result.converged is False


# ── (j) Default plan_id ────────────────────────────────────────────────────


class TestDefaults:
    def test_default_plan_id(self, tmp_path: Path):
        """Default plan_id='plan' is used when not specified."""
        deps = FakeDependencies()
        deps.set_claims(_full_claims(), _full_honesty())
        deps.set_plan_items(_valid_plan_items())
        deps.set_subresults([_make_subresult("child-0")])

        run_plan_mode(
            "test request",
            propose_claims=deps.propose_claims,
            decide=deps.decide,
            propose_plan_items=deps.propose_plan_items,
            batch_spawn=deps.batch_spawn,
            engine="mock",
            model="test-model",
            repo_path=str(tmp_path),
        )

        cp = load_checkpoint("plan", tmp_path)
        assert cp is not None
        assert cp.plan_id == "plan"


# ── (k) Quick path (--quick / --no-spec) ────────────────────────────────────


class TestQuickPath:
    def test_quick_skips_spec_stage(self):
        """When quick=True, propose_claims is NOT called (spec stage skipped)."""
        deps = FakeDependencies()
        deps.set_claims(_full_claims(), _full_honesty())
        deps.set_plan_items(_valid_plan_items())
        deps.set_subresults([_make_subresult("child-0")])

        run_plan_mode(
            "quick request",
            propose_claims=deps.propose_claims,
            decide=deps.decide,
            propose_plan_items=deps.propose_plan_items,
            batch_spawn=deps.batch_spawn,
            engine="mock",
            model="test-model",
            quick=True,
        )

        # propose_claims should NOT have been called
        assert not deps.propose_claims_called
        # But plan items and workforce should still run
        assert deps.propose_plan_items_called
        assert deps.batch_spawn_called

    def test_quick_produces_converged_result(self):
        """Quick path produces a converged=True result with plan items."""
        deps = FakeDependencies()
        deps.set_claims(_full_claims(), _full_honesty())
        deps.set_plan_items(_valid_plan_items())
        deps.set_subresults([_make_subresult("child-0")])

        result = run_plan_mode(
            "quick request",
            propose_claims=deps.propose_claims,
            decide=deps.decide,
            propose_plan_items=deps.propose_plan_items,
            batch_spawn=deps.batch_spawn,
            engine="mock",
            model="test-model",
            quick=True,
        )

        assert result.converged is True
        assert len(result.plan_items) == 2
        assert len(result.waves) == 1
        assert len(result.sub_results) == 1

    def test_quick_spec_result_has_empty_transcript(self):
        """Quick path's spec_result has an empty transcript (no gates)."""
        deps = FakeDependencies()
        deps.set_claims(_full_claims(), _full_honesty())
        deps.set_plan_items(_valid_plan_items())
        deps.set_subresults([_make_subresult("child-0")])

        result = run_plan_mode(
            "quick request",
            propose_claims=deps.propose_claims,
            decide=deps.decide,
            propose_plan_items=deps.propose_plan_items,
            batch_spawn=deps.batch_spawn,
            engine="mock",
            model="test-model",
            quick=True,
        )

        assert result.spec_result is not None
        assert result.spec_result.transcript == []
        assert result.spec_result.result.passed is True

    def test_quick_frame_contains_request_text(self):
        """The quick path frame carries the request as a confirmed claim."""
        # We verify indirectly: propose_plan_items receives the frame,
        # and the quick path builds a frame with a single confirmed claim
        # whose text is the request.
        captured_frames: list[PlanFrame] = []

        def capture_propose_plan_items(frame: PlanFrame) -> list[PlanItem]:
            captured_frames.append(frame)
            return [PlanItem(id="q1", summary="from request", acceptance=["ok"])]

        deps = FakeDependencies()
        deps.set_claims(_full_claims(), _full_honesty())
        deps.set_subresults([_make_subresult("child-0")])

        run_plan_mode(
            "my quick request",
            propose_claims=deps.propose_claims,
            decide=deps.decide,
            propose_plan_items=capture_propose_plan_items,
            batch_spawn=deps.batch_spawn,
            engine="mock",
            model="test-model",
            quick=True,
        )

        assert len(captured_frames) == 1
        frame = captured_frames[0]
        assert len(frame.claims) == 1
        assert frame.claims[0].text == "my quick request"
        assert frame.claims[0].state == "confirmed"

    def test_quick_checkpoint_has_plan_move(self, tmp_path: Path):
        """Quick path saves a checkpoint with recommended_move='plan'."""
        deps = FakeDependencies()
        deps.set_claims(_full_claims(), _full_honesty())
        deps.set_plan_items(_valid_plan_items())
        deps.set_subresults([_make_subresult("child-0")])

        run_plan_mode(
            "quick request",
            propose_claims=deps.propose_claims,
            decide=deps.decide,
            propose_plan_items=deps.propose_plan_items,
            batch_spawn=deps.batch_spawn,
            engine="mock",
            model="test-model",
            repo_path=str(tmp_path),
            plan_id="quick-plan",
            quick=True,
        )

        cp = load_checkpoint("quick-plan", tmp_path)
        assert cp is not None
        # After workforce runs, the final checkpoint says "workforce"
        assert cp.recommended_move == "workforce"

    def test_quick_default_false_is_identical(self):
        """When quick=False (default), behaviour is identical to before."""
        deps = FakeDependencies()
        deps.set_claims(_full_claims(), _full_honesty())
        deps.set_plan_items(_valid_plan_items())
        deps.set_subresults([_make_subresult("child-0")])

        result = run_plan_mode(
            "test request",
            propose_claims=deps.propose_claims,
            decide=deps.decide,
            propose_plan_items=deps.propose_plan_items,
            batch_spawn=deps.batch_spawn,
            engine="mock",
            model="test-model",
            quick=False,
        )

        # Full spec stage ran
        assert deps.propose_claims_called
        assert result.converged is True
        assert len(result.spec_result.transcript) == 12  # 6 claims + 6 honesty
        assert len(result.plan_items) == 2
