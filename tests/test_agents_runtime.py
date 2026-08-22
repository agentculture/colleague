"""Tests for colleague/agents/runtime.py (plan task t9).

Covers: the InvocationRecord identity + context manifest (to_dict round-trip,
the closed token_estimate_source vocabulary, and the guarantee that
token_estimate is NEVER written into the ledger event / Usage), the ONE agent
seat builder agent_engine_config (context budget follows the role advert,
refresh_seat/on_delta cleared, #348 same-origin api_key hygiene, the
recorded-fallback degrade when a role is absent), estimate_tokens (engine
counter labelled "tokenize" vs the chars fallback), and append_invocation
('invocation' events on the t4 task ledger; the record's ledger_digest
matches derive_snapshot's replay).

The lobes advert double mirrors the 2026-08-21 re-probe: cortex ready at
1,048,576; senses ready at 32,768; worker NOT ready at 65,536. No network.
"""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from colleague.agents.profile import AgentProfile, resolve_profile
from colleague.agents.runtime import (
    TOKEN_ESTIMATE_SOURCES,
    InvocationRecord,
    agent_engine_config,
    append_invocation,
    estimate_tokens,
)
from colleague.agents.state.ledger import TaskLedger, derive_snapshot, read_ledger
from colleague.agents.tools import tool_surface_digest
from colleague.config import EngineConfig
from colleague.lobes import RoleInfo

# ---------------------------------------------------------------------------
# The 2026-08-21 advert double (cortex ready 1048576; worker ready:false)
# ---------------------------------------------------------------------------


def _role(model: str, ready: bool, context: int, endpoint: str = "") -> RoleInfo:
    return RoleInfo(
        model=model,
        endpoint=endpoint,
        path="/v1",
        context=context,
        ready=ready,
        responsibilities=(),
        forbidden_responsibilities=(),
    )


def _advert_roles() -> SimpleNamespace:
    """The saved 2026-08-21 advert: cortex ready, senses ready, worker NOT ready."""
    return SimpleNamespace(
        cortex=_role("cortex-model", True, 1048576),
        senses=_role("senses-model", True, 32768),
        worker=_role("worker-model", False, 65536),
    )


def _parent_config() -> EngineConfig:
    return EngineConfig(
        base_url="http://localhost:8001/v1",
        api_key="parent-key",
        model="cortex-model",
        context_budget_tokens=131072,
        lobes_gateway_url="http://localhost:8001",
    )


def _worker_profile(roles) -> AgentProfile:
    """A worker-purpose profile resolved against *roles* (the recorded fallback)."""
    res = resolve_profile("worker", roles)
    return AgentProfile(
        agent_id="agent-1",
        purpose="worker",
        model_role=res.model_role,
        resolved_model=res.resolved_model,
        tool_profile="worker",
        authority_profile="repo_patch_no_publish",
        parent_agent_id=None,
        task_id="task-1",
        fallback_from_role=res.fallback_from_role,
    )


def _record(profile: AgentProfile, **overrides) -> InvocationRecord:
    base = dict(
        agent_id=profile.agent_id,
        purpose=profile.purpose,
        model_role=profile.model_role,
        resolved_model=profile.resolved_model,
        fallback_from_role=profile.fallback_from_role,
        tool_surface_digest=tool_surface_digest(["read_file", "list_dir", "run_tests", "finish"]),
        ledger_digest="0" * 64,
        nucleus_refs=("task:task-1",),
        working_set_refs=("path:colleague/agents/runtime.py",),
        retrieved_memory_refs=("recall:1",),
        peer_message_refs=("msg-1",),
        token_estimate=1234,
        token_estimate_source="chars",
        truncated=False,
        parent_agent_id=profile.parent_agent_id,
        delegation_id=None,
        seq=0,
    )
    base.update(overrides)
    return InvocationRecord(**base)


# ---------------------------------------------------------------------------
# InvocationRecord
# ---------------------------------------------------------------------------


