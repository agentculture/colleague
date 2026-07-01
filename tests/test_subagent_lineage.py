"""Structural goal/acceptance threading + parent task_id lineage (spec R6 / plan
t16 / #259).

Covers:
(b) ``run_subagent(..., parent_task_id="p1")`` records it on the returned
    ``SubResult.parent``; omitting it stays ``None`` (byte-identical to before).
(c) A batch item carrying ``"goal"``/``"acceptance"`` produces a child ``Task``
    with them set (a task-capturing engine records the ``Task`` passed to
    ``engine.work``).
(e) Items WITHOUT the new keys build a byte-identical goal-less child ``Task``.

Also verifies the grandchild-lineage rule: a nested (depth+1) spawn records
ITS immediate parent (the depth-1 child), never the top-level root — the
walkable-one-hop-at-a-time design named in ``SubResult.parent``'s docstring.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from colleague.config import EngineConfig
from colleague.contract import OK, Task, Usage
from colleague.subagents import make_batch_spawn, make_spawn, run_subagent


def _fake_taskresult(task_id: str = "t"):
    return SimpleNamespace(
        task_id=task_id, status=OK, summary="ok", changed_files=[], usage=Usage()
    )


class _TaskCapturingEngine:
    """Records every ``Task`` handed to ``work()`` (no real model, no git)."""

    def __init__(self) -> None:
        self.tasks: list[Task] = []

    def work(self, task: Task, config) -> SimpleNamespace:
        self.tasks.append(task)
        return _fake_taskresult(task.id)


class _NestingEngine:
    """Delegates exactly ONE nested child on the FIRST call, recording the
    nested SubResult so a test can inspect its ``.parent`` (grandchild lineage)."""

    def __init__(self) -> None:
        self.calls = 0
        self.nested = None

    def work(self, task: Task, config) -> SimpleNamespace:
        self.calls += 1
        if config.subagent_spawn is not None and self.calls == 1:
            self.nested = config.subagent_spawn("grandchild task")
        return _fake_taskresult(task.id)


@pytest.fixture
def patch_engine(monkeypatch):
    def _install(engine):
        monkeypatch.setattr("colleague.subagents.registry.load", lambda name: engine)
        return engine

    return _install


# ---------------------------------------------------------------------------
# (b) run_subagent(parent_task_id=...) -> SubResult.parent
# ---------------------------------------------------------------------------


def test_run_subagent_parent_task_id_sets_sub_result_parent(tmp_path, patch_engine):
    patch_engine(_TaskCapturingEngine())
    sub = run_subagent(
        "x",
        repo_path=str(tmp_path),
        parent_config=EngineConfig(),
        parent_engine="mock",
        depth=1,
        parent_task_id="p1",
    )
    assert sub.parent == "p1"


def test_run_subagent_without_parent_task_id_is_none(tmp_path, patch_engine):
    patch_engine(_TaskCapturingEngine())
    sub = run_subagent(
        "x",
        repo_path=str(tmp_path),
        parent_config=EngineConfig(),
        parent_engine="mock",
        depth=1,
    )
    assert sub.parent is None
    assert "parent" not in sub.to_dict()


def test_make_spawn_binds_parent_task_id_for_every_child(tmp_path, patch_engine):
    patch_engine(_TaskCapturingEngine())
    spawn = make_spawn(str(tmp_path), EngineConfig(), "mock", parent_task_id="root-task")
    first = spawn("a")
    second = spawn("b")
    assert first.parent == "root-task"
    assert second.parent == "root-task"


def test_nested_child_records_immediate_parent_not_root(tmp_path, patch_engine):
    """A grandchild's SubResult.parent names its IMMEDIATE parent (the depth-1
    child), not the top-level root — the tree is walkable one hop at a time."""
    engine = _NestingEngine()
    patch_engine(engine)
    spawn = make_spawn(str(tmp_path), EngineConfig(), "mock", parent_task_id="root-task")
    top_result = spawn("root instruction")

    assert top_result.parent == "root-task"
    assert engine.nested is not None
    # The grandchild's parent is the FIRST child's own task id, not "root-task".
    assert engine.nested.parent == top_result.task_id
    assert engine.nested.parent != "root-task"


# ---------------------------------------------------------------------------
# (c) / (e) goal/acceptance thread onto the child Task (or stay None)
# ---------------------------------------------------------------------------


def test_run_subagent_builds_child_task_with_goal_and_acceptance(tmp_path, patch_engine):
    engine = _TaskCapturingEngine()
    patch_engine(engine)
    run_subagent(
        "do the thing",
        repo_path=str(tmp_path),
        parent_config=EngineConfig(),
        parent_engine="mock",
        depth=1,
        goal="ship it",
        acceptance=["a flaky call retries", "a permanent error does not"],
    )
    assert len(engine.tasks) == 1
    assert engine.tasks[0].goal == "ship it"
    assert engine.tasks[0].acceptance == [
        "a flaky call retries",
        "a permanent error does not",
    ]


def test_run_subagent_without_goal_or_acceptance_is_byte_identical(tmp_path, patch_engine):
    engine = _TaskCapturingEngine()
    patch_engine(engine)
    run_subagent(
        "do the thing",
        repo_path=str(tmp_path),
        parent_config=EngineConfig(),
        parent_engine="mock",
        depth=1,
    )
    assert engine.tasks[0].goal is None
    assert engine.tasks[0].acceptance is None
    assert "goal" not in engine.tasks[0].to_dict()
    assert "acceptance" not in engine.tasks[0].to_dict()


# ---------------------------------------------------------------------------
# Batch path: goal/acceptance/parent_task_id round-trip through a real worktree
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    )


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    """A minimal git repo with one commit (needed for 'git worktree add')."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@colleague.test")
    _git(repo, "config", "user.name", "Colleague Test")
    (repo / "README.md").write_text("# test repo\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "initial commit")
    return repo


def test_batch_item_goal_and_acceptance_reach_the_child_task(git_repo, patch_engine):
    engine = _TaskCapturingEngine()
    patch_engine(engine)
    batch = make_batch_spawn(
        str(git_repo), EngineConfig(model="X"), "mock", parent_task_id="parent-1"
    )
    items = [
        {
            "instruction": "do the thing",
            "goal": "the thing is done",
            "acceptance": ["it works", "it is fast"],
        }
    ]
    results = batch(items)

    # One child + one merge child.
    assert len(results) == 2
    child = results[0]
    assert child.parent == "parent-1"
    assert len(engine.tasks) == 1
    assert engine.tasks[0].goal == "the thing is done"
    assert engine.tasks[0].acceptance == ["it works", "it is fast"]

    # The merge child also carries the batch's parent_task_id (consistency).
    merge_child = results[-1]
    assert merge_child.parent == "parent-1"


def test_batch_item_without_goal_or_acceptance_builds_bare_child_task(git_repo, patch_engine):
    """(e) Items without the new keys are byte-identical: a goal-less child Task."""
    engine = _TaskCapturingEngine()
    patch_engine(engine)
    batch = make_batch_spawn(str(git_repo), EngineConfig(model="X"), "mock")
    items = [{"instruction": "do the thing"}]
    results = batch(items)

    assert len(engine.tasks) == 1
    assert engine.tasks[0].goal is None
    assert engine.tasks[0].acceptance is None
    assert results[0].parent is None
    assert results[-1].parent is None  # merge child too
