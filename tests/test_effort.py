"""Tests for colleague.effort — the per-seat thinking-effort ladder (#416).

Covers spec targets c32, h22, c37, h25, c36, h24, c40, h26, c26, h17.

Also covers purpose-tools-associate-seat t1 (c8, h8, c16, h16, c37): the two
NEW tables in :mod:`colleague.efforttables` — ``ASSOCIATE_SEAT_TABLE`` and
``PURPOSE_TABLE``/``PURPOSE_STEPS`` — kept in a sibling module so
``colleague/effort.py`` never grows past the file-length ratchet.
"""

from __future__ import annotations

import pytest

from colleague import effort, efforttables
from colleague.cli._errors import CliError


def test_ladder_constant():
    assert effort.LADDER == ("off", "low", "medium", "high", "xhigh")
    assert effort.DEFAULT_SENTINEL == "default"


# (table, key, expected) rows pinning the exact v4 tables (the
# effort-v4-rung-observability-rerank arc, #475): acting/associate seats and
# writer/planner roles drop to "low"; only deepthink/design keep xhigh.
_TABLE_ROWS = [
    (effort.SEAT_TABLE, "cortex", "off"),
    (effort.SEAT_TABLE, "worker", "low"),
    (effort.SEAT_TABLE, "deepthink", "xhigh"),
    (effort.SEAT_TABLE, "evaluator", "low"),
    (effort.SEAT_TABLE, "senses", "off"),
    (effort.SEAT_TABLE, "design", "xhigh"),
    # v4 (#475): the associate seat's floor is "low" — Nemotron on the armed
    # seat needs low as its floor (supersedes the t18 "thinking OFF" row).
    (effort.SEAT_TABLE, "associate", "low"),
    (effort.ROLE_TABLE, "writer", "low"),
    (effort.ROLE_TABLE, "planner", "low"),
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
        "associate",
    }
    assert set(effort.ROLE_TABLE) == {
        "writer",
        "planner",
        "reviewer",
        "validator",
        "explorer",
        "scout",  # adopt-from-qwen-code t19: the unarmed scout = read-only, thinking off
    }
    assert set(effort.TOP_LEVEL_ROLE_TABLE) == {"explorer", "reviewer"}
    assert set(effort.TOP_LEVEL_MODE_TABLE) == {"explore", "review"}
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


# ---------------------------------------------------------------------------
# purpose-tools-associate-seat t1 — ASSOCIATE_SEAT_TABLE / PURPOSE_TABLE /
# PURPOSE_STEPS (c8, h8, c16, h16, c37), a sibling module to avoid growing
# effort.py past the file-length ratchet.
# ---------------------------------------------------------------------------

# v4 (the effort-v4-rung-observability-rerank arc, #475): every associate
# sub-seat and every purpose runs at "low".
_NEW_TABLE_ROWS = [
    (efforttables.ASSOCIATE_SEAT_TABLE, "scout", "low"),
    (efforttables.ASSOCIATE_SEAT_TABLE, "compact", "low"),
    (efforttables.ASSOCIATE_SEAT_TABLE, "synthesis", "low"),
    (efforttables.ASSOCIATE_SEAT_TABLE, "digest", "low"),
    (efforttables.ASSOCIATE_SEAT_TABLE, "distill", "low"),
    (efforttables.PURPOSE_TABLE, "web_survey", "low"),
    (efforttables.PURPOSE_TABLE, "code_survey", "low"),
    (efforttables.PURPOSE_TABLE, "review", "low"),
    (efforttables.PURPOSE_TABLE, "validate", "low"),
    (efforttables.PURPOSE_TABLE, "plan", "low"),
    (efforttables.PURPOSE_TABLE, "handover_to_colleague", "low"),
]


@pytest.mark.parametrize("table,key,expected", _NEW_TABLE_ROWS)
def test_new_table_rows(table, key, expected):
    assert table[key] == expected


def test_purpose_steps_table():
    assert efforttables.PURPOSE_STEPS == {
        "web_survey": 12,
        "code_survey": 12,
        "review": 16,
        "validate": 16,
        "plan": 10,
        "handover_to_colleague": None,
    }


def test_new_table_sizes_exact():
    assert set(efforttables.ASSOCIATE_SEAT_TABLE) == {
        "scout",
        "compact",
        "synthesis",
        "digest",
        "distill",
    }
    assert set(efforttables.PURPOSE_TABLE) == {
        "web_survey",
        "code_survey",
        "review",
        "validate",
        "plan",
        "handover_to_colleague",
    }
    assert set(efforttables.PURPOSE_STEPS) == set(efforttables.PURPOSE_TABLE)


def test_code_survey_agrees_with_scout_row():
    # A purpose-called scout's rung is the PURPOSE_TABLE row (an explicit
    # override); ASSOCIATE_SEAT_TABLE['scout'] applies only to a manual
    # subagent role='scout'. Under the effort-v4-rung-observability-rerank
    # arc (#475) both moved to 'low' TOGETHER — pinned so the two tables
    # never silently diverge — while effort.ROLE_TABLE['scout'] (the UNARMED
    # scout, no associate model behind it) deliberately stays 'off': the
    # associate sub-seat row now diverges from the unarmed role row on
    # purpose, because only the armed seat has Nemotron's low floor.
    assert (
        efforttables.PURPOSE_TABLE["code_survey"]
        == efforttables.ASSOCIATE_SEAT_TABLE["scout"]
        == "low"
    )
    assert effort.ROLE_TABLE["scout"] == "off"


