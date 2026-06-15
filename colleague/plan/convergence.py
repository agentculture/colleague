"""Native convergence gate for colleague plan mode.

Mirrors the devague convergence rule without importing devague.  Pure stdlib.

Rule
----
* **Mandatory kinds** — each must be present AND confirmed
  (``state == "confirmed"``): ``announcement``, ``audience``, ``after_state``,
  ``boundary``, ``success_signal``, and *either* ``before_state`` *or*
  ``why_it_matters`` (at least one of the two).

* **Spec-affecting claims** — confirmed claims whose ``kind`` is in
  ``{announcement, audience, after_state, before_state, why_it_matters,
  boundary, success_signal, requirement}``.  Every spec-affecting confirmed
  claim must have at least one *confirmed* honesty condition
  (``HonestyCondition`` with matching ``claim_id`` and ``state == "confirmed"``).

* **Optional steps** — ``PlanFrame.steps`` entries with ``mandatory == False``
  may be skipped; their ids are recorded in the result rather than blocking.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from colleague.plan.frame import PlanFrame

# ── constants ────────────────────────────────────────────────────────────────

# Canonical order for reporting missing mandatory kinds.
MANDATORY_KIND_ORDER = [
    "announcement",
    "audience",
    "after_state",
    "boundary",
    "success_signal",
]

MANDATORY_KINDS = frozenset(MANDATORY_KIND_ORDER)

# The "before_state OR why_it_matters" pair — at least one must be confirmed.
BEFORE_OR_WHY = frozenset(["before_state", "why_it_matters"])

SPEC_AFFECTING_KINDS = frozenset(
    [
        "announcement",
        "audience",
        "after_state",
        "before_state",
        "why_it_matters",
        "boundary",
        "success_signal",
        "requirement",
    ]
)


# ── result type ──────────────────────────────────────────────────────────────


@dataclass
class ConvergenceResult:
    """Outcome of a convergence check on a :class:`PlanFrame`.

    Fields
    ------
    passed:
        ``True`` only when ``missing_kinds`` and ``claims_missing_honesty``
        are both empty.
    missing_kinds:
        Mandatory kinds that are absent or unconfirmed.
    claims_missing_honesty:
        IDs of spec-affecting confirmed claims that lack a confirmed
        honesty condition.
    skipped_optional:
        IDs of optional steps (``mandatory == False``) that were skipped.
    """

    passed: bool
    missing_kinds: list[str] = field(default_factory=list)
    claims_missing_honesty: list[str] = field(default_factory=list)
    skipped_optional: list[str] = field(default_factory=list)


# ── convergence logic ───────────────────────────────────────────────────────


def converge(frame: PlanFrame) -> ConvergenceResult:
    """Evaluate the convergence gate for *frame*.

    Returns a :class:`ConvergenceResult` describing whether the frame is
    converged enough to proceed.
    """

    # ── 1. mandatory kinds ──────────────────────────────────────────────
    confirmed_kinds: set[str] = {c.kind for c in frame.claims if c.state == "confirmed"}

    missing_kinds: list[str] = []
    for kind in MANDATORY_KIND_ORDER:
        if kind not in confirmed_kinds:
            missing_kinds.append(kind)

    # before_state OR why_it_matters
    has_before = "before_state" in confirmed_kinds
    has_why = "why_it_matters" in confirmed_kinds
    if not (has_before or has_why):
        missing_kinds.append("before_state_or_why_it_matters")

    # ── 2. honesty conditions for spec-affecting confirmed claims ──────
    # Build a set of claim_ids that have at least one confirmed honesty condition.
    confirmed_honesty_claim_ids: set[str] = {
        hc.claim_id for hc in frame.honesty_conditions if hc.state == "confirmed"
    }

    claims_missing_honesty: list[str] = []
    for claim in frame.claims:
        if claim.state != "confirmed":
            continue
        if claim.kind not in SPEC_AFFECTING_KINDS:
            continue
        if claim.id not in confirmed_honesty_claim_ids:
            claims_missing_honesty.append(claim.id)

    # ── 3. optional steps ───────────────────────────────────────────────
    skipped_optional: list[str] = [step.id for step in frame.steps if not step.mandatory]

    passed = len(missing_kinds) == 0 and len(claims_missing_honesty) == 0

    return ConvergenceResult(
        passed=passed,
        missing_kinds=missing_kinds,
        claims_missing_honesty=claims_missing_honesty,
        skipped_optional=skipped_optional,
    )
