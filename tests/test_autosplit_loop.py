"""Loop-level reactive auto-split (#151, task t3).

These tests drive :func:`colleague.loop.run` with a scripted ``complete`` to prove
the reactive split is sequenced correctly:

* an EXHAUSTED context overflow injects ONE split recommendation (naming the
  per-child budget + child cap + the ``subagents`` tool) — STRICTLY BEFORE the
  ``_escalation.escalate`` seam runs (honesty h1, requirement c16);
* when the model then calls ``subagents``, the existing batch machinery is used
  and its results are folded onto the result (requirement c18, honesty h6/h8);
* a within-budget assignment does NOT get the up-front hint, while an
  over-one-window instruction does;
* the feature is dormant (no recommendation, no extra behavior) when no trigger
  fires — covered here for the armed path; the byte-identical no-op guard lives in
  the cross-cutting test (t4).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from colleague import loop as loop_mod
from colleague.contract import OK, SubResult, Task, Usage
from colleague.loop import ContextControls, ModelResponse, Spawns, ToolCall, run

_OVERFLOW = "This model's maximum context length is 4096 tokens"

# A minimal system prompt that, unlike the loop's default, does NOT mention the
# `subagents` tool — so the tests can detect the injected hint/recommendation by
# checking for "subagents" in the message stream without false positives.
_SYS = "You are a test coding agent."


def _task(tmp_path: Path, instruction: str = "do a large thing") -> Task:
    return Task.new(str(tmp_path), instruction, engine="mock")


def _run(complete, task, **kwargs):
    """run() with the subagents-free system prompt so `subagents` only appears in
    the loop's own injected hint/recommendation messages.

    Translates the convenience kwargs ``context_budget`` / ``count_tokens`` /
    ``autosplit_target`` into the :class:`ContextControls` bundle so the test bodies
    stay readable.
    """
    kwargs.setdefault("system_prompt", _SYS)
    cc = ContextControls(
        budget=kwargs.pop("context_budget", None),
        count_tokens=kwargs.pop("count_tokens", None),
        autosplit_target=kwargs.pop("autosplit_target", None),
    )
    return run(complete, task, context=cc, **kwargs)


@pytest.fixture(autouse=True)
def _no_real_escalation(monkeypatch):
    """Record escalate() calls (and when they happen) without any network/agtag."""
    calls: list[str] = []

    def _fake_escalate(result, stats, repo, *, model=None, run=None):
        calls.append(result.task_id)
        return None

    monkeypatch.setattr(loop_mod._escalation, "escalate", _fake_escalate)
    return calls


def test_exhausted_overflow_injects_recommendation_then_model_finishes(
    tmp_path, _no_real_escalation
):
    """An exhausted overflow offers a split; once the model sees it, it finishes.

    Escalation is NOT called — the split was offered and the work resolved before
    the abort+escalate fallback (h1: recommendation strictly before escalate).
    """
    seen_recommendation: list[bool] = []

    def complete(messages):
        recommended = any("subagents" in (m.get("content") or "") for m in messages)
        if recommended:
            seen_recommendation.append(True)
            return ModelResponse(
                content="splitting done",
                tool_calls=[ToolCall("f", "finish", {"summary": "handled via split"})],
                prompt_tokens=1,
                completion_tokens=1,
            )
        # No recommendation yet → keep overflowing so degradation exhausts.
        raise RuntimeError(_OVERFLOW)

    result = _run(
        complete,
        _task(tmp_path),
        max_steps=8,
        context_budget=1000,
        autosplit_target=1_000_000,
    )

    assert seen_recommendation, "model never saw the injected split recommendation"
    assert result.status == OK
    assert result.summary == "handled via split"
    assert _no_real_escalation == [], "escalation fired even though the split resolved the work"


def test_recommendation_names_budget_cap_and_tool(tmp_path, _no_real_escalation):
    """Injected message names the per-child budget, the child cap, and `subagents` (h2)."""
    captured: list[list[dict]] = []

    def complete(messages):
        if any("subagents" in (m.get("content") or "") for m in messages):
            captured.append([dict(m) for m in messages])
            return ModelResponse(
                content="ok",
                tool_calls=[ToolCall("f", "finish", {"summary": "done"})],
                prompt_tokens=1,
                completion_tokens=1,
            )
        raise RuntimeError(_OVERFLOW)

    _run(
        complete,
        _task(tmp_path),
        max_steps=8,
        context_budget=250_000,
        autosplit_target=1_000_000,
    )

    rec = "\n".join(
        m.get("content") or "" for m in captured[0] if "subagents" in (m.get("content") or "")
    )
    assert "subagents" in rec
    assert "250000" in rec  # the per-child budget
    # child cap = ceil(1_000_000 / 250_000) = 4, clamped to MAX_SUBAGENT_FANOUT-1 = 3
    assert "3" in rec


def test_declined_split_falls_back_to_escalation(tmp_path, _no_real_escalation):
    """If the model ignores the recommendation, the error propagates → escalate fires (fallback).

    The recommendation is offered AT MOST ONCE, so a persistent overflow ends in the
    abort+escalate path — escalation is the fallback, never the first response.
    """
    complete_calls = {"n": 0}

    def complete(messages):
        complete_calls["n"] += 1
        # Always overflow — the model ignores the recommendation entirely.
        raise RuntimeError(_OVERFLOW)

    with pytest.raises(loop_mod.WorkAborted):
        _run(
            complete,
            _task(tmp_path),
            max_steps=4,
            context_budget=1000,
            autosplit_target=1_000_000,
        )

    # Escalation fired exactly once on the aborted path (the fallback).
    assert len(_no_real_escalation) == 1
    # The recommendation bought at least one extra turn beyond the first
    # (first-attempt + overflow retries) before giving up — i.e. it was offered.
    assert complete_calls["n"] >= loop_mod._MAX_OVERFLOW_RETRIES + 2


def test_model_acts_on_split_via_subagents_batch(tmp_path, _no_real_escalation):
    """End-to-end: recommendation → model calls `subagents` → batch results folded (c18/h6)."""
    batch_items: list[list[dict]] = []

    def fake_batch(items):
        batch_items.append(items)
        children = [
            SubResult(
                task_id=f"sub-{i}",
                engine="mock",
                model="m",
                status=OK,
                summary=f"child {i} done",
                changed_files=[],
                usage=Usage(),
            )
            for i, _ in enumerate(items)
        ]
        children.append(
            SubResult(
                task_id="merge-sub-0",
                engine="mock",
                model="m",
                status=OK,
                summary="merged 2 branch(es)",
                changed_files=[],
                usage=Usage(),
            )
        )
        return children

    state = {"phase": 0}

    def complete(messages):
        recommended = any("subagents" in (m.get("content") or "") for m in messages)
        if recommended and state["phase"] == 0:
            state["phase"] = 1
            return ModelResponse(
                content="fanning out",
                tool_calls=[
                    ToolCall(
                        "s",
                        "subagents",
                        {"instructions": [{"instruction": "part A"}, {"instruction": "part B"}]},
                    )
                ],
                prompt_tokens=1,
                completion_tokens=1,
            )
        if state["phase"] == 1:
            return ModelResponse(
                content="done",
                tool_calls=[ToolCall("f", "finish", {"summary": "split + integrated"})],
                prompt_tokens=1,
                completion_tokens=1,
            )
        raise RuntimeError(_OVERFLOW)

    result = _run(
        complete,
        _task(tmp_path),
        max_steps=8,
        context_budget=1000,
        autosplit_target=1_000_000,
        spawns=Spawns(batch=fake_batch),
    )

    assert result.status == OK
    assert result.summary == "split + integrated"
    assert batch_items and len(batch_items[0]) == 2, "subagents batch not invoked with 2 children"
    # The children + merge child are folded onto the result.
    assert len(result.sub_results) == 3
    assert _no_real_escalation == []


def test_recommendation_on_last_budget_slot_still_gives_model_a_turn(tmp_path, _no_real_escalation):
    """Regression (#151 Qodo): an overflow on the FINAL budget slot still lets the model act.

    With ``max_steps=1``, the exhausted overflow injects the recommendation; because
    the loop budgets *successful model turns* (not raw iterations), the injection
    does not consume the only slot — the model gets a turn afterwards and finishes.
    Under the old iteration-counted loop this exited _EXIT_BUDGET with zero turns to
    act, escalating instead.
    """

    def complete(messages):
        if any("subagents" in (m.get("content") or "") for m in messages):
            return ModelResponse(
                content="acted",
                tool_calls=[ToolCall("f", "finish", {"summary": "split on last slot"})],
                prompt_tokens=1,
                completion_tokens=1,
            )
        raise RuntimeError(_OVERFLOW)

    result = _run(
        complete,
        _task(tmp_path),
        max_steps=1,  # the recommendation lands on the only budget slot
        context_budget=1000,
        autosplit_target=1_000_000,
    )

    assert result.status == OK
    assert result.summary == "split on last slot"
    assert _no_real_escalation == [], "escalated despite the model acting on the recommendation"


def test_dormant_when_no_target(tmp_path, _no_real_escalation):
    """With autosplit_target unset, an overflow propagates with no recommendation (dormant)."""
    calls = {"n": 0}

    def complete(messages):
        calls["n"] += 1
        assert not any(
            "subagents" in (m.get("content") or "") for m in messages
        ), "recommendation injected while feature dormant"
        raise RuntimeError(_OVERFLOW)

    with pytest.raises(loop_mod.WorkAborted):
        _run(
            complete,
            _task(tmp_path),
            max_steps=4,
            context_budget=1000,
            # autosplit_target omitted → dormant
        )
    # Pure degradation only (first attempt + the bounded in-loop retries + the
    # final re-attempt) — and crucially NO extra split turn, since the feature is
    # dormant without a target.
    assert calls["n"] == loop_mod._MAX_OVERFLOW_RETRIES + 2


def test_upfront_hint_only_for_over_window_instruction(tmp_path, _no_real_escalation):
    """A within-budget instruction gets NO up-front hint; an over-one-window one does."""
    first_messages: dict[str, list[dict]] = {}

    def make_complete(key):
        def complete(messages):
            first_messages.setdefault(key, [dict(m) for m in messages])
            return ModelResponse(
                content="ok",
                tool_calls=[ToolCall("f", "finish", {"summary": "done"})],
                prompt_tokens=1,
                completion_tokens=1,
            )

        return complete

    # Small instruction, big window → no hint.
    _run(
        make_complete("small"),
        _task(tmp_path, "tiny task"),
        max_steps=2,
        context_budget=1_000_000,
        autosplit_target=1_000_000,
    )
    small_blob = "\n".join(m.get("content") or "" for m in first_messages["small"])
    assert "subagents" not in small_blob

    # Instruction whose char-estimate exceeds the (tiny) one-window budget → hint.
    big_instruction = "x " * 5000  # ~10000 chars → ~2500 tokens (char heuristic)
    _run(
        make_complete("big"),
        _task(tmp_path, big_instruction),
        max_steps=2,
        context_budget=100,
        autosplit_target=1_000_000,
    )
    big_blob = "\n".join(m.get("content") or "" for m in first_messages["big"])
    assert "subagents" in big_blob
