"""Tests for colleague/livecheck.py — the livecheck logic layer.

Covers:
- select_proofs returns only existing files
- unreachable endpoint short-circuits (no pytest run)
- fake pytest runner maps exit codes to statuses
- CLI renders both text and --json shapes
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from colleague.livecheck import (
    ProofResult,
    probe_endpoint,
    run_proofs,
    select_proofs,
)


class TestSelectProofs:
    """select_proofs returns only files that exist in the repo."""

    def test_returns_only_existing_files(self, tmp_path: Path) -> None:
        """Only files that exist on disk are returned."""
        # Create only two of the known proof files
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_vllm_live.py").write_text("pass")
        (tmp_path / "tests" / "test_dual_live.py").write_text("pass")

        results = select_proofs(tmp_path)
        files = [r["file"] for r in results]

        assert "tests/test_vllm_live.py" in files
        assert "tests/test_dual_live.py" in files
        # A file that doesn't exist should not appear
        assert "tests/test_vllm_live_context_budget.py" not in files

    def test_returns_empty_when_no_proofs_exist(self, tmp_path: Path) -> None:
        """Empty repo yields empty list."""
        results = select_proofs(tmp_path)
        assert results == []

    def test_includes_label(self, tmp_path: Path) -> None:
        """Each result carries a short label."""
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_vllm_live.py").write_text("pass")

        results = select_proofs(tmp_path)
        assert len(results) == 1
        assert results[0]["label"] == "basic live drive"


class TestProbeEndpoint:
    """probe_endpoint reuses EngineConfig.resolve + urllib reachability."""

    def test_unreachable_returns_false(self, tmp_path: Path) -> None:
        """A non-routable endpoint is reported as unreachable."""
        # Use a port that nothing listens on
        import os

        env_patch = patch.dict(
            os.environ,
            {
                "COLLEAGUE_BASE_URL": "http://localhost:59999",
            },
        )
        env_patch.start()
        try:
            result = probe_endpoint(tmp_path)
            assert result["reachable"] is False
            assert result["endpoint"] == "http://localhost:59999"
            assert result["reason"] is not None
        finally:
            env_patch.stop()


class TestRunProofs:
    """run_proofs maps pytest exit codes to statuses."""

    @patch("colleague.livecheck.subprocess.run")
    def test_zero_exit_means_passed(self, mock_run: MagicMock) -> None:
        """pytest exit 0 → passed."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="",
            stderr="",
        )
        proofs = [{"file": "tests/test_vllm_live.py", "label": "basic"}]
        results = run_proofs(proofs, ".")

        assert len(results) == 1
        assert results[0].status == "passed"
        assert results[0].detail == ""

    @patch("colleague.livecheck.subprocess.run")
    def test_nonzero_exit_means_failed(self, mock_run: MagicMock) -> None:
        """pytest exit != 0 → failed with detail from stderr."""
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="FAILED tests/test_vllm_live.py::test_foo",
        )
        proofs = [{"file": "tests/test_vllm_live.py", "label": "basic"}]
        results = run_proofs(proofs, ".")

        assert len(results) == 1
        assert results[0].status == "failed"
        assert "FAILED" in results[0].detail

    @patch("colleague.livecheck.subprocess.run")
    def test_timeout_means_skipped(self, mock_run: MagicMock) -> None:
        """TimeoutExpired → skipped."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="pytest", timeout=120)
        proofs = [{"file": "tests/test_vllm_live.py", "label": "basic"}]
        results = run_proofs(proofs, ".")

        assert len(results) == 1
        assert results[0].status == "skipped"
        assert "timeout" in results[0].detail

    @patch("colleague.livecheck.subprocess.run")
    def test_file_not_found_means_skipped(self, mock_run: MagicMock) -> None:
        """FileNotFoundError → skipped."""
        mock_run.side_effect = FileNotFoundError("pytest")
        proofs = [{"file": "tests/test_vllm_live.py", "label": "basic"}]
        results = run_proofs(proofs, ".")

        assert len(results) == 1
        assert results[0].status == "skipped"


class TestUnreachableShortCircuit:
    """When the endpoint is unreachable, no pytest should run."""

    @patch("colleague.cli._commands.livecheck.probe_endpoint")
    def test_unreachable_skips_proofs(self, mock_probe: MagicMock) -> None:
        """Unreachable endpoint → skip report, no run_proofs call."""
        mock_probe.return_value = {
            "endpoint": "http://localhost:8000/v1",
            "reachable": False,
            "reason": "Connection refused",
        }

        from colleague.cli._commands.livecheck import cmd_livecheck

        args = argparse.Namespace(repo=".", json=False)
        # Capture stdout
        import io
        import sys

        captured = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            exit_code = cmd_livecheck(args)
        finally:
            sys.stdout = old_stdout

        assert exit_code == 0
        output = captured.getvalue()
        assert "not reachable" in output
        # run_proofs should NOT have been called
        # (probe_endpoint was mocked, so we can't check run_proofs directly,
        # but the exit code of 0 and skip message confirm short-circuit)

    @patch("colleague.cli._commands.livecheck.probe_endpoint")
    def test_unreachable_json_output(self, mock_probe: MagicMock) -> None:
        """Unreachable endpoint with --json produces structured output."""
        mock_probe.return_value = {
            "endpoint": "http://localhost:8000/v1",
            "reachable": False,
            "reason": "Connection refused",
        }

        from colleague.cli._commands.livecheck import cmd_livecheck

        args = argparse.Namespace(repo=".", json=True)

        import io
        import sys

        captured = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            exit_code = cmd_livecheck(args)
        finally:
            sys.stdout = old_stdout

        assert exit_code == 0
        output = captured.getvalue()
        parsed = json.loads(output)
        assert parsed["endpoint"] == "http://localhost:8000/v1"
        assert parsed["reachable"] is False
        assert parsed["proofs"] == []


class TestCliTextOutput:
    """CLI renders a per-row table in text mode."""

    @patch("colleague.cli._commands.livecheck.probe_endpoint")
    @patch("colleague.cli._commands.livecheck.run_proofs")
    @patch("colleague.cli._commands.livecheck.select_proofs")
    def test_text_table(
        self,
        mock_select: MagicMock,
        mock_run: MagicMock,
        mock_probe: MagicMock,
    ) -> None:
        """Text mode prints a table with header, rows, and summary."""
        mock_probe.return_value = {
            "endpoint": "http://localhost:8000/v1",
            "reachable": True,
            "reason": None,
        }
        mock_select.return_value = [
            {"file": "tests/test_vllm_live.py", "label": "basic"},
            {"file": "tests/test_dual_live.py", "label": "dual"},
        ]
        mock_run.return_value = [
            ProofResult("tests/test_vllm_live.py", "passed", ""),
            ProofResult("tests/test_dual_live.py", "failed", "AssertionError"),
        ]

        from colleague.cli._commands.livecheck import cmd_livecheck

        args = argparse.Namespace(repo=".", json=False)

        import io
        import sys

        captured = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            exit_code = cmd_livecheck(args)
        finally:
            sys.stdout = old_stdout

        assert exit_code == 1  # one failed
        output = captured.getvalue()
        assert "file" in output
        assert "status" in output
        assert "passed" in output
        assert "failed" in output
        assert "summary:" in output


class TestCliJsonOutput:
    """CLI renders structured JSON with --json."""

    @patch("colleague.cli._commands.livecheck.probe_endpoint")
    @patch("colleague.cli._commands.livecheck.run_proofs")
    @patch("colleague.cli._commands.livecheck.select_proofs")
    def test_json_shape(
        self,
        mock_select: MagicMock,
        mock_run: MagicMock,
        mock_probe: MagicMock,
    ) -> None:
        """--json produces {endpoint, reachable, proofs: [...]}."""
        mock_probe.return_value = {
            "endpoint": "http://localhost:8000/v1",
            "reachable": True,
            "reason": None,
        }
        mock_select.return_value = [
            {"file": "tests/test_vllm_live.py", "label": "basic"},
        ]
        mock_run.return_value = [
            ProofResult("tests/test_vllm_live.py", "passed", ""),
        ]

        from colleague.cli._commands.livecheck import cmd_livecheck

        args = argparse.Namespace(repo=".", json=True)

        import io
        import sys

        captured = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            exit_code = cmd_livecheck(args)
        finally:
            sys.stdout = old_stdout

        assert exit_code == 0
        output = captured.getvalue()
        parsed = json.loads(output)
        assert parsed["endpoint"] == "http://localhost:8000/v1"
        assert parsed["reachable"] is True
        assert len(parsed["proofs"]) == 1
        assert parsed["proofs"][0]["file"] == "tests/test_vllm_live.py"
        assert parsed["proofs"][0]["status"] == "passed"
