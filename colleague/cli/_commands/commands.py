"""``colleague commands`` — discover, list, and approve command templates.

``commands list`` enumerates the command templates discovered under
``.colleague/commands/`` for the target repo; ``commands approve`` records a
checksum approval into ``<repo>/.colleague/approvals.json``; ``commands
overview`` describes the noun (satisfying the agent-first rubric: any noun with
action-verbs must also expose ``overview``).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from colleague import commands as _cmds
from colleague.cli import _approvals
from colleague.cli._commands.overview import emit_overview
from colleague.cli._errors import EXIT_USER_ERROR, CliError
from colleague.cli._output import JSON_HELP, emit_result
from colleague.configdir import CONFIG_DIR_NAME
from colleague.policy import file_checksum, load_policy, verify_checksum


def _commands_sections() -> list[dict[str, object]]:
    return [
        {
            "title": "What it does",
            "items": [
                "Discovers named command templates under .colleague/commands/*.md",
                "Templates support $1/$2/$ARGUMENTS substitution and optional metadata",
                "Use 'colleague drive --command <name>' to expand and run a template",
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
        "colleague commands",
        _commands_sections(),
        json_mode=bool(getattr(args, "json", False)),
    )
    return 0


def _compute_approval_status(name: str, path: Path, repo: Path, model: str | None = None) -> str:
    """Return 'approved', 'drifted', 'unapproved', or 'ungated'.

    Reflects the *merged* policy (repo-over-user + per-model overlay), the same
    source enforcement uses — not a raw single-file read:

    - 'ungated'    — no commands section in the merged policy (gate not active).
    - 'unapproved' — commands section present but no entry for this name.
    - 'drifted'    — entry exists but checksum mismatches current file.
    - 'approved'   — entry exists and checksum matches.
    """
    policy = load_policy(repo, model=model)
    if not policy.section_present("commands"):
        return "ungated"
    approval = policy.file_approval("commands", name)
    if approval is None:
        return "unapproved"
    return "approved" if verify_checksum(path, approval) else "drifted"


def cmd_commands_list(args: argparse.Namespace) -> int:
    repo = Path(getattr(args, "repo", ".")).expanduser()
    json_mode = bool(getattr(args, "json", False))
    model: str | None = getattr(args, "model", None) or None

    discovered = _cmds.discover_commands(repo)

    if json_mode:
        entries = []
        for name, path in sorted(discovered.items()):
            cmd = _cmds.load_command(path)
            status = _compute_approval_status(name, path, repo, model)
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
            status = _compute_approval_status(name, path, repo, model)
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
            remediation="run 'colleague commands list --repo PATH' to see available commands",
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
        help="Discover command templates (see 'colleague commands overview').",
    )
    p.add_argument("--json", action="store_true", help=JSON_HELP)
    p.set_defaults(func=_no_verb, json=False)
    noun_sub = p.add_subparsers(dest="commands_command", parser_class=type(p))

    lst = noun_sub.add_parser("list", help="List discovered command templates.")
    lst.add_argument("--repo", default=".", help="Path to the target repository (default: cwd).")
    lst.add_argument(
        "--model",
        default=None,
        metavar="MODEL",
        help=(
            "Resolve approval status against the per-model overlay "
            ".colleague/<model>/approvals.json (the <model> token is sanitized), "
            "matching how enforcement merges policy for that model."
        ),
    )
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
