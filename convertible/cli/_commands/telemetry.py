"""``convertible telemetry`` — inspect the GPS (OpenTelemetry) configuration.

``telemetry status`` reports the resolved :class:`~convertible.telemetry.TelemetryConfig`
(enabled flag, OTLP endpoint/protocol, service name, traces/metrics toggles) and
whether the optional ``[otel]`` extra is installed; ``telemetry overview``
describes the noun (satisfying the agent-first rubric: any noun with
action-verbs must also expose ``overview``).

This module imports only the **stdlib-clean** telemetry facade — never the SDK —
so ``convertible telemetry`` works (reporting ``sdk_installed: false``) even when
the extra is not installed.
"""

from __future__ import annotations

import argparse

from convertible.cli._commands.overview import emit_overview
from convertible.cli._output import JSON_HELP, emit_result
from convertible.telemetry import TelemetryConfig, sdk_available


def _telemetry_sections() -> list[dict[str, object]]:
    return [
        {
            "title": "What it does",
            "items": [
                "GPS for a drive: OpenTelemetry traces + metrics over OTLP",
                "Off by default; opt in with CONVERTIBLE_OTEL_ENABLED=1",
                "Needs the optional extra: pip install 'convertible-cli[otel]'",
                "Instrumented in the loop + shared drive path, so every engine emits it",
            ],
        },
        {
            "title": "Signals",
            "items": [
                "spans: convertible.drive -> convertible.tool.* (+ convertible.handoff)",
                "metrics: convertible.steps, convertible.tokens, convertible.generated.chars,"
                " convertible.bytes_written, convertible.tool.latency, convertible.tool.calls,"
                " convertible.hook.denials, convertible.drive.duration",
            ],
        },
        {
            "title": "Configuration (precedence: explicit > CONVERTIBLE_OTEL_* > OTEL_* > default)",
            "items": [
                "CONVERTIBLE_OTEL_ENABLED — turn telemetry on (default: off)",
                "CONVERTIBLE_OTEL_ENDPOINT / OTEL_EXPORTER_OTLP_ENDPOINT — collector URL",
                "CONVERTIBLE_OTEL_SERVICE_NAME / OTEL_SERVICE_NAME — resource service.name",
                "OTEL_SDK_DISABLED=true — standard kill-switch, forces telemetry off",
            ],
        },
        {
            "title": "Verbs",
            "items": [
                "telemetry status [--json] — show the resolved telemetry config",
                "telemetry overview — describe the telemetry surface (this command)",
            ],
        },
    ]


def cmd_telemetry_overview(args: argparse.Namespace) -> int:
    emit_overview(
        "convertible telemetry",
        _telemetry_sections(),
        json_mode=bool(getattr(args, "json", False)),
    )
    return 0


def cmd_telemetry_status(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    cfg = TelemetryConfig.resolve()
    installed = sdk_available()

    if json_mode:
        payload = cfg.to_dict()
        payload["sdk_installed"] = installed
        emit_result(payload, json_mode=True)
    else:
        lines = [
            f"enabled:        {cfg.enabled}",
            f"sdk_installed:  {installed}",
            f"service_name:   {cfg.service_name}",
            f"otlp_endpoint:  {cfg.otlp_endpoint}",
            f"otlp_protocol:  {cfg.otlp_protocol}",
            f"traces_enabled: {cfg.traces_enabled}",
            f"metrics_enabled:{cfg.metrics_enabled}",
        ]
        if cfg.enabled and not installed:
            lines.append("note:           enabled but the [otel] extra is not installed (no-op)")
        emit_result("\n".join(lines), json_mode=False)
    return 0


def _no_verb(args: argparse.Namespace) -> int:
    return cmd_telemetry_overview(args)


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "telemetry",
        help="Inspect the GPS / OpenTelemetry config (see 'convertible telemetry overview').",
    )
    p.add_argument("--json", action="store_true", help=JSON_HELP)
    p.set_defaults(func=_no_verb, json=False)
    noun_sub = p.add_subparsers(dest="telemetry_command", parser_class=type(p))

    st = noun_sub.add_parser("status", help="Show the resolved telemetry configuration.")
    st.add_argument("--json", action="store_true", help=JSON_HELP)
    st.set_defaults(func=cmd_telemetry_status)

    ov = noun_sub.add_parser("overview", help="Describe the telemetry surface.")
    ov.add_argument("--json", action="store_true", help=JSON_HELP)
    ov.set_defaults(func=cmd_telemetry_overview)
