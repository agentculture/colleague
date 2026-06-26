"""t6: the read-only inspect/identity verbs rendered from the agentfront registry.

Exercises ``backends`` (+ the deprecated ``wheels`` alias), ``whoami``,
``telemetry``, and ``config`` through agentfront's ``run_cli`` (the rendered
path), proving each is a clean rendered tool: a named-param func returning
``rendered(structured, text)`` gives colleague's exact dual output (pretty text
vs ``--json``), and every verb lands in the registry (so MCP/learn enumerate it).
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


def test_backends_list_dual_rendered():
    code, out, _ = _run(["backends", "list", "--json"])
    assert code == 0
    assert "engines" in json.loads(out)

    code, out, _ = _run(["backends", "list"])
    # mock + vllm-openai ship as entry points, so the header row renders.
    assert code == 0 and ("NAME" in out or "no backend plugins" in out)


def test_wheels_alias_still_works():
    """The deprecated ``wheels`` noun alias is registered under its own group prefix."""
    code, out, _ = _run(["wheels", "list", "--json"])
    assert code == 0 and "engines" in json.loads(out)
    paths = _paths()
    assert ("backends", "list") in paths and ("wheels", "list") in paths


def test_whoami_dual_rendered():
    code, out, _ = _run(["whoami", "--json"])
    assert code == 0
    rec = json.loads(out)
    assert "nick" in rec and "work_engine" in rec and "version" in rec

    code, out, _ = _run(["whoami"])
    assert code == 0 and "nick:" in out
    assert ("whoami",) in _paths()


def test_telemetry_status_dual_rendered():
    code, out, _ = _run(["telemetry", "status", "--json"])
    assert code == 0
    rec = json.loads(out)
    assert "enabled" in rec and "sdk_installed" in rec

    code, out, _ = _run(["telemetry", "status"])
    assert code == 0 and "enabled:" in out
    assert ("telemetry", "status") in _paths()


def test_config_show_dual_rendered(tmp_path):
    code, out, _ = _run(["config", "show", "--repo", str(tmp_path), "--json"])
    assert code == 0
    assert "base_url" in json.loads(out)

    code, out, _ = _run(["config", "show", "--repo", str(tmp_path)])
    assert code == 0 and "base_url:" in out
    assert ("config", "show") in _paths()
