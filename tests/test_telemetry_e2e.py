"""End-to-end telemetry through the production ``execute_drive`` path (#126, §6).

``tests/test_telemetry.py`` proves the ``Telemetry`` object and the loop's tool
spans/metrics in isolation, but it calls ``run()`` directly with a single shared
instance and hand-assembles the drive span. It does NOT exercise the real
production orchestration: the root ``colleague.drive`` span and the
``colleague.handoff`` span live in ``execute_drive`` / ``_handoff_result``, not the
loop, and ``execute_drive`` and the loop each call ``load_telemetry()``
independently. This module closes that gap — and covers the previously-untested
``colleague.handoff`` span, ``colleague.drive.duration``, and
``colleague.hook.denials`` metrics — by driving the **whole** production path and
capturing every span/metric in one in-memory (debug) exporter.

Telemetry is **engine-agnostic** (the all-engines rule): the spans and metrics
fire identically for every backend, so the ``mock`` backend is the contract
reference here (it exercises the same loop + drive path a live model does). The
sibling ``tests/test_vllm_live_telemetry.py`` adds the live composition stamp.

Gated on the ``[otel]`` extra (installed in ``.venv``), so it RUNS in CI rather
than skipping. The strict no-op when telemetry is OFF (no spans, no ``_otel`` /
SDK import even with the extra installed) is locked deterministically by
``tests/test_zero_deps.py`` and
``tests/test_telemetry.py::test_loop_default_telemetry_is_noop`` — not re-proven
here, since importing the SDK in this module would pollute ``sys.modules``.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

# Guard on the SDK package, not the bare ``opentelemetry`` namespace: ``opentelemetry``
# is a namespace package that ``opentelemetry-api`` alone provides, but these tests
# import ``opentelemetry.sdk.*`` — guarding on the namespace would error at collection
# (instead of skipping) in an API-only env. See ``telemetry.sdk_available``'s docstring.
pytest.importorskip("opentelemetry.sdk", reason="install the [otel] extra to test SDK emission")

from opentelemetry.sdk.metrics.export import InMemoryMetricReader  # noqa: E402
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (  # noqa: E402
    InMemorySpanExporter,
)

import colleague.telemetry as tel  # noqa: E402
from colleague.cli._commands.drive import execute_drive  # noqa: E402
from colleague.config import EngineConfig  # noqa: E402
from colleague.contract import OK, Task  # noqa: E402
from colleague.telemetry import _otel  # noqa: E402


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True)


def _init_repo(repo: Path) -> Path:
    """A real git repo with one commit so the handoff can actually commit a branch."""
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@colleague.test")
    _git(repo, "config", "user.name", "Colleague Test")
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def _metric_names(metric_reader: InMemoryMetricReader) -> set[str]:
    """Collect the emitted metric names. Reads the reader exactly once (it clears
    its buffer on read; cumulative temporality returns full totals)."""
    data = metric_reader.get_metrics_data()
    names: set[str] = set()
    if data is None:
        return names
    for rm in data.resource_metrics:
        for sm in rm.scope_metrics:
            for metric in sm.metrics:
                names.add(metric.name)
    return names


@pytest.fixture
def captured_drive(monkeypatch):
    """Capture telemetry from the REAL execute_drive path into in-memory exporters.

    ``execute_drive`` (drive span + handoff span) and the loop (tool spans +
    metrics) each call ``load_telemetry()`` independently. Both modules bind the
    name via ``from colleague.telemetry import load_telemetry``, so patch BOTH
    rebound import-site symbols to ONE captured instance — then every span lands
    in one exporter and metrics accumulate on one reader. Span nesting is via
    OTel's global context (contextvars), not instance sharing, so this is faithful
    to production (where the cached global provider plays the singleton's role).
    """
    _otel.reset_for_tests()
    span_exporter = InMemorySpanExporter()
    metric_reader = InMemoryMetricReader()
    captured = tel.load_telemetry(
        tel.TelemetryConfig(enabled=True, service_name="colleague-e2e"),
        span_exporter=span_exporter,
        metric_reader=metric_reader,
    )
    monkeypatch.setattr("colleague.cli._commands.drive.load_telemetry", lambda *a, **k: captured)
    monkeypatch.setattr("colleague.loop.load_telemetry", lambda *a, **k: captured)
    yield captured, span_exporter, metric_reader
    _otel.reset_for_tests()


def test_execute_drive_emits_full_span_tree_and_metrics(tmp_path: Path, captured_drive) -> None:
    """A full mock drive emits root + per-tool + handoff spans (nested) and metrics."""
    repo = _init_repo(tmp_path / "repo")
    _captured, span_exporter, metric_reader = captured_drive

    task = Task.new(str(repo), "do the mock task", engine="mock")
    result, _artifact = execute_drive(
        repo=repo,
        engine_name="mock",
        task=task,
        open_pr=False,
        base="main",
        config=EngineConfig.resolve(),
    )
    assert result.status == OK, result.error

    spans = {s.name: s for s in span_exporter.get_finished_spans()}
    # Root + per-tool + handoff spans all present.
    assert "colleague.drive" in spans
    assert "colleague.tool.write_file" in spans
    assert "colleague.tool.finish" in spans
    assert "colleague.handoff" in spans

    # One nested trace: every child parented under the root drive span.
    drive = spans["colleague.drive"]
    for child_name in ("colleague.tool.write_file", "colleague.tool.finish", "colleague.handoff"):
        child = spans[child_name]
        assert child.context.trace_id == drive.context.trace_id, child_name
        assert child.parent is not None, child_name
        assert child.parent.span_id == drive.context.span_id, child_name

    # The handoff actually committed a branch (real git repo).
    assert spans["colleague.handoff"].attributes.get("committed") is True

    # Metrics — read once. Includes the previously-untested drive.duration, plus
    # the issue's headline generated.chars / bytes_written.
    names = _metric_names(metric_reader)
    for metric_name in (
        "colleague.steps",
        "colleague.tokens",
        "colleague.generated.chars",
        "colleague.bytes_written",
        "colleague.tool.calls",
        "colleague.tool.latency",
        "colleague.drive.duration",
    ):
        assert metric_name in names, metric_name


def test_execute_drive_hook_denial_records_metric(tmp_path: Path, captured_drive) -> None:
    """A pre_tool deny records colleague.hook.denials (previously untested).

    The deny matcher targets ``write_file`` — the mock's only non-finish tool. The
    deny is non-fatal: the loop continues to ``finish`` and the drive stays OK,
    but the write never runs (no marker file) and the denial counter is emitted.
    No ``approvals.json`` is present, so the hook runs freely (the gate is a no-op).
    """
    repo = _init_repo(tmp_path / "repo")
    dotdir = repo / ".colleague"
    dotdir.mkdir(parents=True, exist_ok=True)
    (dotdir / "hooks.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "pre_tool": [
                        {
                            "matcher": "write_file",
                            "command": "sh -c 'echo blocked-by-policy >&2; exit 1'",
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    _captured, _span_exporter, metric_reader = captured_drive

    task = Task.new(str(repo), "do the mock task", engine="mock")
    result, _artifact = execute_drive(
        repo=repo,
        engine_name="mock",
        task=task,
        open_pr=False,
        base="main",
        config=EngineConfig.resolve(),
    )
    assert result.status == OK, result.error

    # The denial counter fired...
    assert "colleague.hook.denials" in _metric_names(metric_reader)
    # ...and the denied write never executed (the mock's marker file is absent).
    assert not (repo / "colleague-mock.md").exists()
    # The runtime also recorded the firing on the result (deterministic, non-telemetry).
    assert any(
        getattr(f, "decision", "") == "deny" for f in result.hook_firings
    ), result.hook_firings
