"""#203 acceptance fixtures — prove the two real false positives are CAUGHT.

Scenario 1 (AWS error mapping): a test file and an impl file that BOTH use the
WRONG attribute ``exc.response_error`` (the real botocore attribute is
``exc.response``).  The mirrored test PASSES on its own, but the test-integrity
gate flags ``response_error`` as a mirror signature.

Scenario 2 (Cost Explorer): a test file and an impl file that BOTH use the
WRONG dict key ``TotalEstimate`` (the real key is ``Total``).  Same pattern:
the test passes, the gate flags it.

These fixtures mechanically demonstrate "a test can actually fail now" —
execution alone misses the bug, the gate catches it.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

from colleague.contract import OK, Task
from colleague.loop import CompleteFn, ContextControls, ModelResponse, ToolCall, run
from colleague.testintegrity import detect_mirror

# ── helpers ──────────────────────────────────────────────────────────────


def _write_and_import_module(tmp_path: Path, name: str, source: str) -> types.ModuleType:
    """Write *source* to *tmp_path*/*name*.py and import it dynamically."""
    mod_path = tmp_path / f"{name}.py"
    mod_path.write_text(source)
    spec = importlib.util.spec_from_file_location(name, mod_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _scripted(responses: list[ModelResponse]) -> CompleteFn:
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


# ── Scenario 1: AWS error mapping (exc.response_error vs exc.response) ──


# Buggy impl: reads the WRONG attribute (botocore uses exc.response, not
# exc.response_error).
_AWS_IMPL = """\
def handle_error(exc):
    return exc.response_error
"""

# Mirrored test: uses the SAME wrong attribute, so it PASSES even though the
# impl is wrong against the real botocore API.
_AWS_TEST = """\
def test_handle_error():
    exc = type('E', (), {'response_error': 'AccessDenied'})()
    assert exc.response_error == 'AccessDenied'
"""


class TestScenario1AWS:
    """#203 Scenario 1: AWS error mapping — exc.response_error mirror."""

    def test_before_mirrored_test_passes(self, tmp_path: Path) -> None:
        """The mirrored test PASSES on its own — execution alone misses the bug.

        This is the 'before' demonstration: the test and impl agree on the
        wrong attribute, so pytest would mark it green.  The bug ships.
        """

        # Execute the test body in-process (no pytest needed).
        def test_handle_error():
            exc = type("E", (), {"response_error": "AccessDenied"})()
            assert exc.response_error == "AccessDenied"

        # This assertion PASSES — the mirrored test is green despite the bug.
        test_handle_error()

    def test_gate_catches_response_error(self, tmp_path: Path) -> None:
        """detect_mirror flags 'response_error' as a mirror signature."""
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "aws_impl.py").write_text(_AWS_IMPL)
        (repo / "test_aws_impl.py").write_text(_AWS_TEST)
        # A benign third file so the repo isn't empty.
        (repo / "other.py").write_text("x = 1\n")

        report = detect_mirror(str(repo), ["test_aws_impl.py", "aws_impl.py"])
        assert len(report.findings) >= 1
        symbols = {f.symbol for f in report.findings}
        assert "response_error" in symbols

        finding = next(f for f in report.findings if f.symbol == "response_error")
        assert finding.kind == "attribute"
        assert finding.test_file == "test_aws_impl.py"
        assert finding.impl_file == "aws_impl.py"

    def test_before_then_gate(self, tmp_path: Path) -> None:
        """Mechanical proof: the test passes AND the gate flags the symbol.

        This is the heart of #203 — a single test that shows both properties:
        1. The mirrored test passes (execution misses the bug).
        2. The test-integrity gate catches it (the symbol is flagged).
        """

        # Step 1: show the test passes.
        def test_handle_error():
            exc = type("E", (), {"response_error": "AccessDenied"})()
            assert exc.response_error == "AccessDenied"

        test_handle_error()  # passes — green, but wrong

        # Step 2: show the gate flags it.
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "aws_impl2.py").write_text(_AWS_IMPL)
        (repo / "test_aws_impl2.py").write_text(_AWS_TEST)
        (repo / "other.py").write_text("x = 1\n")

        report = detect_mirror(str(repo), ["test_aws_impl2.py", "aws_impl2.py"])
        symbols = {f.symbol for f in report.findings}
        assert "response_error" in symbols


# ── Scenario 2: Cost Explorer (TotalEstimate vs Total) ──────────────────


# Buggy impl: reads the WRONG dict key (the real API returns "Total", not
# "TotalEstimate").
_COST_IMPL = """\
def get_total(data):
    return data["TotalEstimate"]
"""

# Mirrored test: uses the SAME wrong key, so it PASSES even though the impl
# is wrong against the real Cost Explorer API.
_COST_TEST = """\
def test_get_total():
    data = {"TotalEstimate": 42}
    assert data["TotalEstimate"] == 42
"""


class TestScenario2CostExplorer:
    """#203 Scenario 2: Cost Explorer — TotalEstimate mirror."""

    def test_before_mirrored_test_passes(self, tmp_path: Path) -> None:
        """The mirrored test PASSES on its own — execution alone misses the bug."""

        def test_get_total():
            data = {"TotalEstimate": 42}
            assert data["TotalEstimate"] == 42

        # This assertion PASSES — the mirrored test is green despite the bug.
        test_get_total()

    def test_gate_catches_total_estimate(self, tmp_path: Path) -> None:
        """detect_mirror flags 'TotalEstimate' as a mirror signature."""
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "cost_impl.py").write_text(_COST_IMPL)
        (repo / "test_cost_impl.py").write_text(_COST_TEST)
        (repo / "other.py").write_text("x = 1\n")

        report = detect_mirror(str(repo), ["test_cost_impl.py", "cost_impl.py"])
        assert len(report.findings) >= 1
        symbols = {f.symbol for f in report.findings}
        assert "TotalEstimate" in symbols

        finding = next(f for f in report.findings if f.symbol == "TotalEstimate")
        assert finding.kind == "dict_key"
        assert finding.test_file == "test_cost_impl.py"
        assert finding.impl_file == "cost_impl.py"

    def test_before_then_gate(self, tmp_path: Path) -> None:
        """Mechanical proof: the test passes AND the gate flags the symbol."""

        # Step 1: show the test passes.
        def test_get_total():
            data = {"TotalEstimate": 42}
            assert data["TotalEstimate"] == 42

        test_get_total()  # passes — green, but wrong

        # Step 2: show the gate flags it.
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "cost_impl2.py").write_text(_COST_IMPL)
        (repo / "test_cost_impl2.py").write_text(_COST_TEST)
        (repo / "other.py").write_text("x = 1\n")

        report = detect_mirror(str(repo), ["test_cost_impl2.py", "cost_impl2.py"])
        symbols = {f.symbol for f in report.findings}
        assert "TotalEstimate" in symbols


# ── Integration: loop gate catches mirrored test+impl ──────────────────


class TestLoopGateIntegration:
    """Integration-level: run() with scripted writes produces a flagged report."""

    def test_loop_gate_flags_response_error(self, tmp_path: Path) -> None:
        """A work item writing a mirrored test+impl pair ends with the
        result.test_integrity_report naming the flagged symbol."""
        responses = [
            _write("test_aws.py", _AWS_TEST),
            _write("aws.py", _AWS_IMPL),
            _finish("wrote AWS error handler"),
        ]
        result = run(
            _scripted(responses),
            Task.new(str(tmp_path), "write AWS error handler"),
            max_steps=6,
        )
        assert result.status == OK
        assert result.test_integrity_report is not None
        symbols = {f.symbol for f in result.test_integrity_report.findings}
        assert "response_error" in symbols
        finding = next(
            f for f in result.test_integrity_report.findings if f.symbol == "response_error"
        )
        assert finding.kind == "attribute"

    def test_loop_gate_flags_total_estimate(self, tmp_path: Path) -> None:
        """A work item writing a mirrored Cost Explorer test+impl pair."""
        responses = [
            _write("test_cost.py", _COST_TEST),
            _write("cost.py", _COST_IMPL),
            _finish("wrote cost handler"),
        ]
        result = run(
            _scripted(responses),
            Task.new(str(tmp_path), "write cost handler"),
            max_steps=6,
        )
        assert result.status == OK
        assert result.test_integrity_report is not None
        symbols = {f.symbol for f in result.test_integrity_report.findings}
        assert "TotalEstimate" in symbols
        finding = next(
            f for f in result.test_integrity_report.findings if f.symbol == "TotalEstimate"
        )
        assert finding.kind == "dict_key"

    def test_loop_gate_disabled_skips(self, tmp_path: Path) -> None:
        """ContextControls(testintegrity=False) disables the gate."""
        responses = [
            _write("test_aws.py", _AWS_TEST),
            _write("aws.py", _AWS_IMPL),
            _finish("wrote AWS error handler"),
        ]
        result = run(
            _scripted(responses),
            Task.new(str(tmp_path), "write AWS error handler"),
            max_steps=6,
            context=ContextControls(testintegrity=False),
        )
        assert result.status == OK
        assert result.test_integrity_report is None

    def test_loop_gate_not_flagged_when_symbol_exists_elsewhere(self, tmp_path: Path) -> None:
        """A symbol also present in a pre-existing repo file is not novel."""
        # Pre-seed a file that uses response_error so it's not novel.
        (tmp_path / "legacy.py").write_text("def old():\n    exc.response_error\n")
        responses = [
            _write("test_aws.py", _AWS_TEST),
            _write("aws.py", _AWS_IMPL),
            _finish("wrote AWS error handler"),
        ]
        result = run(
            _scripted(responses),
            Task.new(str(tmp_path), "write AWS error handler"),
            max_steps=6,
        )
        assert result.status == OK
        # response_error exists in legacy.py → not novel → no finding
        assert result.test_integrity_report is None
