"""The per-drive feedback store (t4): single record, last-pointer, clean no-op."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from colleague import feedback
from colleague.artifact import write
from colleague.contract import OK, TaskResult, WorkStats
from colleague.feedback import Feedback, FeedbackError


def _record_drive(repo: Path, task_id: str, request: str, started_at: str = "") -> None:
    """Write a minimal drive artifact under repo/.colleague (for list_work_items)."""
    stats = WorkStats(request=request, started_at=started_at)
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
# #132: list_work_items — recover a drive by its request, not a fragile `last`
# ---------------------------------------------------------------------------


def test_list_work_items_empty_is_empty_list(tmp_path: Path) -> None:
    assert feedback.list_work_items(tmp_path) == []


def test_list_work_items_newest_first_with_grade(tmp_path: Path) -> None:
    _record_drive(tmp_path, "older", "implement the parser", started_at="2026-06-05T10:00:00+00:00")
    _record_drive(tmp_path, "newer", "review the auth diff", started_at="2026-06-05T11:00:00+00:00")
    feedback.write_feedback(tmp_path, "older", rating=4)  # graded; newer is ungraded

    rows = feedback.list_work_items(tmp_path)
    assert [r.task_id for r in rows] == ["newer", "older"]  # newest-first by started_at
    by_id = {r.task_id: r for r in rows}
    assert by_id["older"].rating == 4 and by_id["older"].request == "implement the parser"
    assert by_id["newer"].rating is None  # ungraded reads back as None, not an error
    assert by_id["newer"].status == OK


def test_list_work_items_reads_task_id_from_contents_not_filename(tmp_path: Path) -> None:
    """The slug in the filename is cosmetic — list_work_items keys off the JSON task_id."""
    _record_drive(tmp_path, "tid99", "do a slugged thing", started_at="2026-06-05T12:00:00+00:00")
    # The artifact on disk is slugged; list_work_items still surfaces the bare id.
    assert (tmp_path / ".colleague" / "tid99.do-a-slugged-thing.json").is_file()
    rows = feedback.list_work_items(tmp_path)
    assert len(rows) == 1 and rows[0].task_id == "tid99"


def test_list_work_items_skips_corrupt_files(tmp_path: Path) -> None:
    _record_drive(tmp_path, "good", "a good drive", started_at="2026-06-05T09:00:00+00:00")
    (tmp_path / ".colleague" / "broken.json").write_text("{not json", encoding="utf-8")
    rows = feedback.list_work_items(tmp_path)
    assert [r.task_id for r in rows] == ["good"]  # the corrupt file is skipped, never raised


def test_list_work_items_excludes_feedback_records(tmp_path: Path) -> None:
    _record_drive(tmp_path, "d1", "the one drive", started_at="2026-06-05T08:00:00+00:00")
    feedback.write_feedback(tmp_path, "d1", rating=5)  # writes d1.feedback.json beside it
    rows = feedback.list_work_items(tmp_path)
    assert len(rows) == 1 and rows[0].task_id == "d1"  # the .feedback.json is not a drive row


def test_rating_must_be_int_not_bool(tmp_path: Path) -> None:
    # bool is an int subclass — must be rejected, not silently treated as 0/1.
    with pytest.raises(FeedbackError):
        feedback.write_feedback(tmp_path, "d", rating=True)  # type: ignore[arg-type]


def test_last_drive_pointer_round_trips(tmp_path: Path) -> None:
    assert feedback.get_last_work(tmp_path) is None
    feedback.set_last_work(tmp_path, "drive-xyz")
    assert feedback.get_last_work(tmp_path) == "drive-xyz"
    # A later drive overwrites the pointer.
    feedback.set_last_work(tmp_path, "drive-abc")
    assert feedback.get_last_work(tmp_path) == "drive-abc"


def test_resolve_task_id_last_and_explicit(tmp_path: Path) -> None:
    feedback.set_last_work(tmp_path, "the-last-one")
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


# ---------------------------------------------------------------------------
# t3: author provenance — operator vs cortex records coexist per task_id (c17/h14)
# ---------------------------------------------------------------------------


def test_write_feedback_defaults_to_operator_author(tmp_path: Path) -> None:
    rec = feedback.write_feedback(tmp_path, "d", rating=4)
    assert rec.author == "operator"
    # The default author keeps the pre-author, un-suffixed filename (back-compat).
    assert (tmp_path / ".colleague" / "d.feedback.json").is_file()


def test_operator_default_to_dict_omits_author_key() -> None:
    """The default-author shape stays byte-identical to the pre-author contract
    (docs/contract.md's pinned `feedback` key block) — author is omit-when-default,
    the same convention already used for `chain`."""
    record = Feedback(task_id="t1", rating=4)
    assert "author" not in record.to_dict()


def test_cortex_author_to_dict_includes_author_key() -> None:
    record = Feedback(task_id="t1", rating=4, author="cortex")
    assert record.to_dict()["author"] == "cortex"


def test_legacy_record_without_author_key_loads_as_operator(tmp_path: Path) -> None:
    """A pre-existing on-disk record with no 'author' key must still load — back-compat."""
    adir = tmp_path / ".colleague"
    adir.mkdir()
    (adir / "legacy.feedback.json").write_text(
        json.dumps(
            {
                "task_id": "legacy",
                "rating": 3,
                "notes": "",
                "by": "",
                "at": "2026-01-01T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    loaded = feedback.read_feedback(tmp_path, "legacy")
    assert loaded is not None
    assert loaded.author == "operator"


def test_cortex_record_lands_beside_operator_record_never_overwriting(tmp_path: Path) -> None:
    feedback.write_feedback(tmp_path, "shared", rating=2, notes="operator take")
    feedback.write_feedback(tmp_path, "shared", rating=5, notes="cortex take", author="cortex")

    op = feedback.read_feedback(tmp_path, "shared")
    cx = feedback.read_feedback(tmp_path, "shared", author="cortex")
    assert op is not None
    assert op.rating == 2
    assert op.notes == "operator take"
    assert op.author == "operator"
    assert cx is not None
    assert cx.rating == 5
    assert cx.notes == "cortex take"
    assert cx.author == "cortex"
    # Two sibling files — writing the cortex record never touched the operator's.
    assert (tmp_path / ".colleague" / "shared.feedback.json").is_file()
    assert (tmp_path / ".colleague" / "shared.cortex.feedback.json").is_file()


def test_same_author_rewrite_still_overwrites(tmp_path: Path) -> None:
    """Idempotent regrade: same task_id + same author overwrites (today's semantics)."""
    feedback.write_feedback(tmp_path, "d", rating=2, author="cortex")
    feedback.write_feedback(tmp_path, "d", rating=5, author="cortex")
    loaded = feedback.read_feedback(tmp_path, "d", author="cortex")
    assert loaded is not None
    assert loaded.rating == 5


def test_invalid_author_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(FeedbackError):
        feedback.write_feedback(tmp_path, "d", rating=3, author="bogus")
    with pytest.raises(FeedbackError):
        feedback.read_feedback(tmp_path, "d", author="bogus")


def test_list_work_items_excludes_every_author_feedback_record(tmp_path: Path) -> None:
    """Both the default-author and the author-suffixed feedback file are skipped
    (the `.feedback.json` suffix check applies regardless of author)."""
    _record_drive(tmp_path, "d1", "the one drive", started_at="2026-06-05T08:00:00+00:00")
    feedback.write_feedback(tmp_path, "d1", rating=5)
    feedback.write_feedback(tmp_path, "d1", rating=4, author="cortex")
    rows = feedback.list_work_items(tmp_path)
    assert len(rows) == 1
    assert rows[0].task_id == "d1"
    assert rows[0].rating == 5  # list_work_items grades off the default (operator) record
