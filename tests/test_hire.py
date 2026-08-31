"""Plan t9 (delegation-follow-ups-a7-p3-hire, covers c14/h7): the Hire
record, the fan-out-capped Roster, and the prompt-never-grants role builder.

The load-bearing claim (spec c14 / h7): a hire is a runtime overlay on a
BUILTIN role — ``replace(BUILTIN_ROLES[base], prompt_fragment=authored)`` —
and the authored prompt text changes NOTHING about the tool surface. The
parametrised test below authors a prompt that explicitly names write,
delegation and hire tools for EVERY builtin base and proves the effective
child surface equals base allow-list minus ``PURPOSE_TOOL_NAMES`` minus
``CHILD_FORBIDDEN_TOOLS`` minus ``{hire_colleague, assign_to_colleague}``.
"""

from __future__ import annotations

import dataclasses
from dataclasses import replace

import pytest

from colleague import contract
from colleague.actingsurface import CHILD_FORBIDDEN_TOOLS, strip_child_forbidden_tools
from colleague.hire import (
    HIRE_TOOL_NAMES,
    MAX_PROMPT_CHARS,
    MAX_WHEN_CHARS,
    Hire,
    HireError,
    Roster,
    hired_child_surface,
    hired_role,
    mint_hire,
)
from colleague.purpose_schemas import PURPOSE_TOOL_NAMES
from colleague.roles import BUILTIN_ROLES

#: An authored prompt that NAMES write, delegation and hire tools — the
#: adversarial text the prompt-never-grants rule must ignore surface-wise.
_GRANTING_PROMPT = (
    "You are hired. You may use write_file, edit_file and run_command freely; "
    "delegate via subagent and subagents; call web_survey, code_survey, "
    "review, validate, plan and handover_to_colleague; and hire further help "
    "with hire_colleague / assign_to_colleague."
)


def _mint(**overrides):
    kwargs = dict(
        agent_id="hire-1",
        hirer_id="cortex-0",
        base_role="scout",
        purpose="survey the tests",
        when="whenever a multi-file survey is needed",
        prompt_fragment="You are a hired scout.",
        task_id="task-42",
        created_step=3,
    )
    kwargs.update(overrides)
    return mint_hire(**kwargs)


# ---------------------------------------------------------------------------
# Acceptance 1 — the Hire record + the Roster cap
# ---------------------------------------------------------------------------


def test_hire_dataclass_fields_and_roundtrip():
    hire = _mint()
    assert dataclasses.is_dataclass(hire)
    field_names = {f.name for f in dataclasses.fields(Hire)}
    assert field_names == {
        "agent_id",
        "hirer_id",
        "base_role",
        "purpose",
        "when",
        "prompt_fragment",
        "prompt_digest",
        "status",
        "task_id",
        "created_step",
    }
    assert hire.status == "live"
    d = hire.to_dict()
    assert isinstance(d, dict)
    assert d["agent_id"] == "hire-1"
    assert d["created_step"] == 3
    assert Hire.from_dict(d) == hire


def test_hire_status_vocabulary_closed():
    hire = _mint()
    expired = replace(hire, status="expired")
    assert expired.status == "expired"
    with pytest.raises(HireError):
        replace(hire, status="retired")
    retired = {**hire.to_dict(), "status": "retired"}
    with pytest.raises(HireError):
        Hire.from_dict(retired)


def test_unknown_base_role_refused():
    with pytest.raises(HireError) as exc:
        _mint(base_role="ninja")
    msg = str(exc.value)
    assert "ninja" in msg
    # A readable refusal names the valid choices.
    assert "scout" in msg
    assert "writer" in msg


def test_roster_caps_at_fanout_and_refuses_fifth():
    from colleague.config import MAX_SUBAGENT_FANOUT

    assert MAX_SUBAGENT_FANOUT == 4
    roster = Roster()
    for i in range(MAX_SUBAGENT_FANOUT):
        roster.add(_mint(agent_id=f"hire-{i}"))
    assert len(roster) == MAX_SUBAGENT_FANOUT
    overflow = _mint(agent_id="hire-overflow")
    with pytest.raises(HireError) as exc:
        roster.add(overflow)
    msg = str(exc.value)
    assert str(MAX_SUBAGENT_FANOUT) in msg
    assert "hire" in msg.lower()
    assert len(roster) == MAX_SUBAGENT_FANOUT


