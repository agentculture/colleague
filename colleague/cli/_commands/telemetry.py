"""``colleague telemetry`` — inspect the telemetry (OpenTelemetry) configuration.

``telemetry status`` reports the resolved :class:`~colleague.telemetry.TelemetryConfig`
(enabled flag, OTLP endpoint/protocol, service name, traces/metrics toggles) and
whether the optional ``[otel]`` extra is installed; ``telemetry overview``
describes the noun (satisfying the agent-first rubric: any noun with
action-verbs must also expose ``overview``).

This module imports only the **stdlib-clean** telemetry facade — never the SDK —
so ``colleague telemetry`` works (reporting ``sdk_installed: false``) even when
the extra is not installed.
"""

from __future__ import annotations

import argparse

from colleague.cli._commands.overview import render_text
from colleague.cli._output import JSON_HELP, emit_result, rendered
from colleague.telemetry import TelemetryConfig, sdk_available


def _telemetry_sections() -> list[dict[str, object]]:
    return [
        {
            "title": "What it does",
            "items": [
                "Telemetry for a work item: OpenTelemetry traces + metrics over OTLP",
                "Off by default; opt in with COLLEAGUE_OTEL_ENABLED=1",
                "Needs the optional extra: pip install 'colleague[otel]'",
                "Instrumented in the loop + shared work path, so every backend emits it",
            ],
        },
        {
            "title": "Signals",
            "items": [
                "spans: colleague.work -> colleague.tool.* (+ colleague.handoff)",
                "metrics: colleague.steps, colleague.tokens, colleague.generated.chars,"
                " colleague.bytes_written, colleague.tool.latency, colleague.tool.calls,"
                " colleague.hook.denials, colleague.work.duration",
            ],
        },
        {
            "title": "Configuration (precedence: explicit > COLLEAGUE_OTEL_* > OTEL_* > default)",
            "items": [
                "COLLEAGUE_OTEL_ENABLED — turn telemetry on (default: off)",
                "COLLEAGUE_OTEL_ENDPOINT / OTEL_EXPORTER_OTLP_ENDPOINT — collector URL",
                "COLLEAGUE_OTEL_SERVICE_NAME / OTEL_SERVICE_NAME — resource service.name",
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


# --- registry tool functions (rendered) + thin legacy adapters --------------


def _telemetry_overview() -> object:
    sections = _telemetry_sections()
    return rendered(
        {"subject": "colleague telemetry", "sections": sections},
        render_text("colleague telemetry", sections),
    )


def _telemetry_status() -> object:
    cfg = TelemetryConfig.resolve()
    installed = sdk_available()
    payload = cfg.to_dict()
    payload["sdk_installed"] = installed
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
    return rendered(payload, "\n".join(lines))


def register_into(app) -> None:
    """Register the telemetry inspection verbs on the agentfront App registry."""
    g = app.group("telemetry")
    g.tool(
        _telemetry_status,
        name="status",
        description="Show the resolved telemetry configuration.",
        doc="# telemetry status\nShow the resolved OpenTelemetry config (enabled, "
        "endpoint, protocol, service name, traces/metrics) + whether the [otel] "
        "extra is installed.",
    )
    g.tool(
        _telemetry_overview,
        name="overview",
        description="Describe the telemetry surface.",
        doc="# telemetry overview\nDescribe the telemetry surface: the signals, the "
        "configuration precedence, and the verbs.",
    )


def cmd_telemetry_overview(args: argparse.Namespace) -> int:
    emit_result(_telemetry_overview(), json_mode=bool(getattr(args, "json", False)))
    return 0


def cmd_telemetry_status(args: argparse.Namespace) -> int:
    emit_result(_telemetry_status(), json_mode=bool(getattr(args, "json", False)))
    return 0


def _no_verb(args: argparse.Namespace) -> int:
    return cmd_telemetry_overview(args)


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "telemetry",
        help="Inspect the telemetry / OpenTelemetry config (see 'colleague telemetry overview').",
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
