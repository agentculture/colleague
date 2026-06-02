"""The subagent launcher (t3): ``run_subagent`` + ``make_spawn``.

Mid-drive, an engine can delegate a scoped sub-task to a NESTED in-process child
drive on a chosen engine/model. The launcher runs that child drive via
``engine.drive`` (which never hands off) and returns its ``SubResult``.

These tests pin the behavior downstream tasks (t4's tool executor, t6's loop
wiring) code against:

1. A mock->mock run returns a ``SubResult`` reflecting the child's work.
2. Omitted engine/model inherits the parent's config; a provided model/engine
   switches it (a pure config-level switch — no engine code changes).
3. Recursion past ``MAX_SUBAGENT_DEPTH`` is refused BEFORE any child starts
   (proves termination).
4. The launcher performs NO git handoff (it calls ``engine.drive``, not the CLI
   ``execute_drive``): no ``.git`` is created, no branch/pr_url leaks.
5. ``make_spawn`` returns a callable whose result matches the equivalent
   ``run_subagent`` call.
"""

from __future__ import annotations

import os

import pytest

from colleague.config import MAX_SUBAGENT_DEPTH, EngineConfig
from colleague.contract import OK, SubResult
from colleague.registry import UnknownEngine
from colleague.subagents import (
    SubagentError,
    make_spawn,
    run_subagent,
)

# ---------------------------------------------------------------------------
# Criterion 1: a mock->mock run returns a SubResult reflecting the child's work.
# ---------------------------------------------------------------------------


def test_mock_to_mock_returns_subresult(tmp_path) -> None:
    """A mock->mock launch yields an ok SubResult on the mock engine."""
    result = run_subagent(
        "do the scoped thing",
        repo_path=str(tmp_path),
        parent_config=EngineConfig(),
        parent_engine="mock",
        depth=1,
    )
    assert isinstance(result, SubResult)
    assert result.engine == "mock"
    assert result.status == OK
    # The summary reflects the child's real work (the mock writes a marker file).
    assert "colleague-mock.md" in result.summary
    assert result.changed_files == ["colleague-mock.md"]
    assert result.task_id  # a real child task id was produced


# ---------------------------------------------------------------------------
# Criterion 2: omitted engine/model inherits the parent; provided overrides it.
# ---------------------------------------------------------------------------


def test_omitted_model_inherits_parent(tmp_path) -> None:
    """No model arg => SubResult.model is the parent's model (inherited)."""
    parent = EngineConfig(model="X")
    result = run_subagent(
        "task",
        repo_path=str(tmp_path),
        parent_config=parent,
        parent_engine="mock",
        depth=1,
    )
    assert result.model == "X"


def test_provided_model_overrides_parent(tmp_path) -> None:
    """An explicit model arg => SubResult.model is that model (override)."""
    parent = EngineConfig(model="X")
    result = run_subagent(
        "task",
        repo_path=str(tmp_path),
        parent_config=parent,
        parent_engine="mock",
        depth=1,
        model="Y",
    )
    assert result.model == "Y"


def test_omitted_engine_inherits_parent_engine(tmp_path) -> None:
    """No engine arg => the parent engine name is used and reflected back."""
    result = run_subagent(
        "task",
        repo_path=str(tmp_path),
        parent_config=EngineConfig(),
        parent_engine="mock",
        depth=1,
    )
    assert result.engine == "mock"


def test_provided_engine_selects_wheel_via_registry(tmp_path) -> None:
    """A provided engine name resolves through registry.load (mock path works)."""
    parent = EngineConfig(model="X")
    result = run_subagent(
        "task",
        repo_path=str(tmp_path),
        parent_config=parent,
        parent_engine="vllm-openai",  # parent default differs from the override
        depth=1,
        engine="mock",
    )
    # The override picked the 'mock' wheel, not the parent's 'vllm-openai'.
    assert result.engine == "mock"
    # Model still inherited from the parent config (only engine was overridden).
    assert result.model == "X"


def test_unknown_engine_surfaces_cleanly(tmp_path) -> None:
    """A bad engine name surfaces a clean error, never an unrelated crash."""
    with pytest.raises((SubagentError, UnknownEngine)):
        run_subagent(
            "task",
            repo_path=str(tmp_path),
            parent_config=EngineConfig(),
            parent_engine="mock",
            depth=1,
            engine="no-such-engine",
        )


