#!/usr/bin/env python3
"""Compare N measurement arms' colleague artifacts against a baseline arm.

Plan task t10 (spec ``docs/specs/2026-08-27-adopt-from-qwen-code.md``, covers
c22/h16/c26/h19). Reads real colleague run artifacts (``.colleague/<id>.*.json``
written by :mod:`colleague.artifact`) for one or more named arms, computes the
per-arm mean wall-clock (``stats.duration_seconds``) and mean model turns
(``stats.model_turns``), and the ratio of every non-baseline arm against the
FIRST named arm (the baseline). Never estimates or reads prose — every number
comes straight from ``stats`` on the artifact JSON, matching the token-honesty
discipline the rest of colleague holds (decision c11/c17).

The c28 bar (decision c28, per the arc spec): a non-baseline arm passes when its
wall-clock ratio is <= 0.7 and its model-turns ratio is <= 0.8. A ratio above
either bar for ANY non-baseline arm is a miss, and the process exits 1 so a CI
or delivery script can catch a silent regression rather than reporting it as
prose.

Usage::

    uv run python scripts/compare_arms.py --repo . \\
        --arm main=abc123,def456,111222 \\
        --arm branch-unarmed=333444,555666,777888 \\
        --arm branch-armed=999000,aaa111,bbb222 \\
        [--bar-wall 0.7] [--bar-turns 0.8]

The first ``--arm`` given is always the baseline; every later ``--arm`` is
reported as a ratio against it. Exits 2 (usage/lookup error, never a silent
skip) when an artifact id cannot be resolved under ``--repo``.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

# Reuse the repo's own artifact-id resolution rather than re-deriving the
# ``.colleague/<id>.<slug>.json`` naming scheme here.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from colleague.artifact import find_artifact  # noqa: E402

DEFAULT_BAR_WALL = 0.7
DEFAULT_BAR_TURNS = 0.8


class ArtifactLookupError(RuntimeError):
    """Raised when an artifact id cannot be resolved under ``--repo``."""


@dataclass
class ArtifactStats:
    """The two numbers this script ever reads from an artifact."""

    task_id: str
    duration_seconds: float
    model_turns: int


@dataclass
class ArmResult:
    """One named arm's per-artifact stats + arm-level means."""

    name: str
    artifacts: list[ArtifactStats]

    @property
    def n(self) -> int:
        return len(self.artifacts)

    @property
    def mean_wall(self) -> float:
        return sum(a.duration_seconds for a in self.artifacts) / self.n

    @property
    def mean_turns(self) -> float:
        return sum(a.model_turns for a in self.artifacts) / self.n


