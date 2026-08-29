"""Pre-registration pins for live rows 49/50 (purpose-tools-associate-seat, t12).

The spec's honesty condition (c11/h11) requires rows 49 and 50 of
``docs/live-testing.md`` to be written BEFORE any run, in the exact
row-47/48 pre-registration shape: brief pointer, a throwaway repo WITH an
``.eidetic`` store (with the eidetic CLI version), the committed pass bar,
and ``result: pending``. The row-49 brief is the row-48 brief verbatim; the
row-50 brief is the row-47 web brief adapted to the ``web_survey`` purpose
tool. Both rows and both briefs name the memory distill counters to record.

This test pins that shape so a later live run (t14) cannot be pre-filled or
re-shaped silently.
"""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LEDGER = REPO / "docs" / "live-testing.md"
BRIEFS = REPO / "docs" / "live-testing" / "briefs"


def _matrix_rows():
    """Return {row_number: [num, feature, files, status, last_validated+issue]} cells.

    The 'Last validated' cell may itself contain `|` (e.g. `#435 #436 |`),
    so split only the first five cells and keep the rest of the line as the
    issue column.
    """
    rows = {}
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\|\s*(\d+)\s*\|", line)
        if not m:
            continue
        body = line.strip().strip("|")
        cells = [re.sub(r"\s+", " ", c).strip() for c in body.split("|", 4)]
        rows[int(m.group(1))] = cells
    return rows


def test_rows_49_and_50_exist_and_are_pending():
    rows = _matrix_rows()
    assert 49 in rows, "row 49 missing from the live-testing matrix"
    assert 50 in rows, "row 50 missing from the live-testing matrix"
    for n in (49, 50):
        status, last = rows[n][3], rows[n][4]
        assert status == "❌", f"row {n} status must be ❌ (not yet validated live)"
        assert "PRE-REGISTERED" in last, f"row {n} must be marked PRE-REGISTERED"
        assert "BEFORE any run" in last, f"row {n} must state it was written before any run"
        assert "result: pending" in last, (
            f"row {n} must carry the pre-registration 'result: pending' "
            "(a filled row keeps it before its '→ RUN' record)"
        )


def test_row_49_shape():
    cells = _matrix_rows()[49]
    last = cells[4]
    # brief pointer
    assert "docs/live-testing/briefs/row49-purpose.md" in last
    # repo: throwaway repo WITH an .eidetic store, eidetic CLI <version>
    assert "throwaway repo WITH an .eidetic store" in last
    assert re.search(r"eidetic CLI \d+\.\d+\.\d+", last), "row 49 must name the eidetic CLI version"
    # pass bar
    assert "purpose calls ≥ 1 on ≥ 2 of 3 runs" in last
    assert "turns ≤ 1.0×" in last
    assert "wall ≤ 1.2×" in last
    assert "e589451" in last
    assert "RE-RUN" in last
    assert "n=3" in last
    # memory distill counters named
    assert "memory distill counters" in last


def test_row_50_shape():
    cells = _matrix_rows()[50]
    last = cells[4]
    # brief pointer
    assert "docs/live-testing/briefs/row50-web-purpose.md" in last
    # repo: throwaway repo WITH an .eidetic store, eidetic CLI <version>
    assert "throwaway repo WITH an .eidetic store" in last
    assert re.search(r"eidetic CLI \d+\.\d+\.\d+", last), "row 50 must name the eidetic CLI version"
    # pass bar
    assert "scout child's served model = the associate's" in last
    assert "evidence ids" in last
    assert "final answer" in last
    assert "zero `run_command` steps outside the repo" in last
    # memory distill counters named
    assert "memory distill counters" in last


def _brief_block(path):
    """Return the fenced '## The brief' code block (the text pasted into `colleague work`)."""
    text = path.read_text(encoding="utf-8")
    m = re.search(r"## The brief.*?\n```text\n(.*?)\n```", text, re.DOTALL)
    assert m, f"{path.name} must carry a '## The brief' fenced block"
    return m.group(1)


def test_row49_brief_is_row48_verbatim():
    # The row-49 brief is the row-48 brief verbatim: the task text pasted into
    # `colleague work` is byte-identical; only the pre-registration metadata
    # (header, pass bar, record section) is adapted to the purpose-tool arm.
    row48_block = _brief_block(BRIEFS / "row48-delegation.md")
    row49_block = _brief_block(BRIEFS / "row49-purpose.md")
    assert row49_block == row48_block, "the row-49 brief text must be the row-48 brief verbatim"
    # the adapted metadata: purpose calls, not raw subagent steps
    row49 = (BRIEFS / "row49-purpose.md").read_text(encoding="utf-8")
    assert "row 49" in row49
    assert "purpose" in row49.lower()


def test_row50_brief_shape():
    text = re.sub(r"\s+", " ", (BRIEFS / "row50-web-purpose.md").read_text(encoding="utf-8"))
    assert "row 50" in text
    assert "web_survey" in text
    # the row-47 web brief's three upstream references survive verbatim
    for url in (
        "https://docs.example.com/api/overview",
        "https://docs.example.com/api/auth",
        "https://docs.example.com/api/errors",
    ):
        assert url in text
    # pass bar elements
    assert "served model" in text
    assert "evidence" in text
    assert "run_command" in text
    # memory distill counters named
    assert "memory distill counters" in text


def test_both_briefs_name_the_memory_distill_counters():
    for name in ("row49-purpose.md", "row50-web-purpose.md"):
        text = re.sub(r"\s+", " ", (BRIEFS / name).read_text(encoding="utf-8"))
        assert (
            "memory distill counters" in text
        ), f"{name} must name the memory distill counters to record"
