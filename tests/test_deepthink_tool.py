"""Tests for the ``deepthink`` loop tool (plan t4 / spec c10(a), c5, h14).

Written TDD — run these before implementing to see them fail, then implement to
make them green. Scope: colleague/tools.py + colleague/roles.py additions only;
loop wiring (offering the tool only when a dual-model config is present,
recording calls onto TaskResult.deepthink) is task t5.

Covers:
 - SCHEMAS stays EXACTLY as today (no ``deepthink``) — a single-model run's
   offered tool list is byte-identical.
 - ``curate_schemas(role, deepthink=False)`` (the default) is byte-identical to
   before this feature existed, for ``role=None`` and every BUILTIN_ROLE.
 - ``curate_schemas(role, deepthink=True)`` appends the deepthink schema for
   ``role=None`` and every BUILTIN_ROLE, with the question-required /
   context-optional shape pinned.
 - The executor dispatches a ``deepthink`` call to the injected callable and
   degrades gracefully (never raises) when no callable is injected.
 - The role-aware allow-list refuses ``deepthink`` for a role that withholds
   it, exactly like any other tool; every BUILTIN_ROLE now lists it.
 - The tool description instructs judgment-escalation, not mechanics — pinned
   so the prompt contract is drift-tested.
"""

from __future__ import annotations

import pytest

from colleague.roles import BUILTIN_ROLES, Role
from colleague.tools import (
    DEEPTHINK,
    DEEPTHINK_SCHEMA,
    SCHEMAS,
    TOOL_NAMES,
    ToolError,
    ToolExecutor,
    curate_schemas,
)

# ---------------------------------------------------------------------------
# 1. SCHEMAS / TOOL_NAMES stay exactly as today — no deepthink
# ---------------------------------------------------------------------------


def test_schemas_has_no_deepthink_entry() -> None:
    """The module-level SCHEMAS list must not carry a 'deepthink' schema — a
    single-model run offers exactly today's tool list."""
    names = [s["function"]["name"] for s in SCHEMAS]
    assert DEEPTHINK not in names
    assert "deepthink" not in TOOL_NAMES


def test_deepthink_schema_is_a_distinct_module_constant() -> None:
    """DEEPTHINK_SCHEMA exists as its own constant, not folded into SCHEMAS."""
    assert DEEPTHINK_SCHEMA["function"]["name"] == "deepthink"
    assert DEEPTHINK_SCHEMA not in SCHEMAS


# ---------------------------------------------------------------------------
# 2. curate_schemas default (deepthink=False) is byte-identical to before
# ---------------------------------------------------------------------------


class TestCurateSchemasDefaultByteIdentical:
    def test_role_none_default_has_no_deepthink(self) -> None:
        curated = curate_schemas(None)
        names = {s["function"]["name"] for s in curated}
        assert DEEPTHINK not in names
        # And the default (no role filter) is the full SCHEMAS list.
        assert names == {s["function"]["name"] for s in SCHEMAS}

    @pytest.mark.parametrize("role_name", sorted(BUILTIN_ROLES))
    def test_every_builtin_role_default_has_no_deepthink(self, role_name: str) -> None:
        curated = curate_schemas(role_name)
        names = {s["function"]["name"] for s in curated}
        assert DEEPTHINK not in names, f"{role_name}'s default schema list must omit deepthink"

    @pytest.mark.parametrize("role_name", sorted(BUILTIN_ROLES))
    def test_default_kwarg_explicit_false_matches_omitted(self, role_name: str) -> None:
        # deepthink=False (explicit) must be byte-identical to omitting the kwarg.
        role = BUILTIN_ROLES[role_name]
        implicit = curate_schemas(role)
        explicit = curate_schemas(role, deepthink=False)
        assert [s["function"]["name"] for s in implicit] == [
            s["function"]["name"] for s in explicit
        ]


# ---------------------------------------------------------------------------
# 3. curate_schemas(role, deepthink=True) appends the schema
# ---------------------------------------------------------------------------


