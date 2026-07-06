"""``feedback export`` — the ROI ledger line (S7, colleague#296).

``colleague.feedback.export_work_items`` joins the artifact + feedback stores
into one JSONL-line dict per GRADED work item (ungraded work items are
excluded entirely — this is a grading ledger, not ``feedback list``'s full
work-item inventory). Covers the core function, the rendered CLI tool
(``colleague.cli._commands.feedback._export`` / ``register_into``), the
legacy argparse path (``colleague.cli.main``), and the agentfront-rendered
dispatch (mirroring ``tests/test_cli_feedback_rendered.py``'s pattern) so the
hyphenated ``--min-rating`` flag is proven to work from real argv, not just a
direct Python call.
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest
from agentfront.cli_surface import run_cli

from colleague import feedback as fb
from colleague.artifact import write
from colleague.cli import main
from colleague.cli._app import build_app
from colleague.contract import OK, TaskResult, WorkStats


def _record_work_item(
    repo: Path,
    task_id: str,
    request: str,
    *,
    started_at: str = "",
    summary: str = "",
    step_count: int = 0,
    files_changed: int = 0,
    bytes_written: int = 0,
) -> None:
    """Write a minimal work-item artifact under repo/.colleague (mirrors test_feedback.py)."""
    stats = WorkStats(
        request=request,
        started_at=started_at,
        step_count=step_count,
        files_changed=files_changed,
        bytes_written=bytes_written,
    )
    write(
        TaskResult(task_id=task_id, status=OK, summary=summary or f"did {request}", stats=stats),
        repo / ".colleague",
    )


# ---------------------------------------------------------------------------
# core: colleague.feedback.export_work_items
# ---------------------------------------------------------------------------


def test_export_empty_store_returns_empty_list(tmp_path: Path) -> None:
    assert fb.export_work_items(tmp_path) == []


def test_export_excludes_ungraded(tmp_path: Path) -> None:
    _record_work_item(tmp_path, "graded", "task A", started_at="2026-01-01T00:00:00+00:00")
    _record_work_item(tmp_path, "ungraded", "task B", started_at="2026-01-02T00:00:00+00:00")
    fb.write_feedback(tmp_path, "graded", rating=4, notes="good")

    rows = fb.export_work_items(tmp_path)
    assert [r["task_id"] for r in rows] == ["graded"]


def test_export_line_shape_and_values(tmp_path: Path) -> None:
    _record_work_item(
        tmp_path,
        "w1",
        "implement the thing",
        started_at="2026-01-01T00:00:00+00:00",
        summary="implemented it",
        step_count=7,
        files_changed=2,
        bytes_written=321,
    )
    fb.write_feedback(tmp_path, "w1", rating=5, notes="great work", by="ori")

    rows = fb.export_work_items(tmp_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["task_id"] == "w1"
    assert row["request"] == "implement the thing"
    assert row["summary"] == "implemented it"
    assert row["rating"] == 5
    assert row["notes"] == "great work"
    assert row["status"] == OK
    assert row["at"]  # the feedback record's grading timestamp, non-empty
    assert row["stats"] == {"steps": 7, "files_changed": 2, "bytes_written": 321}


def test_export_min_rating_filters(tmp_path: Path) -> None:
    _record_work_item(tmp_path, "low", "low quality", started_at="2026-01-01T00:00:00+00:00")
    _record_work_item(tmp_path, "high", "high quality", started_at="2026-01-02T00:00:00+00:00")
    fb.write_feedback(tmp_path, "low", rating=2)
    fb.write_feedback(tmp_path, "high", rating=5)

    rows = fb.export_work_items(tmp_path, min_rating=4)
    assert [r["task_id"] for r in rows] == ["high"]

    rows_all = fb.export_work_items(tmp_path, min_rating=0)
    assert {r["task_id"] for r in rows_all} == {"low", "high"}


def test_export_since_filters_by_started_at(tmp_path: Path) -> None:
    _record_work_item(tmp_path, "old", "old task", started_at="2026-01-01T00:00:00+00:00")
    _record_work_item(tmp_path, "new", "new task", started_at="2026-03-01T00:00:00+00:00")
    fb.write_feedback(tmp_path, "old", rating=3)
    fb.write_feedback(tmp_path, "new", rating=3)

    rows = fb.export_work_items(tmp_path, since="2026-02-01")
    assert [r["task_id"] for r in rows] == ["new"]


def test_export_since_excludes_unparseable_started_at(tmp_path: Path) -> None:
    """A row whose started_at can't be parsed is excluded (conservative) when
    a since filter is active — it can't be proven to satisfy the filter."""
    _record_work_item(tmp_path, "weird", "weird task", started_at="not-a-date")
    fb.write_feedback(tmp_path, "weird", rating=3)

    rows = fb.export_work_items(tmp_path, since="2026-01-01")
    assert rows == []
    # ...but with no since filter, the row still shows up (best-effort, never dropped).
    rows_no_filter = fb.export_work_items(tmp_path)
    assert [r["task_id"] for r in rows_no_filter] == ["weird"]


def test_export_newest_first(tmp_path: Path) -> None:
    _record_work_item(tmp_path, "older", "older task", started_at="2026-01-01T00:00:00+00:00")
    _record_work_item(tmp_path, "newer", "newer task", started_at="2026-02-01T00:00:00+00:00")
    fb.write_feedback(tmp_path, "older", rating=3)
    fb.write_feedback(tmp_path, "newer", rating=3)

    rows = fb.export_work_items(tmp_path)
    assert [r["task_id"] for r in rows] == ["newer", "older"]


