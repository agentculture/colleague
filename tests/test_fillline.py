"""Proactive fill-line capacity decision (#156): pure helpers + loop integration.

Covers plan targets c4/h2/h11 (the trigger records exactly one declared move,
byte-identical no-op otherwise), c10/h3 (self-compaction: a model-authored summary
replaces the elided turns, head preserved, lossy-windowing fallback on overflow),
c11 (a split declaration routes through the existing subagents path), and c12 (a
finish-with-handoff declaration preserves a continuation summary).
"""

from __future__ import annotations

from pathlib import Path

from colleague import fillline
from colleague.contract import OK, Task
from colleague.loop import ContextControls, ModelResponse, ToolCall, run

_SYS = "You are a test coding agent."
_OVERFLOW = "This model's maximum context length is 4096 tokens"


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_armed_requires_budget_and_threshold() -> None:
    assert fillline.armed(100, 0.8) is True
    assert fillline.armed(None, 0.8) is False
    assert fillline.armed(0, 0.8) is False
    assert fillline.armed(100, 0) is False
    assert fillline.armed(100, 1.5) is False


def test_crossed() -> None:
    assert fillline.crossed(80, 100, 0.8) is True
    assert fillline.crossed(79, 100, 0.8) is False


def test_classify_declaration() -> None:
    assert fillline.classify_declaration(["subagents"]) == fillline.MOVE_SPLIT
    assert fillline.classify_declaration(["subagent"]) == fillline.MOVE_SPLIT
    assert fillline.classify_declaration(["finish"]) == fillline.MOVE_HANDOFF
    assert fillline.classify_declaration([]) == fillline.MOVE_COMPACT
    assert fillline.classify_declaration(["read_file"]) == fillline.MOVE_COMPACT


def test_build_decision_prompt_names_all_three_moves() -> None:
    body = fillline.build_decision_prompt(
        used_tokens=200, budget_tokens=250, per_child_budget_tokens=250, max_children=3
    )
    assert "COMPACT" in body
    assert "SPLIT" in body
    assert "FINISH-WITH-HANDOFF" in body
    assert "subagents" in body
    assert "200" in body and "250" in body and "3" in body


def test_apply_compaction_preserves_head_and_replaces_tail() -> None:
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "original assignment"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "1"}]},
        {"role": "tool", "content": "tool result", "tool_call_id": "1"},
    ]
    out = fillline.apply_compaction(messages, "did A and B; remains C")
    assert out[0] == messages[0]  # system preserved
    assert out[1] == messages[1]  # original assignment preserved
    assert len(out) == 3
    assert out[2]["content"].startswith("[Compacted summary")
    assert "did A and B" in out[2]["content"]
    # The elided working turns (assistant tool_calls + tool reply) are gone.
    assert not any(m.get("role") == "tool" for m in out)


# ---------------------------------------------------------------------------
# Loop integration
# ---------------------------------------------------------------------------


def _task(tmp_path: Path) -> Task:
    return Task.new(str(tmp_path), "do a long thing", engine="mock")


def _run(complete, task, **kwargs):
    cc = ContextControls(
        budget=kwargs.pop("budget", 100),
        count_tokens=kwargs.pop("count_tokens", None),
        autosplit_target=kwargs.pop("autosplit_target", 100),
        fillline_threshold=kwargs.pop("fillline_threshold", 0.8),
    )
    kwargs.setdefault("system_prompt", _SYS)
    kwargs.setdefault("max_steps", 10)
    return run(complete, task, context=cc, **kwargs)


def _has(messages, needle: str) -> bool:
    return any(needle in (m.get("content") or "") for m in messages)


def test_no_fillline_event_is_byte_identical_noop(tmp_path) -> None:
    """A work item whose context never crosses the line records no decision (#156, h2)."""

    def complete(messages):
        return ModelResponse(
            content="done",
            tool_calls=[ToolCall("f", "finish", {"summary": "done"})],
            prompt_tokens=10,  # well under 0.8 * 100
            completion_tokens=1,
        )

    result = _run(complete, _task(tmp_path))
    assert result.status == OK
    assert result.capacity_decision is None
    assert "capacity_decision" not in result.to_dict()
    assert "capacity_warning" not in result.to_dict()


