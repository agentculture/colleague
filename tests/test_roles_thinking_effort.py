"""``Role.effort`` (#416 t5, c13/h8): built-in default rungs from the single
:data:`colleague.effort.ROLE_TABLE` source, an operator role overlay that can
set/override it, and the top-level ``--role`` rule (explorer -> low, others
keep the acting seat default — "low" since v4, #475) that already lives on
``EngineConfig.reasoning_effort_effective`` (t2) — this file adds the pin.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from colleague import effort
from colleague.config import EngineConfig
from colleague.roles import BUILTIN_ROLES, load_role

# ---------------------------------------------------------------------------
# BUILTIN_ROLES carry the ROLE_TABLE rung
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,expected",
    [
        ("writer", "low"),  # v4 (#475)
        ("planner", "low"),  # v4 (#475)
        ("reviewer", "low"),
        ("validator", "low"),
        ("explorer", "off"),
    ],
)
def test_builtin_role_effort_matches_role_table(name: str, expected: str) -> None:
    assert BUILTIN_ROLES[name].effort == expected
    # Single source: the built-in must never drift from effort.ROLE_TABLE.
    assert BUILTIN_ROLES[name].effort == effort.ROLE_TABLE[name]


def test_role_gains_an_effort_field() -> None:
    # A Role built with no explicit effort defaults to None (existing
    # construction sites across the test suite stay valid, unaffected).
    from colleague.roles import Role

    role = Role(
        name="custom",
        prompt_fragment="x",
        tool_allowlist=(),
        skill_subset=None,
        read_only=False,
    )
    assert role.effort is None


# ---------------------------------------------------------------------------
# An operator role overlay can set/override the built-in's effort
# ---------------------------------------------------------------------------


def _write_overlay(tmp_path: Path, name: str, body: str) -> None:
    agents_dir = tmp_path / ".colleague" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    (agents_dir / f"{name}.md").write_text(body, encoding="utf-8")


def test_operator_overlay_overrides_builtin_effort(tmp_path: Path) -> None:
    _write_overlay(tmp_path, "reviewer", "effort: high\n\nYou are a custom reviewer.\n")
    role = load_role("reviewer", tmp_path, "some-model")
    assert role is not None
    assert role.effort == "high"
    # The frontmatter line never leaks into the served prompt.
    assert "effort:" not in role.prompt_fragment
    assert role.prompt_fragment == "\nYou are a custom reviewer.\n"


def test_operator_overlay_without_effort_keeps_builtin_default(tmp_path: Path) -> None:
    _write_overlay(tmp_path, "reviewer", "You are a custom reviewer, no effort line.\n")
    role = load_role("reviewer", tmp_path, "some-model")
    assert role is not None
    assert role.effort == "low"  # BUILTIN_ROLES["reviewer"].effort, unchanged
    assert role.prompt_fragment == "You are a custom reviewer, no effort line.\n"


def test_operator_overlay_invalid_effort_raises(tmp_path: Path) -> None:
    from colleague.cli._errors import CliError

    _write_overlay(tmp_path, "reviewer", "effort: not-a-rung\n\nBody.\n")
    with pytest.raises(CliError):
        load_role("reviewer", tmp_path, "some-model")


def test_no_overlay_file_keeps_builtin_default(tmp_path: Path) -> None:
    role = load_role("validator", tmp_path, "some-model")
    assert role is not None
    assert role.effort == "low"


# ---------------------------------------------------------------------------
# Top-level --role rule (already lives in EngineConfig.reasoning_effort_effective,
# t2) — pinned here per t5's acceptance criterion 3.
# ---------------------------------------------------------------------------


def _config(**overrides) -> EngineConfig:
    base = dict(model="main-model", base_url="http://main:8001/v1", api_key="main-key")
    base.update(overrides)
    return EngineConfig(**base)


def test_top_level_explorer_role_resolves_to_low() -> None:
    config = _config(role="explorer")
    assert config.reasoning_effort_effective == "low"


def test_top_level_explorer_role_off_selectable_via_seat_override() -> None:
    config = _config(role="explorer", reasoning_effort_seats={"cortex": "off"})
    assert config.reasoning_effort_effective == "off"


# reviewer moved to TOP_LEVEL_ROLE_TABLE (low) on 2026-08-30 — see
# tests/test_effort_top_level_mode.py.
@pytest.mark.parametrize("role_name", ["validator", "writer", "planner"])
def test_top_level_other_roles_keep_acting_seat_default(role_name: str) -> None:
    config = _config(role=role_name)
    assert config.reasoning_effort_effective == "off"  # v4 seat default (#475)


def test_top_level_no_role_keeps_acting_seat_default() -> None:
    config = _config()
    assert config.reasoning_effort_effective == "off"  # v4 seat default (#475)
