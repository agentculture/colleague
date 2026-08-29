"""Unarmed byte-identical suite for the purpose-tools-associate-seat arc
(plan task t13, spec c1/h1, docs/specs/2026-08-28-purpose-tools-associate-seat.md)
— UPDATED for the deviation-d14 fix (workforce t15, ``colleague/actingsurface.py``).

Reuses ``tests/_baseline_scenario.py`` (the SAME scenario builder
``tests/test_knobs_byte_identical.py`` / ``tests/test_all_engines_batch.py``
already rely on) and the SAME off-knob environment
``tests/test_knobs_byte_identical.py.OFF_ENV`` applies, against the
reference fixture pair recorded from ``e589451`` (main, the tip the
purpose-tools-associate-seat branch forked from — ``delivery:
web-scout-associate ... v1.65.1 (#445)``, the last commit before any
purpose-tools-associate-seat work landed) instead of the adopt-from-qwen-code
arc's older ``ff7331e`` baseline — see ``tests/fixtures/e589451_baseline/*.json``.

**Two things are proven here, and they must NOT be conflated:**

1. **A bare unarmed ``colleague work`` (no ``--role``, no ``agents`` mode)
   offers the writer role's carved-out surface, byte-identical to e589451
   EXCEPT the one named carve-out** — deviation d14 (spec c4/h1: "on the
   armed rig 'colleague work' offers web_survey/code_survey... (no raw web
   on cortex)" is the spec's own HEADLINE claim about the bare run, which the
   pre-fix tip never actually delivered: t5 only ever reached an EXPLICIT
   ``role='writer'`` work item). ``colleague.loop.resolve_role`` no longer
   returns ``None`` for the top-level acting seat (depth 0,
   ``colleague.actingsurface.is_top_level``) when ``config.role`` is unset —
   it now substitutes ``colleague.roles.BUILTIN_ROLES['writer']`` (the SAME
   role an explicit ``--role writer`` run already resolved to, t5's swap:
   drop ``web``, gain the six purpose tools — arm 4 (plan t11) restored the
   raw ``subagent``/``subagents`` on the acting seat). The
   mock scenario's captured shape stays TRULY byte-identical (mock never
   sends tools over the wire, and its ``schemas`` key is a fixed
   ``curate_schemas(None)`` probe untouched by this fix);
   ``test_bare_run_is_byte_identical_to_e589451_mock`` proves that with ZERO
   carve-out. The vllm scenario's WIRE ``tools`` payload DOES change — this
   is the real, intended effect of the fix — so
   ``test_bare_run_carves_out_the_purpose_tool_swap_on_the_wire_vllm`` names
   the swap explicitly (the same nothing-dropped/five-added shape as test 2
   below) and asserts every OTHER captured field (status, steps, the
   ``schemas`` probe, system prompt, tokenize/chat counts, every other
   payload key) stays equal.

2. **The SAME carve-out lives on the ``writer`` ROLE's curated surface
   directly** (``colleague.roles.BUILTIN_ROLES["writer"]``, plan task t5):
   ``curate_schemas(BUILTIN_ROLES["writer"])`` drops ``web`` and gains the
   six purpose tool names (arm 4 / plan t11 kept ``subagent``/``subagents``).
   ``test_writer_role_surface_carves_out_the_purpose_tool_swap`` names this
   explicitly, and ``test_bare_top_level_run_resolves_to_the_writer_carveout``
   proves ``resolve_role`` now hands the top-level acting seat EXACTLY this
   role — the bare run is not a second, independently-drifting surface.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests import _baseline_scenario as scenario
from tests.test_knobs_byte_identical import (
    _SCENARIO_ENV,
    _WEB_OFF_ENV,
    OFF_ENV,
    _assert_acting_seat_prompt_carveout,
    _resync_loop_default_system,
)

FIXTURES = Path(__file__).parent / "fixtures" / "e589451_baseline"


def _apply_off_knobs(monkeypatch: pytest.MonkeyPatch) -> None:
    """The SAME off-knob application ``test_knobs_byte_identical.py`` uses."""
    for key, value in OFF_ENV.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    for key, value in _SCENARIO_ENV.items():
        monkeypatch.setenv(key, value)
    for key, value in _WEB_OFF_ENV.items():
        monkeypatch.setenv(key, value)
    _resync_loop_default_system(monkeypatch)


def _load_fixture(name: str) -> "dict[str, Any]":
    return json.loads((FIXTURES / name).read_text())


def _assert_purpose_tool_carveout(captured_names: "set[str]", expected_names: "set[str]") -> None:
    """The documented swap, as ARM 4 (plan t11) leaves it: NOTHING is dropped
    relative to e589451 any more and five purpose tools are gained (web_survey
    stays hidden together with web under this suite's COLLEAGUE_WEB=0 off-knob
    — the SAME hidden-state rule as web itself; ``web`` is therefore absent
    from ``expected_names`` too, so its own #443 drop cannot show up here).

    #443 dropped ``subagent``/``subagents`` from the acting seat ("replace,
    don't add"); arm 4 puts them BACK alongside the typed purposes to measure
    whether their absence is what suppressed delegation. The expectation is
    changed here rather than relaxed to a subset check: the acting seat is now
    a STRICT superset of e589451's surface."""
    from colleague.purpose_schemas import PURPOSE_TOOL_NAMES

    dropped = expected_names - captured_names
    added = captured_names - expected_names
    assert dropped == set(), dropped
    assert added == set(PURPOSE_TOOL_NAMES) - {"web_survey"}, added
    # Everything else (read_file, write_file, edit_file, run_command, ...) is
    # untouched by the swap.
    assert (expected_names & captured_names) == expected_names - dropped


# ---------------------------------------------------------------------------
# 1. A bare unarmed run: mock stays TRUE byte-identical; the vllm WIRE
#    surface carries the same named carve-out as the writer role directly.
# ---------------------------------------------------------------------------


def test_bare_run_is_byte_identical_to_e589451_mock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The mock scenario, unarmed: payload keys, schema names+params (the
    fixed ``curate_schemas(None)`` probe, untouched by the d14 fix), system
    prompt text and the Step trace all compare EQUAL to e589451 — mock never
    sends a wire ``tools`` payload, so the d14 fix (which changes what
    ``resolve_role`` returns, not what ``curate_schemas(None)`` returns) has
    nothing to touch here."""
    _apply_off_knobs(monkeypatch)
    repo = scenario.make_repo(tmp_path / "mock")
    captured = scenario.capture_mock_scenario(repo)
    expected = _load_fixture("mock_scenario.json")
    assert captured == expected


def test_bare_run_carves_out_the_purpose_tool_swap_on_the_wire_vllm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bare unarmed vllm-openai run's WIRE tool surface (deviation d14 fix:
    ``colleague.loop.resolve_role`` no longer returns ``None`` for the
    top-level acting seat's bare case) drops subagent/subagents and gains
    five purpose tools on every turn's payload — the SAME swap
    ``test_writer_role_surface_carves_out_the_purpose_tool_swap`` names on the
    writer role directly.

    Plan t5 (``docs/plans/2026-08-29-purpose-tools-get-chosen.md``) adds the
    matching PROMPT carve-out: the same bare run's wire system message now
    also carries the writer role's prompt fragment, because both halves read
    one resolution (``actingsurface.acting_role_name``). Every other captured
    field (status, steps, the ``schemas`` probe, the ``system_prompt`` base
    probe, tokenize/chat counts, and every OTHER payload key) is untouched."""
    _apply_off_knobs(monkeypatch)
    repo = scenario.make_repo(tmp_path / "vllm")
    captured = scenario.capture_vllm_scenario(repo)
    expected = _load_fixture("vllm_scenario.json")

    captured_payloads = captured.pop("payloads")
    expected_payloads = expected.pop("payloads")
    assert captured == expected
    assert len(captured_payloads) == len(expected_payloads)
    for cp, ep in zip(captured_payloads, expected_payloads):
        c_tools = {t["function"]["name"] for t in cp.pop("tools", [])}
        e_tools = {t["function"]["name"] for t in ep.pop("tools", [])}
        _assert_purpose_tool_carveout(c_tools, e_tools)
        _assert_acting_seat_prompt_carveout(cp.pop("messages", []), ep.pop("messages", []))
        assert cp == ep


# ---------------------------------------------------------------------------
# 2. The named carve-out: the writer role's curated surface swaps
#    web/subagent/subagents for the six purpose tools
# ---------------------------------------------------------------------------


def test_writer_role_surface_carves_out_the_purpose_tool_swap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE named exception to 'byte-identical' (per the brief's own
    instruction): the writer role's curated tool surface — what
    ``role='writer'`` (colleague's full-access acting role, referred to as
    'cortex' in the spec's own language) is offered — drops ``web`` and gains
    the six purpose tools, relative to e589451's full unfiltered schema-name
    list; arm 4 (plan t11) restored ``subagent``/``subagents``."""
    from colleague.roles import BUILTIN_ROLES
    from colleague.tools import curate_schemas

    _apply_off_knobs(monkeypatch)
    e589451_names = {s["name"] for s in _load_fixture("mock_scenario.json")["schemas"]}
    writer_names = {s["function"]["name"] for s in curate_schemas(BUILTIN_ROLES["writer"])}
    _assert_purpose_tool_carveout(writer_names, e589451_names)


def test_bare_top_level_run_resolves_to_the_writer_carveout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deviation d14 fix: a bare top-level run's ACTUAL curated surface
    (``curate_schemas(resolve_role(EngineConfig(), repo))``) is now EXACTLY
    the writer role's carved-out surface proven above — never the raw,
    unfiltered ``curate_schemas(None)`` list, and never a second,
    independently-drifting swap. ``curate_schemas(None)`` itself is
    UNCHANGED — it is still the "no role, full raw surface" contract several
    other pinning tests and ``colleague.subagents._child_requested_tools``'s
    bare-name lookups rely on."""
    from colleague.config import EngineConfig
    from colleague.loop import resolve_role
    from colleague.roles import BUILTIN_ROLES
    from colleague.tools import curate_schemas

    _apply_off_knobs(monkeypatch)
    e589451_names = {s["name"] for s in _load_fixture("mock_scenario.json")["schemas"]}
    assert {s["function"]["name"] for s in curate_schemas(None)} == e589451_names

    bare_role = resolve_role(EngineConfig(), str(tmp_path))
    assert bare_role is not None
    assert set(bare_role.tool_allowlist) == set(BUILTIN_ROLES["writer"].tool_allowlist)
    bare_names = {s["function"]["name"] for s in curate_schemas(bare_role)}
    writer_names = {s["function"]["name"] for s in curate_schemas(BUILTIN_ROLES["writer"])}
    assert bare_names == writer_names
