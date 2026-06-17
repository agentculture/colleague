"""Test that TaskResult.affected_tests_report round-trips through to_dict/from_dict."""

from colleague.affectedtests import AffectedTestsReport
from colleague.contract import TaskResult


def _make_result(affected_tests_report=None):
    return TaskResult(
        task_id="abc123",
        status="ok",
        affected_tests_report=affected_tests_report,
    )


def test_round_trip_populated():
    report = AffectedTestsReport(
        status="passed",
        selected=["tests/test_foo.py", "tests/test_bar.py"],
        total=2,
        capped=False,
        passed=10,
        failed=0,
        reason=None,
    )
    result = _make_result(affected_tests_report=report)
    d = result.to_dict()
    assert "affected_tests_report" in d
    assert d["affected_tests_report"] == report.to_dict()

    restored = TaskResult.from_dict(d)
    assert restored.affected_tests_report is not None
    assert restored.affected_tests_report.status == "passed"
    assert restored.affected_tests_report.selected == ["tests/test_foo.py", "tests/test_bar.py"]
    assert restored.affected_tests_report.total == 2
    assert restored.affected_tests_report.capped is False
    assert restored.affected_tests_report.passed == 10
    assert restored.affected_tests_report.failed == 0
    assert restored.affected_tests_report.reason is None


def test_key_absent_when_none():
    result = _make_result()
    d = result.to_dict()
    assert "affected_tests_report" not in d

    # from_dict with no key should leave the field as None
    restored = TaskResult.from_dict(d)
    assert restored.affected_tests_report is None
