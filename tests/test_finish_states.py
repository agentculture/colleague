"""Integration tests: colleague.loop.run() actually populates
TaskResult.finish_states on every exit path (plan task t1, covers c4/h4,
decision c30).

tests/test_finishstate.py covers the pure colleague.finishstate classifier in
isolation; this file proves the loop WIRES it correctly — the "main" seat's
finish_reason/outcome tracking, the always-on artifact field, and the
"senses" seat derivation from an already-populated SensesBlock.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from colleague.contract import (
    FINISH_DELIBERATE,
    FINISH_EMPTY,
    FINISH_STOPPED,
    FINISH_TIMEOUT,
    FINISH_TRUNCATED,
    NO_RESULT_PRODUCED,
    OK,
    ContextPacket,
    FinishRecord,
    SensesBlock,
    SensesRecord,
    Task,
    TaskResult,
)
from colleague.loop import ModelResponse, ToolCall, WorkAborted, _senses_finish_record, run


def _scripted(responses: list[ModelResponse]):
    state = {"i": 0}

    def complete(_messages: list[dict]) -> ModelResponse:
        i = min(state["i"], len(responses) - 1)
        state["i"] += 1
        return responses[i]

    return complete


# ---------------------------------------------------------------------------
# The field exists, defaults sanely, and round-trips.
# ---------------------------------------------------------------------------


def test_finish_states_field_exists_with_empty_default() -> None:
    result = TaskResult(task_id="x", status="ok")
    assert result.finish_states == []


def test_finish_states_round_trips_through_from_dict() -> None:
    original = TaskResult(
        task_id="abc",
        status="ok",
        finish_states=[
            FinishRecord(seat="main", finish_reason="stop", state="deliberate", truncated=False),
            FinishRecord(seat="senses", finish_reason="", state="empty", truncated=False),
        ],
    )
    restored = TaskResult.from_dict(original.to_dict())
    assert restored == original


def test_finish_states_key_is_always_serialized_even_when_empty() -> None:
    """Unlike destination/senses/etc., finish_states is NEVER omitted — the
    key is present even for a bare TaskResult that never ran (decision c30)."""
    result = TaskResult(task_id="x", status="ok")
    assert "finish_states" in result.to_dict()
    assert result.to_dict()["finish_states"] == []


# ---------------------------------------------------------------------------
# deliberate: a clean finish, and a no-tool-call answer.
# ---------------------------------------------------------------------------


def test_clean_finish_records_deliberate_main_seat(tmp_path: Path) -> None:
    def finish_immediately(_messages: list[dict]) -> ModelResponse:
        return ModelResponse(
            tool_calls=[ToolCall("1", "finish", {"summary": "done"})], finish_reason="stop"
        )

    task = Task.new(str(tmp_path), "clean finish test")
    result = run(finish_immediately, task, max_steps=5)

    assert result.status == OK
    assert len(result.finish_states) == 1
    main = result.finish_states[0]
    assert main.seat == "main"
    assert main.state == FINISH_DELIBERATE
    assert main.finish_reason == "stop"
    assert main.truncated is False


def test_no_tool_call_answer_records_deliberate_main_seat(tmp_path: Path) -> None:
    def answer_directly(_messages: list[dict]) -> ModelResponse:
        return ModelResponse(content="Here is the answer.")

    task = Task.new(str(tmp_path), "direct answer test")
    result = run(answer_directly, task, max_steps=5)

    assert result.finish_states[0].state == FINISH_DELIBERATE


# ---------------------------------------------------------------------------
# truncated: a wire finish_reason="length", and step-budget exhaustion.
# ---------------------------------------------------------------------------


def test_wire_finish_reason_length_records_truncated_even_on_a_clean_finish(
    tmp_path: Path,
) -> None:
    def finishes_but_wire_says_length(_messages: list[dict]) -> ModelResponse:
        return ModelResponse(
            tool_calls=[ToolCall("1", "finish", {"summary": "done"})], finish_reason="length"
        )

    task = Task.new(str(tmp_path), "clipped finish test")
    result = run(finishes_but_wire_says_length, task, max_steps=5)

    assert result.status == OK  # the finish tool still ran cleanly
    main = result.finish_states[0]
    assert main.state == FINISH_TRUNCATED
    assert main.truncated is True
    assert main.finish_reason == "length"


def test_budget_exhaustion_with_content_records_truncated(tmp_path: Path) -> None:
    def narrating_looper(_messages: list[dict]) -> ModelResponse:
        return ModelResponse(
            content="still working",
            tool_calls=[ToolCall("1", "list_dir", {"path": "."})],
        )

    task = Task.new(str(tmp_path), "narrating budget test")
    result = run(narrating_looper, task, max_steps=2)

    assert result.not_finished is True
    assert result.summary != NO_RESULT_PRODUCED  # a real fallback summary survived
    assert result.finish_states[0].state == FINISH_TRUNCATED


# ---------------------------------------------------------------------------
# empty: NO_RESULT_PRODUCED — must never be reported as deliberate.
# ---------------------------------------------------------------------------


def test_no_content_ever_produced_records_empty(tmp_path: Path) -> None:
    def silent_tool_caller(_messages: list[dict]) -> ModelResponse:
        return ModelResponse(tool_calls=[ToolCall("x", "list_dir", {"path": "."})])

    task = Task.new(str(tmp_path), "no narration drive")
    result = run(silent_tool_caller, task, max_steps=3)

    assert result.summary == NO_RESULT_PRODUCED
    assert result.finish_states[0].state == FINISH_EMPTY
    assert result.finish_states[0].state != FINISH_DELIBERATE


def test_blank_no_tool_call_turns_exhaust_nudges_and_record_empty(tmp_path: Path) -> None:
    def blank(_messages: list[dict]) -> ModelResponse:
        return ModelResponse(content="", tool_calls=[])

    task = Task.new(str(tmp_path), "blank drive")
    result = run(blank, task, max_steps=5)

    assert result.summary == NO_RESULT_PRODUCED
    assert result.finish_states[0].state == FINISH_EMPTY


# ---------------------------------------------------------------------------
# stopped: the tool-protocol-broken guard (#321) — an EXTERNAL stop, distinct
# from the loop's own same-spelled "stopped" exit reason (see test_finishstate.py).
# ---------------------------------------------------------------------------


def test_tool_protocol_break_records_stopped(tmp_path: Path) -> None:
    responses = [
        ModelResponse(tool_calls=[ToolCall(str(i), 'read_file"', {"path": "x"})])
        for i in range(1, 21)
    ]
    task = Task.new(str(tmp_path), "make a change")
    result = run(_scripted(responses), task, max_steps=20)

    assert result.incompletion is not None
    assert result.incompletion.reason == "tool-protocol-broken"
    assert result.finish_states[0].state == FINISH_STOPPED


# ---------------------------------------------------------------------------
# timeout: an aborted run whose exception is timeout-classified.
# ---------------------------------------------------------------------------


def test_timeout_aborted_run_records_timeout_on_the_partial_result(tmp_path: Path) -> None:
    def always_times_out(_messages: list[dict]) -> ModelResponse:
        raise TimeoutError("request timed out after 30s")

    task = Task.new(str(tmp_path), "timeout test")
    with pytest.raises(WorkAborted) as exc_info:
        run(always_times_out, task, max_steps=5)

    result = exc_info.value.result
    assert result.status == "error"
    assert len(result.finish_states) == 1
    assert result.finish_states[0].seat == "main"
    assert result.finish_states[0].state == FINISH_TIMEOUT


def test_non_timeout_abort_records_empty_not_deliberate(tmp_path: Path) -> None:
    call_count = {"n": 0}

    def blows_up(_messages: list[dict]) -> ModelResponse:
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("engine exploded")
        return ModelResponse(tool_calls=[ToolCall("1", "list_dir", {"path": "."})])

    task = Task.new(str(tmp_path), "aborted drive test")
    with pytest.raises(WorkAborted) as exc_info:
        run(blows_up, task, max_steps=10)

    result = exc_info.value.result
    assert result.finish_states[0].state == FINISH_EMPTY
    assert result.finish_states[0].state != FINISH_DELIBERATE


# ---------------------------------------------------------------------------
# The "senses" seat: derived from SensesRecord.degraded, appended only when
# a senses block with at least one record is present.
# ---------------------------------------------------------------------------


def test_senses_finish_record_is_none_when_no_senses_block() -> None:
    assert _senses_finish_record(None) is None


def test_senses_finish_record_is_none_when_no_records() -> None:
    block = SensesBlock(mode="split", packet=None, records=[])
    assert _senses_finish_record(block) is None


def test_senses_finish_record_degraded_maps_to_empty() -> None:
    block = SensesBlock(
        mode="split",
        packet=ContextPacket(original="hi"),
        records=[SensesRecord(point="interpret", degraded=True)],
    )
    record = _senses_finish_record(block)
    assert record is not None
    assert record.seat == "senses"
    assert record.state == FINISH_EMPTY
    assert record.truncated is False


def test_senses_finish_record_clean_maps_to_deliberate() -> None:
    block = SensesBlock(
        mode="split",
        packet=ContextPacket(original="hi"),
        records=[SensesRecord(point="interpret", degraded=False)],
    )
    record = _senses_finish_record(block)
    assert record is not None
    assert record.state == FINISH_DELIBERATE


def test_senses_finish_record_uses_the_last_record_when_several_fired() -> None:
    """Keyed on the LAST invocation (the seat's terminal state), mirroring the
    main seat's own "last turn wins" convention."""
    block = SensesBlock(
        mode="split",
        packet=ContextPacket(original="hi"),
        records=[
            SensesRecord(point="interpret", degraded=True),
            SensesRecord(point="interpret", degraded=False),
        ],
    )
    record = _senses_finish_record(block)
    assert record is not None
    assert record.state == FINISH_DELIBERATE
