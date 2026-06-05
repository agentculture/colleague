"""The integration seam (t5): batch-spawn wired end to end.

These tests guard the wiring that connects the already-merged pieces —
:func:`colleague.subagents.make_batch_spawn`, the tool executor's injected
``batch_spawn`` callback, and the ``subagents`` (plural) tool schema — into the
live drive path.

The wiring under test:

1. ``loop.run`` accepts a keyword-only ``batch_spawn`` callback, injects it into
   the ``ToolExecutor``, and the executor's ``_batch_spawn`` is the exact object
   passed in.
2. Both bundled engines forward ``config.subagent_batch_spawn`` to ``run(...)``
   (the all-engines rule): for each engine, when
   ``EngineConfig.subagent_batch_spawn`` is set the engine passes it through so
   the executor's ``_batch_spawn`` is non-None.
3. The existing single-child ``spawn`` wiring is unchanged (still passes).
"""

from __future__ import annotations

from pathlib import Path
from unittest import mock as umock

import pytest

from colleague import registry
from colleague.config import EngineConfig
from colleague.contract import OK, Task
from colleague.loop import ModelResponse, Spawns, ToolCall, run
from colleague.tools import ToolExecutor

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _script(turns: list[ModelResponse]):
    """A deterministic ``complete`` that replays ``turns`` then repeats the last."""
    state = {"i": 0}

    def complete(_messages: list[dict]) -> ModelResponse:
        turn = turns[min(state["i"], len(turns) - 1)]
        state["i"] += 1
        return turn

    return complete


def _finish_complete(_messages):
    """A complete function that immediately calls finish."""
    return ModelResponse(
        tool_calls=[ToolCall("x-1", "finish", {"summary": "done"})],
        prompt_tokens=1,
        completion_tokens=1,
    )


# ---------------------------------------------------------------------------
# AC1: loop.run accepts batch_spawn and injects it into the ToolExecutor
# ---------------------------------------------------------------------------


def test_run_injects_batch_spawn_into_executor(tmp_path: Path) -> None:
    """``loop.run(...)`` accepts a ``batch_spawn`` kwarg and injects it into the
    ``ToolExecutor`` — the executor's ``_batch_spawn`` is the exact sentinel passed
    in."""
    repo = tmp_path / "repo"
    repo.mkdir()

    task = Task.new(str(repo), "test batch wiring", engine="mock")
    sentinel = object()

    captured_executors = []

    original_init = ToolExecutor.__init__

    def patched_init(self, root, *, spawn=None, batch_spawn=None, max_output_chars=100000):
        original_init(
            self, root, spawn=spawn, batch_spawn=batch_spawn, max_output_chars=max_output_chars
        )
        captured_executors.append(self)

    with umock.patch.object(ToolExecutor, "__init__", patched_init):
        result = run(_finish_complete, task, max_steps=10, spawns=Spawns(batch=sentinel))

    assert result.status == OK
    # At least one ToolExecutor was constructed; the one the loop built must carry
    # the sentinel as its _batch_spawn.
    assert any(
        ex._batch_spawn is sentinel for ex in captured_executors
    ), "None of the ToolExecutors created during run() had the sentinel batch_spawn"


# ---------------------------------------------------------------------------
# AC2: both engines forward config.subagent_batch_spawn to run(...)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "engine_source",
    [
        "colleague/engines/mock.py",
        "colleague/engines/vllm_openai.py",
    ],
)
def test_both_engines_forward_subagent_batch_spawn(engine_source: str) -> None:
    """The all-engines rule: both bundled engines must forward
    ``batch_spawn=config.subagent_batch_spawn`` into ``run(...)`` or into the
    ``ToolExecutor`` constructor.

    Asserted by reading the engine source — the cheapest honest guard that the
    callback is threaded identically in both engines (mirrors the existing
    subagent_spawn wiring test in test_loop_subagent_wiring.py)."""
    root = Path(__file__).resolve().parent.parent
    text = (root / engine_source).read_text(encoding="utf-8")
    assert (
        "batch_spawn=config.subagent_batch_spawn" in text
    ), f"{engine_source} must forward batch_spawn=config.subagent_batch_spawn to run(...)"


def test_mock_engine_batch_spawn_reaches_executor(tmp_path: Path) -> None:
    """End-to-end via ``MockEngine.drive`` with ``config.subagent_batch_spawn`` set:
    the executor built inside the engine carries a non-None ``_batch_spawn``.

    This exercises the engine-forwarding wiring without spinning up a real vLLM
    server — we just check that the executor was given the callback."""
    repo = tmp_path / "repo"
    repo.mkdir()

    config = EngineConfig.resolve()
    sentinel = object()
    config.subagent_batch_spawn = sentinel

    captured_executors = []
    original_init = ToolExecutor.__init__

    def patched_init(self, root, *, spawn=None, batch_spawn=None, max_output_chars=100000):
        original_init(
            self, root, spawn=spawn, batch_spawn=batch_spawn, max_output_chars=max_output_chars
        )
        captured_executors.append(self)

    with umock.patch.object(ToolExecutor, "__init__", patched_init):
        result = registry.load("mock").work(
            task=Task.new(str(repo), "batch wiring mock"), config=config
        )

    assert result.status == OK
    assert any(
        ex._batch_spawn is sentinel for ex in captured_executors
    ), "MockEngine did not forward subagent_batch_spawn to the ToolExecutor"


