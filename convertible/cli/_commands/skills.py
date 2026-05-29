"""``convertible skills`` — inspect layered skill docs.

``skills list`` resolves the skill docs for a model — ``.convertible/skills/*.md``
(base) overlaid by ``.convertible/<model>/skills/*.md`` (model overlay shadows
base by stem) — and reports them with their winning scope. ``skills overview``
describes the noun (satisfying the agent-first rubric).

A skill is purely instructional: convertible folds a compact name +
one-line-summary catalog of the resolved skills into the system prompt every
drive sends. There is no skill *execution* model (an execution sandbox is out of
v0 scope); invokable skills are a tracked follow-up.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from convertible.cli._commands.overview import emit_overview
from convertible.cli._output import JSON_HELP, emit_result
from convertible.config import EngineConfig
from convertible.layers import resolve_skills


def _skills_sections() -> list[dict[str, object]]:
    return [
        {
            "title": "What it does",
            "items": [
                "Resolves skill docs for the current model",
                "base: .convertible/skills/*.md",
                "model overlay: .convertible/<model>/skills/*.md (shadows base by stem)",
                "Folded into the system prompt as a name + one-line-summary catalog",
                "Skills are declarative/instructional — never approval-gated (status=accessible)",
            ],
        },
        {
            "title": "Scope",
            "items": [
                "A skill is instructional text only — no execution model in v0",
                "<model> is sanitized; only the named model's overlay is read",
                "Skills load freely; they are never blocked by the approval gate",
                "Invokable skills (skills as procedures) are a tracked follow-up",
            ],
        },
        {
            "title": "Verbs",
            "items": [
                "skills list [--model M] [--repo PATH] — list resolved skills (all accessible)",
                "skills overview — describe the skills surface (this command)",
            ],
        },
    ]


def cmd_skills_overview(args: argparse.Namespace) -> int:
    emit_overview(
        "convertible skills",
        _skills_sections(),
        json_mode=bool(getattr(args, "json", False)),
    )
    return 0


def cmd_skills_list(args: argparse.Namespace) -> int:
    repo = Path(getattr(args, "repo", ".")).expanduser()
    model = getattr(args, "model", None) or EngineConfig.resolve().model
    json_mode = bool(getattr(args, "json", False))

    skills = resolve_skills(repo, model)
    ordered = [skills[name] for name in sorted(skills)]

    if json_mode:
        items = [{"name": s.name, "scope": s.scope, "status": "accessible"} for s in ordered]
        emit_result({"model": model, "skills": items}, json_mode=True)
    elif not ordered:
        emit_result("(no skills found)", json_mode=False)
    else:
        lines = [f"{s.scope}\t{s.name}\t[accessible]" for s in ordered]
        emit_result("\n".join(lines), json_mode=False)
    return 0


def _no_verb(args: argparse.Namespace) -> int:
    return cmd_skills_overview(args)


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "skills",
        help="Inspect layered skill docs (see 'convertible skills overview').",
    )
    p.add_argument("--json", action="store_true", help=JSON_HELP)
    p.set_defaults(func=_no_verb, json=False)
    noun_sub = p.add_subparsers(dest="skills_command", parser_class=type(p))

    lst = noun_sub.add_parser("list", help="List resolved skill docs.")
    lst.add_argument("--repo", default=".", help="Path to the target repository (default: cwd).")
    lst.add_argument(
        "--model",
        default=None,
        help="Model to resolve skills for (default: the resolved engine model).",
    )
    lst.add_argument("--json", action="store_true", help=JSON_HELP)
    lst.set_defaults(func=cmd_skills_list)

    ov = noun_sub.add_parser("overview", help="Describe the skills surface.")
    ov.add_argument("--json", action="store_true", help=JSON_HELP)
    ov.set_defaults(func=cmd_skills_overview)
