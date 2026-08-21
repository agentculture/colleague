"""#411 t2 — tool profiles, purpose surfaces, the six-way intersection and its digest."""

from __future__ import annotations

import hashlib

import pytest

from colleague import roles, tae_loop, tools
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


def test_every_registry_tool_plus_deepthink_has_a_profile() -> None:
    assert set(TOOL_PROFILES) == _FULL | {"deepthink"}
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
    for spawner in ("subagent", "subagents", "deepthink"):
        assert profile_for(spawner).inheritable is False
    assert profile_for("read_file").inheritable
    assert profile_for("write_file").inheritable
    with pytest.raises(KeyError):
        profile_for("not_a_tool")
    with pytest.raises(ValueError):
        ToolProfile("x", "magic", False, True)


def test_worker_profile_has_no_generic_code_authoring_tools() -> None:
    assert "write_file" not in WORKER_TOOLS
    assert "edit_file" not in WORKER_TOOLS
    assert {
        "read_file",
        "view_media",
        "list_dir",
        "run_tests",
        "run_command",
        "memory",
        "subagent",
        "subagents",
        "finish",
    } <= WORKER_TOOLS
    assert WORKER_TOOLS < THINKER_CODER_TOOLS


def test_talker_is_empty_thinker_is_full_associate_is_coder_class() -> None:
    assert TALKER_TOOLS == frozenset()
    assert THINKER_CODER_TOOLS == frozenset(_FULL)  # base six + chassis
    assert ASSOCIATE_TOOLS == THINKER_CODER_TOOLS
    assert set(PURPOSE_TOOLS) == set(PURPOSES)
    assert tools_for_purpose("worker") is WORKER_TOOLS
    with pytest.raises(KeyError):
        tools_for_purpose("oracle")


def test_effective_tools_is_the_sorted_intersection_and_never_adds() -> None:
    eff = effective_tools(
        available=_FULL,
        model_supported=_FULL,
        purpose_tools=WORKER_TOOLS,
        policy_tools=_FULL - {"run_command"},
        env_tools=_FULL,
        approved_tools=_FULL,
    )
    assert eff == tuple(sorted(WORKER_TOOLS - {"run_command"}))
    assert set(eff) <= WORKER_TOOLS
    assert "write_file" not in eff
    # narrowing any dimension can only shrink
    smaller = effective_tools(_FULL, _FULL, WORKER_TOOLS, {"read_file"}, _FULL, _FULL)
    assert smaller == ("read_file",)
    # an extra name in one dimension never appears in the result
    assert "write_file" not in effective_tools(
        _FULL, _FULL, WORKER_TOOLS, _FULL | {"magic"}, _FULL, _FULL
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


def test_module_is_pure() -> None:
    src = open(agent_tools.__file__, encoding="utf-8").read()
    for banned in (
        "import subprocess",
        "import threading",
        "from colleague import loop",
        "colleague.engines",
    ):
        assert banned not in src
