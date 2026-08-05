"""Typed change lattice + authority ceiling tests (t4) — TEST-FIRST.

Covers the change-lattice validation in :mod:`colleague.lattice`:

* Valid change units are accepted with structured results.
* Out-of-catalog tool ids refuse the WHOLE unit with a recorded reason.
* Unknown target keys refuse the WHOLE unit.
* Operator-owned targets refuse the WHOLE unit.
* Worker-origin writing anything but senses.knowledge is refused.
* Knowledge entries without an origin are refused.
* All refusals return structured reasons, never exception crashes.
"""

from __future__ import annotations

import sys

from colleague.lattice import (
    CapabilityCatalog,
    ChangeUnit,
    Origin,
    Target,
    validate_change,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _catalog(tool_ids: list[str]) -> CapabilityCatalog:
    """Build a CapabilityCatalog from the given tool id list."""
    return CapabilityCatalog(tool_ids=tuple(tool_ids))


# ===========================================================================
# AC1 — Valid unit accepted
# ===========================================================================


def test_valid_host_write_worker_tools() -> None:
    """Host-origin writing worker.tools with in-catalog tools is accepted."""
    catalog = _catalog(["read_file", "write_file"])
    unit = ChangeUnit(
        target=Target.WORKER_TOOLS,
        origin=Origin.HOST,
        tool_ids=["read_file", "write_file"],
    )
    result = validate_change(unit, catalog)
    assert result.allowed is True
    assert result.reason == ""


def test_valid_host_write_worker_prompt_strategist() -> None:
    """Host-origin writing worker.prompt.strategist is accepted."""
    catalog = _catalog(["read_file"])
    unit = ChangeUnit(
        target=Target.WORKER_PROMPT_STRATEGIST,
        origin=Origin.HOST,
    )
    result = validate_change(unit, catalog)
    assert result.allowed is True


def test_valid_host_write_worker_knowledge() -> None:
    """Host-origin writing worker.knowledge with origin-tagged entries is accepted."""
    catalog = _catalog(["read_file"])
    unit = ChangeUnit(
        target=Target.WORKER_KNOWLEDGE,
        origin=Origin.HOST,
        knowledge_entries=[{"key": "fact1", "origin": "host"}],
    )
    result = validate_change(unit, catalog)
    assert result.allowed is True


def test_valid_host_write_senses_prompt_strategist() -> None:
    """Host-origin writing senses.prompt.strategist is accepted."""
    catalog = _catalog(["read_file"])
    unit = ChangeUnit(
        target=Target.SENSES_PROMPT_STRATEGIST,
        origin=Origin.HOST,
    )
    result = validate_change(unit, catalog)
    assert result.allowed is True


def test_valid_host_write_senses_knowledge() -> None:
    """Host-origin writing senses.knowledge with origin-tagged entries is accepted."""
    catalog = _catalog(["read_file"])
    unit = ChangeUnit(
        target=Target.SENSES_KNOWLEDGE,
        origin=Origin.HOST,
        knowledge_entries=[{"key": "sense1", "origin": "host"}],
    )
    result = validate_change(unit, catalog)
    assert result.allowed is True


def test_valid_cortex_propose_worker_tools() -> None:
    """Cortex-origin proposing worker.tools with in-catalog tools is accepted."""
    catalog = _catalog(["read_file"])
    unit = ChangeUnit(
        target=Target.WORKER_TOOLS,
        origin=Origin.CORTEX,
        tool_ids=["read_file"],
    )
    result = validate_change(unit, catalog)
    assert result.allowed is True


def test_valid_cortex_propose_senses_knowledge() -> None:
    """Cortex-origin proposing senses.knowledge is accepted."""
    catalog = _catalog(["read_file"])
    unit = ChangeUnit(
        target=Target.SENSES_KNOWLEDGE,
        origin=Origin.CORTEX,
        knowledge_entries=[{"key": "sense1", "origin": "cortex"}],
    )
    result = validate_change(unit, catalog)
    assert result.allowed is True


def test_valid_worker_write_senses_knowledge() -> None:
    """Worker-origin writing senses.knowledge is accepted (the only worker target)."""
    catalog = _catalog(["read_file"])
    unit = ChangeUnit(
        target=Target.SENSES_KNOWLEDGE,
        origin=Origin.WORKER,
        knowledge_entries=[{"key": "sense1", "origin": "worker"}],
    )
    result = validate_change(unit, catalog)
    assert result.allowed is True


# ===========================================================================
# AC2 — Out-of-catalog tool refused whole
# ===========================================================================


def test_out_of_catalog_tool_refused_whole() -> None:
    """A change selecting a tool id outside the catalog refuses the WHOLE unit."""
    catalog = _catalog(["read_file"])
    unit = ChangeUnit(
        target=Target.WORKER_TOOLS,
        origin=Origin.HOST,
        tool_ids=["read_file", "dangerous_tool"],
    )
    result = validate_change(unit, catalog)
    assert result.allowed is False
    assert "dangerous_tool" in result.reason
    assert "catalog" in result.reason.lower() or "tool" in result.reason.lower()


def test_out_of_catalog_tool_refuses_even_with_valid_tools() -> None:
    """One bad tool id refuses the whole unit even when other tools are valid."""
    catalog = _catalog(["read_file", "write_file"])
    unit = ChangeUnit(
        target=Target.WORKER_TOOLS,
        origin=Origin.HOST,
        tool_ids=["read_file", "unknown_tool", "write_file"],
    )
    result = validate_change(unit, catalog)
    assert result.allowed is False
    assert "unknown_tool" in result.reason


def test_empty_catalog_refuses_any_tool() -> None:
    """An empty catalog refuses any tool id."""
    catalog = _catalog([])
    unit = ChangeUnit(
        target=Target.WORKER_TOOLS,
        origin=Origin.HOST,
        tool_ids=["read_file"],
    )
    result = validate_change(unit, catalog)
    assert result.allowed is False


# ===========================================================================
# AC3 — Unknown key refused whole
# ===========================================================================


def test_unknown_target_refused_whole() -> None:
    """An unknown target string refuses the WHOLE unit."""
    catalog = _catalog(["read_file"])
    unit = ChangeUnit(
        target="unknown.target",  # type: ignore[arg-type]
        origin=Origin.HOST,
    )
    result = validate_change(unit, catalog)
    assert result.allowed is False
    assert "unknown" in result.reason.lower() or "target" in result.reason.lower()


def test_unknown_extra_key_refused_whole() -> None:
    """Extra keys on a change unit refuse the WHOLE unit."""
    catalog = _catalog(["read_file"])
    unit = ChangeUnit(
        target=Target.WORKER_TOOLS,
        origin=Origin.HOST,
        extra_fields={"extra_field": "not_allowed"},
    )
    result = validate_change(unit, catalog)
    assert result.allowed is False
    assert (
        "extra" in result.reason.lower()
        or "unknown" in result.reason.lower()
        or "field" in result.reason.lower()
    )


# ===========================================================================
# AC4 — Operator-owned target refused whole
# ===========================================================================


def test_operator_owned_approvals_refused() -> None:
    """Targeting operator-owned approvals surface refuses the WHOLE unit."""
    catalog = _catalog(["read_file"])
    unit = ChangeUnit(
        target="approvals",  # type: ignore[arg-type]
        origin=Origin.HOST,
    )
    result = validate_change(unit, catalog)
    assert result.allowed is False
    assert (
        "operator" in result.reason.lower()
        or "forbidden" in result.reason.lower()
        or "approvals" in result.reason.lower()
    )


def test_operator_owned_hooks_refused() -> None:
    """Targeting operator-owned hooks surface refuses the WHOLE unit."""
    catalog = _catalog(["read_file"])
    unit = ChangeUnit(
        target="hooks",  # type: ignore[arg-type]
        origin=Origin.HOST,
    )
    result = validate_change(unit, catalog)
    assert result.allowed is False


def test_operator_owned_command_approvals_refused() -> None:
    """Targeting operator-owned command approvals refuses the WHOLE unit."""
    catalog = _catalog(["read_file"])
    unit = ChangeUnit(
        target="command_approvals",  # type: ignore[arg-type]
        origin=Origin.HOST,
    )
    result = validate_change(unit, catalog)
    assert result.allowed is False


def test_operator_owned_task_roles_refused() -> None:
    """Targeting operator-owned task roles refuses the WHOLE unit."""
    catalog = _catalog(["read_file"])
    unit = ChangeUnit(
        target="task_roles",  # type: ignore[arg-type]
        origin=Origin.HOST,
    )
    result = validate_change(unit, catalog)
    assert result.allowed is False


def test_operator_owned_mode_gates_refused() -> None:
    """Targeting operator-owned mode gates refuses the WHOLE unit."""
    catalog = _catalog(["read_file"])
    unit = ChangeUnit(
        target="mode_gates",  # type: ignore[arg-type]
        origin=Origin.HOST,
    )
    result = validate_change(unit, catalog)
    assert result.allowed is False


def test_operator_owned_handoff_policy_refused() -> None:
    """Targeting operator-owned handoff policy refuses the WHOLE unit."""
    catalog = _catalog(["read_file"])
    unit = ChangeUnit(
        target="handoff_policy",  # type: ignore[arg-type]
        origin=Origin.HOST,
    )
    result = validate_change(unit, catalog)
    assert result.allowed is False


# ===========================================================================
# AC5 — Worker-origin writing anything but senses.knowledge refused
# ===========================================================================


def test_worker_origin_write_worker_tools_refused() -> None:
    """Worker-origin writing worker.tools is refused."""
    catalog = _catalog(["read_file"])
    unit = ChangeUnit(
        target=Target.WORKER_TOOLS,
        origin=Origin.WORKER,
        tool_ids=["read_file"],
    )
    result = validate_change(unit, catalog)
    assert result.allowed is False
    assert "worker" in result.reason.lower()


def test_worker_origin_write_worker_prompt_strategist_refused() -> None:
    """Worker-origin writing worker.prompt.strategist is refused."""
    catalog = _catalog(["read_file"])
    unit = ChangeUnit(
        target=Target.WORKER_PROMPT_STRATEGIST,
        origin=Origin.WORKER,
    )
    result = validate_change(unit, catalog)
    assert result.allowed is False
    assert "worker" in result.reason.lower()


def test_worker_origin_write_worker_knowledge_refused() -> None:
    """Worker-origin writing worker.knowledge is refused."""
    catalog = _catalog(["read_file"])
    unit = ChangeUnit(
        target=Target.WORKER_KNOWLEDGE,
        origin=Origin.WORKER,
        knowledge_entries=[{"key": "k1", "origin": "worker"}],
    )
    result = validate_change(unit, catalog)
    assert result.allowed is False
    assert "worker" in result.reason.lower()


def test_worker_origin_write_senses_prompt_strategist_refused() -> None:
    """Worker-origin writing senses.prompt.strategist is refused."""
    catalog = _catalog(["read_file"])
    unit = ChangeUnit(
        target=Target.SENSES_PROMPT_STRATEGIST,
        origin=Origin.WORKER,
    )
    result = validate_change(unit, catalog)
    assert result.allowed is False
    assert "worker" in result.reason.lower()


# ===========================================================================
# AC6 — Knowledge entry without origin refused
# ===========================================================================


def test_knowledge_entry_without_origin_refused() -> None:
    """A knowledge entry missing its origin field refuses the WHOLE unit."""
    catalog = _catalog(["read_file"])
    unit = ChangeUnit(
        target=Target.SENSES_KNOWLEDGE,
        origin=Origin.HOST,
        knowledge_entries=[{"key": "fact1"}],  # no "origin"
    )
    result = validate_change(unit, catalog)
    assert result.allowed is False
    assert "origin" in result.reason.lower()


def test_knowledge_entry_with_empty_origin_refused() -> None:
    """A knowledge entry with an empty-string origin refuses the WHOLE unit."""
    catalog = _catalog(["read_file"])
    unit = ChangeUnit(
        target=Target.SENSES_KNOWLEDGE,
        origin=Origin.HOST,
        knowledge_entries=[{"key": "fact1", "origin": ""}],
    )
    result = validate_change(unit, catalog)
    assert result.allowed is False
    assert "origin" in result.reason.lower()


def test_mixed_knowledge_entries_one_without_origin_refused() -> None:
    """If any knowledge entry lacks an origin, the WHOLE unit is refused."""
    catalog = _catalog(["read_file"])
    unit = ChangeUnit(
        target=Target.SENSES_KNOWLEDGE,
        origin=Origin.HOST,
        knowledge_entries=[
            {"key": "fact1", "origin": "host"},
            {"key": "fact2"},  # missing origin
        ],
    )
    result = validate_change(unit, catalog)
    assert result.allowed is False
    assert "origin" in result.reason.lower()


# ===========================================================================
# AC7 — Refusals return structured reasons, never exception crashes
# ===========================================================================


def test_refusal_returns_structured_verdict_not_exception() -> None:
    """All validation paths return a Verdict, never raise an exception."""
    catalog = _catalog(["read_file"])
    # Various invalid inputs that should all return structured refusals.
    bad_units = [
        ChangeUnit(target="not_a_target", origin=Origin.HOST),  # type: ignore[arg-type]
        ChangeUnit(target=Target.WORKER_TOOLS, origin=Origin.HOST, tool_ids=["bad"]),
        ChangeUnit(target=Target.WORKER_TOOLS, origin=Origin.WORKER),
        ChangeUnit(
            target=Target.SENSES_KNOWLEDGE,
            origin=Origin.HOST,
            knowledge_entries=[{"key": "x"}],
        ),
    ]
    for unit in bad_units:
        result = validate_change(unit, catalog)
        assert result.allowed is False
        assert isinstance(result.reason, str)
        assert len(result.reason) > 0


def test_validate_change_never_raises() -> None:
    """validate_change never raises, even with completely malformed input."""
    catalog = _catalog(["read_file"])
    # Edge cases that might trip up a naive implementation.
    edge_cases = [
        ChangeUnit(target=Target.WORKER_TOOLS, origin=Origin.HOST, tool_ids=[]),
        ChangeUnit(target=Target.SENSES_KNOWLEDGE, origin=Origin.HOST, knowledge_entries=[]),
        ChangeUnit(target=Target.WORKER_TOOLS, origin=Origin.HOST, extra_fields={"x": 1}),
    ]
    for unit in edge_cases:
        result = validate_change(unit, catalog)
        assert isinstance(result.allowed, bool)
        assert isinstance(result.reason, str)


# ===========================================================================
# AC8 — CapabilityCatalog construction from caller-supplied allow-list
# ===========================================================================


def test_catalog_constructed_from_allowlist() -> None:
    """CapabilityCatalog is built from a caller-supplied tool allow-list."""
    catalog = CapabilityCatalog(tool_ids=("read_file", "write_file", "edit_file"))
    assert "read_file" in catalog.tool_ids
    assert "write_file" in catalog.tool_ids
    assert "edit_file" in catalog.tool_ids
    assert "run_command" not in catalog.tool_ids


def test_catalog_has_no_constructor_reading_executor() -> None:
    """CapabilityCatalog takes only tool_ids, never a tool executor reference."""
    # The constructor signature should only accept tool_ids.
    # This is verified by the type: it has no parameter for an executor.
    catalog = CapabilityCatalog(tool_ids=("read_file",))
    assert catalog.tool_ids == ("read_file",)


# ===========================================================================
# AC9 — Zero-deps guard: the module imports stdlib only
# ===========================================================================


def test_lattice_module_imports_stdlib_only() -> None:
    """Importing + exercising colleague.lattice introduces no third-party module."""
    before = set(sys.modules.keys())

    import colleague.lattice as _lattice  # noqa: F401

    # Exercise the real validation path.
    catalog = _lattice.CapabilityCatalog(tool_ids=("read_file",))
    unit = _lattice.ChangeUnit(
        target=_lattice.Target.WORKER_TOOLS,
        origin=_lattice.Origin.HOST,
        tool_ids=["read_file"],
    )
    _lattice.validate_change(unit, catalog)

    new_top_level = {name.split(".")[0] for name in (set(sys.modules.keys()) - before) if name}
    third_party = []
    for name in sorted(new_top_level):
        is_stdlib = name in sys.stdlib_module_names
        is_colleague = name.startswith("colleague")
        is_builtin = name.startswith("_")
        if not (is_stdlib or is_colleague or is_builtin):
            third_party.append(name)
    assert not third_party, f"colleague.lattice leaked third-party imports: {third_party}"


class TestIntegratorTightening:
    """Merge-gate additions: distinct forbidden-key reason + field/target shape."""

    def test_forbidden_key_gets_specific_reason(self):
        from colleague.lattice import (
            CapabilityCatalog,
            ChangeUnit,
            Origin,
            Target,
            validate_change,
        )

        unit = ChangeUnit(
            target=Target.WORKER_TOOLS,
            origin=Origin.CORTEX,
            extra_fields={"permissions": "everything"},
        )
        verdict = validate_change(unit, CapabilityCatalog(tool_ids=("read_file",)))
        assert not verdict.allowed
        assert "forbidden" in verdict.reason
        assert "permissions" in verdict.reason

    def test_tool_ids_on_knowledge_target_refuse_whole(self):
        from colleague.lattice import (
            CapabilityCatalog,
            ChangeUnit,
            Origin,
            Target,
            validate_change,
        )

        unit = ChangeUnit(
            target=Target.SENSES_KNOWLEDGE,
            origin=Origin.CORTEX,
            tool_ids=["read_file"],
        )
        verdict = validate_change(unit, CapabilityCatalog(tool_ids=("read_file",)))
        assert not verdict.allowed
        assert "tool_ids" in verdict.reason

    def test_knowledge_entries_on_tools_target_refuse_whole(self):
        from colleague.lattice import (
            CapabilityCatalog,
            ChangeUnit,
            Origin,
            Target,
            validate_change,
        )

        unit = ChangeUnit(
            target=Target.WORKER_TOOLS,
            origin=Origin.CORTEX,
            knowledge_entries=[{"origin": "cortex", "value": "x"}],
        )
        verdict = validate_change(unit, CapabilityCatalog(tool_ids=("read_file",)))
        assert not verdict.allowed
        assert "knowledge_entries" in verdict.reason
