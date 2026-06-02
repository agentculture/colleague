"""checks/claude_commands.py — doc-test-alignment check (b) "claude".

Same engine as check (a), but scoped to the fenced ``bash`` block(s) under the
``## Commands`` heading of CLAUDE.md (the "build/test/publish" command lines).
Reuses :mod:`_cmd` so classification, execution, and static-validation behave
identically to the README check (one shared engine).

All failures are advisory ``severity="warning"``. ``run()`` NEVER raises.

Contract: ``NAME == "claude"`` and ``def run(repo: pathlib.Path) -> list[dict]``.
Stdlib only — no ``import colleague``.
"""

from __future__ import annotations

import pathlib
import re
import sys

_SCRIPTS_DIR = str(pathlib.Path(__file__).resolve().parents[1])
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)
_CHECKS_DIR = str(pathlib.Path(__file__).resolve().parent)
if _CHECKS_DIR not in sys.path:
    sys.path.insert(0, _CHECKS_DIR)

import _cmd  # type: ignore[import]  # noqa: E402
from _md import iter_fenced_blocks  # type: ignore[import]  # noqa: E402
from _report import make_check  # type: ignore[import]  # noqa: E402

NAME = "claude"

# An ATX heading line like ``## Commands`` (level 1-6, exactly "Commands").
_COMMANDS_HEADING_RE = re.compile(r"^#{1,6}\s+Commands\s*$")
_ANY_HEADING_RE = re.compile(r"^#{1,6}\s+\S")


def _commands_section(text: str) -> str:
    """Return the slice of *text* from the ``## Commands`` heading to the next
    heading of the same-or-shallower level (or EOF). Empty string if not found.

    Fence-aware: a ``#`` comment line INSIDE a fenced code block (e.g.
    ``# Extensibility layer:``) is NOT mistaken for a Markdown heading, so a
    Commands block full of shell comments is captured in full.
    """
    lines = text.splitlines()
    start = None
    start_level = 0
    for i, line in enumerate(lines):
        if _COMMANDS_HEADING_RE.match(line):
            start = i
            start_level = len(line) - len(line.lstrip("#"))
            break
    if start is None:
        return ""

    end = len(lines)
    in_fence = False
    for j in range(start + 1, len(lines)):
        line = lines[j]
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if _ANY_HEADING_RE.match(line):
            level = len(line) - len(line.lstrip("#"))
            if level <= start_level:
                end = j
                break
    return "\n".join(lines[start:end])


def _scan_blocks(blocks_text, repo: pathlib.Path):
    """Dispatch over (label, block_text) pairs; return checks + counts."""
    checks: list = []
    help_cache: dict = {}
    n_blocks = 0
    n_commands = 0
    n_executed = 0
    n_static = 0
    n_skipped = 0

    for _label, block in blocks_text:
        n_blocks += 1
        for inv in _cmd.iter_colleague_invocations(block):
            n_commands += 1
            kind = _cmd.classify(inv.command, inv.env_assignments)
            if kind == "safe":
                check = _cmd.run_safe(inv, repo)
                msg = check["message"].lower()
                if "not executed" in msg or "not available" in msg:
                    n_skipped += 1
                else:
                    n_executed += 1
            else:
                check = _cmd.static_validate(inv.command, repo, help_cache)
                n_static += 1
            checks.append(check)

    return checks, n_blocks, n_commands, n_executed, n_static, n_skipped


def run(repo: pathlib.Path) -> list:
    """Run check (b) "claude" against ``repo``. Never raises."""
    try:
        claude = repo / "CLAUDE.md"
        if not claude.exists():
            return [
                make_check(
                    "claude_missing",
                    True,
                    "info",
                    "no CLAUDE.md found; nothing to check",
                    "",
                )
            ]

        text = claude.read_text(encoding="utf-8", errors="replace")
        section = _commands_section(text)
        if not section:
            return [
                make_check(
                    "claude_summary",
                    True,
                    "info",
                    "CLAUDE.md has no '## Commands' section; nothing to check",
                    "",
                )
            ]

        blocks = list(iter_fenced_blocks(section, "bash"))
        labelled = [(f"commands-block@{line}", body) for line, body in blocks]

        (
            checks,
            n_blocks,
            n_commands,
            n_executed,
            n_static,
            n_skipped,
        ) = _scan_blocks(labelled, repo)

        summary = make_check(
            "claude_summary",
            True,
            "info",
            (
                f"scanned {n_blocks} bash block(s) under '## Commands', "
                f"{n_commands} colleague command(s): {n_executed} executed, "
                f"{n_static} static-validated, {n_skipped} skipped (CLI unavailable)"
            ),
            "",
        )
        return [summary] + checks
    except Exception as exc:  # noqa: BLE001 - run() must never raise
        return [
            make_check(
                "claude_internal_error",
                False,
                "error",
                f"claude check failed internally: {exc.__class__.__name__}: {exc}",
                "This is a bug in the claude check module, not a doc drift.",
            )
        ]
