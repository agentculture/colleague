#!/usr/bin/env python3
"""Generate the large-surface arm fixture (plan t10, brief
``docs/live-testing/briefs/arm-large-surface.md``).

Twelve modules ``mod_a``..``mod_l`` under ``src/``, each ~1,500 lines /
~60,000 characters and each exposing 8-12 public functions. Four PAIRS
implement the same algorithm under different function names, different
parameter names, different local variable names and different docstrings, so
grepping one identifier cannot find the duplicate — and the four pairs
implement four GENUINELY DIFFERENT algorithms (interval coalescing,
decay-ranked ordering, a rolling 32-bit checksum, even partitioning), so the
answer "four pairs" is well defined rather than one eight-way duplicate.

Bulk comes from module-level data tables and long function bodies, never from
emitting more public functions, so the public surface stays in the 8-12 band
the brief specifies.

The call graph is visible only from the import lines plus the call sites in
the bodies: every module imports two neighbours and bridges to BOTH of them
(one bridge per neighbour), so each module really has two outgoing call edges.

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

#: The four duplicate pairs. Pair ``i`` shares ALGORITHMS[i] — a distinct
#: algorithm per pair — but the two sides share NO identifiers, so a grep for
#: one side's names never reaches the other.
PAIRS = [("mod_a", "mod_g"), ("mod_b", "mod_i"), ("mod_c", "mod_k"), ("mod_d", "mod_l")]

#: One entry per pair: ``(left, right)``, each side a dict of the identifiers
#: that side uses plus its own docstring lines. The two sides of a pair are
#: behaviourally identical; the four pairs are behaviourally different.
ALGORITHMS: list[tuple[dict, dict]] = [
    (
        {
            "fn": "coalesce_windows",
            "arg": "intervals",
            "v": ("ordered", "cover", "window"),
            "doc": (
                "Collapse overlapping half-open intervals into a minimal cover.",
                "Each input element is a (start, end) pair. Sorting first means a",
                "single left-to-right sweep is enough: an interval either extends",
                "the interval currently being built or starts a new one.",
            ),
        },
        {
            "fn": "merge_spans",
            "arg": "ranges",
            "v": ("arranged", "result", "span"),
            "doc": (
                "Reduce a run of touching ranges to the fewest ranges covering it.",
                "Every entry is a (low, high) tuple. Once the entries are in order a",
                "one-pass scan suffices, because a range can only ever absorb into",
                "the range that is currently open or begin a fresh one.",
            ),
        },
    ),
    (
        {
            "fn": "rank_by_decay",
            "arg": "values",
            "extra": "half_life",
            "v": ("weighted", "position", "value", "weight", "record"),
            "lam": "row",
            "doc": (
                "Order items by a value that halves every fixed number of steps.",
                "The item at index i keeps 0.5 ** (i // half_life) of its magnitude,",
                "so later items fade geometrically. Ties fall back to the original",
                "position, which keeps the ordering stable and reproducible.",
            ),
        },
        {
            "fn": "score_with_falloff",
            "arg": "entries",
            "extra": "halving",
            "v": ("scored", "slot", "element", "factor", "pairing"),
            "lam": "item",
            "doc": (
                "Sort entries by a weight that drops by half at a fixed cadence.",
                "An entry sitting at offset k retains 0.5 ** (k // halving) of its",
                "size, so the tail decays geometrically. Equal weights keep their",
                "incoming offset order, which makes the result deterministic.",
            ),
        },
    ),
    (
        {
            "fn": "fold_checksum",
            "arg": "stream",
            "v": ("carry", "chunk"),
            "doc": (
                "Fold a byte stream into a rotating 32-bit checksum.",
                "Each step rotates the accumulator left by five bits, mixes in the",
                "low byte of the next element, and adds the golden-ratio constant.",
                "Everything is masked back to 32 bits so the result never widens.",
            ),
        },
        {
            "fn": "accumulate_digest",
            "arg": "blocks",
            "v": ("running", "block"),
            "doc": (
                "Reduce a sequence of blocks to one rolling 32-bit signature.",
                "Every iteration spins the register five places to the left, folds",
                "in the bottom eight bits of the block, then adds the golden-ratio",
                "increment, truncating to 32 bits after each of the three moves.",
            ),
        },
    ),
    (
        {
            "fn": "partition_evenly",
            "arg": "sequence",
            "extra": "parts",
            "v": ("base", "leftover", "buckets", "cursor", "index", "width"),
            "doc": (
                "Split a sequence into n parts whose lengths differ by at most one.",
                "The quotient gives every part its floor length and the remainder is",
                "handed out one element at a time to the earliest parts, so the",
                "widest and narrowest part are never more than one element apart.",
            ),
        },
        {
            "fn": "split_into_buckets",
            "arg": "items",
            "extra": "groups",
            "v": ("quota", "remainder", "chunks", "offset", "step", "size"),
            "doc": (
                "Divide a list into n groups of as near the same width as possible.",
                "Integer division fixes the shared floor size and what is left over",
                "is distributed a single element per group starting from the front,",
                "bounding the spread between the largest and smallest group at one.",
            ),
        },
    ),
]


def _docblock(doc: tuple[str, ...]) -> list[str]:
    """Render a side's own docstring — never shared with its pair partner."""
    out = [f'    """{doc[0]}', ""]
    out.extend(f"    {line}" for line in doc[1:])
    out.append('    """')
    return out