def test_compact_branch_summarizes_and_preserves_head(tmp_path) -> None:
    """A COMPACT declaration records the move and replaces elided turns with a
    model-authored summary; messages[:2] survive (#156, c10/h3)."""
    calls: list[list] = []

    def complete(messages):
        calls.append(list(messages))
        if _has(messages, "Summarize everything done"):
            return ModelResponse(
                content="COMPACT SUMMARY: read foo.py; remains bar",
                prompt_tokens=5,
                completion_tokens=5,
            )
        if _has(messages, "declare ONE move"):
            # Declare COMPACT: reply without a tool call.
            return ModelResponse(content="compacting", prompt_tokens=85, completion_tokens=1)
        if len(calls) == 1:
            # First working turn crosses the fill line (prompt_tokens 90 >= 0.8*100).
            return ModelResponse(
                content="",
                tool_calls=[ToolCall("1", "list_dir", {"path": "."})],
                prompt_tokens=90,
                completion_tokens=1,
            )
        # After compaction: finish.
        return ModelResponse(
            content="done",
            tool_calls=[ToolCall("2", "finish", {"summary": "done"})],
            prompt_tokens=5,
            completion_tokens=1,
        )

    result = _run(complete, _task(tmp_path))
    assert result.status == OK
    assert result.capacity_decision is not None
    assert result.capacity_decision.kind == "compact"
    assert "fill line" in result.capacity_decision.reason
    # The final (finish) turn ran against head + the model-authored summary only.
    final = calls[-1]
    assert final[0]["role"] == "system"  # messages[:2] preserved (head)
    assert any(
        (m.get("content") or "").startswith("[Compacted summary") for m in final
    ), "compacted summary must replace the elided turns"
    assert _has(final, "COMPACT SUMMARY: read foo.py")  # model-authored content present
    assert not any(m.get("role") == "tool" for m in final)  # working history elided


def test_compact_overflow_falls_back_to_windowing(tmp_path) -> None:
    """If the summarization turn itself overflows, compaction falls back to lossy
    windowing rather than aborting — degradation is the documented floor (#156, h3)."""
    calls: list[int] = []

    def complete(messages):
        calls.append(1)
        if _has(messages, "Summarize everything done"):
            raise RuntimeError(_OVERFLOW)  # the summary turn cannot fit
        if _has(messages, "declare ONE move"):
            return ModelResponse(content="compacting", prompt_tokens=85, completion_tokens=1)
        if len(calls) == 1:
            return ModelResponse(
                content="",
                tool_calls=[ToolCall("1", "list_dir", {"path": "."})],
                prompt_tokens=90,
                completion_tokens=1,
            )
        return ModelResponse(
            content="done",
            tool_calls=[ToolCall("2", "finish", {"summary": "done"})],
            prompt_tokens=5,
            completion_tokens=1,
        )

    result = _run(
        complete,
        _task(tmp_path),
        count_tokens=lambda msgs: sum(len(m.get("content") or "") for m in msgs),
    )
    # The run completed (no abort) and the decision was still recorded as compact.
    assert result.status == OK
    assert result.capacity_decision is not None
    assert result.capacity_decision.kind == "compact"


def test_split_declaration_records_split(tmp_path) -> None:
    """A SPLIT declaration (subagents call) is recorded as kind 'split' (#156, c11)."""

    def complete(messages):
        if _has(messages, "declare ONE move"):
            return ModelResponse(
                content="splitting",
                tool_calls=[ToolCall("s", "subagents", {"tasks": []})],
                prompt_tokens=85,
                completion_tokens=1,
            )
        if not _has(messages, "list_dir-done-marker"):
            return ModelResponse(
                content="",
                tool_calls=[ToolCall("1", "list_dir", {"path": "."})],
                prompt_tokens=90,
                completion_tokens=1,
            )
        return ModelResponse(
            content="done",
            tool_calls=[ToolCall("f", "finish", {"summary": "done"})],
            prompt_tokens=5,
            completion_tokens=1,
        )

    result = _run(complete, _task(tmp_path))
    assert result.capacity_decision is not None
    assert result.capacity_decision.kind == "split"


def test_finish_with_handoff_declaration_preserves_continuation(tmp_path) -> None:
    """A FINISH-WITH-HANDOFF declaration records the move and the continuation
    summary is preserved on the result (#156, c12)."""

    def complete(messages):
        if _has(messages, "declare ONE move"):
            return ModelResponse(
                content="handing off",
                tool_calls=[ToolCall("f", "finish", {"summary": "DONE: A,B  REMAINS: C,D"})],
                prompt_tokens=85,
                completion_tokens=1,
            )
        return ModelResponse(
            content="",
            tool_calls=[ToolCall("1", "list_dir", {"path": "."})],
            prompt_tokens=90,
            completion_tokens=1,
        )

    result = _run(complete, _task(tmp_path))
    assert result.status == OK
    assert result.capacity_decision is not None
    assert result.capacity_decision.kind == "finish-with-handoff"
    assert result.summary == "DONE: A,B  REMAINS: C,D"
