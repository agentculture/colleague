"""t16 — the always-on loop guards (colleague/loopguards.py), spec c20/h15."""

from __future__ import annotations

from colleague import loopguards
from colleague.contract import Step
from colleague.loop import ToolCall


def _steps(n: int, tool: str = "read_file", args: dict | None = None) -> list[Step]:
    return [Step(i, tool, dict(args or {"path": "a"}), "ok") for i in range(n)]


def test_thresholds_are_qwen_codes_always_on_values() -> None:
    assert loopguards.IDENTICAL_CALL_THRESHOLD == 5
    assert loopguards.MAX_TOOL_CALLS_PER_TURN == 100


def test_four_identical_prior_steps_plus_one_more_trips() -> None:
    trip = loopguards.check(_steps(4), [ToolCall("x", "read_file", {"path": "a"})])
    assert trip is not None
    assert trip["kind"] == "loop-guard"
    assert trip["guard"] == "identical-calls"
    assert trip["tool"] == "read_file"
    assert trip["repeats"] == 5
    assert trip["dropped"] == 1


def test_three_identical_prior_steps_do_not_trip() -> None:
    assert loopguards.check(_steps(3), [ToolCall("x", "read_file", {"path": "a"})]) is None


def test_different_arguments_break_the_run() -> None:
    prior = _steps(4)
    assert loopguards.check(prior, [ToolCall("x", "read_file", {"path": "b"})]) is None
    prior[2] = Step(2, "read_file", {"path": "other"}, "ok")
    assert loopguards.check(prior, [ToolCall("x", "read_file", {"path": "a"})]) is None


def test_argument_order_does_not_matter_for_identity() -> None:
    prior = [Step(i, "grep_search", {"pattern": "x", "path": "."}, "ok") for i in range(4)]
    trip = loopguards.check(prior, [ToolCall("x", "grep_search", {"path": ".", "pattern": "x"})])
    assert trip is not None
    assert trip["guard"] == "identical-calls"


def test_five_identical_calls_inside_one_turn_trip_and_drop_the_whole_turn() -> None:
    calls = [ToolCall(str(i), "list_dir", {"path": "."}) for i in range(5)]
    trip = loopguards.check([], calls)
    assert trip is not None
    assert trip["repeats"] == 5
    assert trip["dropped"] == 5


def test_a_prior_run_of_five_never_retrips_on_a_different_call() -> None:
    # The run already happened (and was allowed at the time); only a call that EXTENDS
    # a run to five trips — history alone never does.
    assert loopguards.check(_steps(9), [ToolCall("x", "finish", {"summary": "s"})]) is None


def test_more_than_one_hundred_calls_in_a_turn_trips_first() -> None:
    calls = [ToolCall(str(i), "read_file", {"path": f"f{i}"}) for i in range(101)]
    trip = loopguards.check([], calls)
    assert trip == {
        "kind": "loop-guard",
        "guard": "calls-per-turn",
        "calls": 101,
        "limit": 100,
        "dropped": 101,
    }
    assert loopguards.check([], calls[:100]) is None


def test_summary_notes_name_the_guard() -> None:
    per_turn = loopguards.check(
        [], [ToolCall(str(i), "read_file", {"path": str(i)}) for i in range(101)]
    )
    identical = loopguards.check(_steps(4), [ToolCall("x", "read_file", {"path": "a"})])
    assert "101 tool calls in one turn (limit 100)" in loopguards.summary_note(per_turn, 0)
    note = loopguards.summary_note(identical, 4)
    assert note.startswith("Stopped after 4 step(s): loop guard tripped")
    assert "5 consecutive identical 'read_file' calls (limit 5)" in note
    assert "pending calls were dropped" in note
