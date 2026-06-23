"""Unit tests for :mod:`colleague.session_intent` (intent classifier)."""

from __future__ import annotations

import pytest

from colleague.session_intent import PLAN, WORK, classify_intent

# ── PLAN cases ───────────────────────────────────────────────────────────

PLAN_CASES = [
    "plan this feature end to end",
    "make a plan for the migration",
    "how should I approach the refactor",
    "break this down into tasks",
    "decompose the auth rewrite",
    "plan out the rollout",
    "what's the best way to structure the cache",
    "design the new caching layer",
    "PLAN THIS",  # case-insensitivity
]

# ── WORK cases ───────────────────────────────────────────────────────────

WORK_CASES = [
    "fix the typo in README",
    "add a test for resolve_engine",
    "implement the planner module",  # planner is not a trigger
    "implement the plan from the doc",  # negative guard: implement+plan
    "rename foo to bar",
    "update plan.py docstring",  # negative guard: plan.py
    "refactor the planning module",  # planning != \\bplan\\b
    "work on the plan mode feature",  # negative guard: concrete work *on* plan-mode code
    "",  # empty
    "   ",  # whitespace
]


@pytest.mark.parametrize("text", PLAN_CASES)
def test_plan_cases(text: str) -> None:
    assert classify_intent(text) == PLAN


@pytest.mark.parametrize("text", WORK_CASES)
def test_work_cases(text: str) -> None:
    assert classify_intent(text) == WORK


@pytest.mark.parametrize("text", PLAN_CASES + WORK_CASES)
def test_returns_only_work_or_plan(text: str) -> None:
    """classify_intent must only return WORK or PLAN."""
    assert classify_intent(text) in {WORK, PLAN}


@pytest.mark.parametrize("text", PLAN_CASES + WORK_CASES)
def test_deterministic(text: str) -> None:
    """Same input twice must yield the same output."""
    assert classify_intent(text) == classify_intent(text)
