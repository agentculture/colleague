"""``colleague agents`` — inspect layered AGENTS instruction files.

``agents list`` resolves the AGENTS instruction cascade for a model
(``AGENTS.md`` -> ``AGENTS.colleague.md`` -> ``AGENTS.colleague.<model>.md``;
repo root with a ``~/.colleague/`` fallback) and reports the layers that
exist, in general -> specific order. ``agents overview`` describes the noun
(satisfying the agent-first rubric: any noun with action-verbs must also expose
``overview``).

These layers are composed (with the engine default and the skills catalog) into
the system prompt every drive sends — so what ``agents list`` reports for a model
is exactly what that model is instructed with. Per-model isolation is structural:
only the named model's overlay is read, never a sibling model's.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from colleague.cli._commands.overview import emit_overview
from colleague.cli._output import JSON_HELP, emit_result
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
                "Composed into the system prompt every drive sends to the engine",
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


def cmd_agents_overview(args: argparse.Namespace) -> int:
    emit_overview(
        "colleague agents",
        _agents_sections(),
        json_mode=bool(getattr(args, "json", False)),
    )
    return 0


def cmd_agents_list(args: argparse.Namespace) -> int:
    repo = Path(getattr(args, "repo", ".")).expanduser()
    model = getattr(args, "model", None) or EngineConfig.resolve().model
    json_mode = bool(getattr(args, "json", False))

    layers = resolve_agents(repo, model)

    if json_mode:
        items = [{"scope": layer.scope, "path": str(layer.path)} for layer in layers]
        emit_result({"model": model, "agents": items}, json_mode=True)
    elif not layers:
        emit_result("(no AGENTS layers found)", json_mode=False)
    else:
        lines = [f"{layer.scope}\t{layer.path}" for layer in layers]
        emit_result("\n".join(lines), json_mode=False)
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
