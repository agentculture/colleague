"""Native plan-mode frame data model for colleague.

A :class:`PlanFrame` captures the structured output of a devague-style planning
session: claims, honesty conditions, and steps.  Each dataclass carries
``to_dict`` / ``from_dict`` classmethods so a frame round-trips through JSON
identically — the same pattern used by :mod:`colleague.contract`.

Stdlib only: ``dataclasses`` and ``json``.  No third-party imports, no import of
devague.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ── Claim ────────────────────────────────────────────────────────────────────

@dataclass
class Claim:
    """One claim within a plan frame.

    Fields
    ------
    id:
        Unique identifier within the frame.
    kind:
        Claim category.  One of: announcement, audience, after_state,
        before_state, why_it_matters, boundary, success_signal, requirement,
        assumption, decision, open_question, non_goal.
    text:
        Human-readable claim text.
    state:
        Lifecycle state.  One of: proposed, confirmed, rejected.
        Defaults to ``"proposed"``.
    """

    id: str
    kind: str
    text: str
    state: str = "proposed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "text": self.text,
            "state": self.state,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Claim":
        return cls(
            id=str(data["id"]),
            kind=str(data["kind"]),
            text=str(data["text"]),
            state=str(data.get("state", "proposed")),
        )


# ── HonestyCondition ────────────────────────────────────────────────────────

@dataclass
class HonestyCondition:
    """An honesty condition attached to a claim.

    Fields
    ------
    id:
        Unique identifier within the frame.
    claim_id:
        The ``Claim.id`` this condition attaches to.
    text:
        Human-readable condition text.
    state:
        Lifecycle state.  One of: proposed, confirmed, rejected.
        Defaults to ``"proposed"``.
    """

    id: str
    claim_id: str
    text: str
    state: str = "proposed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "claim_id": self.claim_id,
            "text": self.text,
            "state": self.state,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HonestyCondition":
        return cls(
            id=str(data["id"]),
            claim_id=str(data["claim_id"]),
            text=str(data["text"]),
            state=str(data.get("state", "proposed")),
        )


# ── Step ────────────────────────────────────────────────────────────────────

@dataclass
class Step:
    """One step within a plan frame.

    Fields
    ------
    id:
        Unique identifier within the frame.
    kind:
        Step category (e.g. "setup", "implement", "test").
    mandatory:
        Whether this step is mandatory (True) or optional (False).
    """

    id: str
    kind: str
    mandatory: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "mandatory": self.mandatory,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Step":
        return cls(
            id=str(data["id"]),
            kind=str(data["kind"]),
            mandatory=bool(data["mandatory"]),
        )


# ── PlanFrame ────────────────────────────────────────────────────────────────

@dataclass
class PlanFrame:
    """A plan-mode frame: claims, honesty conditions, and steps.

    This is the native data model for colleague's plan mode.  A frame
    round-trips through JSON identically via :meth:`to_dict` /
    :meth:`from_dict`.
    """

    claims: list[Claim] = field(default_factory=list)
    honesty_conditions: list[HonestyCondition] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "claims": [c.to_dict() for c in self.claims],
            "honesty_conditions": [h.to_dict() for h in self.honesty_conditions],
            "steps": [s.to_dict() for s in self.steps],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PlanFrame":
        return cls(
            claims=[Claim.from_dict(c) for c in data.get("claims", [])],
            honesty_conditions=[
                HonestyCondition.from_dict(h)
                for h in data.get("honesty_conditions", [])
            ],
            steps=[Step.from_dict(s) for s in data.get("steps", [])],
        )
