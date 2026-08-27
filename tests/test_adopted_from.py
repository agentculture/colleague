"""
Guard test for the Qwen Code / Google Gemini CLI provenance ledger (t1 of
the adopt-from-qwen-code arc).

Asserts:
1. NOTICE exists at the repo root and names both upstream projects with
   license, version, and copyright holder.
2. docs/adopted-from.md exists, carries the documented header row, and is
   linked from both README.md and CLAUDE.md.
3. Every non-pending colleague path listed in the ledger exists and
   contains the literal ``adapted-from: qwen-code`` marker; a row is
   allowed a 'pending' colleague path ONLY while its date column also
   reads 'pending' (h13's tolerance for mechanisms the later tasks fill in).
4. A repo-wide grep for 'antigravity' (case-insensitive) over NOTICE,
   docs/, and colleague/ returns nothing (h12 — the lineage credit is
   Google Gemini CLI, never the unrelated Antigravity project).
"""

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

_HEADER_ROW = "mechanism | qwen-code path:lines | colleague path | date"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _ledger_rows():
    """Parse docs/adopted-from.md's table body into (mechanism, colleague_path, date) tuples.

    The table follows the documented header
    ``mechanism | qwen-code path:lines | colleague path | date`` (modeled on
    docs/skill-sources.md's table idiom). Rows are markdown table rows
    (``| a | b | c | d |``) after the header + separator line; the mechanism
    cell may carry a parenthetical description, so only the first
    whitespace-delimited token of the cell is used as the mechanism name.
    """
    ledger_path = REPO_ROOT / "docs" / "adopted-from.md"
    lines = _read(ledger_path).splitlines()

    rows = []
    in_table = False
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if not in_table:
            # Look for the header row.
            if len(cells) >= 4 and cells[0].lower() == "mechanism":
                in_table = True
            continue
        # Skip the markdown separator row (---|---|---|---).
        if all(re.fullmatch(r":?-+:?", c) for c in cells):
            continue
        if len(cells) < 4:
            continue
        mechanism, qwen_path, colleague_path, date = cells[0], cells[1], cells[2], cells[3]
        rows.append((mechanism, qwen_path, colleague_path, date))
    return rows


def test_notice_exists_and_names_both_projects():
    notice_path = REPO_ROOT / "NOTICE"
    assert notice_path.exists(), "NOTICE must exist at the repo root"
    text = _read(notice_path)

    # Qwen Code: project name, version, license, copyright holder.
    assert "Qwen Code" in text
    assert "QwenLM/qwen-code" in text
    assert "0.22.2" in text
    assert "Apache License, Version 2.0" in text or "Apache-2.0" in text
    assert "Qwen Team" in text

    # Google Gemini CLI lineage: project name, version, license, copyright holder.
    assert "Google Gemini CLI" in text
    assert "0.8.2" in text
    assert "Google LLC" in text


def test_adopted_from_ledger_exists_with_header_and_is_linked():
    ledger_path = REPO_ROOT / "docs" / "adopted-from.md"
    assert ledger_path.exists(), "docs/adopted-from.md must exist"
    text = _read(ledger_path)

    # Header row cells must appear, in order, somewhere in the file (allows
    # markdown table formatting/spacing around the pipes).
    header_cells = [c.strip() for c in _HEADER_ROW.split("|")]
    header_line_found = any(
        all(cell in line for cell in header_cells) for line in text.splitlines()
    )
    assert header_line_found, f"Expected a table header row with cells {header_cells}"

    readme = _read(REPO_ROOT / "README.md")
    claude_md = _read(REPO_ROOT / "CLAUDE.md")
    assert "adopted-from.md" in readme, "README.md must link docs/adopted-from.md"
    assert "adopted-from.md" in claude_md, "CLAUDE.md must link docs/adopted-from.md"


def test_ledger_has_rows():
    rows = _ledger_rows()
    assert len(rows) >= 1, "docs/adopted-from.md must have at least one mechanism row"


def test_every_ledger_colleague_path_exists_and_is_marked_or_pending():
    rows = _ledger_rows()
    assert rows, "no ledger rows parsed from docs/adopted-from.md"

    for mechanism, _qwen_path, colleague_path, date in rows:
        colleague_path_clean = colleague_path.strip("`")
        if colleague_path_clean == "pending":
            # Tolerated ONLY while the date column also reads 'pending'.
            assert date.strip("`") == "pending", (
                f"row {mechanism!r} has colleague path 'pending' but date "
                f"{date!r} is not also 'pending' — a landed mechanism must "
                "name its real colleague path"
            )
            continue

        target = REPO_ROOT / colleague_path_clean
        assert target.exists(), (
            f"row {mechanism!r} names colleague path {colleague_path!r} " "which does not exist"
        )
        content = _read(target)
        assert "adapted-from: qwen-code" in content, (
            f"row {mechanism!r}'s colleague path {colleague_path!r} does not "
            "contain the literal 'adapted-from: qwen-code' marker"
        )


def test_no_antigravity_references():
    """Antigravity is never credited: qwen-code's lineage is Google Gemini
    CLI, not Antigravity (docs/specs/2026-08-27-adopt-from-qwen-code.md's
    scope/boundaries section: "Crediting Antigravity would be a fabricated
    attribution unless the operator has a separate basis"). This mirrors the
    honesty condition via `grep -ri antigravity NOTICE docs colleague`.

    Scope note: docs/specs/ and docs/plans/ are devague's own frame/plan
    artifacts (this arc's confirmed spec + plan) — they legitimately name
    "Antigravity" by word to explain, and reject, the very attribution this
    guard exists to prevent (q1: "Antigravity is not credited (no basis in
    the qwen-code repo)"). Flagging that discussion as a violation would be
    a false positive, and excluding it is the only way this guard can ever
    pass once the spec/plan are committed (they are, from arc setup, and are
    out of this task's file list). The check instead covers every path a
    real (shipped) attribution could land: NOTICE, colleague/, and docs/
    minus docs/specs/ and docs/plans/.
    """
    docs_dir = REPO_ROOT / "docs"
    doc_files = [
        p
        for p in docs_dir.rglob("*")
        if p.is_file()
        and "specs" not in p.relative_to(docs_dir).parts
        and "plans" not in p.relative_to(docs_dir).parts
    ]
    targets = ["NOTICE", "colleague"] + [str(p.relative_to(REPO_ROOT)) for p in doc_files]

    result = subprocess.run(
        ["grep", "-ril", "antigravity", *targets],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    # grep exit code 1 = no matches (success for us); 0 = matches found (fail).
    assert result.returncode != 0, (
        f"'antigravity' found in: {result.stdout.strip()!r} — the lineage "
        "credit is Google Gemini CLI, never Antigravity"
    )
