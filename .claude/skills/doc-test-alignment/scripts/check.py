#!/usr/bin/env python3
"""check.py — doc-test-alignment CLI entry point.

Usage:
    check.py [--only <check>]... [--repo <path>] [--json]

Options:
    --only <check>   Run only the named check(s). Repeatable and comma-splittable.
                     Valid values: readme, claude, skills, tests.
    --repo <path>    Repository root (dir containing pyproject.toml). Defaults to
                     walking up from cwd until pyproject.toml is found.
    --json           Emit the aggregate dict as JSON to stdout.

Exit codes:
    0  aligned (no failed error-severity checks)
    1  drift found (at least one error-severity check failed)
    2  usage or operational error
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

# Ensure this script's directory is on sys.path so sibling imports work
# regardless of how the script is invoked.
_THIS_DIR = pathlib.Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from _report import aggregate  # type: ignore[import]
from checks import CANONICAL, run_checks  # type: ignore[import]


def _find_repo_root(start: pathlib.Path) -> pathlib.Path | None:
    """Walk up from *start* until a directory containing pyproject.toml is found."""
    current = start.resolve()
    while current != current.parent:
        if (current / "pyproject.toml").exists():
            return current
        current = current.parent
    return None


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="check.py",
        description="Verify doc-test alignment for a repository.",
        add_help=True,
    )
    parser.add_argument(
        "--only",
        action="append",
        metavar="CHECK",
        dest="only",
        default=[],
        help=(
            "Run only the named check(s). Repeatable and comma-splittable. "
            f"Valid values: {', '.join(CANONICAL)}."
        ),
    )
    parser.add_argument(
        "--repo",
        metavar="PATH",
        default=None,
        help="Repository root (default: walk up from cwd to find pyproject.toml).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        dest="json_output",
        help="Emit the aggregate dict as JSON to stdout.",
    )
    return parser.parse_args(argv)


def _resolve_checks(only_args: list[str]) -> list[str] | None:
    """Expand --only args (comma-splittable) into a validated list of check names.

    Returns None if any name is invalid (caller should exit 2).
    """
    names: list[str] = []
    for arg in only_args:
        for part in arg.split(","):
            names.append(part.strip())

    if not names:
        return list(CANONICAL)

    invalid = [n for n in names if n not in CANONICAL]
    if invalid:
        print(
            f"error: unknown check name(s): {', '.join(invalid)}\n"
            f"  valid names: {', '.join(CANONICAL)}\n"
            f"  example: --only readme --only claude",
            file=sys.stderr,
        )
        return None
    return names


def _resolve_repo(repo_arg: str | None) -> pathlib.Path | None:
    """Resolve the repository root path.

    Uses --repo if given, otherwise walks up from cwd.
    Returns None if not found.
    """
    if repo_arg is not None:
        p = pathlib.Path(repo_arg).resolve()
        if not (p / "pyproject.toml").exists():
            print(
                f"error: --repo {repo_arg!r} does not contain pyproject.toml",
                file=sys.stderr,
            )
            return None
        return p

    found = _find_repo_root(pathlib.Path.cwd())
    if found is None:
        print(
            "error: could not find pyproject.toml walking up from cwd.\n"
            "  Use --repo <path> to specify the repository root explicitly.",
            file=sys.stderr,
        )
    return found


def _render_human(result: dict) -> str:
    """Format the aggregate result as human-readable text."""
    lines: list[str] = []

    if result["aligned"]:
        lines.append("doc-test-alignment: aligned")
    else:
        lines.append("doc-test-alignment: drift found")

    for check in result["checks"]:
        passed = check["passed"]
        severity = check["severity"]
        cid = check["id"]
        message = check["message"]
        remediation = check.get("remediation", "")

        if passed:
            marker = "[PASS]"
        elif severity == "error":
            marker = "[FAIL]"
        else:
            marker = "[WARN]"

        lines.append(f"  {marker} {cid} — {message}")
        if not passed and remediation:
            lines.append(f"    hint: {remediation}")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    # Resolve check names
    selected = _resolve_checks(args.only)
    if selected is None:
        return 2

    # Resolve repo root
    repo = _resolve_repo(args.repo)
    if repo is None:
        return 2

    # Run checks
    checks = run_checks(selected, repo)
    result = aggregate(checks)

    # Output
    if args.json_output:
        print(json.dumps(result))
    else:
        print(_render_human(result))

    # Exit code
    if result["aligned"]:
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