def test_token_estimate_sources_is_closed():
    assert TOKEN_ESTIMATE_SOURCES == ("tokenize", "chars")


def test_record_to_dict_has_all_fields():
    rec = _record(_worker_profile(_advert_roles()))
    assert set(rec.to_dict()) == {
        "agent_id",
        "purpose",
        "model_role",
        "resolved_model",
        "fallback_from_role",
        "tool_surface_digest",
        "ledger_digest",
        "nucleus_refs",
        "working_set_refs",
        "retrieved_memory_refs",
        "peer_message_refs",
        "token_estimate",
        "token_estimate_source",
        "truncated",
        "parent_agent_id",
        "delegation_id",
        "seq",
    }


def test_record_round_trip():
    rec = _record(_worker_profile(_advert_roles()))
    assert InvocationRecord.from_dict(rec.to_dict()) == rec


def test_record_refuses_unknown_estimate_source():
    profile = _worker_profile(_advert_roles())
    with pytest.raises(ValueError, match="token_estimate_source"):
        _record(profile, token_estimate_source="guess")


# ---------------------------------------------------------------------------
# agent_engine_config — the ONE agent seat builder
# ---------------------------------------------------------------------------


def test_worker_profile_resolves_to_cortex_with_recorded_fallback():
    """The 2026-08-21 advert double: worker not ready -> the purpose is carried
    on the cortex model under a RECORDED fallback, and the seat builder
    resolves to the cortex model with the fallback on the record."""
    roles = _advert_roles()
    profile = _worker_profile(roles)
    assert profile.model_role == "cortex"
    assert profile.resolved_model == "cortex-model"
    assert profile.fallback_from_role == "worker"

    seat = agent_engine_config(_parent_config(), profile, roles)
    assert seat.model == "cortex-model"
    assert seat.refresh_seat is None
    assert seat.on_delta is None
    # The record carries the fallback.
    rec = _record(profile)
    assert rec.fallback_from_role == "worker"
    assert rec.model_role == "cortex"
    assert rec.resolved_model == "cortex-model"


def test_context_budget_follows_the_role_advert():
    """cortex 1,048,576 per the 2026-08-21 re-probe; worker 65,536 when ready —
    the bigger sliding window is intended."""
    roles = _advert_roles()
    profile = _worker_profile(roles)  # carried on cortex
    seat = agent_engine_config(_parent_config(), profile, roles)
    assert seat.context_budget_tokens == 1048576

    ready_roles = SimpleNamespace(
        cortex=roles.cortex,
        senses=roles.senses,
        worker=_role("worker-model", True, 65536),
    )
    res = resolve_profile("worker", ready_roles)
    assert res.fallback_from_role is None
    ready_profile = AgentProfile(
        agent_id="agent-2",
        purpose="worker",
        model_role=res.model_role,
        resolved_model=res.resolved_model,
        tool_profile="worker",
        authority_profile="repo_patch_no_publish",
        parent_agent_id=None,
        task_id="task-1",
        fallback_from_role=res.fallback_from_role,
    )
    seat2 = agent_engine_config(_parent_config(), ready_profile, ready_roles)
    assert seat2.model == "worker-model"
    assert seat2.context_budget_tokens == 65536


def test_seat_clears_on_delta_and_inherits_other_knobs():
    parent = replace(_parent_config(), on_delta=lambda s: None, max_steps=42)
    seat = agent_engine_config(parent, _worker_profile(_advert_roles()), _advert_roles())
    assert seat.on_delta is None
    assert seat.max_steps == 42
    assert seat.timeout == parent.timeout


def test_api_key_hygiene_same_origin_inherits_parent_key():
    """#348: the parent's key is inherited only toward the parent's own origin.
    An unwired role (empty endpoint) dials the gateway origin — same origin as
    the parent here — so the key is inherited."""
    roles = _advert_roles()
    seat = agent_engine_config(_parent_config(), _worker_profile(roles), roles)
    assert seat.base_url == "http://localhost:8001"
    assert seat.api_key == "parent-key"


