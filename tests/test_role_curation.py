"""Role-aware tool-schema curation and role-aware ToolExecutor (t2)."""

from __future__ import annotations

import pytest

from colleague.purpose_schemas import PURPOSE_TOOL_NAMES
from colleague.roles import BUILTIN_ROLES, Role
from colleague.tools import SCHEMAS, ToolError, ToolExecutor, curate_schemas

# ---------------------------------------------------------------------------
# 1. curate_schemas(role) — subset filtering
# ---------------------------------------------------------------------------


class TestCurateSchemas:
    def test_writer_offers_purposes_and_drops_web(self) -> None:
        # t5 (operator decisions q9/q10): cortex reaches the web BY PURPOSE —
        # the writer's curated surface loses the raw web tool (still present in
        # SCHEMAS itself) and gains the six purpose schemas. Arm 4 (plan t11)
        # put the raw subagent/subagents BACK, so only web stays dropped.
        writer = BUILTIN_ROLES["writer"]
        curated_names = [s["function"]["name"] for s in curate_schemas(writer)]
        schema_names = [s["function"]["name"] for s in SCHEMAS]
        dropped = {"web"}
        assert curated_names == [n for n in schema_names if n not in dropped] + list(
            PURPOSE_TOOL_NAMES
        )
        assert set(dropped).isdisjoint(curated_names)
        assert set(PURPOSE_TOOL_NAMES) <= set(curated_names)

    def test_explorer_returns_only_allowlisted(self) -> None:
        explorer = BUILTIN_ROLES["explorer"]
        curated = curate_schemas(explorer)
        names = {s["function"]["name"] for s in curated}
        # "deepthink" (plan t4) is in explorer's allowlist but is deliberately
        # NOT part of SCHEMAS, so the default (deepthink=False) curated list
        # never includes it — see test_deepthink_tool.py for the opt-in path.
        from colleague.tools import DEEPTHINK

        assert names == set(explorer.tool_allowlist) - {DEEPTHINK}

    def test_unknown_allowlist_name_is_skipped(self) -> None:
        # A role whose allow-list contains a name not in SCHEMAS (e.g. a tool a
        # later task will add, or a typo) must not raise — it is simply skipped.
        role = Role(
            name="custom",
            prompt_fragment="",
            tool_allowlist=("read_file", "not_a_real_tool", "list_dir"),
            skill_subset=None,
            read_only=True,
        )
        curated = curate_schemas(role)
        names = {s["function"]["name"] for s in curated}
        assert names == {"read_file", "list_dir"}
        assert "not_a_real_tool" not in names

    def test_empty_allowlist_returns_empty(self) -> None:
        role = Role(
            name="empty",
            prompt_fragment="",
            tool_allowlist=(),
            skill_subset=None,
            read_only=True,
        )
        assert curate_schemas(role) == []


# ---------------------------------------------------------------------------
# 2. ToolExecutor role-awareness — allow-list enforcement
# ---------------------------------------------------------------------------


class TestRoleAwareExecutor:
    def test_no_allowlist_allows_everything(self, tmp_path) -> None:
        # Construction with no allow-list stays byte-identical to today.
        ex = ToolExecutor(tmp_path)
        out = ex.execute("write_file", {"path": "a.txt", "content": "ok"})
        assert out.changed_file == "a.txt"

    def test_allowlist_refuses_withheld_tool(self, tmp_path) -> None:
        ex = ToolExecutor(tmp_path, allowlist=("read_file", "list_dir"))
        with pytest.raises(ToolError):
            ex.execute("write_file", {"path": "b.txt", "content": "nope"})

    def test_allowlist_allows_permitted_tool(self, tmp_path) -> None:
        (tmp_path / "c.txt").write_text("data")
        ex = ToolExecutor(tmp_path, allowlist=("read_file",))
        out = ex.execute("read_file", {"path": "c.txt"})
        # read_file grounds each line with its true 1-based number (#240).
        assert out.result == "     1\tdata"

    def test_role_object_as_allowlist(self, tmp_path) -> None:
        explorer = BUILTIN_ROLES["explorer"]
        ex = ToolExecutor(tmp_path, allowlist=explorer)
        # read_file is in explorer's allowlist
        (tmp_path / "d.txt").write_text("hello")
        out = ex.execute("read_file", {"path": "d.txt"})
        assert out.result == "     1\thello"
        # write_file is not
        with pytest.raises(ToolError):
            ex.execute("write_file", {"path": "e.txt", "content": "nope"})


# ---------------------------------------------------------------------------
# 3. Read-only role schemas exclude write tools; executor refuses them
# ---------------------------------------------------------------------------


class TestReadOnlyRole:
    @pytest.mark.parametrize("role_name", ["explorer", "planner", "reviewer"])
    def test_readonly_schema_excludes_write_tools(self, role_name: str) -> None:
        role = BUILTIN_ROLES[role_name]
        curated = curate_schemas(role)
        names = {s["function"]["name"] for s in curated}
        for forbidden in ("write_file", "edit_file", "run_command"):
            assert forbidden not in names, f"{role_name} schema must not include {forbidden}"

    @pytest.mark.parametrize("role_name", ["explorer", "planner", "reviewer"])
    def test_readonly_executor_refuses_write_tools(self, role_name: str, tmp_path) -> None:
        role = BUILTIN_ROLES[role_name]
        ex = ToolExecutor(tmp_path, allowlist=role)
        for tool_name in ("write_file", "edit_file", "run_command"):
            with pytest.raises(ToolError):
                if tool_name == "write_file":
                    ex.execute(tool_name, {"path": "x.txt", "content": "no"})
                elif tool_name == "edit_file":
                    ex.execute(
                        tool_name,
                        {"path": "x.txt", "old_string": "a", "new_string": "b"},
                    )
                else:
                    ex.execute(tool_name, {"command": "echo nope"})


# ---------------------------------------------------------------------------
# 4. subagent and subagents schemas gain optional "role" parameter
# ---------------------------------------------------------------------------


class TestSubagentRoleParam:
    def _find_schema(self, name: str) -> dict:
        for s in SCHEMAS:
            if s["function"]["name"] == name:
                return s
        raise ValueError(f"schema {name} not found")

    def test_subagent_schema_has_optional_role(self) -> None:
        schema = self._find_schema("subagent")
        props = schema["function"]["parameters"]["properties"]
        assert "role" in props, "subagent schema must have 'role' property"
        assert "role" not in schema["function"]["parameters"].get(
            "required", []
        ), "'role' must NOT be required on subagent"

    def test_subagents_schema_has_optional_role(self) -> None:
        schema = self._find_schema("subagents")
        props = schema["function"]["parameters"]["properties"]
        assert "role" in props, "subagents schema must have 'role' property"
        assert "role" not in schema["function"]["parameters"].get(
            "required", []
        ), "'role' must NOT be required on subagents"

    def test_subagent_schema_rest_unchanged(self) -> None:
        schema = self._find_schema("subagent")
        props = schema["function"]["parameters"]["properties"]
        # The existing properties must still be present.
        assert "instruction" in props
        assert "engine" in props
        assert "model" in props
        assert "role" in props
        assert schema["function"]["parameters"]["required"] == ["instruction"]

    def test_subagents_schema_rest_unchanged(self) -> None:
        schema = self._find_schema("subagents")
        props = schema["function"]["parameters"]["properties"]
        # The existing property must still be present.
        assert "instructions" in props
        assert "role" in props
        assert schema["function"]["parameters"]["required"] == ["instructions"]
