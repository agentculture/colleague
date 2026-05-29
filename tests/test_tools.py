"""Tool schemas + repo-confined executor (R3, h3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from convertible.tools import FINISH, SCHEMAS, TOOL_NAMES, ToolError, ToolExecutor


def test_schemas_cover_base_five_plus_culture_and_devague() -> None:
    # The five base tools, plus the curated shared culture tool (t3) and the
    # curated shared devague tool (t2).
    assert set(TOOL_NAMES) == {
        "read_file",
        "write_file",
        "list_dir",
        "run_command",
        "finish",
        "culture",
        "devague",
    }
    for schema in SCHEMAS:
        assert schema["type"] == "function"
        assert "name" in schema["function"]
        assert "parameters" in schema["function"]


def test_write_then_read_round_trip(tmp_path: Path) -> None:
    ex = ToolExecutor(tmp_path)
    out = ex.execute("write_file", {"path": "sub/hello.txt", "content": "hi there"})
    assert out.changed_file == "sub/hello.txt"
    assert "sub/hello.txt" in ex.changed
    assert (tmp_path / "sub" / "hello.txt").read_text() == "hi there"
    read = ex.execute("read_file", {"path": "sub/hello.txt"})
    assert read.result == "hi there"


def test_list_dir(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "d").mkdir()
    out = ToolExecutor(tmp_path).execute("list_dir", {"path": "."})
    assert "a.txt" in out.result
    assert "d/" in out.result


def test_run_command_runs_in_root(tmp_path: Path) -> None:
    out = ToolExecutor(tmp_path).execute("run_command", {"command": "echo hello-from-cmd"})
    assert "hello-from-cmd" in out.result
    assert "exit=0" in out.result


def test_finish_signals_completion() -> None:
    out = ToolExecutor("/tmp").execute(FINISH, {"summary": "all done"})
    assert out.finished is True
    assert out.finish_summary == "all done"


def test_write_outside_root_is_refused(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    ex = ToolExecutor(repo)
    with pytest.raises(ToolError):
        ex.execute("write_file", {"path": "../escaped.txt", "content": "nope"})
    # nothing was written outside the root
    assert not (tmp_path / "escaped.txt").exists()
    assert ex.changed == set()


def test_read_outside_root_is_refused(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (tmp_path / "secret.txt").write_text("secret")
    with pytest.raises(ToolError):
        ToolExecutor(repo).execute("read_file", {"path": "../secret.txt"})


def test_read_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ToolError):
        ToolExecutor(tmp_path).execute("read_file", {"path": "nope.txt"})


def test_unknown_tool_raises(tmp_path: Path) -> None:
    with pytest.raises(ToolError):
        ToolExecutor(tmp_path).execute("teleport", {})
