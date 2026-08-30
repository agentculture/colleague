"""#411 t2 — tool profiles, purpose surfaces, the six-way intersection and its digest."""

from __future__ import annotations

import dataclasses
import hashlib

import pytest

from colleague import purpose_schemas, roles, tae_loop, tools
from colleague.agents import tools as agent_tools
from colleague.agents.profile import PURPOSES
from colleague.agents.tools import (
    ASSOCIATE_TOOLS,
    PURPOSE_TOOLS,
    TALKER_TOOLS,
    THINKER_CODER_TOOLS,
    TOOL_CLASSES,
    TOOL_PROFILES,
    WORKER_TOOLS,
    EmptyToolSurface,
    ToolProfile,
    effective_tools,
    profile_for,
    tool_surface_digest,
    tools_for_purpose,
)

_FULL = set(tools.TOOL_NAMES)
#: The six purpose tools (plan t5) — spliced onto CANONICAL_TOOLS/THINKER_CODER_TOOLS
#: the same way DEEPTHINK is, never folded into ``tools.TOOL_NAMES`` itself.
_PURPOSES = set(purpose_schemas.PURPOSE_TOOL_NAMES)


def test_every_registry_tool_plus_deepthink_has_a_profile() -> None:
    # t5: the six purpose tools (web_survey/code_survey/review/validate/plan/
    # handover_to_colleague) join deepthink as profiled-but-outside-SCHEMAS names.
    assert set(TOOL_PROFILES) == _FULL | {"deepthink"} | _PURPOSES
    for name, prof in TOOL_PROFILES.items():
        assert prof.canonical_id == name
        assert prof.tool_class in TOOL_CLASSES


def test_tool_class_reconciles_roles_write_set_and_tae_consequential_set() -> None:
    reconciled = set(roles._WRITE_TOOLS) | set(tae_loop.CONSEQUENTIAL_TOOLS)
    assert {n for n, p in TOOL_PROFILES.items() if p.tool_class == "write"} == reconciled
    assert {n for n, p in TOOL_PROFILES.items() if p.tool_class == "external"} == {
        "culture",
        "devague",
    }
    assert not [n for n, p in TOOL_PROFILES.items() if p.tool_class == "destructive"]
    for name in roles._READONLY_TOOLS:
        assert TOOL_PROFILES[name].tool_class == "read"


def test_approval_and_inheritance_flags() -> None:
    assert profile_for("run_command").required_approval is True
    assert not any(p.required_approval for n, p in TOOL_PROFILES.items() if n != "run_command")
    for spawner in ("subagent", "subagents", "deepthink", *_PURPOSES):
        assert profile_for(spawner).inheritable is False
    assert profile_for("read_file").inheritable
    assert profile_for("write_file").inheritable
    with pytest.raises(KeyError):
        profile_for("not_a_tool")
    with pytest.raises(ValueError):
        ToolProfile("x", "magic", False, True)


def test_worker_profile_has_no_generic_code_authoring_tools() -> None:
    # t5: subagent/subagents leave the worker's surface, replaced BY PURPOSE.
    assert "write_file" not in WORKER_TOOLS
    assert "edit_file" not in WORKER_TOOLS
    assert "subagent" not in WORKER_TOOLS
    assert "subagents" not in WORKER_TOOLS
    assert {
        "read_file",
        "view_media",
        "list_dir",
        "run_tests",
        "run_command",
        "memory",
        "finish",
    } | _PURPOSES <= WORKER_TOOLS
    assert WORKER_TOOLS < THINKER_CODER_TOOLS


def test_talker_is_empty_thinker_is_full_associate_is_coder_class() -> None:
    assert TALKER_TOOLS == frozenset()
    # t5: THINKER_CODER_TOOLS is the registry surface minus web/subagent/subagents
    # (replaced BY PURPOSE, operator decisions q9/q10), plus the six purposes.
    # ARM 4 (plan t11) briefly restored the raw pair here; the arm matrix
    # measured zero raw-pair calls in 21 runs, so the reversal was rejected.
    assert THINKER_CODER_TOOLS == frozenset(_FULL - {"web", "subagent", "subagents"}) | _PURPOSES
    assert ASSOCIATE_TOOLS == THINKER_CODER_TOOLS
    assert set(PURPOSE_TOOLS) == set(PURPOSES)
    assert tools_for_purpose("worker") is WORKER_TOOLS
    with pytest.raises(KeyError):
        tools_for_purpose("oracle")


