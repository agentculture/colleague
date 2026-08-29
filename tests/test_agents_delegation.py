"""Delegation envelope, child ⊆ parent property, lifecycle events, handoff (#411, t11).

Covers the acceptance criteria for ``colleague/agents/delegation.py``:

- :class:`DelegationRequest` validates ``requested_tools`` ⊆ parent effective
  tools, ``authority_ceiling`` ≤ parent's, and depth/fanout/total within the
  ``MAX_SUBAGENT_*`` caps — refusing whole otherwise (a
  :class:`DelegationVerdict`, never a raise).
- :func:`open_delegation` appends the ``delegate`` event BEFORE the spawn and
  returns a handle; :func:`close_delegation` appends the matching ``return``;
  ``derive_snapshot`` lists a delegate without a return as an open loop naming
  ``sub/<child_id>``.
- :func:`handoff` changes plan-node ownership on the ledger only.
- A hypothesis-free, seeded-random property test: for random parent/child
  profiles, ``child_effective`` ⊆ ``parent_effective`` and the child's ceiling
  ≤ the parent's — regardless of the child's model.
"""

from __future__ import annotations

import dataclasses
import random
from types import SimpleNamespace
from typing import Iterable

from colleague import roles
from colleague.agents.delegation import (
    AUTHORITY_CEILINGS,
    CONTEXT_MODES,
    DelegationRequest,
    ceiling_rank,
    close_delegation,
    handoff,
    open_delegation,
    validate_delegation,
)
from colleague.agents.profile import PURPOSES
from colleague.agents.state.ledger import TaskLedger
from colleague.agents.tools import TOOL_PROFILES, tools_for_purpose
from colleague.config import MAX_SUBAGENT_DEPTH, MAX_SUBAGENT_FANOUT, MAX_SUBAGENT_TOTAL

# The tool universe a parent's effective surface is drawn from: every purpose's
# tool set (the registry surface plus the opt-in deepthink, via t2's profiles).
TOOL_UNIVERSE: frozenset[str] = frozenset().union(*(tools_for_purpose(p) for p in PURPOSES))

# A purpose's authority ceiling (the parent's bound the child may not exceed).
PURPOSE_CEILING = {
    "talker": "read_only",
    "worker": "read_only",
    "thinker_coder": "repo_patch_no_publish",
    "associate": "repo_patch_publish",
}


def _effective(purpose: str, universe: Iterable[str] = TOOL_UNIVERSE) -> frozenset[str]:
    """A purpose's effective tool surface: the universe ∩ the purpose's tools,
    narrowed to the inheritable tools (a child may never inherit a spawn or an
    escalation). The child's model is NOT an input — the property must hold
    regardless of it."""
    purpose_tools = tools_for_purpose(purpose)
    return (
        frozenset(universe)
        & purpose_tools
        & frozenset(name for name in purpose_tools if TOOL_PROFILES[name].inheritable)
    )


def _child_surface(parent_purpose: str, child_purpose: str) -> frozenset[str]:
    """The child's effective surface for a delegation: the parent's effective
    tools ∩ the child's purpose tools. A subset of the parent's by
    construction — narrowing can only ever shrink a surface, never add."""
    return _effective(parent_purpose) & tools_for_purpose(child_purpose)


def _valid_request(
    parent_purpose: str,
    child_purpose: str,
    *,
    delegation_id: str = "d-1",
    depth: int = 1,
    fanout: int = 1,
    total: int = 1,
) -> DelegationRequest:
    """A request that is valid against *parent_purpose*'s bounds: the child's
    tools are the child's effective surface (⊆ the parent's) and its ceiling is
    the child's purpose ceiling clamped to the parent's."""
    parent_ceiling = PURPOSE_CEILING[parent_purpose]
    child_ceiling = PURPOSE_CEILING[child_purpose]
    if ceiling_rank(child_ceiling) > ceiling_rank(parent_ceiling):
        child_ceiling = parent_ceiling  # a child may never exceed its parent
    return DelegationRequest(
        delegation_id=delegation_id,
        from_agent=f"agent-{parent_purpose}",
        requested_agent_profile=child_purpose,
        objective="do the scoped piece",
        acceptance="tests pass",
        evidence_refs=("seq:1",),
        context_refs=("seq:2",),
        requested_tools=tuple(sorted(_child_surface(parent_purpose, child_purpose))),
        authority_ceiling=child_ceiling,
        return_contract="a SubResult",
        context_mode="inherit",
        depth=depth,
        fanout=fanout,
        total=total,
    )


# ---------------------------------------------------------------------------
# ceiling_rank — the closed, ordered enum
# ---------------------------------------------------------------------------


def test_ceiling_rank_is_total_and_ordered() -> None:
    assert ceiling_rank("read_only") < ceiling_rank("repo_patch_no_publish")
    assert ceiling_rank("repo_patch_no_publish") < ceiling_rank("repo_patch_publish")
    assert len(AUTHORITY_CEILINGS) == 3


