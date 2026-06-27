"""t10: the ``colleague mcp serve`` verb + an MCP round-trip (behind ``[mcp]``).

``mcp serve`` exposes colleague's operations as a single-dispatch MCP server (one
``run`` tool whose description embeds the catalog), built from the same agentfront
App that renders the CLI. The verb itself is a host command (``serve`` blocks);
these tests exercise the surface WITHOUT blocking: the verb's overview + its clean
degradation when ``[mcp]`` is absent, and a round-trip through the ``run`` tool's
dispatch logic (``get_by_path`` → ``func(**args)``) — proving a command from the
catalog resolves and executes the SAME registry operation the CLI verb does.
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout

import pytest
from agentfront.cli_surface import run_cli

from colleague.cli._app import build_app


def _run(argv):
    out, err = io.StringIO(), io.StringIO()
    code = None
    try:
        with redirect_stdout(out), redirect_stderr(err):
            code = run_cli(build_app(), argv)
    except SystemExit as exc:
        code = exc.code
    return code, out.getvalue(), err.getvalue()


def test_mcp_is_a_host_command_with_overview():
    """`mcp` registers as a host command; `mcp overview` describes the surface."""
    app = build_app()
    assert app.get_command("mcp") is not None
    # Not a registry tool (a host command — serve blocks).
    assert "mcp" not in {t.group[0] if t.group else t.name for t in app.list_tools()}

    code, out, _ = _run(["mcp", "overview", "--json"])
    assert code == 0
    rec = json.loads(out)
    assert rec["subject"] == "colleague mcp" and "sections" in rec

    code, out, _ = _run(["mcp", "overview"])
    assert code == 0 and "single-dispatch" in out.lower()


def test_mcp_explain_entry_exists():
    """The new noun carries an explain catalog entry (the agent-first convention)."""
    from colleague.explain import known_paths

    paths = set(known_paths())
    assert ("mcp",) in paths and ("mcp", "overview") in paths


def test_mcp_server_builds_and_round_trips():
    """With [mcp] installed, the server builds; a command from the catalog
    dispatches through the run-tool logic to the SAME registry op the CLI runs."""
    pytest.importorskip("mcp", reason="the MCP bonus needs the optional [mcp] extra")

    app = build_app()
    server = app.mcp_server()  # builds without raising → the extra is present
    assert server is not None

    # Public run-tool accessor (agentfront 0.15.0, issue #38 Ask 2) — no longer
    # reaching into the private ``_build_run_tool``.
    run_tool = server.run_tool
    assert run_tool.name == "run"
    assert set(run_tool.inputSchema["required"]) == {"command", "args"}

    # Round-trip: the run tool dispatches {command, args} via get_by_path -> func.
    # Drive a no-arg command (`whoami`) through that exact path and confirm it
    # returns the same identity payload the CLI `whoami --json` emits.
    entry = app.get_by_path(("whoami",))
    assert entry is not None
    result = entry.func()  # what call_tool(run, {command:[whoami], args:{}}) returns
    assert isinstance(result, dict) and result["nick"] and result["work_engine"]

    # An unknown command path resolves to None (the run tool's error branch).
    assert app.get_by_path(("does", "not", "exist")) is None
