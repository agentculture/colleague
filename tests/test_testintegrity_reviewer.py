"""Diverse-model reviewer subagent for the test-integrity gate (#203, t4).

When a flagged finding remains and a DIFFERENT reviewer model is configured, the
gate auto-spawns ONE reviewer subagent on that model (the robust guard — a
same-model re-examine turn can re-confirm its own mirror) to independently re-derive
the real API shape. The reviewer's SubResult is folded into result.sub_results.
Degrades to record-only when no reviewer model / no spawn callback is wired.
"""

from __future__ import annotations

from pathlib import Path

from colleague.contract import OK, SubResult, Task
from colleague.loop import (
    _DEFAULT_SYSTEM,
    CompleteFn,
    ContextControls,
    ModelResponse,
    Spawns,
    ToolCall,
    run,
)


def scripted(responses: list[ModelResponse]) -> CompleteFn:
    state = {"i": 0}

    def complete(_messages: list[dict]) -> ModelResponse:
        i = min(state["i"], len(responses) - 1)
        state["i"] += 1
        return responses[i]

    return complete


def _write(path: str, content: str) -> ModelResponse:
    return ModelResponse(
        tool_calls=[ToolCall("w", "write_file", {"path": path, "content": content})]
    )


def _finish(summary: str) -> ModelResponse:
    return ModelResponse(tool_calls=[ToolCall("f", "finish", {"summary": summary})])


_TEST = "import exc\n\n\ndef test_x():\n    return exc.response_error\n"
_IMPL = "import exc\n\n\ndef handle():\n    return exc.response_error\n"


def _mirror_responses() -> list[ModelResponse]:
    return [
        _write("test_thing.py", _TEST),
        _write("thing.py", _IMPL),
        _finish("done"),
    ]


def test_reviewer_spawned_on_different_model(tmp_path: Path) -> None:
    """A configured reviewer model + a wired spawn → ONE reviewer subagent spawned
    on that model, its SubResult folded into result.sub_results."""
    calls: list[tuple] = []

    def fake_spawn(instruction: str, engine, model) -> SubResult:
        calls.append((instruction, engine, model))
        return SubResult(
            task_id="rev1",
            engine="vllm-openai",
            model=model or "?",
            status=OK,
            summary="reviewer: response_error is wrong; botocore uses .response",
        )

    result = run(
        scripted(_mirror_responses()),
        Task.new(str(tmp_path), "write a test and impl"),
        max_steps=6,
        context=ContextControls(
            testintegrity=True, testintegrity_reviewer_model="reviewer-model-x"
        ),
        spawns=Spawns(single=fake_spawn),
    )
    assert result.status == OK
    assert result.test_integrity_report is not None
    # Exactly one reviewer spawn, on the configured DIFFERENT model.
    assert len(calls) == 1
    _instruction, _engine, model = calls[0]
    assert model == "reviewer-model-x"
    assert "response_error" in _instruction
    # The reviewer's verdict is folded into the parent's sub_results.
    assert len(result.sub_results) == 1
    assert result.sub_results[0].task_id == "rev1"
    assert "botocore uses .response" in result.sub_results[0].summary


def test_no_reviewer_model_is_record_only(tmp_path: Path) -> None:
    """No reviewer model configured → the finding is recorded but no reviewer spawns."""
    calls: list[tuple] = []

    def fake_spawn(instruction: str, engine, model) -> SubResult:
        calls.append((instruction, engine, model))
        return SubResult(task_id="x", engine="e", model="m", status=OK)

    result = run(
        scripted(_mirror_responses()),
        Task.new(str(tmp_path), "write a test and impl"),
        max_steps=6,
        context=ContextControls(testintegrity=True),  # no reviewer model
        spawns=Spawns(single=fake_spawn),
    )
    assert result.status == OK
    assert result.test_integrity_report is not None
    assert calls == []  # record-only
    assert result.sub_results == []


def test_no_spawn_wired_is_record_only(tmp_path: Path) -> None:
    """Reviewer model set but no spawn callback wired → record-only, no crash."""
    result = run(
        scripted(_mirror_responses()),
        Task.new(str(tmp_path), "write a test and impl"),
        max_steps=6,
        context=ContextControls(
            testintegrity=True, testintegrity_reviewer_model="reviewer-model-x"
        ),
        # no spawns= → executor._spawn is None
    )
    assert result.status == OK
    assert result.test_integrity_report is not None
    assert result.sub_results == []


def test_no_findings_no_reviewer(tmp_path: Path) -> None:
    """No mirror → no reviewer spawn even with a reviewer model configured."""
    calls: list[tuple] = []

    def fake_spawn(instruction: str, engine, model) -> SubResult:
        calls.append((instruction, engine, model))
        return SubResult(task_id="x", engine="e", model="m", status=OK)

    result = run(
        scripted([_write("m.py", "x = 1\n"), _finish("done")]),
        Task.new(str(tmp_path), "write m.py"),
        max_steps=5,
        context=ContextControls(
            testintegrity=True, testintegrity_reviewer_model="reviewer-model-x"
        ),
        spawns=Spawns(single=fake_spawn),
    )
    assert result.status == OK
    assert result.test_integrity_report is None
    assert calls == []


def test_default_system_carries_nonloadbearing_nudge() -> None:
    """The advisory test-integrity nudge is present and explicitly non-load-bearing."""
    assert "check_test_integrity" in _DEFAULT_SYSTEM
    assert "REAL external API shape" in _DEFAULT_SYSTEM
    # Explicitly states the harness gate runs regardless (the nudge is not relied upon).
    assert "regardless" in _DEFAULT_SYSTEM
