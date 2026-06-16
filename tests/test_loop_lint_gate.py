"""Pre-finish lint gate wired into the loop (#200, task t4).

Exercises the runtime integration via ``run()`` with a scripted ``complete``:
the gate runs the repo's configured linters on the changed files before the
result is finalized, auto-fixes, surfaces residual, and — on a clean finish with
residual — injects ONE bounded model fix-turn without clobbering the work item's
own summary. Default (no ContextControls.lint) is a strict no-op.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from colleague.contract import OK, Task
from colleague.loop import CompleteFn, ContextControls, ModelResponse, ToolCall, run


def scripted(responses: list[ModelResponse]) -> CompleteFn:
    state = {"i": 0}

    def complete(_messages: list[dict]) -> ModelResponse:
        i = min(state["i"], len(responses) - 1)
        state["i"] += 1
        return responses[i]

    return complete


def _write(tmp: Path, path: str, content: str) -> ModelResponse:
    return ModelResponse(
        tool_calls=[ToolCall("w", "write_file", {"path": path, "content": content})]
    )


def _finish(summary: str) -> ModelResponse:
    return ModelResponse(tool_calls=[ToolCall("f", "finish", {"summary": summary})])


def test_lint_disabled_is_strict_noop(tmp_path: Path) -> None:
    """Default run() (no ContextControls.lint) never touches lint_report."""
    (tmp_path / "pyproject.toml").write_text("[tool.black]\n")
    responses = [_write(tmp_path, "m.py", "x = {  'a':1 }\n"), _finish("done")]
    result = run(scripted(responses), Task.new(str(tmp_path), "write m.py"), max_steps=5)
    assert result.status == OK
    assert result.lint_report is None
    assert "lint_report" not in result.to_dict()


def test_lint_noop_when_no_linters_configured(tmp_path: Path) -> None:
    """Lint enabled but no linter configured → strict no-op (report None)."""
    responses = [_write(tmp_path, "m.py", "x=1\n"), _finish("done")]
    result = run(
        scripted(responses),
        Task.new(str(tmp_path), "write m.py"),
        max_steps=5,
        context=ContextControls(lint=True),
    )
    assert result.lint_report is None


@pytest.mark.skipif(shutil.which("black") is None, reason="black not installed")
def test_lint_black_autofixes_changed_file(tmp_path: Path) -> None:
    """A black-configured repo: the gate reformats the model's changed file."""
    (tmp_path / "pyproject.toml").write_text("[tool.black]\n")
    bad = "x = {  'a':1 }\n"
    responses = [_write(tmp_path, "m.py", bad), _finish("wrote m.py")]
    result = run(
        scripted(responses),
        Task.new(str(tmp_path), "write m.py"),
        max_steps=5,
        context=ContextControls(lint=True),
    )
    assert result.status == OK
    assert result.lint_report is not None
    assert (tmp_path / "m.py").read_text() != bad  # black reformatted it
    assert result.summary == "wrote m.py"  # gate did not clobber the summary


@pytest.mark.skipif(shutil.which("flake8") is None, reason="flake8 not installed")
def test_lint_surfaces_residual_without_fix_turn(tmp_path: Path) -> None:
    """flake8-configured repo, no fix-turn budget: residual is surfaced, not fixed."""
    (tmp_path / ".flake8").write_text("[flake8]\nmax-line-length = 88\n")
    responses = [_write(tmp_path, "m.py", "import os\nx = 1\n"), _finish("done")]
    result = run(
        scripted(responses),
        Task.new(str(tmp_path), "write m.py"),
        max_steps=5,
        context=ContextControls(lint=True, lint_fix_retries=0),
    )
    assert result.lint_report is not None
    assert any("F401" in line for line in result.lint_report.residual)
    assert (tmp_path / "m.py").read_text() == "import os\nx = 1\n"  # untouched (no fix-turn)


@pytest.mark.skipif(shutil.which("flake8") is None, reason="flake8 not installed")
def test_lint_bounded_fix_turn_resolves_and_preserves_summary(tmp_path: Path) -> None:
    """A clean finish with residual injects ONE fix-turn; the work summary survives."""
    (tmp_path / ".flake8").write_text("[flake8]\nmax-line-length = 88\n")
    responses = [
        _write(tmp_path, "m.py", "import os\nx = 1\n"),  # F401 unused import
        _finish("main work done"),
        _write(tmp_path, "m.py", "x = 1\n"),  # fix-turn removes the unused import
        _finish("fixed lint"),
    ]
    result = run(
        scripted(responses),
        Task.new(str(tmp_path), "write m.py"),
        max_steps=5,
        context=ContextControls(lint=True, lint_fix_retries=1),
    )
    assert result.lint_report is not None
    assert result.lint_report.residual == []  # the fix-turn cleared the F401
    assert (tmp_path / "m.py").read_text() == "x = 1\n"
    # The fix-turn's own finish must NOT become the work item's summary.
    assert result.summary == "main work done"
