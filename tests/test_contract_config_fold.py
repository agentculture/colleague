"""Contract fold: configlifecycle events -> durable configevents.ConfigEvent
records, and verbatim applied strategist content (three-tier-execution plan
task t8, covers c6/h6/c36/h29).

colleague.configlifecycle.EpisodeConfigLifecycle keeps its OWN small,
in-memory event log (kind in {"proposed", "refused", "applied", "boundary"})
plus a per-window application history -- neither shape is what
TaskResult.config_events carries. colleague.contract.map_configlifecycle_events
is the ONE mapper that turns the lifecycle's own records into the durable
configevents.ConfigEvent vocabulary, mapping kinds honestly (never inventing
a new configevents kind) and folding each applied worker.prompt.strategist
unit's verbatim content onto its applied record -- sourced from the
originally-queued ChangeUnit, since neither the lifecycle event nor
ConfigApplication carries content itself.

configevents.py belongs to a sibling task (t6) this wave and is never
touched here or by the mapper; colleague.contract.ConfigEventRecord is
contract.py's own compatible extension of ConfigEvent.to_dict/from_dict.
"""

from __future__ import annotations

import json

from colleague.artifact import write
from colleague.configevents import (
    EVENT_KIND_APPLIED,
    EVENT_KIND_BASELINE,
    EVENT_KIND_DEGRADED,
    EVENT_KIND_PROPOSED,
    EVENT_KIND_REFUSED,
    EVENT_KIND_REVERTED,
    EVENT_KIND_VERIFIED,
    EVENT_KINDS,
    effective_digest,
)
from colleague.configlifecycle import (
    WINDOW_BEFORE_EPISODE_1,
    WINDOW_BETWEEN_EPISODES,
    EpisodeConfigLifecycle,
)
from colleague.contract import (
    ConfigEventRecord,
    TaskResult,
    config_digest_for,
    map_configlifecycle_events,
)
from colleague.lattice import CapabilityCatalog, ChangeUnit, Origin, Target


def _catalog(tool_ids: list[str]) -> CapabilityCatalog:
    return CapabilityCatalog(tool_ids=tuple(tool_ids))


# ---------------------------------------------------------------------------
# Kind mapping -- honest, never invented (acceptance 1)
# ---------------------------------------------------------------------------


def test_maps_proposed_refused_applied_and_boundary_kinds_honestly() -> None:
    lifecycle = EpisodeConfigLifecycle(catalog=_catalog(["read_file"]))
    lifecycle.propose(
        ChangeUnit(target=Target.WORKER_TOOLS, origin=Origin.CORTEX, tool_ids=["read_file"])
    )
    lifecycle.propose(
        ChangeUnit(target=Target.WORKER_TOOLS, origin=Origin.CORTEX, tool_ids=["missing"])
    )
    lifecycle.apply_window(WINDOW_BEFORE_EPISODE_1)
    lifecycle.end_episode()

    applied_unit = ChangeUnit(
        target=Target.WORKER_TOOLS, origin=Origin.CORTEX, tool_ids=["read_file"]
    )
    mapped = map_configlifecycle_events(lifecycle.events(), applied_units=[applied_unit])

    assert [e.kind for e in mapped] == [
        EVENT_KIND_PROPOSED,
        EVENT_KIND_REFUSED,
        EVENT_KIND_APPLIED,
        EVENT_KIND_BASELINE,
    ]


def test_boundary_never_invents_a_new_kind_it_reuses_baseline() -> None:
    """ "boundary" has no durable counterpart of its own in configevents.py --
    it maps onto the closest HONEST existing kind (baseline, a resting-state
    marker) rather than inventing e.g. "boundary" as a brand-new string."""
    lifecycle = EpisodeConfigLifecycle()
    lifecycle.end_episode()

    mapped = map_configlifecycle_events(lifecycle.events())

    assert len(mapped) == 1
    assert mapped[0].kind == EVENT_KIND_BASELINE
    assert mapped[0].kind in EVENT_KINDS  # never a string outside the vocabulary
    assert "boundary" not in EVENT_KINDS  # confirms this really is a reused kind


def test_seq_is_assigned_positionally_from_zero() -> None:
    lifecycle = EpisodeConfigLifecycle()
    lifecycle.end_episode()
    lifecycle.end_episode()
    lifecycle.end_episode()

    mapped = map_configlifecycle_events(lifecycle.events())

    assert [e.seq for e in mapped] == [0, 1, 2]


