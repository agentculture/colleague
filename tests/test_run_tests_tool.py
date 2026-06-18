"""Tests for the run_tests tool (t7).

Verifies:
- run_tests schema exists in SCHEMAS with optional "paths" arg
- _run_tests handler runs pytest and returns a summary string
- run_tests does NOT write any files (changed stays empty)
- curate_schemas("validator") includes run_tests but excludes write/edit/run_command
- Graceful degradation when subprocess raises (FileNotFoundError, TimeoutExpired, etc.)
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from colleague.tools import SCHEMAS, ToolExecutor, ToolOutcome

# ── helpers ────────────────────────────────────────────────────────────────


def _executor(tmp_path: Path) -> ToolExecutor:
    return ToolExecutor(tmp_path)


def _run_tests_schema() -> dict:
    """Return the run_tests schema entry, or raise."""
    for s in SCHEMAS:
        if s["function"]["name"] == "run_tests":
            return s
    raise ValueError("run_tests schema not found in SCHEMAS")


# ── schema presence ───────────────────────────────────────────────────────


class TestRunTestsSchema:
    def test_schema_exists(self):
        schema = _run_tests_schema()
        assert schema["function"]["name"] == "run_tests"

    def test_schema_has_optional_paths_arg(self):
        schema = _run_tests_schema()
        props = schema["function"]["parameters"]["properties"]
        assert "paths" in props
        assert props["paths"]["type"] == "array"
        assert props["paths"]["items"]["type"] == "string"
        # No required args
        assert (
            schema["function"]["parameters"].get("required") == []
            or schema["function"]["parameters"].get("required") is None
        )


# ── handler behaviour ────────────────────────────────────────────────────


class TestRunTestsHandler:
    def test_execute_dispatches_to_handler(self, tmp_path):
        ex = _executor(tmp_path)
        # Just verify dispatch doesn't raise for run_tests
        with patch.object(ex, "_run_tests", return_value=ToolOutcome(result="ok")) as mock:
            outcome = ex.execute("run_tests", {})
            mock.assert_called_once_with({})
            assert outcome.result == "ok"

    def test_no_paths_runs_pytest_in_root(self, tmp_path):
        ex = _executor(tmp_path)
        # Create a trivial passing test so pytest exits 0
        (tmp_path / "test_trivial.py").write_text("def test_ok(): pass\n")
        outcome = ex.execute("run_tests", {})
        assert isinstance(outcome.result, str)
        # Should contain some indication of success
        assert "passed" in outcome.result.lower() or "ok" in outcome.result.lower()

    def test_with_paths_arg(self, tmp_path):
        ex = _executor(tmp_path)
        (tmp_path / "test_specific.py").write_text("def test_specific(): assert True\n")
        outcome = ex.execute("run_tests", {"paths": ["test_specific.py"]})
        assert isinstance(outcome.result, str)

    def test_does_not_mutate_changed_files(self, tmp_path):
        """run_tests must NOT add anything to self.changed."""
        ex = _executor(tmp_path)
        (tmp_path / "test_ok.py").write_text("def test_ok(): pass\n")
        ex.execute("run_tests", {})
        assert ex.changed == set(), f"run_tests mutated changed: {ex.changed}"

    def test_failing_tests_returns_failure_summary(self, tmp_path):
        ex = _executor(tmp_path)
        (tmp_path / "test_fail.py").write_text("def test_fail(): assert False\n")
        outcome = ex.execute("run_tests", {"paths": ["test_fail.py"]})
        assert isinstance(outcome.result, str)
        assert "FAILED" in outcome.result or "failed" in outcome.result


# ── graceful degradation ──────────────────────────────────────────────────


class TestGracefulDegradation:
    def test_file_not_found_error_degrades(self, tmp_path):
        """When subprocess raises FileNotFoundError, return a string, not an exception."""
        ex = _executor(tmp_path)
        with patch("subprocess.run", side_effect=FileNotFoundError("no pytest")):
            outcome = ex.execute("run_tests", {})
            assert isinstance(outcome.result, str)
            assert "skipped" in outcome.result.lower() or "error" in outcome.result.lower()

    def test_timeout_expired_degrades(self, tmp_path):
        """When subprocess raises TimeoutExpired, return a string, not an exception."""
        ex = _executor(tmp_path)
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 30)):
            outcome = ex.execute("run_tests", {})
            assert isinstance(outcome.result, str)
            assert (
                "skipped" in outcome.result.lower()
                or "timeout" in outcome.result.lower()
                or "error" in outcome.result.lower()
            )

    def test_os_error_degrades(self, tmp_path):
        """When subprocess raises OSError, return a string, not an exception."""
        ex = _executor(tmp_path)
        with patch("subprocess.run", side_effect=OSError("launch failed")):
            outcome = ex.execute("run_tests", {})
            assert isinstance(outcome.result, str)


# ── validator role curation ──────────────────────────────────────────────


class TestValidatorCuration:
    def test_validator_includes_run_tests(self):
        from colleague.tools import curate_schemas

        schemas = curate_schemas("validator")
        names = {s["function"]["name"] for s in schemas}
        assert "run_tests" in names, "validator should include run_tests"

    def test_validator_excludes_write_tools(self):
        from colleague.tools import curate_schemas

        schemas = curate_schemas("validator")
        names = {s["function"]["name"] for s in schemas}
        for tool in ("write_file", "edit_file", "run_command"):
            assert tool not in names, f"validator must NOT include {tool}"
