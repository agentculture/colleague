"""Telemetry — OpenTelemetry observability for a drive (issue #22).

Colleague's run report (the JSON result artifact + step trace) is per-run and
blind across runs. This package adds **telemetry**: live OTel traces + metrics so a
drive can be observed against the same collector the sibling repos already feed
(``../culture`` runs a full ``culture/telemetry/`` package).

Two hard invariants shape the design:

1. **Zero runtime deps** (``tests/test_zero_deps.py``). The OpenTelemetry SDK is
   an *optional extra* (``pip install colleague[otel]``); this module —
   on the import path of :mod:`colleague.loop` — is **stdlib only**. The SDK
   is imported lazily inside :func:`load_telemetry`, never at module load, so
   the zero-deps guard holds even when the extra is installed. The real,
   SDK-backed implementation lives in :mod:`colleague.telemetry._otel`.
2. **No-op by default.** Telemetry is off unless explicitly enabled. When off —
   or when on but the extra is not installed — every call resolves to
   :class:`_NoopTelemetry`: no spans, no metrics, no SDK import, ``TaskResult``
   unchanged. The artifact-shape and zero-deps guards pass untouched.

The facade mirrors the lifecycle the loop already exposes for hooks, so
telemetry belongs to the **runtime** (the loop + the shared drive path), not to
any backend — every backend inherits it (the all-engines rule).
"""

from __future__ import annotations

import contextlib
import importlib.util
import os
import sys
from dataclasses import dataclass
from typing import Iterator

from colleague.config import _pick, _str

_TRUTHY = frozenset({"1", "true", "yes", "on"})

# Default exporter target: OTLP/HTTP on the conventional collector port. gRPC
# (:4317, as culture uses) is selectable via ``otlp_protocol`` but needs the
# grpc exporter package, which the lean ``[otel]`` extra does not pull.
_DEFAULT_SERVICE_NAME = "colleague"
_DEFAULT_ENDPOINT = "http://localhost:4318"
_DEFAULT_PROTOCOL = "http/protobuf"

# One-shot guard so a missing-SDK warning is printed at most once per process.
_warned_missing = False


def _as_bool(value: object | None, default: bool) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in _TRUTHY


@dataclass
class TelemetryConfig:
    """OTel settings for a drive. Mirrors ``agentirc.config.TelemetryConfig``.

    Resolution precedence matches :class:`~colleague.config.EngineConfig`:
    explicit value > ``COLLEAGUE_OTEL_*`` env (legacy ``CONVERTIBLE_OTEL_*`` is
    honored as a deprecated fallback) > standard ``OTEL_*`` env > default. Off by
    default; the standard ``OTEL_SDK_DISABLED=true`` forces it off regardless of
    the other knobs.
    """

    enabled: bool = False
    service_name: str = _DEFAULT_SERVICE_NAME
    otlp_endpoint: str = _DEFAULT_ENDPOINT
    otlp_protocol: str = _DEFAULT_PROTOCOL
    otlp_timeout_ms: int = 5000
    otlp_compression: str = "gzip"
    traces_enabled: bool = True
    traces_sampler: str = "parentbased_always_on"
    metrics_enabled: bool = True
    metrics_export_interval_ms: int = 10000

    @classmethod
    def resolve(
        cls,
        *,
        enabled: bool | None = None,
        endpoint: str | None = None,
        protocol: str | None = None,
        service_name: str | None = None,
        metrics_enabled: bool | None = None,
    ) -> "TelemetryConfig":
        """Build a config from explicit args, env vars, then defaults."""
        enabled_val = _as_bool(
            _pick(
                _str(enabled),
                "COLLEAGUE_OTEL_ENABLED",
                "CONVERTIBLE_OTEL_ENABLED",
                default="false",
            ),
            False,
        )
        # Standard OTel kill-switch wins: an operator-set OTEL_SDK_DISABLED=true
        # disables colleague telemetry even if COLLEAGUE_OTEL_ENABLED=1.
        if _as_bool(os.environ.get("OTEL_SDK_DISABLED"), False):
            enabled_val = False
        return cls(
            enabled=enabled_val,
            service_name=_pick(
                service_name,
                "COLLEAGUE_OTEL_SERVICE_NAME",
                "CONVERTIBLE_OTEL_SERVICE_NAME",
                "OTEL_SERVICE_NAME",
                default=_DEFAULT_SERVICE_NAME,
            ),
            otlp_endpoint=_pick(
                endpoint,
                "COLLEAGUE_OTEL_ENDPOINT",
                "CONVERTIBLE_OTEL_ENDPOINT",
                "OTEL_EXPORTER_OTLP_ENDPOINT",
                default=_DEFAULT_ENDPOINT,
            ),
            otlp_protocol=_pick(
                protocol,
                "COLLEAGUE_OTEL_PROTOCOL",
                "CONVERTIBLE_OTEL_PROTOCOL",
                "OTEL_EXPORTER_OTLP_PROTOCOL",
                default=_DEFAULT_PROTOCOL,
            ),
            metrics_enabled=_as_bool(
                _pick(
                    _str(metrics_enabled),
                    "COLLEAGUE_OTEL_METRICS_ENABLED",
                    "CONVERTIBLE_OTEL_METRICS_ENABLED",
                    default="true",
                ),
                True,
            ),
        )

    def to_dict(self) -> dict[str, object]:
        """Config snapshot for ``telemetry status`` / the result artifact."""
        return {
            "enabled": self.enabled,
            "service_name": self.service_name,
            "otlp_endpoint": self.otlp_endpoint,
            "otlp_protocol": self.otlp_protocol,
            "traces_enabled": self.traces_enabled,
            "metrics_enabled": self.metrics_enabled,
        }


