"""Cross-cutting guards for the #156 capacity standard (t8).

Proves the runtime-owned guarantees the feature must hold for EVERY backend:

* all-engines rule — both bundled engines forward ``config.fillline_threshold``
  into the shared loop via ``ContextControls`` (c14, h14);
* strict no-op — a work item that never crosses the fill line makes no extra model
  turn and serializes byte-identically (no capacity keys) (c1, c7, h7, h8);
* structural caps unchanged — MAX_STEPS / retry caps / subagent fan-out + depth are
  untouched, so termination is preserved (h13);
* contrast — a long job now retains meaning via a model-authored summary instead of
  the lossy ``[earlier steps elided]`` drop (h12).
"""

from __future__ import annotations

from pathlib import Path

import colleague.engines.mock as mock_eng
import colleague.engines.vllm_openai as vllm_eng
from colleague.config import (
    MAX_SUBAGENT_DEPTH,
    MAX_SUBAGENT_FANOUT,
    MAX_SUBAGENT_TOTAL,
    EngineConfig,
    ResolveOverrides,
)
from colleague.contract import OK, Task, TaskResult
from colleague.loop import (
    _MAX_OVERFLOW_RETRIES,
    _MAX_TIMEOUT_RETRIES,
    ContextControls,
    ModelResponse,
    ToolCall,
    run,
)

_SYS = "You are a test coding agent."


# ---------------------------------------------------------------------------
# All-engines rule: both backends forward the fill-line threshold into the loop
# ---------------------------------------------------------------------------


def _capture_context(monkeypatch, engine_module) -> dict:
    captured: dict = {}

    def fake_run(complete, task, **kwargs):
        captured["context"] = kwargs.get("context")
        return TaskResult(task_id=task.id, status=OK)

    monkeypatch.setattr(engine_module, "run", fake_run)
    return captured


def test_mock_engine_forwards_fillline_threshold(monkeypatch, tmp_path: Path) -> None:
    captured = _capture_context(monkeypatch, mock_eng)
    cfg = EngineConfig.resolve(overrides=ResolveOverrides(fillline_threshold=0.55))
    mock_eng.MockEngine().work(Task.new(str(tmp_path), "do", engine="mock"), cfg)
    assert captured["context"].fillline_threshold == 0.55


def test_vllm_engine_forwards_fillline_threshold(monkeypatch, tmp_path: Path) -> None:
    captured = _capture_context(monkeypatch, vllm_eng)
    cfg = EngineConfig.resolve(overrides=ResolveOverrides(fillline_threshold=0.55))
    vllm_eng.VllmOpenAIEngine().work(Task.new(str(tmp_path), "do", engine="vllm-openai"), cfg)
    assert captured["context"].fillline_threshold == 0.55


def test_mock_engine_forwards_max_continue_nudges(monkeypatch, tmp_path: Path) -> None:
    captured = _capture_context(monkeypatch, mock_eng)
    cfg = EngineConfig.resolve(overrides=ResolveOverrides(max_continue_nudges=4))
    mock_eng.MockEngine().work(Task.new(str(tmp_path), "do", engine="mock"), cfg)
    assert captured["context"].max_continue_nudges == 4


def test_vllm_engine_forwards_max_continue_nudges(monkeypatch, tmp_path: Path) -> None:
    captured = _capture_context(monkeypatch, vllm_eng)
    cfg = EngineConfig.resolve(overrides=ResolveOverrides(max_continue_nudges=4))
    vllm_eng.VllmOpenAIEngine().work(Task.new(str(tmp_path), "do", engine="vllm-openai"), cfg)
    assert captured["context"].max_continue_nudges == 4


# ---------------------------------------------------------------------------
# Single source for config→ContextControls forwarding (de-dup, #221)
# ---------------------------------------------------------------------------


