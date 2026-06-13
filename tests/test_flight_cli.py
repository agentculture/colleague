"""Tests for the ``colleague flight`` CLI noun."""

from __future__ import annotations

import argparse
import json

import pytest

from colleague import flight as flight_mod
from colleague.cli._commands.flight import (
    cmd_flight_guide,
    cmd_flight_list,
    cmd_flight_status,
    cmd_flight_stop,
)
from colleague.cli._errors import CliError


def _ns(**kw):
    """Build an argparse.Namespace with sensible defaults."""
    defaults = {"repo": str(kw.pop("repo", ".")), "json": True}
    defaults.update(kw)
    return argparse.Namespace(**defaults)


class TestFlightStatus:
    def test_status_returns_latest_record(self, tmp_path):
        flight_mod.arm(tmp_path, "tid")
        session = flight_mod.FlightSession(repo_path=tmp_path, task_id="tid")
        session.append_feed(step_index=0, tool="read_file", intent="read README", stats={})
        session.append_feed(step_index=1, tool="write_file", intent="write result", stats={})

        args = _ns(task_id="tid", repo=tmp_path)
        rc = cmd_flight_status(args)
        assert rc == 0

        # The last record should be step_index=1
        feed = flight_mod.feed_path(tmp_path, "tid").read_text().strip().splitlines()
        last = json.loads(feed[-1])
        assert last["step_index"] == 1

    def test_status_missing_flight_raises(self, tmp_path):
        args = _ns(task_id="nope", repo=tmp_path)
        with pytest.raises(CliError, match="no active flight nope"):
            cmd_flight_status(args)


class TestFlightGuide:
    def test_guide_appends_guidance(self, tmp_path):
        flight_mod.arm(tmp_path, "tid")

        args = _ns(task_id="tid", message="refactor auth", repo=tmp_path)
        rc = cmd_flight_guide(args)
        assert rc == 0

        session = flight_mod.FlightSession(repo_path=tmp_path, task_id="tid")
        control = session.read_control()
        assert "refactor auth" in control.guidance


class TestFlightStop:
    def test_stop_sets_stop_flag(self, tmp_path):
        flight_mod.arm(tmp_path, "tid")

        args = _ns(task_id="tid", repo=tmp_path)
        rc = cmd_flight_stop(args)
        assert rc == 0

        session = flight_mod.FlightSession(repo_path=tmp_path, task_id="tid")
        control = session.read_control()
        assert control.stop is True


class TestFlightList:
    def test_list_reports_active_flights(self, tmp_path):
        flight_mod.arm(tmp_path, "tid")
        flight_mod.arm(tmp_path, "other")

        args = _ns(repo=tmp_path)
        rc = cmd_flight_list(args)
        assert rc == 0

        # Both task ids should appear
        files = flight_mod.list_flight_files(tmp_path)
        feed_files = [f for f in files if f.name.endswith(".feed.jsonl")]
        task_ids = sorted(f.name[: -len(".feed.jsonl")] for f in feed_files)
        assert "tid" in task_ids
        assert "other" in task_ids
