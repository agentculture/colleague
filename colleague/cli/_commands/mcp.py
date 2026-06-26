"""``colleague mcp`` — serve colleague's operations as an MCP server (the bonus).

The same imported agentfront :class:`~agentfront.app.App` that renders the CLI
also exposes a **single-dispatch** MCP server: ONE ``run`` tool whose description
embeds the command catalog (the same registry operations the CLI verbs and
``learn`` enumerate). ``mcp serve`` runs it over stdio (blocking) so a platform
(e.g. Cowork) can drive colleague; ``mcp overview`` describes the surface.

This is the documented v1 MCP **server** bonus, distinct from the explicitly
out-of-scope MCP *client* (colleague reads no ``mcp.json`` and registers no
external MCP tools). No socket/daemon code lives here — the blocking stdio loop is
agentfront's :func:`agentfront.mcp_surface.serve_stdio`; colleague only assembles
the App and hands it over. ``mcp`` is therefore a **host command** (``serve``
blocks on a long-running server), registered alongside the other launchers.

Needs the optional ``[mcp]`` extra; absent it, ``mcp serve`` fails with a clean
:class:`~colleague.cli._errors.CliError` naming the install.
"""

from __future__ import annotations

import argparse

from colleague.cli._commands.overview import render_text
from colleague.cli._errors import EXIT_ENV_ERROR, CliError
from colleague.cli._output import JSON_HELP, emit_diagnostic, emit_result, rendered

_MCP_HELP = "Serve colleague's operations as an MCP server (see 'colleague mcp overview')."


def _mcp_sections() -> list[dict[str, object]]:
    return [
        {
            "title": "What it does",
            "items": [
                "Serves colleague's operations as a single-dispatch MCP server",
                "ONE 'run' tool whose description embeds the command catalog",
                "Same registry the CLI verbs + 'learn' enumerate (catalog-level parity)",
                "For a platform (e.g. Cowork) to drive colleague over MCP",
            ],
        },
        {
            "title": "Verbs",
            "items": [
                "mcp serve — serve over stdio (blocking; Ctrl-C to stop)",
                "mcp overview — describe the MCP surface (this command)",
            ],
        },
        {
            "title": "Requirements",
            "items": [
                "Needs the optional [mcp] extra: pip install 'colleague[mcp]'",
                "No socket/daemon code in colleague — the stdio loop is agentfront's",
                "This is the MCP server bonus, not an MCP client (no mcp.json is read)",
            ],
        },
    ]


def _mcp_overview() -> object:
    sections = _mcp_sections()
    return rendered(
        {"subject": "colleague mcp", "sections": sections},
        render_text("colleague mcp", sections),
    )


def cmd_mcp_overview(args: argparse.Namespace) -> int:
    emit_result(_mcp_overview(), json_mode=bool(getattr(args, "json", False)))
    return 0


def cmd_mcp_serve(args: argparse.Namespace) -> int:
    """Serve colleague's operations over stdio (blocking) via agentfront."""
    from colleague.cli._app import build_app

    app = build_app()
    # Validate the optional [mcp] extra up front so a missing install fails with a
    # clean, actionable CliError rather than a traceback from deep in the stdio loop.
    try:
        app.mcp_server()
    except ModuleNotFoundError as exc:
        raise CliError(
            EXIT_ENV_ERROR,
            str(exc),
            "install the optional extra: pip install 'colleague[mcp]' " "(or: uv sync --extra mcp)",
        ) from exc

    emit_diagnostic(
        "colleague MCP: serving over stdio — a single 'run' dispatch tool " "(Ctrl-C to stop)."
    )
    # The blocking stdio loop lives in agentfront (no socket/daemon code in
    # colleague); colleague only assembles the App and hands it over.
    from agentfront.mcp_surface import serve_stdio

    serve_stdio(app)
    return 0


def _no_verb(args: argparse.Namespace) -> int:
    return cmd_mcp_overview(args)


def _configure_mcp_parser(p: argparse.ArgumentParser) -> None:
    """Add ``mcp``'s ``--json`` + serve/overview sub-verbs to an already-created parser.

    Shared by the legacy :func:`register` and the host-command ``configure`` hook.
    ``mcp`` is a host command (``mcp serve`` blocks on a long-running server, and a
    noun is either a tool-group or a host command, never both). ``func`` on *p* is
    left for the caller / agentfront to set to :func:`_no_verb` (bare ``mcp`` →
    overview); each sub-verb sets its own ``func``.
    """
    p.add_argument("--json", action="store_true", help=JSON_HELP)
    p.set_defaults(json=False)
    noun_sub = p.add_subparsers(dest="mcp_command", parser_class=type(p))

    sv = noun_sub.add_parser(
        "serve", help="Serve colleague's operations as an MCP server over stdio (blocking)."
    )
    sv.set_defaults(func=cmd_mcp_serve)

    ov = noun_sub.add_parser("overview", help="Describe the MCP surface.")
    ov.add_argument("--json", action="store_true", help=JSON_HELP)
    ov.set_defaults(func=cmd_mcp_overview)


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("mcp", help=_MCP_HELP)
    _configure_mcp_parser(p)
    p.set_defaults(func=_no_verb)


def register_into(app) -> None:
    """Register the ``mcp`` noun-group as an agentfront host command.

    ``mcp serve`` blocks on a long-running stdio server (and the one-noun-one-door
    rule applies), so the whole group is a host command, reusing the existing
    ``cmd_mcp_*`` handlers verbatim; bare ``mcp`` falls through to overview.
    """
    app.add_command("mcp", _no_verb, help=_MCP_HELP, configure=_configure_mcp_parser)
