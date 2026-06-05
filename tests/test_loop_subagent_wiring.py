"""The integration seam (t6): subagent delegation wired end to end.

These tests guard the wiring that connects the already-merged pieces — the
subagent launcher (:func:`colleague.subagents.make_spawn`/``run_subagent``), the
tool executor's injected ``spawn`` callback, the ``subagent`` tool schema, and the
``TaskResult.sub_results`` field — into the live drive path.

The wiring under test:

1. ``loop.run`` accepts a keyword-only ``spawn`` callback, injects it into the
   ``ToolExecutor``, and snapshots ``executor.sub_results`` onto
   ``result.sub_results`` on EVERY exit path (the single place ``changed_files``
   is set).
2. Both bundled engines forward ``config.subagent_spawn`` to ``run(...)`` (the
   all-engines rule).
3. ``_DEFAULT_SYSTEM`` advertises the ``subagent`` tool as OPTIONAL / engine-judged
   (parallel to the destination paragraph).
4. A drive that never delegates yields ``sub_results == []`` and a ``to_dict()``
   with NO ``"sub_results"`` key (byte-identical to the pre-feature shape).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from colleague import registry
from colleague.config import EngineConfig
from colleague.contract import OK, Task
from colleague.loop import _DEFAULT_SYSTEM, ModelResponse, Spawns, ToolCall, run
from colleague.subagents import make_spawn


def _script(turns: list[ModelResponse]):
    """A deterministic ``complete`` that replays ``turns`` then repeats the last."""
    state = {"i": 0}

    def complete(_messages: list[dict]) -> ModelResponse:
        turn = turns[min(state["i"], len(turns) - 1)]
        state["i"] += 1
        return turn

    return complete


# --- AC1: a drive that delegates records one sub_result + merges child files ---


def test_subagent_call_records_sub_result_and_merges_changed_files(tmp_path: Path) -> None:
    """A drive whose scripted model emits a ``subagent`` tool call records ONE
    entry in ``result.sub_results``, and the file the child wrote shows up in the
    parent's ``changed_files`` (merged for the single top-level handoff).

    The child runs the REAL ``mock`` engine through ``make_spawn``/``run_subagent``
    — the mock engine deterministically writes ``colleague-mock.md`` and finishes,
    so its changed file is the assertion target.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    config = EngineConfig.resolve()
    task = Task.new(str(repo), "delegate something", engine="mock")

    # The top-level spawn callback, exactly as execute_work builds it.
    spawn = make_spawn(str(repo), config, "mock")

    # Scripted parent: delegate once via the subagent tool, then finish.
    complete = _script(
        [
            ModelResponse(
                tool_calls=[
                    ToolCall(
                        "p-1",
                        "subagent",
                        {"instruction": "write the marker file", "engine": "mock"},
                    )
                ],
                prompt_tokens=1,
                completion_tokens=1,
            ),
            ModelResponse(
                tool_calls=[ToolCall("p-2", "finish", {"summary": "delegated then done"})],
                prompt_tokens=1,
                completion_tokens=1,
            ),
        ]
    )

    result = run(complete, task, max_steps=10, spawns=Spawns(single=spawn))

    assert result.status == OK
    # Exactly one nested child was recorded.
    assert len(result.sub_results) == 1
    sub = result.sub_results[0]
    assert sub.engine == "mock"
    assert sub.status == OK
    # The mock child writes colleague-mock.md — it must be merged into the parent.
    from colleague.engines.mock import OUTPUT_FILE

    assert OUTPUT_FILE in sub.changed_files
    assert OUTPUT_FILE in result.changed_files
    # And the serialized artifact carries the nested result.
    serialized = result.to_dict()
    assert "sub_results" in serialized
    assert len(serialized["sub_results"]) == 1


