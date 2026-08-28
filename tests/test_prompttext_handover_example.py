"""Task t8 — the opt-in HANDOVER_EXAMPLE prompt section (spec c30/c31, h19/h20).

Pins: HANDOVER_EXAMPLE is listed in SECTION_TABLE, EXCLUDED from the default
COLLEAGUE_PROMPT_VARIANT (byte-identical to v1.64.0), and included only under
the named ``qwen-handover`` variant or the COLLEAGUE_PROMPT_SECTIONS opt-in.
"""

from __future__ import annotations

from pathlib import Path

from colleague.prompttext import (
    HANDOVER_EXAMPLE,
    SECTION_TABLE,
    V1_DEFAULT_SYSTEM,
    default_system,
)

SNAP = Path(__file__).parent / "snapshots"


def test_handover_example_listed_in_section_table():
    assert SECTION_TABLE["HANDOVER_EXAMPLE"] is HANDOVER_EXAMPLE


def test_handover_example_is_a_worked_example():
    assert "<example>" in HANDOVER_EXAMPLE
    assert "</example>" in HANDOVER_EXAMPLE
    assert "subagent" in HANDOVER_EXAMPLE


def test_default_variant_excludes_handover_example(monkeypatch):
    monkeypatch.delenv("COLLEAGUE_PROMPT_VARIANT", raising=False)
    monkeypatch.delenv("COLLEAGUE_PROMPT_SECTIONS", raising=False)
    prompt = default_system("any")
    assert HANDOVER_EXAMPLE not in prompt
    assert "Hand-over, Review, Collect" not in prompt


def test_default_prompt_is_byte_identical_to_v164_fixture(monkeypatch):
    monkeypatch.delenv("COLLEAGUE_PROMPT_VARIANT", raising=False)
    monkeypatch.delenv("COLLEAGUE_PROMPT_SECTIONS", raising=False)
    pinned = (SNAP / "prompttext_v1.txt").read_text()
    assert default_system("any") == pinned == V1_DEFAULT_SYSTEM


def test_qwen_variant_without_opt_in_excludes_handover_example(monkeypatch):
    monkeypatch.delenv("COLLEAGUE_PROMPT_SECTIONS", raising=False)
    prompt = default_system("x", variant="qwen")
    assert HANDOVER_EXAMPLE not in prompt


def test_named_variant_qwen_handover_includes_it(monkeypatch):
    monkeypatch.delenv("COLLEAGUE_PROMPT_SECTIONS", raising=False)
    prompt = default_system("x", variant="qwen-handover")
    assert HANDOVER_EXAMPLE in prompt


def test_sections_env_opt_in_includes_it_under_qwen_variant(monkeypatch):
    prompt = default_system("x", variant="qwen", sections="HANDOVER_EXAMPLE")
    assert HANDOVER_EXAMPLE in prompt


def test_sections_opt_in_is_ignored_under_v1_variant(monkeypatch):
    prompt = default_system("x", variant="v1", sections="HANDOVER_EXAMPLE")
    assert prompt == V1_DEFAULT_SYSTEM
    assert HANDOVER_EXAMPLE not in prompt


def test_unknown_section_name_is_ignored(monkeypatch):
    prompt = default_system("x", variant="qwen", sections="BOGUS_SECTION")
    assert HANDOVER_EXAMPLE not in prompt


def test_env_var_opt_in(monkeypatch):
    monkeypatch.setenv("COLLEAGUE_PROMPT_VARIANT", "qwen")
    monkeypatch.setenv("COLLEAGUE_PROMPT_SECTIONS", "HANDOVER_EXAMPLE")
    prompt = default_system("x")
    assert HANDOVER_EXAMPLE in prompt
