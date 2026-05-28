"""``convertible doctor`` — configuration-readiness health check (oilcheck).

Thin presentation layer over :mod:`convertible.oilcheck`. The diagnostic logic
lives in the oilcheck check-group spine (a chassis-level package, like
:mod:`convertible.telemetry`); ``doctor`` only renders the aggregated report and
maps it to an exit code.

The report is the rubric-shaped contract
``{healthy, checks: [{id, passed, severity, message, remediation}]}`` so the
agent-first rubric's bundle 7 passes. ``doctor`` exits ``1`` when the report is
unhealthy (a failed ``error`` check), else ``0``. Read-only — every check-group
is contractually read-only, so a diagnosis never touches the repo.
"""

from __future__ import annotations

import argparse

from convertible.cli._output import emit_result
from convertible.oilcheck import diagnose


def cmd_doctor(args: argparse.Namespace) -> int:
    report = diagnose()
    json_mode = bool(getattr(args, "json", False))
    if json_mode:
        emit_result(report, json_mode=True)
    else:
        status = "healthy" if report["healthy"] else "unhealthy"
        lines = [f"convertible doctor: {status}", ""]
        for check in report["checks"]:
            mark = "ok" if check["passed"] else "FAIL"
            lines.append(f"[{mark}] {check['id']}: {check['message']}")
            if not check["passed"] and check["remediation"]:
                lines.append(f"  hint: {check['remediation']}")
        emit_result("\n".join(lines), json_mode=False)
    return 0 if report["healthy"] else 1


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "doctor",
        help="Check configuration readiness (identity, provider, engines, otel, environment).",
    )
    p.add_argument("--json", action="store_true", help="Emit structured JSON.")
    p.set_defaults(func=cmd_doctor)
