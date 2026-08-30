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


# --- t10: the purpose-tool surface (post-t5, cortex's curated writer role) --


def _writer_schema_names(schemas):
    return {s["function"]["name"] for s in schemas}


def test_apply_armed_facts_curated_writer_surface_has_no_raw_subagent():
    """Sanity: cortex's curated (``writer``) surface holds the purpose tools
    and, post-t5, neither raw delegation tool — the case this test module
    otherwise never exercises via the raw :data:`SCHEMAS` constant. Arm 4
    (plan t11) briefly restored the raw pair here and was rejected on measured
    evidence, so the expectation is changed back, never relaxed."""
    from colleague.tools import curate_schemas

    names = _writer_schema_names(curate_schemas("writer"))
    assert "subagent" not in names
    assert "subagents" not in names
    assert "web" not in names
    assert {"web_survey", "code_survey", "handover_to_colleague"} <= names  # surface has all three


def test_apply_armed_facts_splices_onto_web_survey_code_survey_handover():
    from colleague.tools import curate_schemas

    curated = curate_schemas("writer")
    before = {s["function"]["name"]: s["function"]["description"] for s in curated}
    result = apply_armed_facts(curated, _ARMED)
    assert result is not curated
    sentence = armed_facts(_ARMED)
    changed = set()
    for entry in result:
        name = entry["function"]["name"]
        desc = entry["function"]["description"]
        if name in ("web_survey", "code_survey"):
            assert desc == before[name] + " " + sentence
            assert desc.count(sentence) == 1
            changed.add(name)
        else:
            assert desc == before[name]
    # ``apply_armed_facts`` also targets the raw subagent/subagents, but they
    # are absent from the curated writer surface again (arm 4 / plan t11 was
    # rejected on measured evidence), so the sentence lands on two
    # descriptions. The handover child is a cortex writer: no scout sentence.
    assert changed == {"web_survey", "code_survey"}


def test_apply_armed_facts_curated_writer_surface_unarmed_returns_same_list():
    from colleague.tools import curate_schemas

    curated = curate_schemas("writer")
    assert apply_armed_facts(curated, _UNARMED) is curated


def test_apply_armed_facts_still_splices_subagent_when_present_alongside_purpose_tools():
    """A manual/hypothetical schema list that still carries the raw delegation
    tools ALONGSIDE the purpose tools (e.g. a manual role config) gets the
    sentence on every one of the five names present — this module never
    assumes the two surfaces are mutually exclusive."""
    from colleague.tools import curate_schemas

    manual = curate_schemas("writer") + [
        s for s in SCHEMAS if s["function"]["name"] in ("subagent", "subagents")
    ]
    before = {s["function"]["name"]: s["function"]["description"] for s in manual}
    result = apply_armed_facts(manual, _ARMED)
    sentence = armed_facts(_ARMED)
    target_names = {"web_survey", "code_survey", "subagent", "subagents"}
    changed = set()
    for entry in result:
        name = entry["function"]["name"]
        desc = entry["function"]["description"]
        if name in target_names:
            assert desc == before[name] + " " + sentence
            changed.add(name)
        else:
            assert desc == before[name]
    assert changed == target_names
