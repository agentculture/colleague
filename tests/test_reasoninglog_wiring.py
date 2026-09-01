"""Wiring of the reasoning sidecar into the loop (effort-v4 plan task t6).

Covers the three acceptance criteria (spec c16/h7/c34/h20):

1. A run with reasoning present yields per-turn sidecar records; the repo's
   ``git status`` stays clean (the sidecar lands under the already-ignored
   ``.colleague/``); the model context messages are byte-identical with and
   without the sidecar (display/disk only — h7).
2. A parallel read-only batch renders N tool-call records sharing ONE
   ``request_ts``/``request_index``; a sequential pair gets two distinct
   indices (mock run, the contract reference — the all-engines rule).
3. A subagent child's sidecar lands TAGGED in the operator repo's
   ``.colleague/`` and survives child-worktree removal (h20).

Kept in its own focused file (not ``tests/test_reasoninglog.py``, which pins
the t3 module's own contract) so the per-file length ratchet stays intact.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from colleague import loop
from colleague.config import EngineConfig
from colleague.contract import Task
from colleague.engines.mock import MockEngine
from colleague.loop_wire import ModelResponse, ToolCall
from colleague.subagents import run_subagent
from colleague.subagents_binding import ChildSpec
from tests._batch_fixture import BATCH_TASK_INSTRUCTION, make_batch_repo

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _read_records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def _sidecar(repo: Path, task_id: str) -> Path:
    return repo / ".colleague" / f"{task_id}.reasoning.jsonl"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env={
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.com",
            "HOME": str(repo),
            "PATH": "/usr/bin:/bin",
        },
    ).stdout


def _scripted_complete(captured: list[str]):
    """A two-turn scripted completion that snapshots the messages it receives."""
    turns = [
        ModelResponse(
            content="writing",
            reasoning="scripted reasoning: write the file",
            tool_calls=[ToolCall("c1", "write_file", {"path": "out.txt", "content": "x\n"})],
            prompt_tokens=1,
            completion_tokens=1,
            finish_reason="stop",
        ),
        ModelResponse(
            content="done",
            reasoning="scripted reasoning: finish",
            tool_calls=[ToolCall("c2", "finish", {"summary": "done"})],
            prompt_tokens=1,
            completion_tokens=1,
            finish_reason="stop",
        ),
    ]
    state = {"i": 0}

    def complete(messages: list[dict]) -> ModelResponse:
        captured.append(json.dumps(messages, sort_keys=True))
        turn = turns[min(state["i"], len(turns) - 1)]
        state["i"] += 1
        return turn

    return complete


# ---------------------------------------------------------------------------
# Acceptance 1 — per-turn records; clean git status; byte-identical context.
# ---------------------------------------------------------------------------


def test_mock_run_writes_per_turn_reasoning_records(tmp_path) -> None:
    """The default mock script (reasoning on both turns) yields per-turn records."""
    task = Task.new(str(tmp_path), "do the thing", engine="mock")
    result = MockEngine().work(task, EngineConfig())
    records = _read_records(_sidecar(tmp_path, task.id))
    reasoning = [r for r in records if r["text"].startswith("mock reasoning")]
    assert len(reasoning) == result.stats.model_turns == 2
    for record in reasoning:
        assert set(record) == {"seat", "turn", "request_ts", "request_index", "text"}
        assert record["seat"] == "cortex"
        assert record["request_index"] == 0  # the completion is ordinal 0 of its turn
    assert [r["turn"] for r in reasoning] == [1, 2]


def test_git_status_stays_clean(tmp_path) -> None:
    """In a repo that ignores ``.colleague/`` (as this one does), no dirt appears."""
    _git(tmp_path, "init", "-q")
    (tmp_path / ".gitignore").write_text(".colleague/\ncolleague-mock.md\nout.txt\n")
    _git(tmp_path, "add", ".gitignore")
    _git(tmp_path, "commit", "-qm", "init")
    task = Task.new(str(tmp_path), "do the thing", engine="mock")
    MockEngine().work(task, EngineConfig())
    assert _sidecar(tmp_path, task.id).is_file()
    assert _git(tmp_path, "status", "--porcelain").strip() == ""


def test_model_context_byte_identical_with_and_without_sidecar(tmp_path, monkeypatch) -> None:
    """h7: the messages the model sees never change — the sidecar is disk-only."""
    off_repo, on_repo = tmp_path / "off", tmp_path / "on"
    captured: dict[str, list[str]] = {"off": [], "on": []}
    for key, repo in (("off", off_repo), ("on", on_repo)):
        repo.mkdir()
        if key == "off":
            monkeypatch.setenv("COLLEAGUE_REASONING_LOG", "0")
        else:
            monkeypatch.delenv("COLLEAGUE_REASONING_LOG", raising=False)
        task = Task(id="fixed-task-id", repo_path=str(repo), instruction="same instruction")
        loop.run(_scripted_complete(captured[key]), task, max_steps=4)
    # Identical repo layout apart from the root name: normalize the one path.
    normalized_off = [m.replace(str(off_repo), "<repo>") for m in captured["off"]]
    normalized_on = [m.replace(str(on_repo), "<repo>") for m in captured["on"]]
    assert normalized_off == normalized_on
    assert not _sidecar(off_repo, "fixed-task-id").exists()  # off-knob: nothing written
    assert _read_records(_sidecar(on_repo, "fixed-task-id"))


def test_reasoning_free_run_writes_nothing(tmp_path) -> None:
    """A run whose turns carry no reasoning materializes NO sidecar at all —
    not even tool-call records — so its tree (and a mid-run ``list_dir``) is
    byte-identical to a run that never had the sidecar (h7)."""

    def complete(_messages: list[dict]) -> ModelResponse:
        return ModelResponse(
            content="done",
            tool_calls=[ToolCall("c1", "finish", {"summary": "done"})],
            prompt_tokens=1,
            completion_tokens=1,
            finish_reason="stop",
        )

    task = Task(id="no-reasoning", repo_path=str(tmp_path), instruction="x")
    loop.run(complete, task, max_steps=2)
    assert not (tmp_path / ".colleague").exists()


def test_parent_sidecar_lands_at_flight_repo_path(tmp_path) -> None:
    """An isolated run's sidecar follows the flight plane to the operator repo."""
    operator, work = tmp_path / "operator", tmp_path / "work"
    operator.mkdir()
    work.mkdir()
    task = Task(
        id="iso-task",
        repo_path=str(work),
        instruction="isolated",
        flight_repo_path=str(operator),
    )
    loop.run(_scripted_complete([]), task, max_steps=4)
    assert _read_records(_sidecar(operator, "iso-task"))
    assert not _sidecar(work, "iso-task").exists()


