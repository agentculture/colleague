"""The per-drive feedback store (t4): single record, last-pointer, clean no-op."""

from __future__ import annotations

from pathlib import Path

import pytest

from convertible import feedback
from convertible.feedback import Feedback, FeedbackError


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
