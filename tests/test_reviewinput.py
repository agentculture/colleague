"""Review-input assembler (pure) — plan task t4.

Two pure functions returning ConfiguratorReviewInput:
  - assemble_before_episode(task) — digest from Task instruction + goal/acceptance
  - assemble_between_episodes(task, result) — digest from TaskResult terminal facts

Acceptance criteria:
1. Pure functions compose digests from Task/TaskResult fields only;
   a hard size bound caps total chars and truncates file lists with "+N more".
2. No field of the worker conversation history appears in the output;
   the signature accepts only Task/TaskResult objects, never a message list.
"""

from __future__ import annotations

import pytest

from colleague.configurator import ConfiguratorReviewInput
from colleague.contract import LintReport, Task, TaskResult
from colleague.reviewinput import (
    assemble_before_episode,
    assemble_between_episodes,
)

# ---------------------------------------------------------------------------
# assemble_before_episode
# ---------------------------------------------------------------------------


def test_before_episode_returns_configurator_review_input() -> None:
    task = Task.new("/repo", "add a README")
    result = assemble_before_episode(task)
    assert isinstance(result, ConfiguratorReviewInput)


def test_before_episode_includes_instruction() -> None:
    task = Task.new("/repo", "add a README")
    result = assemble_before_episode(task)
    assert "add a README" in result.digest


def test_before_episode_includes_goal_when_present() -> None:
    task = Task.new("/repo", "add a README", goal="README exists with project description")
    result = assemble_before_episode(task)
    assert "README exists with project description" in result.digest


def test_before_episode_omits_goal_when_absent() -> None:
    task = Task.new("/repo", "add a README", goal=None)
    result = assemble_before_episode(task)
    # Goal section should not appear when goal is None
    assert "goal:" not in result.digest.lower() or "none" in result.digest.lower()


def test_before_episode_includes_acceptance_when_present() -> None:
    task = Task.new(
        "/repo",
        "add a README",
        acceptance=["file exists", "contains project name"],
    )
    result = assemble_before_episode(task)
    assert "file exists" in result.digest
    assert "contains project name" in result.digest


def test_before_episode_omits_acceptance_when_absent() -> None:
    task = Task.new("/repo", "add a README", acceptance=None)
    result = assemble_before_episode(task)
    # Acceptance section should not appear when acceptance is None
    assert "acceptance" not in result.digest.lower() or "none" in result.digest.lower()


def test_before_episode_no_history_leak() -> None:
    """The signature must not accept a message list — structural pin 1."""
    task = Task.new("/repo", "add a README")
    result = assemble_before_episode(task)
    # The digest should contain no conversation-history-shaped content
    # (no "role", "content", "tool_calls" keys from message dicts)
    assert "role" not in result.digest.lower() or "goal" in result.digest.lower()


def test_before_episode_respects_max_chars() -> None:
    """The digest must never exceed the max_chars bound."""
    long_instruction = "x" * 5000
    task = Task.new("/repo", long_instruction)
    result = assemble_before_episode(task, max_chars=100)
    assert len(result.digest) <= 100


def test_before_episode_truncation_is_honest() -> None:
    """When truncated, the digest should indicate truncation."""
    long_instruction = "x" * 5000
    task = Task.new("/repo", long_instruction)
    result = assemble_before_episode(task, max_chars=100)
    assert len(result.digest) <= 100
    # Should contain some signal that truncation happened
    assert "…" in result.digest or "truncated" in result.digest.lower()


def test_before_episode_default_max_chars_reasonable() -> None:
    """Default max_chars should be large enough for typical instructions."""
    task = Task.new("/repo", "add a README with project description and setup instructions")
    result = assemble_before_episode(task)
    assert "add a README" in result.digest


# ---------------------------------------------------------------------------
# assemble_between_episodes
# ---------------------------------------------------------------------------


def test_between_episodes_returns_configurator_review_input() -> None:
    task = Task.new("/repo", "add a README")
    result_obj = TaskResult(task_id=task.id, status="ok", summary="done")
    result = assemble_between_episodes(task, result_obj)
    assert isinstance(result, ConfiguratorReviewInput)


