"""#411 t8 — an empty-content ``finish_reason=length`` turn is a recorded truncation.

On the rolled reasoning-heavy cortex the output budget can be consumed by
reasoning before any answer: the wire returns empty content, no tool calls and
``finish_reason="length"``. Before this change the loop treated that as an
ordinary no-tool turn (a finish nudge); now it is accounted exactly, recorded
as ``{"kind": "truncated-turn"}`` and routed through the existing bounded
shrink-and-retry lane. The SSE proof runs over a REAL ``os.pipe``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from colleague import context, loop
from colleague.contract import OK, Task
from colleague.engines.vllm_openai import (
    _apply_stream_frame,
    _iter_sse_frames,
    _parse_response,
    _StreamAccumulator,
)
from colleague.loop import ContextControls, ModelResponse, ToolCall


def _truncated(prompt: int = 100, completion: int = 50) -> ModelResponse:
    return ModelResponse(
        content="",
        tool_calls=[],
        prompt_tokens=prompt,
        completion_tokens=completion,
        reasoning="r" * 40,
        finish_reason="length",
    )


def _finish(prompt: int = 80, completion: int = 10) -> ModelResponse:
    return ModelResponse(
        content="",
        tool_calls=[ToolCall("f", "finish", {"summary": "done"})],
        prompt_tokens=prompt,
        completion_tokens=completion,
        finish_reason="tool_calls",
    )


@pytest.fixture
def task(tmp_path: Path) -> Task:
    repo = tmp_path / "repo"
    repo.mkdir()
    return Task.new(str(repo), "answer briefly")


def test_truncated_turn_is_recorded_accounted_and_retried_with_a_tighter_window(task: Task) -> None:
    seen: list[int] = []
    script = iter([_truncated(), _finish()])

    def complete(messages):
        seen.append(len(messages))
        return next(script)

    result = loop.run(complete, task, max_steps=5, context=ContextControls(budget=5000))
    assert result.status == OK
    truncs = [w for w in result.warnings if w.get("kind") == "truncated-turn"]
    assert len(truncs) == 1
    assert truncs[0]["finish_reason"] == "length"
    assert truncs[0]["reasoning_chars"] == 40
    assert truncs[0]["step_index"] == 0
    # the truncated attempt's tokens are EXACT and never dropped; both turns counted
    assert result.usage.prompt_tokens == 180
    assert result.usage.completion_tokens == 60
    assert result.stats.model_turns == 2
    # the retry went straight back to the model (no finish nudge appended)
    assert len(seen) == 2
    assert seen[1] <= seen[0]
    assert result.stopped_without_finish is False


def test_without_a_budget_the_truncation_is_recorded_then_the_nudge_path_runs(task: Task) -> None:
    seen: list[list] = []
    script = iter([_truncated(), _finish()])

    def complete(messages):
        seen.append(list(messages))
        return next(script)

    result = loop.run(complete, task, max_steps=5)
    assert result.status == OK
    assert [w["kind"] for w in result.warnings] == ["truncated-turn"]
    assert result.usage.prompt_tokens == 180
    assert result.usage.completion_tokens == 60
    # no budget = nothing to shrink: the existing nudge path handled the empty turn
    assert len(seen) == 2
    assert len(seen[1]) > len(seen[0])


def test_streaming_truncation_over_a_real_pipe_is_carried_as_length(task: Task) -> None:
    rfd, wfd = os.pipe()
    frames = [
        {"choices": [{"delta": {"reasoning": "thinking"}, "finish_reason": None}]},
        {
            "choices": [{"delta": {}, "finish_reason": "length"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 7},
        },
    ]
    with os.fdopen(wfd, "wb") as writer:
        for frame in frames:
            writer.write(b"data: " + json.dumps(frame).encode() + b"\n\n")
        writer.write(b": keepalive\n")
        writer.write(b"data: [DONE]\n")
    acc = _StreamAccumulator()
    with os.fdopen(rfd, "rb") as response:
        for frame in _iter_sse_frames(response):
            _apply_stream_frame(frame, acc, lambda _d: None)
    resp = ModelResponse(
        content="".join(acc.content_parts),
        tool_calls=[],
        prompt_tokens=int(acc.usage.get("prompt_tokens", 0)),
        completion_tokens=int(acc.usage.get("completion_tokens", 0)),
        reasoning="".join(acc.reasoning_parts),
        finish_reason=acc.finish_reason,
    )
    assert resp.finish_reason == "length"
    assert resp.content == ""
    assert resp.reasoning == "thinking"
    assert loop._is_truncated_turn(resp)
    # and through the loop the same shape is recorded
    script = iter([resp, _finish()])
    result = loop.run(
        lambda _m: next(script), task, max_steps=4, context=ContextControls(budget=5000)
    )
    assert [w["kind"] for w in result.warnings] == ["truncated-turn"]
    assert result.usage.prompt_tokens == 85  # 5 (truncated) + 80 (finish)


def test_blocking_path_parses_the_same_truncation() -> None:
    resp = _parse_response(
        {
            "choices": [
                {
                    "message": {"role": "assistant", "content": "", "reasoning": "x"},
                    "finish_reason": "length",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 2},
        }
    )
    assert resp.finish_reason == "length"
    assert resp.content == ""
    assert loop._is_truncated_turn(resp)


def test_only_the_empty_tool_less_length_turn_counts_as_truncated() -> None:
    assert not loop._is_truncated_turn(
        ModelResponse(content="partial answer", tool_calls=[], finish_reason="length")
    )
    assert not loop._is_truncated_turn(
        ModelResponse(
            content="", tool_calls=[ToolCall("x", "list_dir", {})], finish_reason="length"
        )
    )
    assert not loop._is_truncated_turn(
        ModelResponse(content="", tool_calls=[], finish_reason="stop")
    )
    assert context.classify_degradable(context.TRUNCATED_TURN_MARKER) == "truncated"
    assert context.classify_degradable("some other error") is None
