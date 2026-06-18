"""Tests for ``colleague flight status --follow`` and the streaming helper."""

from __future__ import annotations

import argparse
import json

from colleague import flight as flight_mod
from colleague.cli._commands.flight import (
    _format_record,
    _iter_new_feed_records,
    cmd_flight_status,
)


def _ns(**kw):
    """Build an argparse.Namespace with sensible defaults."""
    defaults = {"repo": str(kw.pop("repo", ".")), "json": True, "follow": False}
    defaults.update(kw)
    return argparse.Namespace(**defaults)


# ── _iter_new_feed_records ──────────────────────────────────────────────


class TestIterNewFeedRecords:
    """Exercises the deterministic helper that powers --follow."""

    def test_yields_all_records_in_order(self, tmp_path):
        feed = tmp_path / "feed.jsonl"
        feed.write_text(
            json.dumps({"step_index": 0, "tool": "read_file", "intent": "read", "stats": {}})
            + "\n"
            + json.dumps({"step_index": 1, "tool": "write_file", "intent": "write", "stats": {}})
            + "\n"
            + json.dumps({"step_index": 2, "tool": "run_tests", "intent": "test", "stats": {}})
            + "\n"
        )

        records, new_pos = _iter_new_feed_records(feed, 0)
        assert len(records) == 3
        assert records[0]["step_index"] == 0
        assert records[1]["step_index"] == 1
        assert records[2]["step_index"] == 2
        assert new_pos == 3

    def test_incremental_calls_only_return_new_records(self, tmp_path):
        feed = tmp_path / "feed.jsonl"
        feed.write_text(
            json.dumps({"step_index": 0, "tool": "read_file", "intent": "read", "stats": {}}) + "\n"
        )

        records, new_pos = _iter_new_feed_records(feed, 0)
        assert len(records) == 1
        assert records[0]["step_index"] == 0
        assert new_pos == 1

        # Append a second record
        with open(feed, "a") as f:
            f.write(
                json.dumps({"step_index": 1, "tool": "write_file", "intent": "write", "stats": {}})
                + "\n"
            )

        records2, new_pos2 = _iter_new_feed_records(feed, new_pos)
        assert len(records2) == 1
        assert records2[0]["step_index"] == 1
        assert new_pos2 == 2

    def test_skips_blank_lines(self, tmp_path):
        feed = tmp_path / "feed.jsonl"
        feed.write_text(
            json.dumps({"step_index": 0, "tool": "read_file", "intent": "read", "stats": {}})
            + "\n"
            + "\n"
            + "   \n"
            + json.dumps({"step_index": 1, "tool": "write_file", "intent": "write", "stats": {}})
            + "\n"
        )

        records, new_pos = _iter_new_feed_records(feed, 0)
        assert len(records) == 2
        assert records[0]["step_index"] == 0
        assert records[1]["step_index"] == 1
        assert new_pos == 4  # counts all 4 lines (2 records + 2 blanks)

    def test_skips_torn_trailing_line(self, tmp_path):
        feed = tmp_path / "feed.jsonl"
        feed.write_text(
            json.dumps({"step_index": 0, "tool": "read_file", "intent": "read", "stats": {}})
            + "\n"
            + '{"step_index": 1, "to'  # torn/partial line
        )

        records, new_pos = _iter_new_feed_records(feed, 0)
        assert len(records) == 1
        assert records[0]["step_index"] == 0
        assert new_pos == 2  # counts both lines

    def test_missing_file_returns_empty(self, tmp_path):
        feed = tmp_path / "missing.jsonl"
        records, new_pos = _iter_new_feed_records(feed, 0)
        assert records == []
        assert new_pos == 0

    def test_start_line_past_end_returns_empty(self, tmp_path):
        feed = tmp_path / "feed.jsonl"
        feed.write_text(
            json.dumps({"step_index": 0, "tool": "read_file", "intent": "read", "stats": {}}) + "\n"
        )

        records, new_pos = _iter_new_feed_records(feed, 10)
        assert records == []
        assert new_pos == 10


# ── _format_record ─────────────────────────────────────────────────────


class TestFormatRecord:
    def test_json_mode_emits_one_json_object(self):
        record = {"step_index": 3, "tool": "read_file", "intent": "read", "stats": {"ok": True}}
        line = _format_record(record, json_mode=True)
        parsed = json.loads(line)
        assert parsed == record

    def test_json_mode_each_line_is_valid_json(self):
        records = [
            {"step_index": i, "tool": f"tool_{i}", "intent": f"intent_{i}", "stats": {}}
            for i in range(5)
        ]
        for record in records:
            line = _format_record(record, json_mode=True)
            parsed = json.loads(line)
            assert parsed == record

    def test_text_mode_produces_human_readable(self):
        record = {"step_index": 1, "tool": "read_file", "intent": "read", "stats": {}}
        line = _format_record(record, json_mode=False)
        assert "step=1" in line
        assert "tool=read_file" in line
        assert "intent=read" in line


# ── one-shot status (no --follow) ──────────────────────────────────────


class TestOneShotStatusUnchanged:
    """Verify the one-shot path is byte-identical to before the --follow change."""

    def test_status_returns_last_record(self, tmp_path, capsys):
        flight_mod.arm(tmp_path, "tid")
        session = flight_mod.FlightSession(repo_path=tmp_path, task_id="tid")
        session.append_feed(step_index=0, tool="read_file", intent="read", stats={})
        session.append_feed(step_index=1, tool="write_file", intent="write", stats={})

        args = _ns(task_id="tid", repo=tmp_path, json=True)
        rc = cmd_flight_status(args)
        assert rc == 0

        payload = json.loads(capsys.readouterr().out)
        assert payload["step_index"] == 1

    def test_status_armed_empty_feed(self, tmp_path, capsys):
        flight_mod.arm(tmp_path, "tid")
        args = _ns(task_id="tid", repo=tmp_path, json=True)
        rc = cmd_flight_status(args)
        assert rc == 0

        payload = json.loads(capsys.readouterr().out)
        assert payload == {"flight": "tid", "records": 0}

    def test_status_skips_torn_trailing_line(self, tmp_path, capsys):
        flight_mod.arm(tmp_path, "tid")
        session = flight_mod.FlightSession(repo_path=tmp_path, task_id="tid")
        session.append_feed(step_index=0, tool="read_file", intent="ok", stats={})
        with open(flight_mod.feed_path(tmp_path, "tid"), "a") as f:
            f.write('{"step_index": 1, "to')

        args = _ns(task_id="tid", repo=tmp_path, json=True)
        rc = cmd_flight_status(args)
        assert rc == 0

        payload = json.loads(capsys.readouterr().out)
        assert payload["step_index"] == 0
