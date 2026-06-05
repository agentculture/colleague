"""Back-compat guards for the `drive`→`work` rename (v0.37.0).

The CLI verb keeps a deprecated `drive` alias, and the machine wire formats that
were renamed (`last_drive` pointer, `drive_step` trace event, the TAUI `"drive"`
key) are still *read* under their old names so pre-rename artifacts keep working.
These guards pin every one of those promises.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from colleague.cli import main


def test_work_verb_is_primary(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["work", "x", "--repo", str(tmp_path), "--engine", "mock", "--no-pr", "--json"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["status"] == "ok"


def test_drive_alias_still_resolves(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The deprecated `drive` alias dispatches to the same handler as `work`."""
    rc = main(["drive", "x", "--repo", str(tmp_path), "--engine", "mock", "--no-pr", "--json"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["status"] == "ok"


def test_explain_work_and_drive_alias(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["explain", "work"]) == 0
    assert "colleague work" in capsys.readouterr().out
    assert main(["explain", "drive"]) == 0  # alias still resolves
    assert "colleague work" in capsys.readouterr().out


def test_legacy_last_drive_pointer_is_read(tmp_path: Path) -> None:
    """A pre-rename `.colleague/last_drive` (no `last_work`) still resolves `last`."""
    from colleague.feedback import get_last_work

    cdir = tmp_path / ".colleague"
    cdir.mkdir()
    (cdir / "last_drive").write_text("legacy-task\n", encoding="utf-8")
    assert get_last_work(tmp_path) == "legacy-task"


def test_legacy_drive_step_event_loads_as_work_step() -> None:
    """A pre-rename trace line with `"type": "drive_step"` still reconstructs."""
    from colleague.tui.events import WorkStep, event_from_dict

    evt = event_from_dict({"type": "drive_step", "tool": "read_file", "summary": "x", "ok": True})
    assert isinstance(evt, WorkStep)
    assert evt.tool == "read_file"


def test_legacy_taui_drive_key_loads_as_work_item() -> None:
    """A pre-rename snapshot carrying the work item under `"drive"` still loads."""
    from colleague.tui.state import CockpitState, WorkItem

    state = CockpitState.from_dict({"drive": {"task_id": "t1", "engine": "mock", "step_count": 2}})
    assert isinstance(state.work_item, WorkItem)
    assert state.work_item.task_id == "t1"
    # And the new key round-trips.
    assert CockpitState.from_dict(state.to_dict()).work_item.task_id == "t1"


def test_whoami_json_uses_work_keys(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["whoami", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert "work_engine" in payload
    assert "work_model" in payload
