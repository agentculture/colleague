"""Effort-v4 t5 (c6/c14/h5/h6/c29): the resolved rung lands on the artifact.

Four claims, each pinned end-to-end where feasible:

1. Override-and-read-back (c14/h5): a run with the operator ``--effort xhigh``
   override applied (the ``_listing.apply_effort`` seam the work CLI uses)
   records ``xhigh`` on the "main" FinishRecord AND the top-level ``effort``
   block of the artifact READ BACK FROM DISK — the effective rung, never the
   SEAT_TABLE default.
2. The effort block lists no-finish-record seats (h6): a delegated scout child
   appears under its role name with the rung its built child config carried
   (``"off"`` — proving off-is-recorded too), and the distill pass records
   ``"distill"`` at its launch site.
3. The c29 pair: a run artifact can carry BOTH the recorded rung and the
   ladder-400 retry warning — the pair is the honest record of a dropped key;
   neither erases the other.
4. Shape parity between mock and vllm-openai rides the extended
   ``tests/test_e2e_mock.py`` assertions (all-engines rule).
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from colleague import artifact, registry
from colleague.cli._commands._listing import acting_seat, apply_effort
from colleague.config import EngineConfig
from colleague.contract import OK, FinishRecord, Task, TaskResult
from colleague.engines.vllm_payload import (
    _LadderRetryWarning,
    _record_ladder_retry_warning,
    ladder_retry_warnings_as_dicts,
)
from colleague.loop import ContextControls, ModelResponse, ToolCall, _Work, run
from colleague.loop_memory import _distill_pass
from colleague.subagents import make_spawn
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


# ---------------------------------------------------------------------------
# 1. override-and-read-back (c14/h5): the EFFECTIVE rung, not the table default
# ---------------------------------------------------------------------------


def test_work_effort_xhigh_override_reads_back_from_the_artifact(tmp_path: Path) -> None:
    cfg = EngineConfig.resolve()
    # The exact seam ``work --effort xhigh`` lands through (spec s11): the
    # acting seat's per-seat override, applied after resolve().
    apply_effort(cfg, "xhigh", acting_seat(cfg))

    repo = tmp_path / "repo"
    repo.mkdir()
    result = registry.load("mock").work(Task.new(str(repo), "do work"), cfg)
    path = artifact.write(result, tmp_path / "artifacts")

    data = json.loads(path.read_text())
    main = data["finish_states"][0]
    assert main["seat"] == "main"  # the seat NAME stays "main" — the rung is the join
    assert main["reasoning_effort"] == "xhigh"  # effective rung, not the "low" table default
    assert data["effort"]["main"] == "xhigh"
    # Round-trip: from_dict restores the block losslessly.
    assert TaskResult.from_dict(data).effort == data["effort"]


def test_default_run_records_the_v4_table_rung(tmp_path: Path) -> None:
    """No override: the recorded value is still the RESOLVED rung ("low", v4)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    result = registry.load("mock").work(Task.new(str(repo), "do work"), EngineConfig.resolve())
    assert result.finish_states[0].reasoning_effort == "low"
    assert result.effort == {"main": "low"}


# ---------------------------------------------------------------------------
# 2. the effort block lists no-finish-record seats (h6): scout child + distill
# ---------------------------------------------------------------------------


def test_delegated_scout_child_lands_in_the_parent_effort_block(tmp_path: Path) -> None:
    """A subagent child appears under its role name with its built config's
    rung — the scout role resolves "off" (ROLE_TABLE), proving both the
    no-finish-record seat AND the off-is-recorded rule in one run."""
    repo = tmp_path / "repo"
    repo.mkdir()
    cfg = EngineConfig.resolve()
    task = Task.new(str(repo), "delegate then finish")
    complete = _scripted(
        [
            ModelResponse(
                tool_calls=[
                    ToolCall(
                        "s",
                        "subagent",
                        {"instruction": "survey the repo", "role": "scout", "engine": "mock"},
                    )
                ]
            ),
            _finish(),
        ]
    )
    result = run(
        complete,
        task,
        max_steps=4,
        executor=ToolExecutor(str(repo), spawn=make_spawn(str(repo), cfg, "mock")),
        context=ContextControls.from_config(cfg),
    )

    assert result.status == OK
    assert result.sub_results
    assert result.sub_results[0].role == "scout"
    # The child's SubResult carries the built seat's rung (read, not recomputed) …
    assert result.sub_results[0].reasoning_effort == "off"
    assert result.sub_results[0].to_dict()["reasoning_effort"] == "off"
    # … and the parent's top-level block names both seats built during the run.
    assert result.effort == {"main": "low", "scout": "off"}


def test_distill_launch_records_the_distill_seat(tmp_path: Path) -> None:
    """The rung-2 pass records "distill" with the already-resolved author rung
    at its own launch site — a seat with no finish record of its own."""
    task = Task.new(str(tmp_path), "t")
    result = TaskResult(task_id=task.id, status=OK)
    ctx = _Work(
        executor=None,
        hooks=None,
        telemetry=None,
        task=task,
        result=result,
        messages=[],
        memory_distill=True,
        distill_fn=lambda res, head: None,
        distill_author=SimpleNamespace(effort="low"),
    )
    _distill_pass(ctx, result, "head", "text", {})
    assert result.effort == {"distill": "low"}


