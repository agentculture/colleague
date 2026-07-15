"""Tests for :mod:`colleague.frontdoor` — the deterministic front-door classifier.

Fixture corpus asserts the bright-line invariant: anything repo-touching
routes to CORTEX, senses-direct is only the confidently non-repo complement,
and ambiguous input always defaults to CORTEX.
"""

from __future__ import annotations

import pytest

from colleague.frontdoor import CORTEX, SENSES_DIRECT, classify_frontdoor

# ── Fixture corpus ─────────────────────────────────────────────────────────

SENSES_DIRECT_CASES: tuple[str, ...] = (
    # greetings / social
    "hi",
    "hey there",
    "hello!",
    "yo",
    "thanks",
    "thank you",
    "good morning",
    "good evening",
    "how are you",
    "how's it going",
    "bye",
    "cheers",
    # identity / architecture / capabilities questions
    "what are you",
    "who are you",
    "what model are you",
    "how do you work",
    "what can you do",
    "what do you do",
    "what is cortex",
    "what is senses",
    "explain yourself",
    "tell me about yourself",
    "what are your capabilities",
    # general non-repo conversation / advice
    "what should I work on",
    "what should we do next",
    "explain how neural networks work",
)

CORTEX_CASES: tuple[str, ...] = (
    "fix the bug in loop.py",
    "run the tests",
    "add a --foo flag to session.py",
    "what does frontdoor.py do?",
    "git status",
    "refactor the loop",
    "",
    "   ",
    "what do you think about that",  # genuinely ambiguous -> safe default
)


@pytest.mark.parametrize("text", SENSES_DIRECT_CASES)
def test_senses_direct_cases(text: str) -> None:
    assert classify_frontdoor(text) == SENSES_DIRECT


@pytest.mark.parametrize("text", CORTEX_CASES)
def test_cortex_cases(text: str) -> None:
    assert classify_frontdoor(text) == CORTEX


@pytest.mark.parametrize("text", SENSES_DIRECT_CASES + CORTEX_CASES)
def test_deterministic(text: str) -> None:
    first = classify_frontdoor(text)
    second = classify_frontdoor(text)
    assert first == second
