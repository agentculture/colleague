"""Honest-incompletion wiring in the shared work loop (colleague#313).

Proves the pure detector in ``colleague.incompletion`` is consulted exactly
once, after the terminal summary is resolved, and that it:

  * downgrades a clean-finish, zero-change, write-intent run to INCOMPLETE
    with a ``write-no-changes`` :class:`~colleague.contract.IncompletionRecord`;
  * leaves the normal mock-shaped run (write then finish) byte-identical —
    status stays OK, ``result.incompletion`` is ``None``, and the
    ``"incompletion"`` key is omitted from ``to_dict()``;
  * never mislabels a legitimately read-only role (explorer) that changed
    nothing but delivered a real summary.
"""

from __future__ import annotations

from pathlib import Path

from colleague.contract import INCOMPLETE, OK, Task
from colleague.loop import CompleteFn, ContextControls, ModelResponse, ToolCall, run


def scripted(responses: list[ModelResponse]) -> CompleteFn:
    """A complete() that returns each canned response in turn (then repeats last)."""
    state = {"i": 0}

    def complete(_messages: list[dict]) -> ModelResponse:
        i = min(state["i"], len(responses) - 1)
        state["i"] += 1
        return responses[i]

    return complete


def test_write_intent_clean_finish_no_changes_is_incomplete(tmp_path: Path) -> None:
    """The #313 core case: a write-intent model that META-finishes — admits it is
    unfinished (``Need to continue implementation``) — with no write_file/edit_file
    produced no deliverable even though the loop exited cleanly. A meta summary is
    NOT a deliverable, so the clean OK status is downgraded to INCOMPLETE and an
    advisory record explains why. (A *substantive* no-change finish is the soft-rule
    'no change needed' case below and stays OK.)"""
    responses = [
        ModelResponse(
            tool_calls=[
                ToolCall(
                    "1",
                    "finish",
                    {"summary": "I have read the files. Need to continue implementation."},
                )
            ]
        ),
    ]
    task = Task.new(str(tmp_path), "make a change")
    result = run(scripted(responses), task, max_steps=5)

    assert result.changed_files == []
    assert result.status == INCOMPLETE
    assert result.incompletion is not None
    assert result.incompletion.reason == "write-no-changes"
    assert result.incompletion.recommendation
    assert result.incompletion.evidence
    # The downgrade is visible in the serialized artifact too.
    serialized = result.to_dict()
    assert serialized["status"] == INCOMPLETE
    assert serialized["incompletion"]["reason"] == "write-no-changes"


def test_write_intent_substantive_no_change_finish_stays_ok(tmp_path: Path) -> None:
    """Soft rule (colleague#313): a write-intent run that finishes cleanly with a
    real, non-meta explanation and 0 changes is a legitimate 'no change needed'
    deliverable — NOT flagged incomplete."""
    responses = [
        ModelResponse(
            tool_calls=[
                ToolCall(
                    "1",
                    "finish",
                    {"summary": "The target function is already correct; no change was needed."},
                )
            ]
        ),
    ]
    task = Task.new(str(tmp_path), "fix the bug if present")
    result = run(scripted(responses), task, max_steps=5)

    assert result.changed_files == []
    assert result.status == OK
    assert result.incompletion is None
    assert "incompletion" not in result.to_dict()


def test_write_intent_clean_finish_with_changes_stays_ok_byte_identical(
    tmp_path: Path,
) -> None:
    """The normal mock-shaped run (write a file, then finish) is unaffected: at
    least one changed file means a real deliverable was produced, so status
    stays OK, ``result.incompletion`` is ``None``, and the key is omitted from
    ``to_dict()`` — a delivering run is byte-identical to before this feature.
    """
    responses = [
        ModelResponse(
            tool_calls=[ToolCall("1", "write_file", {"path": "out.txt", "content": "hi"})]
        ),
        ModelResponse(tool_calls=[ToolCall("2", "finish", {"summary": "wrote out.txt"})]),
    ]
    task = Task.new(str(tmp_path), "write out.txt")
    result = run(scripted(responses), task, max_steps=10)

    assert result.status == OK
    assert result.changed_files == ["out.txt"]
    assert result.incompletion is None
    assert "incompletion" not in result.to_dict()


def test_read_only_role_no_changes_real_summary_is_not_flagged(tmp_path: Path) -> None:
    """A read-only role (explorer) that changes nothing but delivers a real,
    non-meta summary must never be mislabeled incomplete by the write-intent
    detector — a legitimately read-only run has no deliverable-by-file-change
    expectation at all."""
    responses = [
        ModelResponse(
            tool_calls=[ToolCall("1", "finish", {"summary": "surveyed modules A and B"})]
        ),
    ]
    task = Task.new(str(tmp_path), "survey the repo")
    result = run(
        scripted(responses),
        task,
        max_steps=5,
        context=ContextControls(role="explorer"),
    )

    assert result.changed_files == []
    assert result.incompletion is None
    assert result.status == OK  # never downgraded by this detector
    assert "incompletion" not in result.to_dict()
