"""checks — registry for doc-test-alignment check modules.

CHECK MODULE CONTRACT
=====================
Each check module under ``checks/`` must follow this contract so the spine can
discover and run it without modification.

1. **Module name:** The module filename must match the value in NAME_TO_MODULE
   for the canonical check name (e.g. ``readme_commands.py`` for ``"readme"``).

2. **NAME constant:** Each module must define a top-level string constant::

       NAME = "<canonical-name>"   # e.g. "readme", "claude", "skills", "tests"

3. **run() function:** Each module must define::

       import pathlib

       def run(repo: pathlib.Path) -> list[dict]:
           ...

   where:
   - ``repo`` is an absolute ``pathlib.Path`` pointing to the repository root
     (the directory that contains ``pyproject.toml``).
   - Returns a list of check dicts built via ``_report.make_check``. An empty
     list is valid (the check has nothing to report).
   - MUST NOT raise — catch all exceptions and return them as a failed error
     check so one broken check cannot take down the whole report.
   - MUST be read-only: no file writes, no network calls, no daemon interaction.

4. **Portability:** The module must NOT ``import convertible`` or any third-party
   library. Stdlib only (``pathlib``, ``ast``, ``re``, ``subprocess``, etc.).

Registration
============
The spine discovers a check module by:
  1. Looking up ``NAME_TO_MODULE[name]`` to get the module filename stem.
  2. Importing ``checks.<stem>`` lazily at runtime.
  3. Calling ``run(repo)`` on it.

To add a new check, ONLY ADD a new file under ``checks/`` — do NOT edit this
``__init__.py`` (the pre-declared NAME_TO_MODULE already maps your canonical name
to your module filename).

Pending fallback
================
If a module does not exist yet (``ModuleNotFoundError``) or lacks a ``run``
callable, ``run_check`` returns a single ``info`` check with ``passed=True`` and
the id ``<name>_pending``. This lets the spine operate today with all four checks
"pending" (exit 0, aligned=True) and incrementally fills in as modules land.
"""

from __future__ import annotations

import importlib
import pathlib
import sys
from typing import List

__all__ = ["CANONICAL", "NAME_TO_MODULE", "run_check", "run_checks"]

# Canonical check names, in report order.
CANONICAL: List[str] = ["readme", "claude", "skills", "tests"]

# Maps each canonical name to the module filename stem under checks/.
# Pre-declared for all four checks even before the modules exist, so the
# registry shape is stable and later tasks only ADD files.
NAME_TO_MODULE: dict = {
    "readme": "readme_commands",
    "claude": "claude_commands",
    "skills": "skill_descriptions",
    "tests": "test_names",
}


def _make_pending(name: str) -> List[dict]:
    """Return a single pending info check for a not-yet-implemented check."""
    # Import _report lazily (it's a sibling module, also not on sys.path as a package)
    _ensure_scripts_on_path()
    from _report import make_check  # type: ignore[import]

    return [
        make_check(
            f"{name}_pending",
            True,
            "info",
            f"check '{name}' not yet implemented",
            "",
        )
    ]


def _ensure_scripts_on_path() -> None:
    """Ensure the scripts/ directory is on sys.path for sibling imports."""
    scripts_dir = str(pathlib.Path(__file__).resolve().parents[1])
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)


def run_check(name: str, repo: pathlib.Path) -> List[dict]:
    """Run the check module for *name* against *repo*.

    Lazily imports ``checks.<NAME_TO_MODULE[name]>``. If the module does not
    exist yet or has no ``run`` callable, returns a pending info check (passed=True)
    so the spine works with all checks in the "pending" state.
    """
    if name not in NAME_TO_MODULE:
        raise ValueError(f"unknown check name {name!r}; expected one of {CANONICAL}")

    module_stem = NAME_TO_MODULE[name]
    _ensure_scripts_on_path()

    try:
        # Ensure checks package directory is importable
        checks_pkg_dir = str(pathlib.Path(__file__).resolve().parent.parent)
        if checks_pkg_dir not in sys.path:
            sys.path.insert(0, checks_pkg_dir)
        mod = importlib.import_module(f"checks.{module_stem}")
    except ModuleNotFoundError:
        return _make_pending(name)

    if not hasattr(mod, "run") or not callable(mod.run):
        return _make_pending(name)

    return mod.run(repo)


def run_checks(names: List[str], repo: pathlib.Path) -> List[dict]:
    """Run selected checks in CANONICAL order, concatenating their results.

    *names* must be a subset of CANONICAL. Results are returned in CANONICAL
    order regardless of the order of *names*.
    """
    # Preserve CANONICAL ordering
    ordered = [n for n in CANONICAL if n in names]
    results: List[dict] = []
    for name in ordered:
        results.extend(run_check(name, repo))
    return results