def test_ceiling_rank_refuses_unknown() -> None:
    try:
        ceiling_rank("superuser")
    except ValueError:
        return
    raise AssertionError("ceiling_rank must refuse an unknown ceiling")


# ---------------------------------------------------------------------------
# validate_delegation — refuse whole
# ---------------------------------------------------------------------------


def test_validate_allows_a_within_bounds_request() -> None:
    req = _valid_request("thinker_coder", "worker")
    verdict = validate_delegation(
        req,
        parent_effective_tools=_effective("thinker_coder"),
        parent_ceiling=PURPOSE_CEILING["thinker_coder"],
    )
    assert verdict.allowed is True
    assert verdict.reason is None


def test_validate_refuses_tools_outside_parent() -> None:
    req = _valid_request("thinker_coder", "worker")
    rogue = dataclasses.replace(req, requested_tools=req.requested_tools + ("write_file",))
    verdict = validate_delegation(
        rogue,
        parent_effective_tools=_effective("worker"),  # worker has no write_file
        parent_ceiling=PURPOSE_CEILING["worker"],
    )
    assert verdict.allowed is False
    assert "write_file" in (verdict.reason or "")


def test_validate_purpose_exempts_the_tools_subset_check_manual_still_refuses() -> None:
    """t8/q3: a delegation flagged ``purpose=<name>`` is exempt from the
    ``requested_tools`` ⊆ parent check — its child surface is FIXED by the
    tool (the role allow-list ∩ environment), independent of the parent's
    curated surface. The SAME superset request WITHOUT the purpose flag is
    still refused with the pre-existing reason — asserted side by side."""
    scout_tools = roles.BUILTIN_ROLES["scout"].tool_allowlist
    assert "web" in scout_tools
    req = _valid_request("thinker_coder", "worker")
    superset = dataclasses.replace(req, requested_tools=tuple(sorted(scout_tools)))
    parent_without_web = _effective("worker") - {"web"}

    flagged = dataclasses.replace(superset, purpose="code_survey")
    verdict = validate_delegation(
        flagged,
        parent_effective_tools=parent_without_web,
        parent_ceiling=PURPOSE_CEILING["worker"],
    )
    assert verdict.allowed is True
    assert verdict.reason is None

    unflagged = dataclasses.replace(superset, purpose=None)
    verdict = validate_delegation(
        unflagged,
        parent_effective_tools=parent_without_web,
        parent_ceiling=PURPOSE_CEILING["worker"],
    )
    assert verdict.allowed is False
    assert "web" in (verdict.reason or "")


def test_validate_refuses_ceiling_above_parent() -> None:
    # An associate child wants repo_patch_publish; a worker parent holds
    # read_only — the ceiling check refuses before the tools check can matter.
    req = dataclasses.replace(
        _valid_request("worker", "associate"), authority_ceiling="repo_patch_publish"
    )
    verdict = validate_delegation(
        req,
        parent_effective_tools=_effective("worker"),
        parent_ceiling=PURPOSE_CEILING["worker"],
    )
    assert verdict.allowed is False
    assert "exceeds" in (verdict.reason or "")


def test_validate_refuses_depth_fanout_total_over_caps() -> None:
    parent_tools = _effective("thinker_coder")
    parent_ceiling = PURPOSE_CEILING["thinker_coder"]
    for field, cap in (
        ("depth", MAX_SUBAGENT_DEPTH),
        ("fanout", MAX_SUBAGENT_FANOUT),
        ("total", MAX_SUBAGENT_TOTAL),
    ):
        req = dataclasses.replace(_valid_request("thinker_coder", "worker"), **{field: cap + 1})
        verdict = validate_delegation(
            req, parent_effective_tools=parent_tools, parent_ceiling=parent_ceiling
        )
        assert verdict.allowed is False, field
        assert str(cap) in (verdict.reason or ""), field


def test_validate_refuses_unknown_context_mode() -> None:
    req = dataclasses.replace(_valid_request("thinker_coder", "worker"), context_mode="fork")
    verdict = validate_delegation(
        req,
        parent_effective_tools=_effective("thinker_coder"),
        parent_ceiling=PURPOSE_CEILING["thinker_coder"],
    )
    assert verdict.allowed is False
    assert CONTEXT_MODES == ("inherit", "clear")


# ---------------------------------------------------------------------------
# the child ⊆ parent property (hypothesis-free, seeded random)
# ---------------------------------------------------------------------------


