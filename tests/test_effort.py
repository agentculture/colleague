"""Tests for colleague.effort — the per-seat thinking-effort ladder (#416).

Covers spec targets c32, h22, c37, h25, c36, h24, c40, h26, c26, h17.
"""

from __future__ import annotations

import pytest

from colleague import effort
from colleague.cli._errors import CliError


def test_ladder_constant():
    assert effort.LADDER == ("off", "low", "medium", "high", "xhigh")
    assert effort.DEFAULT_SENTINEL == "default"


# (table, key, expected) rows pinning the exact v3 tables (c36/c40).
_TABLE_ROWS = [
    (effort.SEAT_TABLE, "cortex", "medium"),
    (effort.SEAT_TABLE, "worker", "medium"),
    (effort.SEAT_TABLE, "deepthink", "xhigh"),
    (effort.SEAT_TABLE, "evaluator", "medium"),
    (effort.SEAT_TABLE, "senses", "off"),
    (effort.SEAT_TABLE, "design", "xhigh"),
    (effort.ROLE_TABLE, "writer", "medium"),
    (effort.ROLE_TABLE, "planner", "medium"),
    (effort.ROLE_TABLE, "reviewer", "low"),
    (effort.ROLE_TABLE, "validator", "low"),
    (effort.ROLE_TABLE, "explorer", "off"),
    (effort.TOP_LEVEL_ROLE_TABLE, "explorer", "low"),
    (effort.DESIGN_SITE_TABLE, "plan.spec_stage", "xhigh"),
    (effort.DESIGN_SITE_TABLE, "plan.plan_stage", "high"),
    (effort.DESIGN_SITE_TABLE, "plan.workforce", "xhigh"),
    (effort.DESIGN_SITE_TABLE, "autosplit", "xhigh"),
    (effort.DESIGN_SITE_TABLE, "fillline.split", "xhigh"),
    (effort.DESIGN_SITE_TABLE, "subagents.decompose", "xhigh"),
]


@pytest.mark.parametrize("table,key,expected", _TABLE_ROWS)
def test_default_table(table, key, expected):
    assert table[key] == expected


def test_table_sizes_exact():
    # No stray rows beyond what's pinned above.
    assert set(effort.SEAT_TABLE) == {
        "cortex",
        "worker",
        "deepthink",
        "evaluator",
        "senses",
        "design",
    }
    assert set(effort.ROLE_TABLE) == {
        "writer",
        "planner",
        "reviewer",
        "validator",
        "explorer",
    }
    assert set(effort.TOP_LEVEL_ROLE_TABLE) == {"explorer"}
    assert set(effort.DESIGN_SITE_TABLE) == {
        "plan.spec_stage",
        "plan.plan_stage",
        "plan.workforce",
        "autosplit",
        "fillline.split",
        "subagents.decompose",
    }


def test_precedence_table():
    # kill_switch beats everything, including an explicit parent_override.
    assert (
        effort.resolve_effort(
            kill_switch=True,
            parent_override="xhigh",
            seat_override="medium",
            role="writer",
            seat="cortex",
            site="autosplit",
        )
        is None
    )

    # parent_override beats seat_override.
    assert (
        effort.resolve_effort(
            kill_switch=False,
            parent_override="low",
            seat_override="xhigh",
            role="writer",
            seat="cortex",
            site="autosplit",
        )
        == "low"
    )

    # seat_override beats the design-site table.
    assert (
        effort.resolve_effort(
            kill_switch=False,
            parent_override=None,
            seat_override="medium",
            role=None,
            seat=None,
            site="autosplit",
        )
        == "medium"
    )

    # design-site table beats the role table.
    assert (
        effort.resolve_effort(
            kill_switch=False,
            parent_override=None,
            seat_override=None,
            role="writer",
            seat=None,
            site="autosplit",
        )
        == "xhigh"
    )

    # role table beats the seat table.
    assert (
        effort.resolve_effort(
            kill_switch=False,
            parent_override=None,
            seat_override=None,
            role="reviewer",
            seat="cortex",
            site=None,
        )
        == "low"
    )

    # seat table beats unset (None).
    assert (
        effort.resolve_effort(
            kill_switch=False,
            parent_override=None,
            seat_override=None,
            role=None,
            seat="senses",
            site=None,
        )
        == "off"
    )

    # Fully unset resolves to None.
    assert (
        effort.resolve_effort(
            kill_switch=False,
            parent_override=None,
            seat_override=None,
            role=None,
            seat=None,
            site=None,
        )
        is None
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"parent_override": effort.DEFAULT_SENTINEL, "seat": "cortex"},
        {"seat_override": effort.DEFAULT_SENTINEL, "seat": "cortex"},
    ],
)
def test_default_sentinel_means_send_nothing(kwargs):
    assert effort.resolve_effort(kill_switch=False, **kwargs) is None


def test_fragment():
    assert effort.to_chat_template_kwargs("off") == {"enable_thinking": False}
    assert effort.to_chat_template_kwargs("medium") == {"reasoning_effort": "medium"}
    # 'high' is sent verbatim even though it probes identical to 'xhigh' on
    # Qwen3.8 (2026-08-22) — colleague never silently upgrades it.
    assert effort.to_chat_template_kwargs("high") == {"reasoning_effort": "high"}
    assert effort.to_chat_template_kwargs("xhigh") == {"reasoning_effort": "xhigh"}
    assert effort.to_chat_template_kwargs(None) is None
    assert effort.to_chat_template_kwargs(effort.DEFAULT_SENTINEL) is None


def test_validate():
    assert effort.validate_effort("high") == "high"
    assert effort.validate_effort(effort.DEFAULT_SENTINEL) == effort.DEFAULT_SENTINEL

    for bogus in ("bogus", "", "HIGH"):
        with pytest.raises(CliError) as exc_info:
            effort.validate_effort(bogus)
        message = str(exc_info.value.message)
        for rung in effort.LADDER:
            assert rung in message
