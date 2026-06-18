"""Role passthrough in workforce items (t10: typed-subagent roles)."""

from __future__ import annotations

from colleague.plan.plan_stage import PlanItem
from colleague.plan.workforce import build_workforce_items


def _sample_items() -> list[PlanItem]:
    return [
        PlanItem(
            id="t1",
            summary="Implement widget A",
            acceptance=["Handles edge case X", "Passes tests"],
            deps=[],
        ),
        PlanItem(
            id="t2",
            summary="Implement widget B",
            acceptance=["Handles edge case Y"],
            deps=["t1"],
        ),
    ]


def test_build_workforce_items_with_role() -> None:
    items = _sample_items()
    result = build_workforce_items(
        items,
        engine="mock",
        model="test-model",
        role="reviewer",
    )
    assert len(result) == 2
    for entry in result:
        assert entry["role"] == "reviewer"


def test_build_workforce_items_without_role() -> None:
    items = _sample_items()
    result = build_workforce_items(
        items,
        engine="mock",
        model="test-model",
    )
    assert len(result) == 2
    for entry in result:
        assert "role" not in entry


def test_build_workforce_items_role_none_explicit() -> None:
    """role=None is byte-identical to omitting it: no 'role' key in item dicts."""
    items = _sample_items()
    result = build_workforce_items(
        items,
        engine="mock",
        model="test-model",
        role=None,
    )
    assert len(result) == 2
    for entry in result:
        assert "role" not in entry
