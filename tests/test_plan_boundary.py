"""Boundary guard tests for colleague.plan — no socket/daemon/process spawning.

Asserts that every colleague/plan/*.py source file contains no references to
socket, threading, subprocess, multiprocessing, or os.fork.  The plan package
opens no socket/daemon and spawns no threads/processes itself (it delegates
parallelism to colleague.subagents).
"""

import re
from pathlib import Path

# Forbidden patterns: each is (description, compiled regex).
_FORBIDDEN_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "socket import",
        re.compile(r"\bimport\s+socket\b|from\s+socket\b"),
    ),
    (
        "threading import",
        re.compile(r"\bimport\s+threading\b|from\s+threading\b"),
    ),
    (
        "subprocess import",
        re.compile(r"\bimport\s+subprocess\b|from\s+subprocess\b"),
    ),
    (
        "multiprocessing import",
        re.compile(r"\bimport\s+multiprocessing\b|from\s+multiprocessing\b"),
    ),
    (
        "os.fork",
        re.compile(r"\bos\.fork\b"),
    ),
]


def _plan_py_sources() -> list[Path]:
    """Return every *.py file under colleague/plan/."""
    plan_dir = Path(__file__).resolve().parents[1] / "colleague" / "plan"
    return sorted(plan_dir.rglob("*.py"))


def test_plan_sources_no_forbidden_imports():
    """No colleague/plan/*.py source contains forbidden imports or calls."""
    violations: list[str] = []

    for py_file in _plan_py_sources():
        content = py_file.read_text(encoding="utf-8")
        lines = content.splitlines()
        rel = py_file.relative_to(Path(__file__).resolve().parents[1])

        for lineno, line in enumerate(lines, start=1):
            for description, pattern in _FORBIDDEN_PATTERNS:
                if pattern.search(line):
                    violations.append(f"{rel}:{lineno}: [{description}] {line.rstrip()!r}")

    assert not violations, "Forbidden import/call found in plan-mode source:\n" + "\n".join(
        violations
    )