def test_subagent_sub_results_surface_through_mock_engine_drive(tmp_path: Path) -> None:
    """End to end via ``MockEngine.drive`` with ``config.subagent_spawn`` set:
    a scripted mock engine that delegates surfaces the child on the parent result.

    This exercises the engine-forwarding wiring (``spawn=config.subagent_spawn``)
    rather than calling ``run`` directly — the mock engine must thread the callback
    from config into the loop.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    config = EngineConfig.resolve()
    config.subagent_spawn = make_spawn(str(repo), config, "mock")

    # Override the mock engine's script to delegate first, then finish.
    from colleague.engines import mock as mock_mod

    def _delegating_script(_task):
        return _script(
            [
                ModelResponse(
                    tool_calls=[
                        ToolCall(
                            "m-1",
                            "subagent",
                            {"instruction": "do the mechanical bit", "engine": "mock"},
                        )
                    ],
                    prompt_tokens=1,
                    completion_tokens=1,
                ),
                ModelResponse(
                    tool_calls=[ToolCall("m-2", "finish", {"summary": "parent done"})],
                    prompt_tokens=1,
                    completion_tokens=1,
                ),
            ]
        )

    import unittest.mock as umock

    with umock.patch.object(mock_mod, "_script", _delegating_script):
        result = registry.load("mock").work(task=Task.new(str(repo), "parent task"), config=config)

    assert result.status == OK
    assert len(result.sub_results) == 1
    assert result.sub_results[0].engine == "mock"


# --- AC2: the system prompt advertises the subagent tool as OPTIONAL ---


def test_default_system_advertises_subagent_as_optional() -> None:
    """``_DEFAULT_SYSTEM`` mentions the subagent tool and frames it as optional /
    engine-judged, parallel to the destination paragraph."""
    lower = _DEFAULT_SYSTEM.lower()
    assert "subagent" in lower, "_DEFAULT_SYSTEM must mention the subagent tool"
    assert "optional" in lower, "_DEFAULT_SYSTEM must frame the subagent tool as optional"
    # The plural batch tool and its parallel nature must be named too (#122): the
    # prompt previously described only the singular tool, which left the live model
    # unaware the parallel `subagents` tool exists.
    assert "subagents" in lower, "_DEFAULT_SYSTEM must mention the plural subagents tool"
    assert "parallel" in lower, "_DEFAULT_SYSTEM must describe parallel batch delegation"
    # The destination guidance is untouched (the new paragraph is additive).
    assert "destination" in lower
    assert "announcement" in lower
    # Base guidance remains.
    assert "coding agent" in lower
    assert "finish" in lower


# --- AC3: both engines forward config.subagent_spawn to run(...) ---


@pytest.mark.parametrize(
    "engine_source",
    [
        "colleague/engines/mock.py",
        "colleague/engines/vllm_openai.py",
    ],
)
def test_both_engines_forward_subagent_spawn(engine_source: str) -> None:
    """The all-engines rule: both bundled engines must forward
    ``spawn=config.subagent_spawn`` into ``run(...)``.

    Asserted by reading the engine source — the cheapest honest guard that the
    callback is threaded identically in both engines (mirrors how the task spec
    frames the all-engines parity)."""
    root = Path(__file__).resolve().parent.parent
    text = (root / engine_source).read_text(encoding="utf-8")
    assert (
        "spawn=config.subagent_spawn" in text
    ), f"{engine_source} must forward spawn=config.subagent_spawn to run(...)"


# --- AC4: no-subagent drive omits the sub_results key (byte-identical) ---


def test_no_subagent_drive_omits_sub_results_key(tmp_path: Path) -> None:
    """A drive that NEVER calls the subagent tool yields ``sub_results == []`` and
    a ``to_dict()`` with NO ``"sub_results"`` key — byte-identical to today's
    no-subagent shape."""
    repo = tmp_path / "repo"
    repo.mkdir()
    config = EngineConfig.resolve()

    # A plain mock drive (no spawn injected) never delegates.
    result = registry.load("mock").work(Task.new(str(repo), "do work"), config)

    assert result.status == OK
    assert result.changed_files  # the drive really ran
    assert result.sub_results == []
    serialized = result.to_dict()
    assert "sub_results" not in serialized
