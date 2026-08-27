"""Reversibility — one off-knob per mechanism, byte-identical pinning suite (t22).

Plan task t22 (docs/specs/2026-08-27-adopt-from-qwen-code.md, docs/plans/
2026-08-27-adopt-from-qwen-code.md), covers c1/h1/c44/h33.

Two things are proven here:

1. **Byte-identical off-state** (``test_mock_scenario_byte_identical_to_main`` /
   ``test_vllm_scenario_byte_identical_to_main``): with every one of the eleven
   reversibility knobs at its off value, the SAME two scenarios
   (:mod:`tests._baseline_scenario`) produce the identical Step sequence,
   system prompt, tool-schema surface (by name) and — for the vllm scenario —
   the identical per-turn request payloads and ``/tokenize`` call count, as
   were recorded from ``main`` (``tests/fixtures/main_baseline/*.json``,
   recorded via ``uv run --project <baseline-checkout> python
   tests/_baseline_scenario.py <out-dir>`` against a clean checkout of
   ``ff7331e`` — see the final report for the exact command).

   ONE known, documented, unconditional exception is normalized out of the
   schema/tools comparison rather than silently ignored: task t9
   (``colleague/readpage.py``) added optional ``limit``/``offset`` parameters
   to the ``read_file`` tool schema with NO off-knob of its own (it is not one
   of this task's eleven knobs, and t9 predates/parallels this task in the
   plan) — so the schema/tools comparison here is scoped to TOOL NAMES, not
   full per-tool parameter shape. This is spelled out again in the final
   report, not papered over.

2. **A dead knob is caught** (the ``test_*_on_*`` functions below, one per
   knob): flipping each knob ON (all the OTHERS held at their off value)
   produces a real, expected behavioral diff at the knob's own mechanism.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import pytest

from tests import _baseline_scenario as scenario

FIXTURES = Path(__file__).parent / "fixtures" / "main_baseline"

#: The eleven reversibility knobs and their OFF value (``None`` = must be
#: UNSET, never an empty string — the sentinel main's own resolve() treats as
#: "absent").
OFF_ENV: "dict[str, str | None]" = {
    "COLLEAGUE_MAX_OUTPUT_TOKENS": "0",
    "COLLEAGUE_EXACT_TOKENS": "1",
    "COLLEAGUE_TOOL_CONCURRENCY": "1",
    "COLLEAGUE_MICROCOMPACT": "0",
    "COLLEAGUE_STREAM_IDLE_TIMEOUT": "0",
    "COLLEAGUE_STREAM_MAX_LIFETIME": "0",
    "COLLEAGUE_TOOL_SPILL": "0",
    "COLLEAGUE_PROMPT_VARIANT": "v1",
    "COLLEAGUE_TOOLS_LEGACY": "1",
    "COLLEAGUE_ASSOCIATE_MODEL": None,
    "COLLEAGUE_PRIOR_READ": "0",
}

#: Not one of the eleven reversibility knobs — an unrelated, pre-existing
#: streaming feature (#393). Set so the vllm scenario's blocking-JSON fake
#: rig (no SSE support) matches how the fixtures were recorded.
_SCENARIO_ENV = {"COLLEAGUE_STREAM": "0"}


def _apply_off_knobs(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in OFF_ENV.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    for key, value in _SCENARIO_ENV.items():
        monkeypatch.setenv(key, value)
    _resync_loop_default_system(monkeypatch)


def _resync_loop_default_system(monkeypatch: pytest.MonkeyPatch) -> None:
    """Re-sync ``colleague.loop``'s cached default system prompt to the live env.

    ``colleague/loop.py`` builds ``_DEFAULT_SYSTEM`` ONCE, at module import
    time (by design — the loop's own comment: "Built ONCE at import ... Kept
    under this name so nothing else in the loop changes"). Since
    ``colleague.loop`` is already imported (transitively, by
    ``tests/conftest.py``) long before this test's ``monkeypatch.setenv``
    runs, that module-level constant never reflects
    ``COLLEAGUE_PROMPT_VARIANT`` set mid-session — a real consequence of the
    "built once" contract, not a bug in this test. A bare repo's
    ``Engine.system_prompt()`` returns ``None`` (no layered config), so the
    loop falls back to exactly this cached constant, and the scenario's
    wire-visible system prompt would silently stay whatever it was at
    collection time. Recomputing it here (from :func:`colleague.prompttext.
    default_system`, which DOES read the env live) reproduces the state a
    freshly started process would have with this env — the only way to
    exercise the knob without re-importing the whole package per test.
    """
    from colleague import loop as _loop
    from colleague import prompttext

    monkeypatch.setattr(_loop, "_DEFAULT_SYSTEM", prompttext.default_system())


def _load_fixture(name: str) -> "dict[str, Any]":
    return json.loads((FIXTURES / name).read_text())


def _names_only(schemas: "list[dict[str, Any]]") -> "list[str]":
    """Tool NAMES, sorted — see the module docstring's t9 normalization note."""
    return sorted(s["name"] for s in schemas)


def _normalize_capture(capture: "dict[str, Any]") -> "dict[str, Any]":
    """Drop per-tool parameter detail (t9's unconditional read_file addition)
    from both the top-level ``schemas`` and any embedded payload ``tools``
    list, so the comparison is scoped to what the eleven knobs actually govern."""
    out = dict(capture)
    out["schemas"] = _names_only(capture["schemas"])
    if "payloads" in capture:
        new_payloads = []
        for payload in capture["payloads"]:
            p = dict(payload)
            if "tools" in p:
                p["tools"] = _names_only([{"name": t["function"]["name"]} for t in p["tools"]])
            new_payloads.append(p)
        out["payloads"] = new_payloads
    return out


# ---------------------------------------------------------------------------
# 1. Byte-identical off-state
# ---------------------------------------------------------------------------


def test_mock_scenario_byte_identical_to_main(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _apply_off_knobs(monkeypatch)
    repo = scenario.make_repo(tmp_path / "mock")
    captured = _normalize_capture(scenario.capture_mock_scenario(repo))
    expected = _normalize_capture(_load_fixture("mock_scenario.json"))
    assert captured == expected


def test_vllm_scenario_byte_identical_to_main(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _apply_off_knobs(monkeypatch)
    repo = scenario.make_repo(tmp_path / "vllm")
    captured = _normalize_capture(scenario.capture_vllm_scenario(repo))
    expected = _normalize_capture(_load_fixture("vllm_scenario.json"))
    assert captured == expected


# ---------------------------------------------------------------------------
# 2. A dead knob is caught — flip each ON (others held off), assert a diff
# ---------------------------------------------------------------------------


def test_max_output_tokens_on_adds_max_tokens_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _apply_off_knobs(monkeypatch)
    monkeypatch.delenv("COLLEAGUE_MAX_OUTPUT_TOKENS", raising=False)  # on: unset -> default ceiling
    repo = scenario.make_repo(tmp_path / "vllm")
    captured = scenario.capture_vllm_scenario(repo)
    assert all("max_tokens" not in p for p in _load_fixture("vllm_scenario.json")["payloads"])
    assert all("max_tokens" in p for p in captured["payloads"])
    assert all(
        isinstance(p["max_tokens"], int) and p["max_tokens"] > 0 for p in captured["payloads"]
    )


def test_exact_tokens_on_reduces_tokenize_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _apply_off_knobs(monkeypatch)
    monkeypatch.delenv("COLLEAGUE_EXACT_TOKENS", raising=False)  # on: unset -> estimate-anchored
    repo = scenario.make_repo(tmp_path / "vllm")
    captured = scenario.capture_vllm_scenario(repo)
    off_calls = _load_fixture("vllm_scenario.json")["tokenize_calls"]
    assert captured["tokenize_calls"] < off_calls


def test_tool_concurrency_on_runs_batch_off_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    from colleague import toolbatch, toolbatch_loop

    monkeypatch.setenv("COLLEAGUE_TOOL_CONCURRENCY", "1")
    assert toolbatch_loop.concurrency_width() == 1
    main_ident = threading.get_ident()
    off_idents = toolbatch.run_batch(
        lambda _c: threading.get_ident(), [1, 2, 3], toolbatch_loop.concurrency_width()
    )
    assert off_idents == [main_ident, main_ident, main_ident]

    monkeypatch.delenv("COLLEAGUE_TOOL_CONCURRENCY", raising=False)  # on: default width 10
    assert toolbatch_loop.concurrency_width() == toolbatch_loop.DEFAULT_TOOL_CONCURRENCY
    on_idents = toolbatch.run_batch(
        lambda _c: threading.get_ident(), [1, 2, 3], toolbatch_loop.concurrency_width()
    )
    assert any(ident != main_ident for ident in on_idents)


def test_microcompact_on_blanks_old_results(monkeypatch: pytest.MonkeyPatch) -> None:
    from colleague import turnbudget

    messages = [
        {"role": "tool", "tool_call_id": f"c{i}", "content": f"result {i}"} for i in range(15)
    ]
    budget = 1000
    last_prompt_tokens = 900  # 0.9 of budget, over the 0.85 trigger

    monkeypatch.setenv("COLLEAGUE_MICROCOMPACT", "0")
    off_count, off_indices = turnbudget.blank_old_results(
        list(messages), last_prompt_tokens, budget
    )
    assert (off_count, off_indices) == (0, [])

    monkeypatch.delenv("COLLEAGUE_MICROCOMPACT", raising=False)  # on: default enabled
    on_count, on_indices = turnbudget.blank_old_results(list(messages), last_prompt_tokens, budget)
    assert on_count > 0
    assert on_indices


def test_stream_guards_on_arms_watchdog(monkeypatch: pytest.MonkeyPatch) -> None:
    from colleague import streamguards

    monkeypatch.setenv("COLLEAGUE_STREAM_IDLE_TIMEOUT", "0")
    monkeypatch.setenv("COLLEAGUE_STREAM_MAX_LIFETIME", "0")
    assert streamguards.StreamGuards.from_env() is None

    monkeypatch.delenv("COLLEAGUE_STREAM_IDLE_TIMEOUT", raising=False)  # on: default 240s
    monkeypatch.delenv("COLLEAGUE_STREAM_MAX_LIFETIME", raising=False)  # on: default 900s
    guards = streamguards.StreamGuards.from_env()
    assert guards is not None
    assert guards.idle == streamguards.IDLE_DEFAULT
    assert guards.lifetime == streamguards.LIFETIME_DEFAULT


def test_tool_spill_on_writes_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from colleague import truncation

    truncation.reset_session_spill_bytes()
    big_text = "line\n" * 5000  # over both the char and line default budgets
    spill_dir = tmp_path / "spill"

    monkeypatch.setenv("COLLEAGUE_TOOL_SPILL", "0")
    off_result = truncation.truncate_output(big_text, 100, 10, spill_dir)
    assert "saved to disk" not in off_result or "not saved to disk" in off_result
    assert not spill_dir.exists() or not list(spill_dir.iterdir())

    monkeypatch.delenv("COLLEAGUE_TOOL_SPILL", raising=False)  # on: default enabled
    on_result = truncation.truncate_output(big_text, 100, 10, spill_dir)
    assert spill_dir.exists() and list(spill_dir.iterdir())
    assert "saved to:" in on_result


def test_prompt_variant_on_changes_system_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    from colleague import prompttext

    monkeypatch.setenv("COLLEAGUE_PROMPT_VARIANT", "v1")
    assert prompttext.default_system() == prompttext.V1_DEFAULT_SYSTEM

    monkeypatch.delenv("COLLEAGUE_PROMPT_VARIANT", raising=False)  # on: adopted qwen-code structure
    adopted = prompttext.default_system()
    assert adopted != prompttext.V1_DEFAULT_SYSTEM
    assert "# Core Mandates" in adopted  # only in the adopted structure


def test_tools_legacy_on_offers_search_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    from colleague.tools import curate_schemas

    monkeypatch.setenv("COLLEAGUE_TOOLS_LEGACY", "1")
    off_names = {s["function"]["name"] for s in curate_schemas(None)}
    assert "grep_search" not in off_names and "glob" not in off_names

    monkeypatch.delenv("COLLEAGUE_TOOLS_LEGACY", raising=False)  # on: default surface
    on_names = {s["function"]["name"] for s in curate_schemas(None)}
    assert {"grep_search", "glob"} <= on_names


def test_associate_model_on_resolves_seat(monkeypatch: pytest.MonkeyPatch) -> None:
    from colleague.associate_config import resolve_associate

    monkeypatch.delenv("COLLEAGUE_ASSOCIATE_MODEL", raising=False)
    off_result = resolve_associate({}, "http://main:8000/v1", "main-key")
    assert off_result is None

    monkeypatch.setenv("COLLEAGUE_ASSOCIATE_MODEL", "a-fast-model")  # on: declared
    on_result = resolve_associate({}, "http://main:8000/v1", "main-key")
    assert on_result is not None and on_result.model == "a-fast-model"


def test_prior_read_on_refuses_unread_edit(monkeypatch: pytest.MonkeyPatch) -> None:
    from colleague import editgate
    from colleague.tools import ToolError

    read_set = editgate.new_read_set()
    text = "line one\nline two\nline three\n"
    old = "line two"

    monkeypatch.setenv("COLLEAGUE_PRIOR_READ", "0")
    editgate.require_prior_read(read_set, "f.py", "f.py", text, old)  # no raise

    monkeypatch.delenv("COLLEAGUE_PRIOR_READ", raising=False)  # on: default enabled
    with pytest.raises(ToolError):
        editgate.require_prior_read(read_set, "f.py", "f.py", text, old)


# ---------------------------------------------------------------------------
# 3. The knob table <-> code coverage (doc task deliverable, still this task's
#    acceptance criterion: "a test asserts every knob in the table is read
#    somewhere in colleague/ (grep) and vice versa")
# ---------------------------------------------------------------------------

_DOC_PATH = Path(__file__).parent.parent / "docs" / "features" / "adopt-from-qwen-code.md"
_COLLEAGUE_DIR = Path(__file__).parent.parent / "colleague"

#: Modules this task's coverage check scans for introduced ``COLLEAGUE_*``
#: literals: every module carrying the ``adapted-from: qwen-code`` marker,
#: plus ``associate_config.py``/``editgate.py`` explicitly (already covered
#: by the marker scan today, named again so the check does not silently stop
#: covering them if the marker is ever dropped from either file).
_EXPLICIT_MODULES = ("associate_config.py", "editgate.py")

#: Knobs that predate this arc (read by one of the scanned modules, but not
#: INTRODUCED by it) — excluded from the "introduced literal" side of the
#: coverage check. Each is a long-standing colleague knob referenced in
#: CLAUDE.md's architecture section already.
_PRE_EXISTING_KNOBS = frozenset(
    {"COLLEAGUE_MAX_OUTPUT_CHARS", "COLLEAGUE_CONTEXT_BUDGET", "COLLEAGUE_TIMEOUT"}
)


def _table_knobs() -> "set[str]":
    """Every ``COLLEAGUE_*`` knob named in the doc's ``## Knobs`` table."""
    import re

    text = _DOC_PATH.read_text()
    return set(re.findall(r"`(COLLEAGUE_[A-Z_]+)`", text.split("## Knobs", 1)[-1]))


def _scanned_modules() -> "list[Path]":
    import re

    marker = re.compile(r"adapted-from: qwen-code")
    modules = {
        p for p in _COLLEAGUE_DIR.glob("*.py") if marker.search(p.read_text(errors="ignore"))
    }
    modules |= {_COLLEAGUE_DIR / name for name in _EXPLICIT_MODULES}
    return sorted(modules)


def _introduced_literals() -> "set[str]":
    """``COLLEAGUE_*`` string literals referenced by the scanned modules,
    minus the pre-existing knobs they merely READ (not introduce)."""
    import re

    literal_re = re.compile(r"""['"](COLLEAGUE_[A-Z_]+)['"]""")
    found: "set[str]" = set()
    for path in _scanned_modules():
        found |= set(literal_re.findall(path.read_text(errors="ignore")))
    return found - _PRE_EXISTING_KNOBS


def test_every_table_knob_is_read_in_colleague() -> None:
    """Every knob named in the doc table is actually referenced under colleague/."""
    table = _table_knobs()
    assert table, "the doc's ## Knobs table named no COLLEAGUE_* knob"
    for knob in table:
        hits = [p for p in _COLLEAGUE_DIR.rglob("*.py") if knob in p.read_text(errors="ignore")]
        assert hits, f"{knob} is in the doc table but not read anywhere in colleague/"


def test_every_introduced_literal_is_in_the_table() -> None:
    """Every COLLEAGUE_* literal the ported modules introduce is documented."""
    introduced = _introduced_literals()
    table = _table_knobs()
    missing = introduced - table
    assert not missing, f"introduced but undocumented knob(s): {sorted(missing)}"


def test_the_eleven_reversibility_knobs_are_all_in_the_table() -> None:
    """The eleven knobs this task's acceptance criteria name are all present."""
    table = _table_knobs()
    for knob in OFF_ENV:
        assert knob in table, f"reversibility knob {knob} missing from the doc table"
