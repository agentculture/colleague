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
    "what’s the best approach for the cache",  # smart-quote ’ apostrophe (Sonar S5869 fix)
    "design the new caching layer",
    "PLAN THIS",  # case-insensitivity
    # Edge cases surfaced by an ask-colleague review (all already correct — pinned
    # so a future regex change can't silently regress them):
    "roadmap the migration",  # \\broadmap\\b matches (the review's claimed "typo" is a non-bug)
    "plan the migration",  # matches the primary `plan the` trigger, not just the fallback
    "architect the system",  # \\barchitect\\b matches
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
    # Edge cases surfaced by an ask-colleague review — precision boundaries that must
    # stay WORK (word-boundary anchors mean a substring of a trigger is not a trigger):
    "architecture review",  # \\barchitect\\b must NOT match inside "architecture"
    "breakdown the task",  # one word, no space — \\bbreak\\s+…down\\b must NOT match
    "plan",  # the bare word alone is no planning *request*
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
    first = classify_intent(text)
    second = classify_intent(text)
    assert first == second