def _algo_coalesce(side: dict) -> list[str]:
    """Pair 0 — interval coalescing."""
    v0, v1, v2 = side["v"]
    arg = side["arg"]
    return [
        f"def {side['fn']}({arg}):",
        *_docblock(side["doc"]),
        f"    {v0} = sorted(tuple(pair) for pair in {arg})",
        f"    {v1} = []",
        f"    for {v2} in {v0}:",
        f"        if not {v1}:",
        f"            {v1}.append(({v2}[0], {v2}[1]))",
        "            continue",
        f"        if {v2}[0] <= {v1}[-1][1]:",
        f"            if {v2}[1] > {v1}[-1][1]:",
        f"                {v1}[-1] = ({v1}[-1][0], {v2}[1])",
        "        else:",
        f"            {v1}.append(({v2}[0], {v2}[1]))",
        f"    return {v1}",
        "",
        "",
    ]


def _algo_decay(side: dict) -> list[str]:
    """Pair 1 — decay-ranked ordering."""
    v0, v1, v2, v3, v4 = side["v"]
    arg, extra, lam = side["arg"], side["extra"], side["lam"]
    return [
        f"def {side['fn']}({arg}, {extra}=4):",
        *_docblock(side["doc"]),
        f"    if {extra} < 1:",
        f"        raise ValueError({extra!r})",
        f"    {v0} = []",
        f"    for {v1}, {v2} in enumerate({arg}):",
        f"        {v3} = float({v2}) * (0.5 ** ({v1} // {extra}))",
        f"        {v0}.append(({v3}, {v1}, {v2}))",
        f"    {v0}.sort(key=lambda {lam}: (-{lam}[0], {lam}[1]))",
        f"    return [({v4}[2], round({v4}[0], 6)) for {v4} in {v0}]",
        "",
        "",
    ]


def _algo_checksum(side: dict) -> list[str]:
    """Pair 2 — rolling 32-bit checksum."""
    v0, v1 = side["v"]
    arg = side["arg"]
    return [
        f"def {side['fn']}({arg}):",
        *_docblock(side["doc"]),
        f"    {v0} = 0",
        f"    for {v1} in {arg}:",
        f"        {v0} = ((({v0} << 5) & 0xFFFFFFFF) | ({v0} >> 27)) & 0xFFFFFFFF",
        f"        {v0} = ({v0} ^ (int({v1}) & 0xFF)) & 0xFFFFFFFF",
        f"        {v0} = ({v0} + 0x9E3779B9) & 0xFFFFFFFF",
        f"    return {v0}",
        "",
        "",
    ]


def _algo_partition(side: dict) -> list[str]:
    """Pair 3 — even partitioning."""
    v0, v1, v2, v3, v4, v5 = side["v"]
    arg, extra = side["arg"], side["extra"]
    return [
        f"def {side['fn']}({arg}, {extra}=3):",
        *_docblock(side["doc"]),
        f"    if {extra} < 1:",
        f"        raise ValueError({extra!r})",
        f"    {v0} = len({arg}) // {extra}",
        f"    {v1} = len({arg}) % {extra}",
        f"    {v2} = []",
        f"    {v3} = 0",
        f"    for {v4} in range({extra}):",
        f"        {v5} = {v0} + (1 if {v4} < {v1} else 0)",
        f"        {v2}.append(list({arg}[{v3}:{v3} + {v5}]))",
        f"        {v3} = {v3} + {v5}",
        f"    return {v2}",
        "",
        "",
    ]


#: One renderer per pair, in PAIRS order.
RENDERERS = [_algo_coalesce, _algo_decay, _algo_checksum, _algo_partition]


def _data_table(module: str, ordinal: int, rows: int) -> list[str]:
    """A module-level data table — bulk that is not a public function."""
    out = [
        f"#: Reference rows {ordinal:02d} for the {module} pipeline; the loader below",
        "#: reads them by tag, so the table is data rather than behaviour.",
        f"_TABLE_{ordinal:02d} = (",
    ]
    for row in range(rows):
        tag = f"{module}.t{ordinal:02d}.r{row:03d}"
        weight = (ordinal * 37 + row * 11) % 97
        scale = ((ordinal * 5 + row * 3) % 40) / 8.0
        out.append(f'    ("{tag}", {weight}, {scale}, "kind_{row % 7}"),')
    out.extend([")", "", ""])
    return out


