"""``colleague explain <path>...`` — global markdown catalog lookup (stable-contract).

``explain`` is global (not nested under a noun). It takes zero or more path
tokens and resolves them via the catalog in :mod:`colleague.explain`.
Unknown paths raise :class:`CliError` with a remediation hint.
"""

from __future__ import annotations

import argparse

from colleague.cli._output import emit_result
from colleague.explain import resolve


def cmd_explain(args: argparse.Namespace) -> int:
    path = tuple(args.path) if args.path else ()
    markdown = resolve(path)
    json_mode = bool(getattr(args, "json", False))
    if json_mode:
        emit_result({"path": list(path), "markdown": markdown}, json_mode=True)
    else:
        # On the bare root form, surface that `explain` takes a topic — a new
        # user otherwise can't tell the richer per-verb docs exist. Human output
        # only; the --json contract above stays the raw catalog markdown.
        if not path:
            markdown += (
                "\n\n---\n"
                "_Tip: `colleague explain <topic>` shows docs for a specific verb "
                "(e.g. `colleague explain work`, `colleague explain feedback`)._"
            )
        emit_result(markdown, json_mode=False)
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "explain",
        help="Print markdown docs for a noun/verb path. Supports --json.",
    )
    p.add_argument(
        "path",
        nargs="*",
        help="Command path tokens; empty = root (same as 'colleague').",
    )
    p.add_argument("--json", action="store_true", help="Emit structured JSON.")
    p.set_defaults(func=cmd_explain)