def load_artifact_stats(repo: str | Path, task_id: str) -> ArtifactStats:
    """Read ``stats.duration_seconds``/``stats.model_turns`` for ``task_id``.

    Resolves the artifact path via :func:`colleague.artifact.find_artifact`
    (the same lookup ``feedback``/``continuation`` use), so both the bare and
    slugged naming schemes, and the legacy ``.convertible/`` fallback, work
    here too. Raises :class:`ArtifactLookupError` — never returns partial or
    estimated data — when the artifact is missing or malformed.
    """
    path = find_artifact(repo, task_id)
    if path is None:
        raise ArtifactLookupError(
            f"no artifact found for id {task_id!r} under {Path(repo) / '.colleague'}"
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArtifactLookupError(f"could not read artifact {path}: {exc}") from exc

    stats = data.get("stats") or {}
    if "duration_seconds" not in stats or "model_turns" not in stats:
        raise ArtifactLookupError(f"artifact {path} is missing stats.duration_seconds/model_turns")
    return ArtifactStats(
        task_id=task_id,
        duration_seconds=float(stats["duration_seconds"]),
        model_turns=int(stats["model_turns"]),
    )


def load_arm(repo: str | Path, name: str, task_ids: Sequence[str]) -> ArmResult:
    """Load every artifact for one arm, in the order the ids were given."""
    artifacts = [load_artifact_stats(repo, task_id) for task_id in task_ids]
    return ArmResult(name=name, artifacts=artifacts)


def parse_arm_spec(spec: str) -> tuple[str, list[str]]:
    """Parse one ``--arm NAME=id1,id2,...`` argument.

    Raises :class:`argparse.ArgumentTypeError` on a malformed spec (no ``=``,
    an empty name, or an empty id list) so a usage mistake fails loudly at
    parse time rather than surfacing as a confusing lookup error later.
    """
    if "=" not in spec:
        raise argparse.ArgumentTypeError(
            f"--arm must be NAME=id1,id2,... (got {spec!r} — missing '=')"
        )
    name, _, ids_part = spec.partition("=")
    name = name.strip()
    task_ids = [t.strip() for t in ids_part.split(",") if t.strip()]
    if not name:
        raise argparse.ArgumentTypeError(f"--arm has an empty NAME (got {spec!r})")
    if not task_ids:
        raise argparse.ArgumentTypeError(f"--arm {name!r} has no artifact ids (got {spec!r})")
    return name, task_ids


def compute_ratios(baseline: ArmResult, arm: ArmResult) -> tuple[float, float]:
    """(wall_ratio, turns_ratio) of ``arm`` against ``baseline``."""
    wall_ratio = arm.mean_wall / baseline.mean_wall
    turns_ratio = arm.mean_turns / baseline.mean_turns
    return wall_ratio, turns_ratio


def format_table(arms: Sequence[ArmResult], bar_wall: float, bar_turns: float) -> tuple[str, bool]:
    """Render the comparison table; return (text, any_miss)."""
    baseline = arms[0]
    lines = []
    header = (
        f"{'arm':<24}{'n':>4}{'mean_wall_s':>14}{'mean_turns':>12}"
        f"{'wall_ratio':>12}{'turns_ratio':>13}  bar"
    )
    lines.append(header)
    lines.append("-" * len(header))
    lines.append(
        f"{baseline.name:<24}{baseline.n:>4}{baseline.mean_wall:>14.2f}"
        f"{baseline.mean_turns:>12.2f}{'—':>12}{'—':>13}  baseline"
    )

    any_miss = False
    for arm in arms[1:]:
        wall_ratio, turns_ratio = compute_ratios(baseline, arm)
        miss = wall_ratio > bar_wall or turns_ratio > bar_turns
        any_miss = any_miss or miss
        verdict = "MISS" if miss else "pass"
        lines.append(
            f"{arm.name:<24}{arm.n:>4}{arm.mean_wall:>14.2f}"
            f"{arm.mean_turns:>12.2f}{wall_ratio:>12.3f}{turns_ratio:>13.3f}  {verdict}"
        )
    lines.append("")
    lines.append(f"bar: wall_ratio <= {bar_wall}, turns_ratio <= {bar_turns} (decision c28)")
    return "\n".join(lines), any_miss


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compare wall-clock and model-turns ratios of N colleague artifact "
            "arms against a baseline arm (the first --arm given)."
        )
    )
    parser.add_argument(
        "--repo",
        default=".",
        help="Repo root whose .colleague/ directory holds the artifacts (default: cwd).",
    )
    parser.add_argument(
        "--arm",
        dest="arms",
        action="append",
        required=True,
        type=parse_arm_spec,
        metavar="NAME=id1,id2,...",
        help="One named arm's artifact ids, comma-separated. Repeatable; the "
        "first --arm is the baseline every later arm is compared against.",
    )
    parser.add_argument(
        "--bar-wall",
        dest="bar_wall",
        type=float,
        default=DEFAULT_BAR_WALL,
        help=f"Max wall-clock ratio for a non-baseline arm (default {DEFAULT_BAR_WALL}).",
    )
    parser.add_argument(
        "--bar-turns",
        dest="bar_turns",
        type=float,
        default=DEFAULT_BAR_TURNS,
        help=f"Max model-turns ratio for a non-baseline arm (default {DEFAULT_BAR_TURNS}).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if len(args.arms) < 2:
        parser.error("at least two --arm entries are required (a baseline plus one comparison arm)")

    try:
        arms = [load_arm(args.repo, name, task_ids) for name, task_ids in args.arms]
    except ArtifactLookupError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    table, any_miss = format_table(arms, args.bar_wall, args.bar_turns)
    print(table)

    return 1 if any_miss else 0


if __name__ == "__main__":
    raise SystemExit(main())
