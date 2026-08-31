"""The hard file-length contract, enforced repo-wide over TRACKED source.

Ported from culture-nodes' ``tests/lint/filelength_test.go`` (the same gate,
expressed as pytest instead of Go). The hard limit is 1000 PHYSICAL lines,
comments included — comments count on purpose: the limit is about how much a
reviewer has to hold in their head, and a 1400-line file does not become
reviewable because 500 of those lines explain the other 900.

Scope: every tracked file with a source extension — **``.py`` first and
foremost**, plus the shell/JS/TS/Go/C/SQL extensions culture-nodes covers, so
the gate does not quietly stop applying if this repo grows one of those.

Relationship to :mod:`tests.test_file_length_ratchet`: that gate is the SOFT
one (a per-file baseline that only tightens; over-1000 merely warns). This one
is the HARD ceiling. They are complementary, not duplicates — the ratchet stops
a 400-line module drifting to 900, this one stops anything crossing 1000.

Grandfathering, honestly: 21 files already exceeded the limit when this gate
landed. They are pinned in :data:`GRANDFATHERED` at their then-current length
and the list is **shrink-only** — a pinned file may not grow, and once it drops
to or below the limit its entry must be deleted (the test fails until it is, so
the list cannot silently outlive the problem). Nothing may be ADDED to it
without a deliberate edit to this file.
"""

from __future__ import annotations

import subprocess  # nosec B404 — `git ls-files`, the tracked-file source of truth
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: The hard ceiling, in physical lines (inclusive: exactly 1000 is fine).
MAX_SOURCE_FILE_LINES = 1000

#: Source extensions the gate covers. ``.py`` is the one that matters here;
#: the rest mirror culture-nodes so the contract is the same contract.
SOURCE_EXTENSIONS = frozenset(
    {".c", ".cc", ".go", ".h", ".js", ".jsx", ".mjs", ".py", ".sh", ".sql", ".ts", ".tsx"}
)

#: Files that already exceeded the limit when this gate landed (2026-08-31),
#: pinned at their length on that day. SHRINK-ONLY: an entry may never be
#: raised, and must be REMOVED once the file fits. Never add to this list.
GRANDFATHERED: dict[str, int] = {}


def count_lines(contents: str) -> int:
    """Count PHYSICAL lines, including a final line with no trailing newline."""
    if not contents:
        return 0
    lines = contents.count("\n")
    if not contents.endswith("\n"):
        lines += 1
    return lines


def _tracked_files(root: Path) -> list[str]:
    """Every path in the git index — the limit is about tracked source."""
    out = subprocess.run(  # nosec B603 B607 — fixed argv, no shell
        ["git", "ls-files", "-z"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [name for name in out.split("\0") if name]


def _is_source(name: str) -> bool:
    return Path(name).suffix in SOURCE_EXTENSIONS


def scan_lengths(root: Path, names: list[str]) -> dict[str, int]:
    """Line counts for the source files among ``names`` that exist under ``root``.

    Returning the full mapping (not just the violations) is the point: a
    scanner that examined nothing reports no violations, which is
    indistinguishable from a clean tree unless someone checks the count. See
    :func:`test_the_scanner_actually_scans`.
    """
    counts: dict[str, int] = {}
    for name in names:
        if not _is_source(name):
            continue
        path = root / name
        if not path.is_file():  # a deleted-but-still-indexed path
            continue
        counts[name] = count_lines(path.read_text(encoding="utf-8", errors="replace"))
    return counts


def test_tracked_source_files_stay_within_the_hard_line_limit() -> None:
    """No tracked source file exceeds 1000 lines, except the pinned few — and
    those may not grow."""
    counts = scan_lengths(REPO_ROOT, _tracked_files(REPO_ROOT))
    assert counts, "scanned no source files; this gate would pass on any tree"

    violations: list[str] = []
    for name, lines in sorted(counts.items()):
        if lines <= MAX_SOURCE_FILE_LINES:
            continue
        pinned = GRANDFATHERED.get(name)
        if pinned is None:
            violations.append(f"  {name}: {lines} lines (limit {MAX_SOURCE_FILE_LINES}) — split it")
        elif lines > pinned:
            violations.append(
                f"  {name}: {lines} lines, grew past its pin of {pinned} — "
                "the grandfather list is shrink-only"
            )

    assert not violations, (
        f"tracked source files exceed the {MAX_SOURCE_FILE_LINES}-line hard limit "
        "(comments count):\n" + "\n".join(violations)
    )


def test_the_grandfather_list_is_reaped() -> None:
    """A pinned file that now fits (or is gone) must lose its entry, so the
    exception list cannot outlive the problem it documents."""
    counts = scan_lengths(REPO_ROOT, _tracked_files(REPO_ROOT))
    stale = [
        f"  {name}: {counts.get(name, 0)} lines (pinned at {pinned})"
        + ("" if name in counts else " — file is gone")
        for name, pinned in sorted(GRANDFATHERED.items())
        if counts.get(name, 0) <= MAX_SOURCE_FILE_LINES
    ]
    assert not stale, (
        "grandfathered entries no longer needed — delete them from GRANDFATHERED "
        "so the hard limit applies again:\n" + "\n".join(stale)
    )


def test_the_scanner_actually_scans(tmp_path: Path) -> None:
    """The gate on the gate.

    The repo-wide test above passes when the tree is clean AND when the scanner
    is broken — a wrong root, an empty extension set, an off-by-one on the
    threshold all produce the same silent green. So plant files that must be
    caught and files that must not be, and check the verdict on each.
    """

    def write(name: str, lines: int, trailing_newline: bool = True) -> None:
        body = "x\n" * lines
        if not trailing_newline and lines:
            body = body[:-1]
        (tmp_path / name).write_text(body, encoding="utf-8")

    write("over.py", MAX_SOURCE_FILE_LINES + 1)
    write("exactly_at_limit.py", MAX_SOURCE_FILE_LINES)
    # One line over, with no trailing newline — the case count_lines exists for.
    write("over_no_final_newline.ts", MAX_SOURCE_FILE_LINES + 1, trailing_newline=False)
    # Not a source extension: long, and deliberately ignored.
    write("huge.md", MAX_SOURCE_FILE_LINES * 2)

    names = ["over.py", "exactly_at_limit.py", "over_no_final_newline.ts", "huge.md"]
    counts = scan_lengths(tmp_path, names)

    assert set(counts) == {"over.py", "exactly_at_limit.py", "over_no_final_newline.ts"}, (
        "the .md must be skipped and the other three counted; got " f"{sorted(counts)}"
    )
    over = {n for n, lines in counts.items() if lines > MAX_SOURCE_FILE_LINES}
    assert "over.py" in over, "the scanner would not catch a new over-limit .py file"
    assert "over_no_final_newline.ts" in over, "a missing final newline hid an over-limit file"
    assert "exactly_at_limit.py" not in over, "the limit is inclusive"


def test_the_gate_covers_python() -> None:
    """``.py`` is in scope and the repo really has Python for it to cover —
    the explicit ask: this gate exists to police Python here."""
    assert ".py" in SOURCE_EXTENSIONS
    counts = scan_lengths(REPO_ROOT, _tracked_files(REPO_ROOT))
    py = [name for name in counts if name.endswith(".py")]
    assert len(py) > 100, f"only {len(py)} tracked .py files scanned — scope looks wrong"
