"""Determinism + shape tests for ``scripts/make_repeated_subtasks_fixture.py``
(plan t16, covers c21/h11; brief
``docs/live-testing/briefs/arm-repeated-subtasks.md``).

The brief's requirement is that the fixture is reproducible from the generator
alone: two invocations must produce byte-identical trees, the shape must be
the pre-registered one (8 packages, 8 public functions each), and every
package must carry exactly ONE seeded docstring/behaviour contradiction at
the index :func:`contradiction_index` declares — the per-package answer the
audit sub-tasks are scored against.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.make_repeated_subtasks_fixture import (  # noqa: E402
    PACKAGES,
    STEP_COUNT,
    contradiction_index,
    main,
)

_CLAIM_RE = re.compile(r"rounds every numeric value to (\d) decimal place")
_ACTUAL_RE = re.compile(r"round\(float\(value\), (\d)\)")


def _tree(root: Path) -> dict[str, bytes]:
    """Every file under *root* as ``relative path -> bytes``."""
    return {
        str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()
    }


def test_two_runs_produce_identical_trees(tmp_path: Path) -> None:
    """The determinism requirement: same invocation, byte-identical fixture."""
    first = tmp_path / "first"
    second = tmp_path / "second"
    assert main(str(first)) == 0
    assert main(str(second)) == 0
    tree_a, tree_b = _tree(first), _tree(second)
    assert tree_a  # non-empty — an empty tree would be vacuously identical
    assert tree_a == tree_b


def test_shape_is_the_pre_registered_one(tmp_path: Path) -> None:
    """8 packages, one ``core.py`` each with exactly STEP_COUNT public defs."""
    main(str(tmp_path))
    assert len(PACKAGES) >= 6  # the amortising shape the brief requires
    for package in PACKAGES:
        core = tmp_path / "pkgs" / package / "core.py"
        assert core.is_file()
        text = core.read_text(encoding="utf-8")
        defs = re.findall(r"^def (\w+)\(", text, flags=re.MULTILINE)
        assert len(defs) == STEP_COUNT
        assert all(name.startswith(f"{package}_step_") for name in defs)


def test_exactly_one_contradiction_per_package_at_declared_index(tmp_path: Path) -> None:
    """Each package: one function whose claimed precision != body precision,
    at :func:`contradiction_index`'s index, off by exactly one."""
    main(str(tmp_path))
    for package in PACKAGES:
        text = (tmp_path / "pkgs" / package / "core.py").read_text(encoding="utf-8")
        claimed = [int(m) for m in _CLAIM_RE.findall(text)]
        actual = [int(m) for m in _ACTUAL_RE.findall(text)]
        assert len(claimed) == len(actual) == STEP_COUNT
        mismatches = [i for i in range(STEP_COUNT) if claimed[i] != actual[i]]
        assert mismatches == [contradiction_index(package)]
        seeded = mismatches[0]
        assert actual[seeded] == claimed[seeded] + 1


def test_recorded_counts_are_printed(tmp_path: Path, capsys) -> None:
    """Generation records per-file line/char counts plus a TOTAL row (the
    brief quotes them), and the operator-only answer key."""
    main(str(tmp_path))
    out = capsys.readouterr().out
    for package in PACKAGES:
        assert re.search(rf"^{package}\s+\d+\s+\d+$", out, flags=re.MULTILINE)
    assert re.search(r"^TOTAL\s+\d+\s+\d+$", out, flags=re.MULTILINE)
    assert "answer key" in out
