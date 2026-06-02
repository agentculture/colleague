"""SubResult dataclass + TaskResult.sub_results (omit-when-empty, byte-identical).

t1: the foundation for subagent delegation. A drive may delegate a scoped
sub-task to a nested child drive; each child produces a :class:`SubResult`
recorded on the parent. This module pins the data shape:

1. A no-subagent ``TaskResult.to_dict()`` is byte-identical to today — the
   ``sub_results`` key is ABSENT (not null) when the list is empty, mirroring
   the existing ``destination``/``announcement`` omit-when-None pattern.
2. A populated ``sub_results`` round-trips ``to_dict()`` -> ``from_dict()`` to
   an equal object.
3. ``SubResult`` records ``task_id``, ``engine``, ``model``, ``status``,
   ``summary``, ``changed_files``, and its OWN nested ``usage`` (nested-only
   cost attribution — the parent ``TaskResult.usage`` is NOT summed with
   children).
"""

from __future__ import annotations

import json

from colleague.contract import OK, Step, SubResult, TaskResult, Usage

# ---------------------------------------------------------------------------
# Criterion 3: SubResult records the expected fields with the right defaults.
# ---------------------------------------------------------------------------


def test_subresult_records_expected_fields() -> None:
    """SubResult carries task_id/engine/model/status + its own nested usage."""
    sub = SubResult(
        task_id="child1",
        engine="mock",
        model="mmangkad/Qwen3.6-27B-NVFP4",
        status=OK,
        summary="implemented the helper",
        changed_files=["helper.py"],
        usage=Usage(prompt_tokens=7, completion_tokens=3, total_tokens=10),
    )
    assert sub.task_id == "child1"
    assert sub.engine == "mock"
    assert sub.model == "mmangkad/Qwen3.6-27B-NVFP4"
    assert sub.status == OK
    assert sub.summary == "implemented the helper"
    assert sub.changed_files == ["helper.py"]
    # The child carries its OWN usage — nested-only cost attribution.
    assert sub.usage.total_tokens == 10


def test_subresult_defaults() -> None:
    """SubResult has sensible defaults for the optional fields."""
    sub = SubResult(task_id="c", engine="mock", model="m", status=OK)
    assert sub.summary == ""
    assert sub.changed_files == []
    assert sub.usage == Usage()


def test_subresult_defaults_are_independent() -> None:
    """Default-factory fields are not shared between instances."""
    a = SubResult(task_id="1", engine="mock", model="m", status=OK)
    b = SubResult(task_id="2", engine="mock", model="m", status=OK)
    a.changed_files.append("x")
    a.usage.add(1, 1)
    assert b.changed_files == []
    assert b.usage == Usage()


def test_subresult_round_trips_through_json() -> None:
    """SubResult serializes to dict and reconstructs identically (nested usage)."""
    sub = SubResult(
        task_id="child2",
        engine="vllm-openai",
        model="some/model",
        status=OK,
        summary="did the thing",
        changed_files=["a.py", "b.py"],
        usage=Usage(prompt_tokens=12, completion_tokens=8, total_tokens=20),
    )
    reloaded = SubResult.from_dict(json.loads(json.dumps(sub.to_dict())))
    assert reloaded == sub
    assert reloaded.usage.total_tokens == 20


def test_subresult_from_dict_tolerates_missing_optional_keys() -> None:
    """from_dict applies defaults when optional keys are absent."""
    sub = SubResult.from_dict({"task_id": "c", "engine": "mock", "model": "m", "status": OK})
    assert sub.summary == ""
    assert sub.changed_files == []
    assert sub.usage == Usage()


# ---------------------------------------------------------------------------
# Criterion 1: no-subagent result is byte-identical — sub_results key ABSENT.
# ---------------------------------------------------------------------------


def test_sub_results_omitted_when_empty() -> None:
    """to_dict() OMITS 'sub_results' (not null) when the list is empty.

    Byte-identical guard: a drive that delegated nothing must produce the exact
    same key set as before the t1 change — exactly like destination/announcement.
    """
    result = TaskResult(task_id="nosub1", status=OK, summary="plain drive")
    serialized = result.to_dict()
    assert "sub_results" not in serialized
    # Exact key set must match the pre-t1 contract (no subagent, no destination).
    expected_keys = {
        "task_id",
        "status",
        "summary",
        "changed_files",
        "steps",
        "usage",
        "stats",
        "artifacts_path",
        "error",
        "branch",
        "pr_url",
        "hook_firings",
        "command",
    }
    assert set(serialized.keys()) == expected_keys


def test_sub_results_default_is_empty_list() -> None:
    """A default TaskResult has an empty sub_results list (and independent)."""
    a = TaskResult(task_id="1", status=OK)
    b = TaskResult(task_id="2", status=OK)
    assert a.sub_results == []
    a.sub_results.append(SubResult(task_id="x", engine="mock", model="m", status=OK))
    assert b.sub_results == []


# ---------------------------------------------------------------------------
# Criterion 2: populated sub_results round-trips to an equal object.
# ---------------------------------------------------------------------------


def test_task_result_with_sub_results_includes_key_and_round_trips() -> None:
    """A TaskResult with one SubResult includes the key and round-trips equal."""
    sub = SubResult(
        task_id="child3",
        engine="mock",
        model="m",
        status=OK,
        summary="sub work",
        changed_files=["c.py"],
        usage=Usage(prompt_tokens=5, completion_tokens=2, total_tokens=7),
    )
    result = TaskResult(
        task_id="parent1",
        status=OK,
        summary="delegated some work",
        sub_results=[sub],
    )
    serialized = result.to_dict()
    assert "sub_results" in serialized
    assert serialized["sub_results"] == [sub.to_dict()]
    reloaded = TaskResult.from_dict(json.loads(json.dumps(serialized)))
    assert reloaded == result
    assert len(reloaded.sub_results) == 1
    assert reloaded.sub_results[0].engine == "mock"


def test_task_result_with_multiple_sub_results_round_trips() -> None:
    """Multiple SubResults survive a full JSON round-trip in order."""
    subs = [
        SubResult(task_id="c1", engine="mock", model="m1", status=OK, summary="one"),
        SubResult(
            task_id="c2",
            engine="vllm-openai",
            model="m2",
            status=OK,
            summary="two",
            changed_files=["x.py"],
            usage=Usage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        ),
    ]
    result = TaskResult(
        task_id="parent2",
        status=OK,
        steps=[Step(index=0, tool="finish", result="done")],
        usage=Usage(prompt_tokens=9, completion_tokens=4, total_tokens=13),
        sub_results=subs,
    )
    reloaded = TaskResult.from_dict(json.loads(json.dumps(result.to_dict())))
    assert reloaded == result
    # Parent usage is NOT summed with children — it keeps its own total.
    assert reloaded.usage.total_tokens == 13
    assert reloaded.sub_results[1].usage.total_tokens == 2


def test_from_dict_tolerates_missing_sub_results() -> None:
    """from_dict defaults sub_results to [] when absent (back-compat artifacts)."""
    old_payload = {
        "task_id": "back1",
        "status": OK,
        "summary": "",
        "changed_files": [],
        "steps": [],
        "usage": {},
    }
    result = TaskResult.from_dict(old_payload)
    assert result.sub_results == []