def test_fallback_effort_off_and_associate_seat_low_together():
    # v4 (#475), two models, one seat: the FALLBACK is CORTEX occupying the
    # associate seat, and cortex above 'off' over-thinks a shallow scout
    # lane — so FALLBACK_EFFORT is 'off'; Nemotron on the ARMED associate
    # seat needs 'low' as its floor — so SEAT_TABLE['associate'] is 'low'.
    # The pair is asserted together because the split IS the rationale.
    from colleague import associate_seats

    assert associate_seats.FALLBACK_EFFORT == "off"
    assert effort.SEAT_TABLE["associate"] == "low"


def _pick_factory(env: dict):
    def pick(explicit, *env_keys, default):
        if explicit is not None:
            return explicit
        for key in env_keys:
            if key in env:
                return env[key]
        return default

    return pick


def test_resolve_associate_seat_overrides_env_wins():
    pick = _pick_factory({"COLLEAGUE_ASSOCIATE_REASONING_EFFORT_SCOUT": "medium"})
    resolved = efforttables.resolve_associate_seat_overrides(pick, {})
    assert resolved == {"associate.scout": "medium"}


def test_resolve_associate_seat_overrides_file_fallback():
    pick = _pick_factory({})
    resolved = efforttables.resolve_associate_seat_overrides(pick, {"associate.distill": "xhigh"})
    assert resolved == {"associate.distill": "xhigh"}


def test_resolve_associate_seat_overrides_invalid_raises():
    pick = _pick_factory({"COLLEAGUE_ASSOCIATE_REASONING_EFFORT_SCOUT": "bogus"})
    with pytest.raises(CliError):
        efforttables.resolve_associate_seat_overrides(pick, {})


def test_resolve_purpose_overrides_env_wins():
    pick = _pick_factory({"COLLEAGUE_REVIEW_REASONING_EFFORT": "high"})
    resolved = efforttables.resolve_purpose_overrides(pick, {})
    assert resolved == {"review": "high"}


def test_resolve_purpose_overrides_file_fallback():
    pick = _pick_factory({})
    resolved = efforttables.resolve_purpose_overrides(pick, {"plan": "xhigh"})
    assert resolved == {"plan": "xhigh"}


def test_resolve_purpose_overrides_invalid_raises():
    pick = _pick_factory({"COLLEAGUE_PLAN_REASONING_EFFORT": "bogus"})
    with pytest.raises(CliError):
        efforttables.resolve_purpose_overrides(pick, {})


def test_associate_sub_seat_precedence():
    # kill_switch beats everything.
    assert (
        efforttables.resolve_associate_sub_seat_effort(
            kill_switch=True,
            parent_override="xhigh",
            seat_override="medium",
            row_override="low",
            seat="scout",
        )
        is None
    )
    # parent_override beats seat_override.
    assert (
        efforttables.resolve_associate_sub_seat_effort(
            parent_override="low",
            seat_override="xhigh",
            row_override="medium",
            seat="scout",
        )
        == "low"
    )
    # seat_override ("associate.<seat>") beats row_override ("associate").
    assert (
        efforttables.resolve_associate_sub_seat_effort(
            seat_override="medium",
            row_override="xhigh",
            seat="scout",
        )
        == "medium"
    )
    # row_override beats the ASSOCIATE_SEAT_TABLE default.
    assert (
        efforttables.resolve_associate_sub_seat_effort(
            row_override="high",
            seat="scout",
        )
        == "high"
    )
    # Table default is the floor (v4 #475: every sub-seat row is "low").
    assert efforttables.resolve_associate_sub_seat_effort(seat="scout") == "low"
    assert efforttables.resolve_associate_sub_seat_effort(seat="distill") == "low"
    # DEFAULT_SENTINEL at any override rung means "send nothing".
    assert (
        efforttables.resolve_associate_sub_seat_effort(
            seat_override=effort.DEFAULT_SENTINEL, seat="scout"
        )
        is None
    )


def test_purpose_effort_precedence():
    assert (
        efforttables.resolve_purpose_effort(
            kill_switch=True,
            parent_override="xhigh",
            purpose_override="medium",
            purpose="review",
        )
        is None
    )
    assert (
        efforttables.resolve_purpose_effort(
            parent_override="high",
            purpose_override="medium",
            purpose="review",
        )
        == "high"
    )
    assert (
        efforttables.resolve_purpose_effort(
            purpose_override="xhigh",
            purpose="review",
        )
        == "xhigh"
    )
    assert efforttables.resolve_purpose_effort(purpose="review") == "low"
    assert (
        efforttables.resolve_purpose_effort(
            purpose_override=effort.DEFAULT_SENTINEL, purpose="review"
        )
        is None
    )
