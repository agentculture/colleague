"""Guard tests for the dual-model deepthink escalation (plan task t9).

t9's job is NOT to add behavior -- it proves three honesty conditions the spec
(docs/specs/2026-07-01-colleague-drives-with-two-minds-a-fast-wide-window.md)
makes about the feature as a whole, using the mock engine as the contract
reference (the all-engines rule):

- Byte-identical single-model path (c1/h10/h1): with no dual-model config
  present, a work item's serialized TaskResult carries no "deepthink" key at
  all, and the rest of the key set matches the pre-feature contract exactly
  (mirroring how tests/test_e2e_mock.py pins the no-destination /
  no-subagent shapes).
- The c13 degradation ladder, end-to-end: with a dual-model config AND
  acceptance criteria declared, the run still COMPLETES -- the mock engine's
  own make_complete has no live model behind it, so the deepthink seam's
  registry.load("mock").make_complete(...) call raises NotImplementedError
  (the base colleague.engine.Engine default), which
  colleague.deepthink.run_deepthink catches and turns into a degraded call
  record -- never a crashed run (spec h5/c13).
- Dual-config alone changes nothing (h1: "the model IS the presence signal"
  is about *config*; this proves it about *behavior* too) -- with no
  acceptance criteria declared, no escalation point fires even though a
  deepthink target IS configured, so TaskResult.deepthink stays None.

A fourth block pins the artifact write/read round-trip through
colleague/artifact.py (not just TaskResult.to_dict/from_dict directly, which
tests/test_contract_deepthink.py already covers) -- the actual on-disk path a
caller reads back from (spec c15/h7: the artifact is the durable handoff
payload).

This file deliberately does NOT duplicate tests/test_loop_deepthink.py (t5's
loop-wiring unit tests, which inject a fake DeepthinkRun directly into
colleague.loop.run) -- every test here drives the FULL engine work() path
(registry.load("mock").work(task, config)), the same seam a real caller
uses, and the mock's real make_complete (which raises) provides the live
degradation instead of a scripted fake.
"""

from __future__ import annotations

import json
from pathlib import Path

from colleague import registry
from colleague.artifact import write
from colleague.config import DeepthinkConfig, EngineConfig
from colleague.contract import OK, DeepthinkCall, Task, TaskResult

# The pre-deepthink byte-identical key set -- mirrors the pinned key sets in
# tests/test_e2e_mock.py (test_no_destination_drive_omits_destination_keys_byte_identical
# et al.) and tests/test_contract_deepthink.py (t3's own byte-identical guard).
# "deepthink" is deliberately absent: it must never appear for a single-model run.
_PRE_DEEPTHINK_KEYS = {
    "task_id",
    "status",
    "summary",
    "changed_files",
    "steps",
    "usage",
    "stats",
    "finish_states",
    "artifacts_path",
    "error",
    "branch",
    "pr_url",
    "hook_firings",
    "command",
    "not_finished",
    "stopped_without_finish",
}


def _dual_config(**kwargs: object) -> EngineConfig:
    """A dual-model EngineConfig pointed at an endpoint that is never actually
    dialed: the mock engine's escalation call resolves via registry.load("mock")
    and its inherited Engine.make_complete raises before any network I/O is
    attempted, so base_url/api_key here are placeholders, not live targets.
    """
    return EngineConfig(
        deepthink=DeepthinkConfig(
            model="deep-model",
            base_url="http://localhost:1/v1",
            api_key="k",
            context_budget=48000,
        ),
        **kwargs,
    )


# ---------------------------------------------------------------------------
# 1. Single-model path is byte-identical (c1/h10/h1).
# ---------------------------------------------------------------------------


def test_single_model_run_has_no_deepthink_key_and_pinned_shape(tmp_path: Path) -> None:
    """A mock work item with NO deepthink config serializes with no "deepthink" key
    and the exact pre-feature key set -- the single-model path is untouched."""
    cfg = EngineConfig.resolve()
    assert cfg.deepthink is None  # sanity: no dual-model declaration in play

    result = registry.load("mock").work(Task.new(str(tmp_path), "do work"), cfg)

    assert result.status == OK
    # The drive really ran (edited the repo) -- this is a live, not a vacuous, result.
    assert result.changed_files
    assert result.deepthink is None

    serialized = result.to_dict()
    assert "deepthink" not in serialized
    assert set(serialized.keys()) == _PRE_DEEPTHINK_KEYS, (
        "single-model artifact key set drifted from the pre-deepthink contract:\n"
        f"  got:      {set(serialized.keys())}\n"
        f"  expected: {_PRE_DEEPTHINK_KEYS}"
    )


def test_single_model_run_json_text_is_byte_identical_to_pre_feature_shape(
    tmp_path: Path,
) -> None:
    """Not just the key set -- the JSON text itself for a bare TaskResult with no
    deepthink calls is unaffected by the new field existing on the dataclass."""
    result = TaskResult(task_id="abc", status=OK, summary="done")
    serialized = result.to_dict()
    reference = {
        "task_id": "abc",
        "status": OK,
        "summary": "done",
        "changed_files": [],
        "steps": [],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "stats": serialized["stats"],
        "finish_states": serialized["finish_states"],
        "artifacts_path": None,
        "error": None,
        "branch": None,
        "pr_url": None,
        "hook_firings": [],
        "command": None,
        "not_finished": False,
        "stopped_without_finish": False,
    }
    assert json.dumps(serialized, sort_keys=True) == json.dumps(reference, sort_keys=True)


