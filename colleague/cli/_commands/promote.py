"""``colleague promote`` — graduate colleague from a task runner into a Culture resident.

The lifecycle transition born → trained → **resident** (decision c15): the same
colleague that drives bounded work items is elevated *in place* into a persistent
mesh peer. The verb is the operator flow behind the ``/promote`` skill. It:

1. **Mints + self-registers** a stable mesh identity — writes ``culture.yaml``
   (``suffix`` + ``backend=colleague`` + ``model``) and a prompt file where the
   Culture steward discovers them, and signals arrival
   (:func:`colleague.resident.register.register_resident`, decision c20).
2. **Selects channels** — queries the Culture roster/steward, ranks candidates,
   and owns ``#<nick>`` by default
   (:func:`colleague.resident.channels.select_channels`, decision c19).
3. **Starts the resident** when ``--serve`` is passed — connects to IRC and runs
   the long-lived supervisor (the bounded loop as its driving engine) until
   interrupted. Without ``--serve`` it *prepares and reports* (idempotent), so
   the consequential network step is explicit.

The resident deps ship only in the opt-in ``[culture]`` extra; an install without
it fails cleanly with an install hint (never a traceback). This verb opens no
async machinery itself — the event loop lives under ``colleague/resident/`` (the
sanctioned async area) and is entered via the sync
:func:`colleague.resident.connection.serve_live`.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from colleague.cli._errors import EXIT_USER_ERROR, CliError
from colleague.cli._output import JSON_HELP, emit_diagnostic, emit_result
from colleague.config import EngineConfig, resolve_engine
from colleague.identity import resolve_identity


def cmd_promote(args: argparse.Namespace) -> int:
    json_mode = getattr(args, "json", False)
    repo = Path(args.repo).resolve()

    # Gate: the resident runtime ships only in the [culture] extra.
    from colleague.resident import CultureExtraMissing, require_culture_deps

    try:
        require_culture_deps()
    except CultureExtraMissing as exc:
        raise CliError(EXIT_USER_ERROR, str(exc))

    from colleague.resident.channels import select_channels
    from colleague.resident.identity_mint import ConflictError
    from colleague.resident.register import register_resident

    suffix = args.suffix or resolve_identity(repo) or "colleague"
    engine = resolve_engine(args.engine)
    config = EngineConfig.resolve(
        base_url=args.base_url,
        api_key=args.api_key,
        model=args.model,
        repo_path=repo,
    )
    model = config.model

    # Step 1 — mint identity + self-register (idempotent). A pre-existing,
    # differing culture.yaml (e.g. promoting inside an AgentCulture repo that
    # already declares an agent) is an expected, recoverable conflict — surface
    # it as an actionable CliError pointing at --force, never the top-level
    # "unexpected … file a bug" wrap.
    try:
        reg = register_resident(
            repo,
            suffix=suffix,
            model=model,
            steward_cli=args.roster_cli,
            signal=not args.no_signal,
            overwrite=args.force,
        )
    except ConflictError as exc:
        raise CliError(
            EXIT_USER_ERROR,
            str(exc),
            remediation=(
                "re-run with --force to overwrite the existing culture.yaml, or "
                "pass --suffix/--repo to mint under a different identity."
            ),
        )

    # Step 2 — channel selection (owns #<nick>, joins the agent-selected set).
    sel = select_channels(repo, roster_cli=args.roster_cli)

    report = {
        "identity": reg.nick,
        "engine": engine,
        "model": model,
        "owned_channel": sel.owned,
        "channels": sel.chosen,
        "registered": reg.signalled,
        "registration_note": reg.signal_output,
        "channels_degraded": sel.degraded,
        "culture_yaml": str(reg.culture_yaml_path),
        "prompt": str(reg.prompt_path),
        "served": False,
    }

    # Step 3 — go live (explicit; blocks until interrupted).
    if args.serve:
        from colleague.resident.connection import serve_live

        channels = [sel.owned, *[c for c in sel.chosen if c != sel.owned]]
        emit_diagnostic(
            f"colleague resident '{reg.nick}' connecting to "
            f"{args.irc_host}:{args.irc_port} (channels: {', '.join(channels)}) — Ctrl-C to stop"
        )
        serve_live(
            host=args.irc_host,
            port=args.irc_port,
            nick=reg.nick,
            channels=channels,
            repo_path=str(repo),
            config=config,
            engine_name=engine,
            agent_nick=reg.nick,
            default_target=sel.owned,
        )
        report["served"] = True
    else:
        emit_diagnostic(
            f"prepared resident '{reg.nick}' (owns {sel.owned}; "
            f"{len(sel.chosen)} channel(s)). Re-run with --serve to go live."
        )

    emit_result(report, json_mode=json_mode)
    return 0


_PROMOTE_HELP = (
    "Graduate colleague into a resident Culture member: mint identity, "
    "select channels, register, and (with --serve) go live "
    "(see 'colleague explain promote')."
)


def _configure_promote_parser(p: argparse.ArgumentParser) -> None:
    """Add ``promote``'s flags to an already-created parser.

    Shared by the legacy :func:`register` and the host-command ``configure`` hook.
    ``promote`` is a host command: it drives the resident's engine,
    can ``--serve`` a long-running IRC loop, and carries hyphenated flags
    (``--base-url`` / ``--roster-cli`` with choices / ``--no-signal`` / ``--irc-host``
    / ``--irc-port``) that don't map cleanly to signature-derived flags. ``func``
    is left for the caller / agentfront to set to :func:`cmd_promote`.
    """
    p.add_argument("--repo", default=".", help="Path to the repository (default: cwd).")
    p.add_argument(
        "--suffix",
        default=None,
        help="Mesh nick to mint (default: the resolved identity, else 'colleague').",
    )
    p.add_argument("--engine", default=None, help="Backend the resident's engine runs on.")
    p.add_argument("--model", default=None, help="Model override for the resident's engine.")
    p.add_argument("--base-url", default=None, help="OpenAI-compatible base URL override.")
    p.add_argument("--api-key", default=None, help="API key override.")
    p.add_argument(
        "--roster-cli",
        default="steward",
        choices=["steward", "culture"],
        help="Roster/registrar CLI to query + register through (default: steward).",
    )
    p.add_argument(
        "--no-signal",
        action="store_true",
        help="Mint + register files but do not signal arrival to the roster CLI.",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing differing culture.yaml when minting.",
    )
    p.add_argument(
        "--serve",
        action="store_true",
        help="Go live: connect to IRC and run the resident until interrupted.",
    )
    p.add_argument(
        "--irc-host", default="localhost", help="IRC host for --serve (default: localhost)."
    )
    p.add_argument(
        "--irc-port", type=int, default=6667, help="IRC port for --serve (default: 6667)."
    )
    p.add_argument("--json", action="store_true", help=JSON_HELP)


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("promote", help=_PROMOTE_HELP)
    _configure_promote_parser(p)
    p.set_defaults(func=cmd_promote)


def register_into(app) -> None:
    """Register ``promote`` as an agentfront host command.

    See :func:`_configure_promote_parser` for why it is a host command (engine-
    driving + ``--serve`` long-run + hyphenated flags). Reuses
    :func:`cmd_promote`'s ``(args) -> int`` handler verbatim.
    """
    app.add_command("promote", cmd_promote, help=_PROMOTE_HELP, configure=_configure_promote_parser)
