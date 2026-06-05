"""The per-drive feedback store (t4): single record, last-pointer, clean no-op."""

from __future__ import annotations

from pathlib import Path

import pytest

from colleague import feedback
from colleague.artifact import write
from colleague.contract import OK, DriveStats, TaskResult
from colleague.feedback import Feedback, FeedbackError


def _record_drive(repo: Path, task_id: str, request: str, started_at: str = "") -> None:
    """Write a minimal drive artifact under repo/.colleague (for list_drives)."""
    stats = DriveStats(request=request, started_at=started_at)
    write(
        TaskResult(task_id=task_id, status=OK, summary=f"did {request}", stats=stats),
        repo / ".colleague",
    )


def test_write_then_read_round_trips(tmp_path: Path) -> None:
    fb = feedback.write_feedback(tmp_path, "drive1", rating=4, notes="solid", by="ori")
    assert isinstance(fb, Feedback)
    assert fb.task_id == "drive1" and fb.rating == 4 and fb.at  # at stamped
    loaded = feedback.read_feedback(tmp_path, "drive1")
    assert loaded == fb


def test_second_write_overwrites_single_record(tmp_path: Path) -> None:
    feedback.write_feedback(tmp_path, "d", rating=2, notes="meh")
    feedback.write_feedback(tmp_path, "d", rating=5, notes="great")
    loaded = feedback.read_feedback(tmp_path, "d")
    assert loaded is not None
    assert loaded.rating == 5 and loaded.notes == "great"


def test_read_absent_is_clean_no_op(tmp_path: Path) -> None:
    """'no feedback yet' is a state (None), not an error."""
    assert feedback.read_feedback(tmp_path, "never-graded") is None


@pytest.mark.parametrize("bad", [0, 6, -1, 100])
def test_rating_out_of_range_rejected(tmp_path: Path, bad: int) -> None:
    with pytest.raises(FeedbackError):
        feedback.write_feedback(tmp_path, "d", rating=bad)


# ---------------------------------------------------------------------------
# #132: list_drives — recover a drive by its request, not a fragile `last`
# ---------------------------------------------------------------------------


def test_list_drives_empty_is_empty_list(tmp_path: Path) -> None:
    assert feedback.list_drives(tmp_path) == []


def test_list_drives_newest_first_with_grade(tmp_path: Path) -> None:
    _record_drive(tmp_path, "older", "implement the parser", started_at="2026-06-05T10:00:00+00:00")
    _record_drive(tmp_path, "newer", "review the auth diff", started_at="2026-06-05T11:00:00+00:00")
    feedback.write_feedback(tmp_path, "older", rating=4)  # graded; newer is ungraded

    rows = feedback.list_drives(tmp_path)
    assert [r.task_id for r in rows] == ["newer", "older"]  # newest-first by started_at
    by_id = {r.task_id: r for r in rows}
    assert by_id["older"].rating == 4 and by_id["older"].request == "implement the parser"
    assert by_id["newer"].rating is None  # ungraded reads back as None, not an error
    assert by_id["newer"].status == OK


def test_list_drives_reads_task_id_from_contents_not_filename(tmp_path: Path) -> None:
    """The slug in the filename is cosmetic — list_drives keys off the JSON task_id."""
    _record_drive(tmp_path, "tid99", "do a slugged thing", started_at="2026-06-05T12:00:00+00:00")
    # The artifact on disk is slugged; list_drives still surfaces the bare id.
    assert (tmp_path / ".colleague" / "tid99.do-a-slugged-thing.json").is_file()
    rows = feedback.list_drives(tmp_path)
    assert len(rows) == 1 and rows[0].task_id == "tid99"


def test_list_drives_skips_corrupt_files(tmp_path: Path) -> None:
    _record_drive(tmp_path, "good", "a good drive", started_at="2026-06-05T09:00:00+00:00")
    (tmp_path / ".colleague" / "broken.json").write_text("{not json", encoding="utf-8")
    rows = feedback.list_drives(tmp_path)
    assert [r.task_id for r in rows] == ["good"]  # the corrupt file is skipped, never raised


def test_list_drives_excludes_feedback_records(tmp_path: Path) -> None:
    _record_drive(tmp_path, "d1", "the one drive", started_at="2026-06-05T08:00:00+00:00")
    feedback.write_feedback(tmp_path, "d1", rating=5)  # writes d1.feedback.json beside it
    rows = feedback.list_drives(tmp_path)
    assert len(rows) == 1 and rows[0].task_id == "d1"  # the .feedback.json is not a drive row


def test_rating_must_be_int_not_bool(tmp_path: Path) -> None:
    # bool is an int subclass — must be rejected, not silently treated as 0/1.
    with pytest.raises(FeedbackError):
        feedback.write_feedback(tmp_path, "d", rating=True)  # type: ignore[arg-type]


def test_last_drive_pointer_round_trips(tmp_path: Path) -> None:
    assert feedback.get_last_drive(tmp_path) is None
    feedback.set_last_drive(tmp_path, "drive-xyz")
    assert feedback.get_last_drive(tmp_path) == "drive-xyz"
    # A later drive overwrites the pointer.
    feedback.set_last_drive(tmp_path, "drive-abc")
    assert feedback.get_last_drive(tmp_path) == "drive-abc"


def test_resolve_task_id_last_and_explicit(tmp_path: Path) -> None:
    feedback.set_last_drive(tmp_path, "the-last-one")
    assert feedback.resolve_task_id(tmp_path, "last") == "the-last-one"
    assert feedback.resolve_task_id(tmp_path, "explicit-id") == "explicit-id"


def test_resolve_last_with_no_pointer_raises(tmp_path: Path) -> None:
    with pytest.raises(FeedbackError):
        feedback.resolve_task_id(tmp_path, "last")


@pytest.mark.parametrize(
    "evil",
    ["../escape", "../../etc/passwd", "/etc/passwd", "a/b", "a\\b", "..", ".", "", "-leading"],
)
def test_path_traversal_ids_are_rejected(tmp_path: Path, evil: str) -> None:
    """A user-supplied ref must not escape the artifact dir (Qodo security finding)."""
    with pytest.raises(FeedbackError):
        feedback.write_feedback(tmp_path, evil, rating=3)
    with pytest.raises(FeedbackError):
        feedback.read_feedback(tmp_path, evil)
    # And nothing was written outside the artifact dir.
    assert not (tmp_path / "escape.feedback.json").exists()
    assert not (tmp_path.parent / "escape.feedback.json").exists()


def test_valid_uuid_hex_id_is_accepted(tmp_path: Path) -> None:
    """The real id shape (uuid hex) must still pass the traversal guard."""
    fb = feedback.write_feedback(tmp_path, "9f2c1ab0e4d1", rating=5)
    assert fb.task_id == "9f2c1ab0e4d1"
    assert feedback.read_feedback(tmp_path, "9f2c1ab0e4d1") == fb
