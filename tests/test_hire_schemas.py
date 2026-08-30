"""t10 — ``colleague/hire_schemas.py``: the two hire tool schemas, the
``COLLEAGUE_HIRE`` hidden rule and the ``curate_schemas`` surface splice
(plan ``docs/plans/2026-08-30-delegation-follow-ups-a7-p3-hire.md``, covers
c17/h8).

Declaration + splice only: the ``hire_colleague`` handler is t12 and the
``assign_to_colleague`` handler is t13 — this suite never executes either
tool. The byte-identical armed/unarmed run-level case lives in
``tests/test_purpose_tools_byte_identical.py`` (same task).
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from colleague import hire_schemas, prompttext, roles
from colleague.tools import curate_schemas

EXPECTED_NAMES = ("hire_colleague", "assign_to_colleague")

#: The properties a hire schema must never expose — the model cannot pick a
#: rung, a backend, or a free-form role (mirrors purpose_schemas c24/h27; the
#: only role choice is the CLOSED ``base_role`` enum of builtin names).
FORBIDDEN_PROPERTIES = ("effort", "model", "engine", "role")


@dataclass
class _Config:
    hire: bool = False


def _schema(name: str) -> dict:
    return hire_schemas.HIRE_SCHEMAS[name]["function"]


# ---------------------------------------------------------------------------
# The two schemas
# ---------------------------------------------------------------------------


class TestHireSchemas:
    def test_names_pinned_in_order(self) -> None:
        assert hire_schemas.HIRE_TOOL_NAMES == EXPECTED_NAMES

    def test_schemas_keyed_by_name(self) -> None:
        assert tuple(hire_schemas.HIRE_SCHEMAS) == EXPECTED_NAMES
        for name in EXPECTED_NAMES:
            assert _schema(name)["name"] == name

    def test_openai_function_shape(self) -> None:
        for name in EXPECTED_NAMES:
            schema = hire_schemas.HIRE_SCHEMAS[name]
            assert schema["type"] == "function"
            fn = schema["function"]
            assert fn["description"]
            assert fn["parameters"]["type"] == "object"

    def test_hire_colleague_properties(self) -> None:
        params = _schema("hire_colleague")["parameters"]
        assert set(params["properties"]) == {"purpose", "when", "base_role", "prompt"}
        assert params["required"] == ["purpose", "when", "base_role", "prompt"]

    def test_base_role_enum_is_the_builtin_names(self) -> None:
        enum = _schema("hire_colleague")["parameters"]["properties"]["base_role"]["enum"]
        assert enum == sorted(roles.BUILTIN_ROLES)

    def test_hire_caps_on_the_schema(self) -> None:
        props = _schema("hire_colleague")["parameters"]["properties"]
        assert props["prompt"]["maxLength"] == hire_schemas.PROMPT_MAX_CHARS == 2000
        assert props["when"]["maxLength"] == hire_schemas.WHEN_MAX_CHARS == 200

    def test_assign_to_colleague_properties(self) -> None:
        params = _schema("assign_to_colleague")["parameters"]
        assert set(params["properties"]) == {"agent_id", "task", "acceptance"}
        assert params["required"] == ["agent_id", "task"]
        assert params["properties"]["acceptance"]["type"] == "array"

    @pytest.mark.parametrize("name", EXPECTED_NAMES)
    @pytest.mark.parametrize("forbidden", FORBIDDEN_PROPERTIES)
    def test_no_seat_choosing_property(self, name: str, forbidden: str) -> None:
        """No effort/model/engine/role property — base_role is a closed enum,
        never a free role string (the purpose-schemas c24/h27 rule)."""
        assert forbidden not in _schema(name)["parameters"]["properties"]


# ---------------------------------------------------------------------------
# The hidden rule: both names hidden unless config.hire is armed
# ---------------------------------------------------------------------------


class TestHiddenRule:
    def test_hidden_without_config(self) -> None:
        assert hire_schemas.hidden_names(None) == frozenset(EXPECTED_NAMES)

    def test_hidden_when_unarmed(self) -> None:
        assert hire_schemas.hidden_names(_Config(hire=False)) == frozenset(EXPECTED_NAMES)

    def test_visible_when_armed(self) -> None:
        assert hire_schemas.hidden_names(_Config(hire=True)) == frozenset()

    def test_config_without_hire_attribute_is_unarmed(self) -> None:
        assert hire_schemas.hidden_names(object()) == frozenset(EXPECTED_NAMES)

    def test_offered_requires_allow_and_armed(self) -> None:
        allow = {"hire_colleague", "assign_to_colleague", "read_file"}
        armed = _Config(hire=True)
        for name in EXPECTED_NAMES:
            assert hire_schemas.offered(name, allow, armed)
            assert not hire_schemas.offered(name, allow, None)
            assert not hire_schemas.offered(name, {"read_file"}, armed)
            assert hire_schemas.offered(name, None, armed)


# ---------------------------------------------------------------------------
# The surface splice + allow-list + prompt sentence
# ---------------------------------------------------------------------------


class TestSurfaceSplice:
    def test_writer_allowlist_carries_both_names(self) -> None:
        allowlist = roles.BUILTIN_ROLES["writer"].tool_allowlist
        for name in EXPECTED_NAMES:
            assert name in allowlist

    def test_unarmed_writer_surface_hides_both(self) -> None:
        offered = {s["function"]["name"] for s in curate_schemas(roles.BUILTIN_ROLES["writer"])}
        assert not offered & set(EXPECTED_NAMES)

    def test_armed_writer_surface_offers_both_appended_like_purpose(self) -> None:
        armed = curate_schemas(roles.BUILTIN_ROLES["writer"], config=_Config(hire=True))
        names = [s["function"]["name"] for s in armed]
        assert names[-2:] == list(EXPECTED_NAMES)  # appended, after the purpose splice
        unarmed = {s["function"]["name"] for s in curate_schemas(roles.BUILTIN_ROLES["writer"])}
        assert set(names) - unarmed == set(EXPECTED_NAMES)

    def test_full_surface_contract_untouched_even_armed(self) -> None:
        """``curate_schemas(None)`` is the pinned no-role raw surface — the
        hire splice, like the purpose splice, only reaches a concrete role."""
        names = {s["function"]["name"] for s in curate_schemas(None, config=_Config(hire=True))}
        assert not names & set(EXPECTED_NAMES)

    def test_role_without_the_names_never_offers_them(self) -> None:
        armed = curate_schemas(roles.BUILTIN_ROLES["explorer"], config=_Config(hire=True))
        assert not {s["function"]["name"] for s in armed} & set(EXPECTED_NAMES)


class TestPromptSentence:
    def test_section_table_carries_hire(self) -> None:
        assert "HIRE" in prompttext.SECTION_TABLE
        sentence = prompttext.SECTION_TABLE["HIRE"]
        assert "hire_colleague" in sentence
        assert "assign_to_colleague" in sentence
        # ONE sentence: a single terminating period, no internal breaks.
        assert sentence.count(".") == 1
        assert sentence.endswith(".")
        assert "\n" not in sentence

    def test_unarmed_default_prompt_is_untouched(self) -> None:
        assert prompttext.SECTION_TABLE["HIRE"] not in prompttext.default_system()
        assert prompttext.default_system() == prompttext.V1_DEFAULT_SYSTEM

    def test_armed_v1_prompt_gains_exactly_the_sentence(self) -> None:
        armed = prompttext.default_system(hire=True)
        assert armed == prompttext.V1_DEFAULT_SYSTEM + "\n\n" + prompttext.SECTION_TABLE["HIRE"]

    def test_armed_adopted_prompt_gains_the_sentence(self) -> None:
        unarmed = prompttext.default_system("x", variant="qwen")
        armed = prompttext.default_system("x", variant="qwen", hire=True)
        assert prompttext.SECTION_TABLE["HIRE"] not in unarmed
        assert prompttext.SECTION_TABLE["HIRE"] in armed

    def test_env_arming_reaches_default_system(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``hire=None`` (the default) falls back to the env knob so the
        loop's own layer-free fallback prompt agrees with the armed run."""
        monkeypatch.setenv("COLLEAGUE_HIRE", "1")
        assert prompttext.default_system().endswith(prompttext.SECTION_TABLE["HIRE"])
        monkeypatch.setenv("COLLEAGUE_HIRE", "0")
        assert prompttext.default_system() == prompttext.V1_DEFAULT_SYSTEM
