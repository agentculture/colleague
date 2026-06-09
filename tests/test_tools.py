"""Tool schemas + repo-confined executor (R3, h3)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from colleague.tools import FINISH, SCHEMAS, TOOL_NAMES, ToolError, ToolExecutor


def test_schemas_cover_base_six_plus_culture_and_devague() -> None:
    # The six base tools (read_file, write_file, edit_file, list_dir,
    # run_command, finish), plus the curated shared culture tool (t3), the
    # curated shared devague tool (t2), the subagent delegation tool (t4), and
    # the parallel batch subagents tool (t4).
    assert set(TOOL_NAMES) == {
        "read_file",
        "write_file",
        "edit_file",
        "list_dir",
        "run_command",
        "finish",
        "culture",
        "devague",
        "subagent",
        "subagents",
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


def test_finish_signals_completion(tmp_path: Path) -> None:
    out = ToolExecutor(tmp_path).execute(FINISH, {"summary": "all done"})
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


# ---------------------------------------------------------------------------
# edit_file tests
# ---------------------------------------------------------------------------


def test_edit_file_happy_path(tmp_path: Path) -> None:
    ex = ToolExecutor(tmp_path)
    ex.execute("write_file", {"path": "greet.txt", "content": "hello world"})
    out = ex.execute(
        "edit_file", {"path": "greet.txt", "old_string": "world", "new_string": "colleague"}
    )
    assert (tmp_path / "greet.txt").read_text() == "hello colleague"
    assert out.changed_file == "greet.txt"
    assert "greet.txt" in ex.changed
    assert "edited" in out.result


def test_edit_file_old_string_not_found(tmp_path: Path) -> None:
    ex = ToolExecutor(tmp_path)
    ex.execute("write_file", {"path": "a.txt", "content": "some content here"})
    with pytest.raises(ToolError):
        ex.execute("edit_file", {"path": "a.txt", "old_string": "missing text", "new_string": "x"})


def test_edit_file_non_unique_without_replace_all(tmp_path: Path) -> None:
    ex = ToolExecutor(tmp_path)
    ex.execute("write_file", {"path": "dup.txt", "content": "foo foo foo"})
    with pytest.raises(ToolError):
        ex.execute("edit_file", {"path": "dup.txt", "old_string": "foo", "new_string": "bar"})


def test_edit_file_replace_all(tmp_path: Path) -> None:
    ex = ToolExecutor(tmp_path)
    ex.execute("write_file", {"path": "dup.txt", "content": "foo foo foo"})
    ex.execute(
        "edit_file",
        {"path": "dup.txt", "old_string": "foo", "new_string": "bar", "replace_all": True},
    )
    text = (tmp_path / "dup.txt").read_text()
    assert "foo" not in text
    assert text.count("bar") == 3


def test_edit_file_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ToolError):
        ToolExecutor(tmp_path).execute(
            "edit_file", {"path": "nonexistent.txt", "old_string": "x", "new_string": "y"}
        )


def test_edit_file_empty_old_string(tmp_path: Path) -> None:
    ex = ToolExecutor(tmp_path)
    ex.execute("write_file", {"path": "b.txt", "content": "hello"})
    with pytest.raises(ToolError):
        ex.execute("edit_file", {"path": "b.txt", "old_string": "", "new_string": "something"})


def test_edit_file_no_op_same_strings(tmp_path: Path) -> None:
    ex = ToolExecutor(tmp_path)
    ex.execute("write_file", {"path": "c.txt", "content": "same"})
    with pytest.raises(ToolError):
        ex.execute("edit_file", {"path": "c.txt", "old_string": "same", "new_string": "same"})


def test_edit_file_escape_root_refused(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (tmp_path / "outside.txt").write_text("secret")
    ex = ToolExecutor(repo)
    with pytest.raises(ToolError):
        ex.execute(
            "edit_file",
            {"path": "../outside.txt", "old_string": "secret", "new_string": "pwned"},
        )


def test_edit_file_neighbour_clone_refused(tmp_path: Path) -> None:
    neighbour_dir = tmp_path / ".colleague" / "neighbours" / "foo"
    neighbour_dir.mkdir(parents=True)
    (neighbour_dir / "x.txt").write_text("original content")
    ex = ToolExecutor(tmp_path)
    with pytest.raises(ToolError):
        ex.execute(
            "edit_file",
            {
                "path": ".colleague/neighbours/foo/x.txt",
                "old_string": "original",
                "new_string": "modified",
            },
        )


def test_edit_file_bytes_written_single(tmp_path: Path) -> None:
    ex = ToolExecutor(tmp_path)
    ex.execute("write_file", {"path": "bw.txt", "content": "alpha beta"})
    before = ex.bytes_written
    new_string = "REPLACED"
    ex.execute("edit_file", {"path": "bw.txt", "old_string": "alpha", "new_string": new_string})
    assert ex.bytes_written - before == len(new_string.encode("utf-8"))


def test_edit_file_bytes_written_replace_all(tmp_path: Path) -> None:
    ex = ToolExecutor(tmp_path)
    ex.execute("write_file", {"path": "bw2.txt", "content": "x x x"})
    before = ex.bytes_written
    new_string = "YY"
    ex.execute(
        "edit_file",
        {"path": "bw2.txt", "old_string": "x", "new_string": new_string, "replace_all": True},
    )
    assert ex.bytes_written - before == 3 * len(new_string.encode("utf-8"))


def test_edit_file_single_match_without_replace_all(tmp_path: Path) -> None:
    # A unique match needs no replace_all: count == 1 passes straight through.
    ex = ToolExecutor(tmp_path)
    ex.execute("write_file", {"path": "u.txt", "content": "alpha beta gamma"})
    out = ex.execute("edit_file", {"path": "u.txt", "old_string": "beta", "new_string": "BETA"})
    assert (tmp_path / "u.txt").read_text() == "alpha BETA gamma"
    assert "replaced 1 occurrence" in out.result


def test_edit_file_multiline_old_string(tmp_path: Path) -> None:
    # The common real-world case: old_string spans multiple lines.
    ex = ToolExecutor(tmp_path)
    ex.execute("write_file", {"path": "m.txt", "content": "line1\nline2\nline3\n"})
    ex.execute(
        "edit_file",
        {"path": "m.txt", "old_string": "line1\nline2", "new_string": "LINE1\nLINE2"},
    )
    assert (tmp_path / "m.txt").read_text() == "LINE1\nLINE2\nline3\n"


def test_edit_file_new_contains_old_replace_all(tmp_path: Path) -> None:
    # new_string containing old_string must NOT runaway-expand: str.replace does a
    # single left-to-right pass and never re-scans replaced text.
    ex = ToolExecutor(tmp_path)
    ex.execute("write_file", {"path": "g.txt", "content": "a a"})
    ex.execute(
        "edit_file",
        {"path": "g.txt", "old_string": "a", "new_string": "a-x", "replace_all": True},
    )
    assert (tmp_path / "g.txt").read_text() == "a-x a-x"


def test_edit_file_non_utf8_raises_toolerror(tmp_path: Path) -> None:
    # A non-UTF8 file surfaces as a recoverable ToolError, not an uncaught
    # UnicodeDecodeError that would abort the work item (the loop only catches
    # ToolError around tool execution).
    (tmp_path / "bin.dat").write_bytes(b"\xff\xfe\x00 raw bytes")
    ex = ToolExecutor(tmp_path)
    with pytest.raises(ToolError):
        ex.execute("edit_file", {"path": "bin.dat", "old_string": "raw", "new_string": "x"})


@pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses file permission bits")
def test_edit_file_write_failure_raises_toolerror(tmp_path: Path) -> None:
    # A write failure (here: a read-only target) is translated to ToolError rather
    # than escaping as a raw OSError.
    target = tmp_path / "ro.txt"
    target.write_text("keep this")
    target.chmod(0o444)
    try:
        ex = ToolExecutor(tmp_path)
        with pytest.raises(ToolError):
            ex.execute("edit_file", {"path": "ro.txt", "old_string": "keep", "new_string": "drop"})
    finally:
        target.chmod(0o644)
