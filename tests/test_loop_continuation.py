"""Bounded agentic tool-loop: execution, termination, usage, errors (R3, h3)."""

from __future__ import annotations

from pathlib import Path

from colleague.contract import INCOMPLETE, OK, Task
from colleague.loop import CompleteFn, ContextControls, ModelResponse, ToolCall, run


def scripted(responses: list[ModelResponse]) -> CompleteFn:
    """A complete() that returns each canned response in turn (then repeats last)."""
    state = {"i": 0}

    def complete(_messages: list[dict]) -> ModelResponse:
        i = min(state["i"], len(responses) - 1)
        state["i"] += 1
        return responses[i]

    return complete


def test_continue_nudge_cap_resumes_past_first_stall(tmp_path: Path) -> None:
    """With ``max_continue_nudges=2`` a model that stalls twice then finishes resumes
    past the FIRST stall and completes — where the old single-nudge cap stops it after
    the first stall (the t5-class failure: a no-tool-call turn ended the run mid-task).
    """
    turn = {"n": 0}

    def stalls_twice_then_finishes(_messages: list[dict]) -> ModelResponse:
        turn["n"] += 1
        if turn["n"] <= 2:
            return ModelResponse(content="Let me check:")  # a stall — no tool call
        return ModelResponse(
            tool_calls=[ToolCall("1", "finish", {"summary": "done after resuming"})]
        )

    # cap=2: two nudges absorb both stalls, the third turn finishes cleanly.
    result = run(
        stalls_twice_then_finishes,
        Task.new(str(tmp_path), "resume past stall"),
        max_steps=8,
        context=ContextControls(max_continue_nudges=2),
    )
    assert result.status == OK
    assert result.stopped_without_finish is False
    assert result.summary == "done after resuming"

    # Contrast — the SAME model under the old single-nudge cap stops without finishing.
    turn["n"] = 0
    stopped = run(
        stalls_twice_then_finishes,
        Task.new(str(tmp_path), "single nudge stops"),
        max_steps=8,
        context=ContextControls(max_continue_nudges=1),
    )
    assert stopped.stopped_without_finish is True
    assert stopped.status == INCOMPLETE


def test_continue_nudge_cap_bounds_termination(tmp_path: Path) -> None:
    """An always-stalling model stops after exactly the cap's worth of nudges — the
    loop terminates on the cap (not the step budget), so continuation never runs away.
    """
    calls = {"n": 0}

    def always_stalls(_messages: list[dict]) -> ModelResponse:
        calls["n"] += 1
        return ModelResponse(content="thinking...")

    result = run(
        always_stalls,
        Task.new(str(tmp_path), "bounded"),
        max_steps=20,  # generous: the CAP must end it, not the step budget
        context=ContextControls(max_continue_nudges=2),
    )
    assert result.stopped_without_finish is True
    assert result.not_finished is False  # cap stop, not budget exhaustion
    assert calls["n"] == 3  # 2 nudges (turns 1,2) then stop on turn 3


def test_context_rich_stop_synthesizes_instead_of_trailing_prose(tmp_path: Path) -> None:
    """A stop after real tool work no longer returns mid-thought trailing prose as the
    summary (the t5 failure). The stop no longer pre-empts forced synthesis (#191), so
    a clean summary is produced from what was read; the prose is only the floor.
    """
    turn = {"n": 0}

    def reads_then_stalls(_messages: list[dict]) -> ModelResponse:
        turn["n"] += 1
        if turn["n"] == 1:
            return ModelResponse(tool_calls=[ToolCall("1", "list_dir", {"path": "."})])  # real work
        if turn["n"] >= 4:  # the forced-synthesis turn answers from what was read
            return ModelResponse(content="SYNTH: surveyed the repo; modules A and B.")
        return ModelResponse(content="Let me check:")  # a mid-thought stall (no tool call)

    result = run(
        reads_then_stalls,
        Task.new(str(tmp_path), "context-rich stop"),
        max_steps=10,
        context=ContextControls(max_continue_nudges=1),
    )
    assert result.stopped_without_finish is True
    assert result.summary == "SYNTH: surveyed the repo; modules A and B."  # not "Let me check:"


