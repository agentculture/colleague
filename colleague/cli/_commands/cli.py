"""``colleague cli`` — noun grouping CLI-surface introspection.

Exists to satisfy the agent-first rubric's ``overview_cli_noun_exists`` check:
any noun with action-verbs must also expose ``overview``. There are no
action-verbs under ``cli`` today, but ``cli overview`` describes the CLI surface
(distinct from the global ``overview``, which describes the agent).
"""

from __future__ import annotations

import argparse

from colleague.cli._commands.overview import cli_sections, render_text
from colleague.cli._output import emit_result, rendered


def _cli_overview() -> object:
    sections = cli_sections()
    return rendered(
        {"subject": "colleague cli", "sections": sections},
        render_text("colleague cli", sections),
    )


def register_into(app) -> None:
    """Register the ``cli`` introspection noun on the agentfront App registry."""
    g = app.group("cli")
    g.tool(
        _cli_overview,
        name="overview",
        description="Describe the colleague CLI surface.",
        doc="# cli overview\nDescribe the colleague CLI surface (the verbs and "
        "conventions) — distinct from the global `overview`, which describes the agent.",
    )


def cmd_cli_overview(args: argparse.Namespace) -> int:
    emit_result(_cli_overview(), json_mode=bool(getattr(args, "json", False)))
    return 0


def _no_verb(args: argparse.Namespace) -> int:
    # `colleague cli` with no sub-verb prints the noun's overview.
    return cmd_cli_overview(args)


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "cli",
        help="CLI-surface introspection (see 'colleague cli overview').",
    )
    p.add_argument("--json", action="store_true", help="Emit structured JSON.")
    p.set_defaults(func=_no_verb, json=False)
    # `p` is a _CliArgumentParser (the top-level subparsers were built with that
    # parser_class); propagate it so `cli overview` parse errors route through
    # the structured error contract instead of argparse's default stderr/exit 2.
    noun_sub = p.add_subparsers(dest="cli_command", parser_class=type(p))
    ov = noun_sub.add_parser("overview", help="Describe the colleague CLI surface.")
    ov.add_argument("--json", action="store_true", help="Emit structured JSON.")
    ov.set_defaults(func=cmd_cli_overview)
