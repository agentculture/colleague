"""``colleague doctor`` — configuration-readiness health check.

Thin presentation layer over :mod:`colleague.oilcheck`. The diagnostic logic
lives in the health-check spine (a runtime-level package, like
:mod:`colleague.telemetry`); ``doctor`` only renders the aggregated report and
maps it to an exit code.

The report is the rubric-shaped contract
``{healthy, checks: [{id, passed, severity, message, remediation}]}`` so the
agent-first rubric's bundle 7 passes. ``doctor`` exits ``1`` when the report is
unhealthy (a failed ``error`` check), else ``0``. Read-only — every check-group
is contractually read-only, so a diagnosis never touches the repo.

With ``--repo``, the provider and reachability groups reflect the repo's
``.colleague/config.json`` (``base_url``, ``api_key``, ``model``); all other
groups remain env/defaults only.
"""

from __future__ import annotations

import argparse

from colleague.cli._output import emit_result
from colleague.oilcheck import diagnose


def cmd_doctor(args: argparse.Namespace) -> int:
    report = diagnose(
        probe=bool(getattr(args, "probe", False)),
        repo_path=getattr(args, "repo", "."),
    )
    json_mode = bool(getattr(args, "json", False))
    if json_mode:
        emit_result(report, json_mode=True)
    else:
        status = "healthy" if report["healthy"] else "unhealthy"
        lines = [f"colleague doctor: {status}", ""]
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
        help=(
            "Check configuration readiness (identity, provider, usage, engines, "
            "otel, environment)."
        ),
    )
    p.add_argument("--json", action="store_true", help="Emit structured JSON.")
    p.add_argument(
        "--probe",
        action="store_true",
        help="Also ping the provider server for reachability (opens a network connection).",
    )
    p.add_argument(
        "--repo",
        default=".",
        help=(
            "Repository path whose .colleague/config.json the provider + "
            "reachability checks reflect (default: cwd)."
        ),
    )
    p.set_defaults(func=cmd_doctor)