def test_post_compaction_synthesis_preferred_over_stale_compaction(tmp_path: Path) -> None:
    """A run that compacted mid-flight and then kept working does NOT return the
    pre-work compaction self-summary at a stop. Forced synthesis (#191) runs FIRST
    and reflects everything read — including the post-compaction work — so the
    compaction note is only a fallback (fixes the stale-compaction-summary
    regression, Qodo PR #198)."""
    turn = {"n": 0}

    def complete(_messages: list[dict]) -> ModelResponse:
        turn["n"] += 1
        n = turn["n"]
        if n == 1:  # cross the fill line (>= 0.8 * 100) with a working tool call
            return ModelResponse(
                tool_calls=[ToolCall("1", "list_dir", {"path": "."})], prompt_tokens=90
            )
        if n == 2:  # fill line now offered; a no-tool reply declares COMPACT
            return ModelResponse(content="Context is large; compacting.", prompt_tokens=90)
        if n == 3:  # the compaction summary turn (run inside _compact_history)
            return ModelResponse(content="COMPACTED: read modules A and B; no edits yet.")
        if n == 4:  # MORE work AFTER compacting — the compaction note is now stale
            return ModelResponse(tool_calls=[ToolCall("2", "list_dir", {"path": "."})])
        if n in (5, 6):  # then stall to a stop (one nudge, then stop)
            return ModelResponse(content="Let me check:")
        # the forced-synthesis turn answers fresh, reflecting the post-compaction work
        return ModelResponse(content="SYNTH: read A and B, then re-scanned; final survey.")

    result = run(
        complete,
        Task.new(str(tmp_path), "compact then keep working then stop"),
        max_steps=12,
        context=ContextControls(budget=100, fillline_threshold=0.8, max_continue_nudges=1),
    )
    assert result.stopped_without_finish is True
    assert result.capacity_decision is not None and result.capacity_decision.kind == "compact"
    # The FRESH synthesis wins — not the stale "no edits yet" compaction note.
    assert result.summary == "SYNTH: read A and B, then re-scanned; final survey."
    assert "no edits yet" not in result.summary


def test_compaction_summary_is_fallback_when_synthesis_empty(tmp_path: Path) -> None:
    """When a stop's forced-synthesis turn yields nothing, the run's own compaction
    self-summary is used as the FALLBACK clean summary (it still survives to the exit
    — auto-compact-on-finish, t3) rather than the mid-thought trailing prose."""
    turn = {"n": 0}

    def complete(_messages: list[dict]) -> ModelResponse:
        turn["n"] += 1
        n = turn["n"]
        if n == 1:  # cross the fill line with a working tool call
            return ModelResponse(
                tool_calls=[ToolCall("1", "list_dir", {"path": "."})], prompt_tokens=90
            )
        if n == 2:  # fill line offered; declare COMPACT
            return ModelResponse(content="Context is large; compacting.", prompt_tokens=90)
        if n == 3:  # the compaction summary turn
            return ModelResponse(content="COMPACTED: read modules A and B.")
        if n in (4, 5):  # stall to a stop (one nudge, then stop)
            return ModelResponse(content="Let me check:")
        return ModelResponse(content="")  # forced-synthesis yields nothing → fallback

    result = run(
        complete,
        Task.new(str(tmp_path), "compact then stop, empty synthesis"),
        max_steps=10,
        context=ContextControls(budget=100, fillline_threshold=0.8, max_continue_nudges=1),
    )
    assert result.stopped_without_finish is True
    assert result.capacity_decision is not None and result.capacity_decision.kind == "compact"
    # Synthesis produced nothing → fall back to the compaction self-summary,
    # NOT the trailing "Let me check:" prose.
    assert result.summary == "COMPACTED: read modules A and B."
