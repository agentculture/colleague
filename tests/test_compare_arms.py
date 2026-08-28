"""Tests for scripts/compare_arms.py (plan task t10, covers c22/h16/c26/h19).

Fixture artifacts live under ``tests/fixtures/compare_arms/.colleague/`` — three
named arms with hand-computed means so every ratio in this file is an exact,
checkable number, never an estimate:

* ``main``            — mean duration 100.0s, mean turns 10.0 (the baseline)
* ``branch-unarmed``  — mean duration  70.0s, mean turns  8.0
                         -> wall ratio 0.70 (== bar, PASS), turns ratio 0.80 (== bar, PASS)
* ``branch-armed``    — mean duration  95.0s, mean turns  9.666...
                         -> wall ratio 0.95 (> 0.7, MISS), turns ratio ~0.9667 (> 0.8, MISS)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.compare_arms import (  # noqa: E402
    ArtifactLookupError,
    build_parser,
    compute_ratios,
    load_arm,
    load_artifact_stats,
    main,
    parse_arm_spec,
)

FIXTURE_REPO = Path(__file__).resolve().parent / "fixtures" / "compare_arms"


# --- parse_arm_spec -----------------------------------------------------


def test_parse_arm_spec_splits_name_and_ids():
    name, ids = parse_arm_spec("main=main-1,main-2,main-3")
    assert name == "main"
    assert ids == ["main-1", "main-2", "main-3"]


def test_parse_arm_spec_strips_whitespace():
    name, ids = parse_arm_spec(" branch-unarmed = unarmed-1 , unarmed-2 ")
    assert name == "branch-unarmed"
    assert ids == ["unarmed-1", "unarmed-2"]


@pytest.mark.parametrize(
    "spec",
    [
        "no-equals-sign",
        "=missing-name",
        "name=",
        "name=   ",
    ],
)
def test_parse_arm_spec_rejects_malformed_spec(spec):
    import argparse

    with pytest.raises(argparse.ArgumentTypeError):
        parse_arm_spec(spec)


# --- load_artifact_stats / load_arm --------------------------------------


def test_load_artifact_stats_reads_duration_and_turns():
    stats = load_artifact_stats(FIXTURE_REPO, "main-1")
    assert stats.task_id == "main-1"
    assert stats.duration_seconds == 100.0
    assert stats.model_turns == 10


def test_load_artifact_stats_missing_id_raises():
    with pytest.raises(ArtifactLookupError):
        load_artifact_stats(FIXTURE_REPO, "does-not-exist-999")


def test_load_arm_computes_means():
    arm = load_arm(FIXTURE_REPO, "main", ["main-1", "main-2", "main-3"])
    assert arm.n == 3
    assert arm.mean_wall == pytest.approx(100.0)
    assert arm.mean_turns == pytest.approx(10.0)


def test_load_arm_unarmed_means():
    arm = load_arm(FIXTURE_REPO, "branch-unarmed", ["unarmed-1", "unarmed-2", "unarmed-3"])
    assert arm.mean_wall == pytest.approx(70.0)
    assert arm.mean_turns == pytest.approx(8.0)


def test_load_arm_armed_means():
    arm = load_arm(FIXTURE_REPO, "branch-armed", ["armed-1", "armed-2", "armed-3"])
    assert arm.mean_wall == pytest.approx(95.0)
    assert arm.mean_turns == pytest.approx(29.0 / 3.0)


def _write_artifact(repo: Path, task_id: str, stats: dict) -> None:
    (repo / ".colleague").mkdir(parents=True, exist_ok=True)
    (repo / ".colleague" / f"{task_id}.json").write_text(
        json.dumps({"task_id": task_id, "stats": stats}), encoding="utf-8"
    )


def test_load_artifact_stats_malformed_stats_raise_lookup_error(tmp_path: Path):
    """Non-numeric duration/turns must raise ArtifactLookupError (never a
    TypeError escaping the script's error wrapper)."""
    _write_artifact(tmp_path, "bad-1", {"duration_seconds": "not-a-number", "model_turns": 10})
    with pytest.raises(ArtifactLookupError, match="bad-1"):
        load_artifact_stats(tmp_path, "bad-1")
    _write_artifact(tmp_path, "bad-2", {"duration_seconds": 100.0, "model_turns": "ten"})
    with pytest.raises(ArtifactLookupError, match="bad-2"):
        load_artifact_stats(tmp_path, "bad-2")


def test_load_artifact_stats_non_positive_stats_raise_lookup_error(tmp_path: Path):
    """A zero/negative duration or turns is malformed (it would make a ratio
    divide by zero or invert) — ArtifactLookupError, not a silent 0.0."""
    _write_artifact(tmp_path, "zero-1", {"duration_seconds": 0, "model_turns": 10})
    with pytest.raises(ArtifactLookupError, match="zero-1"):
        load_artifact_stats(tmp_path, "zero-1")
    _write_artifact(tmp_path, "zero-2", {"duration_seconds": 100.0, "model_turns": 0})
    with pytest.raises(ArtifactLookupError, match="zero-2"):
        load_artifact_stats(tmp_path, "zero-2")


def test_main_exits_two_on_malformed_artifact(tmp_path: Path, capsys):
    """End-to-end: a malformed artifact is a lookup error (exit 2, clear
    stderr message), never a traceback."""
    _write_artifact(tmp_path, "bad-1", {"duration_seconds": "oops", "model_turns": 10})
    _write_artifact(tmp_path, "ok-1", {"duration_seconds": 100.0, "model_turns": 10})
    exit_code = main(
        [
            "--repo",
            str(tmp_path),
            "--arm",
            "baseline=ok-1",
            "--arm",
            "other=bad-1",
        ]
    )
    assert exit_code == 2
    err = capsys.readouterr().err
    assert "bad-1" in err


def test_main_exits_two_on_zero_turn_baseline(tmp_path: Path, capsys):
    """A zero-turn baseline would divide by zero in compute_ratios — the
    script must refuse it at load time with exit 2."""
    _write_artifact(tmp_path, "zero-1", {"duration_seconds": 100.0, "model_turns": 0})
    _write_artifact(tmp_path, "ok-1", {"duration_seconds": 100.0, "model_turns": 10})
    exit_code = main(
        [
            "--repo",
            str(tmp_path),
            "--arm",
            "baseline=zero-1",
            "--arm",
            "other=ok-1",
        ]
    )
    assert exit_code == 2
    err = capsys.readouterr().err
    assert "zero-1" in err


# --- compute_ratios -------------------------------------------------------


def test_compute_ratios_unarmed_hits_bar_exactly():
    baseline = load_arm(FIXTURE_REPO, "main", ["main-1", "main-2", "main-3"])
    unarmed = load_arm(FIXTURE_REPO, "branch-unarmed", ["unarmed-1", "unarmed-2", "unarmed-3"])
    wall_ratio, turns_ratio = compute_ratios(baseline, unarmed)
    assert wall_ratio == pytest.approx(0.7)
    assert turns_ratio == pytest.approx(0.8)


def test_compute_ratios_armed_misses_bar():
    baseline = load_arm(FIXTURE_REPO, "main", ["main-1", "main-2", "main-3"])
    armed = load_arm(FIXTURE_REPO, "branch-armed", ["armed-1", "armed-2", "armed-3"])
    wall_ratio, turns_ratio = compute_ratios(baseline, armed)
    assert wall_ratio == pytest.approx(0.95)
    assert turns_ratio > 0.8


# --- main() end-to-end -----------------------------------------------------


def test_main_exits_zero_when_every_arm_meets_the_bar(capsys):
    exit_code = main(
        [
            "--repo",
            str(FIXTURE_REPO),
            "--arm",
            "main=main-1,main-2,main-3",
            "--arm",
            "branch-unarmed=unarmed-1,unarmed-2,unarmed-3",
        ]
    )
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "main" in out
    assert "branch-unarmed" in out
    assert "pass" in out
    assert "MISS" not in out


def test_main_exits_one_when_an_arm_misses_the_bar(capsys):
    exit_code = main(
        [
            "--repo",
            str(FIXTURE_REPO),
            "--arm",
            "main=main-1,main-2,main-3",
            "--arm",
            "branch-armed=armed-1,armed-2,armed-3",
        ]
    )
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "MISS" in out


def test_main_reports_first_arm_missing_and_second_passing_still_misses(capsys):
    """One miss among several arms is enough to fail the whole run (never silent)."""
    exit_code = main(
        [
            "--repo",
            str(FIXTURE_REPO),
            "--arm",
            "main=main-1,main-2,main-3",
            "--arm",
            "branch-unarmed=unarmed-1,unarmed-2,unarmed-3",
            "--arm",
            "branch-armed=armed-1,armed-2,armed-3",
        ]
    )
    out = capsys.readouterr().out
    assert exit_code == 1
    assert out.count("MISS") == 1
    assert out.count("pass") == 1


def test_main_never_estimates_from_prose_only_from_stats_fields(capsys):
    """The printed numbers are exactly the fixture's stats fields, not derived text."""
    main(
        [
            "--repo",
            str(FIXTURE_REPO),
            "--arm",
            "main=main-1,main-2,main-3",
            "--arm",
            "branch-unarmed=unarmed-1,unarmed-2,unarmed-3",
        ]
    )
    out = capsys.readouterr().out
    assert "100.00" in out  # main's mean_wall
    assert "70.00" in out  # branch-unarmed's mean_wall


def test_main_exits_two_on_missing_artifact(capsys):
    exit_code = main(
        [
            "--repo",
            str(FIXTURE_REPO),
            "--arm",
            "main=main-1,main-2,main-3",
            "--arm",
            "branch-unarmed=unarmed-1,does-not-exist-999",
        ]
    )
    assert exit_code == 2
    err = capsys.readouterr().err
    assert "does-not-exist-999" in err


def test_main_requires_at_least_two_arms():
    with pytest.raises(SystemExit) as exc_info:
        main(["--repo", str(FIXTURE_REPO), "--arm", "main=main-1,main-2,main-3"])
    assert exc_info.value.code == 2


def test_custom_bar_flags_change_the_verdict(capsys):
    """A looser --bar-wall/--bar-turns turns a MISS arm into a pass."""
    exit_code = main(
        [
            "--repo",
            str(FIXTURE_REPO),
            "--arm",
            "main=main-1,main-2,main-3",
            "--arm",
            "branch-armed=armed-1,armed-2,armed-3",
            "--bar-wall",
            "0.99",
            "--bar-turns",
            "0.99",
        ]
    )
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "MISS" not in out


def test_build_parser_defaults():
    parser = build_parser()
    args = parser.parse_args(["--arm", "main=main-1", "--arm", "other=other-1"])
    assert args.bar_wall == 0.7
    assert args.bar_turns == 0.8
