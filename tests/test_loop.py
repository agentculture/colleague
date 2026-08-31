"""Bounded agentic tool-loop: execution, termination, usage, errors (R3, h3)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from colleague.contract import ERROR, INCOMPLETE, NO_RESULT_PRODUCED, OK, Task
from colleague.loop import (
    CompleteFn,
    ContextControls,
    ModelResponse,
    ToolCall,
    WorkAborted,
    _assistant_message,
    run,
)


def scripted(responses: list[ModelResponse]) -> CompleteFn:
    """A complete() that returns each canned response in turn (then repeats last)."""
    state = {"i": 0}

    def complete(_messages: list[dict]) -> ModelResponse:
        i = min(state["i"], len(responses) - 1)
        state["i"] += 1
        return responses[i]

    return complete


def test_loop_writes_file_and_finishes(tmp_path: Path) -> None:
    responses = [
        ModelResponse(
            tool_calls=[ToolCall("1", "write_file", {"path": "out.txt", "content": "hello"})],
            prompt_tokens=10,
            completion_tokens=2,
        ),
        ModelResponse(
            tool_calls=[ToolCall("2", "finish", {"summary": "wrote out.txt"})],
            completion_tokens=1,
        ),
    ]
    task = Task.new(str(tmp_path), "write out.txt")
    result = run(scripted(responses), task, max_steps=10)

    assert result.status == OK
    assert result.changed_files == ["out.txt"]
    assert (tmp_path / "out.txt").read_text() == "hello"
    assert result.summary == "wrote out.txt"
    assert result.usage.total_tokens == 13
    assert len(result.steps) == 2


def test_loop_stops_at_budget_when_never_finishing(tmp_path: Path) -> None:
    def never_finish(_messages: list[dict]) -> ModelResponse:
        return ModelResponse(tool_calls=[ToolCall("x", "list_dir", {"path": "."})])

    task = Task.new(str(tmp_path), "loop forever")
    result = run(never_finish, task, max_steps=3)

    assert result.status == INCOMPLETE
    assert len(result.steps) == 3
    # No content was ever produced, so the summary is the NO_RESULT_PRODUCED
    # sentinel (t2, #109).  Budget exhaustion is preserved in stats.step_count
    # (== max_steps) rather than encoded in the summary string.
    assert result.summary == NO_RESULT_PRODUCED
    assert result.stats.step_count == 3


def test_budget_exhaustion_forces_synthesis(tmp_path: Path) -> None:
    """#191: a budget-exhausted run that read context but never finished gets ONE
    forced no-tools synthesis turn, returned as the summary — not the sentinel.

    Three tool-call turns consume ``max_steps=3``; the loop exits on the budget.
    The forced synthesis turn (which executes no tool) then returns prose, which
    becomes the summary.  Contrast with
    :func:`test_loop_stops_at_budget_when_never_finishing`, where the model keeps
    emitting tool calls (no content) even on the forced turn, so the run correctly
    falls back to ``NO_RESULT_PRODUCED``.
    """
    tool = ModelResponse(tool_calls=[ToolCall("x", "list_dir", {"path": "."})])
    synthesis = ModelResponse(content="SYNTHESIZED: the repo maps to modules A and B.")
    task = Task.new(str(tmp_path), "map the repo")
    result = run(scripted([tool, tool, tool, synthesis]), task, max_steps=3)

    assert result.status == INCOMPLETE
    assert result.not_finished is True
    assert result.summary == "SYNTHESIZED: the repo maps to modules A and B."
    # The forced synthesis executes no tool, so it adds no step (only a model turn).
    assert result.stats.step_count == 3


def test_mapping_fanout_advisory_injected_after_threshold(tmp_path: Path) -> None:
    """#188: once a read-only survey reads MORE than the files-read threshold, the
    loop injects ONE advisory pointing at the ``subagents`` tool — and only once."""
    captured: list[list[str]] = []

    def complete(messages: list[dict]) -> ModelResponse:
        captured.append([str(m.get("content", "")) for m in messages])
        return ModelResponse(tool_calls=[ToolCall("x", "list_dir", {"path": "."})])

    task = Task.new(str(tmp_path), "map the repo")
    run(complete, task, max_steps=6, context=ContextControls(fanout_files=2))

    marker = "partition the unmapped surface"
    # The recommendation is appended to the history once it fires, so the final
    # turn the model saw must contain it EXACTLY once (one-shot) and name subagents.
    final_turn = captured[-1]
    assert sum(1 for c in final_turn if marker in c) == 1
    assert any("subagents" in c for c in final_turn)


def test_mapping_fanout_dormant_is_noop(tmp_path: Path) -> None:
    """#188: with the advisory dormant (``fanout_files`` <= 0) a read-heavy run never
    sees the recommendation — a strict no-op."""
    seen: list[str] = []

    def complete(messages: list[dict]) -> ModelResponse:
        seen.extend(str(m.get("content", "")) for m in messages)
        return ModelResponse(tool_calls=[ToolCall("x", "list_dir", {"path": "."})])

    task = Task.new(str(tmp_path), "map the repo")
    run(complete, task, max_steps=6, context=ContextControls(fanout_files=0))
    assert not any("partition the unmapped surface" in c for c in seen)


def test_loop_terminates_on_empty_tool_calls(tmp_path: Path) -> None:
    task = Task.new(str(tmp_path), "just answer")
    result = run(scripted([ModelResponse(content="nothing to do here")]), task, max_steps=5)
    assert result.summary == "nothing to do here"
    assert result.steps == []


def test_assistant_message_serializes_arguments_as_json_string() -> None:
    # OpenAI wire format: function.arguments must be a JSON *string*, not a dict,
    # or strict servers reject replayed turns.
    resp = ModelResponse(tool_calls=[ToolCall("1", "write_file", {"path": "a", "content": "b"})])
    msg = _assistant_message(resp)
    args = msg["tool_calls"][0]["function"]["arguments"]
    assert isinstance(args, str)
    assert json.loads(args) == {"path": "a", "content": "b"}


def test_assistant_message_passes_string_arguments_through() -> None:
    resp = ModelResponse(tool_calls=[ToolCall("1", "finish", '{"summary": "done"}')])
    args = _assistant_message(resp)["tool_calls"][0]["function"]["arguments"]
    assert args == '{"summary": "done"}'


def test_loop_records_tool_error_and_continues(tmp_path: Path) -> None:
    responses = [
        ModelResponse(tool_calls=[ToolCall("1", "read_file", {"path": "missing.txt"})]),
        ModelResponse(tool_calls=[ToolCall("2", "finish", {"summary": "gave up reading"})]),
    ]
    task = Task.new(str(tmp_path), "read a missing file")
    result = run(scripted(responses), task, max_steps=5)

    assert result.status == OK  # a failed tool call is not a failed drive
    assert result.steps[0].ok is False
    assert "error:" in result.steps[0].result
    assert result.summary == "gave up reading"


def test_loop_preserves_partial_result_when_complete_raises(tmp_path: Path) -> None:
    """An engine that raises mid-loop -> WorkAborted carrying the partial result (#37)."""
    calls = {"n": 0}

    def flaky(_messages: list[dict]) -> ModelResponse:
        calls["n"] += 1
        if calls["n"] == 1:
            return ModelResponse(
                tool_calls=[ToolCall("1", "write_file", {"path": "out.txt", "content": "hi"})],
                prompt_tokens=7,
                completion_tokens=3,
            )
        raise TimeoutError("timed out")

    task = Task.new(str(tmp_path), "write then time out")
    with pytest.raises(WorkAborted) as excinfo:
        run(flaky, task, max_steps=10)

    result = excinfo.value.result
    assert result.status == ERROR
    assert "TimeoutError" in (result.error or "")
    assert isinstance(excinfo.value.__cause__, TimeoutError)
    # Work done up to the failure is preserved, not discarded.
    assert result.changed_files == ["out.txt"]
    assert len(result.steps) == 1
    assert result.usage.total_tokens == 10
    assert (tmp_path / "out.txt").read_text() == "hi"  # the file really landed on disk


def test_loop_emits_progress_per_step(tmp_path: Path) -> None:
    """The progress sink fires once per tool call with (index, tool, target, ok) (#38).

    A pre-completion phase notice (#206) now also fires before each turn — encoded with
    an EMPTY tool name — so the per-step contract is asserted over the step events
    (non-empty tool) only; the phase events are asserted separately below.
    """
    events: list[tuple] = []
    responses = [
        ModelResponse(tool_calls=[ToolCall("1", "write_file", {"path": "a.txt", "content": "x"})]),
        ModelResponse(tool_calls=[ToolCall("2", "read_file", {"path": "missing.txt"})]),  # errors
        ModelResponse(tool_calls=[ToolCall("3", "finish", {"summary": "done"})]),
    ]
    task = Task.new(str(tmp_path), "two steps then finish")
    run(scripted(responses), task, max_steps=10, progress=lambda *a: events.append(a))

    steps = [e for e in events if e[1]]  # step events carry a real (non-empty) tool name
    assert [e[0] for e in steps] == [0, 1, 2]  # step indices, in order
    assert [e[1] for e in steps] == ["write_file", "read_file", "finish"]
    assert steps[0][2] == "a.txt"  # target hint = the path
    assert steps[0][3] is True  # write ok
    assert steps[1][3] is False  # read of a missing file is not ok
    assert steps[2][3] is True  # finish ok


def test_loop_emits_thinking_phase_before_each_turn(tmp_path: Path) -> None:
    """A pre-completion 'thinking' phase notice (#206) fires before every model turn.

    It is encoded as a progress event with an EMPTY tool name (a real tool always has
    a name), so a sink can render it as a phase line, never a step. One fires per turn,
    so on a slow backend a long completion is visibly working, not stalled.
    """
    events: list[tuple] = []
    responses = [
        ModelResponse(tool_calls=[ToolCall("1", "read_file", {"path": "a.txt"})]),
        ModelResponse(tool_calls=[ToolCall("2", "finish", {"summary": "done"})]),
    ]
    (tmp_path / "a.txt").write_text("hi")
    task = Task.new(str(tmp_path), "read then finish")
    run(scripted(responses), task, max_steps=10, progress=lambda *a: events.append(a))

    phases = [e for e in events if not e[1]]  # phase events carry an EMPTY tool name
    assert len(phases) == 2  # one before each of the two model turns
    assert all(e[2] for e in phases)  # each carries a human-readable detail line
    assert all("thinking" in e[2] for e in phases)
    # The phase step index is the LIVE step count (len(result.steps)), not the
    # stats.step_count field that stays 0 until _finalize_stats (#206 review): the
    # first phase fires with 0 steps done, the second after the read_file step.
    assert [e[0] for e in phases] == [0, 1]


def test_loop_emits_synthesizing_phase_before_synthesis_turn(tmp_path: Path) -> None:
    """The forced no-tools synthesis turn (#191) gets its own louder phase notice (#206).

    The synthesis turn is the worst case: a single completion that emits no step line,
    so on a slow backend it is indistinguishable from a hang (the exact friction #206
    reports). It must announce a distinct 'synthesizing' phase, not a generic step.
    """
    events: list[tuple] = []
    marker = "Stop using tools and answer"  # from _SYNTHESIS_PROMPT

    def complete(messages: list[dict]) -> ModelResponse:
        last = messages[-1].get("content", "") if messages else ""
        if marker in last:  # the forced-synthesis prompt arrived
            return ModelResponse(content="VERDICT: done.", tool_calls=[])
        return ModelResponse(
            content="reading", tool_calls=[ToolCall("r", "read_file", {"path": "m.py"})]
        )

    (tmp_path / "m.py").write_text("x = 1\n")
    task = Task.new(str(tmp_path), "review", engine="mock")
    result = run(complete, task, max_steps=2, progress=lambda *a: events.append(a))

    assert "VERDICT" in result.summary  # synthesis produced the answer
    phases = [e[2] for e in events if not e[1]]
    assert any("synthesizing" in detail for detail in phases)  # the loud synthesis notice fired


def test_loop_progress_default_is_noop(tmp_path: Path) -> None:
    """No progress sink -> behavior is byte-identical to before (#38)."""
    responses = [ModelResponse(tool_calls=[ToolCall("1", "finish", {"summary": "ok"})])]
    task = Task.new(str(tmp_path), "finish immediately")
    result = run(scripted(responses), task, max_steps=5)  # no progress=
    assert result.status == OK
    assert result.summary == "ok"


def test_loop_progress_sink_failure_does_not_abort(tmp_path: Path) -> None:
    """A raising progress sink is observability, not control — the drive still completes (Qodo)."""

    def boom(*_args: object) -> None:
        raise RuntimeError("progress sink blew up")

    responses = [
        ModelResponse(tool_calls=[ToolCall("1", "write_file", {"path": "a.txt", "content": "x"})]),
        ModelResponse(tool_calls=[ToolCall("2", "finish", {"summary": "done"})]),
    ]
    task = Task.new(str(tmp_path), "write then finish")
    result = run(scripted(responses), task, max_steps=10, progress=boom)

    assert result.status == OK  # the sink failure was suppressed, not propagated
    assert result.summary == "done"
    assert (tmp_path / "a.txt").read_text() == "x"
