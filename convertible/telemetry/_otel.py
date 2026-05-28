"""SDK-backed OpenTelemetry implementation — imported only when enabled.

This module imports ``opentelemetry`` at top level, so it is **never** imported
at convertible's module-load time. :func:`convertible.telemetry.load_telemetry`
imports it lazily, and only when telemetry is enabled *and* the ``[otel]`` extra
is installed. Keeping the SDK confined here is what lets the zero-deps guard
(``tests/test_zero_deps.py``) pass even with the extra present.

Span/metric names follow culture's ``<service>.<area>.<metric>`` convention
(see ``culture/telemetry/metrics.py``). Providers are built once and cached in
module state (idempotent init, like ``culture/telemetry/tracing.py``); we keep
them local rather than registering globals, since
``start_as_current_span`` propagates parentage through the global *context*
(contextvars) regardless of which provider created the tracer — so the loop's
tool spans still nest under the drive span without any global registration.
"""

from __future__ import annotations

import atexit
import contextlib
import time
from dataclasses import dataclass
from typing import Any, Iterator, Optional

from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    InMemoryMetricReader,
    MetricReader,
    PeriodicExportingMetricReader,
)
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter
from opentelemetry.sdk.trace.sampling import ALWAYS_OFF, ALWAYS_ON, ParentBased, Sampler
from opentelemetry.trace import format_trace_id, get_current_span

from convertible.telemetry import Telemetry, TelemetryConfig

_TRACER_NAME = "convertible"
_METER_NAME = "convertible"


def _build_sampler(name: str) -> Sampler:
    table = {
        "always_on": ALWAYS_ON,
        "always_off": ALWAYS_OFF,
        "parentbased_always_on": ParentBased(ALWAYS_ON),
    }
    return table.get(name, ParentBased(ALWAYS_ON))