def test_target_and_origin_ride_straight_through() -> None:
    lifecycle = EpisodeConfigLifecycle(catalog=_catalog(["read_file"]))
    lifecycle.propose(
        ChangeUnit(target=Target.WORKER_TOOLS, origin=Origin.CORTEX, tool_ids=["read_file"])
    )

    mapped = map_configlifecycle_events(lifecycle.events())

    assert mapped[0].target == "worker.tools"
    assert mapped[0].origin == "cortex"


# ---------------------------------------------------------------------------
# Verbatim applied strategist content (acceptance 2)
# ---------------------------------------------------------------------------


def test_applied_strategist_unit_content_rides_the_applied_record() -> None:
    lifecycle = EpisodeConfigLifecycle()
    unit = ChangeUnit(
        target=Target.WORKER_PROMPT_STRATEGIST,
        origin=Origin.CORTEX,
        content="  Focus on the honest-README timer inversion.  ",
    )
    lifecycle.propose(unit)
    lifecycle.apply_window(WINDOW_BEFORE_EPISODE_1)

    mapped = map_configlifecycle_events(lifecycle.events(), applied_units=[unit])

    applied = [e for e in mapped if e.kind == "applied"]
    assert len(applied) == 1
    assert applied[0].content == "Focus on the honest-README timer inversion."
    assert isinstance(applied[0], ConfigEventRecord)


def test_applied_non_strategist_unit_carries_no_content() -> None:
    lifecycle = EpisodeConfigLifecycle(catalog=_catalog(["read_file"]))
    unit = ChangeUnit(target=Target.WORKER_TOOLS, origin=Origin.CORTEX, tool_ids=["read_file"])
    lifecycle.propose(unit)
    lifecycle.apply_window(WINDOW_BEFORE_EPISODE_1)

    mapped = map_configlifecycle_events(lifecycle.events(), applied_units=[unit])

    applied = [e for e in mapped if e.kind == "applied"]
    assert len(applied) == 1
    # A non-strategist applied unit contributes no content -- the mapped
    # record is a PLAIN ConfigEvent (no content attribute at all), not a
    # ConfigEventRecord, mirroring _coerce_config_events' own class-selection
    # rule so mapper output and a round-tripped artifact match.
    assert not isinstance(applied[0], ConfigEventRecord)
    assert getattr(applied[0], "content", "") == ""


def test_refused_records_stay_reason_only_never_content() -> None:
    lifecycle = EpisodeConfigLifecycle(catalog=_catalog(["read_file"]))
    lifecycle.propose(
        ChangeUnit(target=Target.WORKER_TOOLS, origin=Origin.CORTEX, tool_ids=["missing"])
    )

    mapped = map_configlifecycle_events(lifecycle.events())

    refused = [e for e in mapped if e.kind == "refused"]
    assert len(refused) == 1
    assert refused[0].reason != ""
    assert not isinstance(refused[0], ConfigEventRecord)
    assert getattr(refused[0], "content", "") == ""


def test_non_refused_records_carry_no_reason() -> None:
    """The flip side of "refused records stay reason-only": every other kind
    keeps reason empty, matching ConfigEvent's own stated convention."""
    lifecycle = EpisodeConfigLifecycle(catalog=_catalog(["read_file"]))
    unit = ChangeUnit(target=Target.WORKER_TOOLS, origin=Origin.CORTEX, tool_ids=["read_file"])
    lifecycle.propose(unit)
    lifecycle.apply_window(WINDOW_BEFORE_EPISODE_1)
    lifecycle.end_episode()

    mapped = map_configlifecycle_events(lifecycle.events(), applied_units=[unit])

    for event in mapped:
        if event.kind != "refused":
            assert event.reason == ""


def test_multiple_applied_units_matched_positionally_across_windows() -> None:
    """Two windows, each applying a different strategist note -- the mapper
    pairs each 'applied' lifecycle event with the caller's flat, ordered
    applied_units list (decision q2: the fold is cumulative)."""
    lifecycle = EpisodeConfigLifecycle()
    first = ChangeUnit(
        target=Target.WORKER_PROMPT_STRATEGIST, origin=Origin.CORTEX, content="First note"
    )
    lifecycle.propose(first)
    lifecycle.apply_window(WINDOW_BEFORE_EPISODE_1)

    second = ChangeUnit(
        target=Target.WORKER_PROMPT_STRATEGIST, origin=Origin.CORTEX, content="Second note"
    )
    lifecycle.propose(second)
    lifecycle.apply_window(WINDOW_BETWEEN_EPISODES)

    mapped = map_configlifecycle_events(lifecycle.events(), applied_units=[first, second])

    applied = [e for e in mapped if e.kind == "applied"]
    assert [e.content for e in applied] == ["First note", "Second note"]


