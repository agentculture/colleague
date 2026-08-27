"""read_file paging + spill truncation wiring in :class:`ToolExecutor` (plan t9).

Acceptance (c8/h6/c10/h8): ``read_file(path, offset?, limit?)`` keeps ORIGINAL
line numbers when paged; defaults 1000 lines / 25,000 chars; a cut result ends
with exactly ``Read lines X-Y of N``; ``run_command`` output is head+tail at
30,000 with the spilled file named under ``.colleague/tool-output/``; other
tools at 25,000; ``COLLEAGUE_MAX_OUTPUT_CHARS`` is a ceiling (decision c50).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from colleague.tools import SCHEMAS, ToolError, ToolExecutor


def _write(tmp_path: Path, name: str, n: int) -> None:
    (tmp_path / name).write_text("\n".join(f"L{i:04d}" for i in range(1, n + 1)) + "\n", "utf-8")


def test_schema_offers_offset_and_limit() -> None:
    props = next(s for s in SCHEMAS if s["function"]["name"] == "read_file")["function"][
        "parameters"
    ]
    assert props["required"] == ["path"]
    assert props["properties"]["offset"]["type"] == "integer"
    assert props["properties"]["limit"]["type"] == "integer"


def test_paged_read_at_offset_500_keeps_original_numbers(tmp_path: Path) -> None:
    _write(tmp_path, "big.py", 600)
    out = ToolExecutor(tmp_path).execute("read_file", {"path": "big.py", "offset": 500, "limit": 2})
    assert out.result == "   500\tL0500\n   501\tL0501\nRead lines 500-501 of 600"


def test_small_file_unchanged_no_trailer(tmp_path: Path) -> None:
    (tmp_path / "blank.txt").write_text("a\n\nb\n", encoding="utf-8")
    out = ToolExecutor(tmp_path).execute("read_file", {"path": "blank.txt"})
    assert out.result == "     1\ta\n     2\t\n     3\tb"


def test_default_line_cap_1000_then_page_on(tmp_path: Path) -> None:
    _write(tmp_path, "long.py", 1200)
    ex = ToolExecutor(tmp_path)
    first = ex.execute("read_file", {"path": "long.py"}).result
    assert first.endswith("\nRead lines 1-1000 of 1200")
    nxt = ex.execute("read_file", {"path": "long.py", "offset": 1001}).result
    assert nxt.startswith("  1001\tL1001")
    assert nxt.endswith("\nRead lines 1001-1200 of 1200")


def test_default_char_cap_25000_even_with_a_loose_env_ceiling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COLLEAGUE_MAX_OUTPUT_CHARS", "100000")
    (tmp_path / "wide.py").write_text("\n".join("x" * 99 for _ in range(400)) + "\n", "utf-8")
    out = ToolExecutor(tmp_path, max_output_chars=100_000).execute("read_file", {"path": "wide.py"})
    body, trailer = out.result.rsplit("\n", 1)
    assert len(body) <= 25_000
    assert trailer.startswith("Read lines 1-")
    assert trailer.endswith(" of 400")


def test_explicit_max_output_chars_still_tightens_read(tmp_path: Path) -> None:
    (tmp_path / "wide.py").write_text("\n".join("x" * 10 for _ in range(50)) + "\n", "utf-8")
    out = ToolExecutor(tmp_path, max_output_chars=100).execute("read_file", {"path": "wide.py"})
    body, trailer = out.result.rsplit("\n", 1)
    assert len(body) <= 100
    assert trailer.endswith(" of 50")
    assert body.split("\n")[0] == "     1\t" + "x" * 10  # numbering never shifted


def test_bad_offset_is_a_tool_error(tmp_path: Path) -> None:
    _write(tmp_path, "f.py", 3)
    with pytest.raises(ToolError):
        ToolExecutor(tmp_path).execute("read_file", {"path": "f.py", "offset": 0})


def test_run_command_output_is_head_tail_at_30000_and_spilled(tmp_path: Path) -> None:
    ex = ToolExecutor(tmp_path)
    out = ex.execute("run_command", {"command": "seq 1 20000"}).result
    assert "saved to:" in out
    spill_dir = tmp_path / ".colleague" / "tool-output"
    spilled = list(spill_dir.glob("*.txt"))
    assert len(spilled) == 1
    full = spilled[0].read_text(encoding="utf-8")
    assert full.startswith("exit=0\n1\n")
    assert full.rstrip().endswith("20000")
    assert "19999\n20000" in out
    assert "exit=0" in out  # head AND tail survive
    preview = out.split("\n\n", 1)[1]
    assert len(preview) < 32_000


def test_run_command_shell_cap_env_tightens_beneath_ceiling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COLLEAGUE_SHELL_MAX_CHARS", "500")
    out = ToolExecutor(tmp_path).execute("run_command", {"command": "seq 1 5000"}).result
    assert "saved to:" in out
    assert len(out.split("\n\n", 1)[1]) < 1_200


def test_other_tools_get_25000_and_spill(tmp_path: Path) -> None:
    for i in range(3000):
        (tmp_path / f"file_with_a_long_name_{i:05d}.txt").write_text("", "utf-8")
    out = ToolExecutor(tmp_path).execute("list_dir", {"path": "."}).result
    assert "saved to:" in out
    assert len(out.split("\n\n", 1)[1]) < 27_000


def test_spill_disabled_falls_back_to_head_tail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COLLEAGUE_TOOL_SPILL", "0")
    out = ToolExecutor(tmp_path).execute("run_command", {"command": "seq 1 20000"}).result
    assert "COLLEAGUE_TOOL_SPILL=0" in out
    assert not (tmp_path / ".colleague" / "tool-output").exists()


def test_spilled_file_is_readable_with_paging(tmp_path: Path) -> None:
    ex = ToolExecutor(tmp_path)
    out = ex.execute("run_command", {"command": "seq 1 20000"}).result
    spilled = next((tmp_path / ".colleague" / "tool-output").glob("*.txt"))
    rel = str(spilled.relative_to(tmp_path))
    page = ex.execute("read_file", {"path": rel, "offset": 19000, "limit": 3}).result
    assert page.startswith(" 19000\t")
    assert page.endswith("Read lines 19000-19002 of 20001")
    assert json.dumps(out)  # the preview is plain text, serialisable as a tool message
