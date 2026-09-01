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
   drop ``web``/``subagent``/``subagents``, gain the six purpose tools — arm 4
   (plan t11) restored the raw pair on the acting seat and was REJECTED on
   measured evidence, so the swap stands). The
   mock scenario's captured shape stays TRULY byte-identical (mock never
   sends tools over the wire, and its ``schemas`` key is a fixed
   ``curate_schemas(None)`` probe untouched by this fix);
   ``test_bare_run_is_byte_identical_to_e589451_mock`` proves that with ZERO
   carve-out. The vllm scenario's WIRE ``tools`` payload DOES change — this
   is the real, intended effect of the fix — so
   ``test_bare_run_carves_out_the_purpose_tool_swap_on_the_wire_vllm`` names
   the swap explicitly (the same three-dropped/five-added shape as test 2
   below) and asserts every OTHER captured field (status, steps, the
   ``schemas`` probe, system prompt, tokenize/chat counts, every other
   payload key) stays equal.

2. **The SAME carve-out lives on the ``writer`` ROLE's curated surface
   directly** (``colleague.roles.BUILTIN_ROLES["writer"]``, plan task t5):
   ``curate_schemas(BUILTIN_ROLES["writer"])`` drops
   ``web``/``subagent``/``subagents`` and gains the six purpose tool names.
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
    _assert_default_prompt_section_carveout,
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
    """The ONE documented swap: subagent/subagents dropped, five purpose tools
    gained (web_survey stays hidden together with web under this suite's
    COLLEAGUE_WEB=0 off-knob — the SAME hidden-state rule as web itself).

    #443 dropped ``subagent``/``subagents`` from the acting seat ("replace,
    don't add"). Arm 4 (plan t11) put them BACK alongside the typed purposes
    to measure whether their absence was what suppressed delegation; the
    21-run arm matrix called the raw pair ZERO times (A4: 0/3 delegation), so
    the reversal was rejected and the #443 drop stands. The expectation is
    changed back here rather than relaxed to a subset check."""
    from colleague.purpose_schemas import PURPOSE_TOOL_NAMES

    dropped = expected_names - captured_names
    added = captured_names - expected_names
    assert dropped == {"subagent", "subagents"}, dropped
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
    # Plan t9's ONE named prompt carve-out (spec c2/h10, operator deviation
    # d1): the base prompt's stale Subagents paragraph became the PURPOSE_TOOLS
    # section. Named here, not normalized away — nothing else may move.
    _assert_default_prompt_section_carveout(
        captured.pop("system_prompt"), expected.pop("system_prompt")
    )
    assert captured == expected