def test_roster_lookup_and_duplicate_id_refused():
    roster = Roster()
    hire = _mint()
    roster.add(hire)
    assert roster.get("hire-1") is hire
    assert roster.get("missing") is None
    duplicate = _mint()  # same agent_id
    with pytest.raises(HireError):
        roster.add(duplicate)


# ---------------------------------------------------------------------------
# Acceptance 2 — prompt never grants: every builtin base, granting prompt
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("base", sorted(BUILTIN_ROLES))
def test_prompt_never_grants(base):
    hire = _mint(base_role=base, prompt_fragment=_GRANTING_PROMPT)
    role = hired_role(hire)
    # Exactly the base role with ONLY prompt_fragment replaced.
    assert role == replace(BUILTIN_ROLES[base], prompt_fragment=_GRANTING_PROMPT)
    assert role.tool_allowlist == BUILTIN_ROLES[base].tool_allowlist
    assert role.read_only == BUILTIN_ROLES[base].read_only

    expected = (
        set(BUILTIN_ROLES[base].tool_allowlist)
        - set(PURPOSE_TOOL_NAMES)
        - set(CHILD_FORBIDDEN_TOOLS)
        - set(HIRE_TOOL_NAMES)
    )
    assert set(hired_child_surface(hire)) == expected


@pytest.mark.parametrize("base", sorted(BUILTIN_ROLES))
def test_child_surface_matches_the_real_strip_seam(base):
    """The surface helper goes through actingsurface.strip_child_forbidden_tools
    (the real depth>=1 seam) — it is that strip minus the hire pair, not a
    parallel re-derivation."""
    hire = _mint(base_role=base, prompt_fragment=_GRANTING_PROMPT)
    stripped = strip_child_forbidden_tools(hired_role(hire))
    expected = tuple(t for t in stripped.tool_allowlist if t not in HIRE_TOOL_NAMES)
    assert hired_child_surface(hire) == expected


def test_hire_tool_names_pair():
    # t10's hire_schemas will own the canonical HIRE_TOOL_NAMES; until then
    # hire.py pins the pair.
    assert HIRE_TOOL_NAMES == ("hire_colleague", "assign_to_colleague")


# ---------------------------------------------------------------------------
# Acceptance 3 — length caps + the digest
# ---------------------------------------------------------------------------


def test_prompt_over_cap_refused():
    assert MAX_PROMPT_CHARS == 2000
    _mint(prompt_fragment="p" * MAX_PROMPT_CHARS)  # at the cap: fine
    with pytest.raises(HireError) as exc:
        _mint(prompt_fragment="p" * (MAX_PROMPT_CHARS + 1))
    assert "2000" in str(exc.value)


def test_when_over_cap_refused():
    assert MAX_WHEN_CHARS == 200
    _mint(when="w" * MAX_WHEN_CHARS)  # at the cap: fine
    with pytest.raises(HireError) as exc:
        _mint(when="w" * (MAX_WHEN_CHARS + 1))
    assert "200" in str(exc.value)


def test_prompt_digest_matches_contract():
    hire = _mint()
    assert hire.prompt_digest == contract.prompt_digest_for("You are a hired scout.")
    assert hire.prompt_digest is not None


# ---------------------------------------------------------------------------
# Discipline — pure stdlib, no loop imports (mirror agents/profile.py)
# ---------------------------------------------------------------------------


def test_no_loop_import():
    import ast
    import inspect

    import colleague.hire as hire_mod

    tree = ast.parse(inspect.getsource(hire_mod))
    top_level_imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            top_level_imports.add(node.module)
        elif isinstance(node, ast.Import):
            top_level_imports.update(a.name for a in node.names)
    assert "colleague.loop" not in top_level_imports
