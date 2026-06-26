"""t9: cross-surface parity — the #246 catalog invariant.

colleague's CLI, MCP, and HTTP surfaces are all derived from ONE imported
agentfront ``App`` registry, so they cannot drift. agentfront chose a
**single-dispatch** MCP surface (one ``run`` tool whose description embeds the
command catalog), so cross-surface parity is **catalog-level set-equality**, not
tool-count equality (spec honesty h5/h13, claim c16, reworded per colleague#246):

    the rendered CLI verb set == the single MCP dispatch tool's command catalog
    == the agentfront learn catalog — all enumerate the SAME registry operations.

The host-command launchers (``work`` / ``plan`` / ``session`` / ``tui`` /
``flight`` / ``clean`` / ``learn-from`` / ``promote``) and the reserved
meta-verbs are a DISTINCT class outside the registry, so they are consistently
absent from all three surfaces — set-equality still holds over the rendered
tools. This is the live successor of the coverage spike that discharged the
migration's feasibility assumption.
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout

import pytest
from agentfront.cli_surface import run_cli

from colleague.cli._app import build_app

# The host-command launchers — deliberately NOT registry tools, so consistently
# outside the CLI/MCP/learn catalog (they carry CLI-only semantics the rendered
# tool model can't express: custom exit codes, streaming, awkward flag surfaces).
_HOST_COMMANDS = {
    "work",
    "plan",
    "session",
    "tui",
    "flight",
    "clean",
    "learn-from",
    "promote",
}


def _registry_paths(app):
    return {tuple(t.group) + (t.name,) for t in app.list_tools()}


def _learn_paths(app):
    buf = io.StringIO()
    with redirect_stdout(buf):
        run_cli(app, ["learn", "--json"])
    return {tuple(t["path"]) for t in json.loads(buf.getvalue())["tools"]}


def test_cli_verb_set_equals_learn_catalog():
    """The rendered CLI verb set == the agentfront learn catalog (both the registry)."""
    app = build_app()
    reg = _registry_paths(app)
    assert reg == _learn_paths(app)
    assert len(reg) >= 20  # the migrated rendered-tool surface, not a stub


def test_host_commands_consistently_absent_from_catalog():
    """The host-command launchers are outside the registry — so absent from the
    CLI verb set, the learn catalog, and (below) the MCP catalog alike."""
    app = build_app()
    reg = _registry_paths(app)
    learn = _learn_paths(app)
    top_level = {p[0] for p in reg}
    for cmd in _HOST_COMMANDS:
        assert app.get_command(cmd) is not None, f"{cmd} must be a host command"
        assert cmd not in top_level, f"{cmd} must not be a registry tool"
    # And every host command really is registered on the CLI (just not as a tool).
    registered = {c.name for c in app.list_commands()}
    assert _HOST_COMMANDS <= registered
    assert top_level == {p[0] for p in learn}  # CLI nouns == learn nouns


def test_mcp_catalog_parity_and_single_dispatch():
    """registry == MCP single-tool catalog == learn, and MCP is ONE ``run`` tool."""
    pytest.importorskip("mcp", reason="the MCP bonus needs the optional [mcp] extra")
    from agentfront.mcp_surface import _build_catalog, _build_run_tool

    app = build_app()
    reg = _registry_paths(app)
    mcp_catalog = {tuple(c["path"]) for c in _build_catalog(app)}
    assert reg == mcp_catalog == _learn_paths(app)

    # Single-dispatch: the whole tool surface is exposed as ONE 'run' tool whose
    # description embeds the command catalog (not N MCP tools).
    run_tool = _build_run_tool(app)
    assert run_tool.name == "run"
    assert "feedback" in run_tool.description  # the catalog is embedded
