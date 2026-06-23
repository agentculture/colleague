"""Deterministic keyword intent classifier for ``colleague session``.

Decides whether a free-text goal should be handled by the ``work`` verb (safe
default) or the ``plan`` verb.  Stdlib ``re`` only — keeps
``dependencies = []`` and the zero-deps guard green.

Classification rubric
----------------------
Return **PLAN** when the text carries an *explicit* planning signal
(word-boundary, case-insensitive):

  * "plan this", "plan it", "plan that", "plan the …", "plan out …", "plan mode"
  * "make a plan", "draft a plan", "create a plan", "write a plan",
    "come up with a plan"
  * leading imperative: stripped text starts with "plan " followed by a word
  * "break down", "break this down", "break it down", "break that down"
  * "decompose"
  * "architect", "roadmap"
  * "spec this", "spec it", "spec out"
  * "design a", "design an", "design the", "design this", "design our",
    "design new", "design how"
  * "how should I", "how do I", "how would I", "how can I", "how might I"
    (also we / you)
  * "what's the best way", "what's the best approach"
    (also "what is the best …")

Return **WORK** (negative guards) even if a plan word appears, when the line
is concrete work that merely mentions a plan as an *object*:

  * "implement the plan" / "implement … plan"
  * "plan.py"
  * "planner"
  * lines starting with a concrete-edit verb that then mention plan:
    "fix … plan", "update … plan", "edit … plan", "refactor … plan",
    "rename … plan", "test … plan"

Negative guards are evaluated **first**; if any matches, return WORK immediately.
Everything else returns WORK.
"""

from __future__ import annotations

import re

#: Intent constants returned by :func:`classify_intent`.
WORK = "work"
PLAN = "plan"

# ── PLAN triggers (word-boundary, case-insensitive) ──────────────────────

_PLAN_TRIGGERS: tuple[re.Pattern, ...] = (
    # "plan this/it/that/the/…/mode" and "plan out …"
    re.compile(r"\bplan\s+(this|it|that|the|out|mode)\b", re.I),
    # "make/draft/create/write a plan" / "come up with a plan"
    re.compile(r"\b(make|draft|create|write)\s+a\s+plan\b", re.I),
    re.compile(r"\bcome\s+up\s+with\s+a\s+plan\b", re.I),
    # leading imperative: "plan <word>…"
    re.compile(r"^\s*plan\s+\w", re.I),
    # "break … down"
    re.compile(r"\bbreak\s+(this\s+|it\s+|that\s+|)down\b", re.I),
    # "decompose"
    re.compile(r"\bdecompose\b", re.I),
    # "architect"
    re.compile(r"\barchitect\b", re.I),
    # "roadmap"
    re.compile(r"\broadmap\b", re.I),
    # "spec this/it/out"
    re.compile(r"\bspec\s+(this|it|out)\b", re.I),
    # "design a/an/the/this/our/new/how"
    re.compile(r"\bdesign\s+(a|an|the|this|our|new|how)\b", re.I),
    # "how should/do/would/can/might I/we/you"
    re.compile(r"\bhow\s+(should|do|would|can|might)\s+(I|we|you)\b", re.I),
    # "what's/what is the best way/approach" (straight ' or smart ’ apostrophe;
    # the ’ escape keeps the class ASCII so a quote-normaliser can't silently
    # collapse it back into the duplicate Sonar S5869 flagged)
    re.compile(r"\bwhat['\u2019]s\s+the\s+best\s+(way|approach)\b", re.I),
    re.compile(r"\bwhat\s+is\s+the\s+best\s+(way|approach)\b", re.I),
)

# ── Negative guards (force WORK) ──────────────────────────────────────────

_NEGATIVE_GUARDS: tuple[re.Pattern, ...] = (
    # "implement … plan"
    re.compile(r"\bimplement\b.*\bplan\b", re.I),
    # "plan.py"
    re.compile(r"\bplan\.py\b", re.I),
    # "planner"
    re.compile(r"\bplanner\b", re.I),
    # concrete-edit verb … plan (incl. "work on … plan", e.g. "work on the plan
    # mode feature" — concrete work *on* the plan-mode code, not a request to plan)
    re.compile(r"^\s*(fix|update|edit|refactor|rename|test|work\s+on)\b.*\bplan\b", re.I),
)


def classify_intent(text: str) -> str:
    """Return ``PLAN`` when *text* carries an explicit planning signal; else
    ``WORK``.

    Pure (no I/O, no module state mutated), deterministic, case-insensitive.
    Empty or whitespace-only text returns ``WORK``.
    """
    if not text or not text.strip():
        return WORK

    # Evaluate negative guards first — concrete work mentioning a plan object.
    for guard in _NEGATIVE_GUARDS:
        if guard.search(text):
            return WORK

    # Check plan triggers.
    for trigger in _PLAN_TRIGGERS:
        if trigger.search(text):
            return PLAN

    return WORK
