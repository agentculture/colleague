"""Tests for colleague/tae_control.py — pure control-logic for TAE mode."""

from __future__ import annotations

import pytest

from colleague.tae_control import (
    EVALUATOR_BOUNDARIES,
    EvaluatorLossPolicy,
    classify_consequential,
    may_plan_action,
    next_actor,
    route_preserves_thought,
    should_invoke_evaluator,
    supersession_policy,
)
from colleague.thought import PresenceUtterance, Thought

# ---------------------------------------------------------------------------
# 1. EVALUATOR_BOUNDARIES and should_invoke_evaluator
# ---------------------------------------------------------------------------


class TestEvaluatorBoundaries:
    """EVALUATOR_BOUNDARIES is exactly the five names, nothing else."""

    def test_exact_boundary_names(self):
        expected = (
            "initial_plan_commit",
            "consequential_action",
            "declared_infeasible",
            "drift_threshold",
            "episode_completion",
        )
        assert EVALUATOR_BOUNDARIES == expected

    def test_no_extra_boundaries(self):
        assert len(EVALUATOR_BOUNDARIES) == 5

    @pytest.mark.parametrize(
        "boundary",
        [
            "initial_plan_commit",
            "consequential_action",
            "declared_infeasible",
            "drift_threshold",
            "episode_completion",
        ],
    )
    def test_all_boundaries_return_true(self, boundary):
        assert should_invoke_evaluator(boundary) is True

    @pytest.mark.parametrize(
        "boundary",
        [
            "tool_call",
            "read_file",
            "write_file",
            "run_command",
            "edit_file",
            "list_dir",
            "view_media",
            "subagent",
            "subagents",
            "culture",
            "devague",
            "check_test_integrity",
            "run_tests",
            "memory",
            "finish",
            "deepthink",
            "some_random_event",
            "",
            "execute",
            "rethink",
            "replan",
            "block",
        ],
    )
    def test_tool_calls_and_others_return_false(self, boundary):
        assert should_invoke_evaluator(boundary) is False


# ---------------------------------------------------------------------------
# 2. next_actor and route_preserves_thought
# ---------------------------------------------------------------------------


class TestNextActor:
    """next_actor maps routes to seats using the closed vocabulary."""

    def test_execute_maps_to_worker(self):
        assert next_actor("execute") == "worker"

    def test_rethink_maps_to_front(self):
        assert next_actor("rethink") == "front"

    def test_replan_maps_to_worker(self):
        assert next_actor("replan") == "worker"

    def test_block_maps_to_host(self):
        assert next_actor("block") == "host"

    def test_unknown_route_raises_value_error(self):
        with pytest.raises(ValueError, match="unknown route"):
            next_actor("execute_and_run")

    def test_unknown_route_names_closed_set(self):
        with pytest.raises(ValueError, match=r"\[.+\]"):
            next_actor("bogus")

    def test_closed_set_is_exhaustive(self):
        """Every route in the closed set is handled."""
        for route in ("execute", "rethink", "replan", "block"):
            result = next_actor(route)
            assert isinstance(result, str)
            assert len(result) > 0


class TestRoutePreservesThought:
    """route_preserves_thought encodes which routes keep the same thought."""

    def test_replan_preserves_thought(self):
        assert route_preserves_thought("replan") is True

    def test_execute_preserves_thought(self):
        assert route_preserves_thought("execute") is True

    def test_rethink_does_not_preserve_thought(self):
        assert route_preserves_thought("rethink") is False

    def test_block_does_not_preserve_thought(self):
        assert route_preserves_thought("block") is False


# ---------------------------------------------------------------------------
# 3. classify_consequential — HOST owns this
# ---------------------------------------------------------------------------


class TestClassifyConsequential:
    """The worker's flag is evidence only; the host verdict wins."""

    def test_host_verdict_true_wins(self):
        """Even when worker says False, host True makes it consequential."""
        assert classify_consequential(False, True) is True

    def test_host_verdict_false_wins(self):
        """When host says False, it is not consequential regardless of worker."""
        assert classify_consequential(True, False) is False

    def test_both_true(self):
        assert classify_consequential(True, True) is True

    def test_both_false(self):
        assert classify_consequential(False, False) is False

    def test_worker_cannot_override_host(self):
        """A worker claiming consequential=False cannot stop a
        host-classified consequential action from being treated as
        consequential."""
        # The critical case: worker says False, host says True.
        # The result must be True (host wins).
        result = classify_consequential(False, True)
        assert result is True, (
            "Worker claiming consequential=False must NOT stop a "
            "host-classified consequential action"
        )


