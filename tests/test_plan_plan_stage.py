"""Tests for colleague.plan.plan_stage — plan items, validation, and wave computation.

Covers:
  (a) PlanItem round-trips through to_dict / from_dict.
  (b) validate_items flags missing acceptance criteria and dangling deps.
  (c) compute_waves produces deterministic layered waves for acyclic graphs,
      raises ValueError for cycles and dangling deps.
"""

from __future__ import annotations

import pytest

from colleague.plan.plan_stage import (
    PlanItem,
    compute_waves,
    validate_items,
)

# ── helpers ─────────────────────────────────────────────────────────────────


def _items(*summaries: tuple[str, str, list[str], list[str]]) -> list[PlanItem]:
    """Convenience: build PlanItem list from (id, summary, acceptance, deps) tuples."""
    return [PlanItem(id=s[0], summary=s[1], acceptance=s[2], deps=s[3]) for s in summaries]


# ── (a) PlanItem round-trip ─────────────────────────────────────────────────


def test_planitem_roundtrip():
    """A PlanItem round-trips through to_dict / from_dict identically."""
    original = PlanItem(
        id="t1",
        summary="Set up project scaffolding",
        acceptance=["README created", "pyproject.toml configured"],
        deps=[],
    )
    restored = PlanItem.from_dict(original.to_dict())
    assert restored == original


def test_planitem_roundtrip_with_deps():
    """A PlanItem with deps round-trips correctly."""
    original = PlanItem(
        id="t2",
        summary="Implement core module",
        acceptance=["module passes tests"],
        deps=["t1"],
    )
    restored = PlanItem.from_dict(original.to_dict())
    assert restored == original


def test_planitem_empty_acceptance_roundtrip():
    """A PlanItem with empty acceptance round-trips (still valid as a data object)."""
    original = PlanItem(id="t3", summary="No criteria", acceptance=[], deps=[])
    restored = PlanItem.from_dict(original.to_dict())
    assert restored == original


# ── (b) validate_items ──────────────────────────────────────────────────────


def test_validate_items_no_acceptance():
    """validate_items flags an item with empty acceptance criteria."""
    items = _items(("t1", "work", [], []))
    problems = validate_items(items)
    assert any("no acceptance criteria" in p for p in problems)


def test_validate_items_dangling_dep():
    """validate_items flags a dependency referencing an unknown item id."""
    items = _items(("t1", "work", ["ok"], ["nonexistent"]))
    problems = validate_items(items)
    assert any("depends on unknown" in p for p in problems)


def test_validate_items_clean():
    """validate_items returns [] for a fully valid item set."""
    items = _items(
        ("t1", "work1", ["a"], []),
        ("t2", "work2", ["b"], ["t1"]),
    )
    assert validate_items(items) == []


def test_validate_items_multiple_problems():
    """validate_items reports all problems, not just the first."""
    items = _items(
        ("t1", "work1", [], []),  # no acceptance
        ("t2", "work2", ["ok"], ["ghost"]),  # dangling dep
    )
    problems = validate_items(items)
    assert len(problems) == 2


# ── (c) compute_waves ──────────────────────────────────────────────────────


def test_compute_waves_simple_chain():
    """A simple chain t1 -> t2 -> t3 produces three waves."""
    items = _items(
        ("t1", "work1", ["a"], []),
        ("t2", "work2", ["b"], ["t1"]),
        ("t3", "work3", ["c"], ["t2"]),
    )
    waves = compute_waves(items)
    assert waves == [["t1"], ["t2"], ["t3"]]


def test_compute_waves_diamond():
    """A diamond graph: t1; t2,t3 dep t1; t4 dep t2,t3."""
    items = _items(
        ("t1", "work1", ["a"], []),
        ("t2", "work2", ["b"], ["t1"]),
        ("t3", "work3", ["c"], ["t1"]),
        ("t4", "work4", ["d"], ["t2", "t3"]),
    )
    waves = compute_waves(items)
    assert waves == [["t1"], ["t2", "t3"], ["t4"]]


def test_compute_waves_no_deps():
    """Items with no deps all land in wave 0, sorted."""
    items = _items(
        ("b", "workb", ["x"], []),
        ("a", "worka", ["y"], []),
        ("c", "workc", ["z"], []),
    )
    waves = compute_waves(items)
    assert waves == [["a", "b", "c"]]


def test_compute_waves_empty():
    """An empty item list yields an empty wave list."""
    waves = compute_waves([])
    assert waves == []


def test_compute_waves_cycle_raises():
    """A cycle (t1 -> t2 -> t1) raises ValueError."""
    items = _items(
        ("t1", "work1", ["a"], ["t2"]),
        ("t2", "work2", ["b"], ["t1"]),
    )
    with pytest.raises(ValueError):
        compute_waves(items)


def test_compute_waves_dangling_dep_raises():
    """A dangling dependency raises ValueError."""
    items = _items(("t1", "work1", ["a"], ["missing"]))
    with pytest.raises(ValueError):
        compute_waves(items)


def test_compute_waves_determinism():
    """Same input always produces the same output (determinism)."""
    items = _items(
        ("t1", "work1", ["a"], []),
        ("t2", "work2", ["b"], ["t1"]),
        ("t3", "work3", ["c"], ["t1"]),
        ("t4", "work4", ["d"], ["t2", "t3"]),
    )
    waves_a = compute_waves(items)
    waves_b = compute_waves(items)
    assert waves_a == waves_b


def test_compute_waves_unsorted_input_sorted_output():
    """Input order does not affect output; waves are sorted within each layer."""
    items = _items(
        ("c", "workc", ["x"], []),
        ("a", "worka", ["y"], []),
        ("b", "workb", ["z"], ["a", "c"]),
    )
    waves = compute_waves(items)
    assert waves == [["a", "c"], ["b"]]