def test_effective_tools_is_the_sorted_intersection_and_never_adds() -> None:
    full = _FULL | _PURPOSES
    eff = effective_tools(
        available=full,
        model_supported=full,
        purpose_tools=WORKER_TOOLS,
        policy_tools=full - {"run_command"},
        env_tools=full,
        approved_tools=full,
    )
    assert eff == tuple(sorted(WORKER_TOOLS - {"run_command"}))
    assert set(eff) <= WORKER_TOOLS
    assert "write_file" not in eff
    # narrowing any dimension can only shrink
    smaller = effective_tools(full, full, WORKER_TOOLS, {"read_file"}, full, full)
    assert smaller == ("read_file",)
    # an extra name in one dimension never appears in the result
    assert "write_file" not in effective_tools(
        full, full, WORKER_TOOLS, full | {"magic"}, full, full
    )


def test_empty_intersection_refuses_whole() -> None:
    with pytest.raises(EmptyToolSurface):
        effective_tools(_FULL, _FULL, TALKER_TOOLS, _FULL, _FULL, _FULL)
    with pytest.raises(EmptyToolSurface):
        effective_tools(_FULL, {"write_file"}, WORKER_TOOLS, _FULL, _FULL, _FULL)


def test_digest_is_sorted_stable_and_order_insensitive() -> None:
    a = tool_surface_digest(["read_file", "finish", "list_dir"])
    b = tool_surface_digest(("list_dir", "read_file", "finish", "finish"))
    assert a == b
    assert a == hashlib.sha256(b"finish\nlist_dir\nread_file").hexdigest()
    assert tool_surface_digest(WORKER_TOOLS) != tool_surface_digest(THINKER_CODER_TOOLS)


def test_web_profile_is_read_no_approval_inheritable() -> None:
    """t4: 'web' classifies exactly like every other pure-read tool — no code
    branch singles it out, it falls straight out of ``_classify``'s default."""
    assert TOOL_PROFILES["web"] == ToolProfile(
        "web", "read", required_approval=False, inheritable=True
    )
    assert profile_for("web").tool_class == "read"


def test_assert_purpose_surface_still_refuses_talker_write_capable() -> None:
    # A write-capable class ('write', 'external', 'destructive') still refuses
    # for the talker even with 'web' (a 'read' class) newly in the mix.
    with pytest.raises(ValueError):
        agent_tools.assert_purpose_surface("talker", {"web", "write_file"})
    with pytest.raises(ValueError):
        agent_tools.assert_purpose_surface("talker", {"web", "devague"})
    # 'web' alone is read-only — never refused for the talker.
    agent_tools.assert_purpose_surface("talker", {"web"})
    # Every other purpose passes through unchanged, 'web' included.
    agent_tools.assert_purpose_surface("worker", {"web", "write_file"})


def test_scout_bound_child_gets_web_only_when_parent_surface_has_it() -> None:
    """SUPERSEDED for a purpose-tool delegation by purpose-tools-associate-seat
    (q3, colleague/agents/delegation.py's ``purpose`` exemption — see
    docs/specs/2026-08-28-purpose-tools-associate-seat.md); still the rule for
    a MANUAL ``subagent``/``subagents`` scout delegation, which this test pins
    unchanged: a scout-bound child's effective surface is the intersection
    with the PARENT's own surface (t4, c12/h10) — 'web' never appears in the
    child's tools unless the parent's surface already carried it, mirroring
    the ⊆-by-construction guarantee ``effective_tools`` already provides."""
    scout_tools = frozenset(roles.BUILTIN_ROLES["scout"].tool_allowlist)
    assert "web" in scout_tools  # scout's own curated surface offers it

    # Parent surface WITHOUT 'web' -> a MANUAL scout child's effective tools
    # (no ``purpose`` flag) exclude it.
    parent_without_web = scout_tools - {"web"}
    child = effective_tools(
        available=parent_without_web,
        model_supported=scout_tools,
        purpose_tools=scout_tools,
        policy_tools=scout_tools,
        env_tools=scout_tools,
        approved_tools=scout_tools,
    )
    assert "web" not in child
    assert set(child) <= parent_without_web

    # Parent surface WITH 'web' -> child may get it (still an intersection).
    child_with_web = effective_tools(
        available=scout_tools,
        model_supported=scout_tools,
        purpose_tools=scout_tools,
        policy_tools=scout_tools,
        env_tools=scout_tools,
        approved_tools=scout_tools,
    )
    assert "web" in child_with_web
    assert set(child_with_web) <= scout_tools

    # NEW RULE (q3): a delegation FLAGGED with a purpose tool's name is exempt
    # from the parent-surface ⊆ check entirely — 'code_survey' on a parent
    # WITHOUT 'web' still validates, because the purpose tool's child surface
    # is FIXED (the role allow-list ∩ environment), never requested from the
    # parent. The same request unflagged (a manual delegation) still refuses.
    from colleague.agents.delegation import DelegationRequest, validate_delegation

    purpose_req = DelegationRequest(
        delegation_id="",
        from_agent="thinker_coder",
        requested_agent_profile="scout",
        objective="survey",
        acceptance="",
        requested_tools=tuple(sorted(scout_tools)),  # includes 'web'
        purpose="code_survey",
    )
    verdict = validate_delegation(
        purpose_req,
        parent_effective_tools=parent_without_web,
        parent_ceiling="read_only",
    )
    assert verdict.allowed is True

    manual_req = dataclasses.replace(purpose_req, purpose=None)
    verdict = validate_delegation(
        manual_req,
        parent_effective_tools=parent_without_web,
        parent_ceiling="read_only",
    )
    assert verdict.allowed is False
    assert "web" in (verdict.reason or "")


