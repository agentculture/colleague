"""t6: the ``agents`` CLI noun rendered from the agentfront registry.

Exercises ``agents list`` and ``agents overview`` through agentfront's
``run_cli`` (the rendered path), proving each is a clean rendered tool:
a named-param func returning ``rendered(structured, text)`` gives colleague's
exact dual output (pretty text vs ``--json``), and every verb lands in the
registry (so MCP/learn enumerate it).
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout

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


def _paths():
    return {tuple(t.group) + (t.name,) for t in build_app().list_tools()}


def test_agents_list_json_empty(tmp_path):
    code, out, _ = _run(["agents", "list", "--repo", str(tmp_path), "--json"])
    assert code == 0
    payload = json.loads(out)
    assert "model" in payload and "agents" in payload

    paths = _paths()
    assert ("agents", "list") in paths


def test_agents_list_text_with_layers(tmp_path):
    (tmp_path / "AGENTS.md").write_text("base")
    code, out, _ = _run(["agents", "list", "--repo", str(tmp_path)])
    assert code == 0 and "base" in out


def test_agents_overview_json():
    code, out, _ = _run(["agents", "overview", "--json"])
    assert code == 0
    payload = json.loads(out)
    assert payload["subject"] == "colleague agents"
    assert isinstance(payload["sections"], list) and payload["sections"]

    paths = _paths()
    assert ("agents", "overview") in paths


def test_agents_overview_text():
    code, out, _ = _run(["agents", "overview"])
    assert code == 0 and "colleague agents" in out