# ---------------------------------------------------------------------------
# 4. supersession_policy
# ---------------------------------------------------------------------------


class TestSupersessionPolicy:
    """Supersession policy avoids half-applied tool state."""

    def test_action_in_flight_returns_complete_then_re_evaluate(self):
        assert supersession_policy(True) == "complete_then_re_evaluate"

    def test_no_action_in_flight_returns_adopt_immediately(self):
        assert supersession_policy(False) == "adopt_immediately"


# ---------------------------------------------------------------------------
# 5. EvaluatorLossPolicy — bounded-retry-then-block
# ---------------------------------------------------------------------------


class TestEvaluatorLossPolicy:
    """Evaluator loss never yields a proceed/execute outcome."""

    def test_default_max_retries_is_2(self):
        policy = EvaluatorLossPolicy()
        assert policy.max_retries == 2

    def test_retry_before_max(self):
        policy = EvaluatorLossPolicy(max_retries=2)
        assert policy.decide_on_evaluator_loss(0) == "retry"
        assert policy.decide_on_evaluator_loss(1) == "retry"

    def test_block_at_max(self):
        policy = EvaluatorLossPolicy(max_retries=2)
        assert policy.decide_on_evaluator_loss(2) == "block"

    def test_block_beyond_max(self):
        policy = EvaluatorLossPolicy(max_retries=2)
        assert policy.decide_on_evaluator_loss(3) == "block"

    def test_custom_max_retries(self):
        policy = EvaluatorLossPolicy(max_retries=5)
        for i in range(5):
            assert policy.decide_on_evaluator_loss(i) == "retry"
        assert policy.decide_on_evaluator_loss(5) == "block"

    def test_never_yields_proceed_or_execute(self):
        """Assert no input to decide_on_evaluator_loss ever yields a
        proceed/execute outcome."""
        policy = EvaluatorLossPolicy(max_retries=2)
        proceed_outcomes = {"proceed", "execute", "continue", "go_ahead"}
        for attempt in range(10):
            result = policy.decide_on_evaluator_loss(attempt)
            assert (
                result not in proceed_outcomes
            ), f"attempt={attempt} yielded {result!r} which is a proceed/execute outcome"

    def test_only_returns_retry_or_block(self):
        """The only valid outcomes are 'retry' and 'block'."""
        policy = EvaluatorLossPolicy(max_retries=3)
        for attempt in range(10):
            result = policy.decide_on_evaluator_loss(attempt)
            assert result in ("retry", "block"), f"attempt={attempt} yielded unexpected {result!r}"


# ---------------------------------------------------------------------------
# 6. may_plan_action — only a committed Thought authorizes action planning
# ---------------------------------------------------------------------------


class TestMayPlanAction:
    """may_plan_action delegates to grants_action_authority."""

    def test_thought_grants_authority(self):
        thought = Thought(
            thought_id="t1",
            intent="fix the bug",
            why="the tests are red",
        )
        assert may_plan_action(thought) is True

    def test_presence_utterance_does_not_grant_authority(self):
        """A PresenceUtterance yields False even when its text clearly
        implies an objective."""
        utterance = PresenceUtterance(text="I should fix the bug in the auth module right now")
        assert may_plan_action(utterance) is False

    def test_presence_utterance_with_strong_intent(self):
        """Even a presence utterance that strongly implies an objective
        cannot authorize action planning."""
        utterance = PresenceUtterance(text="Execute the plan: rewrite the entire payment module")
        assert may_plan_action(utterance) is False

    def test_none_returns_false(self):
        assert may_plan_action(None) is False

    def test_bare_string_returns_false(self):
        assert may_plan_action("just some text") is False

    def test_dict_returns_false(self):
        assert may_plan_action({"intent": "do something"}) is False

    def test_empty_thought_grants_authority(self):
        """Even a minimal Thought grants authority — the type is what matters."""
        thought = Thought(thought_id="t0", intent="", why="")
        assert may_plan_action(thought) is True
