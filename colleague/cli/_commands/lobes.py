"""``colleague lobes`` — inspect the lobes gateway (cortex/senses arc, task t10;
re-synced to lobes-cli 0.38.0's ready semantics by colleague#292/291 S1).

``lobes show`` reports the ARMED state of colleague's connection to a lobes
gateway (``colleague/lobes.py``'s :func:`~colleague.lobes.resolve_roles`), the
resolved ``cortex``/``senses`` (and, when the gateway serves them, ``stt``/
``tts``/``muse``) role metadata when reachable (model, context, endpoint,
ready, responsibilities), and the degradation rung actually in effect:
``not_configured`` (unarmed), ``armed_reachable``, or ``armed_unreachable``.
Each role's ``ready`` is labeled with its ``ready_kind`` (``colleague/lobes.py``'s
:func:`~colleague.lobes.ready_kind`) — ``"config-proxy"`` for cortex/senses/muse
(gateway-local bookkeeping, not a liveness probe; ``ready`` and ``loaded`` may
diverge for proxied roles; see lobes-cli issue 146) vs ``"live-probed"`` for
stt/tts (lobes-cli#89, 0.38.0: the gateway's realtime bridge health-checks the
audio backend itself) — so an operator never conflates the two. ``muse`` is
shown as a plain resolved role only (two-machines-two-minds arc, task t4);
nothing here consumes it yet. ``lobes overview`` describes the noun
(satisfying the agent-first rubric: any noun with action-verbs must also
expose ``overview``).

**Armed-signal precedence:** ``lobes show`` uses the same resolution as the
runtime: ``COLLEAGUE_LOBES_URL`` env (``CONVERTIBLE_LOBES_URL`` honored as
deprecated fallback) > a ``lobes`` section in ``.colleague/config.json`` (repo-level
or user-level) > ``None``. Scope of ``--repo`` (default: ``.``) reflects the
repo-level ``.colleague/config.json`` override.
"""

from __future__ import annotations

import argparse

from colleague.cli._commands._listing import append_not_consumed
from colleague.cli._commands.overview import render_text
from colleague.cli._output import JSON_HELP, emit_result, rendered
from colleague.config import resolve_lobes_gateway_url
from colleague.lobes import RoleInfo, ready_kind, resolve_roles

#: The sole armed signal this noun consults (see the scope note above).
_GATEWAY_URL_ENV = "COLLEAGUE_LOBES_URL"

#: The three degradation rungs this noun can report.
_RUNG_NOT_CONFIGURED = "not_configured"
_RUNG_ARMED_REACHABLE = "armed_reachable"
_RUNG_ARMED_UNREACHABLE = "armed_unreachable"


def _lobes_sections() -> list[dict[str, object]]:
    return [
        {
            "title": "What it does",
            "items": [
                "Shows whether colleague is armed at a lobes gateway",
                "When reachable: the resolved cortex + senses role metadata",
                "The degradation rung in effect: not_configured / armed_reachable /"
                " armed_unreachable",
                "Read-only, zero side effects — one GET to the gateway's /capabilities",
            ],
        },
        {
            "title": "Armed-signal precedence",
            "items": [
                "COLLEAGUE_LOBES_URL env (CONVERTIBLE_LOBES_URL deprecated fallback)",
                ".colleague/config.json lobes section (repo-level or user-level)",
                "not configured (unarmed)",
            ],
        },
        {
            "title": "Roles",
            "items": [
                "cortex — the fast, wide-window reasoning mind that drives the tool loop",
                "senses — the tools-off multimodal front door (intake/normalize/speak-back)",
                "muse — a second machine's reasoning model, proxied through the gateway"
                " (shown when advertised; not consumed elsewhere yet)",
                "stt/tts — optional voice-arc roles, shown when the gateway serves them",
                "The gateway may also serve embedder/reranker; this noun does not list"
                " them (embedder is relayed elsewhere, never shown here; reranker is"
                " ignored entirely)",
            ],
        },
        {
            "title": "Verbs",
            "items": [
                "lobes show [--repo PATH] [--json] — show the armed state and roles",
                "lobes overview — describe the lobes surface (this command)",
            ],
        },
    ]


def _role_info_to_dict(name: str, info: RoleInfo) -> dict[str, object]:
    return {
        "model": info.model,
        "endpoint": info.endpoint,
        "path": info.path,
        "context": info.context,
        "ready": info.ready,
        "ready_kind": ready_kind(name),
        "responsibilities": list(info.responsibilities),
        "forbidden_responsibilities": list(info.forbidden_responsibilities),
    }


def _role_lines(name: str, info: RoleInfo) -> list[str]:
    ready = "ready" if info.ready else "not ready"
    kind = ready_kind(name)
    lines = [
        "",
        f"{name}\t{info.model}\t[{ready} ({kind})]",
        f"  context:  {info.context}",
        f"  endpoint: {info.endpoint}{info.path}",
        f"  responsibilities: {', '.join(info.responsibilities) or '(none)'}",
    ]
    if info.forbidden_responsibilities:
        lines.append(f"  forbidden: {', '.join(info.forbidden_responsibilities)}")
    return lines


