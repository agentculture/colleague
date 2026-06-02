"""ROI end-to-end (t10): the four signals are readable from one artifact + feedback.

The headline claim — "you can calculate the ROI of outsourcing" — holds iff a
single drive's artifact (cost: time + tokens + bytes written) plus its feedback
record (quality: a 1-5 rating) together carry everything a retro needs, with no
external data (h9/h13). This proves that without a network, via the mock engine.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from colleague.cli import main
from colleague.contract import DriveStats
from colleague.feedback import read_feedback


def test_roi_inputs_readable_from_one_artifact_plus_feedback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(
        [
            "drive",
            "improve the docs",
            "--repo",
            str(tmp_path),
            "--engine",
            "mock",
            "--no-pr",
            "--json",
        ]
    )
    assert rc == 0
    result = json.loads(capsys.readouterr().out)
    task_id = result["task_id"]

    stats, usage = result["stats"], result["usage"]
    # COST signals — all present in the single artifact:
    assert stats["request"] == "improve the docs"
    assert stats["duration_seconds"] >= 0.0  # time
    assert "prompt_tokens" in usage and "completion_tokens" in usage  # tokens (verbatim)
    assert stats["bytes_written"] > 0  # written
    assert stats["tool_counts"]  # tools used (non-empty)
    assert stats["model_turns"] >= 1

    # QUALITY signal — the feedback record:
    rc = main(["feedback", "record", "last", "--rating", "4", "--repo", str(tmp_path), "--json"])
    assert rc == 0
    capsys.readouterr()
    fb = read_feedback(tmp_path, task_id)
    assert fb is not None and fb.rating == 4

    # => ROI = (time, tokens, bytes_written, rating) all from one artifact + feedback.


def test_stats_block_carries_the_previously_missing_fields() -> None:
    """h12: the pre-feature artifact demonstrably lacked these; they are exactly
    the fields DriveStats now adds (pin the schema so a drop is caught)."""
    assert set(DriveStats().to_dict().keys()) == {
        "request",
        "started_at",
        "duration_seconds",
        "model_turns",
        "step_count",
        "tool_counts",
        "files_changed",
        "bytes_written",
        "reasoning_chars",
        "reasoning_bytes",
        "answer_chars",
        "answer_bytes",
    }
