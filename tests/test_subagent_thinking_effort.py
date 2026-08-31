"""Per-seat thinking effort on subagent child builds (#416 t5, c13/h8/c28).

Both child-config builders — the armed cross-role dial
(:func:`colleague.subagents._child_config_for_profile`, the #411 t14 path)
and the legacy bare-role build (:func:`colleague.subagents._build_child_config`'s
``dataclasses.replace`` path) — resolve the CHILD's own thinking-effort rung
fresh via :func:`colleague.effort.resolve_effort`, keyed on the child's typed
role and its seat (the resolved lobes role, or ``"cortex"`` with no binding):

- unset parent/spec -> the role/seat tables decide (c28: NEVER inherited
  from the parent, because ``dataclasses.replace`` drops the parent's own
  dynamic ``reasoning_effort_seat`` attribute — a parent at "off" delegating
  to a cortex/thinker child must NOT carry "off" forward);
- an explicit ``ChildSpec.effort`` override wins over both tables and is
  recorded on the ``delegate``/#411-ledger event as ``effort`` +
  ``effort_override=True``;
- the global kill switch (``parent_config.reasoning_effort == "default"``)
  unsets it regardless of role/seat/override.
"""

from __future__ import annotations

from colleague import effort
from colleague.config import EngineConfig
from colleague.subagents import (
    ChildSpec,
    _build_child_config,
    _child_config_for_profile,
    _ChildBinding,
    _delegate_event_data,
)


def _config(**overrides) -> EngineConfig:
    base = dict(model="main-model", base_url="http://main:8001/v1", api_key="main-key")
    base.update(overrides)
    return EngineConfig(**base)


def _binding(model_role: str = "cortex") -> _ChildBinding:
    return _ChildBinding(
        profile="thinker_coder",
        requested_role=model_role,
        model_role=model_role,
        resolved_model=f"{model_role}-model",
        fallback_from_role=None,
        role_info=None,
        gateway_url="http://gateway:9000",
    )


def _effort_of(child_config: EngineConfig) -> str | None:
    return getattr(child_config, "reasoning_effort_seat", None)


# ---------------------------------------------------------------------------
# _build_child_config's bare-role build (no binding — seat is always cortex)
# ---------------------------------------------------------------------------


def test_bare_role_build_resolves_effort_from_role_table() -> None:
    child = _build_child_config(_config(), ChildSpec(), None, model=None, role="reviewer")
    assert _effort_of(child) == effort.ROLE_TABLE["reviewer"]  # "low"


def test_bare_role_build_no_role_falls_back_to_cortex_seat() -> None:
    child = _build_child_config(_config(), ChildSpec(), None, model=None, role=None)
    assert _effort_of(child) == effort.SEAT_TABLE["cortex"]  # "low" (v4, #475)


def test_bare_role_build_parent_off_does_not_carry_forward_to_cortex_child() -> None:
    """c28: a parent at "off" delegating to a writer/cortex child does NOT
    inherit that "off" — the child's own role/seat table rung wins instead,
    because dataclasses.replace drops the parent's dynamic attribute."""
    parent = _config()
    # Simulate a parent whose OWN acting seat resolved to "off" (a dynamic
    # attribute set by the main-seat builder, never a resolve()-time field).
    setattr(parent, "reasoning_effort_seat", "off")
    child = _build_child_config(parent, ChildSpec(), None, model=None, role="writer")
    assert _effort_of(child) != "off"
    assert _effort_of(child) == effort.ROLE_TABLE["writer"]  # "low" (v4, #475)


def test_bare_role_build_explicit_override_wins() -> None:
    spec = ChildSpec(effort="xhigh")
    child = _build_child_config(_config(), spec, None, model=None, role="reviewer")
    assert _effort_of(child) == "xhigh"


def test_bare_role_build_seat_override_wins_over_role_table() -> None:
    parent = _config(reasoning_effort_seats={"cortex": "high"})
    child = _build_child_config(parent, ChildSpec(), None, model=None, role="reviewer")
    assert _effort_of(child) == "high"


def test_bare_role_build_kill_switch_unsets() -> None:
    parent = _config(reasoning_effort="default", reasoning_effort_seats={"cortex": "high"})
    spec = ChildSpec(effort="xhigh")
    child = _build_child_config(parent, spec, None, model=None, role="reviewer")
    assert _effort_of(child) is None


# ---------------------------------------------------------------------------
# _child_config_for_profile's armed cross-role dial (binding.model_role is the seat)
# ---------------------------------------------------------------------------


