"""GPS / OpenTelemetry support (issue #22).

Config resolution and the no-op paths run with stdlib only. The SDK-backed
emission tests are gated on the optional ``[otel]`` extra via
``pytest.importorskip`` (mirroring the ``CONVERTIBLE_VLLM_E2E`` opt-in idiom) and
capture spans/metrics in memory — no collector, no network.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import convertible.telemetry as tel
from convertible.contract import OK, Task
from convertible.loop import ModelResponse, ToolCall, run

# --- env hygiene: every test resolves config against a known-clean environment.

_TELEMETRY_ENV = [
    "CONVERTIBLE_OTEL_ENABLED",
    "CONVERTIBLE_OTEL_ENDPOINT",
    "CONVERTIBLE_OTEL_PROTOCOL",
    "CONVERTIBLE_OTEL_SERVICE_NAME",
    "CONVERTIBLE_OTEL_METRICS_ENABLED",
    "OTEL_SDK_DISABLED",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_EXPORTER_OTLP_PROTOCOL",
    "OTEL_SERVICE_NAME",
]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _TELEMETRY_ENV:
        monkeypatch.delenv(key, raising=False)


# --------------------------------------------------------------------------- #
# Config resolution (stdlib only)
# --------------------------------------------------------------------------- #


def test_disabled_by_default() -> None:
    cfg = tel.TelemetryConfig.resolve()
    assert cfg.enabled is False
    assert cfg.service_name == "convertible"
    assert cfg.otlp_endpoint == "http://localhost:4318"


def test_enabled_via_convertible_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONVERTIBLE_OTEL_ENABLED", "1")
    monkeypatch.setenv("CONVERTIBLE_OTEL_SERVICE_NAME", "myagent")
    cfg = tel.TelemetryConfig.resolve()
    assert cfg.enabled is True
    assert cfg.service_name == "myagent"


def test_standard_otel_env_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONVERTIBLE_OTEL_ENABLED", "true")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")
    monkeypatch.setenv("OTEL_SERVICE_NAME", "fromstd")
    cfg = tel.TelemetryConfig.resolve()
    assert cfg.otlp_endpoint == "http://collector:4318"
    assert cfg.service_name == "fromstd"


def test_convertible_env_overrides_standard(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONVERTIBLE_OTEL_ENABLED", "1")
    monkeypatch.setenv("CONVERTIBLE_OTEL_SERVICE_NAME", "wins")
    monkeypatch.setenv("OTEL_SERVICE_NAME", "loses")
    assert tel.TelemetryConfig.resolve().service_name == "wins"


def test_sdk_disabled_killswitch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONVERTIBLE_OTEL_ENABLED", "1")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    assert tel.TelemetryConfig.resolve().enabled is False


def test_explicit_arg_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONVERTIBLE_OTEL_ENABLED", "0")
    assert tel.TelemetryConfig.resolve(enabled=True).enabled is True


# --------------------------------------------------------------------------- #
# No-op paths (no SDK import)
# --------------------------------------------------------------------------- #


def test_load_disabled_returns_noop() -> None:
    t = tel.load_telemetry(tel.TelemetryConfig(enabled=False))
    assert t.enabled is False
    assert t.trace_id_hex() is None
    # No-op context managers and recorders never raise.
    with t.drive_span(task_id="x", engine="mock", model="m", max_steps=1) as span:
        span.set(status="ok")
    with t.tool_span(tool="read_file", step_index=0) as span:
        span.set(ok=True)
    t.on_completion(3, 4)
    t.on_hook_denial()
    t.flush()


def test_enabled_without_sdk_degrades_to_noop(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Simulate the [otel] extra being absent: the lazy SDK import raises.
    def _boom():
        raise ImportError("no module named 'opentelemetry'")

    monkeypatch.setattr(tel, "_import_otel", _boom)
    monkeypatch.setattr(tel, "_warned_missing", False)
    t = tel.load_telemetry(tel.TelemetryConfig(enabled=True))
    assert t.enabled is False  # degraded to the no-op
    assert "[otel] extra" in capsys.readouterr().err  # one-time stderr notice


def test_loop_default_telemetry_is_noop(tmp_path: Path) -> None:
    # With telemetry off (default), the loop result is unchanged — no new fields,
    # no behavior drift (protects the e2e shape guard).
    responses = [
        ModelResponse(tool_calls=[ToolCall("1", "finish", {"summary": "done"})]),
    ]

    def complete(_messages: list[dict]) -> ModelResponse:
        return responses[0]

    task = Task.new(str(tmp_path), "noop")
    result = run(complete, task, max_steps=5)
    assert result.status == OK
    assert result.summary == "done"


# --------------------------------------------------------------------------- #
# SDK-backed emission (requires the [otel] extra)
# --------------------------------------------------------------------------- #

pytest.importorskip("opentelemetry", reason="install the [otel] extra to test SDK emission")

from opentelemetry.sdk.metrics.export import InMemoryMetricReader  # noqa: E402
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (  # noqa: E402
    InMemorySpanExporter,
)

from convertible.telemetry import _otel  # noqa: E402


def _scripted(responses: list[ModelResponse]):
    state = {"i": 0}

    def complete(_messages: list[dict]) -> ModelResponse:
        i = min(state["i"], len(responses) - 1)
        state["i"] += 1
        return responses[i]

    return complete


@pytest.fixture
def otel_capture():
    """An enabled, SDK-backed Telemetry writing spans/metrics to memory."""
    _otel.reset_for_tests()
    span_exporter = InMemorySpanExporter()
    metric_reader = InMemoryMetricReader()
    cfg = tel.TelemetryConfig(enabled=True, service_name="convertible-test")
    t = tel.load_telemetry(cfg, span_exporter=span_exporter, metric_reader=metric_reader)
    yield t, span_exporter, metric_reader
    _otel.reset_for_tests()


def test_loop_emits_tool_spans(tmp_path: Path, otel_capture) -> None:
    t, span_exporter, _reader = otel_capture
    responses = [
        ModelResponse(
            tool_calls=[ToolCall("1", "write_file", {"path": "a.txt", "content": "hi"})],
            prompt_tokens=10,
            completion_tokens=2,
        ),
        ModelResponse(tool_calls=[ToolCall("2", "finish", {"summary": "wrote a.txt"})]),
    ]
    task = Task.new(str(tmp_path), "write a.txt")
    result = run(_scripted(responses), task, max_steps=10, telemetry=t)
    assert result.status == OK

    names = [s.name for s in span_exporter.get_finished_spans()]
    assert "convertible.tool.write_file" in names
    assert "convertible.tool.finish" in names


def test_drive_span_parents_tool_spans(tmp_path: Path, otel_capture) -> None:
    t, span_exporter, _reader = otel_capture
    responses = [ModelResponse(tool_calls=[ToolCall("1", "finish", {"summary": "ok"})])]
    task = Task.new(str(tmp_path), "x")

    with t.drive_span(task_id=task.id, engine="mock", model="m", max_steps=5) as d:
        d.set(status="ok")
        run(_scripted(responses), task, max_steps=5, telemetry=t)

    spans = {s.name: s for s in span_exporter.get_finished_spans()}
    drive = spans["convertible.drive"]
    tool = spans["convertible.tool.finish"]
    # The tool span auto-nested under the drive span (shared trace + parent).
    assert tool.context.trace_id == drive.context.trace_id
    assert tool.parent is not None
    assert tool.parent.span_id == drive.context.span_id


def test_metrics_recorded(tmp_path: Path, otel_capture) -> None:
    t, _span_exporter, metric_reader = otel_capture
    responses = [
        ModelResponse(
            tool_calls=[ToolCall("1", "list_dir", {"path": "."})],
            prompt_tokens=5,
            completion_tokens=1,
        ),
        ModelResponse(tool_calls=[ToolCall("2", "finish", {"summary": "done"})]),
    ]
    task = Task.new(str(tmp_path), "list")
    run(_scripted(responses), task, max_steps=10, telemetry=t)
    t.flush()

    data = metric_reader.get_metrics_data()
    names = set()
    for rm in data.resource_metrics:
        for sm in rm.scope_metrics:
            for metric in sm.metrics:
                names.add(metric.name)
    assert "convertible.steps" in names
    assert "convertible.tokens" in names
    assert "convertible.tool.calls" in names
    assert "convertible.tool.latency" in names


def test_metrics_disabled_suppresses_metrics(tmp_path: Path) -> None:
    # CONVERTIBLE_OTEL_METRICS_ENABLED=false must actually suppress emission, not
    # just hide the flag — no meter provider, no instruments, no recording.
    _otel.reset_for_tests()
    span_exporter = InMemorySpanExporter()
    cfg = tel.TelemetryConfig(enabled=True, metrics_enabled=False)
    t = tel.load_telemetry(cfg, span_exporter=span_exporter)
    assert t._s.meter_provider is None  # type: ignore[attr-defined]
    assert t._s.steps is None  # type: ignore[attr-defined]

    responses = [ModelResponse(tool_calls=[ToolCall("1", "finish", {"summary": "x"})])]
    run(_scripted(responses), Task.new(str(tmp_path), "x"), max_steps=5, telemetry=t)
    t.flush()  # must not raise with no meter provider
    # Traces are unaffected — only metrics are off.
    assert any(s.name.startswith("convertible.tool.") for s in span_exporter.get_finished_spans())
    _otel.reset_for_tests()


def test_otlp_protocol_grpc_falls_back_to_http(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The lean [otel] extra ships HTTP only; otlp_protocol=grpc without the grpc
    # exporter package falls back to HTTP with a one-time notice (never silently
    # ignored — the config field is honored).
    monkeypatch.setattr(_otel, "_warned_protocol", False)
    assert _otel._use_grpc(tel.TelemetryConfig(enabled=True, otlp_protocol="grpc")) is False
    assert "grpc" in capsys.readouterr().err
    assert (
        _otel._use_grpc(tel.TelemetryConfig(enabled=True, otlp_protocol="http/protobuf")) is False
    )


def test_sdk_available_true_with_extra() -> None:
    # The probe checks the SDK + exporter modules, not just the API namespace.
    assert tel.sdk_available() is True