# --- registry tool functions (rendered) + thin legacy adapters --------------


def _lobes_overview() -> object:
    sections = _lobes_sections()
    return rendered(
        {"subject": "colleague lobes", "sections": sections},
        render_text("colleague lobes", sections),
    )


def _lobes_show(repo: str = ".") -> object:
    """Registry tool: the lobes gateway armed state as ``rendered(dict, text)``.

    ``repo`` (default ``"."``) is derived by agentfront into ``--repo`` from this
    signature, matching the legacy ``lobes show --repo PATH``. Resolves the
    gateway URL using the full precedence chain: COLLEAGUE_LOBES_URL env >
    .colleague/config.json lobes section > None.

    Never raises: an unarmed or unreachable gateway is a clean, honest report
    (exit 0), not an error — mirroring :func:`colleague.lobes.resolve_roles`'s
    own degrade-never-raise contract.
    """
    url = (resolve_lobes_gateway_url(repo) or "").strip()

    if not url:
        payload = {
            "armed": False,
            "rung": _RUNG_NOT_CONFIGURED,
            "gateway_url": None,
            "roles": None,
        }
        text = (
            "lobes: not configured\n"
            f"  set {_GATEWAY_URL_ENV}=<gateway-url> to arm cortex/senses role resolution."
        )
        return rendered(payload, text)

    roles = resolve_roles(url)

    if roles is None:
        payload = {
            "armed": True,
            "rung": _RUNG_ARMED_UNREACHABLE,
            "gateway_url": url,
            "roles": None,
        }
        text = (
            f"lobes: armed at {url} — UNREACHABLE\n"
            "  gateway did not answer /capabilities (down, timed out, non-200, or"
            " malformed response); colleague degrades to its next configured rung."
        )
        return rendered(payload, text)

    payload = {
        "armed": True,
        "rung": _RUNG_ARMED_REACHABLE,
        "gateway_url": url,
        "roles": {
            "cortex": _role_info_to_dict("cortex", roles.cortex),
            "senses": _role_info_to_dict("senses", roles.senses),
        },
    }
    lines = [f"lobes: armed at {url} — reachable"]
    lines += _role_lines("cortex", roles.cortex)
    lines += _role_lines("senses", roles.senses)
    # stt/tts (voice arc) and muse (two-machines-two-minds t4) are OPTIONAL
    # roles — shown, ready-kind label and all, only when the gateway serves them.
    for opt_name, opt_role in (("stt", roles.stt), ("tts", roles.tts), ("muse", roles.muse)):
        if opt_role is not None:
            payload["roles"][opt_name] = _role_info_to_dict(opt_name, opt_role)
            lines += _role_lines(opt_name, opt_role)
    payload["not_consumed"] = append_not_consumed(lines, url, None, roles=roles, repo=repo)  # c7
    return rendered(payload, "\n".join(lines))


def register_into(app) -> None:
    """Register the lobes-gateway inspection verbs on the App registry."""
    g = app.group("lobes")
    g.tool(
        _lobes_show,
        name="show",
        description="Show the lobes gateway armed state, resolved roles, and rung.",
        doc="# lobes show [--repo PATH] [--json]\nShow whether colleague is armed at a "
        "lobes gateway (COLLEAGUE_LOBES_URL env or .colleague/config.json), the resolved "
        "cortex/senses role metadata when reachable, and the degradation rung in effect "
        "(not_configured / armed_reachable / armed_unreachable).",
    )
    g.tool(
        _lobes_overview,
        name="overview",
        description="Describe the lobes surface.",
        doc="# lobes overview\nDescribe the lobes-gateway introspection surface: "
        "what it shows, the cortex/senses roles, and the verbs.",
    )


def cmd_lobes_overview(args: argparse.Namespace) -> int:
    emit_result(_lobes_overview(), json_mode=bool(getattr(args, "json", False)))
    return 0


def cmd_lobes_show(args: argparse.Namespace) -> int:
    emit_result(
        _lobes_show(getattr(args, "repo", ".")), json_mode=bool(getattr(args, "json", False))
    )
    return 0


def _no_verb(args: argparse.Namespace) -> int:
    return cmd_lobes_overview(args)


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "lobes",
        help="Inspect the lobes gateway state (see 'colleague lobes overview').",
    )
    p.add_argument("--json", action="store_true", help=JSON_HELP)
    p.set_defaults(func=_no_verb, json=False)
    noun_sub = p.add_subparsers(dest="lobes_command", parser_class=type(p))

    show = noun_sub.add_parser(
        "show", help="Show the lobes gateway armed state, resolved roles, and rung."
    )
    show.add_argument(
        "--repo",
        default=".",
        help="Repository path (default: cwd).",
    )
    show.add_argument("--json", action="store_true", help=JSON_HELP)
    show.set_defaults(func=cmd_lobes_show)

    ov = noun_sub.add_parser("overview", help="Describe the lobes surface.")
    ov.add_argument("--json", action="store_true", help=JSON_HELP)
    ov.set_defaults(func=cmd_lobes_overview)
