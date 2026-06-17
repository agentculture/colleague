"""Tests for the check_test_integrity loop tool (task t5).

Verifies that the tool schema is present in SCHEMAS, the dispatch works
through ToolExecutor, and the result correctly names flagged symbols.
"""

from __future__ import annotations

from pathlib import Path

from colleague.tools import SCHEMAS, TOOL_NAMES, ToolExecutor


def test_check_test_integrity_schema_present() -> None:
    """The check_test_integrity tool schema is in SCHEMAS and TOOL_NAMES."""
    assert "check_test_integrity" in TOOL_NAMES
    schema = next(s for s in SCHEMAS if s["function"]["name"] == "check_test_integrity")
    assert schema["type"] == "function"
    assert "description" in schema["function"]
    assert "mirror" in schema["function"]["description"].lower()
    # No required parameters — empty properties object
    assert schema["function"]["parameters"]["type"] == "object"
    assert schema["function"]["parameters"]["properties"] == {}


def test_check_test_integrity_no_findings(tmp_path: Path) -> None:
    """When changed files share no novel symbols, the tool reports no findings."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "other.py").write_text("def helper(): pass\n")

    ex = ToolExecutor(repo)
    # Simulate changed files that don't share a novel symbol
    ex.changed = {"other.py"}
    out = ex.execute("check_test_integrity", {})
    assert "no mirror findings" in out.result


def test_check_test_integrity_flags_mirror_symbol(tmp_path: Path) -> None:
    """A novel symbol co-introduced in a test and impl file is flagged."""
    repo = tmp_path / "repo"
    repo.mkdir()

    # Test file and impl file both use a novel attribute `response_error`
    test_content = """
def test_error():
    raise exc.response_error("boom")
"""
    impl_content = """
def handle():
    raise exc.response_error("boom")
"""
    (repo / "test_thing.py").write_text(test_content)
    (repo / "thing.py").write_text(impl_content)
    # A third file that does NOT use response_error
    (repo / "other.py").write_text("x = 1\n")

    ex = ToolExecutor(repo)
    ex.changed = {"test_thing.py", "thing.py"}
    out = ex.execute("check_test_integrity", {})
    assert "response_error" in out.result
    assert "test_thing.py" in out.result
    assert "thing.py" in out.result


def test_check_test_integrity_dict_key_mirror(tmp_path: Path) -> None:
    """A dict-key string literal shared between test and impl is flagged."""
    repo = tmp_path / "repo"
    repo.mkdir()

    test_content = """
def test_cost():
    data = {"TotalEstimate": 42}
    assert data["TotalEstimate"] == 42
"""
    impl_content = """
def compute():
    data = {"TotalEstimate": 100}
    return data["TotalEstimate"]
"""
    (repo / "test_cost.py").write_text(test_content)
    (repo / "cost.py").write_text(impl_content)
    (repo / "other.py").write_text("x = 1\n")

    ex = ToolExecutor(repo)
    ex.changed = {"test_cost.py", "cost.py"}
    out = ex.execute("check_test_integrity", {})
    assert "TotalEstimate" in out.result


def test_check_test_integrity_not_flagged_when_symbol_exists_elsewhere(tmp_path: Path) -> None:
    """A symbol also present in a non-changed repo file is NOT flagged."""
    repo = tmp_path / "repo"
    repo.mkdir()

    test_content = """
def test_error():
    raise exc.response_error("boom")
"""
    impl_content = """
def handle():
    raise exc.response_error("boom")
"""
    # This third file also uses response_error, so it's NOT novel.
    extra_content = """
def legacy():
    raise exc.response_error("old")
"""
    (repo / "test_thing.py").write_text(test_content)
    (repo / "thing.py").write_text(impl_content)
    (repo / "legacy.py").write_text(extra_content)

    ex = ToolExecutor(repo)
    ex.changed = {"test_thing.py", "thing.py"}
    out = ex.execute("check_test_integrity", {})
    assert "no mirror findings" in out.result


def test_check_test_integrity_empty_changed(tmp_path: Path) -> None:
    """When changed is empty, the tool returns no findings."""
    repo = tmp_path / "repo"
    repo.mkdir()

    ex = ToolExecutor(repo)
    ex.changed = set()
    out = ex.execute("check_test_integrity", {})
    assert "no mirror findings" in out.result
