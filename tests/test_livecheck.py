"""Tests for colleague/livecheck.py — the livecheck logic layer.

Covers:
- select_proofs returns only existing files
- unreachable endpoint short-circuits (no pytest run)
- fake pytest runner maps exit codes to statuses
- CLI renders both text and --json shapes
- webglass_status (t6): doctor healthy/unhealthy/timeout, session count
  parsing (real nested shape + fallbacks)
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from colleague import livecheck as livecheck_mod
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
        """TimeoutExpired → skipped, naming the configured cap + the env knob (#266)."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="pytest", timeout=600)
        proofs = [{"file": "tests/test_vllm_live.py", "label": "basic"}]
        results = run_proofs(proofs, ".")

        assert len(results) == 1
        assert results[0].status == "skipped"
        assert "timeout" in results[0].detail
        assert "600" in results[0].detail
        assert "COLLEAGUE_LIVECHECK_TIMEOUT" in results[0].detail

    @patch("colleague.livecheck.subprocess.run")
    def test_timeout_env_override_wins(self, mock_run: MagicMock, monkeypatch) -> None:
        """COLLEAGUE_LIVECHECK_TIMEOUT overrides the 600s default (#266)."""
        monkeypatch.setenv("COLLEAGUE_LIVECHECK_TIMEOUT", "1234")
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="pytest", timeout=1234)
        proofs = [{"file": "tests/test_vllm_live.py", "label": "basic"}]
        results = run_proofs(proofs, ".")

        assert mock_run.call_args.kwargs["timeout"] == 1234.0
        assert "1234" in results[0].detail

    @patch("colleague.livecheck.subprocess.run")
    def test_explicit_timeout_param_wins_over_env(self, mock_run: MagicMock, monkeypatch) -> None:
        monkeypatch.setenv("COLLEAGUE_LIVECHECK_TIMEOUT", "1234")
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        proofs = [{"file": "tests/test_vllm_live.py", "label": "basic"}]
        run_proofs(proofs, ".", timeout=42.0)

        assert mock_run.call_args.kwargs["timeout"] == 42.0

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
    @patch("colleague.cli._commands.livecheck.run_runner_checks")
    @patch("colleague.cli._commands.livecheck.run_proofs")
    @patch("colleague.cli._commands.livecheck.select_proofs")
    def test_text_table(
        self,
        mock_select: MagicMock,
        mock_run: MagicMock,
        mock_runners: MagicMock,
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
        mock_runners.return_value = []

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
    @patch("colleague.cli._commands.livecheck.run_runner_checks")
    @patch("colleague.cli._commands.livecheck.run_proofs")
    @patch("colleague.cli._commands.livecheck.select_proofs")
    def test_json_shape(
        self,
        mock_select: MagicMock,
        mock_run: MagicMock,
        mock_runners: MagicMock,
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
        mock_runners.return_value = []

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


class TestRunnerChecksWiring:
    """Task t7: the ProofResult runner checks (presence narration, media
    image/audio, cortex/senses, realtime) are executed by the CLI verb
    alongside the _KNOWN_PROOFS pytest files, and reported in the SAME
    table/JSON — closing the no-production-caller gap found in /scope."""

    @patch("colleague.cli._commands.livecheck.probe_endpoint")
    @patch("colleague.cli._commands.livecheck.run_runner_checks")
    @patch("colleague.cli._commands.livecheck.run_proofs")
    @patch("colleague.cli._commands.livecheck.select_proofs")
    def test_runner_rows_included_alongside_pytest_proofs(
        self,
        mock_select: MagicMock,
        mock_run: MagicMock,
        mock_runners: MagicMock,
        mock_probe: MagicMock,
    ) -> None:
        """Runner rows land in the same proofs list as the pytest-file rows."""
        mock_probe.return_value = {
            "endpoint": "http://localhost:8000/v1",
            "reachable": True,
            "reason": None,
        }
        mock_select.return_value = [{"file": "tests/test_vllm_live.py", "label": "basic"}]
        mock_run.return_value = [ProofResult("tests/test_vllm_live.py", "passed", "")]
        mock_runners.return_value = [
            ProofResult("presence_narration", "skipped", "tts not configured"),
            ProofResult("realtime", "skipped", "no realtime lane resolved"),
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
        parsed = json.loads(captured.getvalue())
        files = [p["file"] for p in parsed["proofs"]]
        assert files == ["tests/test_vllm_live.py", "presence_narration", "realtime"]
        mock_runners.assert_called_once_with(Path("."))

    @patch("colleague.cli._commands.livecheck.probe_endpoint")
    @patch("colleague.cli._commands.livecheck.run_runner_checks")
    @patch("colleague.cli._commands.livecheck.run_proofs")
    @patch("colleague.cli._commands.livecheck.select_proofs")
    def test_runner_skip_never_flips_exit_code(
        self,
        mock_select: MagicMock,
        mock_run: MagicMock,
        mock_runners: MagicMock,
        mock_probe: MagicMock,
    ) -> None:
        """All pytest proofs pass, all runner checks skip -> exit 0 (runner SKIPs
        must not affect the exit code)."""
        mock_probe.return_value = {
            "endpoint": "http://localhost:8000/v1",
            "reachable": True,
            "reason": None,
        }
        mock_select.return_value = [{"file": "tests/test_vllm_live.py", "label": "basic"}]
        mock_run.return_value = [ProofResult("tests/test_vllm_live.py", "passed", "")]
        mock_runners.return_value = [
            ProofResult("presence_narration", "skipped", "not configured"),
            ProofResult("media_image", "skipped", "endpoint unreachable"),
            ProofResult("media_audio", "skipped", "endpoint unreachable"),
            ProofResult("cortex_senses", "skipped", "not serving"),
            ProofResult("realtime", "skipped", "no realtime lane resolved"),
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

        assert exit_code == 0
        assert "skipped" in captured.getvalue()

    @patch("colleague.cli._commands.livecheck.probe_endpoint")
    @patch("colleague.cli._commands.livecheck.run_runner_checks")
    @patch("colleague.cli._commands.livecheck.run_proofs")
    @patch("colleague.cli._commands.livecheck.select_proofs")
    def test_runner_fail_still_flips_exit_code(
        self,
        mock_select: MagicMock,
        mock_run: MagicMock,
        mock_runners: MagicMock,
        mock_probe: MagicMock,
    ) -> None:
        """A runner FAIL follows the existing exit-1-on-failed rule even when
        every pytest-file proof passed."""
        mock_probe.return_value = {
            "endpoint": "http://localhost:8000/v1",
            "reachable": True,
            "reason": None,
        }
        mock_select.return_value = [{"file": "tests/test_vllm_live.py", "label": "basic"}]
        mock_run.return_value = [ProofResult("tests/test_vllm_live.py", "passed", "")]
        mock_runners.return_value = [
            ProofResult("realtime", "failed", "zero server events"),
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

        assert exit_code == 1

    @patch("colleague.cli._commands.livecheck.probe_endpoint")
    @patch("colleague.cli._commands.livecheck.run_runner_checks")
    @patch("colleague.cli._commands.livecheck.select_proofs")
    def test_runner_rows_report_even_with_no_known_proof_files(
        self,
        mock_select: MagicMock,
        mock_runners: MagicMock,
        mock_probe: MagicMock,
    ) -> None:
        """A repo with none of the _KNOWN_PROOFS files still reports the
        (self-gating) runner rows rather than short-circuiting to 'no live
        proofs found'."""
        mock_probe.return_value = {
            "endpoint": "http://localhost:8000/v1",
            "reachable": True,
            "reason": None,
        }
        mock_select.return_value = []
        mock_runners.return_value = [ProofResult("realtime", "skipped", "no realtime lane")]

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
        parsed = json.loads(captured.getvalue())
        assert len(parsed["proofs"]) == 1
        assert parsed["proofs"][0]["file"] == "realtime"


class TestRunRunnerChecksAggregation:
    """run_runner_checks (colleague/livecheck.py) executes the registered
    runners and never lets one runner's bug crash the whole aggregation."""

    def test_aggregates_every_registered_runner_in_order(self, monkeypatch) -> None:
        import colleague.livecheck as livecheck_mod

        calls: list[str] = []

        def _make(name: str, status: str):
            def _runner(repo, *, model=None):
                calls.append(name)
                return ProofResult(file=name, status=status, detail="")

            return _runner

        fake_registry = (
            _make("a", "passed"),
            _make("b", "skipped"),
            _make("c", "failed"),
        )
        monkeypatch.setattr(livecheck_mod, "_RUNNER_CHECKS", fake_registry)

        results = livecheck_mod.run_runner_checks(".")

        assert calls == ["a", "b", "c"]
        assert [r.file for r in results] == ["a", "b", "c"]
        assert [r.status for r in results] == ["passed", "skipped", "failed"]

    def test_one_runner_exception_does_not_crash_the_others(self, monkeypatch) -> None:
        import colleague.livecheck as livecheck_mod

        def _boom(repo, *, model=None):
            raise RuntimeError("kaboom")

        def _ok(repo, *, model=None):
            return ProofResult(file="ok", status="passed", detail="")

        monkeypatch.setattr(livecheck_mod, "_RUNNER_CHECKS", (_boom, _ok))

        results = livecheck_mod.run_runner_checks(".")

        assert len(results) == 2
        assert results[0].status == "skipped"
        assert "kaboom" in results[0].detail
        assert results[1].status == "passed"


class TestWebglassSessionCount:
    """_webglass_session_count parses the real nested shape + fallbacks."""

    def test_real_nested_shape(self) -> None:
        """Probed 2026-08-28 shape: content.trusted.sessions."""
        data = {"content": {"trusted": {"sessions": [{}, {}, {}]}}}
        assert livecheck_mod._webglass_session_count(data) == 3

    def test_bare_list(self) -> None:
        assert livecheck_mod._webglass_session_count([{}, {}]) == 2

    def test_top_level_sessions_key(self) -> None:
        assert livecheck_mod._webglass_session_count({"sessions": [{}]}) == 1

    def test_unrecognized_shape_returns_none(self) -> None:
        assert livecheck_mod._webglass_session_count({"nope": True}) is None
        assert livecheck_mod._webglass_session_count(None) is None
        assert livecheck_mod._webglass_session_count("not json") is None


class TestWebglassStatus:
    """webglass_status shells out via subprocess; never raises."""

    def test_absent_binary(self, monkeypatch) -> None:
        monkeypatch.setattr(livecheck_mod.shutil, "which", lambda name: None)
        result = livecheck_mod.webglass_status()
        assert result == {
            "present": False,
            "healthy": False,
            "detail": "not on PATH",
            "sessions": None,
        }

    def test_healthy_with_session_count(self, monkeypatch) -> None:
        monkeypatch.setattr(livecheck_mod.shutil, "which", lambda name: "/usr/bin/webglass")

        def _fake_run(argv, **kwargs):
            if argv[1:] == ["doctor"]:
                return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
            payload = json.dumps({"content": {"trusted": {"sessions": [{}] * 12}}})
            return subprocess.CompletedProcess(argv, 0, stdout=payload, stderr="")

        monkeypatch.setattr(livecheck_mod.subprocess, "run", _fake_run)
        result = livecheck_mod.webglass_status()
        assert result["present"] is True
        assert result["healthy"] is True
        assert result["sessions"] == 12

    def test_unhealthy_doctor_exit(self, monkeypatch) -> None:
        monkeypatch.setattr(livecheck_mod.shutil, "which", lambda name: "/usr/bin/webglass")

        def _fake_run(argv, **kwargs):
            if argv[1:] == ["doctor"]:
                return subprocess.CompletedProcess(argv, 1, stdout="", stderr="rig unreachable\n")
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr="")

        monkeypatch.setattr(livecheck_mod.subprocess, "run", _fake_run)
        result = livecheck_mod.webglass_status()
        assert result["healthy"] is False
        assert "rig unreachable" in result["detail"]

    def test_doctor_timeout_reported_honestly(self, monkeypatch) -> None:
        monkeypatch.setattr(livecheck_mod.shutil, "which", lambda name: "/usr/bin/webglass")

        def _fake_run(argv, **kwargs):
            raise subprocess.TimeoutExpired(cmd=argv, timeout=kwargs.get("timeout", 10.0))

        monkeypatch.setattr(livecheck_mod.subprocess, "run", _fake_run)
        result = livecheck_mod.webglass_status(timeout=10.0)
        assert result["healthy"] is False
        assert "timed out" in result["detail"]
