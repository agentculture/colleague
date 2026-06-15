"""Plan-stage data model and wave computation for colleague.

A :class:`PlanItem` represents one bounded child work item: a summary,
acceptance criteria, and an explicit dependency list.  The module provides
:func:`validate_items` (sanity checks) and :func:`compute_waves` (deterministic
dependency-wave layering).

Stdlib only: ``dataclasses`` and ``typing``.  No third-party imports, no import of
devague.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ── PlanItem ────────────────────────────────────────────────────────────────


@dataclass
class PlanItem:
    """One plan item: sized for a single bounded child work item.

    Fields
    ------
    id:
        Unique identifier within the plan.
    summary:
        Human-readable one-line description of the work.
    acceptance:
        Acceptance criteria (list of strings).  Empty list is a validation
        problem (flagged by :func:`validate_items`).
    deps:
        List of item ids this item depends on.  Must reference ids present in
        the item set; otherwise :func:`validate_items` flags a dangling dep.
    """

    id: str
    summary: str
    acceptance: list[str]
    deps: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "summary": self.summary,
            "acceptance": self.acceptance,
            "deps": self.deps,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PlanItem":
        return cls(
            id=str(data["id"]),
            summary=str(data["summary"]),
            acceptance=list(data["acceptance"]),
            deps=list(data.get("deps", [])),
        )


# ── Validation ──────────────────────────────────────────────────────────────


def validate_items(items: list[PlanItem]) -> list[str]:
    """Return a list of human-readable problems in *items*.

    Checks
    ------
    * Duplicate item ids are a problem (``"duplicate item id: <id>"``).
    * An item with an empty ``acceptance`` list is a problem
      (``"item <id> has no acceptance criteria"``).
    * A dep referencing an unknown item id is a problem
      (``"item <id> depends on unknown <dep>"``).

    Returns
    -------
    list[str]
        Empty list means the item set is valid.
    """
    ids = {item.id for item in items}
    problems: list[str] = []

    # Detect duplicate ids (deterministic order).
    seen: dict[str, int] = {}
    for item in items:
        if item.id in seen:
            if seen[item.id] == 0:
                problems.append(f"duplicate item id: {item.id}")
                seen[item.id] = 1
        else:
            seen[item.id] = 0

    for item in items:
        if not item.acceptance:
            problems.append(f"item {item.id} has no acceptance criteria")
        for dep in item.deps:
            if dep not in ids:
                problems.append(f"item {item.id} depends on unknown {dep}")

    return problems


# ── Wave computation ────────────────────────────────────────────────────────


def compute_waves(items: list[PlanItem]) -> list[list[str]]:
    """Deterministic dependency-wave layering.

    Wave 0 contains items with no dependencies.  Each subsequent wave contains
    items whose dependencies are all satisfied by earlier waves.  Within a wave,
    ids are sorted for determinism.

    Raises
    ------
    ValueError
        On a cycle (cannot make progress) or a dangling dependency (dep id not
        among items).
    """
    ids = {item.id for item in items}
    item_map = {item.id: item for item in items}

    # Check for dangling deps first.
    for item in items:
        for dep in item.deps:
            if dep not in ids:
                raise ValueError(f"item {item.id} depends on unknown {dep}")

    remaining = set(ids)
    placed: set[str] = set()  # ids already assigned to an earlier wave
    waves: list[list[str]] = []

    while remaining:
        wave = sorted(
            item_id for item_id in remaining if all(dep in placed for dep in item_map[item_id].deps)
        )
        if not wave:
            raise ValueError("cycle detected: cannot make progress")
        waves.append(wave)
        placed.update(wave)
        remaining -= set(wave)

    return waves
