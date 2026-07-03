"""ContextPacket + Task.context_packet + omit-when-None TaskResult.senses (t2).

Cortex/senses arc (#274): the "senses" model is a tools-off front door that
interprets an operator's verbatim request into a :class:`ContextPacket`
(``{original, interpretation, confidence, task_type, omissions}``) before the
"cortex" model drives the loop. Each senses invocation is recorded as a
:class:`SensesRecord` (``{point, latency, tokens, degraded}``) inside an
omit-when-None :class:`SensesBlock` (``{mode, packet, records}``) on
``TaskResult.senses``.

This module pins the *data contract only* — no split logic lives here. It
mirrors the existing ``TaskResult.deepthink`` discipline EXACTLY (see
``tests/test_contract_deepthink.py``): the field defaults to ``None`` and is
OMITTED (not emitted as null) from the artifact, so a run with no senses
involvement serializes byte-identically to today. The per-record numeric
coercion tolerance mirrors :class:`~colleague.contract.DeepthinkCall`, and the
``Task.context_packet`` omit-when-None treatment mirrors
``goal``/``acceptance``/``attachments`` (see ``tests/test_contract_attachments.py``).

CRITICAL: the ``ContextPacket.original`` string must round-trip through JSON
*verbatim* — no normalization, no trimming.
"""

from __future__ import annotations

import json

from colleague.contract import (
    OK,
    ContextPacket,
    SensesBlock,
    SensesRecord,
    Task,
    TaskResult,
)

# ---------------------------------------------------------------------------
# ContextPacket dataclass: defaults, round-trip, verbatim `original`.
# ---------------------------------------------------------------------------


def test_context_packet_holds_all_fields() -> None:
    packet = ContextPacket(
        original="fix the bug",
        interpretation="fix the off-by-one in the paginator",
        confidence=0.82,
        task_type="bugfix",
        omissions=["which file", "which test"],
    )
    assert packet.original == "fix the bug"
    assert packet.interpretation == "fix the off-by-one in the paginator"
    assert packet.confidence == 0.82
    assert packet.task_type == "bugfix"
    assert packet.omissions == ["which file", "which test"]


def test_context_packet_round_trips_through_json() -> None:
    packet = ContextPacket(
        original="add a README",
        interpretation="write a top-level README.md",
        confidence=0.5,
        task_type="docs",
        omissions=["length", "sections"],
    )
    reloaded = ContextPacket.from_dict(json.loads(json.dumps(packet.to_dict())))
    assert reloaded == packet


def test_context_packet_original_survives_json_round_trip_verbatim() -> None:
    """The operator's verbatim text must NOT be normalized or trimmed.

    Leading/trailing whitespace, embedded newlines, tabs, and unicode must all
    survive a JSON round-trip byte-for-byte — this is the whole point of the
    ``original`` field (the operator's exact words feed the audit trail).
    """
    tricky = "  Fix\tthe\n\n  paginator — off-by-one 🐛  \n"
    packet = ContextPacket(
        original=tricky,
        interpretation="normalized interpretation",
        confidence=0.9,
        task_type="bugfix",
        omissions=[],
    )
    reloaded = ContextPacket.from_dict(json.loads(json.dumps(packet.to_dict())))
    assert reloaded.original == tricky
    # The interpretation may be normalized, but `original` is byte-identical.
    assert reloaded.original == packet.original


def test_context_packet_from_dict_tolerates_bad_confidence() -> None:
    """A malformed (unparseable) confidence degrades to 0.0, never raises."""
    packet = ContextPacket.from_dict({"original": "x", "confidence": "n/a", "task_type": "y"})
    assert packet.confidence == 0.0
    assert packet.original == "x"
    assert packet.task_type == "y"


# ---------------------------------------------------------------------------
# SensesRecord dataclass: mirrors DeepthinkCall {point, tokens, duration,
# degraded} with `latency` in place of `duration`.
# ---------------------------------------------------------------------------


def test_senses_record_defaults() -> None:
    rec = SensesRecord(point="interpret")
    assert rec.point == "interpret"
    assert rec.latency is None
    assert rec.tokens is None
    assert rec.degraded is False


def test_senses_record_accepts_all_fields() -> None:
    rec = SensesRecord(point="interpret", latency=0.4, tokens=128, degraded=True)
    assert rec.point == "interpret"
    assert rec.latency == 0.4
    assert rec.tokens == 128
    assert rec.degraded is True


def test_senses_record_round_trips_through_json() -> None:
    rec = SensesRecord(point="interpret", latency=1.5, tokens=64, degraded=False)
    reloaded = SensesRecord.from_dict(json.loads(json.dumps(rec.to_dict())))
    assert reloaded == rec


