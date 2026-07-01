"""Tests for colleague.plan.workforce — workforce stage of plan mode.

Uses a FAKE batch_spawn that records calls and returns canned SubResults.
No real subagents are spawned.
"""

from __future__ import annotations

from colleague.contract import ERROR, OK, SubResult, Usage
from colleague.plan.plan_stage import PlanItem
from colleague.plan.workforce import (
    build_workforce_items,
    chunk,
    run_wave,
    surface_conflicts,
)

# ── helpers ────────────────────────────────────────────────────────────────


def _make_items(count: int) -> list[PlanItem]:
    """Produce *count* PlanItems with deterministic ids and acceptance criteria."""
    return [
        PlanItem(
            id=f"item-{i}",
            summary=f"Summary for item {i}",
            acceptance=[f"Acceptance {i}.1", f"Acceptance {i}.2"],
        )
        for i in range(count)
    ]


def _make_subresult(task_id: str, status: str = OK) -> SubResult:
    return SubResult(
        task_id=task_id,
        engine="mock",
        model="test-model",
        status=status,
        summary=f"Result for {task_id}",
        usage=Usage(),
    )


# ── build_workforce_items ──────────────────────────────────────────────────


class TestBuildWorkforceItems:
    def test_empty(self) -> None:
        assert build_workforce_items([], engine="mock", model="m") == []

    def test_single_item_mapping(self) -> None:
        items = [
            PlanItem(
                id="a",
                summary="Do the thing",
                acceptance=["it works", "it is fast"],
            )
        ]
        result = build_workforce_items(items, engine="mock", model="m")
        assert len(result) == 1
        d = result[0]
        assert d["engine"] == "mock"
        assert d["model"] == "m"
        assert "Do the thing" in d["instruction"]

    def test_acceptance_is_structural_not_prose(self) -> None:
        """t16: acceptance criteria are carried structurally, not flattened text.

        The instruction keeps only the task description — the "Acceptance
        criteria:" prose list it used to embed is gone; the criteria live on
        their own ``"acceptance"`` key instead.
        """
        items = [
            PlanItem(
                id="a",
                summary="Do the thing",
                acceptance=["it works", "it is fast"],
            )
        ]
        result = build_workforce_items(items, engine="mock", model="m")
        d = result[0]
        assert "Acceptance criteria:" not in d["instruction"]
        assert "it works" not in d["instruction"]
        assert d["acceptance"] == ["it works", "it is fast"]

    def test_goal_key_carries_the_plan_item_summary(self) -> None:
        items = [
            PlanItem(
                id="a",
                summary="Do the thing",
                acceptance=["it works"],
            )
        ]
        result = build_workforce_items(items, engine="mock", model="m")
        assert result[0]["goal"] == "Do the thing"

    def test_order_preserved(self) -> None:
        items = _make_items(3)
        result = build_workforce_items(items, engine="e", model="m")
        assert len(result) == 3
        for i, d in enumerate(result):
            assert f"Summary for item {i}" in d["instruction"]

    def test_engine_and_model_propagated(self) -> None:
        items = _make_items(1)
        result = build_workforce_items(items, engine="vllm-openai", model="gpt-4")
        assert result[0]["engine"] == "vllm-openai"
        assert result[0]["model"] == "gpt-4"

    def test_single_acceptance_criterion(self) -> None:
        items = [
            PlanItem(
                id="x",
                summary="One-liner",
                acceptance=["only one"],
            )
        ]
        result = build_workforce_items(items, engine="e", model="m")
        assert result[0]["acceptance"] == ["only one"]
        assert "only one" not in result[0]["instruction"]


# ── chunk ──────────────────────────────────────────────────────────────────


class TestChunk:
    def test_empty(self) -> None:
        assert chunk([], 3) == []

    def test_exact_fit(self) -> None:
        assert chunk([1, 2, 3], 3) == [[1, 2, 3]]

    def test_one_remainder(self) -> None:
        assert chunk([1, 2, 3, 4], 3) == [[1, 2, 3], [4]]

    def test_size_one(self) -> None:
        assert chunk([1, 2, 3], 1) == [[1], [2], [3]]

    def test_size_larger_than_list(self) -> None:
        assert chunk([1, 2], 5) == [[1, 2]]


# ── run_wave ──────────────────────────────────────────────────────────────


