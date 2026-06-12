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
    from colleague.cli._commands import hooks as _hooks_group
    from colleague.cli._commands import learn as _learn_cmd
    from colleague.cli._commands import learn_from as _learn_from_cmd
    from colleague.cli._commands import overview as _overview_cmd
    from colleague.cli._commands import promote as _promote_cmd
    from colleague.cli._commands import session as _session_cmd
    from colleague.cli._commands import skills as _skills_group
    from colleague.cli._commands import telemetry as _telemetry_group
    from colleague.cli._commands import tui as _tui_cmd
    from colleague.cli._commands import whoami as _whoami_cmd
    from colleague.cli._commands import work as _work_cmd

    parser = _CliArgumentParser(
        prog="colleague",
        description="colleague — a swappable coder-agent harness. One runtime, many minds.",
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
    # Mesh-member promotion: born -> trained -> resident Culture member ([culture] extra).
    _promote_cmd.register(sub)
    _backends_group.register(sub)  # registers `backends` (+ the deprecated `wheels` alias)
    # ROI loop: grade a work item after the fact (stats say cost; feedback says quality).
    _feedback_group.register(sub)
    # Extensibility layer: command templates + lifecycle hooks.
    _commands_group.register(sub)
    _hooks_group.register(sub)
    # Layered per-model config: AGENTS instructions + skills.
    _agents_group.register(sub)
    _skills_group.register(sub)
    # Telemetry: OpenTelemetry traces + metrics (opt-in, optional [otel] extra).
    _telemetry_group.register(sub)
    # Provider config: resolved engine/provider settings (api_key redacted).
    _config_group.register(sub)
    # Interactive foreground palette (c28/R8).
    _session_cmd.register(sub)
    # Headless TUI inspection + JSON scenario runner (TAUI).
    _tui_cmd.register(sub)

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
    except Exception as err:  # noqa: BLE001 - last-resort; wrap and route cleanly
        wrapped = CliError(
            code=EXIT_USER_ERROR,
            message=f"unexpected: {err.__class__.__name__}: {err}",
            remediation=f"file a bug at {_ISSUES_URL}",
        )
        emit_error(wrapped, json_mode=json_mode)
        return wrapped.code
    return rc if rc is not None else 0


def main(argv: list[str] | None = None) -> int:
    # Pre-parse peek so argparse-level errors honour --json.
    _CliArgumentParser._json_hint = _argv_has_json(argv)
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        # Bare `colleague` opens the interactive harness at a terminal; piped /
        # redirected / non-interactive it prints usage so scripts and agents keep
        # a discoverable surface. `-h/--help` is handled by argparse before here,
        # so the help surface (and the teken rubric, which probes --help) stay
        # available either way. Re-parsing ["session"] reuses the session
        # subparser's defaults and func wiring — no parallel code path.
        if _stdio_is_interactive():
            return _dispatch(parser.parse_args(["session"]))
        parser.print_help()
        return 0

    return _dispatch(args)


if __name__ == "__main__":
    sys.exit(main())