class TestCurateSchemasDeepthinkOptIn:
    def test_role_none_with_deepthink_true_includes_it(self) -> None:
        curated = curate_schemas(None, deepthink=True)
        names = {s["function"]["name"] for s in curated}
        assert DEEPTHINK in names
        # Full surface + deepthink, nothing dropped.
        assert names == {s["function"]["name"] for s in SCHEMAS} | {DEEPTHINK}

    @pytest.mark.parametrize("role_name", sorted(BUILTIN_ROLES))
    def test_every_builtin_role_with_deepthink_true_includes_it(self, role_name: str) -> None:
        curated = curate_schemas(role_name, deepthink=True)
        names = {s["function"]["name"] for s in curated}
        assert DEEPTHINK in names, f"{role_name} must be offered deepthink when opted in"

    def test_role_object_form_also_honors_deepthink_kwarg(self) -> None:
        role = BUILTIN_ROLES["reviewer"]
        curated = curate_schemas(role, deepthink=True)
        names = {s["function"]["name"] for s in curated}
        assert DEEPTHINK in names

    def test_deepthink_true_never_appended_when_role_withholds_it(self) -> None:
        # A custom role whose allowlist does NOT include "deepthink" must never
        # have it appended, even with deepthink=True.
        role = Role(
            name="no-deepthink",
            prompt_fragment="",
            tool_allowlist=("read_file", "finish"),
            skill_subset=None,
            read_only=True,
        )
        curated = curate_schemas(role, deepthink=True)
        names = {s["function"]["name"] for s in curated}
        assert DEEPTHINK not in names

    def test_appended_schema_is_the_shared_constant(self) -> None:
        curated = curate_schemas(None, deepthink=True)
        schema = next(s for s in curated if s["function"]["name"] == DEEPTHINK)
        assert schema is DEEPTHINK_SCHEMA


# ---------------------------------------------------------------------------
# 4. Schema shape: question required, context optional
# ---------------------------------------------------------------------------


class TestDeepthinkSchemaShape:
    def test_question_and_context_properties_present(self) -> None:
        props = DEEPTHINK_SCHEMA["function"]["parameters"]["properties"]
        assert "question" in props
        assert "context" in props
        assert props["question"]["type"] == "string"
        assert props["context"]["type"] == "string"

    def test_question_required_context_optional(self) -> None:
        required = DEEPTHINK_SCHEMA["function"]["parameters"].get("required", [])
        assert required == ["question"]
        assert "context" not in required


# ---------------------------------------------------------------------------
# 5. Description text — judgment-not-mechanics escalation, pinned phrases
# ---------------------------------------------------------------------------


class TestDeepthinkDescription:
    def _description(self) -> str:
        return DEEPTHINK_SCHEMA["function"]["description"]

    def test_instructs_escalating_judgment(self) -> None:
        desc = self._description().lower()
        assert "escalate" in desc
        assert "judgment" in desc

    def test_instructs_not_mechanical_work(self) -> None:
        desc = self._description().lower()
        assert "mechanical" in desc
        assert "read files" in desc or "read_file" in desc
        assert "run commands" in desc or "run_command" in desc

    def test_instructs_self_contained_digest(self) -> None:
        desc = self._description().lower()
        assert "self-contained" in desc
        assert "digest" in desc

    def test_instructs_no_repo_or_conversation_access(self) -> None:
        desc = self._description().lower()
        assert "no repo access" in desc
        assert "no conversation history" in desc

    def test_instructs_use_sparingly(self) -> None:
        desc = self._description().lower()
        assert "sparingly" in desc
        assert "slower" in desc


# ---------------------------------------------------------------------------
# 6. Executor dispatch — injected callable
# ---------------------------------------------------------------------------


