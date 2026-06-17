"""``colleague config`` — inspect the resolved engine/provider configuration.

``config show`` prints the resolved :class:`~colleague.config.EngineConfig`
(base_url, model, max_steps, temperature, timeout, context_budget_tokens) with
the api_key redacted. ``config overview`` describes the noun.

Precedence (highest first): explicit flag > COLLEAGUE_*/OPENAI_* env >
.colleague/config.json > built-in default.
"""

from __future__ import annotations

import argparse

from colleague.cli._commands.overview import emit_overview
from colleague.cli._output import JSON_HELP, emit_result
from colleague.config import EngineConfig, load_config_file


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
                "precedence: flag > COLLEAGUE_*/OPENAI_* env > .colleague/config.json > default",
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


def cmd_config_show(args: argparse.Namespace) -> int:
    repo = getattr(args, "repo", ".")
    json_mode = bool(getattr(args, "json", False))
    cfg = EngineConfig.resolve(repo_path=repo)

    if json_mode:
        emit_result(cfg.to_dict(), json_mode=True)
    else:
        lines = [
            f"base_url:               {cfg.base_url}",
            f"model:                  {cfg.model}",
            f"max_steps:              {cfg.max_steps}",
            f"temperature:            {cfg.temperature}",
            f"timeout:                {cfg.timeout}",
            f"context_budget_tokens:  {cfg.context_budget_tokens}",
        ]
        file_cfg = load_config_file(repo)
        if file_cfg:
            keys = ", ".join(sorted(file_cfg.keys()))
            lines.append(f"config_file: .colleague/config.json sets [{keys}]")
        else:
            lines.append("config_file: (none — using env vars + built-in defaults)")
        emit_result("\n".join(lines), json_mode=False)
    return 0


def cmd_config_overview(args: argparse.Namespace) -> int:
    emit_overview(
        "colleague config",
        _config_sections(),
        json_mode=bool(getattr(args, "json", False)),
    )
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
