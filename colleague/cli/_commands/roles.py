"""``colleague roles`` — inspect the typed subagent roles.

``roles list`` shows every built-in subagent role (explorer, planner, reviewer,
validator, writer) resolved for a model — its read-only flag, curated tool
allow-list, and skill subset. A *role* types a delegated subagent: it gives the
child a tailored prompt, a curated subset of the tool surface, and a curated
skill subset. Read-only roles (explorer/planner/reviewer/validator) withhold
``write_file``, ``edit_file``, and ``run_command``, so they provably cannot
mutate the tree; ``validator`` additionally gets a read-only ``run_tests``
capability (no write/exec surface).

Operator-authored prompt overlays at ``.colleague/agents/<name>.md`` (and the
per-model ``.colleague/<model>/agents/<name>.md``) override a built-in role's
prompt; ``roles list`` resolves them for the named model. This noun is distinct
from the sibling ``agents`` noun, which inspects the AGENTS *instruction-file*
cascade. ``roles overview`` describes the surface (satisfying the agent-first
rubric: any noun with action-verbs must also expose ``overview``).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from colleague.cli._commands.overview import emit_overview
from colleague.cli._output import JSON_HELP, emit_result
from colleague.config import EngineConfig
from colleague.roles import BUILTIN_ROLES, Role, load_role


def _roles_sections() -> list[dict[str, object]]:
    return [
        {
            "title": "What it does",
            "items": [
                "Lists the typed subagent roles (a child's prompt + curated tools + skills)",
                "Built-ins: explorer, planner, reviewer, validator (read-only); writer (full)",
                "Read-only roles withhold write_file, edit_file, run_command — cannot mutate the tree",
                "validator adds a read-only run_tests capability (no write/exec surface)",
            ],
        },
        {
            "title": "Roles vs agents",
            "items": [
                "roles  = typed SUBAGENT profiles (this noun)",
                "agents = layered AGENTS *instruction files* (the sibling 'agents' noun)",
                "Operator prompt overlay: .colleague/agents/<name>.md (+ per-model overlay)",
            ],
        },
        {
            "title": "Verbs",
            "items": [
                "roles list [--model M] [--repo PATH] [--json] — list resolved roles",
                "roles overview — describe the roles surface (this command)",
            ],
        },
    ]


def _role_to_dict(role: Role) -> dict[str, object]:
    return {
        "name": role.name,
        "read_only": role.read_only,
        "tools": list(role.tool_allowlist),
        "skills": (None if role.skill_subset is None else list(role.skill_subset)),
    }


def _resolve_roles(repo: Path, model: str) -> list[Role]:
    """Resolve every built-in role for *model*, applying any operator prompt overlay."""
    resolved: list[Role] = []
    for name in BUILTIN_ROLES:
        # load_role applies a .colleague/agents/<name>.md prompt overlay when present
        # and falls back to the built-in; it never returns None for a built-in name.
        resolved.append(load_role(name, repo, model) or BUILTIN_ROLES[name])
    return resolved


def cmd_roles_overview(args: argparse.Namespace) -> int:
    emit_overview(
        "colleague roles",
        _roles_sections(),
        json_mode=bool(getattr(args, "json", False)),
    )
    return 0


def cmd_roles_list(args: argparse.Namespace) -> int:
    repo = Path(getattr(args, "repo", ".")).expanduser()
    model = getattr(args, "model", None) or EngineConfig.resolve().model
    json_mode = bool(getattr(args, "json", False))

    roles = _resolve_roles(repo, model)

    if json_mode:
        emit_result({"model": model, "roles": [_role_to_dict(r) for r in roles]}, json_mode=True)
    else:
        lines = []
        for r in roles:
            flag = "read-only" if r.read_only else "full"
            skills = "all" if r.skill_subset is None else (",".join(r.skill_subset) or "none")
            lines.append(
                f"{r.name}\t[{flag}]\ttools: {','.join(r.tool_allowlist)}\tskills: {skills}"
            )
        emit_result("\n".join(lines), json_mode=False)
    return 0


def _no_verb(args: argparse.Namespace) -> int:
    return cmd_roles_overview(args)


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "roles",
        help="Inspect the typed subagent roles (see 'colleague roles overview').",
    )
    p.add_argument("--json", action="store_true", help=JSON_HELP)
    p.set_defaults(func=_no_verb, json=False)
    noun_sub = p.add_subparsers(dest="roles_command", parser_class=type(p))

    lst = noun_sub.add_parser("list", help="List the resolved typed subagent roles.")
    lst.add_argument("--repo", default=".", help="Path to the target repository (default: cwd).")
    lst.add_argument(
        "--model",
        default=None,
        help="Model to resolve roles for (default: the resolved engine model).",
    )
    lst.add_argument("--json", action="store_true", help=JSON_HELP)
    lst.set_defaults(func=cmd_roles_list)

    ov = noun_sub.add_parser("overview", help="Describe the roles surface.")
    ov.add_argument("--json", action="store_true", help=JSON_HELP)
    ov.set_defaults(func=cmd_roles_overview)
