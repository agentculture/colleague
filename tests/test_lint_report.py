"""LintReport dataclass and TaskResult.lint_report field (task t1)."""

from __future__ import annotations

from colleague.contract import LintReport, TaskResult


def test_empty_lint_report_omitted() -> None:
    """A TaskResult with lint_report=None omits the key from to_dict()."""
    result = TaskResult(task_id="t", status="ok")
    assert "lint_report" not in result.to_dict()


def test_lint_report_roundtrips() -> None:
    """A TaskResult with a populated LintReport round-trips through to_dict/from_dict."""
    lr = LintReport(
        fixed=["black reformatted 2 file(s)"],
        residual=["flake8 F811 colleague/x.py:10"],
        skipped=["ruff: not installed"],
    )
    tr = TaskResult(task_id="t", status="ok", lint_report=lr)
    reloaded = TaskResult.from_dict(tr.to_dict())
    assert reloaded == tr
    assert reloaded.lint_report is not None
    assert reloaded.lint_report.fixed == ["black reformatted 2 file(s)"]
    assert reloaded.lint_report.residual == ["flake8 F811 colleague/x.py:10"]
    assert reloaded.lint_report.skipped == ["ruff: not installed"]


def test_lint_report_dataclass_roundtrips() -> None:
    """A LintReport round-trips through to_dict/from_dict."""
    lr = LintReport(
        fixed=["a"],
        residual=["b"],
        skipped=["c"],
    )
    assert LintReport.from_dict(lr.to_dict()) == lr
