"""``convertible commands`` — discover, list, and approve command templates.

``commands list`` enumerates the command templates discovered under
``.convertible/commands/`` for the target repo; ``commands approve`` records a
checksum approval into ``<repo>/.convertible/approvals.json``; ``commands
overview`` describes the noun (satisfying the agent-first rubric: any noun with
action-verbs must also expose ``overview``).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from convertible import commands as _cmds
from convertible.cli import _approvals
from convertible.cli._commands.overview import emit_overview
from convertible.cli._errors import EXIT_USER_ERROR, CliError
from convertible.cli._output import JSON_HELP, emit_result
from convertible.configdir import CONFIG_DIR_NAME
from convertible.policy import file_checksum


def _commands_sections() -> list[dict[str, object]]:
    return [
        {
            "title": "What it does",
            "items": [
                "Discovers named command templates under .convertible/commands/*.md",
                "Templates support $1/$2/$ARGUMENTS substitution and optional metadata",
                "Use 'convertible drive --command <name>' to expand and run a template",
                "Approval gate: operator can approve templates by checksum (approvals.json)",
            ],
        },
        {
            "title": "Verbs",
            "items": [
                "commands list [--repo PATH] — list discovered templates + approval status",
                "commands approve <name> [--repo PATH] [--algo sha256|md5] — record approval",
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


def _compute_approval_status(name: str, path: Path, repo: Path) -> str:
    """Return 'approved', 'drifted', 'unapproved', or 'ungated'.

    - 'ungated'    — no commands section in approvals.json (gate not active).
    - 'unapproved' — commands section present but no entry for this name.
    - 'drifted'    — entry exists but checksum mismatches current file.
    - 'approved'   — entry exists and checksum matches.
    """
    section = _approvals.read_section(repo, "commands")
    if section is None:
        return "ungated"
    entry = section.get(name)
    if entry is None:
        return "unapproved"
    return _approvals.verify_status(path, entry)


def cmd_commands_list(args: argparse.Namespace) -> int:
    repo = Path(getattr(args, "repo", ".")).expanduser()
    json_mode = bool(getattr(args, "json", False))

    discovered = _cmds.discover_commands(repo)

    if json_mode:
        entries = []
        for name, path in sorted(discovered.items()):
            cmd = _cmds.load_command(path)
            status = _compute_approval_status(name, path, repo)
            entries.append(
                {
                    "name": cmd.name,
                    "description": cmd.description,
                    "status": status,
                }
            )
        emit_result({"commands": entries}, json_mode=True)
    elif not discovered:
        emit_result("(no command templates found)", json_mode=False)
    else:
        lines = []
        for name, path in sorted(discovered.items()):
            cmd = _cmds.load_command(path)
            status = _compute_approval_status(name, path, repo)
            if cmd.description:
                lines.append(f"{name}\t{cmd.description}\t[{status}]")
            else:
                lines.append(f"{name}\t[{status}]")
        emit_result("\n".join(lines), json_mode=False)
    return 0


def cmd_commands_approve(args: argparse.Namespace) -> int:
    name: str = args.name
    repo = Path(getattr(args, "repo", ".")).expanduser()
    algo: str = getattr(args, "algo", "sha256") or "sha256"
    json_mode = bool(getattr(args, "json", False))

    # Resolve the command template file
    discovered = _cmds.discover_commands(repo)
    if name not in discovered:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"command template {name!r} not found in {repo / CONFIG_DIR_NAME / 'commands'}",
            remediation="run 'convertible commands list --repo PATH' to see available commands",
        )

    path = discovered[name]
    try:
        checksum = file_checksum(path, algo)
    except (OSError, ValueError) as exc:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"could not checksum {path}: {exc}",
            remediation="ensure the file exists and is readable",
        ) from exc

    _approvals.write_approval(repo, "commands", name, checksum)

    result = {"name": name, "category": "commands", "checksum": checksum, "path": str(path)}
    text = f"approved commands/{name}  {checksum}"
    emit_result(result if json_mode else text, json_mode=json_mode)
    return 0


def _no_verb(args: argparse.Namespace) -> int:
    return cmd_commands_overview(args)


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "commands",
        help="Discover command templates (see 'convertible commands overview').",
    )
    p.add_argument("--json", action="store_true", help=JSON_HELP)
    p.set_defaults(func=_no_verb, json=False)
    noun_sub = p.add_subparsers(dest="commands_command", parser_class=type(p))

    lst = noun_sub.add_parser("list", help="List discovered command templates.")
    lst.add_argument("--repo", default=".", help="Path to the target repository (default: cwd).")
    lst.add_argument("--json", action="store_true", help=JSON_HELP)
    lst.set_defaults(func=cmd_commands_list)

    apr = noun_sub.add_parser("approve", help="Record a checksum approval for a command template.")
    apr.add_argument("name", help="Command template name (without .md extension).")
    apr.add_argument("--repo", default=".", help="Path to the target repository (default: cwd).")
    apr.add_argument(
        "--algo",
        default="sha256",
        choices=["sha256", "md5"],
        help="Checksum algorithm (default: sha256).",
    )
    apr.add_argument("--json", action="store_true", help=JSON_HELP)
    apr.set_defaults(func=cmd_commands_approve)

    ov = noun_sub.add_parser("overview", help="Describe the commands surface.")
    ov.add_argument("--json", action="store_true", help=JSON_HELP)
    ov.set_defaults(func=cmd_commands_overview)
