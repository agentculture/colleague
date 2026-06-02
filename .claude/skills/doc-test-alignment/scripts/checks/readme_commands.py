"""checks/readme_commands.py — doc-test-alignment check (a) "readme".

Scans every fenced ``bash`` block in README.md for ``colleague`` /
``uv run colleague`` invocations and dispatches each through the shared
:mod:`_cmd` engine:

  * SAFE introspection commands are EXECUTED (hardened env, short timeout) and
    their exit-code class is asserted against any adjacent ``#`` comment hint.
  * NETWORKED / side-effecting commands (vLLM, ``--base-url``, ``drive``,
    ``doctor --probe``, …) are NEVER executed — they are STATICALLY validated
    against the parsed ``colleague --help`` choice/option set.

All failures here are advisory ``severity="warning"`` (these checks do not gate
CI in v1). ``run()`` NEVER raises — internal failure returns a single
``severity="error"`` check so one broken check cannot take down the report.

Contract: ``NAME == "readme"`` and ``def run(repo: pathlib.Path) -> list[dict]``.
Stdlib only — no ``import colleague``.
"""

from __future__ import annotations

import pathlib
import sys

# scripts/ dir on sys.path so ``_md`` / ``_report`` resolve like the spine does.
_SCRIPTS_DIR = str(pathlib.Path(__file__).resolve().parents[1])
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)
_CHECKS_DIR = str(pathlib.Path(__file__).resolve().parent)
if _CHECKS_DIR not in sys.path:
    sys.path.insert(0, _CHECKS_DIR)

import _cmd  # type: ignore[import]  # noqa: E402
from _md import iter_fenced_blocks  # type: ignore[import]  # noqa: E402
from _report import make_check  # type: ignore[import]  # noqa: E402

NAME = "readme"


def _scan_blocks(blocks_text, repo: pathlib.Path):
    """Run the dispatch over a list of (label, block_text) and return checks + counts.

    Returns (checks, n_blocks, n_commands, n_executed, n_static, n_skipped).
    """
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
                # A "CLI not available / not executed" downgrade is counted as
                # skipped rather than executed.
                msg = check["message"].lower()
                if "not executed" in msg or "not available" in msg:
                    n_skipped += 1
                else:
                    n_executed += 1
            else:
                # networked OR unknown → fail-closed static validation.
                check = _cmd.static_validate(inv.command, repo, help_cache)
                n_static += 1
            checks.append(check)

    return checks, n_blocks, n_commands, n_executed, n_static, n_skipped


def run(repo: pathlib.Path) -> list:
    """Run check (a) "readme" against ``repo``. Never raises."""
    try:
        readme = repo / "README.md"
        if not readme.exists():
            return [
                make_check(
                    "readme_missing",
                    True,
                    "info",
                    "no README.md found; nothing to check",
                    "",
                )
            ]

        text = readme.read_text(encoding="utf-8", errors="replace")
        blocks = list(iter_fenced_blocks(text, "bash"))
        labelled = [(f"block@{line}", body) for line, body in blocks]

        (
            checks,
            n_blocks,
            n_commands,
            n_executed,
            n_static,
            n_skipped,
        ) = _scan_blocks(labelled, repo)

        summary = make_check(
            "readme_summary",
            True,
            "info",
            (
                f"scanned {n_blocks} bash block(s), {n_commands} colleague "
                f"command(s): {n_executed} executed, {n_static} static-validated, "
                f"{n_skipped} skipped (CLI unavailable)"
            ),
            "",
        )
        return [summary] + checks
    except Exception as exc:  # noqa: BLE001 - run() must never raise
        return [
            make_check(
                "readme_internal_error",
                False,
                "error",
                f"readme check failed internally: {exc.__class__.__name__}: {exc}",
                "This is a bug in the readme check module, not a doc drift.",
            )
        ]
