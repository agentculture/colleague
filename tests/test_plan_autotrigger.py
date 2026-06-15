"""Tests for the plan-mode auto-trigger loop hook (#t8).

Exercises :func:`colleague.loop._maybe_offer_plan_mode` via a duck-typed context
(it only touches ``plan_offer_tokens`` / ``_plan_offered`` / ``task.instruction``
/ ``messages``), so no full work loop is needed.
"""

from __future__ import annotations

from types import SimpleNamespace

from colleague.loop import _maybe_offer_plan_mode

_LONG = "build a sweeping multi-file feature " * 20


def _ctx(threshold, instruction):
    return SimpleNamespace(
        plan_offer_tokens=threshold,
        _plan_offered=[],
        task=SimpleNamespace(instruction=instruction),
        messages=[],
    )


def test_dormant_by_default_is_strict_noop() -> None:
    ctx = _ctx(0, _LONG)
    _maybe_offer_plan_mode(ctx)
    assert ctx.messages == []
    assert ctx._plan_offered == []


def test_armed_but_small_task_does_not_offer() -> None:
    ctx = _ctx(100000, "tiny task")
    _maybe_offer_plan_mode(ctx)
    assert ctx.messages == []


def test_armed_complex_task_offers_once() -> None:
    ctx = _ctx(1, _LONG)
    _maybe_offer_plan_mode(ctx)
    assert len(ctx.messages) == 1
    assert ctx.messages[0]["role"] == "user"
    assert "plan" in ctx.messages[0]["content"].lower()
    # Fires at most once per work item.
    _maybe_offer_plan_mode(ctx)
    assert len(ctx.messages) == 1