def _step_function(module: str, i: int) -> list[str]:
    """A public helper with a long docstring and a long body.

    Length comes from the body, never from emitting more functions: the brief
    requires 8-12 public functions per module.
    """
    return [
        f"def {module}_step_{i:02d}(payload, *, strict=False, table=None):",
        f'    """Normalise payload variant {i} for the {module} pipeline.',
        "",
        "    The canonical form drops unknown keys, lower-cases and strips every",
        "    string value, rounds every numeric value to a fixed precision for this",
        "    variant, and guarantees the 'kind' discriminator is present so that",
        "    downstream stages never have to branch on its absence when they",
        "    dispatch on the variant tag.",
        "",
        "    The reference table supplies the per-tag weights this variant applies",
        "    when it folds the payload into its summary form. Callers that already",
        "    hold a filtered table may pass it in; otherwise the module-level table",
        "    for this variant is used, which is the common case.",
        "",
        "    Args:",
        "        payload: the mapping to normalise; keys outside the known set are",
        "            dropped unless strict is set, in which case they raise KeyError.",
        "        strict: when true, an unknown key raises instead of being dropped,",
        "            which callers use when the payload came from a trusted",
        "            producer and an unexpected key indicates an upstream defect.",
        "        table: optional replacement for the module-level reference rows;",
        "            each row is a (tag, weight, scale, kind) tuple.",
        "",
        "    Returns:",
        "        A new mapping with the variant's keys canonicalised plus the",
        "        derived 'weight' and 'scale' entries; the input is never mutated,",
        "        so callers may safely reuse the argument afterwards.",
        "",
        "    Raises:",
        "        KeyError: if strict is set and the payload carries an unknown key.",
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
        "        elif isinstance(value, bool):",
        "            result[key] = value",
        "        elif isinstance(value, (int, float)):",
        f"            result[key] = round(float(value), {i % 5 + 1})",
        "        else:",
        "            result[key] = value",
        f"    rows = table if table is not None else _TABLE_{i % 4:02d}",
        "    weight = 0",
        "    scale = 0.0",
        "    for tag, row_weight, row_scale, row_kind in rows:",
        f"        if not tag.endswith('{i % 7}'):",
        "            continue",
        "        weight += row_weight",
        "        scale += row_scale",
        f"        if row_kind == 'kind_{i % 7}':",
        "            weight += 1",
        "    result['weight'] = weight",
        "    result['scale'] = round(scale, 4)",
        f"    result.setdefault('kind', '{module}.v{i}')",
        "    return result",
        "",
        "",
    ]


def _bridge_function(module: str, ordinal: int, other: str) -> list[str]:
    """A public bridge whose body carries the outgoing call edge to ``other``.

    One bridge is emitted per imported neighbour, so both documented call
    edges are always present.
    """
    return [
        f"def {module}_bridge_{ordinal:02d}(payload):",
        f'    """Hand payload to {other} and re-wrap the result.',
        "",
        f"    This is the only place {module} reaches into {other}: the call graph",
        "    edge is visible from the import line above plus this call site.",
        '    """',
        f"    staged = {module}_step_{ordinal:02d}(payload)",
        f"    return {other}.{other}_step_00(staged)",
        "",
        "",
    ]


#: Public functions per module: eight steps plus one bridge per neighbour,
#: plus the shared algorithm on the eight duplicate-carrying modules — 10 or
#: 11, inside the brief's 8-12 band.
STEP_COUNT = 8

#: Target shape per module (the brief: ~1,500 lines / ~60,000 chars).
TARGET_LINES = 1480
TABLE_ROWS = 60


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

    # Blocks are emitted in a fixed order; the shared algorithm is spliced in
    # at a per-module OFFSET, never at a fixed one, so a uniform slice such as
    # `sed -n '1,36p' src/mod_*.py` (or any single slice at a known offset)
    # cannot surface every duplicate body at once. `depth` is derived from the
    # module name, so it stays deterministic while differing across modules.
    blocks: list[list[str]] = []
    for i in range(STEP_COUNT):
        blocks.append(_data_table(module, i, TABLE_ROWS))
        blocks.append(_step_function(module, i))
        # Bridge ordinal — NOT the step index — selects the neighbour, so the
        # two bridges genuinely target the two different imports.
        if calls and i % 4 == 3:
            ordinal = i // 4
            blocks.append(_bridge_function(module, ordinal, calls[ordinal % len(calls)]))

    if algo is not None:
        renderer, side = algo
        depth = sum(ord(c) for c in module) % (len(blocks) + 1)
        blocks.insert(depth, renderer(side))

    for block in blocks:
        lines.extend(block)

    # Pad with further data-table rows (never more functions) until the module
    # reaches the brief's ~1,500-line shape.
    pad = STEP_COUNT
    while len(lines) < TARGET_LINES:
        lines.extend(_data_table(module, pad, TABLE_ROWS))
        pad += 1
    return "\n".join(lines) + "\n"


def main(target: str) -> int:
    root = Path(target)
    src = root / "src"
    src.mkdir(parents=True, exist_ok=True)
    (src / "__init__.py").write_text("", encoding="utf-8")

    algo_for: dict[str, tuple] = {}
    for pair_index, (left, right) in enumerate(PAIRS):
        left_side, right_side = ALGORITHMS[pair_index]
        renderer = RENDERERS[pair_index]
        algo_for[left] = (renderer, left_side)
        algo_for[right] = (renderer, right_side)

    for index, module in enumerate(MODULES):
        # Each module calls two neighbours, wrapping around — the call graph is
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