def test_api_key_hygiene_cross_origin_never_inherits_parent_key():
    """A role advertising a cross-origin endpoint gets None — the parent's
    Bearer token is never forwarded to a host a wire payload advertised."""
    roles = _advert_roles()
    cross = SimpleNamespace(
        cortex=_role("cortex-model", True, 1048576, endpoint="http://rig2:8001/v1"),
        senses=roles.senses,
        worker=roles.worker,
    )
    seat = agent_engine_config(_parent_config(), _worker_profile(cross), cross)
    assert seat.base_url == "http://rig2:8001/v1"
    assert seat.api_key is None


def test_absent_role_degrades_to_profile_trace_data():
    """A role the gateway did not advertise (associate today) degrades to the
    profile's own trace data — never a refusal, never the parent's key."""
    roles = _advert_roles()  # no .associate attribute at all
    res = resolve_profile("associate", roles)
    assert res.model_role == "cortex"
    assert res.fallback_from_role == "associate"
    profile = AgentProfile(
        agent_id="agent-3",
        purpose="associate",
        model_role=res.model_role,
        resolved_model=res.resolved_model,
        tool_profile="associate",
        authority_profile="repo_patch_no_publish",
        parent_agent_id=None,
        task_id="task-1",
        fallback_from_role=res.fallback_from_role,
    )
    seat = agent_engine_config(_parent_config(), profile, roles)
    assert seat.model == "cortex-model"
    assert seat.context_budget_tokens == 1048576


# ---------------------------------------------------------------------------
# estimate_tokens — the engine's counter when available, else chars
# ---------------------------------------------------------------------------


class _EngineWithCounter:
    def make_count_tokens(self, config):
        def counter(messages):
            return 777

        return counter


def test_estimate_uses_engine_counter_and_labels_tokenize():
    est, source = estimate_tokens(
        _EngineWithCounter(), _parent_config(), [{"role": "user", "content": "hi"}]
    )
    assert (est, source) == (777, "tokenize")


def test_estimate_falls_back_to_chars_when_engine_has_no_counter():
    est, source = estimate_tokens(None, _parent_config(), [{"role": "user", "content": "x" * 40}])
    assert source == "chars"
    assert est == 10  # 40 chars / 4


def test_estimate_degrades_to_chars_when_the_counter_raises():
    class _Broken:
        def make_count_tokens(self, config):
            raise RuntimeError("no /tokenize")

    est, source = estimate_tokens(
        _Broken(), _parent_config(), [{"role": "user", "content": "x" * 40}]
    )
    assert (est, source) == (10, "chars")


# ---------------------------------------------------------------------------
# append_invocation — 'invocation' events on the t4 task ledger
# ---------------------------------------------------------------------------


def test_append_invocation_assigns_seq_and_replayed_digest(tmp_path: Path):
    roles = _advert_roles()
    profile = _worker_profile(roles)
    ledger = TaskLedger(tmp_path / "task-1.jsonl", task_id="task-1")
    ledger.append("operator_request", {"ref": "brief.md", "text": "do the thing"})

    rec = _record(profile)
    appended = append_invocation(ledger, rec)

    # The ledger-assigned seq and the digest of the state AFTER the append —
    # what derive_snapshot replays.
    assert appended.seq == 1
    snapshot = derive_snapshot(ledger.events())
    assert appended.ledger_digest == snapshot.state_digest
    # The input record is frozen and untouched.
    assert rec.seq == 0
    assert rec.ledger_digest == "0" * 64
    # The invocation event counts as an episode on replay.
    assert snapshot.episode == 1


