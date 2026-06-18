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


# ── read-only safety: option injection, path confinement, no tree writes ──


class TestRunTestsReadOnlySafety:
    """The validator role exposes run_tests *instead of* run_command precisely so a
    read-only role can run tests without a write surface. These pin that promise:
    no option injection, no path escape, and no files left behind (#221 qodo)."""

    def test_rejects_option_like_path(self, tmp_path):
        """A leading-dash arg (e.g. --junitxml=) is an option, not a test path."""
        ex = _executor(tmp_path)
        outcome = ex.execute("run_tests", {"paths": ["--junitxml=/tmp/out.xml"]})
        assert "invalid test path" in outcome.result.lower()
        assert not (tmp_path / "out.xml").exists()

    def test_rejects_short_option(self, tmp_path):
        ex = _executor(tmp_path)
        outcome = ex.execute("run_tests", {"paths": ["-p", "evilplugin"]})
        assert "invalid test path" in outcome.result.lower()

    def test_rejects_path_escaping_repo_root(self, tmp_path):
        """A ../ traversal must be refused before it reaches pytest."""
        ex = _executor(tmp_path)
        outcome = ex.execute("run_tests", {"paths": ["../outside.py"]})
        assert "escapes the repo root" in outcome.result.lower()

    def test_rejects_absolute_path_outside_root(self, tmp_path):
        ex = _executor(tmp_path)
        outcome = ex.execute("run_tests", {"paths": ["/etc/passwd"]})
        assert "escapes the repo root" in outcome.result.lower()

    def test_leaves_no_cache_artifacts(self, tmp_path):
        """A clean run must not drop .pytest_cache / __pycache__ into the tree —
        the read-only guarantee is literal (PYTHONDONTWRITEBYTECODE + no:cacheprovider)."""
        (tmp_path / "test_ok.py").write_text("def test_ok(): pass\n")
        ex = _executor(tmp_path)
        ex.execute("run_tests", {"paths": ["test_ok.py"]})
        leftovers = [
            p.name for p in tmp_path.rglob("*") if p.name in {".pytest_cache", "__pycache__"}
        ]
        assert leftovers == [], f"run_tests left cache artifacts: {leftovers}"

    def test_strips_env_injected_pytest_options(self, tmp_path, monkeypatch):
        """The ``--`` separator only guards CLI args; PYTEST_ADDOPTS / PYTEST_PLUGINS
        are honored from the env. A read-only run must NOT let an inherited env
        re-open the option/plugin-injection vector."""
        monkeypatch.setenv("PYTEST_ADDOPTS", f"--junitxml={tmp_path}/pwn.xml")
        monkeypatch.setenv("PYTEST_PLUGINS", "definitely_not_a_real_plugin")
        (tmp_path / "test_ok.py").write_text("def test_ok(): pass\n")
        ex = _executor(tmp_path)
        outcome = ex.execute("run_tests", {"paths": ["test_ok.py"]})
        # The injected --junitxml must NOT have produced a report, and the bogus
        # plugin must NOT have crashed the run (it would, if PYTEST_PLUGINS survived).
        assert not (tmp_path / "pwn.xml").exists(), "PYTEST_ADDOPTS was honored from env"
        assert "passed" in outcome.result.lower()


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
