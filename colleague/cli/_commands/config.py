"""``colleague config`` — inspect the resolved engine/provider configuration.

``config show`` prints the resolved :class:`~colleague.config.EngineConfig`
(base_url, model, max_steps, temperature, timeout, context_budget_tokens) with
the api_key redacted. ``config overview`` describes the noun.

Precedence (highest first): explicit flag > COLLEAGUE_*/OPENAI_* env >
.colleague/config.json > built-in default.

``temperature`` is a flat scalar being superseded by the per-half sampling
table in ``colleague.sampling`` / the tracked ``.colleague/models.json``
(reasoning-aware-sampling arc, #479 t7): ``CONVERTIBLE_TEMPERATURE`` is
removed (warns if set), ``COLLEAGUE_TEMPERATURE`` is deprecated for one
release (still applies, warns naming ``.colleague/models.json``). Beside the
effort lines, ``config show`` states the resolved SAMPLING match positively
— the row + model it matched, or an explicit no-row-matched line — never a
silent miss on a checkpoint colleague has no card for.
"""

from __future__ import annotations

import argparse
import os

from colleague import associate_cli, harness_cli
from colleague import sampling as _sampling
from colleague import samplingwire as _samplingwire
from colleague.cli._commands import _effort_groups
from colleague.cli._commands._listing import append_not_consumed
from colleague.cli._commands.overview import render_text
from colleague.cli._output import JSON_HELP, emit_result, rendered
from colleague.config import (
    EngineConfig,
    config_provenance,
    resolve_lobes_gateway_url,
)
from colleague.effort import DEFAULT_SENTINEL


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


#: The kill switch's env name (t5 owns the adapter-side consumption; this
#: reads the SAME variable read-only, so config show never lies about it
#: even though this task builds no other half of the switch). Mirrors the
#: exact ``== "0"`` convention ``colleague/web.py``'s ``COLLEAGUE_WEB``
#: kill switch already uses.
_SAMPLING_KILL_SWITCH_ENV = _samplingwire.SAMPLING_ENV_KEY