def test_applied_units_shorter_than_applied_events_never_raises() -> None:
    lifecycle = EpisodeConfigLifecycle(catalog=_catalog(["read_file"]))
    lifecycle.propose(
        ChangeUnit(target=Target.WORKER_TOOLS, origin=Origin.CORTEX, tool_ids=["read_file"])
    )
    lifecycle.apply_window(WINDOW_BEFORE_EPISODE_1)

    mapped = map_configlifecycle_events(lifecycle.events(), applied_units=[])  # none supplied

    applied = [e for e in mapped if e.kind == "applied"]
    assert getattr(applied[0], "content", "") == ""


def test_no_applied_units_kwarg_defaults_to_empty_and_never_raises() -> None:
    lifecycle = EpisodeConfigLifecycle()
    lifecycle.end_episode()
    mapped = map_configlifecycle_events(lifecycle.events())
    assert len(mapped) == 1


# ---------------------------------------------------------------------------
# ConfigEventRecord -- compatible extension of ConfigEvent (old artifacts load)
# ---------------------------------------------------------------------------


def test_content_omitted_from_to_dict_when_empty() -> None:
    record = ConfigEventRecord(kind="applied", target="worker.tools", origin="cortex", seq=0)
    assert "content" not in record.to_dict()


def test_content_present_in_to_dict_when_set() -> None:
    record = ConfigEventRecord(
        kind="applied", target="worker.prompt.strategist", origin="cortex", seq=0, content="note"
    )
    assert record.to_dict()["content"] == "note"


def test_from_dict_reads_content_when_present() -> None:
    data = {
        "kind": "applied",
        "target": "worker.prompt.strategist",
        "origin": "cortex",
        "reason": "",
        "seq": 0,
        "content": "note",
    }
    record = ConfigEventRecord.from_dict(data)
    assert record.content == "note"


def test_from_dict_defaults_content_empty_for_an_old_artifact_entry() -> None:
    """An entry written before content existed (no 'content' key) loads with
    content='' -- old artifacts must still load."""
    data = {"kind": "baseline", "target": "worker.tools", "origin": "host", "reason": "", "seq": 0}
    record = ConfigEventRecord.from_dict(data)
    assert record.content == ""
    assert "content" not in record.to_dict()  # round-trips back to the omitted shape


def test_a_plain_configevent_instance_is_unaffected_by_the_subclass() -> None:
    """A plain ConfigEvent (e.g. one another producer, like
    colleague.configurator, appends directly onto a ConfigEventStream) keeps
    its own to_dict shape untouched -- Python dispatches on the actual class."""
    from colleague.configevents import ConfigEvent

    plain = ConfigEvent(kind="applied", target="worker.tools", origin="cortex", seq=0)
    assert plain.to_dict() == {
        "kind": "applied",
        "target": "worker.tools",
        "origin": "cortex",
        "reason": "",
        "seq": 0,
    }


# ---------------------------------------------------------------------------
# TaskResult round trip (acceptance 1) + the artifact on disk
# ---------------------------------------------------------------------------


def test_taskresult_round_trips_mapped_events_with_content() -> None:
    lifecycle = EpisodeConfigLifecycle()
    unit = ChangeUnit(
        target=Target.WORKER_PROMPT_STRATEGIST, origin=Origin.CORTEX, content="Applied note"
    )
    lifecycle.propose(unit)
    lifecycle.apply_window(WINDOW_BEFORE_EPISODE_1)
    mapped = map_configlifecycle_events(lifecycle.events(), applied_units=[unit])

    result = TaskResult(
        task_id="fold1",
        status="ok",
        config_events=mapped,
        config_digest=config_digest_for(mapped),
    )
    restored = TaskResult.from_dict(result.to_dict())

    assert [e.kind for e in restored.config_events] == [e.kind for e in mapped]
    applied = [e for e in restored.config_events if e.kind == "applied"]
    assert applied[0].content == "Applied note"
    assert restored.config_digest == effective_digest(mapped)


def test_unarmed_run_omits_config_events_entirely() -> None:
    """No lifecycle activity -> the mapper returns [] -> the artifact omits
    the key entirely (omit-when-empty pinned, acceptance 2)."""
    mapped = map_configlifecycle_events([])
    result = TaskResult(task_id="unarmed1", status="ok", config_events=mapped)

    d = result.to_dict()

    assert mapped == []
    assert "config_events" not in d
    assert "config_digest" not in d


