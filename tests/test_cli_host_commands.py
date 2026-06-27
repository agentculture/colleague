"""t4/t5: the launcher verbs registered as agentfront *host commands*.

``work`` / ``drive`` / ``plan`` / ``session`` / ``tui`` are NOT rendered registry
tools — each owns CLI-specific semantics the agentfront tool dispatch (return →
``emit_result``, exit always 0; raise → structured error) cannot express:

* ``work`` exits ``2`` on ``INCOMPLETE`` (#192) with the result on stdout, ``1``
  on a soft error;
* ``plan run`` exits non-zero when the spec does not converge, result on stdout;
* ``tui test`` exits ``1`` on a scenario FAIL;
* ``session`` is an interactive raw-mode cockpit.

So they are host commands (``app.add_command``), reusing their existing
``cmd_*(args) -> int`` handlers verbatim. This exercises them through agentfront's
``run_cli`` (the rendered path) to pin: registration as host commands (NOT tools,
so they stay out of the MCP/learn catalog by design), the ``drive`` alias, and —
the load-bearing part — exit-code passthrough with clean stdout on failure.
"""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout

from agentfront.cli_surface import make_cli, run_cli

from colleague.cli._app import build_app

_LAUNCHERS = ("work", "plan", "session", "tui")


def _run(argv):
    out, err = io.StringIO(), io.StringIO()
    code = None
    try:
        with redirect_stdout(out), redirect_stderr(err):
            code = run_cli(build_app(), argv)
    except SystemExit as exc:  # KeyboardInterrupt path raises SystemExit
        code = exc.code
    return code, out.getvalue(), err.getvalue()


def test_launchers_are_host_commands_not_tools():
    """The launcher verbs register as host commands and stay OUT of the tool catalog."""
    app = build_app()
    for name in _LAUNCHERS:
        assert app.get_command(name) is not None, f"{name} should be a host command"
    tool_paths = {tuple(t.group) + (t.name,) for t in app.list_tools()}
    top_level = {p[0] for p in tool_paths}
    for name in _LAUNCHERS:
        assert name not in top_level, f"{name} must not also be a registry tool"


def test_work_no_instruction_exits_user_error_clean_stdout(tmp_path):
    """work with neither an instruction nor --command → exit 1, structured error,
    clean stdout (the CliError → AgentfrontError bridge renders it, no traceback)."""
    code, out, err = _run(["work", "--repo", str(tmp_path)])
    assert code == 1  # EXIT_USER_ERROR, surfaced via the AgentfrontError dispatch
    assert out.strip() == ""  # the result stream stays clean on failure
    assert "error:" in err and "Traceback" not in err


def test_drive_alias_dispatches_to_work(tmp_path):
    """The deprecated ``drive`` alias rides the same host command → same behaviour."""
    code, out, err = _run(["drive", "--repo", str(tmp_path)])
    assert code == 1 and out.strip() == "" and "error:" in err


def test_plan_status_no_checkpoint_exits_zero(tmp_path):
    """plan status with no checkpoint is a clean state (exit 0, result on stdout)."""
    code, out, _ = _run(["plan", "status", "--repo", str(tmp_path)])
    assert code == 0
    assert "no plan checkpoint" in out


def test_tui_overview_and_bare_tui_exit_zero():
    """tui overview prints the surface; bare ``tui`` falls through to overview."""
    code, out, _ = _run(["tui", "overview"])
    assert code == 0 and "tui" in out.lower()

    code, out, _ = _run(["tui"])
    assert code == 0


def test_session_host_command_flag_surface():
    """session registers with its full flag surface + the long --help description
    (set on the parser so the host-command door, which only takes help=, keeps it)."""
    app = build_app()
    cmd = app.get_command("session")
    assert cmd is not None and cmd.configure is not None

    parser = make_cli(app)
    # The session subparser parses its flags without error (a host command whose
    # configure replays the legacy argparse surface).
    args = parser.parse_args(["session", "--repo", ".", "--pr", "--json"])
    assert args.repo == "." and args.pr is True and args.json is True