def _assert_effort_v4_carveout(captured_kwargs, expected_kwargs):
    """The effort-v4-rung-observability-rerank carve-out (#475): the acting
    seat's table default moved "medium" -> "low", so every turn's
    ``chat_template_kwargs`` differs from the recorded main baseline in
    exactly that one way. Named and asserted, never normalized silently."""
    if captured_kwargs == expected_kwargs:
        return
    assert captured_kwargs == {"reasoning_effort": "low"}
    assert expected_kwargs == {"reasoning_effort": "medium"}


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
    _assert_default_prompt_section_carveout(
        captured.pop("system_prompt"), expected.pop("system_prompt")
    )
    assert captured == expected
    assert len(captured_payloads) == len(expected_payloads)
    for cp, ep in zip(captured_payloads, expected_payloads):
        c_tools = {t["function"]["name"] for t in cp.pop("tools", [])}
        e_tools = {t["function"]["name"] for t in ep.pop("tools", [])}
        _assert_purpose_tool_carveout(c_tools, e_tools)
        _assert_acting_seat_prompt_carveout(cp.pop("messages", []), ep.pop("messages", []))
        # The v4 effort tables (#475) moved the acting rung medium -> low.
        _assert_effort_v4_carveout(
            cp.pop("chat_template_kwargs", None), ep.pop("chat_template_kwargs", None)
        )
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
    'cortex' in the spec's own language) is offered — drops
    ``web``/``subagent``/``subagents`` and gains the six purpose tools,
    relative to e589451's full unfiltered schema-name list (arm 4 / plan t11
    restored the raw pair and was rejected on measured evidence)."""
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


# ---------------------------------------------------------------------------
# 3. Hire arming (delegation-follow-ups t10, c17/h8): COLLEAGUE_HIRE=1 with no
#    hire call differs from unarmed by exactly the two hire tool names and
#    exactly one composed-prompt sentence — nothing else moves.
# ---------------------------------------------------------------------------


def test_armed_hire_differs_by_exactly_two_tools_and_one_sentence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The armed-vs-unarmed live-capture diff (never a fixture diff): the SAME
    vllm scenario run twice, once unarmed and once with ``COLLEAGUE_HIRE=1``
    threaded onto the config the way ``EngineConfig.resolve`` threads it. The
    armed run makes no hire call, so every captured field must compare equal
    EXCEPT: each payload's ``tools`` names gain exactly
    ``hire_schemas.HIRE_TOOL_NAMES``, and each payload's system message (and
    the ``system_prompt`` probe) gain exactly the ONE ``SECTION_TABLE['HIRE']``
    sentence."""
    from colleague.config import _resolve_hire_enabled
    from colleague.hire_schemas import HIRE_TOOL_NAMES
    from colleague.prompttext import SECTION_TABLE

    _apply_off_knobs(monkeypatch)
    unarmed = scenario.capture_vllm_scenario(scenario.make_repo(tmp_path / "unarmed"))

    monkeypatch.setenv("COLLEAGUE_HIRE", "1")
    _resync_loop_default_system(monkeypatch)
    # The scenario builder constructs EngineConfig directly (no resolve()), so
    # thread the flag through the SAME resolver a real run uses — asserting the
    # env knob is what armed it.
    hire = _resolve_hire_enabled(None)
    assert hire is True
    monkeypatch.setattr(scenario, "_ENGINE_CONFIG_KW", {**scenario._ENGINE_CONFIG_KW, "hire": hire})
    armed = scenario.capture_vllm_scenario(scenario.make_repo(tmp_path / "armed"))

    sentence = "\n\n" + SECTION_TABLE["HIRE"]

    def _strip_sentence(text: str) -> str:
        assert text.count(SECTION_TABLE["HIRE"]) == 1
        return text.replace(sentence, "", 1)

    # The system_prompt probe: exactly the one sentence appended.
    assert _strip_sentence(armed.pop("system_prompt")) == unarmed.pop("system_prompt")

    armed_payloads = armed.pop("payloads")
    unarmed_payloads = unarmed.pop("payloads")
    assert armed == unarmed  # status, steps, schemas probe, tokenize/chat counts
    assert len(armed_payloads) == len(unarmed_payloads)
    for ap, up in zip(armed_payloads, unarmed_payloads):
        a_tools = {t["function"]["name"] for t in ap.pop("tools", [])}
        u_tools = {t["function"]["name"] for t in up.pop("tools", [])}
        assert a_tools - u_tools == set(HIRE_TOOL_NAMES)
        assert u_tools - a_tools == set()
        a_messages = ap.pop("messages", [])
        u_messages = up.pop("messages", [])
        assert len(a_messages) == len(u_messages)
        for am, um in zip(a_messages, u_messages):
            if um.get("role") == "system":
                assert _strip_sentence(am["content"]) == um["content"]
                assert set(am) == set(um)
            else:
                assert am == um
        assert ap == up


def test_armed_hire_offered_tools_differ_by_exactly_the_two_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``TaskResult.offered_tools`` (t2) on the mock contract reference: two
    otherwise-identical bare runs differing only in the resolved hire flag
    differ on the artifact's offered list by exactly the two hire names."""
    from colleague.config import EngineConfig
    from colleague.contract import Task
    from colleague.hire_schemas import HIRE_TOOL_NAMES
    from colleague.registry import load

    _apply_off_knobs(monkeypatch)
    repo = scenario.make_repo(tmp_path / "mock")

    def _offered(hire: bool) -> "list[str]":
        config = EngineConfig(hire=hire, **scenario._ENGINE_CONFIG_KW)
        task = Task(
            id=f"t10-hire-{int(hire)}",
            repo_path=str(repo),
            instruction=scenario.MOCK_INSTRUCTION,
            engine="mock",
        )
        result = load("mock").work(task, config)
        assert result.offered_tools is not None
        return result.offered_tools

    unarmed = _offered(False)
    armed = _offered(True)
    assert set(armed) - set(unarmed) == set(HIRE_TOOL_NAMES)
    assert set(unarmed) - set(armed) == set()
    # Appended like the purpose schemas: order preserved, hire pair last.
    assert armed[: len(unarmed)] == unarmed
    assert armed[len(unarmed) :] == list(HIRE_TOOL_NAMES)
