"""``colleague skills`` — inspect layered skill docs.

``skills list`` resolves the skill docs for a model — ``.colleague/skills/*.md``
(base) overlaid by ``.colleague/<model>/skills/*.md`` (model overlay shadows
base by stem) — and reports them with their winning scope. ``skills overview``
describes the noun (satisfying the agent-first rubric).

A skill is purely instructional: colleague folds a compact name +
one-line-summary catalog of the resolved skills into the system prompt every
drive sends. There is no skill *execution* model (an execution sandbox is out of
v0 scope); invokable skills are a tracked follow-up.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from colleague.cli._commands.overview import render_text
from colleague.cli._output import JSON_HELP, emit_result, rendered
from colleague.config import EngineConfig
from colleague.layers import resolve_skills


def _skills_sections() -> list[dict[str, object]]:
    return [
        {
            "title": "What it does",
            "items": [
                "Resolves skill docs for the current model",
                "base: .colleague/skills/*.md",
                "model overlay: .colleague/<model>/skills/*.md (shadows base by stem)",
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


# --- registry tool functions (rendered) + thin legacy adapters --------------


def _skills_overview() -> object:
    sections = _skills_sections()
    return rendered(
        {"subject": "colleague skills", "sections": sections},
        render_text("colleague skills", sections),
    )


def _skills_list(model: str | None = None, repo: str = ".") -> object:
    """Registry tool: resolved skill docs as ``rendered(dict, text)``.

    ``model`` / ``repo`` derive into ``--model`` / ``--repo``; an empty ``model``
    resolves to the engine's model exactly as the legacy ``--model`` default did.
    Mirrors the sibling ``agents list`` so the two layered-config nouns stay
    parallel, including the empty-state dual rendering.
    """
    repo_path = Path(repo).expanduser()
    resolved_model = model or EngineConfig.resolve().model
    skills = resolve_skills(repo_path, resolved_model)
    ordered = [skills[name] for name in sorted(skills)]
    if not ordered:
        text = "(no skills found)"
        items: list[dict[str, str]] = []
    else:
        text = "\n".join(f"{s.scope}\t{s.name}\t[accessible]" for s in ordered)
        items = [{"name": s.name, "scope": s.scope, "status": "accessible"} for s in ordered]
    return rendered({"model": resolved_model, "skills": items}, text)


def register_into(app) -> None:
    """Register the layered-skill inspection verbs on the agentfront App registry."""
    g = app.group("skills")
    g.tool(
        _skills_list,
        name="list",
        description="List resolved skill docs.",
        doc="# skills list [--model M] [--repo PATH]\nList the skill docs resolved "
        "for a model: base .colleague/skills/*.md overlaid by the per-model overlay, "
        "each with its winning scope (all accessible — skills are never gated).",
    )
    g.tool(
        _skills_overview,
        name="overview",
        description="Describe the skills surface.",
        doc="# skills overview\nDescribe the layered-skill surface: resolution, the "
        "instructional-only scope, and the verbs.",
    )


def cmd_skills_overview(args: argparse.Namespace) -> int:
    emit_result(_skills_overview(), json_mode=bool(getattr(args, "json", False)))
    return 0


def cmd_skills_list(args: argparse.Namespace) -> int:
    emit_result(
        _skills_list(model=getattr(args, "model", None), repo=getattr(args, "repo", ".")),
        json_mode=bool(getattr(args, "json", False)),
    )
    return 0


def _no_verb(args: argparse.Namespace) -> int:
    return cmd_skills_overview(args)


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "skills",
        help="Inspect layered skill docs (see 'colleague skills overview').",
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
