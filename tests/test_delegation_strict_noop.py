"""Delegation-safety features are STRICT NO-OPS when nothing triggers them (h7).

When synthesis_reserve is 0 (the default) and a finish carries a real summary,
the loop must be byte-identical to the pre-feature path: no forced-synthesis
turn fires, and the real summary is kept verbatim. Likewise, when step_count is
0 there is nothing to synthesise, so an empty finish stays empty (or becomes the
NO_RESULT_PRODUCED sentinel) rather than triggering a synthesis turn.
"""

from __future__ import annotations

from pathlib import Path

from colleague.contract import NO_RESULT_PRODUCED, OK, Task
from colleague.loop import ContextControls, ModelResponse, ToolCall, run
from colleague.tools import ToolExecutor


def _scripted(turns: list[ModelResponse]):
    state = {"i": 0}

    def complete(_messages: list[dict]) -> ModelResponse:
        turn = turns[min(state["i"], len(turns) - 1)]
        state["i"] += 1
        return turn

    return complete


def test_real_finish_with_zero_reserve_is_byte_identical(tmp_path: Path) -> None:
    """A finish with a real summary + synthesis_reserve=0 keeps the summary verbatim."""
    repo = tmp_path
    (repo / "mod.py").write_text("x = 1\n")
    task = Task.new(str(repo), "review it", engine="mock")

    turns = [
        # Turn 1: read the file.
        ModelResponse(
            content="reading the module",
            tool_calls=[ToolCall("r1", "read_file", {"path": "mod.py"})],
            prompt_tokens=1,
            completion_tokens=1,
        ),
        # Turn 2: finish with a REAL summary.
        ModelResponse(
            content="done",
            tool_calls=[ToolCall("f1", "finish", {"summary": "Verdict: fine."})],
            prompt_tokens=1,
            completion_tokens=1,
        ),
    ]

    result = run(
        _scripted(turns),
        task,
        max_steps=10,
        system_prompt="",
        model="mock",
        executor=ToolExecutor(str(repo)),
        context=ContextControls(synthesis_reserve=0),
    )

    assert result.status == OK
    assert result.summary == "Verdict: fine."


def test_no_read_empty_finish_does_not_synthesize(tmp_path: Path) -> None:
    """An empty finish with step_count==0 does not synthesize — nothing to synthesise."""
    repo = tmp_path
    (repo / "mod.py").write_text("x = 1\n")
    task = Task.new(str(repo), "review it", engine="mock")

    # Single turn: finish with empty summary, NO tool calls first (step_count == 0
    # at synthesis-check time because _finalize_stats hasn't run yet). Empty
    # content so _last_substantive is never set — the fallback becomes the sentinel.
    turns = [
        ModelResponse(
            content="",
            tool_calls=[ToolCall("f1", "finish", {"summary": ""})],
            prompt_tokens=1,
            completion_tokens=1,
        ),
    ]

    result = run(
        _scripted(turns),
        task,
        max_steps=10,
        system_prompt="",
        model="mock",
        executor=ToolExecutor(str(repo)),
        context=ContextControls(synthesis_reserve=0),
    )

    assert result.status == OK
    # With step_count 0 there is nothing to synthesise, so the summary must be
    # empty or the NO_RESULT_PRODUCED sentinel — never a synthesized verdict.
    assert result.summary in ("", NO_RESULT_PRODUCED)
