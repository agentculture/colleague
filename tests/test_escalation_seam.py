"""Integration tests for the escalation seam wired into colleague/loop.py (t3, #106).

Tests confirm:
  1. A not-finished drive (step budget exhausted) escalates exactly once.
  2. Flag unset (default-off) → fake run NOT called; result is byte-identical.
  3. The aborted branch escalates before DriveAborted is re-raised.
  4. Idempotency: two runs with the same task_id → run called once total.
  5. Escalation failure (run returns exit=1 or raises) does not break the drive.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

import colleague.escalation as escalation_mod
from colleague.contract import Task
from colleague.loop import DriveAborted, ModelResponse, ToolCall, run

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_main_repo(tmp_path: Path) -> Path:
    """Simulate a main checkout: .git is a DIRECTORY."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    return repo


def _arm_escalation(monkeypatch, repo: Path) -> None:
    """Set all gates to pass: env flag + remote + gh available.

    No approvals.json → policy no-op → agtag allowed.
    """
    monkeypatch.setenv("COLLEAGUE_ESCALATE", "1")
    monkeypatch.setattr(escalation_mod, "has_remote", lambda _repo: True)
    monkeypatch.setattr(escalation_mod, "gh_available", lambda: True)


def _fake_run_success(calls: list) -> escalation_mod.run_culture.__class__:
    """Return a fake run_culture that records calls and returns a success payload."""

    def _fake(cli, args, *, root):
        calls.append({"cli": cli, "args": list(args), "root": root})
        # Simulate agtag printing the issue URL on success.
        return "exit=0\nhttps://github.com/example/repo/issues/42\n"

    return _fake


def _fake_run_failure(calls: list) -> escalation_mod.run_culture.__class__:
    """Return a fake run_culture that records calls and returns a failure payload."""

    def _fake(cli, args, *, root):
        calls.append({"cli": cli, "args": list(args), "root": root})
        return "exit=1\nerror: agtag not configured\n"

    return _fake


def _fake_run_raises(calls: list) -> escalation_mod.run_culture.__class__:
    """Return a fake run_culture that records calls and raises an exception."""

    def _fake(cli, args, *, root):
        calls.append({"cli": cli, "args": list(args), "root": root})
        raise RuntimeError("agtag subprocess exploded")

    return _fake


# ---------------------------------------------------------------------------
# Test 1 — not-finished drive escalates exactly once
# ---------------------------------------------------------------------------


def test_not_finished_escalates_once(tmp_path: Path, monkeypatch) -> None:
    """A drive that exhausts the step budget triggers the escalation seam exactly once.

    The fake run_culture must be called once with:
      - cli = "agtag"
      - args starting with ["issue", "post", ...]
    The body written to the tempfile must include the task_id.
    """
    repo = _make_main_repo(tmp_path)
    _arm_escalation(monkeypatch, repo)

    calls: list = []
    fake_run = _fake_run_success(calls)

    task = Task.new(str(repo), "work that will exceed the step budget")
    # Store the task_id so we can check it appears in the body.
    task_id = task.id

    def budget_exhausting_complete(_messages):
        return ModelResponse(tool_calls=[ToolCall("1", "list_dir", {"path": "."})])

    with patch.object(escalation_mod, "run_culture", fake_run):
        result = run(budget_exhausting_complete, task, max_steps=2)

    assert result.not_finished is True, "Drive must be marked not_finished"

    # Escalation must fire exactly once.
    assert len(calls) == 1, f"Expected 1 escalation call, got {len(calls)}: {calls}"

    call = calls[0]
    assert call["cli"] == "agtag", f"Expected cli='agtag', got {call['cli']!r}"
    assert call["args"][0] == "issue", f"Expected args[0]='issue', got {call['args'][0]!r}"
    assert call["args"][1] == "post", f"Expected args[1]='post', got {call['args'][1]!r}"
    assert "--title" in call["args"], f"Expected --title in args: {call['args']}"
    assert "--body-file" in call["args"], f"Expected --body-file in args: {call['args']}"

    # The title must mention the task_id.
    title_idx = call["args"].index("--title") + 1
    title = call["args"][title_idx]
    assert task_id in title, f"Expected task_id {task_id!r} in title {title!r}"

    # Verify the marker was written (idempotency marker).
    marker = repo / ".colleague" / f"{task_id}.escalation.json"
    assert marker.is_file(), "Escalation marker must be written on success"