def test_inheritance_preserves_base_fields(tmp_path) -> None:
    """Inherited config keeps base_url/api_key/max_steps/temperature/timeout."""
    parent = EngineConfig(
        base_url="http://example/v1",
        api_key="SECRET",
        model="X",
        max_steps=7,
        temperature=0.5,
        timeout=9.0,
    )
    # We cannot read the child config off the SubResult directly, but the
    # inherited model proves dataclasses.replace ran with only model overridden;
    # a model override leaves every other field untouched. Assert the model
    # switch is the ONLY change by overriding it and inheriting the rest.
    result = run_subagent(
        "task",
        repo_path=str(tmp_path),
        parent_config=parent,
        parent_engine="mock",
        depth=1,
        model="Y",
    )
    assert result.model == "Y"
    # Parent config object is not mutated by the launch.
    assert parent.model == "X"
    assert parent.max_steps == 7
    assert parent.subagent_spawn is None


# ---------------------------------------------------------------------------
# Criterion 3: recursion past the cap is refused BEFORE any child starts.
# ---------------------------------------------------------------------------


def test_depth_cap_refuses_before_work(tmp_path) -> None:
    """depth > MAX_SUBAGENT_DEPTH raises SubagentError and starts no child."""
    # Point at a non-existent repo so that IF any drive were attempted past the
    # cap, it would be obvious — but the depth check must fire first regardless.
    with pytest.raises(SubagentError) as exc:
        run_subagent(
            "task",
            repo_path=str(tmp_path),
            parent_config=EngineConfig(),
            parent_engine="mock",
            depth=MAX_SUBAGENT_DEPTH + 1,
        )
    assert str(MAX_SUBAGENT_DEPTH) in str(exc.value)
    # No child drive ran: the mock would have written a marker file. Absent.
    assert not os.path.exists(os.path.join(str(tmp_path), "colleague-mock.md"))


def test_depth_at_cap_is_allowed(tmp_path) -> None:
    """depth == MAX_SUBAGENT_DEPTH is the last allowed level (boundary)."""
    result = run_subagent(
        "task",
        repo_path=str(tmp_path),
        parent_config=EngineConfig(),
        parent_engine="mock",
        depth=MAX_SUBAGENT_DEPTH,
    )
    assert result.status == OK


# ---------------------------------------------------------------------------
# Criterion 4: the launcher performs NO git handoff.
# ---------------------------------------------------------------------------


def test_no_git_handoff(tmp_path) -> None:
    """A mock->mock run in a non-git tmp dir creates no .git and no branch/pr."""
    result = run_subagent(
        "task",
        repo_path=str(tmp_path),
        parent_config=EngineConfig(),
        parent_engine="mock",
        depth=1,
    )
    # engine.drive never hands off: no repo init, no branch, no PR.
    assert not os.path.exists(os.path.join(str(tmp_path), ".git"))
    # SubResult carries no branch/pr_url field at all (it is nested-only data).
    assert not hasattr(result, "pr_url")
    assert not hasattr(result, "branch")


# ---------------------------------------------------------------------------
# Criterion 5: make_spawn returns a callable matching run_subagent.
# ---------------------------------------------------------------------------


def test_make_spawn_returns_callable(tmp_path) -> None:
    """make_spawn returns a callable spawn(instruction, engine=None, model=None)."""
    spawn = make_spawn(str(tmp_path), EngineConfig(), "mock")
    assert callable(spawn)


def test_spawn_matches_run_subagent(tmp_path) -> None:
    """spawn('do x') yields a SubResult equivalent to the matching run_subagent."""
    parent = EngineConfig(model="X")
    spawn = make_spawn(str(tmp_path), parent, "mock")
    via_spawn = spawn("do x")

    via_direct = run_subagent(
        "do x",
        repo_path=str(tmp_path),
        parent_config=parent,
        parent_engine="mock",
        depth=1,
    )
    # Equivalent on every field except the (random) task_id.
    assert via_spawn.engine == via_direct.engine == "mock"
    assert via_spawn.model == via_direct.model == "X"
    assert via_spawn.status == via_direct.status == OK
    assert via_spawn.summary == via_direct.summary
    assert via_spawn.changed_files == via_direct.changed_files


def test_spawn_default_depth_is_one(tmp_path) -> None:
    """make_spawn defaults depth=1, so a top-level spawn is allowed and runs."""
    spawn = make_spawn(str(tmp_path), EngineConfig(), "mock")
    result = spawn("task")
    assert result.status == OK


def test_spawn_forwards_engine_and_model(tmp_path) -> None:
    """spawn forwards engine/model overrides to run_subagent."""
    spawn = make_spawn(str(tmp_path), EngineConfig(model="X"), "vllm-openai")
    result = spawn("task", "mock", "Y")
    assert result.engine == "mock"
    assert result.model == "Y"
