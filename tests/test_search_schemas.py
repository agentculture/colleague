"""Plan t14 — grep_search + glob on the tool surface (c7 / h5).

Pins the acceptance criteria verbatim:

* SCHEMAS contains ``grep_search`` and ``glob`` with descriptions naming
  ripgrep-style patterns; ``ToolExecutor.execute`` dispatches them;
  ``curate_schemas`` offers them to every read-capable role (read-only roles
  included);
* both go through truncation (``ToolExecutor._truncate``), both are in
  ``toolbatch.CONCURRENCY_SAFE_TOOLS``, and ``COLLEAGUE_TOOLS_LEGACY=1`` hides
  both schemas (the byte-identical proof path) — dispatch refuses too;
* ``docs/features/work-and-loop.md``'s tool table lists both.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from colleague import search_schemas, search_tools, toolbatch
from colleague.roles import BUILTIN_ROLES
from colleague.tools import SCHEMAS, TOOL_NAMES, ToolError, ToolExecutor, curate_schemas

REPO_ROOT = Path(__file__).resolve().parent.parent
_NAMES = {s["function"]["name"] for s in SCHEMAS}


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "alpha.py").write_text("def alpha():\n    return 'needle'\n")
    (tmp_path / "pkg" / "beta.py").write_text("beta = 1\n")
    (tmp_path / "notes.md").write_text("a Needle in the notes\n")
    return tmp_path


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


def test_schemas_contain_both_search_tools_with_ripgrep_style_descriptions() -> None:
    assert {"grep_search", "glob"} <= _NAMES
    by_name = {s["function"]["name"]: s["function"] for s in SCHEMAS}
    for name in ("grep_search", "glob"):
        assert "ripgrep" in by_name[name]["description"]
        assert by_name[name]["parameters"]["required"] == ["pattern"]
    assert set(by_name["grep_search"]["parameters"]["properties"]) == {
        "pattern",
        "path",
        "glob",
        "max_results",
    }
    assert set(by_name["glob"]["parameters"]["properties"]) == {"pattern", "path", "max_results"}


def test_tool_names_registry_and_toolbatch_agree() -> None:
    assert "grep_search" in TOOL_NAMES
    assert "glob" in TOOL_NAMES
    assert set(search_schemas.SEARCH_TOOL_NAMES) <= toolbatch.CONCURRENCY_SAFE_TOOLS
    assert search_schemas.DEFAULT_MAX_RESULTS == search_tools.DEFAULT_MAX_RESULTS


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def test_execute_dispatches_grep_search(tree: Path) -> None:
    out = ToolExecutor(tree).execute("grep_search", {"pattern": "needle"})
    assert out.result.splitlines() == [
        "notes.md:1: a Needle in the notes",
        "pkg/alpha.py:2:     return 'needle'",
    ]
    assert out.changed_file is None
    assert not out.finished


def test_execute_dispatches_grep_search_with_path_and_glob(tree: Path) -> None:
    out = ToolExecutor(tree).execute("grep_search", {"pattern": "needle", "path": "pkg"})
    assert out.result.splitlines() == ["pkg/alpha.py:2:     return 'needle'"]
    out = ToolExecutor(tree).execute("grep_search", {"pattern": "needle", "glob": "*.md"})
    assert out.result.splitlines() == ["notes.md:1: a Needle in the notes"]
    out = ToolExecutor(tree).execute("grep_search", {"pattern": "zzz-absent"})
    assert out.result == "no matches"


def test_execute_dispatches_glob(tree: Path) -> None:
    out = ToolExecutor(tree).execute("glob", {"pattern": "**/*.py"})
    assert sorted(out.result.splitlines()) == ["pkg/alpha.py", "pkg/beta.py"]
    out = ToolExecutor(tree).execute("glob", {"pattern": "*.py", "path": "pkg"})
    assert sorted(out.result.splitlines()) == ["pkg/alpha.py", "pkg/beta.py"]
    out = ToolExecutor(tree).execute("glob", {"pattern": "*.rs"})
    assert out.result == "no files match"


def test_max_results_caps_and_flags(tree: Path) -> None:
    out = ToolExecutor(tree).execute("grep_search", {"pattern": "needle", "max_results": 1})
    lines = out.result.splitlines()
    assert len(lines) == 2
    assert lines[-1].startswith("... [capped at 1 matches")


@pytest.mark.parametrize("tool", ["grep_search", "glob"])
def test_bad_arguments_are_tool_errors_not_crashes(tree: Path, tool: str) -> None:
    ex = ToolExecutor(tree)
    with pytest.raises(ToolError, match="non-empty 'pattern'"):
        ex.execute(tool, {})
    with pytest.raises(ToolError, match="max_results"):
        ex.execute(tool, {"pattern": "x", "max_results": 0})


def test_path_escape_is_refused_like_read_file(tree: Path) -> None:
    ex = ToolExecutor(tree)
    with pytest.raises(ToolError):
        ex.execute("grep_search", {"pattern": "x", "path": "../"})
    with pytest.raises(ToolError):
        ex.execute("glob", {"pattern": "*", "path": "../"})


def test_output_goes_through_the_executor_truncation(tree: Path, monkeypatch) -> None:
    # A tiny executor ceiling proves the search result went through _truncate:
    # the rendered hits are cut and the truncation marker names the spill.
    for i in range(300):
        (tree / f"f{i:03d}.txt").write_text("needle needle needle needle needle needle\n")
    ex = ToolExecutor(tree, max_output_chars=400)
    out = ex.execute("grep_search", {"pattern": "needle", "max_results": 300})
    assert len(out.result) < 2000
    assert "truncat" in out.result.lower() or "tool-output" in out.result


# ---------------------------------------------------------------------------
# Role curation
# ---------------------------------------------------------------------------


_READ_CAPABLE_ROLES = ["explorer", "planner", "reviewer", "validator", "scout", "writer"]


@pytest.mark.parametrize("role", _READ_CAPABLE_ROLES)
def test_every_read_capable_role_is_offered_both(role: str) -> None:
    offered = {s["function"]["name"] for s in curate_schemas(role)}
    assert {"grep_search", "glob"} <= offered, role
    assert {"grep_search", "glob"} <= set(BUILTIN_ROLES[role].tool_allowlist)


def test_full_surface_offers_both() -> None:
    assert {"grep_search", "glob"} <= {s["function"]["name"] for s in curate_schemas(None)}


# ---------------------------------------------------------------------------
# The legacy knob — byte-identical proof path
# ---------------------------------------------------------------------------


def test_legacy_knob_hides_both_schemas_and_refuses_dispatch(tree: Path, monkeypatch) -> None:
    monkeypatch.setenv(search_schemas.LEGACY_ENV, "1")
    assert search_schemas.legacy_hidden()
    offered = {s["function"]["name"] for s in curate_schemas(None)}
    assert offered.isdisjoint({"grep_search", "glob"})
    assert offered == _NAMES - {"grep_search", "glob"}
    for role in ("explorer", "scout", "writer"):
        assert {s["function"]["name"] for s in curate_schemas(role)}.isdisjoint(
            {"grep_search", "glob"}
        )
    ex = ToolExecutor(tree)
    with pytest.raises(ToolError, match="COLLEAGUE_TOOLS_LEGACY"):
        ex.execute("grep_search", {"pattern": "needle"})
    with pytest.raises(ToolError, match="COLLEAGUE_TOOLS_LEGACY"):
        ex.execute("glob", {"pattern": "*"})


def test_legacy_knob_unset_offers_the_full_surface(monkeypatch) -> None:
    monkeypatch.delenv(search_schemas.LEGACY_ENV, raising=False)
    assert not search_schemas.legacy_hidden()
    assert search_schemas.hidden_names() == frozenset()
    assert {s["function"]["name"] for s in curate_schemas(None)} == _NAMES


# ---------------------------------------------------------------------------
# Docs + prompt guidance
# ---------------------------------------------------------------------------


def test_work_and_loop_tool_table_lists_both() -> None:
    doc = (REPO_ROOT / "docs" / "features" / "work-and-loop.md").read_text(encoding="utf-8")
    assert "| `grep_search` |" in doc
    assert "| `glob` |" in doc


def test_prompt_text_prefers_search_tools_over_shell_grep() -> None:
    from colleague import prompttext

    text = prompttext.default_system("unsloth/Qwen3.8-27B-NVFP4", variant="qwen")
    assert "grep_search" in text
    assert "glob" in text
    assert "grep_search" not in prompttext.V1_DEFAULT_SYSTEM  # the pre-arc prompt is untouched
