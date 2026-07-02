"""Tool schemas + repo-confined executor (R3, h3)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from colleague.tools import FINISH, SCHEMAS, TOOL_NAMES, ToolError, ToolExecutor


def test_schemas_cover_base_six_plus_culture_and_devague() -> None:
    # The six base tools (read_file, write_file, edit_file, list_dir,
    # run_command, finish), plus the curated shared culture tool (t3), the
    # curated shared devague tool (t2), the subagent delegation tool (t4), the
    # parallel batch subagents tool (t4), the test-integrity self-check tool
    # (t5), the read-only run_tests tool (typed-subagent roles, t7), and the
    # memory tool (eidetic CLI, t3).
    assert set(TOOL_NAMES) == {
        "read_file",
        "view_media",
        "write_file",
        "edit_file",
        "list_dir",
        "run_command",
        "finish",
        "culture",
        "devague",
        "subagent",
        "subagents",
        "check_test_integrity",
        "run_tests",
        "memory",
    }
    for schema in SCHEMAS:
        assert schema["type"] == "function"
        assert "name" in schema["function"]
        assert "parameters" in schema["function"]


def test_subagents_batch_merges_child_changed_files(tmp_path: Path) -> None:
    """#263: a batch child's changed files must reach the parent tracker.

    The single-``subagent`` path already merges ``sub.changed_files`` into
    ``executor.changed``; the batch path silently dropped them, so a work item
    that delegated an edit via ``subagents`` under-reported ``changed_files``
    in the artifact AND under-scoped every changed-file-scoped pre-handoff
    gate (lint / test-integrity / affected-tests). Live evidence: work item
    5ccdf8573cad (t3) — tools.py edited by a batch child, absent from the
    artifact's changed_files.
    """
    from colleague.contract import SubResult

    def fake_batch_spawn(items, batch_role=None):
        return [
            SubResult(
                task_id="c1",
                engine="mock",
                model="m",
                status="ok",
                summary="edited tools",
                changed_files=["colleague/tools.py"],
            ),
            SubResult(
                task_id="c2",
                engine="mock",
                model="m",
                status="ok",
                summary="edited roles",
                changed_files=["colleague/roles.py"],
            ),
            SubResult(
                task_id="merge",
                engine="mock",
                model="m",
                status="ok",
                summary="merged",
                changed_files=[],
            ),
        ]

    ex = ToolExecutor(tmp_path, batch_spawn=fake_batch_spawn)
    out = ex.execute(
        "subagents",
        {"instructions": [{"instruction": "edit tools"}, {"instruction": "edit roles"}]},
    )
    assert "subagents batch" in out.result
    assert "colleague/tools.py" in ex.changed
    assert "colleague/roles.py" in ex.changed


def test_dispatch_converts_handler_crash_to_tool_error(tmp_path: Path) -> None:
    """#269 defense-in-depth: a non-ToolError handler crash becomes a
    model-visible ToolError naming the tool — a step error the model can react
    to, never a run abort with a bare ``'path'``."""
    ex = ToolExecutor(tmp_path)

    def broken(arguments):
        raise KeyError("path")

    ex._read_file = broken  # simulate a future unguarded handler crash
    with pytest.raises(ToolError) as ei:
        ex.execute("read_file", {})
    msg = str(ei.value)
    assert "read_file" in msg
    assert "KeyError" in msg


def test_missing_required_arg_is_tool_error_not_crash(tmp_path: Path) -> None:
    """#269 primary shape (fixed by ``_require`` in 1.31.0, pinned here): a
    tool call missing its required argument costs one self-correcting step
    error naming the tool and the key."""
    ex = ToolExecutor(tmp_path)
    for tool in ("read_file", "write_file", "edit_file"):
        with pytest.raises(ToolError) as ei:
            ex.execute(tool, {})
        assert tool in str(ei.value)
        assert "path" in str(ei.value)


def test_write_then_read_round_trip(tmp_path: Path) -> None:
    ex = ToolExecutor(tmp_path)
    out = ex.execute("write_file", {"path": "sub/hello.txt", "content": "hi there"})
    assert out.changed_file == "sub/hello.txt"
    assert "sub/hello.txt" in ex.changed
    assert (tmp_path / "sub" / "hello.txt").read_text() == "hi there"
    read = ex.execute("read_file", {"path": "sub/hello.txt"})
    # read_file grounds each line with its true 1-based number, cat -n style (#240).
    assert read.result == "     1\thi there"


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


# ---------------------------------------------------------------------------
# read_file line-grounding tests (#240) — a cited "line N" must be
# copy-derived from tool output, never re-counted by the model.
# ---------------------------------------------------------------------------


def test_read_file_prefixes_each_line_with_its_true_line_number(tmp_path: Path) -> None:
    real_lines = [f"line{i}" for i in range(1, 11)]
    (tmp_path / "f.py").write_text("\n".join(real_lines) + "\n", encoding="utf-8")
    out = ToolExecutor(tmp_path).execute("read_file", {"path": "f.py"})
    numbered_lines = out.result.split("\n")
    assert len(numbered_lines) == 10
    for i, numbered_line in enumerate(numbered_lines, start=1):
        prefix, body = numbered_line.split("\t", 1)
        assert int(prefix) == i
        assert body == real_lines[i - 1]


def test_read_file_trailing_newline_does_not_mint_a_phantom_line(tmp_path: Path) -> None:
    # cat -n / grep -n convention: a trailing "\n" terminates the last line, it
    # does not add a numbered empty line after it.
    (tmp_path / "g.py").write_text("alpha\nbeta\n", encoding="utf-8")
    out = ToolExecutor(tmp_path).execute("read_file", {"path": "g.py"})
    assert out.result == "     1\talpha\n     2\tbeta"


def test_read_file_no_trailing_newline(tmp_path: Path) -> None:
    (tmp_path / "h.py").write_text("alpha\nbeta", encoding="utf-8")
    out = ToolExecutor(tmp_path).execute("read_file", {"path": "h.py"})
    assert out.result == "     1\talpha\n     2\tbeta"


def test_read_file_empty_file_grounds_to_empty_string(tmp_path: Path) -> None:
    (tmp_path / "empty.txt").write_text("", encoding="utf-8")
    out = ToolExecutor(tmp_path).execute("read_file", {"path": "empty.txt"})
    assert out.result == ""


def test_read_file_embedded_blank_line_is_numbered(tmp_path: Path) -> None:
    (tmp_path / "blank.txt").write_text("a\n\nb\n", encoding="utf-8")
    out = ToolExecutor(tmp_path).execute("read_file", {"path": "blank.txt"})
    assert out.result == "     1\ta\n     2\t\n     3\tb"


def test_read_file_line_numbers_survive_truncation(tmp_path: Path) -> None:
    # Every real line is a fixed 20-char body (zero-padded index + filler) so the
    # truncation cutoff can be aligned to an exact line boundary deterministically
    # (each numbered line is exactly 6 + 1 + 20 = 27 chars).
    real_lines = [f"L{i:04d}" + "-" * 15 for i in range(1, 201)]
    (tmp_path / "big.py").write_text("\n".join(real_lines) + "\n", encoding="utf-8")

    # 3 numbered lines (27 chars each) joined by 2 "\n" separators, no trailing "\n".
    limit = 27 * 3 + 2
    ex = ToolExecutor(tmp_path, max_output_chars=limit)
    out = ex.execute("read_file", {"path": "big.py"})

    assert f"truncated at {limit} chars" in out.result
    body = out.result.split("\n... [truncated")[0]
    expected_body = "\n".join(f"{i:6d}\t{real_lines[i - 1]}" for i in range(1, 4))
    # The surviving lines are byte-identical to what the real file's first three
    # lines would produce — the numbering is not shifted/renumbered by the cut.
    assert body == expected_body
    assert len(body) == limit
    # The final result stays bounded: max_output_chars + the fixed truncation
    # note, never unbounded by the added numbering overhead.
    expected_suffix = f"\n... [truncated at {limit} chars]"
    assert out.result == expected_body + expected_suffix
    assert real_lines[3] not in out.result  # line 4 never made it into the result


def test_read_file_max_output_chars_bounds_the_numbered_result(tmp_path: Path) -> None:
    # A file whose RAW content fits comfortably under the limit, but whose
    # NUMBERED content does not — proves numbering overhead is still folded
    # into (never exempt from) the max_output_chars budget.
    real_lines = ["x" * 10 for _ in range(50)]  # raw: 50*11-1 = 549 chars
    (tmp_path / "wide.py").write_text("\n".join(real_lines) + "\n", encoding="utf-8")
    limit = 600  # bigger than the raw text, smaller than the numbered text
    ex = ToolExecutor(tmp_path, max_output_chars=limit)
    out = ex.execute("read_file", {"path": "wide.py"})
    assert "truncated" in out.result
    truncated_prefix = out.result.split("\n... [truncated")[0]
    assert len(truncated_prefix) == limit


def test_edit_file_matches_raw_content_not_the_numbered_display(tmp_path: Path) -> None:
    """edit_file's old_string matches the raw file on disk, never a read_file

    numbering artifact — read_file's line-grounding (#240) is display-only and
    must never round-trip into an edit.
    """
    ex = ToolExecutor(tmp_path)
    ex.execute("write_file", {"path": "e.txt", "content": "alpha\nbeta\ngamma\n"})

    read_out = ex.execute("read_file", {"path": "e.txt"})
    assert "\t" in read_out.result  # grounded numbering is present in the display

    # edit_file still matches the RAW (unnumbered) file content.
    ex.execute("edit_file", {"path": "e.txt", "old_string": "beta", "new_string": "BETA"})
    assert (tmp_path / "e.txt").read_text() == "alpha\nBETA\ngamma\n"

    # A numbered-looking old_string (as if copy-pasted from read_file's display)
    # does not exist verbatim in the raw file, so it is correctly refused.
    with pytest.raises(ToolError):
        ex.execute(
            "edit_file",
            {"path": "e.txt", "old_string": "     1\talpha", "new_string": "nope"},
        )
