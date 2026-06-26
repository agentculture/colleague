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
from colleague.cli._commands.overview import render_text
from colleague.cli._errors import EXIT_USER_ERROR, CliError
from colleague.cli._output import JSON_HELP, emit_result, rendered
from colleague.configdir import CONFIG_DIR_NAME
from colleague.policy import file_checksum, load_policy, verify_checksum


def _commands_sections() -> list[dict[str, object]]:
    return [
        {
            "title": "What it does",
            "items": [
                "Discovers named command templates under .colleague/commands/*.md",
                "Templates support $1/$2/$ARGUMENTS substitution and optional metadata",
                "Use 'colleague work --command <name>' to expand and run a template",
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


# --- registry tool functions (rendered) + thin legacy adapters --------------


def _commands_overview() -> object:
    sections = _commands_sections()
    return rendered(
        {"subject": "colleague commands", "sections": sections},
        render_text("colleague commands", sections),
    )


def _commands_list(repo: str = ".", model: str = "") -> object:
    """Registry tool: discovered command templates + approval status.

    ``repo`` / ``model`` derive into ``--repo`` / ``--model``. The ``--json``
    shape uses each template's ``cmd.name``; the text column uses the discovered
    file key — preserved separately so both renderings stay byte-identical.
    """
    repo_path = Path(repo).expanduser()
    model_arg = model or None
    discovered = _cmds.discover_commands(repo_path)
    entries = []
    lines = []
    for name, path in sorted(discovered.items()):
        cmd = _cmds.load_command(path)
        status = _compute_approval_status(name, path, repo_path, model_arg)
        entries.append({"name": cmd.name, "description": cmd.description, "status": status})
        if cmd.description:
            lines.append(f"{name}\t{cmd.description}\t[{status}]")
        else:
            lines.append(f"{name}\t[{status}]")
    text = "\n".join(lines) if discovered else "(no command templates found)"
    return rendered({"commands": entries}, text)


def _commands_approve(name: str, repo: str = ".", algo: str = "sha256") -> object:
    """Registry tool: record a checksum approval for a command template.

    ``name`` (no default) derives into a positional argument. ``algo`` derives
    into ``--algo``; agentfront's Flag carries no ``choices``, so an invalid algo
    is caught by ``file_checksum`` (``ValueError`` → CliError) rather than at
    parse time — a clean error either way.
    """
    repo_path = Path(repo).expanduser()
    algo = algo or "sha256"
    discovered = _cmds.discover_commands(repo_path)
    if name not in discovered:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=(
                f"command template {name!r} not found in "
                f"{repo_path / CONFIG_DIR_NAME / 'commands'}"
            ),
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
    _approvals.write_approval(repo_path, "commands", name, checksum)
    result = {"name": name, "category": "commands", "checksum": checksum, "path": str(path)}
    return rendered(result, f"approved commands/{name}  {checksum}")


def register_into(app) -> None:
    """Register the command-template verbs on the agentfront App registry."""
    g = app.group("commands")
    g.tool(
        _commands_list,
        name="list",
        description="List discovered command templates.",
        doc="# commands list [--repo PATH] [--model M]\nList the command templates "
        "under .colleague/commands/ for the repo, each with its approval status.",
    )
    g.tool(
        _commands_approve,
        name="approve",
        description="Record a checksum approval for a command template.",
        doc="# commands approve <name> [--repo PATH] [--algo sha256|md5]\nRecord a "
        "checksum approval for a command template into .colleague/approvals.json.",
    )
    g.tool(
        _commands_overview,
        name="overview",
        description="Describe the commands surface.",
        doc="# commands overview\nDescribe the command-template surface: discovery, "
        "$1/$ARGUMENTS substitution, the approval gate, and the verbs.",
    )


def cmd_commands_overview(args: argparse.Namespace) -> int:
    emit_result(_commands_overview(), json_mode=bool(getattr(args, "json", False)))
    return 0


def cmd_commands_list(args: argparse.Namespace) -> int:
    emit_result(
        _commands_list(getattr(args, "repo", "."), getattr(args, "model", None) or ""),
        json_mode=bool(getattr(args, "json", False)),
    )
    return 0


def cmd_commands_approve(args: argparse.Namespace) -> int:
    emit_result(
        _commands_approve(args.name, getattr(args, "repo", "."), getattr(args, "algo", "sha256")),
        json_mode=bool(getattr(args, "json", False)),
    )
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
