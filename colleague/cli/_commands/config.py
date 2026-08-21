"""``colleague config`` — inspect the resolved engine/provider configuration.

``config show`` prints the resolved :class:`~colleague.config.EngineConfig`
(base_url, model, max_steps, temperature, timeout, context_budget_tokens) with
the api_key redacted. ``config overview`` describes the noun.

Precedence (highest first): explicit flag > COLLEAGUE_*/OPENAI_* env >
.colleague/config.json > built-in default.
"""

from __future__ import annotations

import argparse

from colleague.cli._commands.overview import render_text
from colleague.cli._output import JSON_HELP, emit_result, rendered
from colleague.config import (
    EngineConfig,
    config_provenance,
    resolve_lobes_gateway_url,
)


def _config_sections() -> list[dict[str, object]]:
    return [
        {
            "title": "What it does",
            "items": [
                "Show the resolved provider configuration (base_url, model, etc.)",
                "api_key is always redacted — never printed in any output",
                "Reflects .colleague/config.json when --repo is given",
            ],
        },
        {
            "title": "Configuration",
            "items": [
                "precedence: flag > COLLEAGUE_*/OPENAI_* env > .colleague/config.json "
                "> lobes discovery > default",
                "lobes discovery — when armed (COLLEAGUE_LOBES_URL or a config.json "
                "'lobes' section) cortex/senses resolve by role from the gateway",
                "base_url — provider endpoint (default: http://localhost:8001/v1)",
                "model — model id to call",
                "api_key — redacted in all output",
                "max_steps, temperature, timeout, context_budget_tokens — engine knobs",
            ],
        },
        {
            "title": "Verbs",
            "items": [
                "config show [--repo PATH] [--json] — show the resolved provider config",
                "config overview — describe the config surface (this command)",
            ],
        },
    ]


# --- registry tool functions (rendered) + thin legacy adapters --------------


def _config_show(repo: str = ".") -> object:
    """Registry tool: the resolved provider config as ``rendered(dict, text)``.

    ``repo`` (default ``"."``) is derived by agentfront into ``--repo`` from this
    signature, matching the legacy ``config show --repo PATH``. ``api_key`` is
    redacted by :meth:`EngineConfig.to_dict`, never printed.
    """
    cfg = EngineConfig.resolve(repo_path=repo)
    lines = [
        f"base_url:               {cfg.base_url}",
        f"model:                  {cfg.model}",
        f"max_steps:              {cfg.max_steps}",
        f"temperature:            {cfg.temperature}",
        f"timeout:                {cfg.timeout}",
        f"context_budget_tokens:  {cfg.context_budget_tokens}",
    ]
    provenance = config_provenance(repo)
    if provenance:
        for entry in provenance:
            keys = ", ".join(entry["keys"])
            wins = ", ".join(entry["winning_keys"])
            lines.append(f"config_file: {entry['path']} sets [{keys}] (wins: {wins})")
    else:
        lines.append("config_file: (none — using env vars + built-in defaults)")

    # Lobes discovery rung (cortex/senses arc, t4): reflect the ARMED state so an
    # operator can debug it. cfg.model above already reflects the rung in effect
    # (cortex when the gateway resolved, else the degraded next-rung value). The
    # to_dict() snapshot stays byte-identical (the guard); the lobes key is added
    # to the rendered payload only when armed.
    data = cfg.to_dict()
    data["config_files"] = provenance
    gateway = resolve_lobes_gateway_url(repo)
    if gateway is not None:
        lines.append(f"lobes: armed (gateway={gateway!r}) — resolved model={cfg.model}")
        data = {**data, "lobes": {"armed": True, "gateway": gateway, "resolved_model": cfg.model}}
    # Model-bound agents (#411 t7): reflect the mode so an operator can see it
    # before a run; the payload carries the key only when armed (to_dict()'s
    # omit-when-unarmed convention).
    lines.append(f"agents: {'armed' if getattr(cfg, 'agents', False) else 'off'}")
    return rendered(data, "\n".join(lines))


def _config_overview() -> object:
    sections = _config_sections()
    return rendered(
        {"subject": "colleague config", "sections": sections},
        render_text("colleague config", sections),
    )


def register_into(app) -> None:
    """Register the provider-config inspection verbs on the agentfront App registry."""
    g = app.group("config")
    g.tool(
        _config_show,
        name="show",
        description="Show the resolved provider configuration.",
        doc="# config show [--repo PATH]\nShow the resolved provider config "
        "(base_url, model, knobs), reflecting .colleague/config.json when --repo "
        "is given. The api_key is always redacted.",
    )
    g.tool(
        _config_overview,
        name="overview",
        description="Describe the config surface.",
        doc="# config overview\nDescribe the provider-config surface: what it "
        "shows, the resolution precedence, and the verbs.",
    )


def cmd_config_show(args: argparse.Namespace) -> int:
    emit_result(
        _config_show(getattr(args, "repo", ".")), json_mode=bool(getattr(args, "json", False))
    )
    return 0


def cmd_config_overview(args: argparse.Namespace) -> int:
    emit_result(_config_overview(), json_mode=bool(getattr(args, "json", False)))
    return 0


def _no_verb(args: argparse.Namespace) -> int:
    return cmd_config_overview(args)


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "config",
        help="Inspect the resolved provider configuration (see 'colleague config overview').",
    )
    p.add_argument("--json", action="store_true", help=JSON_HELP)
    p.set_defaults(func=_no_verb, json=False)
    noun_sub = p.add_subparsers(dest="config_command", parser_class=type(p))

    sh = noun_sub.add_parser("show", help="Show the resolved provider configuration.")
    sh.add_argument(
        "--repo",
        default=".",
        help="Repository path (default: cwd).",
    )
    sh.add_argument("--json", action="store_true", help=JSON_HELP)
    sh.set_defaults(func=cmd_config_show)

    ov = noun_sub.add_parser("overview", help="Describe the config surface.")
    ov.add_argument("--json", action="store_true", help=JSON_HELP)
    ov.set_defaults(func=cmd_config_overview)
