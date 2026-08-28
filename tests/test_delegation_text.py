"""Task t8 — armed-facts sentence on the delegation surface (spec c30/c31, h19/h20).

Pins: ``armed_facts`` is empty when ``config.associate`` is ``None``, else ONE
fact-only sentence (no digits, no time units, no imperative verbs);
``apply_armed_facts`` rewrites only the ``subagent``/``subagents`` tool
descriptions and returns the SAME list object, unchanged, when unarmed.
"""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

from colleague.delegation_text import apply_armed_facts, armed_facts
from colleague.tools import SCHEMAS

_UNARMED = SimpleNamespace(associate=None)
_ARMED = SimpleNamespace(associate=object())

_TIME_UNIT_WORDS = ("second", "minute", "ms", "hour")
_IMPERATIVE_WORDS = ("delegate", "must", "should", "always")


def test_armed_facts_empty_when_unarmed():
    assert armed_facts(_UNARMED) == ""


def test_armed_facts_empty_when_config_has_no_associate_attr():
    assert armed_facts(SimpleNamespace()) == ""


def test_armed_facts_is_one_sentence_when_armed():
    sentence = armed_facts(_ARMED)
    assert sentence
    # exactly one sentence: a single terminal period, not mid-sentence too
    assert sentence.count(".") == 1
    assert sentence.endswith(".")


def test_armed_facts_has_no_digits():
    sentence = armed_facts(_ARMED)
    assert re.search(r"\d", sentence) is None


@pytest.mark.parametrize("word", _TIME_UNIT_WORDS)
def test_armed_facts_has_no_time_units(word):
    sentence = armed_facts(_ARMED)
    assert re.search(re.escape(word), sentence, re.I) is None


@pytest.mark.parametrize("word", _IMPERATIVE_WORDS)
def test_armed_facts_has_no_imperative_words(word):
    sentence = armed_facts(_ARMED)
    assert re.search(rf"\b{re.escape(word)}\b", sentence, re.I) is None


def test_armed_facts_conveys_speed_readonly_thinking_off_and_digest_review():
    sentence = armed_facts(_ARMED).lower()
    assert "quick" in sentence or "fast" in sentence
    assert "reasoning" in sentence or "thinking" in sentence
    assert "digest" in sentence
    assert "review" in sentence


# --- apply_armed_facts -------------------------------------------------------


def test_apply_armed_facts_unarmed_returns_same_list_object():
    result = apply_armed_facts(SCHEMAS, _UNARMED)
    assert result is SCHEMAS


def test_apply_armed_facts_unarmed_is_byte_identical_to_v164_fixture():
    subagent = next(s for s in SCHEMAS if s["function"]["name"] == "subagent")
    subagents = next(s for s in SCHEMAS if s["function"]["name"] == "subagents")
    result = apply_armed_facts(SCHEMAS, _UNARMED)
    result_subagent = next(s for s in result if s["function"]["name"] == "subagent")
    result_subagents = next(s for s in result if s["function"]["name"] == "subagents")
    assert result_subagent is subagent
    assert result_subagents is subagents


def test_apply_armed_facts_armed_rewrites_only_delegation_descriptions():
    before = {s["function"]["name"]: s["function"]["description"] for s in SCHEMAS}
    result = apply_armed_facts(SCHEMAS, _ARMED)
    assert result is not SCHEMAS
    assert len(result) == len(SCHEMAS)
    sentence = armed_facts(_ARMED)
    changed = 0
    for entry in result:
        name = entry["function"]["name"]
        desc = entry["function"]["description"]
        if name in ("subagent", "subagents"):
            assert desc == before[name] + " " + sentence
            assert desc.count(sentence) == 1
            changed += 1
        else:
            assert desc == before[name]
    assert changed == 2


def test_apply_armed_facts_armed_leaves_original_schemas_untouched():
    before_subagent_desc = next(s for s in SCHEMAS if s["function"]["name"] == "subagent")[
        "function"
    ]["description"]
    apply_armed_facts(SCHEMAS, _ARMED)
    after_subagent_desc = next(s for s in SCHEMAS if s["function"]["name"] == "subagent")[
        "function"
    ]["description"]
    assert before_subagent_desc == after_subagent_desc


def test_apply_armed_facts_armed_changes_nothing_else_about_the_schema():
    result = apply_armed_facts(SCHEMAS, _ARMED)
    result_subagent = next(s for s in result if s["function"]["name"] == "subagent")
    original_subagent = next(s for s in SCHEMAS if s["function"]["name"] == "subagent")
    assert result_subagent["function"]["parameters"] == original_subagent["function"]["parameters"]
    assert result_subagent["type"] == original_subagent["type"]
