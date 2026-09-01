"""#479 t9 (c38/h30): the resolved sampling profile lands on the run artifact.

Mirrors ``tests/test_effort_recording.py`` in shape and presence discipline:
a seat that resolves a sampling profile gets a recorded entry (row AND wire,
each labeled), a seat that resolves nothing (unmatched model / never-resolved
rung / kill-switch) is simply absent — never an invented/empty placeholder.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from colleague import artifact, samplingrecord
from colleague.contract import OK, Task, TaskResult
from colleague.contract_records import SubResult
from colleague.effort import DEFAULT_SENTINEL
from colleague.loop import ContextControls, ModelResponse, ToolCall, run
from colleague.tools import ToolExecutor


def _finish(summary: str = "done") -> ModelResponse:
    return ModelResponse(tool_calls=[ToolCall("f", "finish", {"summary": summary})])


def _scripted(responses):
    state = {"i": 0}

    def complete(messages):
        i = min(state["i"], len(responses) - 1)
        state["i"] += 1
        return responses[i]

    return complete


def _sampling_entries(result: TaskResult, seat: str | None = None) -> list[dict]:
    entries = list(result.sampling or [])
    if seat is not None:
        entries = [w for w in entries if w.get("seat") == seat]
    return entries


# ---------------------------------------------------------------------------
# 1. a matched model+rung records BOTH the row and the wire, labeled apart
# ---------------------------------------------------------------------------


def test_main_seat_records_row_and_wire_for_a_matched_model(tmp_path: Path) -> None:
    executor = ToolExecutor(str(tmp_path))
    complete = _scripted([_finish()])
    task = Task.new(str(tmp_path), "do work")
    result = run(
        complete,
        task,
        max_steps=5,
        executor=executor,
        model="unsloth/Qwen3.8-27B-NVFP4",
        context=ContextControls(reasoning_effort_main="low"),
    )

    entries = _sampling_entries(result, "main")
    assert len(entries) == 1
    entry = entries[0]
    assert entry["half"] == "thinking"
    # The ROW is every card key the thinking half sets, min_p/presence_penalty/
    # repetition_penalty included even though they equal the server default.
    assert entry["row"] == {
        "temperature": 1.0,
        "top_p": 0.95,
        "top_k": 20,
        "min_p": 0.0,
        "presence_penalty": 0.0,
        "repetition_penalty": 1.0,
    }
    # The WIRE drops exactly the keys that equal the server default — the
    # worked example from the task brief.
    assert entry["wire"] == {"temperature": 1.0, "top_p": 0.95, "top_k": 20}


def test_off_rung_records_the_non_thinking_row_where_wire_equals_row(tmp_path: Path) -> None:
    """The non-thinking card sets no key that happens to equal a server
    default, so row and wire coincide here — a useful contrast case."""
    executor = ToolExecutor(str(tmp_path))
    complete = _scripted([_finish()])
    task = Task.new(str(tmp_path), "do work")
    result = run(
        complete,
        task,
        max_steps=5,
        executor=executor,
        model="Qwen/Qwen3.8-27B",
        context=ContextControls(reasoning_effort_main="off"),
    )

    entry = _sampling_entries(result, "main")[0]
    assert entry["half"] == "non_thinking"
    assert (
        entry["row"]
        == entry["wire"]
        == {
            "temperature": 0.7,
            "top_p": 0.80,
            "top_k": 20,
            "presence_penalty": 1.5,
        }
    )


# ---------------------------------------------------------------------------
# 2. the presence rule: no match = no entry at all (never a placeholder)
# ---------------------------------------------------------------------------


def test_unmatched_model_records_nothing(tmp_path: Path) -> None:
    executor = ToolExecutor(str(tmp_path))
    complete = _scripted([_finish()])
    task = Task.new(str(tmp_path), "do work")
    result = run(
        complete,
        task,
        max_steps=5,
        executor=executor,
        model="Qwen/Qwen3.8-4B",  # no card for the 4B checkpoint
        context=ContextControls(reasoning_effort_main="low"),
    )
    assert _sampling_entries(result) == []
    assert not any(True for _ in result.to_dict().get("sampling", []))


def test_never_resolved_rung_records_nothing(tmp_path: Path) -> None:
    executor = ToolExecutor(str(tmp_path))
    complete = _scripted([_finish()])
    task = Task.new(str(tmp_path), "do work")
    result = run(
        complete,
        task,
        max_steps=5,
        executor=executor,
        model="Qwen/Qwen3.8-27B",
        context=ContextControls(reasoning_effort_main=None),
    )
    assert _sampling_entries(result) == []


def test_kill_switch_records_nothing(tmp_path: Path) -> None:
    executor = ToolExecutor(str(tmp_path))
    complete = _scripted([_finish()])
    task = Task.new(str(tmp_path), "do work")
    result = run(
        complete,
        task,
        max_steps=5,
        executor=executor,
        model="Qwen/Qwen3.8-27B",
        context=ContextControls(reasoning_effort_main=DEFAULT_SENTINEL),
    )
    assert _sampling_entries(result) == []


# ---------------------------------------------------------------------------
# 3. a delegated child is recorded under its role name, read off SubResult
# ---------------------------------------------------------------------------


def test_delegated_child_is_recorded_under_its_role_name() -> None:
    task = Task.new("/tmp/repo-does-not-need-to-exist", "t")
    result = TaskResult(task_id=task.id, status=OK)
    ctx = SimpleNamespace(
        result=result,
        model="Qwen/Qwen3.8-27B",
        reasoning_effort_main=None,  # main never resolved — proves independence
        executor=SimpleNamespace(
            sub_results=[
                SubResult(
                    task_id="c1",
                    engine="mock",
                    model="Qwen/Qwen3.8-27B",
                    status=OK,
                    role="scout",
                    reasoning_effort="low",
                )
            ]
        ),
    )
    samplingrecord.fold_run_seats(ctx)

    assert _sampling_entries(result, "main") == []
    child_entries = _sampling_entries(result, "scout")
    assert len(child_entries) == 1
    assert child_entries[0]["wire"] == {"temperature": 1.0, "top_p": 0.95, "top_k": 20}


def test_unmatched_child_model_leaves_only_the_matching_child_recorded() -> None:
    task = Task.new("/tmp/repo-does-not-need-to-exist", "t")
    result = TaskResult(task_id=task.id, status=OK)
    ctx = SimpleNamespace(
        result=result,
        model="Qwen/Qwen3.8-27B",
        reasoning_effort_main="low",
        executor=SimpleNamespace(
            sub_results=[
                SubResult(
                    task_id="c1",
                    engine="mock",
                    model="Qwen/Qwen3.8-4B",  # no card
                    status=OK,
                    role="scout",
                    reasoning_effort="low",
                )
            ]
        ),
    )
    samplingrecord.fold_run_seats(ctx)

    assert _sampling_entries(result, "scout") == []
    assert len(_sampling_entries(result, "main")) == 1


# ---------------------------------------------------------------------------
# 4. round-trips onto the written artifact
# ---------------------------------------------------------------------------


def test_recorded_sampling_survives_the_artifact_round_trip(tmp_path: Path) -> None:
    executor = ToolExecutor(str(tmp_path))
    complete = _scripted([_finish()])
    task = Task.new(str(tmp_path), "do work")
    result = run(
        complete,
        task,
        max_steps=5,
        executor=executor,
        model="unsloth/Qwen3.8-27B-NVFP4",
        context=ContextControls(reasoning_effort_main="low"),
    )
    path = artifact.write(result, tmp_path / "artifacts")
    data = json.loads(path.read_text())
    on_disk = list(data["sampling"])
    assert on_disk == _sampling_entries(result)

    restored = TaskResult.from_dict(data)
    assert _sampling_entries(restored) == _sampling_entries(result)


# ---------------------------------------------------------------------------
# 5. re-recording one seat replaces (never duplicates) its prior entry
# ---------------------------------------------------------------------------


def test_rerecording_a_seat_replaces_rather_than_duplicates() -> None:
    task = Task.new("/tmp/repo-does-not-need-to-exist", "t")
    result = TaskResult(task_id=task.id, status=OK)
    samplingrecord.record(result, "main", "Qwen/Qwen3.8-27B", None, "off")
    samplingrecord.record(result, "main", "Qwen/Qwen3.8-27B", None, "low")
    entries = _sampling_entries(result, "main")
    assert len(entries) == 1
    assert entries[0]["half"] == "thinking"  # the SECOND record won


def test_the_kill_switch_records_nothing_rather_than_a_profile_never_sent(monkeypatch) -> None:
    """COLLEAGUE_SAMPLING=0 sends no sampling keys, so the artifact records none.

    Qodo #485 finding 6, reproduced before it was fixed: the record recomputed
    against the builtin table without consulting the kill switch, so a run that
    sent ``temperature 0.0`` and nothing else carried a record claiming the full
    thinking row. Absence is the honest record.
    """
    model = "unsloth/Qwen3.8-27B-NVFP4"
    result = TaskResult(task_id="k1", status="ok", summary="s")

    monkeypatch.setenv("COLLEAGUE_SAMPLING", "0")
    samplingrecord.record(result, "main", model, None, "low")
    assert result.sampling is None

    monkeypatch.delenv("COLLEAGUE_SAMPLING", raising=False)
    samplingrecord.record(result, "main", model, None, "low")
    assert result.sampling is not None
    assert result.sampling[0]["wire"]["top_k"] == 20
