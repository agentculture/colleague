#!/usr/bin/env python3
"""Generate the large-surface arm fixture (plan t10, brief
``docs/live-testing/briefs/arm-large-surface.md``).

Twelve modules ``mod_a``..``mod_l`` under ``src/``, each ~1,500 lines /
~60,000 characters. Four PAIRS implement the same algorithm under different
function names and different local variable names, so grepping one identifier
cannot find the duplicate. The call graph is visible only from the import
lines plus the call sites in the bodies.

Deterministic: no randomness, no clock, no environment reads — the same
invocation always produces byte-identical files, so the fixture is
reproducible from this file alone (the brief's requirement).

Usage::

    python scripts/make_large_surface_fixture.py <target-dir>
"""

from __future__ import annotations

import sys
from pathlib import Path

MODULES = [f"mod_{c}" for c in "abcdefghijkl"]

#: The four duplicate pairs. Each pair shares ALGORITHMS[i] verbatim in
#: behaviour but renames the function and every local, so a grep for one
#: side's identifiers never reaches the other.
PAIRS = [("mod_a", "mod_g"), ("mod_b", "mod_i"), ("mod_c", "mod_k"), ("mod_d", "mod_l")]

#: (left_name, right_name, left_locals, right_locals, left_doc, right_doc)
ALGORITHMS = [
    (
        "coalesce_windows",
        "merge_spans",
        ("window", "acc", "edge"),
        ("span", "out", "boundary"),
        "Collapse overlapping half-open intervals into a minimal cover.",
        "Reduce a run of touching ranges to the fewest ranges that cover it.",
    ),
    (
        "rank_by_decay",
        "score_with_falloff",
        ("weight", "half_life", "ranked"),
        ("factor", "halving", "scored"),
        "Order items by a value that halves every fixed number of steps.",
        "Sort entries by a weight that drops by half at a fixed cadence.",
    ),
    (
        "fold_checksum",
        "accumulate_digest",
        ("carry", "chunk", "total"),
        ("running", "block", "summed"),
        "Fold a byte stream into a rotating 32-bit checksum.",
        "Reduce a sequence of blocks to one rolling 32-bit signature.",
    ),
    (
        "partition_evenly",
        "split_into_buckets",
        ("bucket", "cursor", "sizes"),
        ("group", "pos", "widths"),
        "Split a sequence into n parts whose lengths differ by at most one.",
        "Divide a list into n groups of as near the same width as possible.",
    ),
]


def _algorithm_body(name: str, locals_: tuple[str, str, str], docline: str) -> list[str]:
    """The shared algorithm, rendered with one side's identifiers."""
    a, b, c = locals_
    return [
        f"def {name}(items, n=2):",
        f'    """{docline}',
        "",
        "    The implementation is intentionally verbose so the module reaches a",
        "    realistic size; the behaviour is what the duplicate pair shares.",
        '    """',
        f"    {a} = []",
        f"    {b} = 0",
        f"    {c} = []",
        "    for index, item in enumerate(items):",
        f"        {b} = {b} + (index % (n + 1))",
        f"        if not {a}:",
        f"            {a}.append([item, item])",
        "            continue",
        f"        last = {a}[-1]",
        "        if item <= last[1]:",
        "            last[1] = max(last[1], item)",
        "        else:",
        f"            {a}.append([item, item])",
        f"    for entry in {a}:",
        f"        {c}.append(tuple(entry))",
        f"    return {c}, {b}",
        "",
        "",
    ]