# ---------------------------------------------------------------------------
# Acceptance 2 — batch: one shared index; sequential: distinct indices.
# ---------------------------------------------------------------------------


def _read_call_records(repo: Path, task_id: str) -> list[dict]:
    records = _read_records(_sidecar(repo, task_id))
    return [r for r in records if r["text"] == "tool_call: read_file"]


def test_parallel_batch_records_share_one_request_ts_and_index(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("COLLEAGUE_TOOL_CONCURRENCY", "10")
    repo = make_batch_repo(tmp_path)
    task = Task.new(str(repo), BATCH_TASK_INSTRUCTION, engine="mock")
    MockEngine().work(task, EngineConfig())
    reads = _read_call_records(repo, task.id)
    assert len(reads) == 3
    assert len({(r["request_ts"], r["request_index"]) for r in reads}) == 1
    assert all(r["turn"] == 1 for r in reads)
    # The mutating write is its own dispatch — a DIFFERENT index than the reads.
    records = _read_records(_sidecar(repo, task.id))
    (write,) = [r for r in records if r["text"] == "tool_call: write_file"]
    assert write["request_index"] != reads[0]["request_index"]


def test_sequential_pair_gets_two_distinct_indices(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("COLLEAGUE_TOOL_CONCURRENCY", "1")
    repo = make_batch_repo(tmp_path)
    task = Task.new(str(repo), BATCH_TASK_INSTRUCTION, engine="mock")
    MockEngine().work(task, EngineConfig())
    reads = _read_call_records(repo, task.id)
    assert len(reads) == 3
    indices = [r["request_index"] for r in reads]
    assert len(set(indices)) == 3  # each sequential dispatch gets its own ordinal
    assert len({r["request_ts"] for r in reads}) >= 1  # stamped per dispatch


# ---------------------------------------------------------------------------
# Acceptance 3 — a child's sidecar lands tagged in the operator repo.
# ---------------------------------------------------------------------------


def test_child_sidecar_tagged_in_operator_repo_survives_worktree_removal(tmp_path) -> None:
    operator, child_worktree = tmp_path / "operator", tmp_path / "sub-worktree"
    operator.mkdir()
    child_worktree.mkdir()
    parent_config = EngineConfig()
    parent_config.reasoning_repo_path = str(operator)  # what _arm_delegation attaches
    sub = run_subagent(
        "scoped child task",
        repo_path=str(child_worktree),
        parent_config=parent_config,
        parent_engine="mock",
        depth=1,
        spec=ChildSpec(parent_task_id="parent-task-1"),
    )
    tagged = operator / ".colleague" / f"parent-task-1.{sub.task_id}.reasoning.jsonl"
    assert tagged.is_file()
    records = _read_records(tagged)
    assert any(r["text"].startswith("mock reasoning") for r in records)
    # No sidecar is left behind in the child worktree itself…
    assert not list(child_worktree.glob(".colleague/*.reasoning.jsonl"))
    # …and removing the worktree (teardown) leaves the tagged sidecar intact.
    shutil.rmtree(child_worktree)
    assert tagged.is_file()


def test_arm_delegation_attaches_operator_repo(tmp_path) -> None:
    """The spawn plumbing carries the OPERATOR repo (flight plane precedent #310)."""
    from colleague.cli._commands.work import _arm_delegation

    operator, work = tmp_path / "operator", tmp_path / "work"
    operator.mkdir()
    work.mkdir()
    task = Task.new(str(work), "x", flight_repo_path=str(operator))
    config = EngineConfig()
    _arm_delegation(config, task)
    assert config.reasoning_repo_path == str(operator)
    # An in-place run (no isolation) tags children to the run's own repo.
    config2 = EngineConfig()
    _arm_delegation(config2, Task.new(str(work), "x"))
    assert config2.reasoning_repo_path == str(work)
