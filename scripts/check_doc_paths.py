#!/usr/bin/env python3
"""Read-only doc-path checker (stdlib only).

Greps every `colleague/...py` citation out of the live docs (docs/features/,
CLAUDE.md, AGENTS.colleague.md, README.md) and asserts each resolves to a
real file in the tree. `docs/specs/` is append-only history and is
deliberately NOT scanned (c34) -- neither are bare `file.py:LINE` line-number
citations, which go stale by design and are out of scope.

Usage: uv run python scripts/check_doc_paths.py [--json]
Exit code: 0 if every citation resolves, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# A citation: a colleague/... path ending in .py, optionally backtick-quoted,
# optionally followed by :LINE or :LINE-LINE which we strip before checking.
# Negative lookbehind excludes `.colleague/...` (operator config-dir examples,
# e.g. `.colleague/hooks/fix-footer-escape.py`) which are not source citations.
PATH_RE = re.compile(r"(?<![./\w])colleague/[A-Za-z0-9_./\-]+\.py")

SCAN_TARGETS = [
    REPO_ROOT / "CLAUDE.md",
    REPO_ROOT / "AGENTS.colleague.md",
    REPO_ROOT / "README.md",
]


def iter_doc_files() -> list[Path]:
    files = [p for p in SCAN_TARGETS if p.exists()]
    features_dir = REPO_ROOT / "docs" / "features"
    if features_dir.exists():
        files.extend(sorted(features_dir.rglob("*.md")))
    return files


def check_file(doc_path: Path) -> list[dict]:
    findings = []
    text = doc_path.read_text(encoding="utf-8", errors="replace")
    for lineno, line in enumerate(text.splitlines(), start=1):
        for match in PATH_RE.finditer(line):
            cited = match.group(0)
            target = REPO_ROOT / cited
            if not target.is_file():
                findings.append(
                    {
                        "doc": str(doc_path.relative_to(REPO_ROOT)),
                        "line": lineno,
                        "citation": cited,
                    }
                )
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit JSON")
    args = parser.parse_args()

    all_findings: list[dict] = []
    scanned = 0
    for doc in iter_doc_files():
        scanned += 1
        all_findings.extend(check_file(doc))

    if args.json:
        print(json.dumps({"scanned": scanned, "unresolved": all_findings}, indent=2))
    else:
        print(f"Scanned {scanned} doc file(s) for colleague/*.py citations.")
        if not all_findings:
            print("OK: every cited colleague/*.py path resolves.")
        else:
            print(f"FOUND {len(all_findings)} unresolved citation(s):")
            for f in all_findings:
                print(f"  {f['doc']}:{f['line']}: {f['citation']}")

    return 1 if all_findings else 0


if __name__ == "__main__":
    sys.exit(main())
