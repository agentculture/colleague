"""The loop seam for the episode-boundary config lifecycle (plan task t6).

TEST-FIRST for ``colleague/loop.py``'s two config-lifecycle touch points,
threaded from ``ContextControls.config_lifecycle``
(:class:`colleague.configlifecycle.EpisodeConfigLifecycle`):

1. ``_work_loop`` calls ``observe_turn()`` once per completed model turn —
   the loop is a READ-ONLY consumer of the lifecycle's frozen snapshot; it
   never calls ``apply_window`` (only ``colleague.chain.apply_config_window``
   does, and never from inside a running episode).
2. ``run()`` calls ``end_episode()`` exactly once, on EVERY exit path — the
   T1 regression fix (a no-tool episode end must count as a boundary exactly
   like a tool-driven one).

Covers (plan task t6): c8, h8, c26, h22.

``config_lifecycle=None`` (the default — no ``ContextControls`` override, or
an explicit ``ContextControls()``) must stay byte-identical to the pre-t6
loop: see :func:`test_dormant_lifecycle_is_a_strict_noop`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from colleague.configlifecycle import (
    WINDOW_BETWEEN_EPISODES,
    EpisodeConfigLifecycle,
)
from colleague.contract import ERROR, INCOMPLETE, OK, Task
from colleague.lattice import CapabilityCatalog, ChangeUnit, Origin, Target
from colleague.loop import ContextControls, ModelResponse, ToolCall, WorkAborted, run
from tests.test_loop import scripted


def _lifecycle() -> EpisodeConfigLifecycle:
    return EpisodeConfigLifecycle(catalog=CapabilityCatalog(tool_ids=("list_dir", "read_file")))


# ===========================================================================
# Dormant default — byte-identical without a lifecycle
# ===========================================================================


def test_dormant_lifecycle_is_a_strict_noop(tmp_path: Path) -> None:
    task = Task.new(str(tmp_path), "write out.txt")
    responses = [
        ModelResponse(
            tool_calls=[ToolCall("1", "write_file", {"path": "out.txt", "content": "hi"})]
        ),
        ModelResponse(tool_calls=[ToolCall("2", "finish", {"summary": "done"})]),
    ]
    # No context at all, and an explicit ContextControls() with no lifecycle,
    # both must behave identically — neither raises, neither needs the field.
    result_a = run(scripted(list(responses)), task, max_steps=10)
    result_b = run(scripted(list(responses)), task, max_steps=10, context=ContextControls())
    assert result_a.status == result_b.status == OK
    assert result_a.summary == result_b.summary == "done"


# ===========================================================================
# 1. The digest stays pinned constant across every model turn in an episode
# ===========================================================================


def test_digest_pinned_constant_across_multiple_model_turns(tmp_path: Path) -> None:
    lifecycle = _lifecycle()
    before = lifecycle.effective_digest()
    turn = {"n": 0}

    def multi_turn(_messages: list[dict]) -> ModelResponse:
        turn["n"] += 1
        if turn["n"] == 2:
            # A proposal "arrives" mid-episode (e.g. a cortex configurator
            # would call this from outside the loop) — it must be queued,
            # never applied, until the next sanctioned window.
            lifecycle.propose(
                ChangeUnit(
                    target=Target.WORKER_TOOLS,
                    origin=Origin.CORTEX,
                    tool_ids=["read_file"],
                )
            )
        if turn["n"] >= 4:
            return ModelResponse(tool_calls=[ToolCall(str(turn["n"]), "finish", {"summary": "ok"})])
        return ModelResponse(tool_calls=[ToolCall(str(turn["n"]), "list_dir", {"path": "."})])

    task = Task.new(str(tmp_path), "survey the repo")
    result = run(
        multi_turn, task, max_steps=10, context=ContextControls(config_lifecycle=lifecycle)
    )

    assert result.status == OK
    digests = lifecycle.turn_digests()
    assert len(digests) == 4  # one per completed model turn
    assert all(d == before for d in digests), "digest must never move mid-episode"
    # The mid-episode proposal is still queued — untouched by the loop.
    assert lifecycle.pending_count() == 1
    assert lifecycle.effective_digest() == before

    # Only a sanctioned window ever moves it.
    application = lifecycle.apply_window(WINDOW_BETWEEN_EPISODES)
    assert application.digest_after != before
    assert lifecycle.effective_digest() != before


def test_single_turn_episode_still_observes_the_pinned_digest(tmp_path: Path) -> None:
    lifecycle = _lifecycle()
    task = Task.new(str(tmp_path), "just answer")
    result = run(
        scripted([ModelResponse(content="nothing to do here")]),
        task,
        max_steps=5,
        context=ContextControls(config_lifecycle=lifecycle, max_continue_nudges=0),
    )
    assert result.summary == "nothing to do here"
    assert lifecycle.turn_digests() == [lifecycle.effective_digest()]


# ===========================================================================
# 2. end_episode() fires exactly once, on EVERY exit path (the T1 regression)
# ===========================================================================


def test_no_tool_episode_end_increments_the_boundary_counter(tmp_path: Path) -> None:
    """The T1 regression: a no-tool stop (never a `finish` tool call) must still
    count as an episode boundary — the exact bug a tool-step-only rule would miss.
    """
    lifecycle = _lifecycle()
    assert lifecycle.boundary_count == 0

    task = Task.new(str(tmp_path), "just answer, no tools")
    result = run(
        scripted([ModelResponse(content="a prose-only answer")]),
        task,
        max_steps=5,
        # cap=0: the very first no-tool turn stops immediately (no nudge absorbs it).
        context=ContextControls(config_lifecycle=lifecycle, max_continue_nudges=0),
    )

    assert result.stopped_without_finish is True
    assert result.status == INCOMPLETE
    assert lifecycle.boundary_count == 1


def test_finish_tool_episode_end_also_increments_the_boundary_counter(tmp_path: Path) -> None:
    """Parity check: a clean `finish` tool call is ALSO exactly one boundary —
    proving the counter is exit-reason-agnostic, not gated on any one path."""
    lifecycle = _lifecycle()
    task = Task.new(str(tmp_path), "write and finish")
    responses = [
        ModelResponse(
            tool_calls=[ToolCall("1", "write_file", {"path": "out.txt", "content": "hi"})]
        ),
        ModelResponse(tool_calls=[ToolCall("2", "finish", {"summary": "done"})]),
    ]
    result = run(
        scripted(responses), task, max_steps=10, context=ContextControls(config_lifecycle=lifecycle)
    )

    assert result.status == OK
    assert lifecycle.boundary_count == 1


def test_budget_exhausted_episode_end_increments_the_boundary_counter(tmp_path: Path) -> None:
    lifecycle = _lifecycle()

    def never_finish(_messages: list[dict]) -> ModelResponse:
        return ModelResponse(tool_calls=[ToolCall("x", "list_dir", {"path": "."})])

    task = Task.new(str(tmp_path), "loop forever")
    result = run(
        never_finish, task, max_steps=3, context=ContextControls(config_lifecycle=lifecycle)
    )

    assert result.status == INCOMPLETE
    assert lifecycle.boundary_count == 1


def test_aborted_episode_end_still_increments_the_boundary_counter(tmp_path: Path) -> None:
    """Even an engine raise (WorkAborted, #37) is an episode boundary — the
    partial-work-preservation path runs the SAME "every exit path" finalizer
    the clean paths do (mirrors the existing hook/neighbour-cleanup discipline
    this seam was added alongside)."""
    lifecycle = _lifecycle()

    def flaky(_messages: list[dict]) -> ModelResponse:
        raise TimeoutError("timed out")

    task = Task.new(str(tmp_path), "time out immediately")
    context = ContextControls(config_lifecycle=lifecycle)
    with pytest.raises(WorkAborted) as excinfo:
        run(flaky, task, max_steps=10, context=context)

    assert excinfo.value.result.status == ERROR
    assert lifecycle.boundary_count == 1


def test_boundary_counter_accumulates_across_shared_lifecycle_runs(tmp_path: Path) -> None:
    """A chain shares ONE lifecycle instance across dispatched episodes (each a
    separate ``run()`` call) — the counter accumulates, one increment per call,
    never reset until the caller explicitly discards it (``reset()``)."""
    lifecycle = _lifecycle()
    task = Task.new(str(tmp_path), "episode one")

    run(
        scripted([ModelResponse(tool_calls=[ToolCall("1", "finish", {"summary": "e1"})])]),
        task,
        max_steps=5,
        context=ContextControls(config_lifecycle=lifecycle),
    )
    assert lifecycle.boundary_count == 1

    run(
        scripted([ModelResponse(tool_calls=[ToolCall("1", "finish", {"summary": "e2"})])]),
        Task.new(str(tmp_path), "episode two"),
        max_steps=5,
        context=ContextControls(config_lifecycle=lifecycle),
    )
    assert lifecycle.boundary_count == 2