def test_not_finished_body_contains_task_id_and_continuation(tmp_path: Path, monkeypatch) -> None:
    """The body passed via --body-file must include the task_id and continuation sections."""
    repo = _make_main_repo(tmp_path)
    _arm_escalation(monkeypatch, repo)

    body_captured: list[str] = []

    def capturing_run(cli, args, *, root):
        # Read the body file and capture it.
        if "--body-file" in args:
            body_file_idx = args.index("--body-file") + 1
            body_path = Path(args[body_file_idx])
            if body_path.is_file():
                body_captured.append(body_path.read_text(encoding="utf-8"))
        return "exit=0\nhttps://github.com/example/repo/issues/99\n"

    task = Task.new(str(repo), "improve the login module")
    task_id = task.id

    def exhausting(_messages):
        return ModelResponse(tool_calls=[ToolCall("1", "list_dir", {"path": "."})])

    with patch.object(escalation_mod, "run_culture", capturing_run):
        run(exhausting, task, max_steps=2)

    assert body_captured, "Body file was not read by the capturing fake run"
    body = body_captured[0]
    assert task_id in body, f"task_id {task_id!r} not found in body"
    # Verify at least one continuation section heading is present.
    assert "##" in body, "Body must contain markdown section headings"
    assert "Continuation State" in body or "continuation" in body.lower()


# ---------------------------------------------------------------------------
# Test 2 — default-off (flag unset) is byte-identical
# ---------------------------------------------------------------------------


def test_default_off_no_escalation(tmp_path: Path, monkeypatch) -> None:
    """With COLLEAGUE_ESCALATE unset, escalation never fires and result is unchanged.

    This is the byte-identical honesty condition h1 — the drive result must be
    identical to a pre-escalation run when the flag is not set.
    """
    monkeypatch.delenv("COLLEAGUE_ESCALATE", raising=False)
    monkeypatch.delenv("CONVERTIBLE_ESCALATE", raising=False)

    repo = _make_main_repo(tmp_path)
    calls: list = []
    fake_run = _fake_run_success(calls)

    task = Task.new(str(repo), "work that exceeds budget")

    def exhausting(_messages):
        return ModelResponse(tool_calls=[ToolCall("1", "list_dir", {"path": "."})])

    with patch.object(escalation_mod, "run_culture", fake_run):
        result = run(exhausting, task, max_steps=2)

    # run_culture must never be called.
    assert len(calls) == 0, (
        f"run_culture was called {len(calls)} time(s) with flag unset — "
        "escalation must be default-off"
    )

    # The result is still correctly formed (the drive happened, not_finished is set).
    assert result.not_finished is True
    assert result.task_id == task.id


def test_default_off_result_unchanged_on_finish(tmp_path: Path, monkeypatch) -> None:
    """A clean finish with the flag unset never triggers escalation."""
    monkeypatch.delenv("COLLEAGUE_ESCALATE", raising=False)
    monkeypatch.delenv("CONVERTIBLE_ESCALATE", raising=False)

    repo = _make_main_repo(tmp_path)
    calls: list = []
    fake_run = _fake_run_success(calls)

    task = Task.new(str(repo), "quick finish")

    def finisher(_messages):
        return ModelResponse(tool_calls=[ToolCall("1", "finish", {"summary": "done"})])

    with patch.object(escalation_mod, "run_culture", fake_run):
        result = run(finisher, task, max_steps=5)

    assert len(calls) == 0, "run_culture must not be called on a clean finish"
    assert result.not_finished is False


# ---------------------------------------------------------------------------
# Test 3 — aborted branch escalates before DriveAborted is re-raised
# ---------------------------------------------------------------------------


def test_aborted_branch_escalates_before_reraise(tmp_path: Path, monkeypatch) -> None:
    """When the engine raises (DriveAborted path), escalation fires before re-raise.

    The test catches DriveAborted and verifies run_culture was called once.
    """
    repo = _make_main_repo(tmp_path)
    _arm_escalation(monkeypatch, repo)

    calls: list = []
    fake_run = _fake_run_success(calls)

    task = Task.new(str(repo), "task that causes engine failure")

    call_count = {"n": 0}

    def exploding_complete(_messages):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("engine exploded mid-drive")
        return ModelResponse(tool_calls=[ToolCall("1", "list_dir", {"path": "."})])

    with patch.object(escalation_mod, "run_culture", fake_run):
        with pytest.raises(DriveAborted):
            run(exploding_complete, task, max_steps=10)

    # Escalation must have fired exactly once (before the re-raise).
    assert len(calls) == 1, f"Expected 1 escalation call on aborted path, got {len(calls)}: {calls}"
    assert calls[0]["cli"] == "agtag"
    assert calls[0]["args"][0] == "issue"
    assert calls[0]["args"][1] == "post"


