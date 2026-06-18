"""Typed-subagent role threading + the global agent budget (#t4).

Covers:
- make_spawn / make_batch_spawn / run_subagent accept an optional role + a shared
  global counter; the child is launched at depth+1 carrying the role; the counter
  increments per spawned agent (and omitting them is byte-identical to before).
- A spawn is refused BEFORE any child work (SubagentError, no engine.work call)
  when depth > MAX_SUBAGENT_DEPTH OR the global agent count would exceed the cap.
- Nested batches are now permitted, but every child counts against the single
  global budget: a deep, wide nesting never spawns more than the cap.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from colleague.config import MAX_SUBAGENT_DEPTH, MAX_SUBAGENT_TOTAL, EngineConfig
from colleague.contract import OK, Task, Usage
from colleague.subagents import (
    SubagentError,
    _AgentBudget,
    make_batch_spawn,
    make_spawn,
    run_subagent,
)


def _fake_taskresult():
    return SimpleNamespace(task_id="t", status=OK, summary="ok", changed_files=[], usage=Usage())


class _SpawningEngine:
    """An engine whose ``work()`` records its config and fans out ``fanout``
    children via ``config.subagent_spawn`` (catching refusals), so a test can drive
    deep/wide nesting deterministically without a real model or git."""

    def __init__(self, recorder: list, fanout: int = 0) -> None:
        self.recorder = recorder
        self.fanout = fanout

    def work(self, task, config):
        self.recorder.append(config)
        if config.subagent_spawn is not None and self.fanout:
            for i in range(self.fanout):
                try:
                    config.subagent_spawn(f"{task.instruction}.{i}")
                except SubagentError:
                    pass  # refused (depth/budget) — bounded, expected
        return _fake_taskresult()


@pytest.fixture
def patch_engine(monkeypatch):
    def _install(engine):
        monkeypatch.setattr("colleague.subagents.registry.load", lambda name: engine)
        return engine

    return _install


# --- AC1: role + counter thread through; depth+1 binding; counter increments ---


def test_role_threads_to_child_config(tmp_path, patch_engine):
    recorder: list = []
    patch_engine(_SpawningEngine(recorder))
    spawn = make_spawn(str(tmp_path), EngineConfig(), "mock")
    spawn("task", role="explorer")
    assert recorder[0].role == "explorer"


def test_omitting_role_is_none(tmp_path, patch_engine):
    recorder: list = []
    patch_engine(_SpawningEngine(recorder))
    spawn = make_spawn(str(tmp_path), EngineConfig(), "mock")
    spawn("task")
    assert recorder[0].role is None


def test_counter_increments_per_spawn(tmp_path, patch_engine):
    recorder: list = []
    patch_engine(_SpawningEngine(recorder))
    budget = _AgentBudget(limit=10)
    spawn = make_spawn(str(tmp_path), EngineConfig(), "mock", counter=budget)
    spawn("a")
    spawn("b")
    spawn("c")
    assert budget.count == 3


def test_linear_nesting_bounded_by_depth_cap(tmp_path, patch_engine):
    # fanout=1 → a linear chain; the child's spawn is bound to depth+1, so the
    # depth cap stops the chain at exactly MAX_SUBAGENT_DEPTH levels (no budget).
    recorder: list = []
    patch_engine(_SpawningEngine(recorder, fanout=1))
    spawn = make_spawn(str(tmp_path), EngineConfig(), "mock")
    spawn("root")
    assert len(recorder) == MAX_SUBAGENT_DEPTH


# --- AC2: refused BEFORE any work, on depth OR global budget ---


def test_depth_cap_refuses_before_work(tmp_path, patch_engine):
    recorder: list = []
    patch_engine(_SpawningEngine(recorder))
    with pytest.raises(SubagentError):
        run_subagent(
            "x",
            repo_path=str(tmp_path),
            parent_config=EngineConfig(),
            parent_engine="mock",
            depth=MAX_SUBAGENT_DEPTH + 1,
        )
    assert recorder == []  # engine.work never called — zero work on refusal


def test_budget_cap_refuses_before_work(tmp_path, patch_engine):
    recorder: list = []
    patch_engine(_SpawningEngine(recorder))
    budget = _AgentBudget(limit=2)
    spawn = make_spawn(str(tmp_path), EngineConfig(), "mock", counter=budget)
    spawn("a")
    spawn("b")
    with pytest.raises(SubagentError):
        spawn("c")  # 3rd exceeds the limit of 2
    assert len(recorder) == 2  # only 2 ran; the 3rd was refused before work
    assert budget.count == 2  # count never exceeds the cap


# --- AC3: nested batches permitted; deep+wide nesting bounded by the global cap ---


def test_child_config_has_nested_batch_spawn(tmp_path, patch_engine):
    recorder: list = []
    patch_engine(_SpawningEngine(recorder))
    spawn = make_spawn(str(tmp_path), EngineConfig(), "mock")
    spawn("root")
    # The ban is lifted: a child can nest batches.
    assert recorder[0].subagent_batch_spawn is not None


def test_deep_wide_nesting_bounded_by_global_cap(tmp_path, patch_engine):
    # Each agent fans out 3; a depth-4 fanout-3 tree has 40 nodes — far more than
    # the budget. The global cap bounds the TOTAL agents that actually run.
    recorder: list = []
    patch_engine(_SpawningEngine(recorder, fanout=3))
    budget = _AgentBudget(limit=5)
    spawn = make_spawn(str(tmp_path), EngineConfig(), "mock", counter=budget)
    spawn("root")
    assert budget.count == 5  # fills exactly to the cap
    assert len(recorder) == budget.count  # every run() charged exactly once
    assert len(recorder) <= 5


def test_default_budget_limit_is_max_subagent_total(tmp_path, patch_engine):
    assert _AgentBudget().limit == MAX_SUBAGENT_TOTAL == 24
    recorder: list = []
    patch_engine(_SpawningEngine(recorder, fanout=10))
    budget = _AgentBudget()
    spawn = make_spawn(str(tmp_path), EngineConfig(), "mock", counter=budget)
    spawn("root")
    assert budget.count <= 24
    assert len(recorder) <= 24


def test_batch_budget_precheck_refuses_oversized_batch(tmp_path, patch_engine):
    # A batch that cannot fit the remaining budget is refused BEFORE any worktree
    # is created (the pre-check), so nothing runs.
    recorder: list = []
    patch_engine(_SpawningEngine(recorder))
    budget = _AgentBudget(limit=2)
    batch = make_batch_spawn(str(tmp_path), EngineConfig(), "mock", counter=budget)
    items = [{"instruction": f"t{i}"} for i in range(3)]  # 3 > 2 remaining
    with pytest.raises(SubagentError):
        batch(items)
    assert recorder == []  # refused before any child work / worktree
    assert budget.count == 0


def test_execute_work_wires_a_shared_agent_budget(tmp_path, monkeypatch):
    """Regression (#t4 Q3): the production wiring (execute_work) must create ONE
    _AgentBudget and pass it as ``counter=`` to BOTH make_spawn AND make_batch_spawn,
    so the global MAX_SUBAGENT_TOTAL cap is actually enforced — not a silent no-op.
    (t11 tested the counter directly; nothing tested the production wiring.)"""
    import subprocess as _sp

    from colleague.cli._commands import work as work_mod
    from colleague.subagents import _AgentBudget

    repo = tmp_path / "repo"
    repo.mkdir()

    def _git(*a):
        _sp.run(["git", "-C", str(repo), *a], check=True, capture_output=True)

    _git("init", "-q")
    _git("config", "user.email", "t@t.test")
    _git("config", "user.name", "T")
    (repo / "README.md").write_text("seed\n")
    _git("add", "-A")
    _git("commit", "-q", "-m", "init")

    captured: dict = {}
    real_spawn, real_batch = work_mod.make_spawn, work_mod.make_batch_spawn

    def cap_spawn(*a, **kw):
        captured["spawn_counter"] = kw.get("counter")
        return real_spawn(*a, **kw)

    def cap_batch(*a, **kw):
        captured["batch_counter"] = kw.get("counter")
        return real_batch(*a, **kw)

    monkeypatch.setattr(work_mod, "make_spawn", cap_spawn)
    monkeypatch.setattr(work_mod, "make_batch_spawn", cap_batch)

    task = Task.new(str(repo), "do the mock task", engine="mock")
    work_mod.execute_work(
        repo=repo,
        engine_name="mock",
        task=task,
        open_pr=False,
        base="main",
        config=EngineConfig.resolve(),
    )

    sc, bc = captured.get("spawn_counter"), captured.get("batch_counter")
    assert sc is not None, "make_spawn got no agent budget — the global cap is a no-op"
    assert bc is not None, "make_batch_spawn got no agent budget"
    assert sc is bc, "single + batch delegation must SHARE one budget"
    assert isinstance(sc, _AgentBudget)
    assert sc.limit == EngineConfig.resolve().subagent_total
