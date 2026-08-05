"""TaskResult carries the config event stream + effective-config digest
(plan task t7, covers c9/h9) — additive-only, omit-when-empty fields.

Mirrors the shape of tests/test_contract_deepthink.py /
tests/test_contract_lineage.py for the omit-when-empty/None convention, and
tests/test_finish_states.py for the round-trip style.
"""

from __future__ import annotations

from colleague.configevents import ConfigEvent, effective_digest
from colleague.contract import TaskResult

# ---------------------------------------------------------------------------
# Defaults + omit-when-empty artifact shape.
# ---------------------------------------------------------------------------


def test_config_events_field_exists_with_empty_default() -> None:
    result = TaskResult(task_id="x", status="ok")
    assert result.config_events == []
    assert result.config_digest is None


def test_config_events_and_digest_are_omitted_when_empty() -> None:
    """A work item with no recorded config-event activity serializes
    byte-identically to today's artifact shape — no extra keys."""
    result = TaskResult(task_id="x", status="ok")
    d = result.to_dict()
    assert "config_events" not in d
    assert "config_digest" not in d


def test_config_events_key_present_when_non_empty() -> None:
    result = TaskResult(
        task_id="x",
        status="ok",
        config_events=[ConfigEvent(kind="baseline", target="worker.tools", origin="host", seq=0)],
        config_digest="deadbeef",
    )
    d = result.to_dict()
    assert "config_events" in d
    assert "config_digest" in d
    assert d["config_digest"] == "deadbeef"


# ---------------------------------------------------------------------------
# Round-trip through to_dict/from_dict.
# ---------------------------------------------------------------------------


def test_config_events_round_trip_through_from_dict() -> None:
    events = [
        ConfigEvent(kind="baseline", target="worker.tools", origin="host", seq=0),
        ConfigEvent(kind="proposed", target="worker.tools", origin="cortex", seq=1),
        ConfigEvent(
            kind="refused", target="worker.tools", origin="cortex", reason="ceiling", seq=2
        ),
    ]
    original = TaskResult(
        task_id="abc",
        status="ok",
        config_events=events,
        config_digest=effective_digest(events),
    )
    restored = TaskResult.from_dict(original.to_dict())
    assert restored == original
    assert restored.config_events == events
    assert restored.config_digest == effective_digest(events)


def test_config_events_from_dict_drops_malformed_entries() -> None:
    """Best-effort like every other optional structured payload read back
    from an artifact (see contract._coerce_deepthink_calls): a non-dict
    entry is dropped rather than raising."""
    data = {
        "task_id": "x",
        "status": "ok",
        "config_events": [
            {"kind": "baseline", "target": "a", "origin": "host", "reason": "", "seq": 0},
            "not-a-dict",
            None,
            {"kind": "applied", "target": "a", "origin": "host", "reason": "", "seq": 1},
        ],
        "config_digest": "somehash",
    }
    result = TaskResult.from_dict(data)
    assert len(result.config_events) == 2
    assert result.config_events[0].kind == "baseline"
    assert result.config_events[1].kind == "applied"
    assert result.config_digest == "somehash"


def test_config_events_absent_from_dict_defaults_to_empty_list() -> None:
    data = {"task_id": "x", "status": "ok"}
    result = TaskResult.from_dict(data)
    assert result.config_events == []
    assert result.config_digest is None


# ---------------------------------------------------------------------------
# The T8 trap, riding the artifact: replaying config_events ALONE reproduces
# config_digest — no other field on TaskResult contributes to the digest.
# ---------------------------------------------------------------------------


def test_replaying_config_events_alone_reproduces_config_digest() -> None:
    events = [
        ConfigEvent(kind="baseline", target="senses.knowledge", origin="host", seq=0),
        ConfigEvent(kind="proposed", target="senses.knowledge", origin="cortex", seq=1),
        ConfigEvent(kind="verified", target="senses.knowledge", origin="cortex", seq=2),
        ConfigEvent(kind="applied", target="senses.knowledge", origin="host", seq=3),
    ]
    digest = effective_digest(events)
    result = TaskResult(
        task_id="t1",
        status="ok",
        summary="unrelated text",
        config_events=events,
        config_digest=digest,
    )
    # Changing fields that are NOT config_events (summary, task_id, status) never
    # changes what replaying config_events alone reproduces.
    assert effective_digest(result.config_events) == digest
    other = TaskResult(
        task_id="different-id",
        status="error",
        summary="totally different",
        config_events=events,
        config_digest=digest,
    )
    assert effective_digest(other.config_events) == digest
