"""``colleague feedback`` CLI verb (t6) + drive→last-pointer integration (t7)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from colleague.cli import main


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


# ---------------------------------------------------------------------------
# #132: transparency on `last` + the `feedback list` discovery surface
# ---------------------------------------------------------------------------


def test_record_last_echoes_resolved_drive_to_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Grading `last` surfaces which drive (id + request) it landed on, on stderr,
    so a mis-resolve is never silent — while stdout/--json stays the clean record."""
    rc = main(
        [
            "drive",
            "fix the parser",
            "--repo",
            str(tmp_path),
            "--engine",
            "mock",
            "--no-pr",
            "--json",
        ]
    )
    assert rc == 0
    task_id = json.loads(capsys.readouterr().out)["task_id"]

    rc = main(["feedback", "record", "last", "--rating", "4", "--repo", str(tmp_path), "--json"])
    assert rc == 0
    captured = capsys.readouterr()
    # The resolution note is a stderr diagnostic — stdout is the clean JSON record.
    assert json.loads(captured.out)["task_id"] == task_id
    assert "'last' resolved to" in captured.err
    assert task_id in captured.err
    assert "fix the parser" in captured.err


def test_show_explicit_id_does_not_emit_resolution_note(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The note fires only for the ambiguous `last`, not for an explicit task-id."""
    rc = main(
        ["drive", "do a thing", "--repo", str(tmp_path), "--engine", "mock", "--no-pr", "--json"]
    )
    assert rc == 0
    task_id = json.loads(capsys.readouterr().out)["task_id"]

    rc = main(["feedback", "show", task_id, "--repo", str(tmp_path)])
    assert rc == 0
    assert "'last' resolved to" not in capsys.readouterr().err


def test_feedback_list_empty_is_clean(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["feedback", "list", "--repo", str(tmp_path)])
    assert rc == 0
    assert "no drives recorded yet" in capsys.readouterr().out

    rc = main(["feedback", "list", "--repo", str(tmp_path), "--json"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == []


def test_feedback_list_shows_drives_with_grade(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(
        [
            "drive",
            "build the thing",
            "--repo",
            str(tmp_path),
            "--engine",
            "mock",
            "--no-pr",
            "--json",
        ]
    )
    assert rc == 0
    task_id = json.loads(capsys.readouterr().out)["task_id"]
    main(["feedback", "record", task_id, "--rating", "3", "--repo", str(tmp_path)])
    capsys.readouterr()

    # Text table: the drive shows up by its request, with its grade.
    rc = main(["feedback", "list", "--repo", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "REQUEST" in out and "build the thing" in out and "3/5" in out

    # JSON: full request + rating for an agent.
    rc = main(["feedback", "list", "--repo", str(tmp_path), "--json"])
    assert rc == 0
    rows = json.loads(capsys.readouterr().out)
    assert len(rows) == 1
    assert rows[0]["request"] == "build the thing" and rows[0]["rating"] == 3
