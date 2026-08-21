"""#410 — SIGTERM writes the partial artifact unconditionally.

The interrupt-safety contract (#162/#222) promised a resumable artifact after a
SIGTERM; from a run wedged INSIDE a model request the WIP commit fired but the
artifact write did not, so ``work --continue`` refused. These tests pin the
fix: the handler reads the loop's live partial through ``colleague.salvage``
and writes the artifact BEFORE the process unwinds — independent of the
request layer's state — and the continuation lane accepts it.

The blocking completion reads a REAL ``os.pipe`` (never a fake stream that
returns; see the repo's fake-streams gotcha) so the signal genuinely interrupts
a blocked read.
"""

from __future__ import annotations

import json
import os
import signal
import threading
from pathlib import Path

import pytest

from colleague import loop, salvage
from colleague.artifact import artifact_dir
from colleague.cli._commands.work import (
    _arm_interrupt_commit,
    _make_salvage_writer,
    finalize_interrupted,
)
from colleague.continuation import resolve_continuation
from colleague.contract import ERROR, Task, TaskResult


def _artifact_json(repo: Path, task_id: str) -> dict:
    files = [
        p
        for p in artifact_dir(repo).glob(f"{task_id}*.json")
        if not p.name.endswith(".trace.jsonl")
    ]
    assert len(files) == 1, files
    return json.loads(files[0].read_text(encoding="utf-8"))


def test_sigterm_inside_blocked_request_writes_artifact_and_continue_accepts(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    task = Task.new(str(repo), "hang forever on the wire")
    rfd, wfd = os.pipe()

    def blocking_complete(_messages):
        os.read(rfd, 1)  # parks the main thread in a real blocking read
        raise AssertionError("unreachable: the signal must unwind the read")

    restore = _arm_interrupt_commit(
        None,
        salvage_write=_make_salvage_writer(
            task, repo, command_name=None, mode=None, continued_from=None
        ),
    )
    timer = threading.Timer(0.3, lambda: os.kill(os.getpid(), signal.SIGTERM))
    timer.daemon = True
    try:
        timer.start()
        with pytest.raises(SystemExit) as excinfo:
            loop.run(blocking_complete, task, max_steps=3)
        assert excinfo.value.code == 128 + signal.SIGTERM
    finally:
        restore()
        timer.cancel()
        os.close(rfd)
        os.close(wfd)

    data = _artifact_json(repo, task.id)
    assert data["status"] == ERROR
    assert data["incompletion"]["reason"] == "interrupted"
    assert "SIGTERM" in data["error"]
    # the live partial is released once salvaged
    assert salvage.peek(task.id) is None
    # the continuation lane accepts the salvaged artifact (the #410 ask)
    task_id, seed = resolve_continuation(repo, task.id)
    assert task_id == task.id
    assert "hang forever on the wire" in seed


def test_salvage_writer_without_live_partial_still_writes_an_artifact(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    task = Task.new(str(repo), "never started")
    writer = _make_salvage_writer(task, repo, command_name="x", mode=None, continued_from=None)
    writer("SIGINT")
    data = _artifact_json(repo, task.id)
    assert data["status"] == ERROR
    assert data["command"] == "x"
    assert "SIGINT" in data["error"]


def test_finalize_interrupted_is_idempotent_and_keeps_summary() -> None:
    result = TaskResult(task_id="abc", status="ok", summary="did two things")
    finalize_interrupted(
        result, reason="SIGTERM", command_name=None, mode="explore", continued_from="prev"
    )
    finalize_interrupted(
        result, reason="SIGTERM", command_name=None, mode="explore", continued_from="prev"
    )
    assert result.status == ERROR
    assert result.summary == "did two things"  # never overwritten
    assert result.mode == "explore" and result.continued_from == "prev"
    assert (
        result.incompletion is not None
        and "work --continue abc" in result.incompletion.recommendation
    )


def test_arm_without_worktree_or_writer_installs_nothing() -> None:
    prior = signal.getsignal(signal.SIGTERM)
    restore = _arm_interrupt_commit(None)
    assert signal.getsignal(signal.SIGTERM) is prior
    restore()
