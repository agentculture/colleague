"""Tests for the goal block + acceptance self-check turn (plan t15 / spec R6 / #259).

A task that declares ``goal``/``acceptance`` carries them as a distinct prompt
block, and a CLEAN finish triggers ONE bounded self-check completion whose
per-criterion outcomes land on ``result.acceptance_outcomes`` — advisory only
(``met=False`` never flips status; an incomplete run never grades itself).
A task without them is byte-identical: no block, no extra completion.
"""

from __future__ import annotations

import json

from colleague.contract import OK, Task
from colleague.loop import (
    ModelResponse,
    ToolCall,
    _build_user_message,
    _parse_acceptance_outcomes,
    run,
)


def _finish(summary: str = "done") -> ModelResponse:
    return ModelResponse(tool_calls=[ToolCall("f", "finish", {"summary": summary})])


def _counting_complete(responses: list[ModelResponse]):
    queue = list(responses)
    calls: list[int] = []

    def complete(_messages: list[dict]) -> ModelResponse:
        calls.append(1)
        return queue.pop(0)

    return complete, calls


# ---------------------------------------------------------------------------
# The goal block
# ---------------------------------------------------------------------------


def test_goal_and_acceptance_render_as_distinct_block(tmp_path):
    task = Task.new(
        str(tmp_path),
        "add a parser",
        goal="the config file parses",
        acceptance=["valid YAML parses", "malformed YAML errors cleanly"],
    )
    message = _build_user_message(task)
    assert "Goal:\nthe config file parses" in message
    assert "Acceptance criteria" in message
    assert "- valid YAML parses" in message


def test_no_goal_is_byte_identical_message(tmp_path):
    task = Task.new(str(tmp_path), "add a parser")
    message = _build_user_message(task)
    assert "Goal:" not in message
    assert "Acceptance criteria" not in message


# ---------------------------------------------------------------------------
# The self-check turn
# ---------------------------------------------------------------------------


def test_clean_finish_with_criteria_records_outcomes(tmp_path):
    checks = [
        {"criterion": "c1 paraphrased", "met": True, "evidence": "wrote the file"},
        {"criterion": "c2", "met": False, "evidence": "not attempted"},
    ]
    complete, calls = _counting_complete([_finish(), ModelResponse(content=json.dumps(checks))])
    task = Task.new(str(tmp_path), "do x", acceptance=["file exists", "tests added"])
    result = run(complete, task, max_steps=5)
    assert result.status == OK
    assert len(calls) == 2  # the work turn + exactly one self-check turn
    assert result.acceptance_outcomes == [
        {"criterion": "file exists", "met": True, "evidence": "wrote the file"},
        {"criterion": "tests added", "met": False, "evidence": "not attempted"},
    ]


def test_unmet_criteria_never_flip_status(tmp_path):
    checks = [{"criterion": "x", "met": False, "evidence": "nope"}]
    complete, _ = _counting_complete([_finish("did it"), ModelResponse(content=json.dumps(checks))])
    task = Task.new(str(tmp_path), "do x", acceptance=["x"])
    result = run(complete, task, max_steps=5)
    assert result.status == OK
    assert result.summary == "did it"  # terminal summary untouched


def test_without_criteria_no_extra_completion(tmp_path):
    complete, calls = _counting_complete([_finish()])
    task = Task.new(str(tmp_path), "do x")
    result = run(complete, task, max_steps=5)
    assert result.status == OK
    assert len(calls) == 1  # no self-check turn — byte-identical
    assert result.acceptance_outcomes is None


def test_incomplete_run_never_grades_itself(tmp_path):
    read = ModelResponse(tool_calls=[ToolCall("r", "list_dir", {"path": "."})])
    complete, calls = _counting_complete([read] * 10)
    task = Task.new(str(tmp_path), "do x", acceptance=["x"])
    result = run(complete, task, max_steps=2)
    assert result.acceptance_outcomes is None
    # Bounded: reading turns + possibly a forced-synthesis turn, never a
    # self-check (which would IndexError past the scripted queue anyway).


def test_malformed_selfcheck_json_records_nothing(tmp_path):
    complete, _ = _counting_complete(
        [_finish(), ModelResponse(content="I think it all works great!")]
    )
    task = Task.new(str(tmp_path), "do x", acceptance=["x"])
    result = run(complete, task, max_steps=5)
    assert result.status == OK
    assert result.acceptance_outcomes is None


# ---------------------------------------------------------------------------
# _parse_acceptance_outcomes
# ---------------------------------------------------------------------------


def test_parse_matches_by_position_with_authoritative_text():
    text = 'noise before [{"criterion": "made up", "met": true, "evidence": "e"}] after'
    outcomes = _parse_acceptance_outcomes(text, ["real criterion", "second"])
    assert outcomes == [
        {"criterion": "real criterion", "met": True, "evidence": "e"},
        {"criterion": "second", "met": False, "evidence": ""},
    ]


def test_parse_garbage_is_empty():
    assert _parse_acceptance_outcomes("no json here", ["c"]) == []
    assert _parse_acceptance_outcomes('{"not": "a list"}', ["c"]) == []
