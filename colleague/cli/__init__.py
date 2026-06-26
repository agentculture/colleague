"""Unified CLI entry point for colleague.

The agent-first global verbs (``whoami``, ``learn``, ``explain``, ``overview``,
``doctor``) are registered here under :mod:`colleague.cli._commands`,
alongside the ``cli`` noun group. Future noun groups register via their own
``register()`` functions following the same pattern.

Error propagation contract
--------------------------
Every handler raises :class:`colleague.cli._errors.CliError` on
failure; ``main()`` catches it via :func:`_dispatch` and routes through
:mod:`colleague.cli._output`. Unknown exceptions are wrapped into a
``CliError`` so no Python traceback leaks to stderr.

Argparse errors (unknown verb, missing arg) also route through the structured
format — ``_CliArgumentParser`` overrides ``.error()`` and the subparsers are
built with ``parser_class=_CliArgumentParser``. Whether errors render as text or
JSON depends on whether ``--json`` appears in the raw argv (:func:`main` sets
``_json_hint`` before ``parse_args``).
"""

from __future__ import annotations

import argparse
import sys

from colleague import __version__
from colleague.cli._errors import EXIT_USER_ERROR, CliError
from colleague.cli._output import emit_error

_ISSUES_URL = "https://github.com/agentculture/colleague/issues"

# Grouped, scannable cheatsheet appended below argparse's flat subcommand list so
# a first-time user has a "start here" path instead of an undifferentiated wall of
# ~26 verbs. Rendered verbatim (RawDescriptionHelpFormatter); the flat list above
# stays the authoritative, complete enumeration.
_HELP_EPILOG = """\
getting started:
  colleague quickstart       guided first-run walkthrough — start here
  colleague doctor           check your configuration is ready to run
  colleague whoami           identity + the live work engine and model

working:
  colleague work <goal>      delegate a scoped repo task to a backend
  colleague session          interactive foreground palette
  colleague plan <goal>      plan a complex task (spec -> plan -> workforce)
  colleague feedback ...     grade a finished work item (the ROI loop)

inspecting:
  colleague backends list    discovered model backends (the minds)
  colleague config show      resolved provider configuration
  colleague explain <topic>  markdown docs for any noun/verb

Tip: 'colleague <verb> --help' for a verb's flags, or 'colleague explain' for
the full command catalog.
"""


class _CliArgumentParser(argparse.ArgumentParser):
    """ArgumentParser that routes errors through :func:`emit_error`.

    Argparse's default error handler writes ``prog: error: <msg>`` to stderr
    and exits 2, skipping the CliError plumbing (and the ``hint:`` line agents
    look for). This subclass emits the structured format and exits with
    :attr:`EXIT_USER_ERROR`.

    JSON mode: parse-time errors happen before ``args.json`` exists, so we rely
    on a class-level ``_json_hint`` that :func:`main` pre-populates by scanning
    raw argv for ``--json``. Shared across all subparser instances.
    """

    _json_hint: bool = False

    def error(self, message: str) -> None:  # type: ignore[override]
        err = CliError(
            code=EXIT_USER_ERROR,
            message=message,
            remediation=f"run '{self.prog} --help' to see valid arguments",
        )
        emit_error(err, json_mode=type(self)._json_hint)
        raise SystemExit(err.code)


def _argv_has_json(argv: list[str] | None) -> bool:
    tokens = argv if argv is not None else sys.argv[1:]
    return any(t == "--json" or t.startswith("--json=") for t in tokens)


def _stdio_is_interactive() -> bool:
    """Whether stdin and stdout are both interactive terminals.

    Bare ``colleague`` opens the interactive harness only at a real terminal;
    isolated as a module function so tests can force the interactive branch
    without a TTY (mirrors :func:`colleague.cli._banner._isatty`). Both streams
    must be a TTY: the palette reads from stdin and renders its chrome to stdout.
    """
    return sys.stdin.isatty() and sys.stdout.isatty()


