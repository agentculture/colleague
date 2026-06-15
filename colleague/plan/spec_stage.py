"""SPEC STAGE for colleague plan mode.

Per-item capture -> interrogate -> review micro-cycle that surfaces ONE
proposed item at a time and blocks on the operator's confirm/reject before
moving to the next.  Pure stdlib only; no devague import.

Designed for testability via dependency injection: the ``decide`` callable
and optional ``complete`` callable are injected by the caller.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from colleague.plan.convergence import ConvergenceResult, converge
from colleague.plan.frame import Claim, HonestyCondition, PlanFrame
from colleague.plan.reviewer import review_item

# ── GateRecord ───────────────────────────────────────────────────────────────


@dataclass
class GateRecord:
    """Record of a single per-item gate decision.

    Fields
    ------
    item_id:
        Unique identifier of the item (claim or honesty condition).
    item_kind:
        ``"claim"`` or ``"honesty"``.
    critique:
        Advisory critique text, or ``None`` when reviewer was disabled.
    decision:
        ``"confirm"`` or ``"reject"``.
    """

    item_id: str
    item_kind: str
    critique: str | None
    decision: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "item_kind": self.item_kind,
            "critique": self.critique,
            "decision": self.decision,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GateRecord":
        return cls(
            item_id=str(data["item_id"]),
            item_kind=str(data["item_kind"]),
            critique=data.get("critique"),
            decision=str(data["decision"]),
        )


# ── SpecStageResult ──────────────────────────────────────────────────────────


@dataclass
class SpecStageResult:
    """Outcome of a spec-stage run.

    Fields
    ------
    transcript:
        Ordered list of :class:`GateRecord` entries, one per proposed item.
    result:
        Final :class:`ConvergenceResult` after all items were processed.
    """

    transcript: list[GateRecord] = field(default_factory=list)
    result: ConvergenceResult | None = None


# ── run_spec_stage ───────────────────────────────────────────────────────────


def run_spec_stage(
    frame: PlanFrame,
    decide: Callable[["Claim | HonestyCondition", str | None], str],
    *,
    complete: Callable[[str, str], str] | None = None,
    reviewer_enabled: bool = False,
) -> SpecStageResult:
    """Run the SPEC STAGE micro-cycle over *frame*.

    Iterates every PROPOSED item in deterministic order: first proposed
    claims (``state == "proposed"``), then proposed honesty conditions
    (``state == "proposed"``), preserving list order within each group.

    For each item, in turn (one at a time):
      a. Optionally obtain an advisory critique via ``review_item``.
      b. Call ``decide(item, critique)`` to get ``"confirm"`` or ``"reject"``.
      c. Update the item's ``state`` accordingly.
      d. Append a :class:`GateRecord` to the transcript.

    After all items are processed, compute ``converge(frame)`` and return
    a :class:`SpecStageResult`.

    Parameters
    ----------
    frame:
        The plan frame to process.
    decide:
        Callable invoked once per proposed item.  Must return ``"confirm"``
        or ``"reject"``.
    complete:
        Injected model callable (``system_prompt, user_prompt -> str``).
        Used only when ``reviewer_enabled=True``.
    reviewer_enabled:
        When ``True``, call ``review_item`` before each ``decide``.
        When ``False``, skip the reviewer entirely (no ``complete`` call).

    Returns
    -------
    SpecStageResult
        The transcript and final convergence result.
    """
    transcript: list[GateRecord] = []

    # Collect proposed items in deterministic order: claims first, then
    # honesty conditions, each preserving original list order.
    proposed_claims: list[Claim] = [c for c in frame.claims if c.state == "proposed"]
    proposed_honesty: list[HonestyCondition] = [
        h for h in frame.honesty_conditions if h.state == "proposed"
    ]

    # Process proposed claims
    for claim in proposed_claims:
        critique = _get_critique(claim.text, complete, reviewer_enabled)
        decision = decide(claim, critique)
        claim.state = "confirmed" if decision == "confirm" else "rejected"
        transcript.append(
            GateRecord(
                item_id=claim.id,
                item_kind="claim",
                critique=critique,
                decision=decision,
            )
        )

    # Process proposed honesty conditions
    for hc in proposed_honesty:
        critique = _get_critique(hc.text, complete, reviewer_enabled)
        decision = decide(hc, critique)
        hc.state = "confirmed" if decision == "confirm" else "rejected"
        transcript.append(
            GateRecord(
                item_id=hc.id,
                item_kind="honesty",
                critique=critique,
                decision=decision,
            )
        )

    final = converge(frame)
    return SpecStageResult(transcript=transcript, result=final)


def _get_critique(
    item_text: str,
    complete: Callable[[str, str], str] | None,
    reviewer_enabled: bool,
) -> str | None:
    """Obtain an advisory critique for *item_text*, or ``None``."""
    if reviewer_enabled and complete is not None:
        critique = review_item(item_text, complete, enabled=True)
        return critique.text if critique else None
    return None
