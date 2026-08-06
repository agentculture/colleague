"""DeepthinkCall dataclass + TaskResult.deepthink (omit-when-None, byte-identical).

Plan task t3 (dual-model deepthink, spec covers c14/h6): when a dual-model
config is present, the runtime MAY escalate a piece of hard reasoning to a
second "deepthink" model instead of the fast wide-window main model. Every
escalation call is recorded as a :class:`~colleague.contract.DeepthinkCall`
on ``TaskResult.deepthink``. This module pins the data shape ONLY — no
escalation logic lives here (that is task t2/t5); a single-model run must
serialize byte-identically to today because ``deepthink`` defaults to
``None`` and is omitted (not emitted as null) from the artifact, mirroring
the existing ``lint_report`` / ``capacity_decision`` / ``acceptance_outcomes``
omit-when-None pattern.
"""

from __future__ import annotations

import json

from colleague.contract import OK, DeepthinkCall, TaskResult

# ---------------------------------------------------------------------------
# Byte-identical guard: no deepthink calls -> no "deepthink" key at all.
# ---------------------------------------------------------------------------


def test_default_taskresult_omits_deepthink_key() -> None:
    """A result with no deepthink calls serializes byte-identical to today."""
    result = TaskResult(task_id="x", status=OK, summary="plain single-model drive")
    assert result.deepthink is None

    serialized = result.to_dict()
    assert "deepthink" not in serialized

    # Exact key set must match the pre-deepthink contract — no extra key sneaks in
    # even when the field exists on the dataclass with its default value.
    expected_keys = {
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
    assert set(serialized.keys()) == expected_keys


def test_default_taskresult_json_is_byte_identical_to_pre_feature_shape() -> None:
    """The JSON text itself (not just the key set) is unaffected by the new field."""
    with_deepthink_field = TaskResult(task_id="abc", status=OK, summary="done")
    serialized = with_deepthink_field.to_dict()
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
# DeepthinkCall defaults.
# ---------------------------------------------------------------------------


def test_deepthink_call_defaults() -> None:
    """tokens/duration default to None, degraded defaults to False."""
    call = DeepthinkCall(point="tool")
    assert call.point == "tool"
    assert call.tokens is None
    assert call.duration is None
    assert call.degraded is False


def test_deepthink_call_accepts_all_fields() -> None:
    call = DeepthinkCall(point="acceptance_selfcheck", tokens=512, duration=1.25, degraded=True)
    assert call.point == "acceptance_selfcheck"
    assert call.tokens == 512
    assert call.duration == 1.25
    assert call.degraded is True


def test_deepthink_call_round_trips_through_json() -> None:
    call = DeepthinkCall(point="plan_proposal", tokens=100, duration=0.5, degraded=False)
    reloaded = DeepthinkCall.from_dict(json.loads(json.dumps(call.to_dict())))
    assert reloaded == call


def test_deepthink_call_round_trips_with_none_tokens_and_duration() -> None:
    """A degraded call that never reached the wire has no tokens/duration to report."""
    call = DeepthinkCall(point="tool", tokens=None, duration=None, degraded=True)
    reloaded = DeepthinkCall.from_dict(json.loads(json.dumps(call.to_dict())))
    assert reloaded == call
    assert reloaded.tokens is None
    assert reloaded.duration is None
    assert reloaded.degraded is True


# ---------------------------------------------------------------------------
# TaskResult.deepthink round-trip (two records, one degraded, one with
# tokens/duration None) through the same serialize/parse path the artifact
# read/write uses (json.dumps -> json.loads -> TaskResult.from_dict).
# ---------------------------------------------------------------------------


def test_task_result_with_deepthink_calls_round_trips_through_json() -> None:
    calls = [
        DeepthinkCall(point="tool", tokens=321, duration=2.75, degraded=False),
        DeepthinkCall(point="acceptance_selfcheck", tokens=None, duration=None, degraded=True),
    ]
    result = TaskResult(
        task_id="dt1",
        status=OK,
        summary="escalated twice",
        deepthink=calls,
    )

    serialized = result.to_dict()
    assert "deepthink" in serialized
    assert serialized["deepthink"] == [c.to_dict() for c in calls]

    reloaded = TaskResult.from_dict(json.loads(json.dumps(serialized)))
    assert reloaded == result
    assert reloaded.deepthink == calls
    assert reloaded.deepthink[0].degraded is False
    assert reloaded.deepthink[1].degraded is True
    assert reloaded.deepthink[1].tokens is None
    assert reloaded.deepthink[1].duration is None


def test_task_result_deepthink_calls_preserve_order() -> None:
    calls = [
        DeepthinkCall(point="a"),
        DeepthinkCall(point="b"),
        DeepthinkCall(point="c"),
    ]
    result = TaskResult(task_id="dt2", status=OK, deepthink=calls)
    reloaded = TaskResult.from_dict(json.loads(json.dumps(result.to_dict())))
    assert [c.point for c in reloaded.deepthink] == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# from_dict back-compat: reads both WITH and WITHOUT the "deepthink" key.
# ---------------------------------------------------------------------------


def test_task_result_from_dict_tolerates_missing_deepthink() -> None:
    """A pre-deepthink artifact (no 'deepthink' key at all) loads with None."""
    old_payload = {
        "task_id": "back1",
        "status": OK,
        "summary": "",
        "changed_files": [],
        "steps": [],
        "usage": {},
    }
    result = TaskResult.from_dict(old_payload)
    assert result.deepthink is None


def test_task_result_from_dict_reads_deepthink_when_present() -> None:
    payload = {
        "task_id": "fwd1",
        "status": OK,
        "summary": "",
        "changed_files": [],
        "steps": [],
        "usage": {},
        "deepthink": [
            {"point": "tool", "tokens": 10, "duration": 0.1, "degraded": False},
        ],
    }
    result = TaskResult.from_dict(payload)
    assert result.deepthink == [DeepthinkCall(point="tool", tokens=10, duration=0.1)]


def test_task_result_from_dict_empty_deepthink_list_is_empty_not_none() -> None:
    """An explicit empty list is distinct from the key being absent entirely."""
    payload = {
        "task_id": "empty1",
        "status": OK,
        "summary": "",
        "changed_files": [],
        "steps": [],
        "usage": {},
        "deepthink": [],
    }
    result = TaskResult.from_dict(payload)
    assert result.deepthink == []
    assert result.deepthink is not None


def test_task_result_from_dict_drops_malformed_deepthink_entries() -> None:
    """Non-dict entries are dropped rather than raising (best-effort, matching
    the codebase's stance on optional structured payloads read back from a
    possibly hand-edited or partially-written artifact — see
    ``acceptance_outcomes``)."""
    payload = {
        "task_id": "malformed1",
        "status": OK,
        "summary": "",
        "changed_files": [],
        "steps": [],
        "usage": {},
        "deepthink": [
            "not-a-dict",
            42,
            None,
            {"point": "tool"},
        ],
    }

    # Must not raise.
    result = TaskResult.from_dict(payload)

    assert result.deepthink == [DeepthinkCall(point="tool")]


def test_task_result_from_dict_tolerates_unparseable_deepthink_numbers() -> None:
    """A malformed ``tokens``/``duration`` (e.g. a hand-edited or corrupted
    artifact entry) must not raise and abort the whole ``TaskResult.from_dict``
    call — it falls back to ``None`` for the field that couldn't be parsed,
    while ``point``/``degraded`` still survive (Qodo review of PR #261,
    comment PRRC_kwDOSoxhoM7RPQer)."""
    payload = {
        "task_id": "badnum1",
        "status": OK,
        "summary": "",
        "changed_files": [],
        "steps": [],
        "usage": {},
        "deepthink": [
            {"point": "x", "tokens": "n/a", "duration": "bad", "degraded": True},
        ],
    }

    # Must not raise.
    result = TaskResult.from_dict(payload)

    assert result.deepthink == [DeepthinkCall(point="x", tokens=None, duration=None, degraded=True)]
    assert result.deepthink[0].tokens is None
    assert result.deepthink[0].duration is None
    assert result.deepthink[0].point == "x"
    assert result.deepthink[0].degraded is True