def test_profile_build_resolves_effort_from_role_table() -> None:
    child = _child_config_for_profile(
        _config(agents=True), ChildSpec(), _binding("cortex"), role="planner"
    )
    assert _effort_of(child) == effort.ROLE_TABLE["planner"]  # "low" (v4, #475)


def test_profile_build_seat_keys_on_bound_lobes_role_not_cortex() -> None:
    # A child bound to the "senses" lobes role, with no typed subagent role
    # named: falls through to the seat table keyed on "senses" ("off"),
    # never the cortex default.
    child = _child_config_for_profile(
        _config(agents=True), ChildSpec(), _binding("senses"), role=None
    )
    assert _effort_of(child) == effort.SEAT_TABLE["senses"]  # "off"


def test_profile_build_parent_off_does_not_carry_forward() -> None:
    parent = _config(agents=True)
    setattr(parent, "reasoning_effort_seat", "off")
    child = _child_config_for_profile(parent, ChildSpec(), _binding("cortex"), role="writer")
    assert _effort_of(child) != "off"
    assert _effort_of(child) == effort.ROLE_TABLE["writer"]  # "low" (v4, #475)


def test_profile_build_explicit_override_wins() -> None:
    spec = ChildSpec(effort="low")
    child = _child_config_for_profile(_config(agents=True), spec, _binding("cortex"), role="writer")
    assert _effort_of(child) == "low"


def test_profile_build_kill_switch_unsets() -> None:
    parent = _config(agents=True, reasoning_effort="default")
    spec = ChildSpec(effort="xhigh")
    child = _child_config_for_profile(parent, spec, _binding("cortex"), role="writer")
    assert _effort_of(child) is None


# ---------------------------------------------------------------------------
# ChildSpec.effort validation
# ---------------------------------------------------------------------------


def test_childspec_effort_defaults_to_none() -> None:
    assert ChildSpec().effort is None


def test_childspec_rejects_an_invalid_effort() -> None:
    import pytest

    from colleague.cli._errors import CliError

    with pytest.raises(CliError):
        ChildSpec(effort="not-a-rung")


def test_childspec_accepts_the_kill_switch_sentinel() -> None:
    assert ChildSpec(effort="default").effort == "default"


# ---------------------------------------------------------------------------
# The delegate/#411-ledger event records the resolved effort + override flag
# ---------------------------------------------------------------------------


def test_delegate_event_records_resolved_effort_and_no_override() -> None:
    data = _delegate_event_data(
        "child-1", ChildSpec(), _binding("cortex"), "agent-1", resolved_effort="medium"
    )
    assert data["effort"] == "medium"
    assert data["effort_override"] is False


def test_delegate_event_records_explicit_override() -> None:
    spec = ChildSpec(effort="xhigh")
    data = _delegate_event_data(
        "child-1", spec, _binding("cortex"), "agent-1", resolved_effort="xhigh"
    )
    assert data["effort"] == "xhigh"
    assert data["effort_override"] is True


# ---------------------------------------------------------------------------
# The subagent/subagents tool schema accepts an optional effort field (c13/h8)
# ---------------------------------------------------------------------------


def test_subagent_schema_exposes_an_effort_field_restricted_to_the_ladder() -> None:
    from colleague import tools

    schema = next(s for s in tools.SCHEMAS if s["function"]["name"] == "subagent")
    props = schema["function"]["parameters"]["properties"]
    assert set(props["effort"]["enum"]) == {"off", "low", "medium", "high", "xhigh", "default"}


def test_subagents_item_schema_exposes_an_effort_field() -> None:
    from colleague import tools

    schema = next(s for s in tools.SCHEMAS if s["function"]["name"] == "subagents")
    item_props = schema["function"]["parameters"]["properties"]["instructions"]["items"][
        "properties"
    ]
    assert set(item_props["effort"]["enum"]) == {"off", "low", "medium", "high", "xhigh", "default"}


def test_subagent_tool_threads_effort_to_the_spawn(tmp_path) -> None:
    from colleague import tools
    from colleague.contract import SubResult

    seen: list = []

    def spawn(instruction, engine=None, model=None, role=None, **kwargs):
        seen.append((instruction, kwargs.get("effort")))
        return SubResult(
            task_id="c1", engine="mock", model="m", status="ok", summary="done", changed_files=[]
        )

    ex = tools.ToolExecutor(str(tmp_path), spawn=spawn)
    ex.execute("subagent", {"instruction": "do it", "effort": "low"})
    assert seen == [("do it", "low")]


def test_batch_items_keep_effort() -> None:
    from colleague import tools

    items = tools._parse_batch_items(
        [
            {"instruction": "a", "effort": "high"},
            {"instruction": "b"},
        ]
    )
    assert items[0]["effort"] == "high"
    assert "effort" not in items[1]