def test_vllm_engine_batch_spawn_reaches_executor(tmp_path: Path) -> None:
    """Check vllm_openai engine source directly: the engine constructs its
    ToolExecutor with ``batch_spawn=config.subagent_batch_spawn`` (source-level
    guard that requires no live server)."""
    root = Path(__file__).resolve().parent.parent
    text = (root / "colleague/engines/vllm_openai.py").read_text(encoding="utf-8")
    assert "batch_spawn=config.subagent_batch_spawn" in text, (
        "vllm_openai engine must pass batch_spawn=config.subagent_batch_spawn "
        "to the ToolExecutor"
    )


# ---------------------------------------------------------------------------
# AC3: the existing single-child spawn wiring is unchanged
# ---------------------------------------------------------------------------


def test_single_spawn_wiring_unchanged(tmp_path: Path) -> None:
    """The existing single-child wiring still works after batch wiring is added —
    a ``loop.run(..., spawns=Spawns(single=<sentinel>))`` injects it into the
    executor's ``_spawn``."""
    repo = tmp_path / "repo"
    repo.mkdir()

    task = Task.new(str(repo), "spawn unchanged check", engine="mock")
    spawn_sentinel = object()

    captured_executors = []
    original_init = ToolExecutor.__init__

    def patched_init(self, root, *, spawn=None, batch_spawn=None, max_output_chars=100000):
        original_init(
            self, root, spawn=spawn, batch_spawn=batch_spawn, max_output_chars=max_output_chars
        )
        captured_executors.append(self)

    with umock.patch.object(ToolExecutor, "__init__", patched_init):
        result = run(_finish_complete, task, max_steps=10, spawns=Spawns(single=spawn_sentinel))

    assert result.status == OK
    assert any(
        ex._spawn is spawn_sentinel for ex in captured_executors
    ), "Existing spawn= wiring was broken — executor did not receive spawn sentinel"


def test_both_spawn_and_batch_spawn_injected_together(tmp_path: Path) -> None:
    """When both ``spawn`` and ``batch_spawn`` are given to ``loop.run(...)``,
    both are injected into the same executor."""
    repo = tmp_path / "repo"
    repo.mkdir()

    task = Task.new(str(repo), "both spawn and batch_spawn", engine="mock")
    spawn_sentinel = object()
    batch_sentinel = object()

    captured_executors = []
    original_init = ToolExecutor.__init__

    def patched_init(self, root, *, spawn=None, batch_spawn=None, max_output_chars=100000):
        original_init(
            self, root, spawn=spawn, batch_spawn=batch_spawn, max_output_chars=max_output_chars
        )
        captured_executors.append(self)

    with umock.patch.object(ToolExecutor, "__init__", patched_init):
        result = run(
            _finish_complete,
            task,
            max_steps=10,
            spawns=Spawns(single=spawn_sentinel, batch=batch_sentinel),
        )

    assert result.status == OK
    combined = [
        ex
        for ex in captured_executors
        if ex._spawn is spawn_sentinel and ex._batch_spawn is batch_sentinel
    ]
    assert combined, "No executor had BOTH spawn and batch_spawn set simultaneously"


# ---------------------------------------------------------------------------
# AC4: EngineConfig.subagent_batch_spawn field defaults to None
# ---------------------------------------------------------------------------


def test_subagent_batch_spawn_defaults_to_none() -> None:
    """EngineConfig.subagent_batch_spawn defaults to None."""
    cfg = EngineConfig.resolve()
    assert cfg.subagent_batch_spawn is None


def test_subagent_batch_spawn_excluded_from_eq() -> None:
    """Two configs that differ only in subagent_batch_spawn are equal (compare=False)."""
    cfg1 = EngineConfig.resolve()
    cfg2 = EngineConfig.resolve()
    cfg2.subagent_batch_spawn = lambda items: []
    assert cfg1 == cfg2


def test_subagent_batch_spawn_excluded_from_repr() -> None:
    """repr() does not mention subagent_batch_spawn (repr=False)."""
    cfg = EngineConfig.resolve()
    cfg.subagent_batch_spawn = lambda items: []
    assert "subagent_batch_spawn" not in repr(cfg)


def test_subagent_batch_spawn_excluded_from_to_dict() -> None:
    """subagent_batch_spawn does not appear in to_dict() output."""
    cfg = EngineConfig.resolve()
    cfg.subagent_batch_spawn = lambda items: []
    assert "subagent_batch_spawn" not in cfg.to_dict()