class _NoopSpan:
    """A span handle that drops every attribute. Returned when telemetry is off."""

    def set(self, **_attrs: object) -> None:
        """No-op: the disabled span drops every attribute."""


class Telemetry:
    """No-op telemetry — the default and the base class for the SDK-backed impl.

    The SDK-backed :class:`colleague.telemetry._otel._OtelTelemetry` overrides
    these to emit real spans and metrics. Keeping the no-op as the base means a
    disabled drive pays nothing and imports no third-party module.
    """

    enabled = False

    @contextlib.contextmanager
    def drive_span(
        self, *, task_id: str, engine: str, model: str, max_steps: int
    ) -> Iterator[_NoopSpan]:
        yield _NoopSpan()

    @contextlib.contextmanager
    def tool_span(self, *, tool: str, step_index: int) -> Iterator[_NoopSpan]:
        yield _NoopSpan()

    @contextlib.contextmanager
    def handoff_span(self) -> Iterator[_NoopSpan]:
        yield _NoopSpan()

    def on_completion(self, prompt_tokens: int, completion_tokens: int) -> None:
        """No-op: token counts are dropped when telemetry is disabled."""

    def on_generated(self, *, reasoning: str = "", answer: str = "") -> None:
        """No-op: generated reasoning/answer sizes are dropped when disabled."""

    def on_bytes_written(self, n_bytes: int) -> None:
        """No-op: the bytes-written total is dropped when telemetry is disabled."""

    def on_hook_denial(self) -> None:
        """No-op: hook-denial counts are dropped when telemetry is disabled."""

    def trace_id_hex(self) -> str | None:
        return None

    def flush(self) -> None:
        pass


# A no-op singleton is enough for the disabled path — it is stateless.
_NOOP = Telemetry()


def sdk_available() -> bool:
    """Whether the full ``[otel]`` extra is importable — not just the API package.

    Probes the specific modules :mod:`colleague.telemetry._otel` actually needs
    (`opentelemetry.sdk` and the OTLP/HTTP exporter), not the bare ``opentelemetry``
    namespace — which can be present with only ``opentelemetry-api`` installed,
    in which case loading would still fail. Uses :func:`importlib.util.find_spec`
    so it never imports the SDK (keeping this module clean for the zero-deps guard).
    """
    required = (
        "opentelemetry.sdk",
        "opentelemetry.exporter.otlp.proto.http.trace_exporter",
    )
    try:
        return all(importlib.util.find_spec(name) is not None for name in required)
    except ModuleNotFoundError:
        # find_spec raises (not returns None) when a *parent* package is absent.
        return False


def _import_otel():
    """Import the SDK-backed module lazily (raises ImportError without the extra).

    Isolated so the missing-extra degradation path is testable regardless of
    whether ``opentelemetry`` happens to be installed in the test environment.
    """
    from colleague.telemetry import _otel

    return _otel


def load_telemetry(config: TelemetryConfig | None = None, **test_seams: object) -> Telemetry:
    """Return the active :class:`Telemetry` — SDK-backed when enabled, else no-op.

    Disabled (the default) → the no-op singleton, with no SDK import. Enabled but
    the ``[otel]`` extra missing → no-op + a one-time stderr diagnostic. Enabled
    with the SDK present → the shared, idempotently-initialised SDK-backed impl
    (mirroring culture's idempotent ``init_telemetry``). ``test_seams`` lets
    tests inject in-memory exporters (see :mod:`colleague.telemetry._otel`).
    """
    global _warned_missing
    cfg = config or TelemetryConfig.resolve()
    if not cfg.enabled:
        return _NOOP
    try:
        otel = _import_otel()
    except ImportError:
        if not _warned_missing:
            _warned_missing = True
            print(
                "telemetry: requested (COLLEAGUE_OTEL_ENABLED) but the [otel] extra is "
                "not installed — running without telemetry. Install with: "
                "pip install 'colleague[otel]'",
                file=sys.stderr,
            )
        return _NOOP
    return otel.get_telemetry(cfg, **test_seams)
