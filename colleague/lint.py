"""Lint pre-finish gate — detection + subprocess runner.

Pure lint mechanics: detect which linters are configured in a repo, run
fixers then reporters on changed Python files, and return a
:class:`~colleague.contract.LintReport`.  Does not touch the loop or the
model.
"""

from __future__ import annotations

import configparser
import subprocess
import tomllib
from pathlib import Path
from typing import Optional

from colleague.contract import LintReport

_LINTER_NAMES = frozenset({"black", "isort", "ruff", "flake8"})

# Per-linter subprocess ceiling (#209 review): a hung linter must never block the
# handoff. Generous — changed-files linting takes seconds; this is only a hang-guard.
_LINT_TIMEOUT = 300


def detect_linters(repo_path: str | Path) -> set[str]:
    """Return the set of configured linter names in *repo_path*.

    Reads ``pyproject.toml`` for black/isort/ruff and checks
    ``.flake8`` / ``setup.cfg`` / ``tox.ini`` for flake8.
    Missing or malformed files are silently ignored.
    """
    repo = Path(repo_path)
    detected: set[str] = set()

    # ── pyproject.toml ────────────────────────────────────────────────
    try:
        with open(repo / "pyproject.toml", "rb") as f:
            data = tomllib.load(f)
        tool = data.get("tool", {})
        if "black" in tool:
            detected.add("black")
        if "isort" in tool:
            detected.add("isort")
        if "ruff" in tool:
            detected.add("ruff")
    except (OSError, tomllib.TOMLDecodeError):
        pass

    # ── flake8 ───────────────────────────────────────────────────────
    for cfg_name in (".flake8", "setup.cfg", "tox.ini"):
        try:
            cp = configparser.ConfigParser()
            cp.read(repo / cfg_name)
            if cp.has_section("flake8"):
                detected.add("flake8")
                break
        except (OSError, configparser.Error):
            pass

    return detected


def _first_nonempty_line(text: str | None) -> str:
    """Return the first non-empty line of *text*, or ``'ran'`` if empty."""
    if text:
        for line in text.splitlines():
            if line.strip():
                return line.strip()
    return "ran"


def _record_fixer(
    report: LintReport, name: str, result: Optional[subprocess.CompletedProcess]
) -> None:
    """Record one fixer run on the report: a note in ``fixed`` or ``skipped``."""
    if result is None:
        report.skipped.append(f"{name}: not installed")
    else:
        report.fixed.append(f"{name}: {_first_nonempty_line(result.stdout or result.stderr)}")


def _record_reporter(
    report: LintReport, name: str, result: Optional[subprocess.CompletedProcess]
) -> None:
    """Record one reporter run: residual violation lines, or a ``skipped`` note."""
    if result is None:
        report.skipped.append(f"{name}: not installed")
    elif result.returncode != 0:
        report.residual.extend(line for line in (result.stdout or "").splitlines() if line.strip())


def _fixer_commands(detected: set[str], py: list[str]) -> list[tuple[str, list[str]]]:
    """The (name, argv) fixer commands for the configured linters, in run order."""
    cmds: list[tuple[str, list[str]]] = []
    if "isort" in detected:
        cmds.append(("isort", ["isort", *py]))
    if "black" in detected:
        cmds.append(("black", ["black", *py]))
    if "ruff" in detected:
        cmds.append(("ruff check --fix", ["ruff", "check", "--fix", *py]))
        cmds.append(("ruff format", ["ruff", "format", *py]))
    return cmds


def _reporter_commands(detected: set[str], py: list[str]) -> list[tuple[str, list[str]]]:
    """The (name, argv) reporter commands for the configured linters, in run order."""
    cmds: list[tuple[str, list[str]]] = []
    if "flake8" in detected:
        cmds.append(("flake8", ["flake8", *py]))
    if "ruff" in detected:
        cmds.append(("ruff check", ["ruff", "check", *py]))
    return cmds


def _run(cmd: list[str], repo_path: str | Path) -> Optional[subprocess.CompletedProcess]:
    """Run *cmd* in *repo_path*; return ``None`` on ANY launch/timeout failure.

    The lint gate is best-effort and must never crash or block the handoff: a
    missing binary, a hung linter (``TimeoutExpired``), or any other OS/value
    error all degrade to ``None`` (recorded by the caller as ``skipped``).
    """
    try:
        return subprocess.run(
            cmd,
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            check=False,
            timeout=_LINT_TIMEOUT,
        )
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def run_lint_gate(repo_path: str | Path, changed_files: list[str]) -> Optional[LintReport]:
    """Run configured fixers then reporters on the changed Python files.

    Returns ``None`` when no linters are configured or there are no Python files
    to lint. Otherwise returns a :class:`~colleague.contract.LintReport`.
    """
    detected = detect_linters(repo_path)
    if not detected:
        return None
    repo = Path(repo_path)
    py = [f for f in changed_files if f.endswith(".py") and (repo / f).is_file()]
    if not py:
        return None
    report = LintReport()
    for name, cmd in _fixer_commands(detected, py):
        _record_fixer(report, name, _run(cmd, repo_path))
    for name, cmd in _reporter_commands(detected, py):
        _record_reporter(report, name, _run(cmd, repo_path))
    return report
