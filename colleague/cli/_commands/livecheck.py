"""``colleague livecheck`` — probe endpoint and run gated live proofs.

One verb that probes the configured endpoint and runs the applicable gated
live proofs, reporting per-ledger-row pass/fail/skip.

When the endpoint probe fails, prints an honest skip report naming the
endpoint and exits 0 without running pytest. When reachable, runs the proofs
and prints a per-row table plus a summary line; exits 1 if any proof failed,
else 0.

Thin presentation layer: the logic lives in :mod:`colleague.livecheck`.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from colleague.cli._output import JSON_HELP, emit_result
from colleague.livecheck import ProofResult, probe_endpoint, run_proofs, select_proofs

_LIVECHECK_HELP = (
    "Probe the configured endpoint and run gated live proofs, reporting "
    "per-row pass/fail/skip (see 'colleague explain livecheck')."
)


def _configure_livecheck_parser(p: argparse.ArgumentParser) -> None:
    """Add livecheck flags to an already-created parser."""
    p.add_argument("--repo", default=".", help="Path to the target repository (default: cwd).")
    p.add_argument("--json", action="store_true", help=JSON_HELP)


def cmd_livecheck(args: argparse.Namespace) -> int:
    """Handle ``colleague livecheck``."""
    repo = Path(args.repo).expanduser()
    json_mode = bool(getattr(args, "json", False))

    # Step 1: probe the endpoint
    probe = probe_endpoint(repo)
    endpoint = probe["endpoint"]
    reachable = probe["reachable"]

    if not reachable:
        # Endpoint unreachable — honest skip report, exit 0
        skip_report = {
            "endpoint": endpoint,
            "reachable": False,
            "reason": probe["reason"],
            "proofs": [],
        }
        if json_mode:
            emit_result(skip_report, json_mode=True)
        else:
            _print_skip_report(endpoint, probe["reason"])
        return 0

    # Step 2: select and run proofs
    proofs = select_proofs(repo)
    if not proofs:
        # No proofs found — report that
        no_proofs = {
            "endpoint": endpoint,
            "reachable": True,
            "proofs": [],
        }
        if json_mode:
            emit_result(no_proofs, json_mode=True)
        else:
            print(f"endpoint {endpoint!r} reachable, no live proofs found")
        return 0

    results = run_proofs(proofs, repo)

    # Build output
    proof_rows = []
    for r in results:
        proof_rows.append(
            {
                "file": r.file,
                "status": r.status,
                "detail": r.detail,
            }
        )

    report = {
        "endpoint": endpoint,
        "reachable": True,
        "proofs": proof_rows,
    }

    if json_mode:
        emit_result(report, json_mode=True)
    else:
        _print_table(results)

    # Exit 1 if any proof failed
    has_failure = any(r.status == "failed" for r in results)
    return 1 if has_failure else 0


def _print_skip_report(endpoint: str, reason: str | None) -> None:
    """Print a human-readable skip report when the endpoint is unreachable."""
    print(f"endpoint {endpoint!r} not reachable")
    if reason:
        print(f"  reason: {reason}")
    print("  proofs: (skipped — endpoint unreachable)")


def _print_table(results: list[ProofResult]) -> None:
    """Print a per-row table of proof results plus a summary line."""
    # Column widths
    file_w = max(len(r.file) for r in results)
    file_w = min(max(file_w, 4), 50)  # cap at 50
    status_w = 8

    header = f"{'file':<{file_w}}  {'status':<{status_w}}  detail"
    print(header)
    print("-" * len(header))

    for r in results:
        detail = r.detail[:60] if r.detail else ""
        print(f"{r.file:<{file_w}}  {r.status:<{status_w}}  {detail}")

    # Summary
    passed = sum(1 for r in results if r.status == "passed")
    failed = sum(1 for r in results if r.status == "failed")
    skipped = sum(1 for r in results if r.status == "skipped")
    total = len(results)
    print(f"\nsummary: {passed} passed, {failed} failed, {skipped} skipped " f"({total} total)")


def register(sub: argparse._SubParsersAction) -> None:
    """Register livecheck with the legacy argparse subparser."""
    p = sub.add_parser("livecheck", help=_LIVECHECK_HELP)
    _configure_livecheck_parser(p)
    p.set_defaults(func=cmd_livecheck)


def register_into(app) -> None:
    """Register livecheck as an agentfront host command."""
    app.add_command(
        "livecheck",
        cmd_livecheck,
        help=_LIVECHECK_HELP,
        configure=_configure_livecheck_parser,
    )