def test_senses_record_round_trips_with_none_latency_and_tokens() -> None:
    """A degraded senses call that never reached the wire reports no latency/tokens."""
    rec = SensesRecord(point="interpret", latency=None, tokens=None, degraded=True)
    reloaded = SensesRecord.from_dict(json.loads(json.dumps(rec.to_dict())))
    assert reloaded == rec
    assert reloaded.latency is None
    assert reloaded.tokens is None
    assert reloaded.degraded is True


def test_senses_record_from_dict_tolerates_unparseable_numbers() -> None:
    """Malformed latency/tokens fall back to None (mirrors DeepthinkCall)."""
    rec = SensesRecord.from_dict(
        {"point": "interpret", "latency": "bad", "tokens": "n/a", "degraded": True}
    )
    assert rec == SensesRecord(point="interpret", latency=None, tokens=None, degraded=True)


# ---------------------------------------------------------------------------
# SensesBlock dataclass: {mode, packet, records}.
# ---------------------------------------------------------------------------


def _packet() -> ContextPacket:
    return ContextPacket(
        original="the operator's exact words",
        interpretation="what senses believes is meant",
        confidence=0.77,
        task_type="feature",
        omissions=["scope"],
    )


def test_senses_block_round_trips_through_json() -> None:
    block = SensesBlock(
        mode="split",
        packet=_packet(),
        records=[
            SensesRecord(point="interpret", latency=0.3, tokens=200, degraded=False),
            SensesRecord(point="interpret_retry", latency=None, tokens=None, degraded=True),
        ],
    )
    reloaded = SensesBlock.from_dict(json.loads(json.dumps(block.to_dict())))
    assert reloaded == block


# ---------------------------------------------------------------------------
# Byte-identical guard #1: TaskResult with no senses -> no "senses" key.
# ---------------------------------------------------------------------------


def test_default_taskresult_omits_senses_key() -> None:
    """A result with no senses involvement serializes byte-identical to today."""
    result = TaskResult(task_id="x", status=OK, summary="plain cortex-only drive")
    assert result.senses is None

    serialized = result.to_dict()
    assert "senses" not in serialized

    # Exact key set must match the pre-senses contract — no extra key sneaks in
    # even though the field exists on the dataclass with its default value.
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
        "not_finished",
        "stopped_without_finish",
    }
    assert set(serialized.keys()) == expected_keys


def test_default_taskresult_json_is_byte_identical_to_pre_feature_shape() -> None:
    """The JSON text itself (not just the key set) is unaffected by the new field."""
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
# Populated senses block round-trips; packet.original preserved verbatim.
# ---------------------------------------------------------------------------


def test_task_result_with_senses_round_trips_and_preserves_original_verbatim() -> None:
    tricky_original = "\t Ship it.\n  (no scope given) 🚀 \n"
    block = SensesBlock(
        mode="split",
        packet=ContextPacket(
            original=tricky_original,
            interpretation="implement the shipping feature",
            confidence=0.6,
            task_type="feature",
            omissions=["acceptance criteria", "target module"],
        ),
        records=[
            SensesRecord(point="interpret", latency=0.9, tokens=321, degraded=False),
        ],
    )
    result = TaskResult(task_id="s1", status=OK, summary="senses split", senses=block)

    serialized = result.to_dict()
    assert "senses" in serialized
    assert serialized["senses"] == block.to_dict()

    reloaded = TaskResult.from_dict(json.loads(json.dumps(serialized)))
    assert reloaded == result
    assert reloaded.senses is not None
    # The whole point of the task: `original` is byte-identical after the trip.
    assert reloaded.senses.packet.original == tricky_original
    assert reloaded.senses.mode == "split"
    assert reloaded.senses.records[0].degraded is False


def test_task_result_senses_records_preserve_order() -> None:
    block = SensesBlock(
        mode="cortex-only",
        packet=_packet(),
        records=[SensesRecord(point="a"), SensesRecord(point="b"), SensesRecord(point="c")],
    )
    result = TaskResult(task_id="s2", status=OK, senses=block)
    reloaded = TaskResult.from_dict(json.loads(json.dumps(result.to_dict())))
    assert [r.point for r in reloaded.senses.records] == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# from_dict back-compat: reads both WITH and WITHOUT the "senses" key.
# ---------------------------------------------------------------------------


