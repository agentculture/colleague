"""Strive module tests — bounded-attempt hypothesis-driven iteration (plan t13).

Covers: c6, h6, c8, h8

Test-first: these tests define the contract for ``colleague/strive.py`` — the
hypothesis-ledger module that drives bounded attempts toward a goal, recording
schema-enforced records and detecting novelty stalls.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from colleague import chain
from colleague.strive import (
    _LEADER_KEYS,
    DEFAULT_NOVELTY_STALL_K,
    HypothesisLedger,
    StriveAttempt,
    _slug,
    drive_strive,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ledger(tmp_path: Path) -> HypothesisLedger:
    return HypothesisLedger(str(tmp_path / "strive"))


def _make_record(
    *,
    goal: str = "make it faster",
    attempt: int = 1,
    score: float = 0.0,
    hypothesis: str = "use caching",
    test: str = "bench.sh",
    result: str = "refuted",
    cause: str = "cache miss rate too high",
    lesson: str = "data too large for L1",
    next_delta: str = "try L2 cache",
) -> dict:
    return {
        "goal": goal,
        "attempt": attempt,
        "score": score,
        "hypothesis": hypothesis,
        "test": test,
        "result": result,
        "cause": cause,
        "lesson": lesson,
        "next_delta": next_delta,
    }


# ---------------------------------------------------------------------------
# _slug
# ---------------------------------------------------------------------------


def test_slug_basic():
    assert _slug("make it faster") == "make-it-faster"


def test_slug_with_numbers():
    assert _slug("fix bug 42") == "fix-bug-42"


def test_slug_special_chars():
    assert _slug("handle 'quotes' & stuff!") == "handle-quotes-stuff"


def test_slug_empty():
    assert _slug("") == ""


# ---------------------------------------------------------------------------
# HypothesisLedger — schema enforcement
# ---------------------------------------------------------------------------


def test_ledger_record_valid():
    ledger = _make_ledger(Path("/dev/shm"))
    rec = _make_record()
    ledger.record(rec)
    assert ledger.entries == [rec]


def test_ledger_refuses_missing_key():
    ledger = _make_ledger(Path("/dev/shm"))
    bad = dict(_make_record())
    del bad["hypothesis"]
    with pytest.raises(ValueError, match="missing"):
        ledger.record(bad)


def test_ledger_refuses_extra_key():
    ledger = _make_ledger(Path("/dev/shm"))
    bad = dict(_make_record())
    bad["extra_key"] = "nope"
    with pytest.raises(ValueError, match="unexpected"):
        ledger.record(bad)


def test_ledger_result_must_be_supported_or_refuted():
    ledger = _make_ledger(Path("/dev/shm"))
    bad = dict(_make_record())
    bad["result"] = "inconclusive"
    with pytest.raises(ValueError, match="result"):
        ledger.record(bad)


def test_ledger_persists_to_json(tmp_path: Path):
    goal = "make it faster"
    ledger = _make_ledger(tmp_path)
    ledger.record(_make_record())
    slug = _slug(goal)
    path = tmp_path / "strive" / f"{slug}.json"
    assert path.exists()
    data = json.loads(path.read_text())
    assert data[0]["goal"] == goal


def test_ledger_loads_from_json(tmp_path: Path):
    goal = "make it faster"
    ledger = _make_ledger(tmp_path)
    ledger.record(_make_record(attempt=1, score=0.5))
    ledger.record(_make_record(attempt=2, score=0.7))

    # Reload from disk
    ledger2 = _make_ledger(tmp_path)
    ledger2.load(goal)
    assert len(ledger2.entries) == 2
    assert ledger2.entries[0]["attempt"] == 1
    assert ledger2.entries[1]["attempt"] == 2


def test_ledger_load_nonexistent_goal():
    ledger = _make_ledger(Path("/dev/shm"))
    ledger.load("nonexistent-goal")
    assert ledger.entries == []


# ---------------------------------------------------------------------------
# HypothesisLedger — novelty stall detection
# ---------------------------------------------------------------------------


def test_ledger_detects_novelty_stall(tmp_path: Path):
    ledger = _make_ledger(tmp_path)
    # Three consecutive refuted attempts with the same normalized hypothesis
    for i in range(1, 4):
        ledger.record(_make_record(attempt=i, hypothesis="use caching", result="refuted"))
    stalls = ledger.novelty_stalls()
    assert len(stalls) == 1
    stall = stalls[0]
    assert stall["start_attempt"] == 1
    assert stall["end_attempt"] == 3
    assert stall["repeated_hypothesis"] == "use caching"


def test_ledger_no_stall_when_supported(tmp_path: Path):
    ledger = _make_ledger(tmp_path)
    ledger.record(_make_record(attempt=1, hypothesis="use caching", result="refuted"))
    ledger.record(_make_record(attempt=2, hypothesis="use caching", result="supported"))
    ledger.record(_make_record(attempt=3, hypothesis="use caching", result="refuted"))
    stalls = ledger.novelty_stalls()
    assert len(stalls) == 0


def test_ledger_no_stall_below_k(tmp_path: Path):
    ledger = _make_ledger(tmp_path)
    for i in range(1, 3):
        ledger.record(_make_record(attempt=i, hypothesis="use caching", result="refuted"))
    stalls = ledger.novelty_stalls()
    assert len(stalls) == 0


def test_ledger_normalized_hypothesis_match(tmp_path: Path):
    """Normalized-exact-match: whitespace and case differences should match."""
    ledger = _make_ledger(tmp_path)
    ledger.record(_make_record(attempt=1, hypothesis="Use Caching", result="refuted"))
    ledger.record(_make_record(attempt=2, hypothesis="use  caching", result="refuted"))
    ledger.record(_make_record(attempt=3, hypothesis="USE CACHING", result="refuted"))
    stalls = ledger.novelty_stalls()
    assert len(stalls) == 1


def test_ledger_different_hypotheses_no_stall(tmp_path: Path):
    ledger = _make_ledger(tmp_path)
    ledger.record(_make_record(attempt=1, hypothesis="use caching", result="refuted"))
    ledger.record(_make_record(attempt=2, hypothesis="use pooling", result="refuted"))
    ledger.record(_make_record(attempt=3, hypothesis="use caching", result="refuted"))
    stalls = ledger.novelty_stalls()
    assert len(stalls) == 0


# ---------------------------------------------------------------------------
# StriveAttempt dataclass
# ---------------------------------------------------------------------------


def test_attempt_fields():
    a = StriveAttempt(
        goal="make it faster",
        attempt=1,
        delta="add caching layer",
        hypothesis="caching reduces latency",
    )
    assert a.goal == "make it faster"
    assert a.attempt == 1
    assert a.delta == "add caching layer"
    assert a.hypothesis == "caching reduces latency"


def test_attempt_no_delta():
    a = StriveAttempt(goal="make it faster", attempt=1)
    assert a.delta == ""
    assert a.hypothesis == ""


# ---------------------------------------------------------------------------
# drive_strive — integration
# ---------------------------------------------------------------------------


def _measure_cmd(path: Path) -> str:
    """Return a shell command that writes a score file and exits 0."""
    return f"echo 42 > {path}"


@dataclass
class FakeDispatch:
    """A fake dispatch that records calls and optionally sets a score file."""

    calls: list = None
    score_path: Path = None

    def __post_init__(self):
        if self.calls is None:
            self.calls = []

    def __call__(self, goal: str, attempt: int, delta: str, hypothesis: str):
        self.calls.append(
            {
                "goal": goal,
                "attempt": attempt,
                "delta": delta,
                "hypothesis": hypothesis,
            }
        )
        if self.score_path is not None:
            self.score_path.write_text("42")


def test_drive_strive_runs_attempts(tmp_path: Path):
    goal = "make it faster"
    score_file = tmp_path / "score.txt"
    dispatch = FakeDispatch()

    result = drive_strive(
        goal=goal,
        attempts=3,
        measure_cmd=f"echo 42 > {score_file}",
        dispatch=dispatch,
        ledger_dir=str(tmp_path / "strive"),
    )

    assert len(dispatch.calls) == 3
    assert dispatch.calls[0]["attempt"] == 1
    assert dispatch.calls[1]["attempt"] == 2
    assert dispatch.calls[2]["attempt"] == 3
    assert result["goal"] == goal
    assert result["attempts_run"] == 3


def test_drive_strive_records_delta_before_dispatch(tmp_path: Path):
    """The delta declaration is recorded BEFORE dispatch is called."""
    goal = "make it faster"
    score_file = tmp_path / "score.txt"

    class RecordingDispatch:
        def __init__(self):
            self.seen_ledger = None

        def __call__(self, goal, attempt, delta, hypothesis):
            # At dispatch time, check the ledger already has the delta recorded
            slug = _slug(goal)
            ledger_path = tmp_path / "strive" / f"{slug}.json"
            if ledger_path.exists():
                data = json.loads(ledger_path.read_text())
                self.seen_ledger = data

    dispatch = RecordingDispatch()
    drive_strive(
        goal=goal,
        attempts=1,
        measure_cmd=f"echo 42 > {score_file}",
        dispatch=dispatch,
        ledger_dir=str(tmp_path / "strive"),
    )
    # The ledger should have been written before dispatch
    assert dispatch.seen_ledger is not None


def test_drive_strive_persists_ledger(tmp_path: Path):
    goal = "make it faster"
    score_file = tmp_path / "score.txt"
    dispatch = FakeDispatch()

    drive_strive(
        goal=goal,
        attempts=2,
        measure_cmd=f"echo 42 > {score_file}",
        dispatch=dispatch,
        ledger_dir=str(tmp_path / "strive"),
    )

    slug = _slug(goal)
    path = tmp_path / "strive" / f"{slug}.json"
    assert path.exists()
    data = json.loads(path.read_text())
    assert len(data) == 2


def test_drive_strive_respects_attempt_limit(tmp_path: Path):
    goal = "make it faster"
    score_file = tmp_path / "score.txt"
    dispatch = FakeDispatch()

    result = drive_strive(
        goal=goal,
        attempts=1,
        measure_cmd=f"echo 42 > {score_file}",
        dispatch=dispatch,
        ledger_dir=str(tmp_path / "strive"),
    )

    assert len(dispatch.calls) == 1
    assert result["attempts_run"] == 1


def test_drive_strive_measure_failure(tmp_path: Path):
    """A failing measure command still records the attempt."""
    goal = "make it faster"
    dispatch = FakeDispatch()

    result = drive_strive(
        goal=goal,
        attempts=1,
        measure_cmd="exit 1",
        dispatch=dispatch,
        ledger_dir=str(tmp_path / "strive"),
    )

    assert len(dispatch.calls) == 1
    assert result["attempts_run"] == 1


def test_drive_strive_novelty_stall(tmp_path: Path):
    """When K consecutive attempts reuse a refuted hypothesis, record a stall."""
    goal = "make it faster"
    score_file = tmp_path / "score.txt"

    class StallDispatch:
        def __init__(self):
            self.calls = []

        def __call__(self, goal, attempt, delta, hypothesis):
            self.calls.append(
                {
                    "goal": goal,
                    "attempt": attempt,
                    "delta": delta,
                    "hypothesis": hypothesis,
                }
            )
            score_file.write_text("0")

    dispatch = StallDispatch()
    result = drive_strive(
        goal=goal,
        attempts=5,
        measure_cmd=f"echo 0 > {score_file}",
        dispatch=dispatch,
        ledger_dir=str(tmp_path / "strive"),
        novelty_stall_k=DEFAULT_NOVELTY_STALL_K,
    )

    # Should have run all attempts
    assert len(dispatch.calls) == 5
    # Should detect the stall
    assert result.get("novelty_stall") is not None


# ---------------------------------------------------------------------------
# _LEADER_KEYS constant
# ---------------------------------------------------------------------------


def test_leader_keys():
    expected = frozenset(
        {
            "goal",
            "attempt",
            "score",
            "hypothesis",
            "test",
            "result",
            "cause",
            "lesson",
            "next_delta",
        }
    )
    assert _LEADER_KEYS == expected


# ---------------------------------------------------------------------------
# Pin chain.CONTINUABLE_REASONS unchanged (strive's retry policy is its own)
# ---------------------------------------------------------------------------


def test_chain_continuable_reasons_pinned():
    """chain.CONTINUABLE_REASONS must remain {budget-exhausted}; strive's retry
    policy lives in its own module, not in chain.py."""
    assert chain.CONTINUABLE_REASONS == frozenset({"budget-exhausted"})
    assert isinstance(chain.CONTINUABLE_REASONS, frozenset)