# ---------------------------------------------------------------------------
# Test 4 — idempotency: second run with same task_id → run called once total
# ---------------------------------------------------------------------------


def test_idempotent_two_runs_same_task_id(tmp_path: Path, monkeypatch) -> None:
    """Two drives with the same task_id trigger run_culture exactly once total.

    The marker written after the first successful post blocks the second.
    """
    repo = _make_main_repo(tmp_path)
    _arm_escalation(monkeypatch, repo)

    calls: list = []
    fake_run = _fake_run_success(calls)

    # Build a fixed task_id by constructing the task manually.
    task = Task.new(str(repo), "idempotent task")
    task_id = task.id

    def exhausting(_messages):
        return ModelResponse(tool_calls=[ToolCall("1", "list_dir", {"path": "."})])

    with patch.object(escalation_mod, "run_culture", fake_run):
        # First drive: marker does not exist yet.
        run(exhausting, task, max_steps=2)

        # Second drive with a NEW task object but the SAME task_id — marker exists.
        task2 = Task.new(str(repo), "idempotent task again")
        object.__setattr__(task2, "id", task_id)  # force the same id

        run(exhausting, task2, max_steps=2)

    # run_culture must have been called exactly once across both runs.
    assert (
        len(calls) == 1
    ), f"Expected 1 escalation call across two runs (idempotency), got {len(calls)}"


# ---------------------------------------------------------------------------
# Test 5 — escalation failure does not break the drive
# ---------------------------------------------------------------------------


def test_escalation_failure_does_not_mask_result(tmp_path: Path, monkeypatch) -> None:
    """If run_culture returns exit=1, the drive result is still returned normally.

    The escalation is best-effort and observe-only — a failed post must never
    mask or alter the TaskResult.
    """
    repo = _make_main_repo(tmp_path)
    _arm_escalation(monkeypatch, repo)

    calls: list = []
    fake_run = _fake_run_failure(calls)

    task = Task.new(str(repo), "failing escalation task")

    def exhausting(_messages):
        return ModelResponse(tool_calls=[ToolCall("1", "list_dir", {"path": "."})])

    with patch.object(escalation_mod, "run_culture", fake_run):
        result = run(exhausting, task, max_steps=2)

    # The drive must still produce a valid result.
    assert result is not None
    assert result.not_finished is True
    assert result.task_id == task.id

    # run_culture was called (the attempt was made).
    assert len(calls) == 1

    # But the marker must NOT be written (failed post → no marker → can retry).
    marker = repo / ".colleague" / f"{task.id}.escalation.json"
    assert not marker.is_file(), "Marker must not be written when run_culture fails"


def test_escalation_exception_does_not_mask_result(tmp_path: Path, monkeypatch) -> None:
    """If run_culture raises, the drive result is still returned normally.

    suppress(Exception) in the wiring must swallow any escalation error.
    """
    repo = _make_main_repo(tmp_path)
    _arm_escalation(monkeypatch, repo)

    calls: list = []
    fake_run = _fake_run_raises(calls)

    task = Task.new(str(repo), "raising escalation task")

    def exhausting(_messages):
        return ModelResponse(tool_calls=[ToolCall("1", "list_dir", {"path": "."})])

    with patch.object(escalation_mod, "run_culture", fake_run):
        result = run(exhausting, task, max_steps=2)

    assert result is not None
    assert result.not_finished is True

    # The exception must NOT have bubbled up; the drive result is intact.
    assert result.task_id == task.id

    # No marker written on exception.
    marker = repo / ".colleague" / f"{task.id}.escalation.json"
    assert not marker.is_file()


def test_escalation_exception_on_aborted_path_does_not_mask_driveaborted(
    tmp_path: Path, monkeypatch
) -> None:
    """If escalation raises on the aborted path, DriveAborted is still re-raised normally."""
    repo = _make_main_repo(tmp_path)
    _arm_escalation(monkeypatch, repo)

    calls: list = []
    fake_run = _fake_run_raises(calls)

    task = Task.new(str(repo), "aborted with failing escalation")

    call_count = {"n": 0}

    def exploding_complete(_messages):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("engine failure")
        return ModelResponse(tool_calls=[ToolCall("1", "list_dir", {"path": "."})])

    with patch.object(escalation_mod, "run_culture", fake_run):
        with pytest.raises(DriveAborted) as exc_info:
            run(exploding_complete, task, max_steps=10)

    # DriveAborted must carry the partial result.
    assert exc_info.value.result is not None
    # The escalation was attempted.
    assert len(calls) == 1