def test_token_estimate_is_never_written_into_the_ledger_or_usage(tmp_path: Path):
    """The 'invocation' event carries identity + manifest refs/digests only —
    token_estimate is a pre-send sizing figure: it never lands in the ledger
    (and therefore never in Usage, which is exact accounting only)."""
    roles = _advert_roles()
    profile = _worker_profile(roles)
    ledger = TaskLedger(tmp_path / "task-1.jsonl", task_id="task-1")
    appended = append_invocation(ledger, _record(profile, token_estimate=9999))

    event = ledger.events()[-1]
    assert event.kind == "invocation"
    assert "token_estimate" not in event.data
    assert "token_estimate_source" not in event.data
    # The manifest fields the event DOES carry match the record.
    assert event.data["agent_id"] == profile.agent_id
    assert event.data["purpose"] == "worker"
    assert event.data["model_role"] == "cortex"
    assert event.data["resolved_model"] == "cortex-model"
    assert event.data["fallback_from_role"] == "worker"
    assert event.data["tool_surface_digest"] == _record(profile).tool_surface_digest
    assert event.data["nucleus_refs"] == list(_record(profile).nucleus_refs)
    assert event.data["working_set_refs"] == list(_record(profile).working_set_refs)
    assert event.data["retrieved_memory_refs"] == list(_record(profile).retrieved_memory_refs)
    assert event.data["peer_message_refs"] == list(_record(profile).peer_message_refs)
    assert event.data["truncated"] is False
    assert event.data["parent_agent_id"] is None
    assert event.data["delegation_id"] is None
    # The record itself still carries the estimate (artifact-side, not Usage).
    assert appended.token_estimate == 9999
    assert appended.token_estimate_source == "chars"


# ---------------------------------------------------------------------------
# reasoning_effort as trace data (#416 t7, c29/h20)
# ---------------------------------------------------------------------------


def test_record_to_dict_omits_reasoning_effort_when_unset():
    """Byte-identical to before this field existed when no rung is set."""
    rec = _record(_worker_profile(_advert_roles()))
    assert rec.reasoning_effort is None
    assert "reasoning_effort" not in rec.to_dict()


def test_record_to_dict_carries_reasoning_effort_when_set():
    rec = _record(_worker_profile(_advert_roles()), reasoning_effort="medium")
    assert rec.to_dict()["reasoning_effort"] == "medium"


def test_record_round_trip_with_reasoning_effort_set():
    rec = _record(_worker_profile(_advert_roles()), reasoning_effort="xhigh")
    assert InvocationRecord.from_dict(rec.to_dict()) == rec


def test_from_dict_tolerates_absent_reasoning_effort():
    rec = _record(_worker_profile(_advert_roles()))
    raw = rec.to_dict()
    assert "reasoning_effort" not in raw
    assert InvocationRecord.from_dict(raw).reasoning_effort is None


def test_append_invocation_omits_reasoning_effort_from_event_when_unset(tmp_path: Path):
    roles = _advert_roles()
    profile = _worker_profile(roles)
    ledger = TaskLedger(tmp_path / "task-1.jsonl", task_id="task-1")
    append_invocation(ledger, _record(profile))
    event = ledger.events()[-1]
    assert "reasoning_effort" not in event.data


def test_append_invocation_carries_reasoning_effort_on_event_when_set(tmp_path: Path):
    roles = _advert_roles()
    profile = _worker_profile(roles)
    ledger = TaskLedger(tmp_path / "task-1.jsonl", task_id="task-1")
    append_invocation(ledger, _record(profile, reasoning_effort="low"))
    event = ledger.events()[-1]
    assert event.data["reasoning_effort"] == "low"


def test_ledger_digest_stable_for_records_without_reasoning_effort(tmp_path: Path):
    """Adding the reasoning_effort field never moves the digest of a ledger
    that never sets it — an unset/unarmed ledger stays byte-identical."""
    roles = _advert_roles()
    profile = _worker_profile(roles)

    ledger_a = TaskLedger(tmp_path / "a.jsonl", task_id="task-1")
    append_invocation(ledger_a, _record(profile))
    digest_a = derive_snapshot(ledger_a.events()).state_digest

    ledger_b = TaskLedger(tmp_path / "b.jsonl", task_id="task-1")
    append_invocation(ledger_b, _record(profile, reasoning_effort=None))
    digest_b = derive_snapshot(ledger_b.events()).state_digest

    assert digest_a == digest_b