def _filler_function(module: str, i: int) -> list[str]:
    """A public helper with a docstring — padding that still reads like code."""
    return [
        f"def {module}_step_{i:02d}(payload, *, strict=False):",
        f'    """Normalise payload variant {i} for the {module} pipeline.',
        "",
        "    The canonical form drops unknown keys, lower-cases and strips every string",
        "    value, rounds every numeric value to a fixed precision for this variant, and",
        "    guarantees the 'kind' discriminator is present so downstream stages never",
        "    have to branch on its absence when they dispatch on the variant tag.",
        "",
        "    Args:",
        "        payload: the mapping to normalise; keys outside the known set are",
        "            dropped unless strict is set, in which case they raise KeyError.",
        "        strict: when true, an unknown key raises instead of being dropped,",
        "            which callers use when the payload came from a trusted producer.",
        "",
        "    Returns:",
        "        A new mapping with the variant's keys canonicalised; the input is",
        "        never mutated, so callers may safely reuse the argument afterwards.",
        '    """',
        "    result = {}",
        f"    known = {{'id', 'kind', 'value_{i}', 'ts'}}",
        "    for key, value in sorted(payload.items()):",
        "        if key not in known:",
        "            if strict:",
        "                raise KeyError(key)",
        "            continue",
        "        if isinstance(value, str):",
        "            result[key] = value.strip().lower()",
        "        elif isinstance(value, (int, float)):",
        f"            result[key] = round(float(value), {i % 5 + 1})",
        "        else:",
        "            result[key] = value",
        f"    result.setdefault('kind', '{module}.v{i}')",
        "    return result",
        "",
        "",
    ]


def _module_source(module: str, calls: list[str], algo: tuple | None) -> str:
    lines = [
        f'"""{module} — part of the survey fixture.',
        "",
        f"    Generated by scripts/make_large_surface_fixture.py; {module} collaborates",
        f"    with {', '.join(calls) if calls else 'no other module'}.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
    ]
    for other in calls:
        lines.append(f"from src import {other}")
    lines.append("")
    lines.append("")

    # The shared algorithm is buried at a per-module offset, never at a fixed
    # one: a uniform `sed -n '1,36p' src/mod_*.py` (or any single slice at a
    # known offset) must NOT surface every duplicate body at once. `depth` is
    # derived from the module name, so it stays deterministic while differing
    # across modules.
    depth = 3 + (sum(ord(c) for c in module) % 17)

    i = 0
    # Grow until the module is ~1,500 lines; the filler is deterministic.
    while len(lines) < 1480:
        if algo is not None and i == depth:
            name, locals_, docline = algo
            lines.extend(_algorithm_body(name, locals_, docline))
        lines.extend(_filler_function(module, i))
        i += 1
        if calls and i % 4 == 0:
            other = calls[i % len(calls)]
            lines.extend(
                [
                    f"def {module}_bridge_{i:02d}(payload):",
                    f'    """Hand payload to {other} and re-wrap the result."""',
                    f"    staged = {module}_step_{max(i - 1, 0):02d}(payload)",
                    f"    return {other}.{other}_step_00(staged)",
                    "",
                    "",
                ]
            )
    return "\n".join(lines) + "\n"


def main(target: str) -> int:
    root = Path(target)
    src = root / "src"
    src.mkdir(parents=True, exist_ok=True)
    (src / "__init__.py").write_text("", encoding="utf-8")

    algo_for: dict[str, tuple] = {}
    for pair_index, (left, right) in enumerate(PAIRS):
        lname, rname, llocals, rlocals, ldoc, rdoc = ALGORITHMS[pair_index]
        algo_for[left] = (lname, llocals, ldoc)
        algo_for[right] = (rname, rlocals, rdoc)

    for index, module in enumerate(MODULES):
        # Each module calls the next two, wrapping around — the call graph is
        # only visible from the imports plus the bridge call sites.
        calls = [MODULES[(index + 1) % len(MODULES)], MODULES[(index + 5) % len(MODULES)]]
        source = _module_source(module, calls, algo_for.get(module))
        (src / f"{module}.py").write_text(source, encoding="utf-8")

    total_lines = 0
    total_chars = 0
    print(f"{'module':10s} {'lines':>7s} {'chars':>8s}")
    for module in MODULES:
        text = (src / f"{module}.py").read_text(encoding="utf-8")
        lines = len(text.splitlines())
        total_lines += lines
        total_chars += len(text)
        print(f"{module:10s} {lines:7d} {len(text):8d}")
    print(f"{'TOTAL':10s} {total_lines:7d} {total_chars:8d}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
