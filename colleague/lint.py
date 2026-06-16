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


def _run(cmd: list[str], repo_path: str | Path) -> Optional[subprocess.CompletedProcess]:
    """Run *cmd* in *repo_path*; return ``None`` on ``FileNotFoundError``."""
    try:
        return subprocess.run(cmd, cwd=str(repo_path), capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return None


def run_lint_gate(repo_path: str | Path, changed_files: list[str]) -> Optional[LintReport]:
    """Run configured fixers then reporters on the changed Python files.

    Returns ``None`` when no linters are configured or there are no Python
    files to lint.  Otherwise returns a :class:`~colleague.contract.LintReport`.
    """
    detected = detect_linters(repo_path)
    if not detected:
        return None

    repo = Path(repo_path)
    py = [f for f in changed_files if f.endswith(".py") and (repo / f).is_file()]
    if not py:
        return None

    fixed: list[str] = []
    residual: list[str] = []
    skipped: list[str] = []

    # ── FIXERS (auto-fix in place) ──────────────────────────────────
    if "isort" in detected:
        result = _run(["isort", *py], repo_path)
        if result is None:
            skipped.append("isort: not installed")
        else:
            fixed.append(f"isort: {_first_nonempty_line(result.stdout or result.stderr)}")

    if "black" in detected:
        result = _run(["black", *py], repo_path)
        if result is None:
            skipped.append("black: not installed")
        else:
            fixed.append(f"black: {_first_nonempty_line(result.stdout or result.stderr)}")

    if "ruff" in detected:
        # ruff check --fix
        result = _run(["ruff", "check", "--fix", *py], repo_path)
        if result is None:
            skipped.append("ruff: not installed")
        else:
            fixed.append(
                f"ruff check --fix: {_first_nonempty_line(result.stdout or result.stderr)}"
            )
        # ruff format
        result = _run(["ruff", "format", *py], repo_path)
        if result is not None:
            fixed.append(f"ruff format: {_first_nonempty_line(result.stdout or result.stderr)}")

    # ── REPORTERS (residual violations) ─────────────────────────────
    if "flake8" in detected:
        result = _run(["flake8", *py], repo_path)
        if result is None:
            skipped.append("flake8: not installed")
        elif result.returncode != 0:
            residual.extend(line for line in (result.stdout or "").splitlines() if line.strip())

    if "ruff" in detected:
        result = _run(["ruff", "check", *py], repo_path)
        if result is None:
            # Already recorded above; skip duplicate.
            pass
        elif result.returncode != 0:
            residual.extend(line for line in (result.stdout or "").splitlines() if line.strip())

    return LintReport(fixed=fixed, residual=residual, skipped=skipped)
