"""Cross-cutting auto-split guards (#151, task t4).

Five guard groups that span the whole feature surface:

1. No-op when armed-but-not-triggered: normal scripted run with both
   context_budget and autosplit_target set fires zero extra turns and
   produces an identical result shape to a dormant run.

2. All-engines parity (all-engines rule): BOTH bundled backends forward
   autosplit_target to loop.run().

3. Toggleable contrast: an always-overflowing complete WITH autosplit_target
   set injects the recommendation (extra turn vs pure-degradation count);
   WITHOUT it, no recommendation fires and call count equals the pure-degradation
   floor.  Both paths raise WorkAborted.

4. Windowing invariant: window_messages preserves messages[0] (system prompt)
   and messages[1] (original assignment) byte-identically at the most aggressive
   trim — the load-bearing assumption for split authoring.

5. Caps unchanged: MAX_SUBAGENT_FANOUT==4 and MAX_SUBAGENT_DEPTH==2 are not
   raised by the auto-split feature.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from colleague import loop as loop_mod
from colleague.config import MAX_SUBAGENT_DEPTH, MAX_SUBAGENT_FANOUT, EngineConfig
from colleague.context import window_messages
from colleague.contract import OK, Task, TaskResult
from colleague.loop import ModelResponse, ToolCall, run

# Overflow string shared with test_autosplit_loop.py.
_OVERFLOW = "This model's maximum context length is 4096 tokens"

# A system prompt that does NOT mention `subagents`, so any `subagents` string
# in the message stream is provably loop-injected, not a false positive from the
# default system prompt.
_SYS = "test agent"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _task(tmp_path: Path, instruction: str = "do a thing") -> Task:
    return Task.new(str(tmp_path), instruction, engine="mock")


def _run(complete, task, **kwargs):
    """run() with the subagents-free system prompt."""
    kwargs.setdefault("system_prompt", _SYS)
    return run(complete, task, **kwargs)


def _scripted_finish() -> tuple[list, object]:
    """A one-turn scripted complete that writes nothing and calls finish.

    Returns (call_log, complete) where call_log is a list appended to on each
    call so the test can count invocations.
    """
    call_log: list[int] = []

    def complete(messages):
        call_log.append(len(call_log))
        return ModelResponse(
            content="done",
            tool_calls=[ToolCall("f", "finish", {"summary": "scripted finish"})],
            prompt_tokens=1,
            completion_tokens=1,
        )

    return call_log, complete


def _dummy_task_result() -> TaskResult:
    """Minimal TaskResult for patched engine.work() stubs."""
    return TaskResult(task_id="dummy", status=OK)


# ---------------------------------------------------------------------------
# Escalation suppressor (avoids real network/agtag in ALL tests in this file)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_escalation(monkeypatch):
    """Suppress escalate() for all tests in this file."""
    monkeypatch.setattr(loop_mod._escalation, "escalate", lambda *a, **kw: None)


# ---------------------------------------------------------------------------
# Guard 1 — No-op when armed-but-not-triggered (c8, h13)
# ---------------------------------------------------------------------------


def test_armed_no_extra_turns_on_normal_run(tmp_path):
    """Armed autosplit fires zero extra complete calls when no overflow occurs.

    The complete() call count must equal the number of scripted turns (just 1),
    regardless of context_budget and autosplit_target being set.
    """
    call_log, complete = _scripted_finish()

    result = _run(
        complete,
        _task(tmp_path),
        max_steps=8,
        context_budget=1_000_000,
        autosplit_target=500_000,
    )

    # Exactly one scripted turn — the trigger never fired.
    assert len(call_log) == 1, f"expected 1 complete call, got {len(call_log)}"
    assert result.status == OK
    assert result.summary == "scripted finish"


def test_armed_result_shape_matches_dormant(tmp_path):
    """Result key set is identical whether autosplit is armed or dormant.

    Both runs use the same scripted complete, same repo path, and the same
    minimal system prompt; the only difference is autosplit_target present vs
    absent.  The to_dict() key sets must be identical — no extra or missing key.
    """
    _, complete_armed = _scripted_finish()
    _, complete_dormant = _scripted_finish()

    result_armed = _run(
        complete_armed,
        _task(tmp_path),
        max_steps=4,
        context_budget=1_000_000,
        autosplit_target=500_000,
    )
    result_dormant = _run(
        complete_dormant,
        _task(tmp_path),
        max_steps=4,
        context_budget=1_000_000,
        # autosplit_target deliberately omitted → dormant
    )

    armed_keys = set(result_armed.to_dict().keys())
    dormant_keys = set(result_dormant.to_dict().keys())
    assert armed_keys == dormant_keys, (
        f"Result shape differs: armed extra={armed_keys - dormant_keys}, "
        f"dormant extra={dormant_keys - armed_keys}"
    )


# ---------------------------------------------------------------------------
# Guard 2 — All-engines parity (c20 / h12)
# ---------------------------------------------------------------------------


def test_mock_engine_forwards_autosplit_target(tmp_path):
    """MockEngine.work() passes autosplit_target=config.autosplit_target_tokens to run()."""
    from colleague.engines.mock import MockEngine

    engine = MockEngine()
    config = EngineConfig.resolve()
    task = _task(tmp_path, "x")

    captured: dict[str, object] = {}

    def fake_run(complete, task, **kwargs):
        captured.update(kwargs)
        return _dummy_task_result()

    with patch("colleague.engines.mock.run", side_effect=fake_run):
        engine.work(task, config)

    assert "autosplit_target" in captured, "MockEngine did not pass autosplit_target to run()"
    assert captured["autosplit_target"] == config.autosplit_target_tokens, (
        f"MockEngine forwarded autosplit_target={captured['autosplit_target']!r} "
        f"instead of config.autosplit_target_tokens={config.autosplit_target_tokens}"
    )


def test_vllm_engine_forwards_autosplit_target(tmp_path):
    """VllmOpenAIEngine.work() passes autosplit_target=config.autosplit_target_tokens to run()."""
    from colleague.engines.vllm_openai import VllmOpenAIEngine

    engine = VllmOpenAIEngine()
    config = EngineConfig.resolve()
    task = _task(tmp_path, "x")

    captured: dict[str, object] = {}

    def fake_run(complete, task, **kwargs):
        captured.update(kwargs)
        return _dummy_task_result()

    with patch("colleague.engines.vllm_openai.run", side_effect=fake_run):
        engine.work(task, config)

    assert "autosplit_target" in captured, "VllmOpenAIEngine did not pass autosplit_target to run()"
    assert captured["autosplit_target"] == config.autosplit_target_tokens, (
        f"VllmOpenAIEngine forwarded autosplit_target={captured['autosplit_target']!r} "
        f"instead of config.autosplit_target_tokens={config.autosplit_target_tokens}"
    )


# ---------------------------------------------------------------------------
# Guard 3 — Toggleable contrast (h9)
# ---------------------------------------------------------------------------


def test_always_overflow_with_target_injects_recommendation(tmp_path):
    """With autosplit_target set, an always-overflowing complete gets the recommendation.

    The recommendation is the signal that the feature fired: once injected, the
    complete call count exceeds the pure-degradation floor
    (_MAX_OVERFLOW_RETRIES + 2) because the loop gave the model at least one
    extra turn after injecting the recommendation message.
    Both the recommendation-injecting path AND the eventual WorkAborted share
    this test (the model ignores the recommendation, so the run still aborts).
    """
    call_count = [0]

    def complete(messages):
        call_count[0] += 1
        # Sanity: the recommendation should never reach complete more than once,
        # but we accept the message being present on subsequent calls.
        raise RuntimeError(_OVERFLOW)

    with pytest.raises(loop_mod.WorkAborted):
        _run(
            complete,
            _task(tmp_path),
            max_steps=10,
            context_budget=1000,
            autosplit_target=1_000_000,
        )

    pure_floor = loop_mod._MAX_OVERFLOW_RETRIES + 2
    assert call_count[0] > pure_floor, (
        f"Expected more than {pure_floor} calls (recommendation gave an extra turn), "
        f"got {call_count[0]}"
    )


def test_always_overflow_with_target_recommendation_content_names_subagents(tmp_path):
    """When the recommendation IS injected, a message containing 'subagents' reached complete."""
    saw_subagents: list[bool] = []

    def complete(messages):
        if any("subagents" in (m.get("content") or "") for m in messages):
            saw_subagents.append(True)
        raise RuntimeError(_OVERFLOW)

    with pytest.raises(loop_mod.WorkAborted):
        _run(
            complete,
            _task(tmp_path),
            max_steps=10,
            context_budget=1000,
            autosplit_target=1_000_000,
        )

    assert saw_subagents, "No message containing 'subagents' was ever seen by complete()"


def test_always_overflow_without_target_no_recommendation(tmp_path):
    """With autosplit_target omitted, an always-overflowing complete gets NO recommendation.

    The call count must equal exactly the pure-degradation floor
    (_MAX_OVERFLOW_RETRIES + 2): first attempt + _MAX_OVERFLOW_RETRIES retries
    + the final re-attempt after the cap is hit.  No extra turn is injected.
    """
    call_count = [0]

    def complete(messages):
        call_count[0] += 1
        assert not any(
            "subagents" in (m.get("content") or "") for m in messages
        ), "recommendation injected while feature is dormant (autosplit_target omitted)"
        raise RuntimeError(_OVERFLOW)

    with pytest.raises(loop_mod.WorkAborted):
        _run(
            complete,
            _task(tmp_path),
            max_steps=10,
            context_budget=1000,
            # autosplit_target omitted → dormant
        )

    pure_floor = loop_mod._MAX_OVERFLOW_RETRIES + 2
    assert (
        call_count[0] == pure_floor
    ), f"Expected exactly {pure_floor} calls (pure degradation), got {call_count[0]}"


def test_always_overflow_with_target_zero_no_recommendation(tmp_path):
    """With autosplit_target=0, the feature is dormant — identical to the omitted case."""
    call_count = [0]

    def complete(messages):
        call_count[0] += 1
        assert not any(
            "subagents" in (m.get("content") or "") for m in messages
        ), "recommendation injected while feature is dormant (autosplit_target=0)"
        raise RuntimeError(_OVERFLOW)

    with pytest.raises(loop_mod.WorkAborted):
        _run(
            complete,
            _task(tmp_path),
            max_steps=10,
            context_budget=1000,
            autosplit_target=0,  # explicitly dormant
        )

    pure_floor = loop_mod._MAX_OVERFLOW_RETRIES + 2
    assert call_count[0] == pure_floor, (
        f"Expected exactly {pure_floor} calls (dormant, autosplit_target=0), "
        f"got {call_count[0]}"
    )


# ---------------------------------------------------------------------------
# Guard 4 — Windowing invariant (c21 / h14)
# ---------------------------------------------------------------------------


def _make_long_messages(n_extra: int = 30) -> list[dict]:
    """Build a long message list: system + first-user + many assistant/tool turns."""
    system = {"role": "system", "content": "you are a test agent"}
    first_user = {
        "role": "user",
        "content": "ORIGINAL ASSIGNMENT: " + ("do important work. " * 50),
    }
    msgs: list[dict] = [system, first_user]
    for i in range(n_extra):
        # Paired assistant-with-tool_calls + tool reply (a droppable segment unit).
        tc_id = f"tc-{i}"
        msgs.append(
            {
                "role": "assistant",
                "content": f"thinking about step {i}",
                "tool_calls": [
                    {
                        "id": tc_id,
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "arguments": f'{{"path": "file{i}.py"}}',
                        },
                    }
                ],
            }
        )
        msgs.append(
            {
                "role": "tool",
                "tool_call_id": tc_id,
                "content": f"content of file {i}: " + ("x" * 100),
            }
        )
    return msgs


def test_windowing_preserves_system_and_first_user_at_aggressive_trim():
    """window_messages preserves messages[0] and messages[1] byte-identically.

    Windowed to an extremely small budget forces the most aggressive possible
    trim (dropping all droppable segments except the minimum tail).  The
    system prompt and original assignment must survive unchanged.
    """
    messages = _make_long_messages(n_extra=30)
    system_original = dict(messages[0])
    first_user_original = dict(messages[1])

    # Budget of 1 forces maximum aggressiveness: the function still preserves
    # head + placeholder + last segment (that is the structural floor).
    windowed = window_messages(messages, budget_tokens=1)

    assert len(windowed) >= 2, "windowed result must have at least 2 messages"
    assert (
        windowed[0] == system_original
    ), "System prompt (messages[0]) was modified or dropped by window_messages"
    assert (
        windowed[1] == first_user_original
    ), "Original assignment (messages[1]) was modified or dropped by window_messages"


def test_windowing_first_user_survives_across_budget_levels():
    """The original assignment survives at multiple budget levels."""
    messages = _make_long_messages(n_extra=20)
    first_user_original = dict(messages[1])

    for budget in (1, 5, 50, 200, 500):
        windowed = window_messages(messages, budget_tokens=budget)
        assert windowed[1] == first_user_original, f"Original assignment dropped at budget={budget}"


def test_windowing_does_not_mutate_input():
    """window_messages must not mutate the input list."""
    messages = _make_long_messages(n_extra=10)
    original_len = len(messages)
    original_head = [dict(m) for m in messages[:3]]

    window_messages(messages, budget_tokens=1)

    assert len(messages) == original_len, "window_messages mutated the input list length"
    for i, (orig, after) in enumerate(zip(original_head, messages[:3])):
        assert orig == after, f"window_messages mutated messages[{i}]"


# ---------------------------------------------------------------------------
# Guard 5 — Caps unchanged (h11 / c6)
# ---------------------------------------------------------------------------


def test_max_subagent_fanout_unchanged():
    """MAX_SUBAGENT_FANOUT must remain 4 — the auto-split feature must not raise it."""
    assert (
        MAX_SUBAGENT_FANOUT == 4
    ), f"MAX_SUBAGENT_FANOUT changed: expected 4, got {MAX_SUBAGENT_FANOUT}"


def test_max_subagent_depth_unchanged():
    """MAX_SUBAGENT_DEPTH must remain 2 — the auto-split feature must not raise it."""
    assert (
        MAX_SUBAGENT_DEPTH == 2
    ), f"MAX_SUBAGENT_DEPTH changed: expected 2, got {MAX_SUBAGENT_DEPTH}"