class TestDeepthinkExecutorDispatch:
    def test_injected_callable_receives_question_and_context(self, tmp_path) -> None:
        received: dict[str, str] = {}

        def fake_deepthink(question: str, context: str) -> str:
            received["question"] = question
            received["context"] = context
            return "the verdict is X"

        ex = ToolExecutor(tmp_path, deepthink=fake_deepthink)
        out = ex.execute(DEEPTHINK, {"question": "is this design sound?", "context": "diff here"})
        assert received == {"question": "is this design sound?", "context": "diff here"}
        assert out.result == "the verdict is X"

    def test_return_string_comes_back_as_tool_result(self, tmp_path) -> None:
        ex = ToolExecutor(tmp_path, deepthink=lambda q, c: f"answer to: {q}")
        out = ex.execute(DEEPTHINK, {"question": "pick A or B"})
        assert out.result == "answer to: pick A or B"

    def test_context_defaults_sensibly_when_omitted(self, tmp_path) -> None:
        received: dict[str, str] = {}

        def fake_deepthink(question: str, context: str) -> str:
            received["context"] = context
            return "ok"

        ex = ToolExecutor(tmp_path, deepthink=fake_deepthink)
        ex.execute(DEEPTHINK, {"question": "no context supplied"})
        assert received["context"] == ""
        assert isinstance(received["context"], str)

    def test_missing_question_raises_tool_error(self, tmp_path) -> None:
        ex = ToolExecutor(tmp_path, deepthink=lambda q, c: "unused")
        with pytest.raises(ToolError):
            ex.execute(DEEPTHINK, {})

    def test_does_not_write_or_change_files(self, tmp_path) -> None:
        ex = ToolExecutor(tmp_path, deepthink=lambda q, c: "verdict")
        ex.execute(DEEPTHINK, {"question": "q"})
        assert ex.changed == set()


# ---------------------------------------------------------------------------
# 7. Executor without an injected callable — clean degradation, never raises
# ---------------------------------------------------------------------------


class TestDeepthinkExecutorUnconfigured:
    def test_no_injected_callable_returns_error_string(self, tmp_path) -> None:
        ex = ToolExecutor(tmp_path)  # deepthink=None by default
        out = ex.execute(DEEPTHINK, {"question": "anything"})
        assert "not configured" in out.result.lower()
        assert out.finished is False

    def test_no_injected_callable_never_raises(self, tmp_path) -> None:
        ex = ToolExecutor(tmp_path)
        # Must not raise ToolError or any other exception.
        out = ex.execute(DEEPTHINK, {"question": "anything", "context": "stuff"})
        assert isinstance(out.result, str)


# ---------------------------------------------------------------------------
# 8. Role allow-list enforcement — deepthink refused like any other tool
# ---------------------------------------------------------------------------


class TestDeepthinkRoleAllowlist:
    def test_role_withholding_deepthink_refuses_the_call(self, tmp_path) -> None:
        role = Role(
            name="no-deepthink",
            prompt_fragment="",
            tool_allowlist=("read_file", "finish"),
            skill_subset=None,
            read_only=True,
        )
        ex = ToolExecutor(tmp_path, allowlist=role, deepthink=lambda q, c: "unused")
        with pytest.raises(ToolError):
            ex.execute(DEEPTHINK, {"question": "q"})

    def test_plain_tuple_allowlist_without_deepthink_refuses(self, tmp_path) -> None:
        ex = ToolExecutor(
            tmp_path, allowlist=("read_file", "finish"), deepthink=lambda q, c: "unused"
        )
        with pytest.raises(ToolError):
            ex.execute(DEEPTHINK, {"question": "q"})

    @pytest.mark.parametrize("role_name", sorted(BUILTIN_ROLES))
    def test_every_builtin_role_lists_deepthink(self, role_name: str) -> None:
        """Pin the surface: every built-in role — including the read-only ones
        and the full-surface writer — allows deepthink (it is pure computation:
        one bounded completion, no writes, no shell; this does not weaken the
        read-only guarantee)."""
        role = BUILTIN_ROLES[role_name]
        assert DEEPTHINK in role.tool_allowlist, f"{role_name} must list deepthink"

    @pytest.mark.parametrize("role_name", sorted(BUILTIN_ROLES))
    def test_every_builtin_role_permits_the_call_via_executor(
        self, role_name: str, tmp_path
    ) -> None:
        role = BUILTIN_ROLES[role_name]
        ex = ToolExecutor(tmp_path, allowlist=role, deepthink=lambda q, c: "verdict")
        out = ex.execute(DEEPTHINK, {"question": "q"})
        assert out.result == "verdict"

    @pytest.mark.parametrize("role_name", ("explorer", "planner", "reviewer", "validator"))
    def test_readonly_roles_still_exclude_write_tools_alongside_deepthink(
        self, role_name: str
    ) -> None:
        # Adding deepthink must not smuggle in any write-capable tool.
        role = BUILTIN_ROLES[role_name]
        allow = set(role.tool_allowlist)
        assert DEEPTHINK in allow
        for forbidden in ("write_file", "edit_file", "run_command"):
            assert forbidden not in allow
