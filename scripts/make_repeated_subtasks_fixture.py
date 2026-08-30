#!/usr/bin/env python3
"""Generate the repeated-sub-tasks arm fixture (plan t16, brief
``docs/live-testing/briefs/arm-repeated-subtasks.md``).

Eight packages ``pkg_a``..``pkg_h`` under ``pkgs/``, each holding one
``core.py`` of the SAME shape: :data:`STEP_COUNT` public normaliser functions,
each reading its own module-level data table. Every package seeds exactly ONE
docstring/behaviour contradiction — one function whose docstring claims a
rounding precision its body does not use — at a per-package index
(:func:`contradiction_index`), so the eight audit sub-tasks are similar,
independent and each has a well-defined answer.

The point of the shape is AMORTISATION, not surface size: eight repeats of the
same small audit are the brief where hiring one helper once can pay for itself
across the run, which is what row 65 of ``docs/live-testing.md`` measures.

Deterministic: no randomness, no clock, no environment reads — the same
invocation always produces byte-identical files, so the fixture is
reproducible from this file alone (the brief's requirement, mirroring
``scripts/make_large_surface_fixture.py``). Recorded per-file line and char
counts are printed on generation; the per-package answer key is printed too,
flagged operator-only — it goes in the operator's notes, never into the
fixture repo.

Usage::

    python scripts/make_repeated_subtasks_fixture.py <target-dir>
"""

from __future__ import annotations

import sys
from pathlib import Path

#: The eight packages — eight similar independent sub-tasks (>= 6, the
#: amortising shape the brief requires).
PACKAGES = [f"pkg_{c}" for c in "abcdefgh"]

#: Public functions per package — every package has exactly this many.
STEP_COUNT = 8

#: Rows per module-level data table (bulk that is data, not behaviour). 28
#: keeps each generated ``core.py`` under 25,000 chars — ONE ``read_file``
#: page (``colleague/truncation.py`` ``DEFAULT_TOOL_MAX_CHARS``) — so each
#: sub-task is a genuinely small, one-page read.
TABLE_ROWS = 28


def contradiction_index(package: str) -> int:
    """The step index carrying *package*'s seeded contradiction.

    Derived from the package name, so it is deterministic while differing
    across packages — a uniform slice at one known offset cannot surface
    every contradiction at once.
    """
    return sum(ord(c) for c in package) % STEP_COUNT


def _claimed_precision(i: int) -> int:
    """The rounding precision step ``i``'s docstring claims (1..4)."""
    return i % 4 + 1


def _data_table(package: str, ordinal: int) -> list[str]:
    """A module-level data table — the reference rows step ``ordinal`` reads."""
    out = [
        f"#: Reference rows {ordinal:02d} for the {package} audit pipeline; step",
        f"#: {ordinal:02d} below reads them by tag, so the table is data, not behaviour.",
        f"_TABLE_{ordinal:02d} = (",
    ]
    for row in range(TABLE_ROWS):
        tag = f"{package}.t{ordinal:02d}.r{row:03d}"
        weight = (ordinal * 31 + row * 13) % 89
        scale = ((ordinal * 7 + row * 5) % 48) / 16.0
        out.append(f'    ("{tag}", {weight}, {scale}, "kind_{row % 5}"),')
    out.extend([")", "", ""])
    return out


def _step_function(package: str, i: int, *, contradict: bool) -> list[str]:
    """One public normaliser; ``contradict`` makes the docstring's claimed
    rounding precision differ from the body's by exactly one."""
    claimed = _claimed_precision(i)
    actual = claimed + 1 if contradict else claimed
    plural = "place" if claimed == 1 else "places"
    return [
        f"def {package}_step_{i:02d}(payload, *, table=None):",
        f'    """Normalise payload variant {i} for the {package} audit pipeline.',
        "",
        "    The canonical form lower-cases and strips every string value and",
        f"    rounds every numeric value to {claimed} decimal {plural} before the",
        "    table weights are folded in, so downstream stages always see the",
        "    same width for this variant.",
        "",
        "    The reference table supplies the per-tag weights this variant",
        "    applies when it folds the payload into its summary form; callers",
        "    holding a filtered table may pass it in, otherwise the module-level",
        "    table for this variant is used, which is the common case.",
        "",
        "    Args:",
        "        payload: the mapping to normalise; the input is never mutated.",
        "        table: optional replacement for the module-level reference",
        "            rows; each row is a (tag, weight, scale, kind) tuple.",
        "",
        "    Returns:",
        "        A new mapping with the values canonicalised plus the derived",
        "        'weight' and 'kind' entries.",
        '    """',
        "    result = {}",
        "    for key, value in sorted(payload.items()):",
        "        if isinstance(value, str):",
        "            result[key] = value.strip().lower()",
        "        elif isinstance(value, bool):",
        "            result[key] = value",
        "        elif isinstance(value, (int, float)):",
        f"            result[key] = round(float(value), {actual})",
        "        else:",
        "            result[key] = value",
        f"    rows = table if table is not None else _TABLE_{i:02d}",
        "    weight = 0",
        "    for tag, row_weight, row_scale, row_kind in rows:",
        f"        if not tag.endswith('{i % 5}'):",
        "            continue",
        "        weight += row_weight",
        f"        if row_kind == 'kind_{i % 5}':",
        "            weight += 1",
        "    result['weight'] = weight",
        f"    result.setdefault('kind', '{package}.v{i}')",
        "    return result",
        "",
        "",
    ]


def _package_source(package: str) -> str:
    seeded = contradiction_index(package)
    lines = [
        f'"""{package}.core — part of the repeated-sub-tasks audit fixture.',
        "",
        "    Generated by scripts/make_repeated_subtasks_fixture.py; every package",
        "    in this fixture has the same shape and is audited independently.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "",
    ]
    for i in range(STEP_COUNT):
        lines.extend(_data_table(package, i))
        lines.extend(_step_function(package, i, contradict=(i == seeded)))
    return "\n".join(lines) + "\n"


def main(target: str) -> int:
    root = Path(target)
    pkgs = root / "pkgs"
    pkgs.mkdir(parents=True, exist_ok=True)
    (pkgs / "__init__.py").write_text("", encoding="utf-8")

    total_lines = 0
    total_chars = 0
    print(f"{'package':10s} {'lines':>7s} {'chars':>8s}")
    for package in PACKAGES:
        pkg_dir = pkgs / package
        pkg_dir.mkdir(parents=True, exist_ok=True)
        (pkg_dir / "__init__.py").write_text("", encoding="utf-8")
        source = _package_source(package)
        (pkg_dir / "core.py").write_text(source, encoding="utf-8")
        lines = len(source.splitlines())
        total_lines += lines
        total_chars += len(source)
        print(f"{package:10s} {lines:7d} {len(source):8d}")
    print(f"{'TOTAL':10s} {total_lines:7d} {total_chars:8d}")

    print()
    print("answer key (operator-only — never commit into the fixture repo):")
    for package in PACKAGES:
        i = contradiction_index(package)
        print(
            f"  {package}: {package}_step_{i:02d} claims {_claimed_precision(i)} "
            f"decimal place(s), rounds to {_claimed_precision(i) + 1}"
        )
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