def _default_span_exporter(cfg: TelemetryConfig) -> SpanExporter:
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    return OTLPSpanExporter(
        endpoint=f"{cfg.otlp_endpoint.rstrip('/')}/v1/traces",
        timeout=max(1, cfg.otlp_timeout_ms // 1000),
    )


def _default_metric_reader(cfg: TelemetryConfig) -> MetricReader:
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter

    exporter = OTLPMetricExporter(
        endpoint=f"{cfg.otlp_endpoint.rstrip('/')}/v1/metrics",
        timeout=max(1, cfg.otlp_timeout_ms // 1000),
    )
    return PeriodicExportingMetricReader(
        exporter, export_interval_millis=cfg.metrics_export_interval_ms
    )


@dataclass
class _State:
    """Cached providers + meter instruments shared across a process's drives."""

    tracer_provider: TracerProvider
    meter_provider: MeterProvider
    tracer: Any
    steps: Any
    tokens: Any
    tool_calls: Any
    tool_latency: Any
    hook_denials: Any
    drive_duration: Any


_state: Optional[_State] = None
_atexit_registered = False


def reset_for_tests() -> None:
    """Drop cached providers so each test builds fresh ones. Test-only."""
    global _state
    if _state is not None:
        with contextlib.suppress(Exception):
            _state.tracer_provider.shutdown()
        with contextlib.suppress(Exception):
            _state.meter_provider.shutdown()
    _state = None


def _build_state(
    cfg: TelemetryConfig,
    *,
    span_exporter: SpanExporter | None = None,
    metric_reader: MetricReader | None = None,
) -> _State:
    resource = Resource.create({SERVICE_NAME: cfg.service_name})

    tracer_provider = TracerProvider(resource=resource, sampler=_build_sampler(cfg.traces_sampler))
    if span_exporter is not None:
        # An injected exporter is a test seam — export on span end (deterministic).
        tracer_provider.add_span_processor(SimpleSpanProcessor(span_exporter))
    else:
        tracer_provider.add_span_processor(BatchSpanProcessor(_default_span_exporter(cfg)))

    reader = metric_reader if metric_reader is not None else _default_metric_reader(cfg)
    meter_provider = MeterProvider(resource=resource, metric_readers=[reader])

    tracer = tracer_provider.get_tracer(_TRACER_NAME)
    meter = meter_provider.get_meter(_METER_NAME)
    return _State(
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        tracer=tracer,
        steps=meter.create_counter("convertible.steps"),
        tokens=meter.create_counter("convertible.tokens"),
        tool_calls=meter.create_counter("convertible.tool.calls"),
        tool_latency=meter.create_histogram("convertible.tool.latency", unit="s"),
        hook_denials=meter.create_counter("convertible.hook.denials"),
        drive_duration=meter.create_histogram("convertible.drive.duration", unit="s"),
    )


def get_telemetry(cfg: TelemetryConfig, **test_seams: Any) -> "Telemetry":
    """Return the SDK-backed telemetry, building (and caching) providers once.

    ``test_seams`` accepts ``span_exporter`` / ``metric_reader`` so tests can
    capture spans and metrics in memory instead of shipping them over OTLP.
    """
    global _state, _atexit_registered
    if test_seams:
        # Tests want isolated, in-memory providers — never share or cache them.
        reset_for_tests()
        _state = _build_state(
            cfg,
            span_exporter=test_seams.get("span_exporter"),  # type: ignore[arg-type]
            metric_reader=test_seams.get("metric_reader"),  # type: ignore[arg-type]
        )
        return _OtelTelemetry(_state)
    if _state is None:
        _state = _build_state(cfg)
    if not _atexit_registered:
        atexit.register(reset_for_tests)
        _atexit_registered = True
    return _OtelTelemetry(_state)


class _Span:
    """A span handle exposing ``.set(**attrs)`` over an OTel span."""

    def __init__(self, span: Any) -> None:
        self._span = span
        self.ok = True
        self._status = "unknown"

    def set(self, **attrs: object) -> None:
        for key, value in attrs.items():
            if value is None:
                continue
            if key == "ok":
                self.ok = bool(value)
            if key == "status":
                self._status = str(value)
            self._span.set_attribute(key, value)


class _OtelTelemetry(Telemetry):
    """Emits real spans and records metrics. One drive == one ``convertible.drive``
    root span with ``convertible.tool.*`` children (and ``convertible.handoff``)."""

    enabled = True

    def __init__(self, state: _State) -> None:
        self._s = state

    @contextlib.contextmanager
    def drive_span(
        self, *, task_id: str, engine: str, model: str, max_steps: int
    ) -> Iterator[_Span]:
        start = time.monotonic()
        with self._s.tracer.start_as_current_span("convertible.drive") as span:
            span.set_attribute("task_id", task_id)
            span.set_attribute("engine", engine)
            span.set_attribute("model", model)
            span.set_attribute("max_steps", max_steps)
            handle = _Span(span)
            try:
                yield handle
            finally:
                status = getattr(handle, "_status", "unknown")
                self._s.drive_duration.record(time.monotonic() - start, {"status": status})

    @contextlib.contextmanager
    def tool_span(self, *, tool: str, step_index: int) -> Iterator[_Span]:
        start = time.monotonic()
        with self._s.tracer.start_as_current_span(f"convertible.tool.{tool}") as span:
            span.set_attribute("tool", tool)
            span.set_attribute("step_index", step_index)
            handle = _Span(span)
            try:
                yield handle
            finally:
                # Every tool-call iteration appends exactly one Step, so one
                # step is counted here regardless of allow/deny/error.
                self._s.steps.add(1, {"tool": tool})
                self._s.tool_calls.add(1, {"tool": tool, "ok": handle.ok})
                self._s.tool_latency.record(time.monotonic() - start, {"tool": tool})

    @contextlib.contextmanager
    def handoff_span(self) -> Iterator[_Span]:
        with self._s.tracer.start_as_current_span("convertible.handoff") as span:
            yield _Span(span)

    def on_completion(self, prompt_tokens: int, completion_tokens: int) -> None:
        if prompt_tokens:
            self._s.tokens.add(prompt_tokens, {"kind": "prompt"})
        if completion_tokens:
            self._s.tokens.add(completion_tokens, {"kind": "completion"})

    def on_hook_denial(self) -> None:
        self._s.hook_denials.add(1)

    def trace_id_hex(self) -> str | None:
        ctx = get_current_span().get_span_context()
        if ctx is None or not ctx.is_valid:
            return None
        return format_trace_id(ctx.trace_id)

    def flush(self) -> None:
        # Force-flush (not shutdown) so a one-shot `drive` ships its spans while
        # a `session` running many drives can keep reusing the providers; the
        # atexit hook performs the real shutdown at process exit.
        with contextlib.suppress(Exception):
            self._s.tracer_provider.force_flush()
        with contextlib.suppress(Exception):
            self._s.meter_provider.force_flush()


# Re-export so tests can build in-memory seams without importing deep SDK paths.
__all__ = ["get_telemetry", "reset_for_tests", "InMemoryMetricReader"]
