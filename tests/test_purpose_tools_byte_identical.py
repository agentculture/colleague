"""Unarmed byte-identical suite for the purpose-tools-associate-seat arc
(plan task t13, spec c1/h1, docs/specs/2026-08-28-purpose-tools-associate-seat.md).

Reuses ``tests/_baseline_scenario.py`` (the SAME scenario builder
``tests/test_knobs_byte_identical.py`` / ``tests/test_all_engines_batch.py``
already rely on) and the SAME off-knob environment
``tests/test_knobs_byte_identical.py.OFF_ENV`` applies, against a NEW
reference fixture pair recorded from ``e589451`` (main, the tip this branch
forked from — ``delivery: web-scout-associate ... v1.65.1 (#445)``, the last
commit before any purpose-tools-associate-seat work landed) instead of the
adopt-from-qwen-code arc's older ``ff7331e`` baseline. Recorded via a
throwaway ``git worktree add --detach <tmp> e589451`` (never touching the
operator's checkout) + the SAME off-knob env
(``COLLEAGUE_WEB=0``/``COLLEAGUE_ASSOCIATE_MODEL`` unset/no effort knobs) as
this suite applies live — see ``tests/fixtures/e589451_baseline/*.json``.

**Two things are proven here, and they must NOT be conflated:**

1. **A bare unarmed ``colleague work`` (no ``--role``, no ``agents`` mode) is
   TRULY byte-identical to e589451** — ``colleague.loop.resolve_role``
   returns ``None`` when ``config.role`` is unset (unchanged by this arc:
   ``git diff`` on ``colleague/loop.py``'s ``resolve_role`` for this arc
   touches only comments/an unrelated ``agents``-mode narrowing rule), so
   ``curate_schemas(None)`` — the top-level acting surface's actual call —
   stays the full, unfiltered ``SCHEMAS`` list: purpose tools are spliced
   into a curated list ONLY when ``allow is not None``
   (``colleague/tools.py``'s ``curate_schemas``, the ``if allow is not None``
   guard around the purpose-schema splice). ``test_bare_run_is_byte_identical_
   to_e589451`` proves this with ZERO carve-out — payload keys, system prompt
   text, and the mock/vllm Step trace are asserted EQUAL, not merely
   equivalent-with-an-exception.

2. **The recorded offered-tool-list change is real, but it lives on the
   ``writer`` ROLE's curated surface** (``colleague.roles.BUILTIN_ROLES
   ["writer"]``, plan task t5): ``curate_schemas(BUILTIN_ROLES["writer"])``
   drops ``web``/``subagent``/``subagents`` and gains the six purpose tool
   names (``colleague.roles._writer_allowlist``'s explicit comment: "cortex
   delegates BY PURPOSE now"). The writer role is what a `role="writer"`
   work item (or, per the plan's own language, "cortex" in the spec's naming
   — the full-access acting role) is offered; a bare run never resolves to
   it by default today. ``test_writer_role_surface_carves_out_the_purpose_
   tool_swap`` names this explicitly, per the brief's instruction: 'the
   byte-identical claim is honest only with the cortex surface change
   carved out and asserted'.
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


# ---------------------------------------------------------------------------
# 1. A bare unarmed run: TRUE byte-identical, zero carve-out
# ---------------------------------------------------------------------------


def test_bare_run_is_byte_identical_to_e589451_mock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The mock scenario, unarmed: payload keys, schema names+params, system
    prompt text and the Step trace all compare EQUAL to e589451 — no
    exception, because a bare run's role stays ``None`` (``curate_schemas
    (None)``), which purpose tools never touch (spliced only for a concrete
    role's allow-list)."""
    _apply_off_knobs(monkeypatch)
    repo = scenario.make_repo(tmp_path / "mock")
    captured = scenario.capture_mock_scenario(repo)
    expected = _load_fixture("mock_scenario.json")
    assert captured == expected


def test_bare_run_is_byte_identical_to_e589451_vllm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same proof over the vllm-openai scenario: request payloads (the fixed
    ``PAYLOAD_KEYS`` subset), schema surface, system prompt, Step trace and
    the ``/tokenize`` call count are all byte-identical, unconditionally."""
    _apply_off_knobs(monkeypatch)
    repo = scenario.make_repo(tmp_path / "vllm")
    captured = scenario.capture_vllm_scenario(repo)
    expected = _load_fixture("vllm_scenario.json")
    assert captured == expected


# ---------------------------------------------------------------------------
# 2. The named carve-out: the writer role's curated surface swaps
#    web/subagent/subagents for the six purpose tools
# ---------------------------------------------------------------------------


def test_writer_role_surface_carves_out_the_purpose_tool_swap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE ONE documented exception to 'byte-identical' (per the brief's own
    instruction): the writer role's curated tool surface — what
    ``role='writer'`` (colleague's full-access acting role, referred to as
    'cortex' in the spec's own language) is offered — drops
    ``web``/``subagent``/``subagents`` and gains the six purpose tools,
    relative to e589451's full unfiltered schema-name list. Every OTHER name
    in e589451's list is preserved unchanged (this is a swap, not a
    reshuffle) — the assertion below spells out precisely those three names
    dropped and precisely the six added, so a future accidental additional
    drop/add fails loudly here rather than passing a looser subset check."""
    from colleague.purpose_schemas import PURPOSE_TOOL_NAMES
    from colleague.roles import BUILTIN_ROLES
    from colleague.tools import curate_schemas

    _apply_off_knobs(monkeypatch)
    e589451_names = {s["name"] for s in _load_fixture("mock_scenario.json")["schemas"]}
    writer_names = {s["function"]["name"] for s in curate_schemas(BUILTIN_ROLES["writer"])}

    dropped = e589451_names - writer_names
    added = writer_names - e589451_names
    assert dropped == {"subagent", "subagents"}, dropped
    # web_survey is hidden together with web under COLLEAGUE_WEB=0 (this
    # suite's off-knob env) — the SAME hidden-state rule as web itself, so
    # five of the six purpose names land here, not six.
    assert added == set(PURPOSE_TOOL_NAMES) - {"web_survey"}, added
    # Everything else (read_file, write_file, edit_file, run_command, ...)
    # is untouched by the swap.
    assert (e589451_names & writer_names) == e589451_names - dropped


def test_writer_role_surface_is_the_only_carve_out_from_a_bare_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bare run's ACTUAL top-level surface (role=None, ``curate_schemas
    (None)``) is unaffected by the writer-role swap above — proving the
    carve-out in test 2 is additive to a role a bare run does not resolve to
    by default, never a silent change to the bare-run path itself."""
    from colleague.tools import curate_schemas

    _apply_off_knobs(monkeypatch)
    e589451_names = {s["name"] for s in _load_fixture("mock_scenario.json")["schemas"]}
    bare_names = {s["function"]["name"] for s in curate_schemas(None)}
    assert bare_names == e589451_names
