"""Goal fields on the contract (spec R6 / plan t14 / issue #259).

Task gains an optional pre-execution ``goal`` (one line) and machine-readable
``acceptance`` criteria; TaskResult gains ``acceptance_outcomes`` (per-criterion
self-check records); SubResult gains ``parent`` (task_id lineage). All four are
omit-when-None — a Task/TaskResult/SubResult authored without them must
serialize exactly as it did before this task, byte-identical.
"""

from __future__ import annotations

import json

from colleague.contract import OK, SubResult, Task, TaskResult, Usage

# ---------------------------------------------------------------------------
# (a) Task.goal / Task.acceptance
# ---------------------------------------------------------------------------


def test_task_new_without_goal_or_acceptance_is_byte_identical() -> None:
    """A Task authored without goal/acceptance serializes with the pre-t14 key set."""
    task = Task.new("/repo", "add a README", engine="mock")

    assert task.goal is None
    assert task.acceptance is None

    serialized = task.to_dict()
    assert "goal" not in serialized
    assert "acceptance" not in serialized

    expected_keys = {"id", "repo_path", "instruction", "context", "constraints", "engine"}
    assert set(serialized.keys()) == expected_keys


def test_task_new_with_goal_and_acceptance_carries_them() -> None:
    """Task.new accepts goal=/acceptance= keyword params and stores them verbatim."""
    task = Task.new(
        "/repo",
        "add retry logic",
        engine="mock",
        goal="Retries transient network errors up to 3 times",
        acceptance=["a flaky call is retried", "a permanent error is not retried"],
    )

    assert task.goal == "Retries transient network errors up to 3 times"
    assert task.acceptance == [
        "a flaky call is retried",
        "a permanent error is not retried",
    ]

    serialized = task.to_dict()
    assert serialized["goal"] == "Retries transient network errors up to 3 times"
    assert serialized["acceptance"] == [
        "a flaky call is retried",
        "a permanent error is not retried",
    ]


def test_task_goal_and_acceptance_round_trip_through_json() -> None:
    task = Task.new(
        "/repo",
        "ship the feature",
        engine="vllm-openai",
        goal="the feature ships behind a flag",
        acceptance=["flag defaults off", "flag flips the behavior on"],
    )
    reloaded = Task.from_dict(json.loads(json.dumps(task.to_dict())))
    assert reloaded == task
    assert reloaded.goal == task.goal
    assert reloaded.acceptance == task.acceptance


def test_task_from_dict_tolerates_missing_goal_and_acceptance() -> None:
    """from_dict defaults both fields to None when absent (back-compat with today's tasks)."""
    old_payload = {
        "id": "abc123",
        "repo_path": "/repo",
        "instruction": "do work",
        "context": "",
        "constraints": [],
        "engine": "mock",
    }
    task = Task.from_dict(old_payload)
    assert task.goal is None
    assert task.acceptance is None


def test_task_from_dict_reads_goal_and_acceptance_when_present() -> None:
    payload = {
        "id": "def456",
        "repo_path": "/repo",
        "instruction": "do work",
        "context": "",
        "constraints": [],
        "engine": "mock",
        "goal": "the change lands cleanly",
        "acceptance": ["tests pass", "lint is clean"],
    }
    task = Task.from_dict(payload)
    assert task.goal == "the change lands cleanly"
    assert task.acceptance == ["tests pass", "lint is clean"]


# ---------------------------------------------------------------------------
# (b) TaskResult.acceptance_outcomes
# ---------------------------------------------------------------------------


def test_task_result_without_acceptance_outcomes_omits_the_key() -> None:
    """The default (no self-check ran) omits the key from the serialized shape."""
    result = TaskResult(task_id="abc", status=OK, summary="done")
    assert result.acceptance_outcomes is None

    serialized = result.to_dict()
    assert "acceptance_outcomes" not in serialized


