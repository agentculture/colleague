"""Tests for the memory loop tool — schema, dispatch, role-aware refusal,
and absent-CLI degradation.

Covers:
- Schema offered and shaped correctly (verb enum, query/record/top_k params)
- Dispatch reaches colleague.memory.recall / colleague.memory.remember
- Refusal matrix: read-only roles (explorer/planner/reviewer/validator)
  cannot use 'remember'; writer/default can use both verbs
- Absent-CLI degradation: returns empty-result string, never crashes
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from colleague import memory as memory_module
from colleague.tools import SCHEMAS, TOOL_NAMES, ToolError, ToolExecutor

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_schema(name: str) -> dict[str, Any]:
    """Return the schema dict for *name* from SCHEMAS."""
    for s in SCHEMAS:
        if s["function"]["name"] == name:
            return s
    raise ValueError(f"no schema for '{name}'")


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    """A bare repo root for ToolExecutor."""
    return tmp_path


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestMemorySchema:
    """The memory tool schema is offered and shaped correctly."""

    def test_memory_in_tool_names(self) -> None:
        assert "memory" in TOOL_NAMES

    def test_memory_in_schemas(self) -> None:
        schema = _find_schema("memory")
        assert schema["function"]["name"] == "memory"

    def test_memory_has_description(self) -> None:
        schema = _find_schema("memory")
        desc = schema["function"]["description"]
        assert "recall" in desc.lower() or "remember" in desc.lower()

    def test_memory_params(self) -> None:
        schema = _find_schema("memory")
        props = schema["function"]["parameters"]["properties"]
        assert "verb" in props
        assert "query" in props
        assert "record" in props
        assert "top_k" in props

    def test_memory_verb_enum(self) -> None:
        schema = _find_schema("memory")
        verb_prop = schema["function"]["parameters"]["properties"]["verb"]
        assert verb_prop["type"] == "string"
        assert set(verb_prop["enum"]) == {"recall", "remember"}

    def test_memory_required_fields(self) -> None:
        schema = _find_schema("memory")
        required = schema["function"]["parameters"]["required"]
        assert "verb" in required

    def test_memory_query_type(self) -> None:
        schema = _find_schema("memory")
        query_prop = schema["function"]["parameters"]["properties"]["query"]
        assert query_prop["type"] == "string"

    def test_memory_record_type(self) -> None:
        schema = _find_schema("memory")
        record_prop = schema["function"]["parameters"]["properties"]["record"]
        assert record_prop["type"] == "object"

    def test_memory_top_k_type(self) -> None:
        schema = _find_schema("memory")
        top_k_prop = schema["function"]["parameters"]["properties"]["top_k"]
        assert top_k_prop["type"] == "integer"


# ---------------------------------------------------------------------------
# Dispatch tests — recall
# ---------------------------------------------------------------------------


class TestMemoryRecallDispatch:
    """The _memory dispatch calls memory.recall with correct args."""

    def test_recall_reaches_memory_module(
        self, tmp_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        hits = [{"id": "1", "content": "test hit"}]
        monkeypatch.setattr(memory_module, "recall", lambda *a, **kw: hits)
        executor = ToolExecutor(tmp_repo)
        outcome = executor.execute(
            "memory",
            {
                "verb": "recall",
                "query": "test query",
            },
        )
        assert outcome.result == json.dumps(hits)

    def test_recall_output_is_bounded_like_every_other_tool(
        self, tmp_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A store with huge records must not blow the tool-output budget (PR #267)."""
        hits = [{"id": "1", "content": "x" * 10_000}]
        monkeypatch.setattr(memory_module, "recall", lambda *a, **kw: hits)
        executor = ToolExecutor(tmp_repo, max_output_chars=500)
        outcome = executor.execute("memory", {"verb": "recall", "query": "q"})
        assert len(outcome.result) < 1_000
        assert outcome.result != json.dumps(hits)

    def test_recall_with_custom_top_k(
        self, tmp_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, Any] = {}

        def fake_recall(repo, query, top_k=5):
            captured["top_k"] = top_k
            return []

        monkeypatch.setattr(memory_module, "recall", fake_recall)
        executor = ToolExecutor(tmp_repo)
        executor.execute(
            "memory",
            {
                "verb": "recall",
                "query": "test",
                "top_k": 10,
            },
        )
        assert captured["top_k"] == 10

    def test_recall_default_top_k(self, tmp_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}

        def fake_recall(repo, query, top_k=5):
            captured["top_k"] = top_k
            return []

        monkeypatch.setattr(memory_module, "recall", fake_recall)
        executor = ToolExecutor(tmp_repo)
        executor.execute(
            "memory",
            {
                "verb": "recall",
                "query": "test",
            },
        )
        assert captured["top_k"] == 5

    def test_recall_missing_query_raises(self, tmp_repo: Path) -> None:
        executor = ToolExecutor(tmp_repo)
        with pytest.raises(ToolError, match="requires a 'query'"):
            executor.execute("memory", {"verb": "recall"})

    def test_recall_empty_query_raises(self, tmp_repo: Path) -> None:
        executor = ToolExecutor(tmp_repo)
        with pytest.raises(ToolError, match="requires a 'query'"):
            executor.execute("memory", {"verb": "recall", "query": ""})


