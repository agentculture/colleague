"""Opt-in live proof that telemetry fires through a real vLLM drive (#126, §6).

Sibling to ``test_telemetry_e2e.py`` (the engine-agnostic CI proof) and the other
``test_vllm_live_*.py`` files. Telemetry is engine-agnostic (the all-engines rule),
so the mock e2e already proves the production wiring; this adds the live composition
stamp — a real model drive whose **real** token usage and reasoning/answer text flow
into ``colleague.tokens`` / ``colleague.generated.chars``, and whose real file write
flows into ``colleague.bytes_written`` — captured through the production
``execute_work`` path into an in-memory (debug) exporter (no collector needed; the
in-memory exporter is the ledger procedure's allowed file/debug-exporter alternative).

Gated on BOTH ``COLLEAGUE_VLLM_E2E=1`` (a live vLLM server) and the ``[otel]`` extra.

Run it (rig up) like::

    COLLEAGUE_VLLM_E2E=1 uv run pytest tests/test_vllm_live_telemetry.py -v -s
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    "1" not in (os.environ.get("COLLEAGUE_VLLM_E2E"), os.environ.get("CONVERTIBLE_VLLM_E2E")),
    reason="set COLLEAGUE_VLLM_E2E=1 (with a live vLLM server) to run the live proof",
)

# Guard on the SDK package, not the bare ``opentelemetry`` namespace (api-only envs
# provide the namespace but not ``opentelemetry.sdk`` — guarding the namespace would
# error at collection instead of skipping). See ``telemetry.sdk_available``.
pytest.importorskip("opentelemetry.sdk", reason="install the [otel] extra to test SDK emission")

from opentelemetry.sdk.metrics.export import InMemoryMetricReader  # noqa: E402
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (  # noqa: E402
    InMemorySpanExporter,
)

import colleague.telemetry as tel  # noqa: E402
from colleague.cli._commands.work import execute_work  # noqa: E402
from colleague.config import EngineConfig  # noqa: E402
from colleague.contract import OK, Task  # noqa: E402
from colleague.telemetry import _otel  # noqa: E402


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True)


def _init_repo(repo: Path) -> Path:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@colleague.test")
    _git(repo, "config", "user.name", "Colleague Test")
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def _metric_names(metric_reader: InMemoryMetricReader) -> set[str]:
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
    """Capture telemetry from the real execute_work path (see test_telemetry_e2e.py).

    Patches BOTH ``load_telemetry`` import sites to one captured instance so the
    drive/handoff/tool spans land in one exporter and metrics on one reader.
    """
    _otel.reset_for_tests()
    span_exporter = InMemorySpanExporter()
    metric_reader = InMemoryMetricReader()
    captured = tel.load_telemetry(
        tel.TelemetryConfig(enabled=True, service_name="colleague-live"),
        span_exporter=span_exporter,
        metric_reader=metric_reader,
    )
    monkeypatch.setattr("colleague.cli._commands.work.load_telemetry", lambda *a, **k: captured)
    monkeypatch.setattr("colleague.loop.load_telemetry", lambda *a, **k: captured)
    yield captured, span_exporter, metric_reader
    _otel.reset_for_tests()


_TELEMETRY_TASK = "Create a file named HELLO.txt containing exactly the text: hello from colleague"


def test_live_drive_emits_telemetry(captured_drive, tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    _captured, span_exporter, metric_reader = captured_drive

    task = Task.new(str(repo), _TELEMETRY_TASK, engine="vllm-openai")
    result, artifact_path = execute_work(
        repo=repo,
        engine_name="vllm-openai",
        task=task,
        open_pr=False,
        base="main",
        config=EngineConfig.resolve(),
    )
    span_names = {s.name for s in span_exporter.get_finished_spans()}
    metric_names = _metric_names(metric_reader)
    print(f"\n[live #126] drive {result.task_id} -> {artifact_path}")
    print(f"[live #126] spans: {sorted(span_names)}")
    print(f"[live #126] metrics: {sorted(metric_names)}")

    assert result.status == OK, result.error

    # Root + per-tool + handoff spans, robust to which tools the live model chooses.
    assert "colleague.work" in span_names
    assert any(n.startswith("colleague.tool.") for n in span_names), span_names
    assert "colleague.handoff" in span_names

    # Headline metrics from REAL model usage (tokens), reasoning/answer text
    # (generated.chars), and a real file write (bytes_written).
    for metric_name in (
        "colleague.tokens",
        "colleague.generated.chars",
        "colleague.bytes_written",
        "colleague.steps",
        "colleague.work.duration",
    ):
        assert metric_name in metric_names, metric_name