def test_task_result_acceptance_outcomes_round_trips_through_json() -> None:
    outcomes = [
        {"criterion": "a flaky call is retried", "met": True, "evidence": "3 retries observed"},
        {
            "criterion": "a permanent error is not retried",
            "met": False,
            "evidence": "no evidence found",
        },
    ]
    result = TaskResult(
        task_id="abc",
        status=OK,
        summary="done",
        acceptance_outcomes=outcomes,
    )

    serialized = result.to_dict()
    assert serialized["acceptance_outcomes"] == outcomes

    reloaded = TaskResult.from_dict(json.loads(json.dumps(serialized)))
    assert reloaded == result
    assert reloaded.acceptance_outcomes == outcomes


def test_task_result_from_dict_tolerates_missing_acceptance_outcomes() -> None:
    """A pre-t14 artifact (no acceptance_outcomes key at all) loads with None — byte-identical."""
    old_payload = {
        "task_id": "back1",
        "status": OK,
        "summary": "",
        "changed_files": [],
        "steps": [],
        "usage": {},
    }
    result = TaskResult.from_dict(old_payload)
    assert result.acceptance_outcomes is None


# ---------------------------------------------------------------------------
# (c) SubResult.parent
# ---------------------------------------------------------------------------


def test_sub_result_without_parent_omits_the_key() -> None:
    sub = SubResult(task_id="child1", engine="mock", model="", status=OK)
    assert sub.parent is None

    serialized = sub.to_dict()
    assert "parent" not in serialized


def test_sub_result_parent_round_trips_through_json() -> None:
    sub = SubResult(
        task_id="child1",
        engine="mock",
        model="",
        status=OK,
        summary="did the sub-task",
        usage=Usage(prompt_tokens=1, completion_tokens=2, total_tokens=3),
        parent="parent-task-id",
    )

    serialized = sub.to_dict()
    assert serialized["parent"] == "parent-task-id"

    reloaded = SubResult.from_dict(json.loads(json.dumps(serialized)))
    assert reloaded == sub
    assert reloaded.parent == "parent-task-id"


def test_sub_result_from_dict_tolerates_missing_parent() -> None:
    """A pre-t14 SubResult payload (no parent key) loads with None — byte-identical."""
    old_payload = {
        "task_id": "child1",
        "engine": "mock",
        "model": "",
        "status": OK,
        "summary": "",
        "changed_files": [],
        "usage": {},
    }
    sub = SubResult.from_dict(old_payload)
    assert sub.parent is None


# ---------------------------------------------------------------------------
# (d) Malformed acceptance_outcomes entries are tolerated, not raised
# ---------------------------------------------------------------------------


def test_task_result_from_dict_drops_malformed_acceptance_outcomes_entries() -> None:
    """Non-dict entries in acceptance_outcomes are dropped rather than raising.

    Mirrors the codebase's best-effort stance on optional structured payloads
    read back from a possibly-hand-edited or partially-written artifact.
    """
    payload = {
        "task_id": "malformed1",
        "status": OK,
        "summary": "",
        "changed_files": [],
        "steps": [],
        "usage": {},
        "acceptance_outcomes": [
            "not-a-dict",
            42,
            None,
            {"criterion": "the valid one", "met": True, "evidence": "seen"},
        ],
    }

    # Must not raise.
    result = TaskResult.from_dict(payload)

    assert result.acceptance_outcomes == [
        {"criterion": "the valid one", "met": True, "evidence": "seen"}
    ]


def test_task_result_from_dict_coerces_partial_acceptance_outcome_entries() -> None:
    """A dict entry missing some keys is coerced with defaults, not dropped."""
    payload = {
        "task_id": "partial1",
        "status": OK,
        "summary": "",
        "changed_files": [],
        "steps": [],
        "usage": {},
        "acceptance_outcomes": [{"criterion": "only a criterion"}],
    }

    result = TaskResult.from_dict(payload)

    assert result.acceptance_outcomes == [
        {"criterion": "only a criterion", "met": False, "evidence": ""}
    ]


def test_task_result_from_dict_empty_acceptance_outcomes_list_is_empty_not_none() -> None:
    """An explicit empty list is distinct from the key being absent entirely."""
    payload = {
        "task_id": "empty1",
        "status": OK,
        "summary": "",
        "changed_files": [],
        "steps": [],
        "usage": {},
        "acceptance_outcomes": [],
    }

    result = TaskResult.from_dict(payload)

    assert result.acceptance_outcomes == []
    assert result.acceptance_outcomes is not None
