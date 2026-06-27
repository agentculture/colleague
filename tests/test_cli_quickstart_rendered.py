"""t3: the quickstart verb rendered from the agentfront App registry.

Exercises the migrated `quickstart` verb through agentfront's run_cli (the
rendered path), proving the flat-verb migration pattern: a named-param tool
func that returns ``rendered(structured, text)`` produces colleague's exact
dual output (pretty text vs --json structured), and the tool lands in the
registry (so MCP/learn see it too).
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
    except SystemExit as exc:  # KeyboardInterrupt path
        code = exc.code
    return code, out.getvalue(), err.getvalue()


def test_quickstart_text_mode():
    code, out, _ = _run(["quickstart"])
    assert code == 0
    assert "quickstart" in out
    assert "colleague doctor" in out


def test_quickstart_json_mode():
    code, out, _ = _run(["quickstart", "--json"])
    assert code == 0
    data = json.loads(out)
    assert "steps" in data
    steps = data["steps"]
    assert isinstance(steps, list) and len(steps) > 0
    first = steps[0]
    assert "title" in first
    assert "command" in first
    assert "why" in first


def test_quickstart_tool_lands_in_registry():
    """The verb is a real registry tool (so MCP/learn enumerate it too)."""
    app = build_app()
    names = {t.name for t in app.list_tools()}
    assert "quickstart" in names
