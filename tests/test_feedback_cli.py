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


def test_record_no_identity_warns_on_stderr_and_still_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Empty repo + clean HOME → resolve_identity returns None. The record still
    # writes (exit 0), `by` renders (unknown), and a stderr advisory points at the
    # fix — without polluting the stdout result (#145).
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    repo = tmp_path / "repo"
    repo.mkdir()
    rc = main(["feedback", "record", "d4", "--rating", "4", "--repo", str(repo)])
    assert rc == 0
    captured = capsys.readouterr()
    assert "feedback: no identity resolved" in captured.err
    assert "(unknown)" in captured.out
    assert "no identity resolved" not in captured.out  # advisory stays off stdout


def test_record_with_identity_emits_no_hint(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # A culture.yaml nick is source 1 (checked before any home fallback), so this
    # is hermetic regardless of host home: identity resolves, no advisory fires.
    (tmp_path / "culture.yaml").write_text("nick: testbot\n", encoding="utf-8")
    rc = main(["feedback", "record", "d5", "--rating", "4", "--repo", str(tmp_path)])
    assert rc == 0
    captured = capsys.readouterr()
    assert "no identity resolved" not in captured.err
    assert "testbot" in captured.out


def test_record_explicit_by_suppresses_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # An explicit --by is a deliberate attribution choice; no advisory even with
    # no resolvable identity.
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    rc = main(["feedback", "record", "d6", "--rating", "4", "--by", "me", "--repo", str(tmp_path)])
    assert rc == 0
    captured = capsys.readouterr()
    assert "no identity resolved" not in captured.err
    assert "me" in captured.out


def test_record_no_identity_json_stdout_stays_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # --json + no identity: the advisory is stderr-only; stdout stays clean,
    # parseable JSON with an empty `by`.
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    rc = main(["feedback", "record", "d7", "--rating", "4", "--repo", str(tmp_path), "--json"])
    assert rc == 0
    captured = capsys.readouterr()
    rec = json.loads(captured.out)
    assert rec["by"] == ""
    assert "feedback: no identity resolved" in captured.err


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
    assert "no work items recorded yet" in capsys.readouterr().out

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


def test_record_chain_tail_grades_every_episode(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """One record call on a chain tail stamps every episode (indefinite-run c30)."""
    adir = tmp_path / ".colleague"
    adir.mkdir()
    base = {"status": "incomplete", "summary": "s", "changed_files": [], "steps": [], "usage": {}}
    (adir / "e1.json").write_text(json.dumps({**base, "task_id": "e1"}), encoding="utf-8")
    (adir / "e2.json").write_text(
        json.dumps({**base, "task_id": "e2", "continued_from": "e1"}), encoding="utf-8"
    )
    (adir / "e3.json").write_text(
        json.dumps({**base, "task_id": "e3", "continued_from": "e2"}), encoding="utf-8"
    )
    rc = main(
        [
            "feedback",
            "record",
            "e3",
            "--rating",
            "5",
            "--by",
            "ori",
            "--repo",
            str(tmp_path),
            "--json",
        ]
    )
    assert rc == 0
    rec = json.loads(capsys.readouterr().out)
    assert rec["chain_episodes"] == ["e3", "e2", "e1"]
    for tid in ("e1", "e2", "e3"):
        rc = main(["feedback", "show", tid, "--repo", str(tmp_path), "--json"])
        assert rc == 0
        shown = json.loads(capsys.readouterr().out)
        assert shown["rating"] == 5 and shown["chain"] is True


def test_record_ordinary_item_keeps_single_record_shape(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A lineage-less grade keeps today's persisted shape — no chain key at all."""
    rc = main(
        [
            "feedback",
            "record",
            "d9",
            "--rating",
            "3",
            "--by",
            "ori",
            "--repo",
            str(tmp_path),
            "--json",
        ]
    )
    assert rc == 0
    rec = json.loads(capsys.readouterr().out)
    assert "chain" not in rec and "chain_episodes" not in rec
