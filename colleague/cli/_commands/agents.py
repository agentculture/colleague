"""``colleague agents`` — inspect layered AGENTS instruction files.

``agents list`` resolves the AGENTS instruction cascade for a model
(``AGENTS.md`` -> ``AGENTS.colleague.md`` -> ``AGENTS.colleague.<model>.md``;
repo root with a ``~/.colleague/`` fallback) and reports the layers that
exist, in general -> specific order. ``agents overview`` describes the noun
(satisfying the agent-first rubric: any noun with action-verbs must also expose
``overview``).

These layers are composed (with the engine default and the skills catalog) into
the system prompt every work item sends — so what ``agents list`` reports for a model
is exactly what that model is instructed with. Per-model isolation is structural:
only the named model's overlay is read, never a sibling model's.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from colleague.cli._commands.overview import render_text
from colleague.cli._output import JSON_HELP, emit_result, rendered
from colleague.config import EngineConfig
from colleague.layers import resolve_agents


def _agents_sections() -> list[dict[str, object]]:
    return [
        {
            "title": "What it does",
            "items": [
                "Resolves AGENTS instruction layers for the current model",
                "Cascade (general -> specific): AGENTS.md, AGENTS.colleague.md, "
                "AGENTS.colleague.<model>.md",
                "Read from the repo root, with a ~/.colleague/ user-level fallback",
                "Composed into the system prompt every work item sends to the engine",
            ],
        },
        {
            "title": "Per-model isolation",
            "items": [
                "<model> is sanitized (e.g. 'Qwen/Qwen3-32B' -> 'Qwen-Qwen3-32B')",
                "Only the named model's overlay is read — never a sibling model's",
                "MCP layering is not built yet (no mcp.json reader); tracked separately",
            ],
        },
        {
            "title": "Verbs",
            "items": [
                "agents list [--model M] [--repo PATH] — list resolved AGENTS layers",
                "agents overview — describe the agents surface (this command)",
            ],
        },
    ]


# --- registry tool functions ------------------------------------------------
# Named params (no argparse Namespace), return rendered(structured, text). The
# agentfront-rendered CLI derives the args from the signature and emits the
# return value (--json -> the dict, else the pretty text). The legacy cmd_*
# handlers below are thin adapters over these, so both doors share one
# rendering and the pre-flip --json/text output stays byte-identical.


def _agents_overview() -> object:
    sections = _agents_sections()
    return rendered(
        {"subject": "colleague agents", "sections": sections},
        render_text("colleague agents", sections),
    )


def _agents_list(model: str | None = None, repo: str = ".") -> object:
    repo_path = Path(repo).expanduser()
    resolved_model = model or EngineConfig.resolve().model
    layers = resolve_agents(repo_path, resolved_model)

    if not layers:
        text = "(no AGENTS layers found)"
        items: list[dict[str, str]] = []
    else:
        lines = [f"{layer.scope}\t{layer.path}" for layer in layers]
        text = "\n".join(lines)
        items = [{"scope": layer.scope, "path": str(layer.path)} for layer in layers]

    return rendered({"model": resolved_model, "agents": items}, text)


def register_into(app) -> None:
    """Register the agents verbs on the agentfront App registry."""
    g = app.group("agents")
    g.tool(
        _agents_list,
        name="list",
        description="List resolved AGENTS instruction layers.",
        doc="# agents list\nList the AGENTS instruction layers resolved for a model "
        "(AGENTS.md -> AGENTS.colleague.md -> AGENTS.colleague.<model>.md).",
    )
    g.tool(
        _agents_overview,
        name="overview",
        description="Describe the agents surface.",
        doc="# agents overview\nDescribe the layered AGENTS instruction file surface.",
    )


# --- legacy argparse path (pre-flip) ----------------------------------------
# Thin adapters delegating to the registry tool functions so the live argparse
# CLI stays byte-identical until the entry is flipped to the rendered CLI.


def cmd_agents_overview(args: argparse.Namespace) -> int:
    emit_result(_agents_overview(), json_mode=bool(getattr(args, "json", False)))
    return 0


def cmd_agents_list(args: argparse.Namespace) -> int:
    emit_result(
        _agents_list(
            model=getattr(args, "model", None),
            repo=getattr(args, "repo", "."),
        ),
        json_mode=bool(getattr(args, "json", False)),
    )
    return 0


def _no_verb(args: argparse.Namespace) -> int:
    return cmd_agents_overview(args)


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "agents",
        help="Inspect layered AGENTS instruction files (see 'colleague agents overview').",
    )
    p.add_argument("--json", action="store_true", help=JSON_HELP)
    p.set_defaults(func=_no_verb, json=False)
    noun_sub = p.add_subparsers(dest="agents_command", parser_class=type(p))

    lst = noun_sub.add_parser("list", help="List resolved AGENTS instruction layers.")
    lst.add_argument("--repo", default=".", help="Path to the target repository (default: cwd).")
    lst.add_argument(
        "--model",
        default=None,
        help="Model to resolve layers for (default: the resolved engine model).",
    )
    lst.add_argument("--json", action="store_true", help=JSON_HELP)
    lst.set_defaults(func=cmd_agents_list)

    ov = noun_sub.add_parser("overview", help="Describe the agents surface.")
    ov.add_argument("--json", action="store_true", help=JSON_HELP)
    ov.set_defaults(func=cmd_agents_overview)