def test_ledger_digest_moves_when_reasoning_effort_is_set(tmp_path: Path):
    roles = _advert_roles()
    profile = _worker_profile(roles)

    ledger_unset = TaskLedger(tmp_path / "unset.jsonl", task_id="task-1")
    append_invocation(ledger_unset, _record(profile))
    digest_unset = derive_snapshot(ledger_unset.events()).state_digest

    ledger_set = TaskLedger(tmp_path / "set.jsonl", task_id="task-1")
    append_invocation(ledger_set, _record(profile, reasoning_effort="medium"))
    digest_set = derive_snapshot(ledger_set.events()).state_digest

    assert digest_unset != digest_set


def test_effort_of_reads_seat_override_before_effective():
    from colleague.effort import effort_of

    cfg = replace(_parent_config(), reasoning_effort=None)
    setattr(cfg, "reasoning_effort_seat", "xhigh")
    assert effort_of(cfg) == "xhigh"


def test_effort_of_falls_back_to_effective_when_seat_override_absent():
    from colleague.effort import effort_of

    cfg = _parent_config()
    assert not hasattr(cfg, "reasoning_effort_seat")
    assert effort_of(cfg) == cfg.reasoning_effort_effective


def test_record_invocation_reads_reasoning_effort_off_the_seat_config(tmp_path: Path):
    """AgentsRun.record_invocation reads the value off self.config at record
    time (the ONE record site in agents/runtime.py) — never recomputed from
    SEAT_TABLE/ROLE_TABLE."""
    from colleague.agents.runtime import AgentsRun
    from colleague.contract import Task

    repo = tmp_path / "repo"
    repo.mkdir()
    cfg = _parent_config()
    setattr(cfg, "reasoning_effort_seat", "high")
    task = Task.new(str(repo), "do the thing")

    run = AgentsRun(cfg)
    run.begin(task, model=cfg.model)
    rec = run.record_invocation([{"role": "user", "content": "hi"}])

    assert rec is not None
    assert rec.reasoning_effort == "high"
    event = run.ledger.events()[-1]
    assert event.data["reasoning_effort"] == "high"


def test_record_invocation_omits_reasoning_effort_when_config_has_none(tmp_path: Path):
    from colleague.agents.runtime import AgentsRun
    from colleague.contract import Task

    repo = tmp_path / "repo"
    repo.mkdir()
    cfg = _parent_config()
    assert not hasattr(cfg, "reasoning_effort_seat")
    task = Task.new(str(repo), "do the thing")

    run = AgentsRun(cfg)
    run.begin(task, model=cfg.model)
    rec = run.record_invocation([{"role": "user", "content": "hi"}])

    assert rec is not None
    assert rec.reasoning_effort == cfg.reasoning_effort_effective
    event = run.ledger.events()[-1]
    if cfg.reasoning_effort_effective is None:
        assert "reasoning_effort" not in event.data
    else:
        assert event.data["reasoning_effort"] == cfg.reasoning_effort_effective


def test_ledger_round_trip_with_invocation(tmp_path: Path):
    roles = _advert_roles()
    profile = _worker_profile(roles)
    ledger = TaskLedger(tmp_path / "task-1.jsonl", task_id="task-1")
    append_invocation(ledger, _record(profile, truncated=True, delegation_id="sub/agent-1"))

    read = read_ledger(ledger.path)
    assert read.task_id == "task-1"
    assert [e.kind for e in read.events] == ["invocation"]
    assert read.events[0].data["truncated"] is True
    assert read.events[0].data["delegation_id"] == "sub/agent-1"
    # The snapshot's digest is what the appended record names.
    assert read.snapshot.state_digest == derive_snapshot(read.events).state_digest
