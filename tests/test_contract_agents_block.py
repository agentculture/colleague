"""``TaskResult.agents`` — the model-bound-agents artifact block (#411, plan
t13; spec c17 / h24).

Pins: the field defaults to ``None`` and is OMITTED from ``to_dict()`` when
``None`` (the ``evaluation_ledger``/``senses``/``chain`` convention — an
unarmed run serializes byte-identically); a populated block round-trips
through ``to_dict``/``from_dict`` and through ``artifact.write``/
``read_artifact``; the pure builders in ``colleague/agents/artifact_block.py``
produce the versioned ``{version, invocations, messages, fallbacks,
ledger_path, ledger_digest}`` shape from real ``InvocationRecord`` /
``AgentMessage`` records (or their dicts); and the engine-side
``fold_agents_block`` is a floor — it fills only a still-``None`` field and
only when ``config.agents`` is armed.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from colleague import artifact
from colleague.agents.artifact_block import (
    AGENTS_BLOCK_KEYS,
    AGENTS_BLOCK_VERSION,
    FALLBACK_ENTRY_KEYS,
    build_agents_block,
    empty_agents_block,
    fallback_entry,
    fallbacks_from_invocations,
    fold_agents_block,
)
from colleague.agents.messages import AgentMessage
from colleague.agents.runtime import InvocationRecord
from colleague.contract import OK, TaskResult


def _record(**over) -> InvocationRecord:
    base = dict(
        agent_id="agent-1",
        purpose="coder",
        model_role="cortex",
        resolved_model="served-id",
        fallback_from_role=None,
        tool_surface_digest="t" * 8,
        ledger_digest="d" * 8,
        nucleus_refs=("step:0",),
        working_set_refs=("a.py",),
        token_estimate=12,
        token_estimate_source="chars",
        seq=1,
    )
    base.update(over)
    return InvocationRecord(**base)


def _message(**over) -> AgentMessage:
    base = dict(
        message_id="m1",
        task_id="t1",
        from_agent="agent-1",
        to_agent="agent-2",
        type="inform",
        subject="status",
        content="done",
        evidence_refs=("step:0",),
        requested_response=None,
        seq=2,
    )
    base.update(over)
    return AgentMessage(**base)


def _populated_block() -> dict:
    return build_agents_block(
        invocations=[
            _record(),
            _record(
                agent_id="agent-2",
                purpose="worker",
                model_role="cortex",
                fallback_from_role="worker",
                seq=3,
            ),
        ],
        messages=[_message()],
        ledger_path=".colleague/agents/t1.ledger.jsonl",
        ledger_digest="e" * 16,
    )


# ---------------------------------------------------------------------------
# The TaskResult field — default, omit-when-None, round-trip
# ---------------------------------------------------------------------------


def test_agents_field_defaults_to_none_and_is_omitted() -> None:
    result = TaskResult(task_id="t1", status=OK, summary="s")
    assert result.agents is None
    assert "agents" not in result.to_dict()
    # Byte-identical to the same result with the field explicitly None.
    same = TaskResult(task_id="t1", status=OK, summary="s", agents=None)
    assert json.dumps(result.to_dict()) == json.dumps(same.to_dict())


def test_agents_from_dict_absent_or_malformed_reads_none() -> None:
    base = TaskResult(task_id="t1", status=OK, summary="s").to_dict()
    assert TaskResult.from_dict(base).agents is None
    for bad in (None, "x", 3, ["not", "a", "dict"]):
        assert TaskResult.from_dict({**base, "agents": bad}).agents is None


def test_agents_populated_block_round_trips() -> None:
    block = _populated_block()
    result = TaskResult(task_id="t1", status=OK, summary="s", agents=block)
    d = result.to_dict()
    assert d["agents"] == block
    reloaded = TaskResult.from_dict(json.loads(json.dumps(d)))
    assert reloaded.agents == block
    assert reloaded == result


def test_to_dict_copies_not_aliases_the_lists() -> None:
    block = _populated_block()
    result = TaskResult(task_id="t1", status=OK, summary="s", agents=block)
    d = result.to_dict()
    assert d["agents"] is not block
    assert d["agents"]["invocations"] is not block["invocations"]
    assert d["agents"]["invocations"][0] is not block["invocations"][0]
    # Appending to the live block afterwards never leaks into the snapshot.
    block["messages"].append(_message(message_id="m2").to_dict())
    assert len(d["agents"]["messages"]) == 1


def test_agents_key_sits_among_the_omit_when_none_extras() -> None:
    """Emitted in the extras group (after ``evaluation_ledger``, before
    ``senses``) — the same omit-when-None family, so a serialized artifact
    reads in one predictable order."""
    result = TaskResult(
        task_id="t1",
        status=OK,
        summary="s",
        evaluation_ledger={"version": 1, "entries": []},
        agents=empty_agents_block(),
    )
    keys = list(result.to_dict().keys())
    assert keys.index("evaluation_ledger") < keys.index("agents")


# ---------------------------------------------------------------------------
# artifact.write / read keep it
# ---------------------------------------------------------------------------


def test_artifact_write_and_read_keep_the_block(tmp_path: Path) -> None:
    block = _populated_block()
    result = TaskResult(task_id="t-art", status=OK, summary="s", agents=block)
    path = artifact.write(result, tmp_path / ".colleague")
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["agents"] == block
    reloaded = artifact.read_artifact(tmp_path, "t-art")
    assert reloaded is not None
    assert reloaded.agents == block


def test_artifact_write_unarmed_has_no_agents_key(tmp_path: Path) -> None:
    result = TaskResult(task_id="t-none", status=OK, summary="s")
    path = artifact.write(result, tmp_path / ".colleague")
    assert "agents" not in json.loads(path.read_text(encoding="utf-8"))
    assert '"agents"' not in path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# The pure builders
# ---------------------------------------------------------------------------


def test_empty_block_shape_and_version() -> None:
    block = empty_agents_block()
    assert tuple(block.keys()) == AGENTS_BLOCK_KEYS
    assert block == {
        "version": AGENTS_BLOCK_VERSION,
        "invocations": [],
        "messages": [],
        "fallbacks": [],
        "ledger_path": None,
        "ledger_digest": None,
    }
    assert AGENTS_BLOCK_VERSION == 1
    # Pure: a fresh dict every call, never a shared module-level object.
    assert empty_agents_block() is not block


def test_build_block_serializes_records_and_derives_fallbacks() -> None:
    block = _populated_block()
    assert block["version"] == AGENTS_BLOCK_VERSION
    assert block["invocations"] == [
        _record().to_dict(),
        _record(
            agent_id="agent-2",
            purpose="worker",
            model_role="cortex",
            fallback_from_role="worker",
            seq=3,
        ).to_dict(),
    ]
    assert block["messages"] == [_message().to_dict()]
    # Exactly the one record that fell back contributes a fallback entry.
    assert block["fallbacks"] == [
        {"purpose": "worker", "from_role": "worker", "resolved_model": "served-id"}
    ]
    assert tuple(block["fallbacks"][0].keys()) == FALLBACK_ENTRY_KEYS
    assert block["ledger_path"] == ".colleague/agents/t1.ledger.jsonl"
    assert block["ledger_digest"] == "e" * 16
    # JSON-clean (the artifact writer's json.dumps must not choke on it).
    json.dumps(block)


def test_build_block_accepts_already_serialized_dicts() -> None:
    from_records = build_agents_block(invocations=[_record()], messages=[_message()])
    from_dicts = build_agents_block(
        invocations=[_record().to_dict()], messages=[_message().to_dict()]
    )
    assert from_records == from_dicts


def test_build_block_explicit_fallbacks_override_derivation() -> None:
    block = build_agents_block(
        invocations=[_record(fallback_from_role="worker")],
        fallbacks=[fallback_entry("reviewer", "senses", "other-id")],
    )
    assert block["fallbacks"] == [
        {"purpose": "reviewer", "from_role": "senses", "resolved_model": "other-id"}
    ]


def test_fallbacks_from_invocations_is_order_preserving_and_skips_own_role() -> None:
    recs = [
        _record(agent_id="a", purpose="p1", fallback_from_role="worker", resolved_model="m1"),
        _record(agent_id="b", purpose="p2", fallback_from_role=None),
        _record(agent_id="c", purpose="p3", fallback_from_role="senses", resolved_model="m3"),
    ]
    assert fallbacks_from_invocations(recs) == [
        fallback_entry("p1", "worker", "m1"),
        fallback_entry("p3", "senses", "m3"),
    ]
    assert fallbacks_from_invocations([]) == []


def test_build_block_refuses_non_record_entries() -> None:
    with pytest.raises(TypeError, match="record or a mapping"):
        build_agents_block(invocations=["not a record"])


def test_build_block_is_pure() -> None:
    assert _populated_block() == _populated_block()


# ---------------------------------------------------------------------------
# fold_agents_block — the engine-side floor
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class _Cfg:
    agents: bool = False


def test_fold_unarmed_is_a_strict_no_op() -> None:
    result = TaskResult(task_id="t1", status=OK, summary="s")
    before = json.dumps(result.to_dict())
    out = fold_agents_block(result, _Cfg(agents=False))
    assert out is result
    assert result.agents is None
    assert json.dumps(result.to_dict()) == before


def test_fold_armed_fills_the_empty_floor() -> None:
    result = TaskResult(task_id="t1", status=OK, summary="s")
    out = fold_agents_block(result, _Cfg(agents=True))
    assert out is result
    assert result.agents == empty_agents_block()
    assert "agents" in result.to_dict()


def test_fold_never_overwrites_a_loop_authored_block() -> None:
    block = _populated_block()
    result = TaskResult(task_id="t1", status=OK, summary="s", agents=block)
    fold_agents_block(result, _Cfg(agents=True))
    assert result.agents is block


def test_fold_tolerates_a_config_without_the_flag() -> None:
    result = TaskResult(task_id="t1", status=OK, summary="s")
    fold_agents_block(result, object())
    assert result.agents is None