class TestRunWave:
    def _fake_batch_spawn(self):
        """Return a fake batch_spawn closure that records calls and returns canned results."""
        calls: list[list[dict]] = []

        def batch_spawn(items: list[dict]) -> list[SubResult]:
            calls.append(items)
            # Return one SubResult per child + one merge child (OK status)
            children = [_make_subresult(f"child-{i}") for i in range(len(items))]
            merge = _make_subresult("merge")
            return children + [merge]

        return batch_spawn, calls

    def test_empty_wave(self) -> None:
        batch_spawn, calls = self._fake_batch_spawn()
        results = run_wave([], batch_spawn, engine="e", model="m")
        assert results == []
        assert calls == []

    def test_small_wave_single_batch(self) -> None:
        """Three items fit in one batch (MAX_SUBAGENT_FANOUT - 1 == 3)."""
        items = _make_items(3)
        batch_spawn, calls = self._fake_batch_spawn()
        results = run_wave(items, batch_spawn, engine="e", model="m")
        assert len(calls) == 1
        assert len(calls[0]) == 3
        # 3 children + 1 merge = 4 results
        assert len(results) == 4

    def test_five_items_two_batches(self) -> None:
        """Five items produce two batch_spawn calls: sizes 3 then 2."""
        items = _make_items(5)
        batch_spawn, calls = self._fake_batch_spawn()
        results = run_wave(items, batch_spawn, engine="e", model="m")
        assert len(calls) == 2
        assert len(calls[0]) == 3
        assert len(calls[1]) == 2
        # Each batch returns children + merge: (3+1) + (2+1) = 7
        assert len(results) == 7

    def test_injected_batch_spawn_used(self) -> None:
        """Verify the injected batch_spawn is called with correct items."""
        items = _make_items(2)
        batch_spawn, calls = self._fake_batch_spawn()
        results = run_wave(items, batch_spawn, engine="e", model="m")
        assert len(calls) == 1
        # 2 children + 1 merge = 3 results
        assert len(results) == 3
        # Check that instructions contain the summaries
        for call_items in calls:
            for item in call_items:
                assert "Summary for item" in item["instruction"]
                assert item["engine"] == "e"
                assert item["model"] == "m"

    def test_four_items_two_batches(self) -> None:
        """Four items: batch of 3 then batch of 1."""
        items = _make_items(4)
        batch_spawn, calls = self._fake_batch_spawn()
        results = run_wave(items, batch_spawn, engine="e", model="m")
        assert len(calls) == 2
        assert len(calls[0]) == 3
        assert len(calls[1]) == 1
        # (3+1) + (1+1) = 6 results
        assert len(results) == 6

    def test_wave_round_trips_goal_and_acceptance_per_item(self) -> None:
        """t16 integration: run_wave's batch items carry each PlanItem's goal +
        acceptance structurally — the shape make_batch_spawn's real _spawn_children
        reads to build each child's Task(goal=..., acceptance=...)."""
        items = _make_items(2)
        batch_spawn, calls = self._fake_batch_spawn()
        run_wave(items, batch_spawn, engine="e", model="m")
        assert len(calls) == 1
        for i, item in enumerate(calls[0]):
            assert item["goal"] == f"Summary for item {i}"
            assert item["acceptance"] == [f"Acceptance {i}.1", f"Acceptance {i}.2"]


# ── surface_conflicts ────────────────────────────────────────────────────


class TestSurfaceConflicts:
    def test_no_conflicts(self) -> None:
        results = [
            _make_subresult("a", OK),
            _make_subresult("b", OK),
        ]
        assert surface_conflicts(results) == []

    def test_one_conflict(self) -> None:
        results = [
            _make_subresult("a", OK),
            _make_subresult("merge-1", ERROR),
            _make_subresult("b", OK),
        ]
        conflicts = surface_conflicts(results)
        assert len(conflicts) == 1
        assert conflicts[0].task_id == "merge-1"
        assert conflicts[0].status == ERROR

    def test_multiple_conflicts(self) -> None:
        results = [
            _make_subresult("a", OK),
            _make_subresult("merge-1", ERROR),
            _make_subresult("b", OK),
            _make_subresult("merge-2", ERROR),
        ]
        conflicts = surface_conflicts(results)
        assert len(conflicts) == 2
        assert all(c.status == ERROR for c in conflicts)

    def test_all_conflicts(self) -> None:
        results = [
            _make_subresult("x", ERROR),
            _make_subresult("y", ERROR),
        ]
        conflicts = surface_conflicts(results)
        assert len(conflicts) == 2

    def test_empty(self) -> None:
        assert surface_conflicts([]) == []