def test_task_result_from_dict_tolerates_missing_senses() -> None:
    """A pre-senses artifact (no 'senses' key at all) loads with None."""
    old_payload = {
        "task_id": "back1",
        "status": OK,
        "summary": "",
        "changed_files": [],
        "steps": [],
        "usage": {},
    }
    result = TaskResult.from_dict(old_payload)
    assert result.senses is None


def test_task_result_from_dict_reads_senses_when_present() -> None:
    payload = {
        "task_id": "fwd1",
        "status": OK,
        "summary": "",
        "changed_files": [],
        "steps": [],
        "usage": {},
        "senses": {
            "mode": "split",
            "packet": {
                "original": "verbatim words",
                "interpretation": "interp",
                "confidence": 0.5,
                "task_type": "feature",
                "omissions": ["x"],
            },
            "records": [{"point": "interpret", "latency": 0.1, "tokens": 10, "degraded": False}],
        },
    }
    result = TaskResult.from_dict(payload)
    assert result.senses is not None
    assert result.senses.mode == "split"
    assert result.senses.packet.original == "verbatim words"
    assert result.senses.records == [
        SensesRecord(point="interpret", latency=0.1, tokens=10, degraded=False)
    ]


def test_task_result_from_dict_drops_malformed_senses_records() -> None:
    """Non-dict record entries are dropped rather than raising (best-effort,
    mirroring DeepthinkCall / acceptance_outcomes)."""
    payload = {
        "task_id": "malformed1",
        "status": OK,
        "summary": "",
        "changed_files": [],
        "steps": [],
        "usage": {},
        "senses": {
            "mode": "split",
            "packet": {"original": "x"},
            "records": ["not-a-dict", 42, None, {"point": "interpret"}],
        },
    }
    # Must not raise.
    result = TaskResult.from_dict(payload)
    assert result.senses is not None
    assert result.senses.records == [SensesRecord(point="interpret")]


def test_task_result_from_dict_non_dict_senses_degrades_to_none() -> None:
    """A bare-string / non-dict senses payload degrades to None, never raises."""
    payload = {
        "task_id": "bad1",
        "status": OK,
        "summary": "",
        "changed_files": [],
        "steps": [],
        "usage": {},
        "senses": "not-a-block",
    }
    result = TaskResult.from_dict(payload)
    assert result.senses is None


# ---------------------------------------------------------------------------
# Task.context_packet: optional, omit-when-None (mirrors goal/attachments).
# ---------------------------------------------------------------------------


def test_task_new_without_context_packet_is_byte_identical() -> None:
    """A Task authored without a context_packet serializes with the pre-t2 key set."""
    task = Task.new("/repo", "add a README", engine="mock")
    assert task.context_packet is None

    serialized = task.to_dict()
    assert "context_packet" not in serialized

    expected_keys = {"id", "repo_path", "instruction", "context", "constraints", "engine"}
    assert set(serialized.keys()) == expected_keys


def test_task_round_trips_without_context_packet() -> None:
    task = Task.new("/repo", "add a README", engine="mock")
    reloaded = Task.from_dict(json.loads(json.dumps(task.to_dict())))
    assert reloaded == task
    assert reloaded.context_packet is None


def test_task_new_with_context_packet_carries_it() -> None:
    packet = _packet()
    task = Task.new("/repo", "do it", engine="mock", context_packet=packet)
    assert task.context_packet == packet

    serialized = task.to_dict()
    assert serialized["context_packet"] == packet.to_dict()


def test_task_context_packet_round_trips_and_preserves_original_verbatim() -> None:
    tricky = "  do\tthe\n thing  \n"
    packet = ContextPacket(
        original=tricky,
        interpretation="the thing, interpreted",
        confidence=0.4,
        task_type="chore",
        omissions=[],
    )
    task = Task.new("/repo", "do it", engine="vllm-openai", context_packet=packet)
    reloaded = Task.from_dict(json.loads(json.dumps(task.to_dict())))
    assert reloaded == task
    assert reloaded.context_packet is not None
    assert reloaded.context_packet.original == tricky


def test_task_from_dict_tolerates_missing_context_packet() -> None:
    """from_dict defaults context_packet to None when absent (back-compat)."""
    old_payload = {
        "id": "abc123",
        "repo_path": "/repo",
        "instruction": "do work",
        "context": "",
        "constraints": [],
        "engine": "mock",
    }
    task = Task.from_dict(old_payload)
    assert task.context_packet is None


def test_task_from_dict_non_dict_context_packet_degrades_to_none() -> None:
    """A bare-string / non-dict context_packet degrades to None, never raises."""
    base = Task.new("/tmp/x", "do x").to_dict()
    base["context_packet"] = "not-a-packet"
    assert Task.from_dict(base).context_packet is None