def _build_parser() -> argparse.ArgumentParser:
    from colleague.cli._commands import agents as _agents_group
    from colleague.cli._commands import backends as _backends_group
    from colleague.cli._commands import clean as _clean_cmd
    from colleague.cli._commands import cli as _cli_group
    from colleague.cli._commands import commands as _commands_group
    from colleague.cli._commands import config as _config_group
    from colleague.cli._commands import doctor as _doctor_cmd
    from colleague.cli._commands import explain as _explain_cmd
    from colleague.cli._commands import feedback as _feedback_group
    from colleague.cli._commands import flight as _flight_cmd
    from colleague.cli._commands import hooks as _hooks_group
    from colleague.cli._commands import learn as _learn_cmd
    from colleague.cli._commands import learn_from as _learn_from_cmd
    from colleague.cli._commands import mcp as _mcp_group
    from colleague.cli._commands import overview as _overview_cmd
    from colleague.cli._commands import plan as _plan_cmd
    from colleague.cli._commands import promote as _promote_cmd
    from colleague.cli._commands import quickstart as _quickstart_cmd
    from colleague.cli._commands import roles as _roles_group
    from colleague.cli._commands import session as _session_cmd
    from colleague.cli._commands import skills as _skills_group
    from colleague.cli._commands import telemetry as _telemetry_group
    from colleague.cli._commands import tui as _tui_cmd
    from colleague.cli._commands import whoami as _whoami_cmd
    from colleague.cli._commands import work as _work_cmd

    parser = _CliArgumentParser(
        prog="colleague",
        description="colleague — a swappable coder-agent harness. One runtime, many minds.",
        epilog=_HELP_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    # parser_class propagates to every subparser so their .error() routes
    # through _CliArgumentParser too.
    sub = parser.add_subparsers(dest="command", parser_class=_CliArgumentParser)

    _whoami_cmd.register(sub)
    # Guided first-run walkthrough for new users (the "where do I start?" path).
    _quickstart_cmd.register(sub)
    _learn_cmd.register(sub)
    # Learn skills from a peer agent (e.g. claude) into .colleague/skills/.
    _learn_from_cmd.register(sub)
    _explain_cmd.register(sub)
    _overview_cmd.register(sub)
    _doctor_cmd.register(sub)
    # Self-heal: reap stale/corrupt colleague/* branches + orphaned artifacts (#162).
    _clean_cmd.register(sub)
    _cli_group.register(sub)
    # Colleague's working surface: assign repo work + inspect backend plugins.
    _work_cmd.register(sub)
    # Plan mode: colleague plans a complex task (spec -> plan -> subagent workforce).
    _plan_cmd.register(sub)
    # Mesh-member promotion: born -> trained -> resident Culture member ([culture] extra).
    _promote_cmd.register(sub)
    _backends_group.register(sub)  # registers `backends` (+ the deprecated `wheels` alias)
    # ROI loop: grade a work item after the fact (stats say cost; feedback says quality).
    _feedback_group.register(sub)
    # Pilot a running work item: watch feed, redirect, or stop.
    _flight_cmd.register(sub)
    # Extensibility layer: command templates + lifecycle hooks.
    _commands_group.register(sub)
    _hooks_group.register(sub)
    # Layered per-model config: AGENTS instructions + skills.
    _agents_group.register(sub)
    _skills_group.register(sub)
    # Typed subagent roles: prompt + curated tools + skills per role (read-only roles).
    _roles_group.register(sub)
    # Telemetry: OpenTelemetry traces + metrics (opt-in, optional [otel] extra).
    _telemetry_group.register(sub)
    # Provider config: resolved engine/provider settings (api_key redacted).
    _config_group.register(sub)
    # Interactive foreground palette (c28/R8).
    _session_cmd.register(sub)
    # Headless TUI inspection + JSON scenario runner (TAUI).
    _tui_cmd.register(sub)
    # MCP server bonus: serve colleague's operations over stdio ([mcp] extra).
    _mcp_group.register(sub)

    return parser


def _dispatch(args: argparse.Namespace) -> int:
    """Invoke the registered handler and translate exceptions to exit codes.

    A handler may return ``None`` (success, exit 0) or an ``int`` exit code.
    Failures MUST raise :class:`CliError`; any other exception is wrapped into
    one so no Python traceback leaks.
    """
    json_mode = bool(getattr(args, "json", False))
    try:
        rc = args.func(args)
    except CliError as err:
        emit_error(err, json_mode=json_mode)
        return err.code
    except KeyboardInterrupt:
        # A Ctrl-C that wasn't converted to SystemExit by the isolated-work signal
        # handler (#222) — exit cleanly with the conventional 130, never a traceback.
        return 130
    except Exception as err:  # noqa: BLE001 - last-resort; wrap and route cleanly
        wrapped = CliError(
            code=EXIT_USER_ERROR,
            message=f"unexpected: {err.__class__.__name__}: {err}",
            remediation=f"file a bug at {_ISSUES_URL}",
        )
        emit_error(wrapped, json_mode=json_mode)
        return wrapped.code
    return rc if rc is not None else 0


# agentfront RESERVES these four meta-verbs (``App._RESERVED_META_VERBS``) and
# renders trivial, generic versions from the registry. colleague's own versions
# are materially richer — ``doctor`` is a real configuration-readiness health
# check, ``overview`` a descriptive agent snapshot, ``learn`` the curated
# self-teaching prompt, ``explain`` the per-verb markdown catalog (which also
# covers the host-command launchers agentfront's registry-driven ``explain``
# cannot) — so the live entry keeps them colleague-owned via the legacy parser.
_META_VERBS = frozenset({"doctor", "overview", "learn", "explain"})


def main(argv: list[str] | None = None) -> int:
    """colleague's CLI entry point — the imported-agentfront rendered surface.

    Every sub-command is dispatched from the agentfront :class:`App` assembled by
    :func:`colleague.cli._app.build_app` (the "CLI rendered from agentfront"
    migration), EXCEPT:

    * ``--version`` — agentfront's rendered parser carries no version action, so
      colleague owns it (matching argparse's print-and-exit-0).
    * ``--help`` / bare non-interactive — rendered through the legacy parser so
      the grouped ``getting started / working / inspecting`` epilog survives.
    * the four reserved meta-verbs (:data:`_META_VERBS`) — routed to colleague's
      richer handlers through the legacy parser (the rendered App never registers
      them, so agentfront's generic versions are simply never reached).

    The legacy argparse parser (:func:`_build_parser`) is no longer the live
    dispatch path; it survives as the backend for these carve-outs, the
    interactive session's in-process noun introspection, and the ``doctor``
    parser self-check. Fully retiring it is a documented follow-up.
    """
    from agentfront.cli_surface import run_cli

    from colleague.cli._app import build_app

    tokens = list(argv) if argv is not None else sys.argv[1:]

    # `--version` is colleague-owned (the rendered parser has no version action);
    # match argparse's behaviour — print and raise SystemExit(0).
    if tokens and tokens[0] in ("--version", "-V"):
        print(f"colleague {__version__}")
        raise SystemExit(0)

    # `--help` / `-h` through the legacy parser preserves the grouped epilog.
    if tokens and tokens[0] in ("--help", "-h"):
        _build_parser().print_help()
        return 0

    first = tokens[0] if tokens and not tokens[0].startswith("-") else None

    if first is None:
        # Bare `colleague`: open the interactive cockpit at a real terminal, else
        # print usage (with the epilog) so scripts/agents keep a discoverable menu.
        if _stdio_is_interactive():
            return run_cli(build_app(), ["session"])
        _build_parser().print_help()
        return 0

    if first in _META_VERBS:
        # Pre-parse peek so the legacy parser's argparse-level errors honour --json.
        _CliArgumentParser._json_hint = _argv_has_json(argv)
        return _dispatch(_build_parser().parse_args(tokens))

    return run_cli(build_app(), argv)


if __name__ == "__main__":
    sys.exit(main())
