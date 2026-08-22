"""``colleague config`` — inspect the resolved engine/provider configuration.

``config show`` prints the resolved :class:`~colleague.config.EngineConfig`
(base_url, model, max_steps, temperature, timeout, context_budget_tokens) with
the api_key redacted. ``config overview`` describes the noun.

Precedence (highest first): explicit flag > COLLEAGUE_*/OPENAI_* env >
.colleague/config.json > built-in default.
"""

from __future__ import annotations

import argparse

from colleague import effort
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
    # Per-seat thinking-effort ladder (#416 t2): one resolved line per seat.
    # "default" (the kill-switch sentinel) sends nothing to every seat, so
    # the winning layer is named there instead of a per-seat rung.
    kill_switch = cfg.reasoning_effort == effort.DEFAULT_SENTINEL
    lines.append("reasoning_effort:" + (" (kill-switch)" if kill_switch else ""))
    for seat in effort.SEAT_TABLE:
        override = cfg.reasoning_effort_seats.get(seat) or (
            cfg.reasoning_effort if not kill_switch else None
        )
        value = effort.resolve_effort(kill_switch=kill_switch, seat_override=override, seat=seat)
        lines.append(f"  {seat}: {value}")
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
        # qwen-direct (c7/h7): name every advertised role colleague does NOT
        # consume by default — senses and muse are opt-in (the ``lobes``
        # sentinel or an explicit model id) — so the retirement is visible,
        # never inferred. Roles come from the same /capabilities payload the
        # resolve() rung read; an unreachable gateway yields no extra lines.
        not_consumed = _not_consumed_roles(gateway, cfg)
        for name, model, knob in not_consumed:
            lines.append(f"not consumed (opt-in): {name} → {model} — {knob}")
        data["lobes"]["not_consumed"] = [name for name, _m, _k in not_consumed]
    # Model-bound agents (#411 t7): reflect the mode so an operator can see it
    # before a run; the payload carries the key only when armed (to_dict()'s
    # omit-when-unarmed convention).
    lines.append(f"agents: {'armed' if getattr(cfg, 'agents', False) else 'off'}")
    return rendered(data, "\n".join(lines))


#: (role name, the config attribute that shows it was consumed, the opt-in knob).
_OPT_IN_ROLES = (
    ("senses", "senses", "COLLEAGUE_SENSES_MODEL=lobes"),
    ("muse", "deepthink", "COLLEAGUE_DEEPTHINK_MODEL=lobes"),
)


def not_consumed_roles_from(roles: object, cfg: object) -> list[tuple[str, str, str]]:
    """Pure: the advertised opt-in roles *cfg* did not consume (qwen-direct c7).

    *roles* is a :class:`colleague.lobes.LobesRoles` (or ``None``); each entry
    is ``(role, served model id, opt-in knob)`` for a role the gateway
    advertises whose consuming seat on *cfg* is ``None``. Shared by
    ``config show`` and ``lobes show`` so both print the same facts.
    """
    out: list[tuple[str, str, str]] = []
    if roles is None:
        return out
    for role_name, attr, knob in _OPT_IN_ROLES:
        info = getattr(roles, role_name, None)
        model = str(getattr(info, "model", "") or "")
        if info is None or not model:
            continue
        if getattr(cfg, attr, None) is None:
            out.append((role_name, model, knob))
    return out


def _not_consumed_roles(gateway: str, cfg: object) -> list[tuple[str, str, str]]:
    """Resolve the gateway roles (never raises; ``None`` on failure) and classify."""
    from colleague.lobes import resolve_roles  # lazy: keeps the CLI import graph thin

    return not_consumed_roles_from(resolve_roles(gateway), cfg)


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
