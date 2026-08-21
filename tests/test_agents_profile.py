"""Tests for colleague/agents/profile.py (plan task t1).

Covers: the AgentProfile frozen dataclass + to_dict/from_dict round-trip, the
closed PURPOSES set, the PURPOSE_ROLE map, and resolve_profile's ready/fallback
semantics against a RoleInfo double mirroring the 2026-08-21 advert. Includes
the vendor-name grep guard over colleague/agents/.
"""

import re
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from colleague.agents.profile import (
    PURPOSE_ROLE,
    PURPOSES,
    SCHEMA_VERSION,
    AgentProfile,
    Resolution,
    resolve_profile,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = REPO_ROOT / "colleague" / "agents"


# ---------------------------------------------------------------------------
# RoleInfo / LobesRoles doubles mirroring the 2026-08-21 advert
# ---------------------------------------------------------------------------


class _RoleInfoDouble:
    """A RoleInfo double — the per-role fields resolve_profile reads."""

    def __init__(
        self,
        model,
        ready,
        context=0,
        endpoint="",
        path="",
        responsibilities=(),
        forbidden_responsibilities=(),
    ):
        self.model = model
        self.ready = ready
        self.context = context
        self.endpoint = endpoint
        self.path = path
        self.responsibilities = responsibilities
        self.forbidden_responsibilities = forbidden_responsibilities


class _RolesDouble:
    """A LobesRoles double — .cortex / .senses / .worker."""

    def __init__(self, cortex, senses, worker):
        self.cortex = cortex
        self.senses = senses
        self.worker = worker


def _advert_roles():
    """The 2026-08-21 advert: cortex ready, senses ready, worker NOT ready."""
    return _RolesDouble(
        cortex=_RoleInfoDouble("unsloth/Qwen3.8-27B-NVFP4", True, context=1048576),
        senses=_RoleInfoDouble("gemma-4-12B", True, context=32768),
        worker=_RoleInfoDouble("Nemotron-3.5-Lightning-30B-A3B", False, context=65536),
    )


def _make_profile(**overrides):
    base = dict(
        agent_id="agent-1",
        purpose="worker",
        model_role="cortex",
        resolved_model="unsloth/Qwen3.8-27B-NVFP4",
        tool_profile="worker",
        authority_profile="repo_patch_no_publish",
        parent_agent_id=None,
        task_id="task-1",
        fallback_from_role="worker",
    )
    base.update(overrides)
    return AgentProfile(**base)


# ---------------------------------------------------------------------------
# Closed set + role map
# ---------------------------------------------------------------------------


def test_purposes_is_closed_set():
    assert PURPOSES == frozenset({"talker", "worker", "thinker_coder"})


def test_purpose_role_map():
    assert PURPOSE_ROLE == {
        "talker": "senses",
        "worker": "worker",
        "thinker_coder": "cortex",
    }


# ---------------------------------------------------------------------------
# AgentProfile dataclass
# ---------------------------------------------------------------------------


def test_agent_profile_is_frozen():
    p = _make_profile()
    with pytest.raises(FrozenInstanceError):
        p.agent_id = "other"


def test_to_dict_has_all_fields():
    p = _make_profile()
    assert set(p.to_dict()) == {
        "agent_id",
        "purpose",
        "model_role",
        "resolved_model",
        "tool_profile",
        "authority_profile",
        "parent_agent_id",
        "task_id",
        "fallback_from_role",
        "schema_version",
    }


def test_to_dict_from_dict_round_trip():
    p = _make_profile()
    assert AgentProfile.from_dict(p.to_dict()) == p


def test_round_trip_preserves_none_fields():
    p = _make_profile(parent_agent_id=None, fallback_from_role=None)
    assert AgentProfile.from_dict(p.to_dict()) == p


def test_profile_rejects_unknown_purpose():
    with pytest.raises(ValueError):
        _make_profile(purpose="bogus")


def test_schema_version_defaults():
    p = _make_profile()
    assert p.schema_version == SCHEMA_VERSION


# ---------------------------------------------------------------------------
# resolve_profile
# ---------------------------------------------------------------------------


def test_resolve_ready_role_no_fallback():
    roles = _RolesDouble(
        cortex=_RoleInfoDouble("cortex-model", True),
        senses=_RoleInfoDouble("senses-model", True),
        worker=_RoleInfoDouble("worker-model", True),
    )
    r = resolve_profile("worker", roles)
    assert r == Resolution(model_role="worker", resolved_model="worker-model")
    assert r.fallback_from_role is None


def test_resolve_fallback_when_role_not_ready():
    # The 2026-08-21 advert: worker is advertised but NOT ready.
    r = resolve_profile("worker", _advert_roles())
    assert r.model_role == "cortex"
    assert r.resolved_model == "unsloth/Qwen3.8-27B-NVFP4"
    assert r.fallback_from_role == "worker"


def test_resolve_fallback_when_role_absent():
    roles = _RolesDouble(
        cortex=_RoleInfoDouble("cortex-model", True),
        senses=_RoleInfoDouble("senses-model", True),
        worker=None,
    )
    r = resolve_profile("worker", roles)
    assert r.model_role == "cortex"
    assert r.resolved_model == "cortex-model"
    assert r.fallback_from_role == "worker"


def test_resolve_talker_uses_senses_when_ready():
    r = resolve_profile("talker", _advert_roles())
    assert r.model_role == "senses"
    assert r.resolved_model == "gemma-4-12B"
    assert r.fallback_from_role is None


def test_resolve_talker_falls_back_when_senses_not_ready():
    roles = _RolesDouble(
        cortex=_RoleInfoDouble("cortex-model", True),
        senses=_RoleInfoDouble("senses-model", False),
        worker=None,
    )
    r = resolve_profile("talker", roles)
    assert r.model_role == "cortex"
    assert r.resolved_model == "cortex-model"
    assert r.fallback_from_role == "senses"


def test_resolve_thinker_coder_uses_cortex():
    r = resolve_profile("thinker_coder", _advert_roles())
    assert r.model_role == "cortex"
    assert r.resolved_model == "unsloth/Qwen3.8-27B-NVFP4"
    assert r.fallback_from_role is None


def test_resolve_unknown_purpose_raises():
    with pytest.raises(ValueError):
        resolve_profile("bogus", _advert_roles())


def test_resolve_is_pure_and_deterministic():
    # Same inputs → same outputs, repeated (no hidden state, no I/O).
    a = resolve_profile("worker", _advert_roles())
    b = resolve_profile("worker", _advert_roles())
    assert a == b


# ---------------------------------------------------------------------------
# Vendor-name grep guard
# ---------------------------------------------------------------------------


def test_no_vendor_model_names_under_agents():
    pattern = re.compile(r"gemma|qwen|nemotron|lightning", re.IGNORECASE)
    offenders = []
    for path in sorted(AGENTS_DIR.rglob("*.py")):
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            if pattern.search(text):
                offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, f"vendor model names found under colleague/agents/: {offenders}"
