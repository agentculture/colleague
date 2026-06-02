"""OTel (GPS) readiness check-group.

Reports on GPS / OpenTelemetry readiness without enabling telemetry or
importing the SDK eagerly.  The zero-deps guard (``tests/test_zero_deps.py``)
must keep passing: no ``import opentelemetry`` at module top level.

Checks emitted
--------------
* ``otel_enabled``  (info) — whether telemetry is enabled, resolved via
  :meth:`colleague.telemetry.TelemetryConfig.resolve`.
* ``otel_sdk``      (info | error) — whether the ``[otel]`` extra is importable
  via :func:`colleague.telemetry.sdk_available` (uses ``importlib.util.find_spec``,
  never imports the SDK).  Error only when enabled AND SDK absent.
* ``otel_endpoint`` (info) — whether ``OTEL_EXPORTER_OTLP_ENDPOINT`` (or the
  colleague-prefixed fallback) is explicitly configured.

Severity rule: the ONLY error is enabled-but-SDK-missing.  Everything else is
info.  Never raises; unexpected errors are caught and returned as failed checks.
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit, urlunsplit

from colleague.oilcheck import make_check

# Truthy strings mirror telemetry's ``_as_bool`` so the kill-switch is read the
# same way the resolver reads it.
_TRUTHY = frozenset({"1", "true", "yes", "on"})


def _truthy(value: str | None) -> bool:
    return value is not None and value.strip().lower() in _TRUTHY


def _redact_endpoint(url: str) -> str:
    """Strip any ``user:password@`` userinfo from an OTLP endpoint URL.

    The endpoint is operator-facing diagnostic output; basic-auth credentials
    embedded in the URL must not leak into the report (mirrors the api_key
    redaction in the provider group). Non-URL / unparseable values pass through
    unchanged.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    if not (parts.username or parts.password):
        return url
    netloc = parts.hostname or ""
    if parts.port is not None:
        netloc = f"{netloc}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def checks() -> list[dict]:
    """Return OTel readiness checks.

    Read-only: reads env vars and probes importability via find_spec; never
    writes files, never opens sockets, never imports opentelemetry at this level.
    Never raises.
    """
    try:
        return _checks()
    except Exception as exc:  # pragma: no cover — safety net
        return [
            make_check(
                "otel_checks_error",
                False,
                "error",
                f"otel check-group raised unexpectedly: {exc}",
                remediation="Report this as a colleague bug.",
            )
        ]


def _checks() -> list[dict]:
    """Inner implementation — let exceptions propagate to the outer safety net."""
    from colleague.telemetry import TelemetryConfig, sdk_available

    cfg = TelemetryConfig.resolve()
    result: list[dict] = []

    # --- otel_enabled ---------------------------------------------------------
    if cfg.enabled:
        result.append(
            make_check(
                "otel_enabled",
                True,
                "info",
                "telemetry enabled (COLLEAGUE_OTEL_ENABLED)",
            )
        )
    elif _truthy(os.environ.get("OTEL_SDK_DISABLED")):
        # The standard OTel kill-switch forces telemetry off even if
        # COLLEAGUE_OTEL_ENABLED=1, so don't advise an action that won't work.
        result.append(
            make_check(
                "otel_enabled",
                True,
                "info",
                "telemetry disabled by the OTEL_SDK_DISABLED kill-switch "
                "(unset it, then set COLLEAGUE_OTEL_ENABLED=1, to enable GPS)",
            )
        )
    else:
        result.append(
            make_check(
                "otel_enabled",
                True,
                "info",
                "telemetry disabled (set COLLEAGUE_OTEL_ENABLED=1 to enable GPS)",
            )
        )

    # --- otel_sdk -------------------------------------------------------------
    sdk_ok = sdk_available()
    if cfg.enabled:
        if sdk_ok:
            result.append(
                make_check(
                    "otel_sdk",
                    True,
                    "info",
                    "OpenTelemetry SDK ([otel] extra) is importable",
                )
            )
        else:
            result.append(
                make_check(
                    "otel_sdk",
                    False,
                    "error",
                    "telemetry is enabled but the OpenTelemetry SDK is not installed",
                    remediation=(
                        "Install the [otel] extra: "
                        "uv sync --extra otel  "
                        "(or: pip install colleague[otel])"
                    ),
                )
            )
    else:
        # Telemetry is off — SDK presence is advisory only.
        result.append(
            make_check(
                "otel_sdk",
                True,
                "info",
                (
                    "OpenTelemetry SDK importable"
                    if sdk_ok
                    else "OpenTelemetry SDK ([otel] extra) not installed (telemetry is disabled)"
                ),
            )
        )

    # --- otel_endpoint --------------------------------------------------------
    # Mirror TelemetryConfig resolution: COLLEAGUE_OTEL_ENDPOINT wins (legacy
    # CONVERTIBLE_OTEL_ENDPOINT is a deprecated fallback), then
    # OTEL_EXPORTER_OTLP_ENDPOINT, then the default.
    explicit_endpoint = (
        os.environ.get("COLLEAGUE_OTEL_ENDPOINT")
        or os.environ.get("CONVERTIBLE_OTEL_ENDPOINT")
        or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    )
    if explicit_endpoint:
        result.append(
            make_check(
                "otel_endpoint",
                True,
                "info",
                f"OTLP endpoint configured: {_redact_endpoint(explicit_endpoint)}",
            )
        )
    else:
        result.append(
            make_check(
                "otel_endpoint",
                True,
                "info",
                f"OTLP endpoint not set; using default ({cfg.otlp_endpoint}). "
                "Set OTEL_EXPORTER_OTLP_ENDPOINT to override.",
            )
        )

    return result