def test_mapped_events_round_trip_through_the_artifact_on_disk(tmp_path) -> None:
    """Acceptance 1: '...and the artifact on disk'."""
    lifecycle = EpisodeConfigLifecycle()
    unit = ChangeUnit(
        target=Target.WORKER_PROMPT_STRATEGIST, origin=Origin.CORTEX, content="On-disk note"
    )
    lifecycle.propose(unit)
    lifecycle.apply_window(WINDOW_BEFORE_EPISODE_1)
    mapped = map_configlifecycle_events(lifecycle.events(), applied_units=[unit])

    result = TaskResult(
        task_id="fold-disk1",
        status="ok",
        config_events=mapped,
        config_digest=config_digest_for(mapped),
    )
    path = write(result, tmp_path / ".colleague")
    payload = json.loads(path.read_text())
    reloaded = TaskResult.from_dict(payload)

    applied = [e for e in reloaded.config_events if e.kind == "applied"]
    assert applied[0].content == "On-disk note"
    assert payload["config_digest"] == config_digest_for(mapped)
    applied_raw = [e for e in payload["config_events"] if e["kind"] == "applied"]
    assert applied_raw[0]["content"] == "On-disk note"


# ---------------------------------------------------------------------------
# config_digest_for -- the digest helper both the front and artifact.py share
# ---------------------------------------------------------------------------


def test_config_digest_for_empty_is_none() -> None:
    assert config_digest_for([]) is None


def test_config_digest_for_matches_effective_digest() -> None:
    lifecycle = EpisodeConfigLifecycle()
    lifecycle.end_episode()
    mapped = map_configlifecycle_events(lifecycle.events())
    assert config_digest_for(mapped) == effective_digest(mapped)


def test_config_digest_for_changes_when_content_changes() -> None:
    """Content rides ConfigEventRecord.to_dict, which canonical()/
    effective_digest already dispatch to dynamically -- an applied
    strategist unit's content genuinely moves the digest, not just kind/
    target/origin/seq."""
    lifecycle_a = EpisodeConfigLifecycle()
    unit_a = ChangeUnit(
        target=Target.WORKER_PROMPT_STRATEGIST, origin=Origin.CORTEX, content="Note A"
    )
    lifecycle_a.propose(unit_a)
    lifecycle_a.apply_window(WINDOW_BEFORE_EPISODE_1)
    mapped_a = map_configlifecycle_events(lifecycle_a.events(), applied_units=[unit_a])

    lifecycle_b = EpisodeConfigLifecycle()
    unit_b = ChangeUnit(
        target=Target.WORKER_PROMPT_STRATEGIST, origin=Origin.CORTEX, content="Note B"
    )
    lifecycle_b.propose(unit_b)
    lifecycle_b.apply_window(WINDOW_BEFORE_EPISODE_1)
    mapped_b = map_configlifecycle_events(lifecycle_b.events(), applied_units=[unit_b])

    assert config_digest_for(mapped_a) != config_digest_for(mapped_b)


# ---------------------------------------------------------------------------
# The mapper never invents a kind outside the honest vocabulary, ever
# (defensive sanity: every kind this module can realistically emit is a
# member of EVENT_KINDS, even the degraded/verified/reverted kinds this
# mapper never itself produces -- listed here so a future reader sees the
# full honest vocabulary the mapper is constrained to).
# ---------------------------------------------------------------------------


def test_every_mapped_kind_is_a_member_of_the_honest_vocabulary() -> None:
    lifecycle = EpisodeConfigLifecycle(catalog=_catalog(["read_file"]))
    lifecycle.propose(
        ChangeUnit(target=Target.WORKER_TOOLS, origin=Origin.CORTEX, tool_ids=["read_file"])
    )
    lifecycle.propose(
        ChangeUnit(target=Target.WORKER_TOOLS, origin=Origin.CORTEX, tool_ids=["missing"])
    )
    lifecycle.apply_window(WINDOW_BEFORE_EPISODE_1)
    lifecycle.end_episode()

    mapped = map_configlifecycle_events(lifecycle.events())

    for event in mapped:
        assert event.kind in EVENT_KINDS
    # Kinds this mapper never itself produces stay reachable only via other
    # producers (e.g. colleague.configurator appends verified/degraded
    # directly onto a ConfigEventStream) -- named here for documentation.
    assert {EVENT_KIND_VERIFIED, EVENT_KIND_DEGRADED, EVENT_KIND_REVERTED} <= set(EVENT_KINDS)
