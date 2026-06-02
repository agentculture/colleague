"""SDK-backed OpenTelemetry implementation — imported only when enabled.

This module imports ``opentelemetry`` at top level, so it is **never** imported
at colleague's module-load time. :func:`colleague.telemetry.load_telemetry`
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
import importlib.util
import sys
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

from colleague.telemetry import Telemetry, TelemetryConfig

_TRACER_NAME = "colleague"
_METER_NAME = "colleague"


def _build_sampler(name: str) -> Sampler:
    table = {
        "always_on": ALWAYS_ON,
        "always_off": ALWAYS_OFF,
        "parentbased_always_on": ParentBased(ALWAYS_ON),
    }
    return table.get(name, ParentBased(ALWAYS_ON))


_HTTP_PROTOCOLS = frozenset({"http/protobuf", "http", "http/json"})
_warned_protocol = False


def _use_grpc(cfg: TelemetryConfig) -> bool:
    """Whether to use the gRPC exporter for ``cfg.otlp_protocol``.

    The lean ``[otel]`` extra ships only the HTTP exporter; gRPC works only when
    the operator has additionally installed ``opentelemetry-exporter-otlp-proto-grpc``.
    A ``grpc`` request without that package falls back to HTTP with a one-time
    stderr notice — so ``otlp_protocol`` is honored, never silently ignored.
    """
    global _warned_protocol
    proto = (cfg.otlp_protocol or "").lower()
    if proto in _HTTP_PROTOCOLS:
        return False
    if proto == "grpc":
        if importlib.util.find_spec("opentelemetry.exporter.otlp.proto.grpc") is not None:
            return True
        if not _warned_protocol:
            _warned_protocol = True
            print(
                "telemetry: otlp_protocol=grpc requested but the gRPC exporter is not "
                "installed (the [otel] extra ships HTTP only) — falling back to "
                "http/protobuf. Install opentelemetry-exporter-otlp-proto-grpc for gRPC.",
                file=sys.stderr,
            )
        return False
    if not _warned_protocol:
        _warned_protocol = True
        print(
            f"telemetry: unknown otlp_protocol={cfg.otlp_protocol!r} — "
            "falling back to http/protobuf.",
            file=sys.stderr,
        )
    return False


def _default_span_exporter(cfg: TelemetryConfig) -> SpanExporter:
    timeout = max(1, cfg.otlp_timeout_ms // 1000)
    if _use_grpc(cfg):
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter as GrpcSpanExporter,
        )

        return GrpcSpanExporter(endpoint=cfg.otlp_endpoint, timeout=timeout)
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    return OTLPSpanExporter(endpoint=f"{cfg.otlp_endpoint.rstrip('/')}/v1/traces", timeout=timeout)


def _default_metric_reader(cfg: TelemetryConfig) -> MetricReader:
    timeout = max(1, cfg.otlp_timeout_ms // 1000)
    if _use_grpc(cfg):
        from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
            OTLPMetricExporter as GrpcMetricExporter,
        )

        exporter: Any = GrpcMetricExporter(endpoint=cfg.otlp_endpoint, timeout=timeout)
    else:
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter

        exporter = OTLPMetricExporter(
            endpoint=f"{cfg.otlp_endpoint.rstrip('/')}/v1/metrics", timeout=timeout
        )
    return PeriodicExportingMetricReader(
        exporter, export_interval_millis=cfg.metrics_export_interval_ms
    )


@dataclass
class _State:
    """Cached providers + meter instruments shared across a process's drives.

    When ``metrics_enabled`` is false the meter provider and instruments are
    ``None`` — metric recording is then skipped, so ``COLLEAGUE_OTEL_METRICS_ENABLED=false``
    actually suppresses emission (not just the displayed config).
    """

    tracer_provider: TracerProvider
    meter_provider: Optional[MeterProvider]
    tracer: Any
    steps: Any
    tokens: Any
    generated: Any
    bytes_written: Any
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
    if cfg.traces_enabled:
        if span_exporter is not None:
            # An injected exporter is a test seam — export on span end (deterministic).
            tracer_provider.add_span_processor(SimpleSpanProcessor(span_exporter))
        else:
            tracer_provider.add_span_processor(BatchSpanProcessor(_default_span_exporter(cfg)))
    tracer = tracer_provider.get_tracer(_TRACER_NAME)

    meter_provider: Optional[MeterProvider] = None
    steps = tokens = tool_calls = tool_latency = hook_denials = drive_duration = None
    generated = bytes_written = None
    if cfg.metrics_enabled:
        reader = metric_reader if metric_reader is not None else _default_metric_reader(cfg)
        meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
        meter = meter_provider.get_meter(_METER_NAME)
        steps = meter.create_counter("colleague.steps")
        tokens = meter.create_counter("colleague.tokens")
        # Generated text size (attr kind=reasoning|answer) — the char-level
        # "thought vs written" measure, since this server reports no reasoning-
        # token breakdown. And the exact bytes written to files.
        generated = meter.create_counter("colleague.generated.chars")
        bytes_written = meter.create_counter("colleague.bytes_written", unit="By")
        tool_calls = meter.create_counter("colleague.tool.calls")
        tool_latency = meter.create_histogram("colleague.tool.latency", unit="s")
        hook_denials = meter.create_counter("colleague.hook.denials")
        drive_duration = meter.create_histogram("colleague.drive.duration", unit="s")

    return _State(
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        tracer=tracer,
        steps=steps,
        tokens=tokens,
        generated=generated,
        bytes_written=bytes_written,
        tool_calls=tool_calls,
        tool_latency=tool_latency,
        hook_denials=hook_denials,
        drive_duration=drive_duration,
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
        self._otel_span = span
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
            self._otel_span.set_attribute(key, value)


class _OtelTelemetry(Telemetry):
    """Emits real spans and records metrics. One drive == one ``colleague.drive``
    root span with ``colleague.tool.*`` children (and ``colleague.handoff``)."""

    enabled = True

    def __init__(self, state: _State) -> None:
        self._s = state

    @contextlib.contextmanager
    def drive_span(
        self, *, task_id: str, engine: str, model: str, max_steps: int
    ) -> Iterator[_Span]:
        start = time.monotonic()
        with self._s.tracer.start_as_current_span("colleague.drive") as span:
            span.set_attribute("task_id", task_id)
            span.set_attribute("engine", engine)
            span.set_attribute("model", model)
            span.set_attribute("max_steps", max_steps)
            handle = _Span(span)
            try:
                yield handle
            finally:
                if self._s.drive_duration is not None:
                    status = getattr(handle, "_status", "unknown")
                    self._s.drive_duration.record(time.monotonic() - start, {"status": status})

    @contextlib.contextmanager
    def tool_span(self, *, tool: str, step_index: int) -> Iterator[_Span]:
        start = time.monotonic()
        with self._s.tracer.start_as_current_span(f"colleague.tool.{tool}") as span:
            span.set_attribute("tool", tool)
            span.set_attribute("step_index", step_index)
            handle = _Span(span)
            try:
                yield handle
            finally:
                if self._s.steps is not None:
                    # Every tool-call iteration appends exactly one Step, so one
                    # step is counted here regardless of allow/deny/error.
                    self._s.steps.add(1, {"tool": tool})
                    self._s.tool_calls.add(1, {"tool": tool, "ok": handle.ok})
                    self._s.tool_latency.record(time.monotonic() - start, {"tool": tool})

    @contextlib.contextmanager
    def handoff_span(self) -> Iterator[_Span]:
        with self._s.tracer.start_as_current_span("colleague.handoff") as span:
            yield _Span(span)

    def on_completion(self, prompt_tokens: int, completion_tokens: int) -> None:
        if self._s.tokens is None:
            return
        if prompt_tokens:
            self._s.tokens.add(prompt_tokens, {"kind": "prompt"})
        if completion_tokens:
            self._s.tokens.add(completion_tokens, {"kind": "completion"})

    def on_generated(self, *, reasoning: str = "", answer: str = "") -> None:
        if self._s.generated is None:
            return
        if reasoning:
            self._s.generated.add(len(reasoning), {"kind": "reasoning"})
        if answer:
            self._s.generated.add(len(answer), {"kind": "answer"})

    def on_bytes_written(self, n_bytes: int) -> None:
        if self._s.bytes_written is not None and n_bytes:
            self._s.bytes_written.add(n_bytes)

    def on_hook_denial(self) -> None:
        if self._s.hook_denials is not None:
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
        if self._s.meter_provider is not None:
            with contextlib.suppress(Exception):
                self._s.meter_provider.force_flush()


# Re-export so tests can build in-memory seams without importing deep SDK paths.
__all__ = ["get_telemetry", "reset_for_tests", "InMemoryMetricReader"]
