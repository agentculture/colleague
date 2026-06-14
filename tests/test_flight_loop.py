"""Loop integration of the flight-control plane (the piloting feature).

Drives ``loop.run`` with a scripted fake model. A "pilot" acts BETWEEN turns by
writing the per-flight control file as a side effect of ``complete`` — exactly
how a real pilot writes it via the ``colleague flight`` CLI while the work item
runs. Asserts the live feed grows one record per turn boundary, that a ``stop``
ends cooperatively with a preserved partial, that ``guidance`` is injected into
the next prompt, and that an unwatched run is a strict no-op.
"""

from __future__ import annotations

import json
from pathlib import Path

from colleague import flight
from colleague.contract import OK, Task
from colleague.loop import ModelResponse, ToolCall, run


def _list_dir_turn() -> ModelResponse:
    return ModelResponse(tool_calls=[ToolCall("c", "list_dir", {"path": "."})])


def _finish_turn() -> ModelResponse:
    return ModelResponse(tool_calls=[ToolCall("f", "finish", {"summary": "done"})])


def _read_feed(repo: Path, task_id: str) -> list[dict]:
    fp = flight.feed_path(repo, task_id)
    if not fp.exists():
        return []
    return [json.loads(line) for line in fp.read_text().splitlines() if line.strip()]


# --- acceptance 1: one feed record per turn boundary, readable mid-run -------


def test_feed_gains_one_record_per_turn_boundary(tmp_path: Path) -> None:
    task = Task.new(str(tmp_path), "scan", watch=True)
    counts: list[int] = []

    def complete(_messages: list[dict]) -> ModelResponse:
        # Captured MID-RUN: how many feed records are on disk right now.
        counts.append(len(_read_feed(tmp_path, task.id)))
        # three working turns, then finish
        return _finish_turn() if len(counts) > 3 else _list_dir_turn()

    result = run(complete, task, max_steps=10)

    assert result.status == OK
    # At the start of turn N (0-indexed) exactly N records have been written:
    # one per completed boundary — proving incremental, mid-run-readable growth.
    assert counts == [0, 1, 2, 3]


# --- acceptance 2: cooperative stop preserves a partial ---------------------


def test_pilot_stop_ends_cooperatively_with_partial(tmp_path: Path) -> None:
    task = Task.new(str(tmp_path), "scan", watch=True)

    def complete(_messages: list[dict]) -> ModelResponse:
        # the pilot writes a cooperative stop DURING this turn; it must take effect
        # only at the NEXT boundary, never mid-turn.
        flight.write_stop(tmp_path, task.id)
        return _list_dir_turn()

    result = run(complete, task, max_steps=10)

    assert result.status == "incomplete"  # cooperative stop is incomplete, not an error
    assert result.stopped_without_finish is True  # partial, not authoritative
    assert len(result.steps) == 1  # the in-flight turn completed (not interrupted)
    assert "Stopped by pilot" in result.summary


# --- acceptance 2/3: guidance injected into the NEXT prompt ------------------


def test_guidance_is_injected_into_next_prompt(tmp_path: Path) -> None:
    task = Task.new(str(tmp_path), "scan", watch=True)
    seen: list[list[dict]] = []

    def complete(messages: list[dict]) -> ModelResponse:
        seen.append([dict(m) for m in messages])
        if len(seen) == 1:
            # pilot guidance written DURING turn 0 -> visible at turn 1, not turn 0
            flight.append_guidance(tmp_path, task.id, "pivot to plan B")
            return _list_dir_turn()
        return _finish_turn()

    run(complete, task, max_steps=10)

    def has_guidance(msgs: list[dict]) -> bool:
        return any("[pilot guidance] pivot to plan B" in (m.get("content") or "") for m in msgs)

    assert not has_guidance(seen[0]), "guidance must NOT affect the turn it was written during"
    assert has_guidance(seen[1]), "guidance must appear in the very next prompt"


def test_directive_takes_effect_only_at_next_boundary(tmp_path: Path) -> None:
    # A stop written during turn 0 does not interrupt turn 0 (its step still lands).
    task = Task.new(str(tmp_path), "scan", watch=True)
    turns = {"n": 0}

    def complete(_messages: list[dict]) -> ModelResponse:
        turns["n"] += 1
        if turns["n"] == 1:
            flight.write_stop(tmp_path, task.id)
        return _list_dir_turn()

    result = run(complete, task, max_steps=10)
    assert turns["n"] == 1  # turn 1 ran; the boundary check stopped before turn 2
    assert len(result.steps) == 1  # turn 1's tool call was NOT preempted


# --- acceptance 4: strict no-op when unwatched ------------------------------


def test_unwatched_run_is_a_strict_noop(tmp_path: Path) -> None:
    task = Task.new(str(tmp_path), "scan")  # watch defaults False
    assert task.watch is False

    def complete(_messages: list[dict]) -> ModelResponse:
        return _finish_turn()

    result = run(complete, task, max_steps=10)

    assert result.status == OK
    assert result.stopped_without_finish is False
    # no flight plane materialized
    assert not flight.flight_dir(tmp_path).exists()


def test_flight_files_reaped_on_finish(tmp_path: Path) -> None:
    task = Task.new(str(tmp_path), "scan", watch=True)

    def complete(_messages: list[dict]) -> ModelResponse:
        # the feed file exists DURING the run (armed at start)
        assert flight.feed_path(tmp_path, task.id).exists()
        return _finish_turn()

    run(complete, task, max_steps=10)

    # ...and is reaped on finish (ephemeral; the artifact holds the authoritative result)
    assert not flight.feed_path(tmp_path, task.id).exists()
    assert not flight.control_path(tmp_path, task.id).exists()