def test_injected_distill_fn_without_author_records_nothing(tmp_path: Path) -> None:
    """No author (a test-injected seam) = no resolved rung = no invented row."""
    task = Task.new(str(tmp_path), "t")
    result = TaskResult(task_id=task.id, status=OK)
    ctx = _Work(
        executor=None,
        hooks=None,
        telemetry=None,
        task=task,
        result=result,
        messages=[],
        memory_distill=True,
        distill_fn=lambda res, head: None,
    )
    _distill_pass(ctx, result, "head", "text", {})
    assert result.effort is None
    assert "effort" not in result.to_dict()


# ---------------------------------------------------------------------------
# 3. c29: the recorded rung and the ladder-400 retry warning COEXIST
# ---------------------------------------------------------------------------


def test_recorded_rung_and_ladder_retry_warning_coexist_on_one_artifact(
    tmp_path: Path,
) -> None:
    """The retry warning stays the marker for a dropped key (c29): a run that
    resolved ``xhigh`` but had the key dropped on the ladder-400 retry carries
    BOTH facts — the rung it MEANT to send and the warning that it was
    withheld — neither erases the other."""
    cfg = EngineConfig.resolve()
    _record_ladder_retry_warning(
        cfg, _LadderRetryWarning(seat="main", effort="xhigh", detail="400: unknown effort")
    )
    result = TaskResult(
        task_id="t-c29",
        status=OK,
        summary="done",
        finish_states=[FinishRecord(seat="main", finish_reason="stop", reasoning_effort="xhigh")],
        effort={"main": "xhigh"},
    )
    # The exact fold the work front performs before the artifact write.
    result.warnings = list(result.warnings) + ladder_retry_warnings_as_dicts(cfg)
    path = artifact.write(result, tmp_path / "artifacts")

    data = json.loads(path.read_text())
    assert data["finish_states"][0]["reasoning_effort"] == "xhigh"
    assert data["effort"] == {"main": "xhigh"}
    assert any(
        w.get("effort") == "xhigh" and "400" in w.get("detail", "") for w in data["warnings"]
    )


# ---------------------------------------------------------------------------
# senses parity: the recorded senses rung IS the built senses seat's rung
# ---------------------------------------------------------------------------


def test_recorded_senses_rung_matches_the_built_senses_seat(tmp_path: Path) -> None:
    """One formula, two consumers (h5): ContextControls records exactly the
    rung senses_engine_config builds onto the seat — they share
    effortrecord.seat_effort, so they cannot drift."""
    from colleague.config import SensesConfig
    from colleague.senses import senses_engine_config

    cfg = EngineConfig.resolve()
    cfg.senses = SensesConfig(
        model="senses-m", base_url="http://x/v1", api_key="k", context_budget=None
    )
    cfg.reasoning_effort_seats = {**cfg.reasoning_effort_seats, "senses": "medium"}

    controls = ContextControls.from_config(cfg)
    seat = senses_engine_config(cfg)
    assert controls.reasoning_effort_senses == "medium"
    assert getattr(seat, "reasoning_effort_seat") == "medium"


# ---------------------------------------------------------------------------
# 5. the deepthink seat joins the block when (and only when) it RAN (review-2)
# ---------------------------------------------------------------------------


def test_deepthink_escalation_records_the_deepthink_rung(tmp_path: Path) -> None:
    """A fired deepthink escalation lands {"deepthink": <rung>} on the block."""
    from tests.test_loop_deepthink import _fake_deepthink

    fake, _calls = _fake_deepthink(text="the verdict")
    executor = ToolExecutor(str(tmp_path), deepthink=fake)
    complete = _scripted(
        [
            ModelResponse(
                tool_calls=[ToolCall("d", "deepthink", {"question": "q", "context": "c"})]
            ),
            _finish(),
        ]
    )
    task = Task.new(str(tmp_path), "review x")
    result = run(
        complete,
        task,
        max_steps=5,
        executor=executor,
        context=ContextControls(deepthink_run=fake, reasoning_effort_deepthink="xhigh"),
    )
    assert result.deepthink is not None
    assert result.effort is not None
    assert result.effort.get("deepthink") == "xhigh"


def test_no_escalation_leaves_deepthink_absent_from_the_block(tmp_path: Path) -> None:
    """The rung is threaded but no escalation fires -> the seat stays absent."""
    executor = ToolExecutor(str(tmp_path))
    complete = _scripted([_finish()])
    task = Task.new(str(tmp_path), "do work")
    result = run(
        complete,
        task,
        max_steps=5,
        executor=executor,
        context=ContextControls(reasoning_effort_deepthink="xhigh"),
    )
    assert (result.effort or {}).get("deepthink") is None