def test_module_is_pure() -> None:
    src = open(agent_tools.__file__, encoding="utf-8").read()
    for banned in (
        "import subprocess",
        "import threading",
        "from colleague import loop",
        "colleague.engines",
    ):
        assert banned not in src


# ---------------------------------------------------------------------------
# Hire confinement (delegation-follow-ups t11, c37/h21): the hire pair joins
# the coder-class purpose surfaces ONLY when COLLEAGUE_HIRE arms it, is never
# inheritable, and can never sit on a talker.
# ---------------------------------------------------------------------------


def _hire_names() -> frozenset:
    from colleague.hire_schemas import HIRE_TOOL_NAMES

    return frozenset(HIRE_TOOL_NAMES)


def test_hire_pair_absent_from_purpose_sets_by_default() -> None:
    # The scrubbed default env (no COLLEAGUE_HIRE): byte-identical to #443.
    assert THINKER_CODER_TOOLS.isdisjoint(_hire_names())
    assert ASSOCIATE_TOOLS.isdisjoint(_hire_names())
    assert WORKER_TOOLS.isdisjoint(_hire_names())
    assert TALKER_TOOLS == frozenset()


def test_hire_pair_joins_coder_sets_only_when_knob_armed(monkeypatch) -> None:
    """COLLEAGUE_AGENTS=1 + COLLEAGUE_HIRE=1 → both names in
    THINKER_CODER_TOOLS/ASSOCIATE_TOOLS; COLLEAGUE_AGENTS=1 alone → neither."""
    import importlib

    names = _hire_names()
    try:
        monkeypatch.setenv("COLLEAGUE_AGENTS", "1")
        monkeypatch.setenv("COLLEAGUE_HIRE", "1")
        armed = importlib.reload(agent_tools)
        assert names <= armed.THINKER_CODER_TOOLS
        assert names <= armed.ASSOCIATE_TOOLS
        assert armed.ASSOCIATE_TOOLS == armed.THINKER_CODER_TOOLS
        # Only the coder-class seats gain it — never the worker or the talker.
        assert armed.WORKER_TOOLS.isdisjoint(names)
        assert armed.TALKER_TOOLS == frozenset()

        monkeypatch.delenv("COLLEAGUE_HIRE")
        unarmed = importlib.reload(agent_tools)
        assert unarmed.THINKER_CODER_TOOLS.isdisjoint(names)
        assert unarmed.ASSOCIATE_TOOLS.isdisjoint(names)
    finally:
        monkeypatch.undo()
        importlib.reload(agent_tools)


def test_hire_pair_is_never_inheritable() -> None:
    # Unconditional deny-list membership: armed or not, a delegated child can
    # never inherit either name.
    assert _hire_names() <= agent_tools._NOT_INHERITABLE


def test_validate_profile_tools_refuses_a_talker_holding_a_hire_tool() -> None:
    from colleague.agents.profile import AgentProfile, validate_profile_tools

    profile = AgentProfile(
        agent_id="talker-hire",
        purpose="talker",
        model_role="senses",
        resolved_model="served-senses",
        tool_profile="talker",
        authority_profile="present",
        parent_agent_id=None,
        task_id="task-11",
        fallback_from_role=None,
    )
    for name in sorted(_hire_names()):
        with pytest.raises(ValueError, match="talker profile refuses"):
            validate_profile_tools(profile, [name])
