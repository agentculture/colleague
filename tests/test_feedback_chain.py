"""Chain-aware feedback grading: grade_chain walks continued_from lineage."""

from __future__ import annotations

from pathlib import Path

from colleague import feedback
from colleague.artifact import write
from colleague.contract import OK, TaskResult, WorkStats


def _record_drive(
    repo: Path,
    task_id: str,
    request: str,
    started_at: str = "",
    continued_from: str | None = None,
) -> None:
    """Write a minimal drive artifact under repo/.colleague."""
    stats = WorkStats(request=request, started_at=started_at)
    result = TaskResult(task_id=task_id, status=OK, summary=f"did {request}", stats=stats)
    if continued_from is not None:
        result.continued_from = continued_from
    write(result, repo / ".colleague")


# ---------------------------------------------------------------------------
# 3-episode chain: tail -> middle -> head
# ---------------------------------------------------------------------------


def test_grade_chain_three_episodes(tmp_path: Path) -> None:
    """grade_chain writes feedback for every episode in a 3-link chain."""
    _record_drive(tmp_path, "head", "initial task", started_at="2026-01-01T00:00:00+00:00")
    _record_drive(
        tmp_path,
        "middle",
        "continued work",
        started_at="2026-01-02T00:00:00+00:00",
        continued_from="head",
    )
    _record_drive(
        tmp_path,
        "tail",
        "final polish",
        started_at="2026-01-03T00:00:00+00:00",
        continued_from="middle",
    )

    records = feedback.grade_chain(
        tmp_path,
        "tail",
        rating=4,
        notes="solid chain",
        by="reviewer",
    )

    assert len(records) == 3
    ids = [r.task_id for r in records]
    assert ids == ["tail", "middle", "head"]

    for rec in records:
        assert rec.rating == 4
        assert rec.notes == "solid chain"
        assert rec.by == "reviewer"
        assert rec.chain is True

    # Verify each record was persisted and round-trips
    for rec in records:
        loaded = feedback.read_feedback(tmp_path, rec.task_id)
        assert loaded is not None
        assert loaded.task_id == rec.task_id
        assert loaded.rating == 4


# ---------------------------------------------------------------------------
# Lineage cycle: two artifacts pointing to each other
# ---------------------------------------------------------------------------


def test_grade_chain_cycle_does_not_loop(tmp_path: Path) -> None:
    """grade_chain detects a cycle and terminates without infinite recursion."""
    _record_drive(
        tmp_path,
        "alpha",
        "task alpha",
        started_at="2026-01-01T00:00:00+00:00",
        continued_from="beta",
    )
    _record_drive(
        tmp_path,
        "beta",
        "task beta",
        started_at="2026-01-02T00:00:00+00:00",
        continued_from="alpha",
    )

    records = feedback.grade_chain(tmp_path, "alpha", rating=3)

    # Should have graded alpha and beta, then stopped on the cycle.
    assert len(records) == 2
    ids = [r.task_id for r in records]
    assert "alpha" in ids
    assert "beta" in ids
    for rec in records:
        assert rec.chain is True


# ---------------------------------------------------------------------------
# Missing artifact: continued_from points to a non-existent task_id
# ---------------------------------------------------------------------------


def test_grade_chain_missing_artifact_stops_cleanly(tmp_path: Path) -> None:
    """grade_chain stops when continued_from references a missing artifact."""
    _record_drive(tmp_path, "head", "real task", started_at="2026-01-01T00:00:00+00:00")
    _record_drive(
        tmp_path,
        "tail",
        "orphan continuation",
        started_at="2026-01-02T00:00:00+00:00",
        continued_from="ghost",  # ghost does not exist
    )

    records = feedback.grade_chain(tmp_path, "tail", rating=5)

    # tail is graded; ghost is missing so chain stops.
    assert len(records) == 1
    assert records[0].task_id == "tail"
    assert records[0].chain is True


# ---------------------------------------------------------------------------
# Single episode (no continued_from)
# ---------------------------------------------------------------------------


def test_grade_chain_single_episode(tmp_path: Path) -> None:
    """grade_chain on a standalone task (no continued_from) returns one record."""
    _record_drive(tmp_path, "solo", "standalone", started_at="2026-01-01T00:00:00+00:00")

    records = feedback.grade_chain(tmp_path, "solo", rating=2, notes="ok")

    assert len(records) == 1
    assert records[0].task_id == "solo"
    assert records[0].chain is True
    assert records[0].notes == "ok"
