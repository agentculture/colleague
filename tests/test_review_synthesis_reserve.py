"""#197: a read-heavy review reserves budget so the verdict turn isn't starved.

``ContextControls.synthesis_reserve`` holds back N steps from the reading budget,
so a run that would otherwise spend every step reading a big diff stops early and
the forced-synthesis verdict (#191) runs with budget/context to spare. The caller
(review) sets it; it is a strict no-op at 0 (the whole budget is spent reading).
"""

from __future__ import annotations

from pathlib import Path

from colleague.contract import Task
from colleague.loop import ContextControls, ModelResponse, ToolCall, run
from colleague.tools import ToolExecutor

_SYNTHESIS_MARKER = "Stop using tools and answer"  # from _SYNTHESIS_PROMPT


def _read_until_synthesis():
    """Always read the module until the forced-synthesis prompt arrives, then verdict."""
    n = {"i": 0}

    def complete(messages: list[dict]) -> ModelResponse:
        last = messages[-1].get("content", "") if messages else ""
        if _SYNTHESIS_MARKER in last:
            return ModelResponse(
                content="VERDICT: reviewed the diff; found one off-by-one bug.",
                tool_calls=[],
                prompt_tokens=1,
                completion_tokens=1,
            )
        n["i"] += 1
        return ModelResponse(
            content="still reading",
            # Alternate the spelling: five identical calls in a row trip the t16 loop guard.
            tool_calls=[
                ToolCall(
                    f"r{n['i']}", "read_file", {"path": "mod.py" if n["i"] % 2 else "./mod.py"}
                )
            ],
            prompt_tokens=1,
            completion_tokens=1,
        )

    return complete


def _run_with_reserve(repo: Path, reserve: int, max_steps: int):
    (repo / "mod.py").write_text("def f():\n    return 1\n")
    task = Task.new(str(repo), "review the diff", engine="mock")
    return run(
        _read_until_synthesis(),
        task,
        max_steps=max_steps,
        system_prompt="",
        model="mock",
        executor=ToolExecutor(str(repo)),
        context=ContextControls(synthesis_reserve=reserve),
    )


def test_reserve_holds_back_reading_steps_but_still_yields_a_verdict(tmp_path: Path) -> None:
    """With a reserve of 2 of 5 steps, only 3 reads happen, and a verdict still lands."""
    result = _run_with_reserve(tmp_path, reserve=2, max_steps=5)
    assert result.stats.step_count == 3  # 5 - 2 reserved
    assert "VERDICT" in result.summary  # synthesis still produced the verdict


def test_zero_reserve_is_byte_identical(tmp_path: Path) -> None:
    """reserve=0 spends the whole budget reading (no behavior change)."""
    result = _run_with_reserve(tmp_path, reserve=0, max_steps=5)
    assert result.stats.step_count == 5  # full budget spent reading
    assert "VERDICT" in result.summary
