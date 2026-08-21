"""File-length ratchet (approved deviation d6, operator 2026-08-21).

A checked-in per-file line-count baseline (``tests/file_length_baseline.json``)
pins every ``colleague/**/*.py`` at the HEAD of the work that introduced this
ratchet. The ratchet only tightens:

* a module that GROWS past its baseline line count FAILS — shrink it, or
  split it, before it may grow again;
* a module that SHRINKS (or is deleted) never fails — the baseline entry is
  stale and is updated via the helper below;
* a NEW module absent from the baseline is allowed only under 1000 lines;
* any module over 1000 lines emits a ``pytest`` WARNING (surfaced by pytest),
  never a failure.

Baseline update (the ONLY sanctioned way to move the ratchet):

    FILE_LENGTH_BASELINE_UPDATE=1 python -m pytest tests/test_file_length_ratchet.py

or, without pytest:

    python -c "from tests.test_file_length_ratchet import write_baseline; write_baseline()"

The env var is conftest-free on purpose: a plain ``python -c`` invocation has
no pytest session, so the helper is importable and callable directly.
"""

from __future__ import annotations

import json
import os
import warnings
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_DIR = REPO_ROOT / "colleague"
BASELINE_PATH = Path(__file__).resolve().parent / "file_length_baseline.json"

#: The hard ceiling for NEW modules (absent from the baseline).
NEW_MODULE_MAX_LINES = 1000

#: The soft ceiling: modules over this emit a pytest WARNING, never a failure.
WARN_THRESHOLD_LINES = 1000


def _all_package_py_files() -> list[Path]:
    """Every ``colleague/**/*.py`` at the repo root, sorted for determinism."""
    return sorted(PACKAGE_DIR.rglob("*.py"))


def _line_count(path: Path) -> int:
    """The file's line count (``splitlines`` — a trailing newline is not a line)."""
    return len(path.read_text(encoding="utf-8").splitlines())


def _load_baseline() -> dict[str, int]:
    if not BASELINE_PATH.is_file():
        raise AssertionError(
            f"baseline missing: {BASELINE_PATH} — regenerate it with "
            "FILE_LENGTH_BASELINE_UPDATE=1 python -m pytest "
            "tests/test_file_length_ratchet.py (or write_baseline())"
        )
    data = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not all(
        isinstance(k, str) and isinstance(v, int) for k, v in data.items()
    ):
        raise AssertionError(f"baseline malformed (expected a path->int mapping): {BASELINE_PATH}")
    return data


def write_baseline() -> dict[str, int]:
    """(Re)write ``tests/file_length_baseline.json`` from the current tree.

    The ratchet's only sanctioned update path: run it after a deliberate
    shrink/split/delete, then commit the new baseline. Never run it to
    *raise* a ceiling for a module that grew — that is the failure this
    test exists to catch.
    """
    baseline = {
        p.relative_to(REPO_ROOT).as_posix(): _line_count(p) for p in _all_package_py_files()
    }
    BASELINE_PATH.write_text(
        json.dumps(baseline, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return baseline


def _current_counts() -> dict[str, int]:
    return {p.relative_to(REPO_ROOT).as_posix(): _line_count(p) for p in _all_package_py_files()}


def test_ratchet() -> None:
    """The ratchet: no module grows past its baseline; new modules start under
    1000 lines; over-1000 modules warn (never fail)."""
    if os.environ.get("FILE_LENGTH_BASELINE_UPDATE") == "1":
        # Sanctioned update path: rewrite the baseline, then skip the check.
        write_baseline()
        pytest.skip("baseline updated via FILE_LENGTH_BASELINE_UPDATE=1")

    baseline = _load_baseline()
    current = _current_counts()

    grew: list[str] = []
    for path, lines in sorted(current.items()):
        if path in baseline:
            if lines > baseline[path]:
                grew.append(f"  {path}: {baseline[path]} -> {lines} (baseline: {baseline[path]})")
        else:
            if lines >= NEW_MODULE_MAX_LINES:
                grew.append(
                    f"  {path}: NEW module at {lines} lines (start under {NEW_MODULE_MAX_LINES})"
                )

    assert not grew, (
        "file-length ratchet violated — a module grew past its baseline (or a new "
        "module started over the ceiling). Shrink or split it; the ratchet only "
        "tightens. Stale entries (shrunk/deleted files) are harmless and are "
        "reaped by the baseline update:\n" + "\n".join(grew)
    )

    # Soft ceiling: over-1000 modules WARN (pytest surfaces it), never fail.
    for path, lines in sorted(current.items()):
        if lines > WARN_THRESHOLD_LINES:
            warnings.warn(
                f"{path} is {lines} lines (over the {WARN_THRESHOLD_LINES}-line soft "
                "ceiling) — a candidate for splitting",
                stacklevel=1,
            )


def test_baseline_covers_every_package_module() -> None:
    """Every current ``colleague/**/*.py`` is either in the baseline or is a new
    module under the ceiling — so the ratchet cannot be bypassed by a file the
    baseline simply forgot."""
    if os.environ.get("FILE_LENGTH_BASELINE_UPDATE") == "1":
        pytest.skip("baseline update in progress")
    baseline = _load_baseline()
    current = _current_counts()
    missing = sorted(p for p in current if p not in baseline and current[p] >= NEW_MODULE_MAX_LINES)
    assert not missing, (
        "modules absent from the baseline AND over the new-module ceiling — "
        "regenerate the baseline (write_baseline) so the ratchet covers them:\n"
        + "\n".join(f"  {p}: {current[p]} lines" for p in missing)
    )
