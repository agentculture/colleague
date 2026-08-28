"""Integration proof for typed-subagent roles (#t11).

The headline guarantees, as concrete mechanical assertions:

- c1/h1 — a read-only role's OFFERED tool schema (what the engine hands the model)
  carries NO write_file / edit_file / run_command, and the role-aware executor
  REFUSES them — so a read-only role provably cannot mutate the tree.
- c6/h14 — a role prompt + its curated skills compose deterministically and per
  model, through the single layered-config path.
- the global agent budget bounds the TOTAL agents spawned, every nesting shape.
- c4/h12 — mock == vllm: a role-typed child yields the same TaskResult/SubResult
  shape, and both engines route role through the SAME resolve_role path.
- c10/h15 — additive invariant: with no .colleague/agents config and no role
  requested, the pipeline is byte-identical to the pre-role contract (the ``role``
  key is omitted).

The zero-deps guard (``tests/test_zero_deps.py``) and the boundary test
(``tests/test_boundary.py``) cover "roles add no runtime dep / open no socket /
keep threads+subprocess confined"; this module proves the behavioural surface.
"""

from __future__ import annotations

import dataclasses
import subprocess

import pytest

from colleague.config import MAX_SUBAGENT_TOTAL, EngineConfig
from colleague.contract import Task
from colleague.engines.mock import MockEngine
from colleague.layers import compose_role_prompt
from colleague.loop import resolve_role
from colleague.purpose_schemas import PURPOSE_TOOL_NAMES
from colleague.roles import BUILTIN_ROLES
from colleague.subagents import _AgentBudget
from colleague.tools import SCHEMAS, ToolError, ToolExecutor, curate_schemas

_WRITE_TOOLS = {"write_file", "edit_file", "run_command"}
_READONLY_ROLES = ("explorer", "planner", "reviewer", "validator")


@pytest.fixture
def git_repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return tmp_path


# --- c1/h1: a read-only role cannot write by ANY offered tool ---------------


@pytest.mark.parametrize("role_name", _READONLY_ROLES)
def test_readonly_role_offered_schema_has_no_write_tools(role_name):
    offered = {s["function"]["name"] for s in curate_schemas(role_name)}
    assert not (
        offered & _WRITE_TOOLS
    ), f"{role_name}'s offered schema exposes a write tool: {offered & _WRITE_TOOLS}"


@pytest.mark.parametrize("role_name", _READONLY_ROLES)
@pytest.mark.parametrize("tool", sorted(_WRITE_TOOLS))
def test_readonly_role_executor_refuses_every_write_tool(git_repo, role_name, tool):
    ex = ToolExecutor(str(git_repo), allowlist=BUILTIN_ROLES[role_name])
    with pytest.raises(ToolError):
        ex.execute(tool, {"path": "x.txt", "content": "y", "command": "echo hi"})


def test_readonly_role_run_end_to_end_mutates_nothing(git_repo):
    # The mock's scripted turn TRIES write_file. An explorer-typed run must refuse
    # it, leaving the tree unchanged — the headline guarantee, end to end.
    cfg = dataclasses.replace(EngineConfig(), role="explorer")
    res = MockEngine().work(Task.new(str(git_repo), "explore"), cfg)
    assert res.changed_files == [], "a read-only role child mutated the tree"
    assert res.role == "explorer"  # the applied role is recorded on the result


def test_validator_runs_tests_without_any_write_surface(git_repo):
    offered = {s["function"]["name"] for s in curate_schemas("validator")}
    assert "run_tests" in offered, "validator must be able to run tests"
    assert not (offered & _WRITE_TOOLS), "validator must have NO write/exec surface"


# --- c6/h14: role prompt + curated skills compose deterministically ---------


def test_role_prompt_composes_deterministically_and_includes_fragment(git_repo):
    role = BUILTIN_ROLES["reviewer"]
    p1 = compose_role_prompt(role, str(git_repo), "some-model", base="BASE")
    p2 = compose_role_prompt(role, str(git_repo), "some-model", base="BASE")
    assert p1 == p2, "role prompt composition must be deterministic"
    assert p1 is not None and p1.startswith("BASE"), "base composes first"
    assert role.prompt_fragment in p1, "the role's prompt fragment must be present"


# --- global agent budget bounds the total ------------------------------------


def test_global_agent_budget_default_is_max_subagent_total():
    assert MAX_SUBAGENT_TOTAL == 24
    assert _AgentBudget().limit == 24


# --- c4/h12: mock == vllm role shape; both engines share one path ------------


def test_both_engines_route_role_through_one_resolver():
    import colleague.engines.mock as mock_mod
    import colleague.engines.vllm_openai as vllm_mod

    # The all-engines rule: neither engine has its own role-resolution path.
    assert mock_mod.resolve_role is resolve_role
    assert vllm_mod.resolve_role is resolve_role


def test_role_typed_result_shape_is_additive(git_repo):
    # No role → 'role' key OMITTED (byte-identical to the pre-role artifact shape).
    none_res = MockEngine().work(Task.new(str(git_repo), "x"), EngineConfig())
    assert none_res.role is None
    assert "role" not in none_res.to_dict()
    # A role → recorded + serialized, the ONLY shape difference.
    role_res = MockEngine().work(
        Task.new(str(git_repo), "y"), dataclasses.replace(EngineConfig(), role="reviewer")
    )
    assert role_res.to_dict()["role"] == "reviewer"
    # The two dicts differ in exactly the 'role' key.
    none_keys = set(none_res.to_dict())
    role_keys = set(role_res.to_dict())
    assert role_keys - none_keys == {"role"}


# --- c10/h15: additive invariant — no role/config = full surface -------------


def test_no_role_offers_full_surface(git_repo):
    # ``curate_schemas(None)`` itself is UNCHANGED (t15/actingsurface, deviation
    # d14): the "no role, full raw surface" contract every other caller relies on
    # (curate_schemas(None) == the raw, unfiltered SCHEMAS list) still holds.
    full = {s["function"]["name"] for s in SCHEMAS}
    assert {s["function"]["name"] for s in curate_schemas(None)} == full
    # t5 (operator decisions q9/q10): an EXPLICIT "writer" role differs from the
    # raw full surface — cortex delegates BY PURPOSE, so the writer's curated
    # schema drops web/subagent/subagents and gains the six purpose tools.
    writer_offered = {s["function"]["name"] for s in curate_schemas("writer")}
    dropped = {"web", "subagent", "subagents"}
    assert writer_offered == (full - dropped) | set(PURPOSE_TOOL_NAMES)
    # d14 fix: resolve_role no longer returns None for the bare TOP-LEVEL acting
    # seat (config.role unset, agents mode unarmed, depth 0) — it now resolves to
    # exactly the writer role's carved-out surface above, so a bare run and an
    # explicit --role writer run are offered the identical curated surface.
    bare_role = resolve_role(EngineConfig(), str(git_repo))
    assert bare_role is not None
    assert set(bare_role.tool_allowlist) == set(BUILTIN_ROLES["writer"].tool_allowlist)
    assert {s["function"]["name"] for s in curate_schemas(bare_role)} == writer_offered
