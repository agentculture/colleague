"""OTel (GPS) readiness check-group — STUB.

Spec for the sibling agent who fills this in. This group reports on **GPS /
OpenTelemetry readiness** without enabling telemetry or importing the SDK
eagerly (the zero-deps guard must keep passing). It must:

* Report whether telemetry is **enabled** — resolve via
  :meth:`convertible.telemetry.TelemetryConfig.resolve` (or read
  ``CONVERTIBLE_OTEL_ENABLED`` / the standard ``OTEL_SDK_DISABLED`` kill-switch
  through that path) — as an ``info`` check.
* Report whether the optional ``[otel]`` extra (the OpenTelemetry SDK + OTLP/HTTP
  exporter) is importable — use :func:`convertible.telemetry.sdk_available`,
  which probes with ``importlib.util.find_spec`` and never imports the SDK. A
  lazy ``try/except`` around an actual import is also acceptable, but prefer the
  existing ``sdk_available`` seam so this stays import-clean.
* Report whether ``OTEL_EXPORTER_OTLP_ENDPOINT`` (or the convertible-prefixed /
  resolved endpoint) is set, as ``info``.
* Emit an ``error`` for the one genuinely broken state: telemetry is **enabled**
  but the ``[otel]`` extra is **not** importable (a drive would silently run
  without the telemetry the operator asked for). Otherwise, disabled or
  enabled-with-SDK is healthy.

Read-only and import-clean: never import ``opentelemetry`` from this module
(keep the SDK confined to ``convertible.telemetry._otel``). Catch unexpected
errors and return them as a failed check; never raise.

Until implemented, returns ``[]``.
"""

from __future__ import annotations


def checks() -> list[dict]:
    """STUB — returns no checks yet. See module docstring for the spec."""
    return []
