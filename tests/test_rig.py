"""Tests for the rig-level cooperative concurrency budget (plan t13 / spec R5 / #258)."""

from __future__ import annotations

import json
import os
from pathlib import Path

from colleague.rig import load_rig_concurrency, rig_slot


def _declare_rig(repo: Path, concurrency: int | object) -> None:
    (repo / ".colleague").mkdir(exist_ok=True)
    (repo / ".colleague" / "rig.json").write_text(
        json.dumps({"concurrency": concurrency}), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# load_rig_concurrency
# ---------------------------------------------------------------------------


def test_unconfigured_repo_is_none(tmp_path):
    assert load_rig_concurrency(tmp_path) is None


def test_declared_concurrency_loads(tmp_path):
    _declare_rig(tmp_path, 2)
    assert load_rig_concurrency(tmp_path) == 2


def test_malformed_or_invalid_is_none(tmp_path):
    (tmp_path / ".colleague").mkdir()
    (tmp_path / ".colleague" / "rig.json").write_text("{oops", encoding="utf-8")
    assert load_rig_concurrency(tmp_path) is None
    _declare_rig(tmp_path, 0)
    assert load_rig_concurrency(tmp_path) is None
    _declare_rig(tmp_path, True)
    assert load_rig_concurrency(tmp_path) is None
    _declare_rig(tmp_path, "three")
    assert load_rig_concurrency(tmp_path) is None


# ---------------------------------------------------------------------------
# rig_slot
# ---------------------------------------------------------------------------


def test_unconfigured_slot_is_strict_noop(tmp_path):
    with rig_slot(tmp_path) as held:
        assert held is False
    assert not (tmp_path / ".colleague" / "rig-slots").exists()


def test_slot_taken_and_released(tmp_path):
    _declare_rig(tmp_path, 1)
    slots = tmp_path / ".colleague" / "rig-slots"
    with rig_slot(tmp_path) as held:
        assert held is True
        assert (slots / "slot-0").is_dir()
        assert (slots / "slot-0" / "pid").read_text().strip() == str(os.getpid())
    assert not (slots / "slot-0").exists()  # released


def test_second_holder_degrades_open_after_wait(tmp_path):
    _declare_rig(tmp_path, 1)
    waits: list[str] = []
    with rig_slot(tmp_path) as first:
        assert first is True
        with rig_slot(tmp_path, on_wait=waits.append, max_wait=0.2, poll=0.05) as second:
            assert second is False  # degraded open, never wedged
    assert any("waiting for a rig slot" in w for w in waits)
    assert any("proceeding without a slot" in w for w in waits)


def test_two_slots_serve_two_holders(tmp_path):
    _declare_rig(tmp_path, 2)
    with rig_slot(tmp_path) as a:
        with rig_slot(tmp_path, max_wait=0.0) as b:
            assert a is True and b is True


def test_stale_slot_from_dead_pid_is_reclaimed(tmp_path):
    _declare_rig(tmp_path, 1)
    slot = tmp_path / ".colleague" / "rig-slots" / "slot-0"
    slot.mkdir(parents=True)
    # A PID that cannot be alive: fork-bomb-proof choice is our own pid's
    # negative? kill(0) semantics differ — use an unlikely-but-valid huge pid.
    (slot / "pid").write_text("99999999", encoding="utf-8")
    with rig_slot(tmp_path, max_wait=0.0) as held:
        assert held is True  # stale holder reaped, slot retaken
    assert not slot.exists()


def test_live_holder_is_never_stolen(tmp_path):
    _declare_rig(tmp_path, 1)
    slot = tmp_path / ".colleague" / "rig-slots" / "slot-0"
    slot.mkdir(parents=True)
    (slot / "pid").write_text(str(os.getpid()), encoding="utf-8")  # us: alive
    waits: list[str] = []
    with rig_slot(tmp_path, on_wait=waits.append, max_wait=0.1, poll=0.05) as held:
        assert held is False
    assert slot.exists()  # untouched


# ---------------------------------------------------------------------------
# execute_work wiring — one slot per top-level work item
# ---------------------------------------------------------------------------


def test_execute_work_holds_and_releases_a_rig_slot(tmp_path, monkeypatch):
    import subprocess

    from colleague.config import EngineConfig
    from colleague.contract import OK, Task, TaskResult

    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    for key, value in (("user.email", "t@e.c"), ("user.name", "T")):
        subprocess.run(
            ["git", "config", key, value],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
    (tmp_path / "README.md").write_text("x\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)
    _declare_rig(tmp_path, 1)

    held_during_work: list[bool] = []

    class _SlotProbeEngine:
        def work(self, task, config):
            slot = tmp_path / ".colleague" / "rig-slots" / "slot-0"
            held_during_work.append(slot.is_dir())
            return TaskResult(task_id=task.id, status=OK, summary="done")

    monkeypatch.setattr("colleague.registry.load", lambda name: _SlotProbeEngine())
    from colleague.cli._commands.work import execute_work

    task = Task.new(str(tmp_path), "probe the slot", engine="mock")
    execute_work(
        repo=tmp_path,
        engine_name="mock",
        task=task,
        open_pr=False,
        base="main",
        config=EngineConfig.resolve(repo_path=tmp_path),
        allow_dirty=True,
    )
    assert held_during_work == [True]  # held while the engine drove
    assert not (tmp_path / ".colleague" / "rig-slots" / "slot-0").exists()  # released
