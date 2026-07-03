"""``colleague lobes`` — inspect the lobes gateway (cortex/senses arc, task t10).

``lobes show`` reports the ARMED state of colleague's connection to a lobes
gateway (``colleague/lobes.py``'s :func:`~colleague.lobes.resolve_roles`), the
resolved ``cortex``/``senses`` role metadata when reachable (model, context,
endpoint, ready, responsibilities), and the degradation rung actually in
effect: ``not_configured`` (unarmed), ``armed_reachable``, or
``armed_unreachable``. ``lobes overview`` describes the noun (satisfying the
agent-first rubric: any noun with action-verbs must also expose ``overview``).

**Scope note (deliberately narrow):** this noun's armed signal is *only*
``COLLEAGUE_LOBES_URL`` env — task t10 depends solely on t1
(``colleague/lobes.py``'s resolution client), not on t4 (the lobes discovery
rung wired into ``EngineConfig``/``SensesConfig`` resolution, which composes a
fuller precedence chain: explicit flag > env > a ``lobes`` section in
``.colleague/config.json`` > builtin default). Reading that nested config
section here would either duplicate t4's future parsing or require editing
``colleague/config.py``, which this task is file-disjoint from in the same
build wave. Once t4 lands, this noun can be widened to reflect the same
precedence colleague's runtime actually resolves — until then it reports
exactly what it is told to consult: the env var.
"""

from __future__ import annotations

import argparse
import os

from colleague.cli._commands.overview import render_text
from colleague.cli._output import JSON_HELP, emit_result, rendered
from colleague.lobes import RoleInfo, resolve_roles

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
                "Shows whether colleague is armed at a lobes gateway (COLLEAGUE_LOBES_URL)",
                "When reachable: the resolved cortex + senses role metadata",
                "The degradation rung in effect: not_configured / armed_reachable /"
                " armed_unreachable",
                "Read-only, zero side effects — one GET to the gateway's /capabilities",
            ],
        },
        {
            "title": "Roles",
            "items": [
                "cortex — the fast, wide-window reasoning mind that drives the tool loop",
                "senses — the tools-off multimodal front door (intake/normalize/speak-back)",
                "The gateway may serve more roles (embedder, reranker, stt, tts); this"
                " noun reports only cortex + senses (colleague resolves nothing else)",
            ],
        },
        {
            "title": "Verbs",
            "items": [
                "lobes show [--json] — show the armed state, resolved roles, and rung",
                "lobes overview — describe the lobes surface (this command)",
            ],
        },
    ]


def _role_info_to_dict(info: RoleInfo) -> dict[str, object]:
    return {
        "model": info.model,
        "endpoint": info.endpoint,
        "path": info.path,
        "context": info.context,
        "ready": info.ready,
        "responsibilities": list(info.responsibilities),
        "forbidden_responsibilities": list(info.forbidden_responsibilities),
    }


def _role_lines(name: str, info: RoleInfo) -> list[str]:
    ready = "ready" if info.ready else "not ready"
    lines = [
        "",
        f"{name}\t{info.model}\t[{ready}]",
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


def _lobes_show() -> object:
    """Registry tool: the lobes gateway armed state as ``rendered(dict, text)``.

    Never raises: an unarmed or unreachable gateway is a clean, honest report
    (exit 0), not an error — mirroring :func:`colleague.lobes.resolve_roles`'s
    own degrade-never-raise contract.
    """
    url = (os.environ.get(_GATEWAY_URL_ENV) or "").strip()

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
            "cortex": _role_info_to_dict(roles.cortex),
            "senses": _role_info_to_dict(roles.senses),
        },
    }
    lines = [f"lobes: armed at {url} — reachable"]
    lines += _role_lines("cortex", roles.cortex)
    lines += _role_lines("senses", roles.senses)
    return rendered(payload, "\n".join(lines))


def register_into(app) -> None:
    """Register the lobes-gateway inspection verbs on the App registry."""
    g = app.group("lobes")
    g.tool(
        _lobes_show,
        name="show",
        description="Show the lobes gateway armed state, resolved roles, and rung.",
        doc="# lobes show [--json]\nShow whether colleague is armed at a lobes "
        "gateway (COLLEAGUE_LOBES_URL), the resolved cortex/senses role metadata "
        "when reachable, and the degradation rung in effect (not_configured / "
        "armed_reachable / armed_unreachable).",
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
    emit_result(_lobes_show(), json_mode=bool(getattr(args, "json", False)))
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
    show.add_argument("--json", action="store_true", help=JSON_HELP)
    show.set_defaults(func=cmd_lobes_show)

    ov = noun_sub.add_parser("overview", help="Describe the lobes surface.")
    ov.add_argument("--json", action="store_true", help=JSON_HELP)
    ov.set_defaults(func=cmd_lobes_overview)
