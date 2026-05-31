"""``convertible feedback`` CLI verb (t6) + drive→last-pointer integration (t7)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from convertible.cli import main


def test_record_then_show_json_round_trip(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(
        [
            "feedback",
            "record",
            "d1",
            "--rating",
            "4",
            "--notes",
            "solid",
            "--by",
            "ori",
            "--repo",
            str(tmp_path),
            "--json",
        ]
    )
    assert rc == 0
    rec = json.loads(capsys.readouterr().out)
    assert rec["task_id"] == "d1" and rec["rating"] == 4 and rec["by"] == "ori"

    rc = main(["feedback", "show", "d1", "--repo", str(tmp_path), "--json"])
    assert rc == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["rating"] == 4 and shown["notes"] == "solid"


def test_record_text_mode(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["feedback", "record", "d2", "--rating", "5", "--repo", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "rating: 5/5" in out


def test_show_ungraded_is_clean_no_op(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["feedback", "show", "never", "--repo", str(tmp_path)])
    assert rc == 0  # not an error
    assert "no feedback yet" in capsys.readouterr().out


def test_bad_rating_is_user_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["feedback", "record", "d3", "--rating", "9", "--repo", str(tmp_path)])
    assert rc != 0
    assert "error:" in capsys.readouterr().err


def test_overview_and_explain(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["feedback", "overview"]) == 0
    assert "feedback" in capsys.readouterr().out.lower()
    assert main(["explain", "feedback"]) == 0
    assert "feedback" in capsys.readouterr().out.lower()


def test_last_with_no_drive_is_user_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["feedback", "record", "last", "--rating", "3", "--repo", str(tmp_path)])
    assert rc != 0
    assert "error:" in capsys.readouterr().err


def test_drive_then_feedback_last(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A mock drive records itself as 'last'; `feedback record last` grades it (t7)."""
    rc = main(
        ["drive", "do work", "--repo", str(tmp_path), "--engine", "mock", "--no-pr", "--json"]
    )
    assert rc == 0
    result = json.loads(capsys.readouterr().out)
    task_id = result["task_id"]
    # The drive's artifact carries the always-on stats block.
    assert "stats" in result and result["stats"]["request"] == "do work"

    # `last` resolves to that drive — feedback lands on the same task_id.
    rc = main(["feedback", "record", "last", "--rating", "5", "--repo", str(tmp_path), "--json"])
    assert rc == 0
    rec = json.loads(capsys.readouterr().out)
    assert rec["task_id"] == task_id and rec["rating"] == 5

    # And it reads back.
    rc = main(["feedback", "show", task_id, "--repo", str(tmp_path), "--json"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["rating"] == 5
