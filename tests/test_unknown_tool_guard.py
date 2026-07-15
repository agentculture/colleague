"""Unknown-tool streak guard (#321): stop a run whose tool-call channel is broken.

A model stuck emitting names the harness doesn't know (a serving-side
``--tool-call-parser`` / template mismatch, #320) used to burn the ENTIRE step
budget on ``error: unknown tool`` round-trips and end with an incompletion
reason that blamed the task (``write-no-changes``). The loop now:

  * feeds the valid-tool list back on every unknown-tool error (self-correction
    help for a merely-confused model);
  * stops the run after ``_UNKNOWN_TOOL_STREAK_CAP`` consecutive unknown-tool
    calls, with an honest ``tool-protocol-broken`` incompletion that points at
    the protocol, not the model's competence;
  * resets the streak whenever a call reaches a real tool, so a model that
    recovers is never cut off.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from colleague.contract import INCOMPLETE, OK, Task
from colleague.incompletion import classify_incompletion
from colleague.loop import CompleteFn, ModelResponse, ToolCall, run
from colleague.tools import ToolError, UnknownToolError


def scripted(responses: list[ModelResponse]) -> CompleteFn:
    """A complete() that returns each canned response in turn (then repeats last)."""
    state = {"i": 0}

    def complete(_messages: list[dict]) -> ModelResponse:
        i = min(state["i"], len(responses) - 1)
        state["i"] += 1
        return responses[i]

    return complete


def _unknown_call(i: int) -> ModelResponse:
    return ModelResponse(tool_calls=[ToolCall(str(i), 'read_file"', {"path": "x"})])


def test_streak_stops_the_run_instead_of_burning_the_budget(tmp_path: Path) -> None:
    responses = [_unknown_call(i) for i in range(1, 21)]
    task = Task.new(str(tmp_path), "make a change")
    result = run(scripted(responses), task, max_steps=20)

    assert result.status == INCOMPLETE
    assert result.stopped_without_finish is True
    # 3 unknown-tool steps, not 20: the cap fired at the next turn boundary.
    assert len(result.steps) == 3
    assert all(not s.ok for s in result.steps)
    assert result.incompletion is not None
    assert result.incompletion.reason == "tool-protocol-broken"
    assert 'read_file"' in result.incompletion.evidence
    assert "3 consecutive" in result.incompletion.evidence
    assert "tool-call parser" in result.incompletion.recommendation
    assert "tool-call channel" in result.summary


def test_streak_cap_is_operator_tunable_via_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """COLLEAGUE_MAX_UNKNOWN_TOOL=1 stops the run after a single unknown-tool step."""
    monkeypatch.setenv("COLLEAGUE_MAX_UNKNOWN_TOOL", "1")
    responses = [_unknown_call(i) for i in range(1, 21)]
    task = Task.new(str(tmp_path), "make a change")
    result = run(scripted(responses), task, max_steps=20)

    assert result.status == INCOMPLETE
    assert result.incompletion is not None
    assert result.incompletion.reason == "tool-protocol-broken"
    assert len(result.steps) == 1


@pytest.mark.parametrize("invalid", ["zero", "0"])
def test_streak_cap_invalid_env_falls_back_to_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, invalid: str
) -> None:
    """A non-int or < 1 COLLEAGUE_MAX_UNKNOWN_TOOL falls back to the default cap of 3."""
    monkeypatch.setenv("COLLEAGUE_MAX_UNKNOWN_TOOL", invalid)
    responses = [_unknown_call(i) for i in range(1, 21)]
    task = Task.new(str(tmp_path), "make a change")
    result = run(scripted(responses), task, max_steps=20)

    assert result.status == INCOMPLETE
    assert result.incompletion is not None
    assert result.incompletion.reason == "tool-protocol-broken"
    assert len(result.steps) == 3


def test_unknown_tool_error_names_the_valid_tools(tmp_path: Path) -> None:
    responses = [
        _unknown_call(1),
        ModelResponse(tool_calls=[ToolCall("2", "finish", {"summary": "Done: nothing to do."})]),
    ]
    task = Task.new(str(tmp_path), "look around")
    result = run(scripted(responses), task, max_steps=5)

    unknown_step = result.steps[0]
    assert not unknown_step.ok
    assert "unknown tool" in unknown_step.result
    assert "valid tools:" in unknown_step.result
    assert "read_file," in unknown_step.result or "read_file" in unknown_step.result


def test_streak_resets_when_a_real_tool_is_reached(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello\n")
    interleaved = []
    call_id = 0
    for _ in range(4):
        call_id += 1
        interleaved.append(_unknown_call(call_id))
        call_id += 1
        interleaved.append(
            ModelResponse(tool_calls=[ToolCall(str(call_id), "read_file", {"path": "a.txt"})])
        )
    interleaved.append(
        ModelResponse(
            tool_calls=[ToolCall("f", "finish", {"summary": "Read a.txt; content is hello."})]
        )
    )
    task = Task.new(str(tmp_path), "read the file")
    result = run(scripted(interleaved), task, max_steps=30)

    # 8 interleaved calls + finish all executed; the guard never fired.
    assert result.status == OK
    assert result.incompletion is None
    assert len(result.steps) == 9


def test_unknown_tool_error_is_a_tool_error() -> None:
    assert issubclass(UnknownToolError, ToolError)


def test_classifier_protocol_reason_wins_over_other_reasons() -> None:
    record = classify_incompletion(
        outcome="tool_protocol",
        write_intent=True,
        changed_files=2,
        summary="a perfectly substantive-looking summary",
        step_count=13,
        protocol_detail="3 consecutive unknown-tool call(s), last 'read_file\"'",
    )
    assert record is not None
    assert record.reason == "tool-protocol-broken"
    assert record.evidence.startswith("3 consecutive")


def test_classifier_protocol_detail_defaults_when_omitted() -> None:
    record = classify_incompletion(
        outcome="tool_protocol",
        write_intent=False,
        changed_files=0,
        summary="",
        step_count=5,
    )
    assert record is not None
    assert record.reason == "tool-protocol-broken"
    assert "5 step(s)" in record.evidence