def _sampling_section(cfg: "EngineConfig") -> "tuple[list[str], dict[str, object]]":
    """Render the sampling-match section beside the effort lines (spec c45/h44).

    Positive statement, never a silent miss (acceptance 4/5, reasoning-aware-
    sampling arc plan task t7): names the row that matched and the model it
    matched for, or an explicit no-row-matched line — a misspelt/unmatched
    model id degrades to that explicit line rather than resolving quietly to
    a default. Uses ``colleague.sampling``'s BUILTIN table only (rows=None) —
    the tracked ``.colleague/models.json`` operator table is a separate
    resolution rung this task does not wire in.

    The acting seat mirrors :func:`colleague.effort.resolve_acting_effort`'s
    own seat rule (``"worker"`` when three-tier armed a worker, else
    ``"cortex"``) and reads the SAME resolved rung
    (``cfg.reasoning_effort_effective``) the vLLM adapter's ``_effort_for``
    sends on the wire, so this display can never claim a match the actual
    request would not also make.
    """
    seat = "worker" if getattr(cfg, "worker", None) is not None else "cortex"
    rung = cfg.reasoning_effort_effective
    half = _sampling.half_for_rung(rung)
    model_key = _sampling.normalize_model_id(cfg.model)
    # Resolve against the SAME merged table the adapter sends (Qodo #485
    # finding 9 / risk r7): builtin rows plus the operator's models.json,
    # operator last so an equal-specificity row wins, exactly as
    # vllm_payload._sampling_fragment layers them.
    _root = getattr(cfg, "memory_root", None) or os.getcwd()
    _rows = _sampling.BUILTIN_SAMPLING_ROWS + _samplingwire.operator_rows(_root)
    profile = _sampling.resolve_sampling(cfg.model, role=seat, rung=rung, rows=_rows)
    payload = _sampling.sampling_payload(profile)
    # What the ROW holds is the model card; what the WIRE carries is the row
    # minus every key already at the server's default (#479 c8, the filter in
    # colleague/samplingwire.py). Showing only the row would tell a reader
    # min_p/repetition_penalty go out when they do not — a silent
    # misstatement in the one command whose job is to state the match
    # honestly (acceptance 4/5).
    wire = _samplingwire.wire_fragment(profile)
    dropped = {k: v for k, v in payload.items() if k not in wire}

    data: dict[str, object] = {
        "seat": seat,
        "rung": rung,
        "half": half,
        "model": cfg.model,
        "normalized_model": model_key,
        "matched": profile is not None,
        "payload": payload,
        "wire": wire,
        "dropped_at_server_default": dropped,
    }
    if profile is not None:
        line = (
            f"sampling: matched {half} row for model {cfg.model!r} "
            f"(normalized {model_key!r}) -> on the wire {wire}"
        )
        if dropped:
            line += f"; dropped as already the server default {dropped}"
    elif half is None:
        line = (
            f"sampling: no row matched — rung {rung!r} (seat {seat!r}) selects "
            "no half, so no sampling keys are sent"
        )
    else:
        line = (
            f"sampling: no row matched for model {cfg.model!r} "
            f"(normalized {model_key!r}, half={half!r}) — no sampling keys are sent"
        )
    lines = [line]

    # COLLEAGUE_SAMPLING (c53/h40): a per-process boolean kill switch, not a
    # value, so it never joins the scalar lane above — but a run with it
    # ARMED sends no sampling keys regardless of the match this section just
    # reported, and config show must never leave that unstated (read-only:
    # the adapter that actually consumes it is a sibling task's file, never
    # imported here).
    kill_switch_raw = os.environ.get(_SAMPLING_KILL_SWITCH_ENV)
    # Ask the SAME predicate the adapter asks (#479 d6): matching only the
    # literal "0" here reported a match while COLLEAGUE_SAMPLING=off sent
    # nothing.
    kill_switch_armed = not _samplingwire.sampling_enabled()
    data["kill_switch_armed"] = kill_switch_armed
    if kill_switch_armed:
        lines.append(
            f"sampling: {_SAMPLING_KILL_SWITCH_ENV}={kill_switch_raw} "
            f"(kill switch armed) — no "
            "sampling keys are sent regardless of the match above"
        )
    return lines, data


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
    # Thinking-effort ladder (#416 t2, t10): 3 groups via the shared renderer.
    kill_switch = cfg.reasoning_effort == DEFAULT_SENTINEL
    lines.append("reasoning_effort:" + (" (kill-switch)" if kill_switch else ""))
    lines.extend(_effort_groups.render_lines(cfg))
    # Reasoning-aware sampling defaults (#479 t7, c45/h44): the sampling
    # match, positively stated, right beside the effort lines it derives its
    # half from.
    sampling_lines, sampling_data = _sampling_section(cfg)
    lines.extend(sampling_lines)
    provenance = config_provenance(repo)
    if provenance:
        for entry in provenance:
            keys = ", ".join(entry["keys"])
            wins = ", ".join(entry["winning_keys"])
            lines.append(f"config_file: {entry['path']} sets [{keys}] (wins: {wins})")
    else:
        lines.append("config_file: (none — using env vars + built-in defaults)")

    # Lobes rung (t4): ARMED state; to_dict() byte-identical, lobes key only when armed.
    data = cfg.to_dict()
    data["config_files"] = provenance
    # t10: the 3 resolved effort groups (additive key; what is actually sent).
    data["reasoning_effort_resolved"] = _effort_groups.resolved_groups(cfg)
    # #479 t7: the sampling match, positively stated (c45/h44) — the same
    # dict backing the ``sampling:`` lines above, so JSON and text can never
    # diverge on whether a row matched.
    data["sampling"] = sampling_data
    data.update(harness_cli.config_show_lines(lines, cfg))  # t20/c43: clamp + window
    gateway = resolve_lobes_gateway_url(repo)
    if gateway is not None:
        lines.append(f"lobes: armed (gateway={gateway!r}) — resolved model={cfg.model}")
        data = {**data, "lobes": {"armed": True, "gateway": gateway, "resolved_model": cfg.model}}
        # qwen-direct (c7/h7): advertised-but-not-consumed roles (senses/muse opt-in).
        data["lobes"]["not_consumed"] = append_not_consumed(lines, gateway, cfg, indent="")
        data["lobes"].update(associate_cli.config_show_lines(lines, cfg))  # t18/c49
    else:  # Qodo #441-8: an explicit-model associate needs no gateway to show
        data.update(associate_cli.config_show_lines(lines, cfg))
    # Model-bound agents (#411 t7): show the mode; payload key only when armed.
    lines.append(f"agents: {'armed' if getattr(cfg, 'agents', False) else 'off'}")
    # hire_colleague + the acting add-set (delegation-follow-ups t4): both
    # knobs always shown (value or unset) so a byte-identical claim is
    # attestable from config show, not from the launching shell.
    hire_armed = bool(getattr(cfg, "hire", False))
    lines.append(f"hire: {'armed' if hire_armed else 'off'}")
    data["hire"] = hire_armed
    add_tools = tuple(getattr(cfg, "acting_add_tools", ()) or ())
    lines.append(f"acting_add_tools: {','.join(add_tools) if add_tools else 'unset'}")
    data["acting_add_tools"] = list(add_tools)
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
