"""Tests for the result-fidelity contract additions (issue #109, task t1+t2+t3).

t1: Verifies that ``colleague.contract`` exposes a stable, importable sentinel
    value that callers can use to detect "no output was produced" without
    string-matching a step-count summary.

t3: Regression tests that prove the loop's no-finish summary-resolution
    behaviour (the t2 fix): content emitted on a tool-call turn is now
    recoverable as the drive summary, the last substantive content wins across
    turns, and the sentinel is returned only when no content was ever emitted.
"""

from __future__ import annotations

from pathlib import Path

from colleague.contract import NO_RESULT_PRODUCED, Task
from colleague.loop import ModelResponse, ToolCall, run


def test_no_result_produced_is_importable():
    """The sentinel must be importable from colleague.contract."""
    # Import at module level above; if it fails the whole module errors out,
    # which is itself a clear signal.  This assertion is belt-and-suspenders.
    assert NO_RESULT_PRODUCED is not None


def test_no_result_produced_is_non_empty_string():
    """The sentinel must be a non-empty string so callers can compare safely."""
    assert isinstance(NO_RESULT_PRODUCED, str)
    assert len(NO_RESULT_PRODUCED) > 0


def test_no_result_produced_is_stable():
    """The sentinel value must be exactly the documented string.

    Callers will write ``result.summary == NO_RESULT_PRODUCED``; if the value
    changes their comparisons silently break.  Pin the exact text here.

    The value is a machine-oriented marker (sentinel affixes), not a plain-English
    phrase, so the model cannot plausibly emit it as legitimate output and have a
    caller misclassify a real result as the empty case.
    """
    assert NO_RESULT_PRODUCED == "__COLLEAGUE_NO_RESULT_PRODUCED__"


def test_no_result_produced_does_not_contain_step_count():
    """The sentinel must not look like a step-count fallback summary.

    The whole point is to give callers something stable to branch on that is
    NOT the "completed in N step(s)" string — verify the sentinel is distinct.
    """
    assert "step" not in NO_RESULT_PRODUCED
    assert "completed" not in NO_RESULT_PRODUCED
    # Collision-resistant: machine-oriented affixes, not natural prose the model
    # could plausibly emit as its own last substantive content.
    assert NO_RESULT_PRODUCED.startswith("__")
    assert NO_RESULT_PRODUCED.endswith("__")
    assert " " not in NO_RESULT_PRODUCED


# ---------------------------------------------------------------------------
# t3: Regression tests for the loop's no-finish summary-resolution (t2 fix)
# ---------------------------------------------------------------------------


