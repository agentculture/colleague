"""t2: the agentfront-rendered CLI assembly + the CliError↔AgentfrontError bridge.

These guard the keystone of the "CLI rendered from imported agentfront" migration:
``build_app()`` assembles colleague's App by auto-discovering ``register_into``
hooks, a colleague ``CliError`` raised by a handler is rendered natively by
agentfront's ``run_cli`` dispatch (structured ``{code,message,remediation}`` on
stderr, clean stdout, non-zero exit), and the bare-invocation no-command handler
routes (session at a TTY, help otherwise).
"""

from __future__ import annotations

import json

import colleague.cli as cli_pkg
from colleague.cli._app import _no_command, build_app, run
from colleague.cli._errors import EXIT_ENV_ERROR, CliError


def test_build_app_returns_named_app():
    app = build_app()
    # Duck-typed agentfront App: registry-backed surfaces + the host hooks.
    assert app.name == "colleague"
    assert hasattr(app, "list_tools") and hasattr(app, "add_command")
    assert app.no_command_handler is not None


def test_clierror_is_rendered_by_run_cli(capsys):
    """A handler raising colleague's CliError → agentfront renders it natively.

    This is the bridge: CliError subclasses AgentfrontError, so agentfront's
    run_cli dispatch catches it and emits {code,message,remediation} — no
    per-handler conversion, no traceback.
    """
    from agentfront.app import App

    app = App(name="t", version="0")

    @app.tool(name="boom")
    def boom():
        raise CliError(code=EXIT_ENV_ERROR, message="kaboom", remediation="fix it")

    from agentfront.cli_surface import run_cli

    code = run_cli(app, ["boom"])
    out = capsys.readouterr()
    assert code == EXIT_ENV_ERROR  # the CliError's own code, not a generic wrap
    assert out.out.strip() == ""  # stdout stays clean on failure
    assert "error: kaboom" in out.err
    assert "hint: fix it" in out.err
    assert "Traceback" not in out.err


def test_clierror_rendered_as_json(capsys):
    from agentfront.app import App
    from agentfront.cli_surface import run_cli

    app = App(name="t", version="0")

    @app.tool(name="boom")
    def boom():
        raise CliError(code=EXIT_ENV_ERROR, message="kaboom", remediation="fix it")

    code = run_cli(app, ["boom", "--json"])
    out = capsys.readouterr()
    assert code == EXIT_ENV_ERROR
    payload = json.loads(out.err)
    assert payload == {"code": EXIT_ENV_ERROR, "message": "kaboom", "remediation": "fix it"}
    assert out.out.strip() == ""


def test_no_command_prints_help_when_not_interactive(capsys, monkeypatch):
    monkeypatch.setattr(cli_pkg, "_stdio_is_interactive", lambda: False)
    code = run([])
    out = capsys.readouterr()
    assert code == 0
    assert "colleague" in out.out  # the help surface, not a crash


def test_no_command_routes_to_session_at_a_tty(monkeypatch):
    """At a TTY with a registered session command, bare invocation routes to it."""
    from agentfront.app import App

    monkeypatch.setattr(cli_pkg, "_stdio_is_interactive", lambda: True)
    app = App(name="colleague", version="0")
    seen = {}

    def session_handler(args):
        seen["ran"] = True
        return 0

    app.add_command("session", session_handler, help="interactive palette")
    code = _no_command(app, object())
    assert code == 0
    assert seen.get("ran") is True


def test_no_command_falls_back_to_help_without_session(capsys, monkeypatch):
    """At a TTY but with no session command registered, fall back to help."""
    from agentfront.app import App

    monkeypatch.setattr(cli_pkg, "_stdio_is_interactive", lambda: True)
    app = App(name="colleague", version="0")
    code = _no_command(app, object())
    out = capsys.readouterr()
    assert code == 0
    assert "colleague" in out.out
