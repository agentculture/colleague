"""``convertible commands`` — discover and list command templates.

``commands list`` enumerates the command templates discovered under
``.convertible/commands/`` for the target repo; ``commands overview`` describes
the noun (satisfying the agent-first rubric: any noun with action-verbs must
also expose ``overview``).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from convertible import commands as _cmds
from convertible.cli._commands.overview import emit_overview
from convertible.cli._output import emit_result


def _commands_sections() -> list[dict[str, object]]:
    return [
        {
            "title": "What it does",
            "items": [
                "Discovers named command templates under .convertible/commands/*.md",
                "Templates support $1/$2/$ARGUMENTS substitution and optional metadata",
                "Use 'convertible drive --command <name>' to expand and run a template",
            ],
        },
        {
            "title": "Verbs",
            "items": [
                "commands list [--repo PATH] — list discovered command templates",
                "commands overview — describe the commands surface (this command)",
            ],
        },
    ]


def cmd_commands_overview(args: argparse.Namespace) -> int:
    emit_overview(
        "convertible commands",
        _commands_sections(),
        json_mode=bool(getattr(args, "json", False)),
    )
    return 0


def cmd_commands_list(args: argparse.Namespace) -> int:
    repo = Path(getattr(args, "repo", ".")).expanduser()
    json_mode = bool(getattr(args, "json", False))

    discovered = _cmds.discover_commands(repo)

    if json_mode:
        entries = []
        for name, path in sorted(discovered.items()):
            cmd = _cmds.load_command(path)
            entries.append({"name": cmd.name, "description": cmd.description})
        emit_result({"commands": entries}, json_mode=True)
    elif not discovered:
        emit_result("(no command templates found)", json_mode=False)
    else:
        lines = []
        for name, path in sorted(discovered.items()):
            cmd = _cmds.load_command(path)
            if cmd.description:
                lines.append(f"{name}\t{cmd.description}")
            else:
                lines.append(name)
        emit_result("\n".join(lines), json_mode=False)
    return 0


def _no_verb(args: argparse.Namespace) -> int:
    return cmd_commands_overview(args)


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "commands",
        help="Discover command templates (see 'convertible commands overview').",
    )
    p.add_argument("--json", action="store_true", help="Emit structured JSON.")
    p.set_defaults(func=_no_verb, json=False)
    noun_sub = p.add_subparsers(dest="commands_command", parser_class=type(p))

    lst = noun_sub.add_parser("list", help="List discovered command templates.")
    lst.add_argument("--repo", default=".", help="Path to the target repository (default: cwd).")
    lst.add_argument("--json", action="store_true", help="Emit structured JSON.")
    lst.set_defaults(func=cmd_commands_list)

    ov = noun_sub.add_parser("overview", help="Describe the commands surface.")
    ov.add_argument("--json", action="store_true", help="Emit structured JSON.")
    ov.set_defaults(func=cmd_commands_overview)