class TestNoFinishResultFidelity:
    """Regression guard for the t2 loop fix (issue #109).

    Every test drives the mock loop WITHOUT a ``finish`` call so we exercise the
    no-finish exit paths: either the step budget is exhausted, or the model stops
    returning tool calls.  We verify that ``result.summary`` is resolved with the
    documented precedence:

        finish_summary > no-tool-call terminating content > last substantive
        content (the t2 gap) > NO_RESULT_PRODUCED sentinel.

    Under the OLD code the last two cases collapsed to a step-count string like
    ``"completed in N step(s)"`` — exactly what these tests reject.
    """

    def test_content_on_tool_call_turn_is_recovered(self, tmp_path: Path) -> None:
        """Core regression (the line-568 gap, #109 t2).

        Every turn emits non-empty ``resp.content`` AND a tool call.  The drive
        never calls ``finish``.  After budget exhaustion the summary must equal
        the emitted content — NOT ``NO_RESULT_PRODUCED``, NOT containing
        "completed" or "budget".

        Under the old code this path produced ``"completed in 3 step(s)"``
        (the step-count fallback), which would cause this test to fail.
        """
        content = "FINDING: docs/x is stale"

        def narrate_then_loop(_messages: list[dict]) -> ModelResponse:
            return ModelResponse(
                content=content,
                tool_calls=[ToolCall("1", "list_dir", {"path": "."})],
            )

        task = Task.new(str(tmp_path), "investigate docs")
        result = run(narrate_then_loop, task, max_steps=3)

        assert result.summary == content
        assert result.summary != NO_RESULT_PRODUCED
        assert "completed" not in result.summary
        assert "budget" not in result.summary
        # The step budget really was hit (confirms the no-finish path was taken).
        assert result.stats.step_count == 3

    def test_last_substantive_content_wins_across_turns(self, tmp_path: Path) -> None:
        """Last-substantive content wins when multiple turns each carry content.

        Turn 1 emits "ALPHA" + tool call.
        Turn 2 emits "BETA"  + tool call.
        Budget exhausted after turn 2.

        Expected: ``result.summary == "BETA"`` (the LAST non-empty content seen,
        regardless of turn index).
        """
        responses = [
            ModelResponse(
                content="ALPHA",
                tool_calls=[ToolCall("1", "list_dir", {"path": "."})],
            ),
            ModelResponse(
                content="BETA",
                tool_calls=[ToolCall("2", "list_dir", {"path": "."})],
            ),
        ]
        turn_index = {"i": 0}

        def two_turns(_messages: list[dict]) -> ModelResponse:
            i = min(turn_index["i"], len(responses) - 1)
            turn_index["i"] += 1
            return responses[i]

        task = Task.new(str(tmp_path), "two turns then budget")
        result = run(two_turns, task, max_steps=2)

        assert result.summary == "BETA"

    def test_no_content_yields_sentinel(self, tmp_path: Path) -> None:
        """When every turn makes a tool call with NO content the sentinel is returned.

        Callers must be able to detect this programmatically by comparing
        ``result.summary`` to the imported ``NO_RESULT_PRODUCED`` constant —
        NOT by matching a step-count string.
        """

        def silent_tool_caller(_messages: list[dict]) -> ModelResponse:
            # content is intentionally absent / empty string (default).
            return ModelResponse(tool_calls=[ToolCall("x", "list_dir", {"path": "."})])

        task = Task.new(str(tmp_path), "no narration drive")
        result = run(silent_tool_caller, task, max_steps=3)

        # Compare to the imported constant — not a string literal — so a rename
        # of the sentinel value breaks this test immediately.
        assert result.summary == NO_RESULT_PRODUCED

    def test_finish_summary_takes_precedence_over_content(self, tmp_path: Path) -> None:
        """``finish`` summary always wins, even when earlier turns emitted content.

        Turn 1: content "NARRATION" + tool call.
        Turn 2: ``finish`` with summary "FINISH_WINS".

        Expected: ``result.summary == "FINISH_WINS"`` (the explicit finish beats
        the narrated content).
        """
        responses = [
            ModelResponse(
                content="NARRATION",
                tool_calls=[ToolCall("1", "list_dir", {"path": "."})],
            ),
            ModelResponse(
                tool_calls=[ToolCall("2", "finish", {"summary": "FINISH_WINS"})],
            ),
        ]
        turn_index = {"i": 0}

        def narrate_then_finish(_messages: list[dict]) -> ModelResponse:
            i = min(turn_index["i"], len(responses) - 1)
            turn_index["i"] += 1
            return responses[i]

        task = Task.new(str(tmp_path), "narrate then finish")
        result = run(narrate_then_finish, task, max_steps=5)

        assert result.summary == "FINISH_WINS"
        assert result.summary != "NARRATION"

    def test_task_result_public_fields_unchanged(self, tmp_path: Path) -> None:
        """Shape parity guard: the no-finish fix must not add new top-level fields.

        Running the mock loop and inspecting the ``TaskResult.__dataclass_fields__``
        keys confirms no new field was silently introduced by the t2 change.
        This complements the e2e shape test in ``test_e2e_mock.py``.
        """
        from dataclasses import fields as dc_fields

        from colleague.contract import TaskResult

        # Run a minimal drive to get a real result instance.
        task = Task.new(str(tmp_path), "shape parity check")
        result = run(
            lambda _msgs: ModelResponse(tool_calls=[ToolCall("1", "finish", {"summary": "done"})]),
            task,
            max_steps=5,
        )
        assert isinstance(result, TaskResult)

        # The expected public field names — update this list only when a new
        # field is intentionally added to TaskResult (and a re-spec documents it).
        expected_fields = {
            "task_id",
            "status",
            "summary",
            "changed_files",
            "steps",
            "usage",
            "stats",
            "finish_states",
            "artifacts_path",
            "error",
            "branch",
            "pr_url",
            "hook_firings",
            "sub_results",
            "command",
            "destination",
            "announcement",
            "capacity_decision",
            "capacity_warning",
            "lint_report",
            "coherence_report",  # the coherence gate report (#294)
            "test_integrity_report",
            "affected_tests_report",
            "not_finished",
            "stopped_without_finish",
            "warnings",
            "role",
            "mode",
            "acceptance_outcomes",
            "deepthink",
            "finish_recovered",
            "memory",
            "media",
            "senses",
            "incompletion",  # honest-incompletion contract (#313)
            "continued_from",  # continue lineage (#167)
            "chain",  # chain-of-episodes accounting (indefinite-run c20)
            "gates_deferred",  # structured gate-deferral marker (#341)
            "config_events",  # append-only config event stream (plan task t7, c9/h9)
            "config_digest",  # deterministic digest over config_events (plan task t7)
        }
        actual_fields = {f.name for f in dc_fields(result)}
        assert actual_fields == expected_fields