# ---------------------------------------------------------------------------
# Dispatch tests — remember
# ---------------------------------------------------------------------------


class TestMemoryRememberDispatch:
    """The _memory dispatch calls memory.remember with correct args."""

    def test_remember_reaches_memory_module(
        self, tmp_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(memory_module, "remember", lambda *a, **kw: True)
        executor = ToolExecutor(tmp_repo)
        outcome = executor.execute(
            "memory",
            {
                "verb": "remember",
                "record": {"key": "value"},
            },
        )
        assert outcome.result == "ok"

    def test_remember_failure(self, tmp_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(memory_module, "remember", lambda *a, **kw: False)
        executor = ToolExecutor(tmp_repo)
        outcome = executor.execute(
            "memory",
            {
                "verb": "remember",
                "record": {"key": "value"},
            },
        )
        assert outcome.result == "failed"

    def test_remember_missing_record_raises(self, tmp_repo: Path) -> None:
        executor = ToolExecutor(tmp_repo)
        with pytest.raises(ToolError, match="requires a 'record'"):
            executor.execute("memory", {"verb": "remember"})

    def test_remember_non_dict_record_raises(self, tmp_repo: Path) -> None:
        executor = ToolExecutor(tmp_repo)
        with pytest.raises(ToolError, match="requires a 'record'"):
            executor.execute("memory", {"verb": "remember", "record": "not a dict"})


# ---------------------------------------------------------------------------
# Bad verb tests
# ---------------------------------------------------------------------------


class TestMemoryBadVerb:
    """Invalid verb values raise ToolError."""

    def test_invalid_verb_raises(self, tmp_repo: Path) -> None:
        executor = ToolExecutor(tmp_repo)
        with pytest.raises(ToolError, match="requires verb"):
            executor.execute("memory", {"verb": "invalid"})

    def test_missing_verb_raises(self, tmp_repo: Path) -> None:
        executor = ToolExecutor(tmp_repo)
        with pytest.raises(ToolError, match="requires verb"):
            executor.execute("memory", {})


# ---------------------------------------------------------------------------
# Role-aware refusal tests
# ---------------------------------------------------------------------------


class TestMemoryRoleRefusal:
    """Read-only roles refuse 'remember'; writer allows both verbs."""

    @pytest.fixture
    def executor(self, tmp_repo: Path) -> ToolExecutor:
        return ToolExecutor(tmp_repo)

    def _make_executor_with_role(self, tmp_repo: Path, role_name: str) -> ToolExecutor:
        from colleague.roles import BUILTIN_ROLES

        role = BUILTIN_ROLES[role_name]
        return ToolExecutor(tmp_repo, allowlist=role)

    @pytest.mark.parametrize(
        "role",
        [
            "explorer",
            "planner",
            "reviewer",
            "validator",
        ],
    )
    def test_read_only_roles_refuse_remember(self, tmp_repo: Path, role: str) -> None:
        executor = self._make_executor_with_role(tmp_repo, role)
        with pytest.raises(ToolError, match="not allowed for read-only"):
            executor.execute(
                "memory",
                {
                    "verb": "remember",
                    "record": {"key": "value"},
                },
            )

    @pytest.mark.parametrize(
        "role",
        [
            "explorer",
            "planner",
            "reviewer",
            "validator",
        ],
    )
    def test_read_only_roles_allow_recall(
        self, tmp_repo: Path, role: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(memory_module, "recall", lambda *a, **kw: [])
        executor = self._make_executor_with_role(tmp_repo, role)
        outcome = executor.execute(
            "memory",
            {
                "verb": "recall",
                "query": "test",
            },
        )
        assert outcome.result == "[]"

    def test_writer_allows_remember(self, tmp_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(memory_module, "remember", lambda *a, **kw: True)
        executor = self._make_executor_with_role(tmp_repo, "writer")
        outcome = executor.execute(
            "memory",
            {
                "verb": "remember",
                "record": {"key": "value"},
            },
        )
        assert outcome.result == "ok"

    def test_writer_allows_recall(self, tmp_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(memory_module, "recall", lambda *a, **kw: [])
        executor = self._make_executor_with_role(tmp_repo, "writer")
        outcome = executor.execute(
            "memory",
            {
                "verb": "recall",
                "query": "test",
            },
        )
        assert outcome.result == "[]"

    def test_no_role_allows_remember(self, tmp_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Default (no role) executor allows both verbs."""
        monkeypatch.setattr(memory_module, "remember", lambda *a, **kw: True)
        executor = ToolExecutor(tmp_repo)
        outcome = executor.execute(
            "memory",
            {
                "verb": "remember",
                "record": {"key": "value"},
            },
        )
        assert outcome.result == "ok"


# ---------------------------------------------------------------------------
# Absent-CLI degradation tests
# ---------------------------------------------------------------------------


class TestMemoryAbsentCLI:
    """When eidetic CLI is absent, memory returns empty results, never crashes."""

    def test_recall_degrades_to_empty_list(
        self, tmp_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Simulate absent CLI by making recall return empty list."""
        monkeypatch.setattr(memory_module, "recall", lambda *a, **kw: [])
        executor = ToolExecutor(tmp_repo)
        outcome = executor.execute(
            "memory",
            {
                "verb": "recall",
                "query": "test",
            },
        )
        assert outcome.result == "[]"

    def test_remember_degrades_gracefully(
        self, tmp_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Simulate absent CLI by making remember return False."""
        monkeypatch.setattr(memory_module, "remember", lambda *a, **kw: False)
        # Need writer role to allow remember
        from colleague.roles import BUILTIN_ROLES

        role = BUILTIN_ROLES["writer"]
        executor = ToolExecutor(tmp_repo, allowlist=role)
        outcome = executor.execute(
            "memory",
            {
                "verb": "remember",
                "record": {"key": "value"},
            },
        )
        assert outcome.result == "failed"

    def test_absent_cli_never_crashes(
        self, tmp_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Even with broken implementations, no exception escapes."""

        def broken_recall(*a, **kw):
            return []

        def broken_remember(*a, **kw):
            return False

        monkeypatch.setattr(memory_module, "recall", broken_recall)
        monkeypatch.setattr(memory_module, "remember", broken_remember)
        executor = ToolExecutor(tmp_repo)
        # recall should not raise
        outcome = executor.execute(
            "memory",
            {
                "verb": "recall",
                "query": "test",
            },
        )
        assert isinstance(outcome.result, str)