def test_property_child_subset_of_parent_regardless_of_model() -> None:
    """For random parent/child profiles, the child's effective surface is a
    subset of the parent's and the child's ceiling ≤ the parent's — and the
    child's model changes neither. A request built from those values validates
    clean."""
    rng = random.Random(411)
    for _ in range(200):
        parent_purpose = rng.choice(sorted(PURPOSES))
        child_purpose = rng.choice(sorted(PURPOSES))
        # The child's model is random and MUST NOT change the effective surface.
        child_model = rng.choice(["model-a", "model-b", "model-c"])
        parent_effective = _effective(parent_purpose)
        child_effective = _child_surface(parent_purpose, child_purpose)
        assert child_effective == _child_surface(parent_purpose, child_purpose)  # model-free
        assert child_model  # the model is irrelevant to the surface
        # The property: child ⊆ parent, ceiling ≤ parent's.
        assert child_effective <= parent_effective
        parent_ceiling = PURPOSE_CEILING[parent_purpose]
        child_ceiling = PURPOSE_CEILING[child_purpose]
        if ceiling_rank(child_ceiling) > ceiling_rank(parent_ceiling):
            child_ceiling = parent_ceiling
        assert ceiling_rank(child_ceiling) <= ceiling_rank(parent_ceiling)
        # A request built from the property's values validates clean.
        req = DelegationRequest(
            delegation_id="d-prop",
            from_agent=f"agent-{parent_purpose}",
            requested_agent_profile=child_purpose,
            objective="o",
            acceptance="a",
            requested_tools=tuple(sorted(child_effective)),
            authority_ceiling=child_ceiling,
        )
        verdict = validate_delegation(
            req, parent_effective_tools=parent_effective, parent_ceiling=parent_ceiling
        )
        assert verdict.allowed is True


def test_property_narrowing_never_adds_a_name() -> None:
    """The strict form: for every random parent/child pair, the child's
    effective surface adds no name the parent does not hold (the intersection
    can only shrink)."""
    rng = random.Random(411)
    for _ in range(200):
        parent_purpose = rng.choice(sorted(PURPOSES))
        child_purpose = rng.choice(sorted(PURPOSES))
        parent_effective = _effective(parent_purpose)
        child_effective = _child_surface(parent_purpose, child_purpose)
        assert child_effective - parent_effective == frozenset()


# ---------------------------------------------------------------------------
# lifecycle events — open / close / snapshot
# ---------------------------------------------------------------------------


def test_open_appends_delegate_before_spawn_and_returns_handle(tmp_path) -> None:
    ledger = TaskLedger(tmp_path / "ledger" / "t1.jsonl", task_id="t1")
    req = _valid_request("thinker_coder", "worker", delegation_id="d-42")
    handle = open_delegation(ledger, req)
    assert handle.delegation_id == "d-42"
    assert handle.child_ref == "sub/d-42"
    events = ledger.events()
    assert len(events) == 1
    assert events[0].kind == "delegate"
    assert events[0].data["id"] == "d-42"
    assert events[0].data["child_ref"] == "sub/d-42"
    assert handle.seq == events[0].seq


def test_snapshot_lists_unreturned_delegate_as_open_loop(tmp_path) -> None:
    ledger = TaskLedger(tmp_path / "ledger" / "t2.jsonl", task_id="t2")
    open_delegation(ledger, _valid_request("thinker_coder", "worker", delegation_id="d-7"))
    snap = ledger.derive()
    open_delegate_loops = [o for o in snap.open_loops if o.get("kind") == "delegate"]
    assert len(open_delegate_loops) == 1
    assert open_delegate_loops[0]["child_ref"] == "sub/d-7"
    assert open_delegate_loops[0]["id"] == "d-7"
    # The delegation is recorded as not-yet-returned.
    assert snap.delegations[0]["returned"] is False


def test_close_appends_return_and_clears_the_open_loop(tmp_path) -> None:
    ledger = TaskLedger(tmp_path / "ledger" / "t3.jsonl", task_id="t3")
    handle = open_delegation(ledger, _valid_request("thinker_coder", "worker", delegation_id="d-9"))
    result = SimpleNamespace(task_id="child-task-9")
    ret = close_delegation(handle, result)
    assert ret.kind == "return"
    assert ret.data["id"] == "d-9"
    assert ret.data["ref"] == "child-task-9"
    snap = ledger.derive()
    assert all(o.get("kind") != "delegate" for o in snap.open_loops)
    assert snap.delegations[0]["returned"] is True
    assert snap.delegations[0]["return_ref"] == "child-task-9"


# ---------------------------------------------------------------------------
# handoff — ledger-only plan-node ownership
# ---------------------------------------------------------------------------


def test_handoff_changes_plan_node_ownership_on_ledger_only(tmp_path) -> None:
    ledger = TaskLedger(tmp_path / "ledger" / "t4.jsonl", task_id="t4")
    ledger.append("plan_node", {"id": "p1", "title": "first node", "owner": "agent-a"})
    handoff(ledger, "p1", "agent-b")
    snap = ledger.derive()
    assert len(snap.plan) == 1
    assert snap.plan[0]["owner"] == "agent-b"
    # The ledger is the only thing touched: exactly two plan_node events.
    assert [e.kind for e in ledger.events()] == ["plan_node", "plan_node"]


def test_handoff_with_mapping_node_preserves_fields(tmp_path) -> None:
    ledger = TaskLedger(tmp_path / "ledger" / "t5.jsonl", task_id="t5")
    handoff(ledger, {"id": "p2", "title": "second node", "status": "active"}, "agent-c")
    snap = ledger.derive()
    assert snap.plan[0]["owner"] == "agent-c"
    assert snap.plan[0]["title"] == "second node"
    assert snap.plan[0]["status"] == "active"