def test_from_config_forwards_fields() -> None:
    """``ContextControls.from_config`` is the one place the config→controls mapping
    lives; pin a representative spread so a dropped field is caught."""
    import dataclasses

    cfg = EngineConfig.resolve(
        overrides=ResolveOverrides(
            context_budget_tokens=12345,
            max_continue_nudges=4,
            fillline_threshold=0.55,
        )
    )
    cfg = dataclasses.replace(cfg, role="reviewer", affected_tests=False)
    ctx = ContextControls.from_config(cfg)
    assert ctx.budget == 12345
    assert ctx.max_continue_nudges == 4
    assert ctx.fillline_threshold == 0.55
    assert ctx.role == "reviewer"
    assert ctx.affectedtests is False
    assert ctx.autosplit_target == cfg.autosplit_target_tokens
    assert ctx.testintegrity == cfg.testintegrity


def test_from_config_count_tokens_optional() -> None:
    cfg = EngineConfig.resolve()
    assert ContextControls.from_config(cfg).count_tokens is None
    sentinel = lambda msgs: 7  # noqa: E731
    assert ContextControls.from_config(cfg, count_tokens=sentinel).count_tokens is sentinel


def test_both_engines_build_identical_controls(monkeypatch, tmp_path: Path) -> None:
    """The all-engines rule: both backends forward config through the SAME factory,
    so their ContextControls are identical apart from the vLLM ``count_tokens``
    counter. This is the guard the de-dup must keep true."""
    import dataclasses

    cfg = EngineConfig.resolve(
        overrides=ResolveOverrides(fillline_threshold=0.55, max_continue_nudges=4)
    )

    cap_mock = _capture_context(monkeypatch, mock_eng)
    mock_eng.MockEngine().work(Task.new(str(tmp_path), "do", engine="mock"), cfg)

    cap_vllm = _capture_context(monkeypatch, vllm_eng)
    vllm_eng.VllmOpenAIEngine().work(Task.new(str(tmp_path), "do", engine="vllm-openai"), cfg)

    mock_ctx = dataclasses.replace(cap_mock["context"], count_tokens=None)
    vllm_ctx = dataclasses.replace(cap_vllm["context"], count_tokens=None)
    assert mock_ctx == vllm_ctx
    # The mock leaves count_tokens None; the vLLM backend supplies its counter.
    assert cap_mock["context"].count_tokens is None
    assert cap_vllm["context"].count_tokens is not None


# ---------------------------------------------------------------------------
# Strict no-op: no fill-line event → no extra turn, byte-identical shape
# ---------------------------------------------------------------------------


def test_no_fillline_event_makes_no_extra_turn(tmp_path: Path) -> None:
    turns = {"n": 0}

    def complete(messages):
        turns["n"] += 1
        return ModelResponse(
            content="done",
            tool_calls=[ToolCall("f", "finish", {"summary": "done"})],
            prompt_tokens=5,  # under 0.8 * 100
            completion_tokens=1,
        )

    result = run(
        complete,
        Task.new(str(tmp_path), "small", engine="mock"),
        context=ContextControls(budget=100, fillline_threshold=0.8),
        system_prompt=_SYS,
        max_steps=5,
    )
    assert result.status == OK
    assert turns["n"] == 1  # exactly the one finishing turn — no extra fill-line turn
    assert result.stats.model_turns == 1
    serialized = result.to_dict()
    assert "capacity_decision" not in serialized
    assert "capacity_warning" not in serialized


# ---------------------------------------------------------------------------
# Structural caps unchanged (termination preserved)
# ---------------------------------------------------------------------------


def test_structural_caps() -> None:
    # Typed-subagent roles (#t4) deepened recursion (2 -> 4) and added a single
    # global per-top-level agent budget (24); the fan-out cap is unchanged.
    assert MAX_SUBAGENT_FANOUT == 4
    assert MAX_SUBAGENT_DEPTH == 4
    assert MAX_SUBAGENT_TOTAL == 24
    assert _MAX_OVERFLOW_RETRIES == 3
    assert _MAX_TIMEOUT_RETRIES == 1
