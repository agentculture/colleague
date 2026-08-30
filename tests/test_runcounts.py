"""Plan t20 (c43/h32): exact harness counters on the artifact — ``WorkStats.counts``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from colleague import readpage, runcounts
from colleague.config import EngineConfig
from colleague.contract import OK, Task, TaskResult, WorkStats
from colleague.engines.mock import MockEngine
from tests._batch_fixture import BATCH_TASK_INSTRUCTION, make_batch_repo

_PRE_ARC_STATS_KEYS = {
    "request",
    "engine",
    "model",
    "started_at",
    "duration_seconds",
    "model_turns",
    "step_count",
    "tool_counts",
    "files_changed",
    "bytes_written",
    "reasoning_chars",
    "reasoning_bytes",
    "answer_chars",
    "answer_bytes",
    "web_calls",  # t9: web-call budget
    "web_failed",
}


def test_keys_are_the_exact_counters() -> None:
    assert runcounts.KEYS == (
        "batches_run",
        "calls_parallelised",
        "results_blanked",
        "outputs_spilled",
        "guard_trips",
        "stream_guard_trips",
        "markup_tool_calls",
    )


def test_bump_and_counts_of() -> None:
    result = TaskResult(task_id="t", status=OK)
    runcounts.bump(result, "batches_run")
    runcounts.bump(result, "calls_parallelised", 3)
    runcounts.bump(result, "calls_parallelised", 0)  # no-op
    assert result.stats.counts == {"batches_run": 1, "calls_parallelised": 3}
    assert runcounts.counts_of(result) == {
        "batches_run": 1,
        "calls_parallelised": 3,
        "results_blanked": 0,
        "outputs_spilled": 0,
        "guard_trips": 0,
        "stream_guard_trips": 0,
        "markup_tool_calls": 0,
    }
    with pytest.raises(KeyError):
        runcounts.bump(result, "not_a_counter")


def test_to_dict_omits_counts_when_all_zero_and_round_trips_when_set() -> None:
    assert set(WorkStats().to_dict().keys()) == _PRE_ARC_STATS_KEYS
    stats = WorkStats(counts={"guard_trips": 1, "results_blanked": 4})
    data = stats.to_dict()
    assert data["counts"] == {"guard_trips": 1, "results_blanked": 4}
    assert WorkStats.from_dict(json.loads(json.dumps(data))).counts == stats.counts
    assert WorkStats.from_dict({}).counts == {}


def test_finalize_derives_blanked_trips_and_spills() -> None:
    result = TaskResult(task_id="t", status=OK)
    result.warnings.extend(
        [
            {"kind": "microcompaction", "blanked": 3, "blanked_total": 3},
            {"kind": "microcompaction", "blanked": 2, "blanked_total": 5},
            {"kind": "loop-guard", "guard": "identical"},
            {"kind": "something-else", "blanked": 99},
        ]
    )

    class _Executor:
        outputs_spilled = 2

    runcounts.finalize(result, _Executor())
    assert runcounts.counts_of(result) == {
        "batches_run": 0,
        "calls_parallelised": 0,
        "results_blanked": 5,
        "outputs_spilled": 2,
        "guard_trips": 1,
        "stream_guard_trips": 0,
        "markup_tool_calls": 0,
    }
    # Idempotent: a second finalize recomputes, never accumulates.
    runcounts.finalize(result, _Executor())
    assert result.stats.counts["results_blanked"] == 5
    # Nothing derived → nothing on the block.
    empty = TaskResult(task_id="e", status=OK)
    runcounts.finalize(empty, None)
    assert empty.stats.counts == {}


def test_finalize_tallies_stream_guard_trips() -> None:
    # A StreamGuardTripped rides the loop's stall path (loop.py:2972) and records
    # a ``step-stall`` warning naming WHICH guard tripped — ``stream-idle`` or
    # ``stream-lifetime``. The plain #400 progress bound names ``step-stall``.
    # #438 guidance 5: the stream-guard trips must become a counter a live-testing
    # row can cite without parsing the warnings array.
    result = TaskResult(task_id="t", status=OK)
    result.warnings.extend(
        [
            {
                "kind": "step-stall",
                "guard": "stream-lifetime",
                "seconds": 900.0,
                "bound_seconds": 900.0,
            },
            {
                "kind": "step-stall",
                "guard": "stream-idle",
                "seconds": 240.0,
                "bound_seconds": 240.0,
            },
            {"kind": "step-stall", "guard": "step-stall", "seconds": 600.0, "bound_seconds": 600.0},
            {"kind": "loop-guard", "guard": "identical"},
        ]
    )
    runcounts.finalize(result, None)
    counts = runcounts.counts_of(result)
    # Two stream-guard trips, readable off the counter — not the warnings array.
    assert counts["stream_guard_trips"] == 2
    # Loop-guard counting is unchanged: the plain step-stall is NOT a loop guard.
    assert counts["guard_trips"] == 1
    # Idempotent: a second finalize recomputes, never accumulates.
    runcounts.finalize(result, None)
    assert runcounts.counts_of(result)["stream_guard_trips"] == 2


def test_finalize_no_stream_guard_trip_leaves_counter_absent() -> None:
    # A run with only the plain #400 step-stall (guard == "step-stall") records no
    # stream-guard trip, so the counter stays off the block (omit-when-zero).
    result = TaskResult(task_id="t", status=OK)
    result.warnings.append(
        {"kind": "step-stall", "guard": "step-stall", "seconds": 600.0, "bound_seconds": 600.0}
    )
    runcounts.finalize(result, None)
    assert "stream_guard_trips" not in result.stats.counts
    assert runcounts.counts_of(result)["stream_guard_trips"] == 0


def test_mock_batch_run_counts_batches_and_parallelised_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COLLEAGUE_TOOL_CONCURRENCY", "10")
    repo = make_batch_repo(tmp_path / "wide")
    result = MockEngine().work(
        Task.new(str(repo), BATCH_TASK_INSTRUCTION, engine="mock"), EngineConfig.resolve()
    )
    assert result.status == OK
    counts = result.to_dict()["stats"]["counts"]
    assert counts == {"batches_run": 1, "calls_parallelised": 3}


def test_sequential_width_keeps_the_mock_stats_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COLLEAGUE_TOOL_CONCURRENCY", "1")
    repo = make_batch_repo(tmp_path / "seq")
    result = MockEngine().work(
        Task.new(str(repo), BATCH_TASK_INSTRUCTION, engine="mock"), EngineConfig.resolve()
    )
    assert result.status == OK
    assert set(result.to_dict()["stats"].keys()) == _PRE_ARC_STATS_KEYS
    # The default mock recipe never touches a mechanism either.
    plain = MockEngine().work(
        Task.new(str(tmp_path / "plain"), "say hi", engine="mock"), EngineConfig.resolve()
    )
    assert set(plain.to_dict()["stats"].keys()) == _PRE_ARC_STATS_KEYS


def test_bound_output_stamps_the_executor_spill_tally(tmp_path: Path) -> None:
    class _Executor:
        pass

    executor = _Executor()
    big = "\n".join(f"line {i} " + "x" * 80 for i in range(3000))
    out = readpage.bound_output(big, "run_command", 68_000, tmp_path, executor)
    assert "tool-output" in out
    assert executor.outputs_spilled == 1
    readpage.bound_output("small", "", 68_000, tmp_path, executor)
    assert executor.outputs_spilled == 1  # no spill → no bump
    # Back-compat: the four-argument call still works and stamps nothing.
    assert readpage.bound_output("small", "", 68_000, tmp_path) == "small"
