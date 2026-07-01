"""``colleague skills`` — inspect layered skill docs.

``skills list`` resolves the skill docs for a model — ``.colleague/skills/*.md``
(base) overlaid by ``.colleague/<model>/skills/*.md`` (model overlay shadows
base by stem) — and reports them with their winning scope. ``skills overview``
describes the noun (satisfying the agent-first rubric).

A skill is purely instructional: colleague folds a compact name +
one-line-summary catalog of the resolved skills into the system prompt every
drive sends. There is no skill *execution* model (an execution sandbox is out of
v0 scope); invokable skills are a tracked follow-up.

``skills list`` additionally accepts two optional flags that mirror what
actually gets composed at drive time (never a separate, driftable code path):

- ``--role NAME`` filters the catalog to that role's curated ``skill_subset``
  (:func:`colleague.layers._filter_skills`), the same filtering
  :func:`colleague.layers.compose_role_prompt` applies.
- ``--budget TOKENS`` additionally shows, for the (role-filtered) catalog,
  which skills COMPOSE within that token cap and which would be OMITTED (each
  with its declared ``<!-- skill-priority: N -->`` priority) —
  :func:`colleague.layers.select_skills_within_budget` is the exact helper
  :func:`colleague.layers.compose_skills` uses to cap the real system prompt.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from colleague.cli._commands.overview import render_text
from colleague.cli._errors import EXIT_USER_ERROR, CliError
from colleague.cli._output import JSON_HELP, emit_result, rendered
from colleague.config import EngineConfig
from colleague.layers import Skill, _filter_skills, resolve_skills, select_skills_within_budget
from colleague.layers import skill_priority as _skill_priority_of
from colleague.roles import load_role


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
                "skills list [--model M] [--repo PATH] [--role NAME] [--budget N] "
                "— list resolved skills (all accessible)",
                "--role filters to that role's curated skill_subset before listing",
                "--budget additionally splits the (role-filtered) catalog into "
                "composed vs omitted at that token cap, with each skill's priority",
                "skills overview — describe the skills surface (this command)",
            ],
        },
    ]


def _resolve_role_subset(
    role: str | None, repo_path: Path, resolved_model: str
) -> tuple[str, ...] | None:
    """Resolve *role*'s ``skill_subset``, or ``None`` when *role* is unset.

    Raises a clean :class:`CliError` for an unknown role name — never a
    silent no-op (an operator typo in ``--role`` must be visible, not quietly
    treated as "no role").
    """
    if not role:
        return None
    loaded = load_role(role, repo_path, resolved_model)
    if loaded is None:
        raise CliError(
            EXIT_USER_ERROR,
            f"unknown role: {role!r}",
            "see 'colleague roles list' for the known role names",
        )
    return loaded.skill_subset


def _skill_entry(skills: dict[str, Skill], name: str) -> dict[str, object]:
    skill = skills[name]
    return {"name": name, "scope": skill.scope, "priority": _skill_priority_of(skill)}


# --- registry tool functions (rendered) + thin legacy adapters --------------


def _skills_overview() -> object:
    sections = _skills_sections()
    return rendered(
        {"subject": "colleague skills", "sections": sections},
        render_text("colleague skills", sections),
    )


def _skills_list(
    model: str | None = None,
    repo: str = ".",
    role: str | None = None,
    budget: int = 0,
) -> object:
    """Registry tool: resolved skill docs as ``rendered(dict, text)``.

    ``model`` / ``repo`` / ``role`` / ``budget`` derive into ``--model`` /
    ``--repo`` / ``--role`` / ``--budget``. An empty ``model`` resolves to the
    engine's model exactly as the legacy ``--model`` default did. ``budget``
    defaults to ``0``, meaning "no budget given" — the classic listing shape
    (byte-identical to today). A positive ``--budget`` switches to the
    composed-vs-omitted inspection shape instead.
    """
    repo_path = Path(repo).expanduser()
    resolved_model = model or EngineConfig.resolve().model
    all_skills = resolve_skills(repo_path, resolved_model)
    subset = _resolve_role_subset(role, repo_path, resolved_model)
    filtered = _filter_skills(all_skills, subset)

    if budget <= 0:
        ordered = [filtered[name] for name in sorted(filtered)]
        if not ordered:
            text = "(no skills found)"
            items: list[dict[str, str]] = []
        else:
            text = "\n".join(f"{s.scope}\t{s.name}\t[accessible]" for s in ordered)
            items = [{"name": s.name, "scope": s.scope, "status": "accessible"} for s in ordered]
        payload: dict[str, object] = {"model": resolved_model, "skills": items}
        if role:
            payload["role"] = role
        return rendered(payload, text)

    kept, omitted_names = select_skills_within_budget(filtered, budget)
    composed = [_skill_entry(filtered, name) for name in sorted(kept)]
    omitted = [_skill_entry(filtered, name) for name in omitted_names]
    payload = {
        "model": resolved_model,
        "budget": budget,
        "composed": composed,
        "omitted": omitted,
    }
    if role:
        payload["role"] = role

    lines = [f"budget: {budget} tokens"]
    if role:
        lines.append(f"role: {role}")
    lines.append(f"composed ({len(composed)}):")
    if composed:
        lines.extend(f"  {c['name']} (priority {c['priority']})" for c in composed)
    else:
        lines.append("  (none)")
    lines.append(f"omitted ({len(omitted)}):")
    if omitted:
        lines.extend(f"  {o['name']} (priority {o['priority']})" for o in omitted)
    else:
        lines.append("  (none)")
    return rendered(payload, "\n".join(lines))


def register_into(app) -> None:
    """Register the layered-skill inspection verbs on the agentfront App registry."""
    g = app.group("skills")
    g.tool(
        _skills_list,
        name="list",
        description="List resolved skill docs.",
        doc="# skills list [--model M] [--repo PATH] [--role NAME] [--budget N]\n"
        "List the skill docs resolved for a model: base .colleague/skills/*.md "
        "overlaid by the per-model overlay, each with its winning scope (all "
        "accessible — skills are never gated). --role filters to that role's "
        "curated skill_subset; --budget additionally shows which skills compose "
        "vs. would be omitted at that token cap, with each skill's declared "
        "priority.",
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
        _skills_list(
            model=getattr(args, "model", None),
            repo=getattr(args, "repo", "."),
            role=getattr(args, "role", None),
            budget=getattr(args, "budget", 0) or 0,
        ),
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
    lst.add_argument(
        "--role",
        default=None,
        help="Filter to a role's curated skill_subset (see 'colleague roles list').",
    )
    lst.add_argument(
        "--budget",
        type=int,
        default=0,
        help="Show composed-vs-omitted skills at this token cap (0 = plain list).",
    )
    lst.add_argument("--json", action="store_true", help=JSON_HELP)
    lst.set_defaults(func=cmd_skills_list)

    ov = noun_sub.add_parser("overview", help="Describe the skills surface.")
    ov.add_argument("--json", action="store_true", help=JSON_HELP)
    ov.set_defaults(func=cmd_skills_overview)