def test_parse_since_accepts_bare_date_and_full_timestamp() -> None:
    assert fb.parse_since("2026-07-01") is not None
    assert fb.parse_since("2026-07-01T12:00:00+00:00") is not None
    assert fb.parse_since("not-a-date") is None


# ---------------------------------------------------------------------------
# legacy argparse CLI: colleague.cli.main(["feedback", "export", ...])
# ---------------------------------------------------------------------------


def _jsonl_lines(text: str) -> list[dict]:
    return [json.loads(line) for line in text.strip("\n").split("\n") if line]


def test_cli_export_text_mode_is_jsonl(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _record_work_item(tmp_path, "w1", "task one", started_at="2026-01-01T00:00:00+00:00")
    _record_work_item(tmp_path, "w2", "task two", started_at="2026-01-02T00:00:00+00:00")
    fb.write_feedback(tmp_path, "w1", rating=4)
    # w2 stays ungraded.

    rc = main(["feedback", "export", "--repo", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    lines = _jsonl_lines(out)
    assert len(lines) == 1
    assert lines[0]["task_id"] == "w1"
    assert lines[0]["rating"] == 4


def test_cli_export_empty_store_exit_0_no_lines(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["feedback", "export", "--repo", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert out.strip() == ""  # no content lines (at most a trailing newline)
    assert _jsonl_lines(out) == []


def test_cli_export_min_rating_flag(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _record_work_item(tmp_path, "low", "low task", started_at="2026-01-01T00:00:00+00:00")
    _record_work_item(tmp_path, "high", "high task", started_at="2026-01-02T00:00:00+00:00")
    fb.write_feedback(tmp_path, "low", rating=2)
    fb.write_feedback(tmp_path, "high", rating=5)

    rc = main(["feedback", "export", "--min-rating", "4", "--repo", str(tmp_path)])
    assert rc == 0
    lines = _jsonl_lines(capsys.readouterr().out)
    assert [line["task_id"] for line in lines] == ["high"]


def test_cli_export_since_flag(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _record_work_item(tmp_path, "old", "old task", started_at="2026-01-01T00:00:00+00:00")
    _record_work_item(tmp_path, "new", "new task", started_at="2026-03-01T00:00:00+00:00")
    fb.write_feedback(tmp_path, "old", rating=3)
    fb.write_feedback(tmp_path, "new", rating=3)

    rc = main(["feedback", "export", "--since", "2026-02-01", "--repo", str(tmp_path)])
    assert rc == 0
    lines = _jsonl_lines(capsys.readouterr().out)
    assert [line["task_id"] for line in lines] == ["new"]


def test_cli_export_json_mode_gives_structured_array(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _record_work_item(tmp_path, "w1", "task one", started_at="2026-01-01T00:00:00+00:00")
    fb.write_feedback(tmp_path, "w1", rating=4)

    rc = main(["feedback", "export", "--repo", str(tmp_path), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload, list)
    assert payload[0]["task_id"] == "w1"


def test_cli_export_bad_format_errors_cleanly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["feedback", "export", "--format", "csv", "--repo", str(tmp_path)])
    assert rc != 0
    captured = capsys.readouterr()
    assert captured.out.strip() == ""
    assert "error:" in captured.err and "Traceback" not in captured.err


def test_cli_export_bad_since_errors_cleanly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["feedback", "export", "--since", "not-a-date", "--repo", str(tmp_path)])
    assert rc != 0
    captured = capsys.readouterr()
    assert captured.out.strip() == ""
    assert "error:" in captured.err


# ---------------------------------------------------------------------------
# agentfront-rendered CLI: proves the hyphenated --min-rating flag from argv
# (mirrors tests/test_cli_feedback_rendered.py's pattern exactly).
# ---------------------------------------------------------------------------


def _run(argv):
    out, err = io.StringIO(), io.StringIO()
    code = None
    try:
        with redirect_stdout(out), redirect_stderr(err):
            code = run_cli(build_app(), argv)
    except SystemExit as exc:
        code = exc.code
    return code, out.getvalue(), err.getvalue()


def test_rendered_cli_export_min_rating_hyphen_flag(tmp_path: Path) -> None:
    _record_work_item(tmp_path, "low", "low task", started_at="2026-01-01T00:00:00+00:00")
    _record_work_item(tmp_path, "high", "high task", started_at="2026-01-02T00:00:00+00:00")
    fb.write_feedback(tmp_path, "low", rating=2)
    fb.write_feedback(tmp_path, "high", rating=5)

    code, out, _ = _run(
        ["feedback", "export", "--min-rating", "4", "--repo", str(tmp_path), "--json"]
    )
    assert code == 0
    rows = json.loads(out)
    assert [r["task_id"] for r in rows] == ["high"]


def test_rendered_cli_export_empty_is_clean_dual(tmp_path: Path) -> None:
    code, out, _ = _run(["feedback", "export", "--repo", str(tmp_path)])
    assert code == 0 and out.strip() == ""

    code, out, _ = _run(["feedback", "export", "--repo", str(tmp_path), "--json"])
    assert code == 0 and json.loads(out) == []


def test_export_tool_lands_in_registry() -> None:
    app = build_app()
    paths = {tuple(t.group) + (t.name,) for t in app.list_tools()}
    assert ("feedback", "export") in paths


def test_explain_feedback_export_reads_doc() -> None:
    code, out, _ = _run(["explain", "feedback", "export"])
    assert code == 0 and "export" in out.lower()
