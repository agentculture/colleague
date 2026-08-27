"""Tests for :mod:`colleague.readpage` — paged, grounded read_file rendering (plan t9).

Acceptance (c8/h6): ORIGINAL line numbers survive paging (offset 500 keeps the
#240 grounding); defaults 1000 lines / 25,000 chars; a cut result ends with
exactly ``Read lines X-Y of N``; a file that fits is returned byte-identical to
the unpaged ``cat -n`` rendering (no trailer).
"""

from __future__ import annotations

import pytest

from colleague import readpage
from colleague.tools import ToolError, _number_lines


def _file(n: int) -> str:
    return "\n".join(f"L{i:04d}" for i in range(1, n + 1)) + "\n"


def test_number_lines_matches_tools_grounding_rule() -> None:
    # Same bare-"\n" rule as tools._number_lines (#240): \v/\f/  never split.
    text = "a\vb\n\nc d\n"
    assert readpage.number_lines(text) == _number_lines(text)
    assert readpage.number_lines("") == _number_lines("") == ""
    assert readpage.number_lines("x") == _number_lines("x")


def test_small_file_is_byte_identical_to_unpaged_rendering() -> None:
    text = "a\n\nb\n"
    assert (
        readpage.render_read(text, None, None)
        == _number_lines(text)
        == "     1\ta\n     2\t\n     3\tb"
    )


def test_offset_500_keeps_original_line_numbers() -> None:
    out = readpage.render_read(_file(600), 500, 3)
    assert out == "   500\tL0500\n   501\tL0501\n   502\tL0502\nRead lines 500-502 of 600"


def test_limit_only_pages_from_the_top() -> None:
    out = readpage.render_read(_file(10), None, 2)
    assert out == "     1\tL0001\n     2\tL0002\nRead lines 1-2 of 10"


def test_default_line_cap_is_1000_and_trailer_is_exact() -> None:
    out = readpage.render_read(_file(1500), None, None)
    lines = out.split("\n")
    assert lines[0] == "     1\tL0001"
    assert lines[999] == "  1000\tL1000"
    assert lines[-1] == "Read lines 1-1000 of 1500"
    assert len(lines) == 1001


def test_default_char_cap_is_25000_and_cuts_on_whole_lines() -> None:
    text = "\n".join("x" * 99 for _ in range(400)) + "\n"  # 400 lines, ~107 chars numbered
    out = readpage.render_read(text, None, None)
    body, trailer = out.rsplit("\n", 1)
    assert len(body) <= 25_000
    shown = body.count("\n") + 1
    assert trailer == f"Read lines 1-{shown} of 400"
    assert shown < 400
    assert body.endswith("x" * 99)  # never a mid-line cut


def test_explicit_ceiling_below_default_tightens(monkeypatch: pytest.MonkeyPatch) -> None:
    text = "\n".join("y" * 20 for _ in range(50)) + "\n"
    out = readpage.render_read(text, None, None, ceiling=100)
    body, trailer = out.rsplit("\n", 1)
    assert len(body) <= 100
    assert trailer.startswith("Read lines 1-") and trailer.endswith(" of 50")


def test_env_ceiling_cannot_loosen_the_25000_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_MAX_OUTPUT_CHARS", "100000")
    text = "\n".join("z" * 99 for _ in range(400)) + "\n"
    body, _ = readpage.render_read(text, None, None).rsplit("\n", 1)
    assert len(body) <= 25_000


def test_offset_past_end_reports_the_range_honestly() -> None:
    assert readpage.render_read(_file(5), 9, None) == "Read lines 9-5 of 5"


def test_at_least_one_line_is_always_shown() -> None:
    text = "w" * 5000 + "\n" + "v\n"
    out = readpage.render_read(text, None, None, ceiling=100)
    body, trailer = out.rsplit("\n", 1)
    assert body.startswith("     1\t") and len(body) <= 100
    assert trailer == "Read lines 1-1 of 2"


@pytest.mark.parametrize("bad", [{"offset": 0}, {"offset": -3}, {"limit": 0}, {"offset": "x"}])
def test_bad_offset_or_limit_is_a_self_correcting_tool_error(bad: dict) -> None:
    with pytest.raises(ToolError):
        readpage.render_read("a\n", bad.get("offset"), bad.get("limit"))


def test_bound_output_uses_per_tool_budgets_and_spills(tmp_path) -> None:
    big = "\n".join("line %d %s" % (i, "q" * 80) for i in range(2000)) + "\n"
    out = readpage.bound_output(big, "run_command", 68_000, tmp_path)
    assert "saved to:" in out and str(tmp_path / ".colleague" / "tool-output") in out
    spilled = list((tmp_path / ".colleague" / "tool-output").glob("*.txt"))
    assert len(spilled) == 1 and spilled[0].read_text(encoding="utf-8") == big
    small = "fits"
    assert readpage.bound_output(small, "", 68_000, tmp_path) == small


def test_bound_output_ceiling_is_the_tighter_of_config_and_tool(tmp_path) -> None:
    text = "\n".join("r" * 50 for _ in range(100)) + "\n"
    out = readpage.bound_output(text, "", 200, tmp_path)
    assert "truncated" in out.lower()
    preview = out.split("\n\n", 1)[-1]
    assert len(preview) <= 200 + len(readpage.truncation._SEPARATOR) + 60
