"""Assemble colleague's agent-first CLI from one imported agentfront ``App``.

Colleague's CLI is *rendered* from an agentfront App registry rather than
hand-maintained argparse scaffolding (the "import, don't duplicate" migration).
Every verb module under :mod:`colleague.cli._commands` exposes a
``register_into(app)`` hook; :func:`build_app` **auto-discovers** them (so no
per-verb edit to this file is ever needed — the file-disjoint verb fan-out can
never collide here) and returns the assembled App. The same App backs the
MCP server (``app.mcp_server()``) and HTTP (``app.http_app()``) surfaces for
free.

:func:`run` dispatches an argv against the assembled App via agentfront's
``run_cli`` — agent-first error handling (``AgentfrontError`` /
:class:`~colleague.cli._errors.CliError` → structured ``{code, message,
remediation}`` on stderr, ``KeyboardInterrupt`` → 130, no traceback leak), a
no-command handler for the bare ``colleague`` invocation, and per-verb ``--json``
all come from agentfront, not from colleague scaffolding.

During the migration this is the *new* rendered path; the live entry point in
:mod:`colleague.cli` is flipped to it once every verb is registry-backed (so the
test suite stays green through the per-verb fan-out).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from colleague import __version__

if TYPE_CHECKING:  # pragma: no cover - typing only
    from agentfront.app import App

_DESCRIPTION = "colleague — a swappable coder-agent harness. One runtime, many minds."


def _iter_command_modules():
    """Yield each verb module under :mod:`colleague.cli._commands`, in CLI order.

    The list is **explicit** (no dynamic ``import_module`` — the boundary guard
    forbids it, since command/hook *templates* are read as text, never imported
    as Python) and written once here. The per-verb migration only ADDS a
    ``register_into(app)`` hook to each module's own file — never edits this
    list — so the file-disjoint verb fan-out can't collide on this module.
    """
    from colleague.cli._commands import (
        agents,
        backends,
        clean,
        cli,
        commands,
        config,
        doctor,
        explain,
        feedback,
        flight,
        hooks,
        learn,
        learn_from,
        livecheck,
        lobes,
        mcp,
        overview,
        plan,
        promote,
        quickstart,
        roles,
        session,
        skills,
        talk,
        telemetry,
        tui,
        whoami,
        work,
    )

    # CLI display order mirrors the pre-migration _build_parser order so the
    # rendered help/overview surface stays stable (behavior-compat).
    return (
        whoami,
        quickstart,
        learn,
        learn_from,
        explain,
        overview,
        doctor,
        clean,
        livecheck,
        cli,
        work,
        plan,
        promote,
        backends,
        feedback,
        flight,
        talk,
        commands,
        hooks,
        agents,
        skills,
        roles,
        telemetry,
        lobes,
        config,
        session,
        tui,
        mcp,
    )


def build_app() -> "App":
    """Build the colleague :class:`agentfront.app.App` from the registry.

    Auto-discovers every ``register_into(app)`` hook under
    :mod:`colleague.cli._commands`, then wires the bare-invocation no-command
    handler. Idempotent and side-effect-free beyond constructing the App.
    """
    from agentfront.app import App

    app = App(name="colleague", version=__version__, description=_DESCRIPTION)
    for mod in _iter_command_modules():
        register_into = getattr(mod, "register_into", None)
        if register_into is not None:
            register_into(app)
    # agentfront invokes the no-command handler as ``handler(args)``; ``_no_command``
    # doesn't need the parsed namespace (it only consults the App + TTY state), so the
    # lambda accepts and discards it (``_args``).
    app.set_no_command_handler(lambda _args: _no_command(app))
    return app


def _no_command(app: "App") -> int:
    """Handle a bare ``colleague`` invocation (no sub-command).

    At an interactive terminal, open the interactive session palette (matching
    the pre-migration behaviour); piped / redirected / non-interactive, print
    the help surface so scripts and agents keep a discoverable menu. Routing to
    ``session`` goes through the registry (``run_cli(app, ["session"])``) so the
    session command's own defaults/flags apply — no parallel code path. Falls
    back to help when ``session`` is not (yet) registered.
    """
    from colleague.cli import _stdio_is_interactive

    if _stdio_is_interactive() and app.get_command("session") is not None:
        from agentfront.cli_surface import run_cli

        return run_cli(app, ["session"])

    from agentfront.cli_surface import make_cli

    make_cli(app).print_help()
    return 0


def run(argv: list[str] | None = None) -> int:
    """Dispatch *argv* against the assembled colleague App via agentfront."""
    from agentfront.cli_surface import run_cli

    return run_cli(build_app(), argv)
