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
    """A ``work_step`` trace event round-trips through ``event_from_dict``.

    The pre-rename ``"drive_step"`` type is no longer supported after the
    agentfront.taui migration (#249); all new trace lines use ``"work_step"``
    with a ``label`` field (replacing the old ``tool`` + ``summary`` pair).
    """
    from agentfront.taui.events import WorkStep, event_from_dict

    evt = event_from_dict({"type": "work_step", "label": "[read_file] x", "ok": True})
    assert isinstance(evt, WorkStep)
    assert evt.label == "[read_file] x"


def test_legacy_taui_drive_key_loads_as_work_item() -> None:
    """The TAUI snapshot work item round-trips through ``from_dict`` / ``to_dict``.

    The pre-rename ``"drive"`` key is no longer supported after the agentfront.taui
    migration (#249); new snapshots carry the work item under the ``"work"`` key.
    """
    from agentfront.taui.state import TAUIState as CockpitState
    from agentfront.taui.state import WorkItem

    state = CockpitState.from_dict({"work": {"task_id": "t1", "engine": "mock", "step_count": 2}})
    assert isinstance(state.work_item, WorkItem)
    assert state.work_item.task_id == "t1"
    # And the new key round-trips.
    assert CockpitState.from_dict(state.to_dict()).work_item.task_id == "t1"


def test_whoami_json_uses_work_keys(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["whoami", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert "work_engine" in payload
    assert "work_model" in payload


def test_legacy_drive_only_engine_still_instantiates_and_runs() -> None:
    """A pre-rename plugin that implements `drive()` (not `work()`) keeps working.

    The Engine ABC bridges its `work` to the legacy `drive` (with a
    DeprecationWarning) so `registry.load(...)` can still instantiate it (Qodo #3).
    """
    import warnings

    from colleague.config import EngineConfig
    from colleague.contract import Task, TaskResult
    from colleague.engine import Engine

    class LegacyEngine(Engine):  # only implements the OLD method name
        name = "legacy"

        def drive(self, task: Task, config: EngineConfig) -> TaskResult:
            return TaskResult(task_id=task.id, status="ok", summary="legacy ok")

    eng = LegacyEngine()  # would raise "abstract method work" without the bridge
    task = Task(id="t1", repo_path=".", instruction="x")
    cfg = EngineConfig.resolve()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = eng.work(task, cfg)
    assert result.summary == "legacy ok"
    assert any(issubclass(w.category, DeprecationWarning) for w in caught)


def test_base_drive_delegates_to_work() -> None:
    """A new-style engine (implements `work`) is still callable via the old `.drive()`."""
    from colleague.config import EngineConfig
    from colleague.contract import Task, TaskResult
    from colleague.engine import Engine

    class NewEngine(Engine):
        name = "new"

        def work(self, task: Task, config: EngineConfig) -> TaskResult:
            return TaskResult(task_id=task.id, status="ok", summary="new ok")

    eng = NewEngine()
    task = Task(id="t2", repo_path=".", instruction="x")
    assert eng.drive(task, EngineConfig.resolve()).summary == "new ok"
