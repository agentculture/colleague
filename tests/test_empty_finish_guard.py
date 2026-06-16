"""#202: an empty/whitespace ``finish`` on a read-heavy run is never a silent ok.

The reported failure: a ``review`` ran real analysis (it had findings in its
scratchpad), then called ``finish`` with empty args. The summary fell back to the
last prose line ("I now have enough… Let me finalize.") — a planning line, not the
findings — and the run reported ``status: ok`` with no review. The deliverable was
lost, including a real bug.

The fix extends the #191 forced-synthesis net to the explicit ``finish``
(``_EXIT_FINISHED``) path: when ``finish`` carries no usable summary but context
was read, the loop forces ONE no-tools turn to produce the answer from what it
read. A ``finish`` that DOES carry a summary is byte-identical to before.
"""

from __future__ import annotations

from pathlib import Path

from colleague.contract import OK, Task
from colleague.loop import ModelResponse, ToolCall, run
from colleague.tools import ToolExecutor


def _scripted(turns: list[ModelResponse]):
    state = {"i": 0}

    def complete(_messages: list[dict]) -> ModelResponse:
        turn = turns[min(state["i"], len(turns) - 1)]
        state["i"] += 1
        return turn

    return complete


def _read_then(*final_turns: ModelResponse) -> list[ModelResponse]:
    """A run that first reads a file (so step_count > 0), then the given turns."""
    return [
        ModelResponse(
            content="reading the module",
            tool_calls=[ToolCall("r1", "read_file", {"path": "mod.py"})],
            prompt_tokens=1,
            completion_tokens=1,
        ),
        *final_turns,
    ]


def test_empty_finish_after_reading_synthesizes_findings(tmp_path: Path) -> None:
    """#202 repro: empty finish + gathered context -> forced synthesis, not a planning line."""
    repo = tmp_path
    (repo / "mod.py").write_text("def f():\n    return 1\n")
    task = Task.new(str(repo), "review mod.py", engine="mock")

    turns = _read_then(
        # The #202 trigger: a planning line + finish with EMPTY summary.
        ModelResponse(
            content="I now have enough to write a thorough review. Let me finalize.",
            tool_calls=[ToolCall("f1", "finish", {"summary": ""})],
            prompt_tokens=1,
            completion_tokens=1,
        ),
        # The forced-synthesis turn the fix injects -> the real findings.
        ModelResponse(
            content="Findings: f() always returns 1; the exclusive-end off-by-one drops Dec 31.",
            tool_calls=[],
            prompt_tokens=1,
            completion_tokens=1,
        ),
    )

    result = run(
        _scripted(turns),
        task,
        max_steps=10,
        system_prompt="",
        model="mock",
        executor=ToolExecutor(str(repo)),
    )

    # finish was called -> a clean OK status, but the summary is the synthesized
    # findings, NOT the empty finish and NOT the "Let me finalize" planning line.
    assert result.status == OK
    assert "Findings" in result.summary
    assert "Let me finalize" not in result.summary


def test_finish_with_real_summary_is_unchanged(tmp_path: Path) -> None:
    """A finish that DOES carry a summary keeps it verbatim — no synthesis (byte-identical)."""
    repo = tmp_path
    (repo / "mod.py").write_text("x = 1\n")
    task = Task.new(str(repo), "review mod.py", engine="mock")

    turns = _read_then(
        ModelResponse(
            content="done",
            tool_calls=[ToolCall("f1", "finish", {"summary": "Verdict: looks correct."})],
            prompt_tokens=1,
            completion_tokens=1,
        ),
        # This turn must NEVER be consumed — a real summary short-circuits synthesis.
        ModelResponse(
            content="SHOULD NOT APPEAR", tool_calls=[], prompt_tokens=1, completion_tokens=1
        ),
    )

    result = run(
        _scripted(turns),
        task,
        max_steps=10,
        system_prompt="",
        model="mock",
        executor=ToolExecutor(str(repo)),
    )

    assert result.status == OK
    assert result.summary == "Verdict: looks correct."
    assert "SHOULD NOT APPEAR" not in result.summary