# ---------------------------------------------------------------------------
# 2. The c13 degradation ladder, end-to-end, through the mock engine's OWN
#    make_complete (no injected fake) -- the lint fix-turn precedent applied
#    to deepthink: a dead/absent live model degrades, it never crashes the run.
# ---------------------------------------------------------------------------


def test_dual_config_acceptance_selfcheck_degrades_and_run_still_completes(
    tmp_path: Path,
) -> None:
    """A mock work item WITH dual-model config AND acceptance criteria completes
    (status OK) and records a DEGRADED acceptance_selfcheck deepthink call.

    The mock engine's own make_complete (inherited, unmocked) raises
    NotImplementedError -- there is no live model behind "mock" -- so
    run_deepthink catches it and returns a degraded record; the loop then
    falls back to its own (also mock-scripted) main-model self-check turn.
    The run's terminal status is never affected by the escalation's fate.
    """
    cfg = _dual_config()
    task = Task.new(str(tmp_path), "do work", acceptance=["file exists"])

    result = registry.load("mock").work(task, cfg)

    assert result.status == OK
    assert result.deepthink is not None
    assert len(result.deepthink) == 1
    call = result.deepthink[0]
    assert isinstance(call, DeepthinkCall)
    assert call.point == "acceptance_selfcheck"
    assert call.degraded is True
    # A degraded call never reached (or never usefully reached) the deepthink
    # model -- no tokens to report, but duration is always measured (spec:
    # "call.duration is the measured wall-clock seconds up to the failure,
    # always >= 0").
    assert call.tokens is None
    assert call.duration is not None and call.duration >= 0

    # The degradation is recorded, never emitted as an error / raised exception --
    # the artifact still serializes cleanly with the deepthink key present.
    serialized = result.to_dict()
    assert serialized["deepthink"] == [call.to_dict()]


# ---------------------------------------------------------------------------
# 3. Dual config alone changes nothing without an escalation trigger (h1).
# ---------------------------------------------------------------------------


def test_dual_config_without_acceptance_criteria_records_no_deepthink_calls(
    tmp_path: Path,
) -> None:
    """A dual-model config with NO acceptance criteria on the task never escalates:
    the acceptance self-check is the only escalation point the mock's scripted run
    can reach (the mock's script never calls the deepthink tool itself), so
    result.deepthink stays None -- dual config is a capability, not a trigger."""
    cfg = _dual_config()
    task = Task.new(str(tmp_path), "do work")  # no acceptance criteria

    result = registry.load("mock").work(task, cfg)

    assert result.status == OK
    assert result.changed_files
    assert result.deepthink is None
    assert "deepthink" not in result.to_dict()


# ---------------------------------------------------------------------------
# 4. Artifact write/read round-trip through colleague/artifact.py (not just
#    TaskResult.to_dict/from_dict directly -- the actual on-disk path).
# ---------------------------------------------------------------------------


def test_artifact_write_read_round_trip_preserves_deepthink_block(tmp_path: Path) -> None:
    """colleague.artifact.write() + a JSON reload preserve a non-empty deepthink
    block byte-for-byte, including a degraded record with no tokens/duration."""
    calls = [
        DeepthinkCall(point="tool", tokens=128, duration=1.5, degraded=False),
        DeepthinkCall(point="acceptance_selfcheck", tokens=None, duration=0.2, degraded=True),
    ]
    result = TaskResult(
        task_id="dt-artifact-1",
        status=OK,
        summary="escalated twice",
        deepthink=calls,
    )

    out_dir = tmp_path / ".colleague"
    path = write(result, out_dir)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert "deepthink" in payload
    assert payload["deepthink"] == [c.to_dict() for c in calls]

    reloaded = TaskResult.from_dict(payload)
    assert reloaded.deepthink == calls
    assert reloaded.deepthink[0].degraded is False
    assert reloaded.deepthink[1].degraded is True
    assert reloaded.deepthink[1].tokens is None


def test_artifact_write_read_round_trip_omits_deepthink_when_none(tmp_path: Path) -> None:
    """A work item with no deepthink calls writes an artifact with NO "deepthink"
    key at all (omit-when-None), and reloading it yields deepthink=None again."""
    result = TaskResult(task_id="dt-artifact-2", status=OK, summary="single-model drive")
    assert result.deepthink is None

    out_dir = tmp_path / ".colleague"
    path = write(result, out_dir)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert "deepthink" not in payload

    reloaded = TaskResult.from_dict(payload)
    assert reloaded.deepthink is None


def test_dual_config_engine_run_artifact_round_trips_full_pipeline(tmp_path: Path) -> None:
    """The full pipeline, end to end: a real dual-config mock work item's degraded
    acceptance_selfcheck record survives engine.work() -> artifact.write() ->
    JSON reload -> TaskResult.from_dict() unchanged."""
    cfg = _dual_config()
    task = Task.new(str(tmp_path), "do work", acceptance=["file exists"])

    result = registry.load("mock").work(task, cfg)
    assert result.status == OK
    assert result.deepthink is not None

    out_dir = tmp_path / ".colleague"
    path = write(result, out_dir)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["deepthink"] == [c.to_dict() for c in result.deepthink]

    reloaded = TaskResult.from_dict(payload)
    assert reloaded.deepthink == result.deepthink
    assert reloaded.deepthink[0].point == "acceptance_selfcheck"
    assert reloaded.deepthink[0].degraded is True