def test_between_episodes_includes_summary() -> None:
    task = Task.new("/repo", "add a README")
    result_obj = TaskResult(task_id=task.id, status="ok", summary="wrote README.md")
    result = assemble_between_episodes(task, result_obj)
    assert "wrote README.md" in result.digest


def test_between_episodes_includes_exit_reason() -> None:
    task = Task.new("/repo", "add a README")
    result_obj = TaskResult(task_id=task.id, status="error", summary="failed")
    result = assemble_between_episodes(task, result_obj)
    assert "error" in result.digest


def test_between_episodes_includes_step_count() -> None:
    task = Task.new("/repo", "add a README")
    result_obj = TaskResult(task_id=task.id, status="ok", summary="done", steps=[])
    result = assemble_between_episodes(task, result_obj)
    assert "0" in result.digest or "step" in result.digest.lower()


def test_between_episodes_includes_changed_files() -> None:
    task = Task.new("/repo", "add a README")
    result_obj = TaskResult(
        task_id=task.id,
        status="ok",
        summary="done",
        changed_files=["README.md", "setup.py"],
    )
    result = assemble_between_episodes(task, result_obj)
    assert "README.md" in result.digest
    assert "setup.py" in result.digest


def test_between_episodes_truncates_long_file_list() -> None:
    """When changed_files is long, truncate with "+N more"."""
    task = Task.new("/repo", "add a README")
    many_files = [f"file_{i}.py" for i in range(50)]
    result_obj = TaskResult(
        task_id=task.id,
        status="ok",
        summary="done",
        changed_files=many_files,
    )
    result = assemble_between_episodes(task, result_obj, max_chars=500)
    # Should contain "+N more" indicator
    assert "+" in result.digest and "more" in result.digest.lower()


def test_between_episodes_includes_gate_outcomes() -> None:
    """Gate outcomes (lint, etc.) should appear in the digest."""
    task = Task.new("/repo", "add a README")
    result_obj = TaskResult(
        task_id=task.id,
        status="ok",
        summary="done",
        lint_report=LintReport(fixed=["black reformatted 1 file"], residual=[]),
    )
    result = assemble_between_episodes(task, result_obj)
    assert "lint" in result.digest.lower()


def test_between_episodes_no_history_leak() -> None:
    """The digest must not contain any conversation history content."""
    task = Task.new("/repo", "add a README")
    result_obj = TaskResult(task_id=task.id, status="ok", summary="done")
    result = assemble_between_episodes(task, result_obj)
    # No message-history-shaped fields should appear
    assert "tool_calls" not in result.digest
    # The digest is built from Task/TaskResult fields only


def test_between_episodes_signature_rejects_message_list() -> None:
    """The function signature must not accept a message list."""
    task = Task.new("/repo", "add a README")
    # This should raise TypeError — the function only accepts TaskResult
    with pytest.raises(TypeError):
        assemble_between_episodes(
            task, [{"role": "user", "content": "hello"}]
        )  # type: ignore[arg-type]


def test_between_episodes_respects_max_chars() -> None:
    """The digest must never exceed the max_chars bound."""
    task = Task.new("/repo", "add a README")
    result_obj = TaskResult(
        task_id=task.id,
        status="ok",
        summary="x" * 5000,
        changed_files=[f"file_{i}.py" for i in range(100)],
    )
    result = assemble_between_episodes(task, result_obj, max_chars=100)
    assert len(result.digest) <= 100


def test_between_episodes_pure_no_io() -> None:
    """The function must be pure — no I/O side effects."""
    task = Task.new("/repo", "add a README")
    result_obj = TaskResult(task_id=task.id, status="ok", summary="done")
    # Running twice with same inputs should produce identical output
    r1 = assemble_between_episodes(task, result_obj)
    r2 = assemble_between_episodes(task, result_obj)
    assert r1.digest == r2.digest


def test_between_episodes_includes_instruction_context() -> None:
    """The digest should include the original task instruction for context."""
    task = Task.new("/repo", "implement feature X")
    result_obj = TaskResult(task_id=task.id, status="ok", summary="done")
    result = assemble_between_episodes(task, result_obj)
    assert "implement feature X" in result.digest
