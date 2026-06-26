"""t7: the mesh/extensibility verbs on the agentfront registry.

Two classes here:

* **Rendered tools** — ``cli`` / ``roles`` / ``commands`` / ``hooks`` are clean
  read-only (or checksum-approve) verbs: a named-param func returning
  ``rendered(structured, text)``, dual --json/text, in the catalog.
* **Host commands** — ``flight`` / ``clean`` / ``learn-from`` / ``promote`` carry
  streaming (``flight status --follow``), hyphenated/None-default flags, or drive
  the engine, so they reuse their argparse handlers via ``app.add_command`` and
  stay OUT of the tool catalog by design (like ``work`` / ``plan``).

All driven through agentfront's ``run_cli`` (the rendered path).
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout

from agentfront.cli_surface import run_cli

from colleague.cli._app import build_app

_T7_HOST_COMMANDS = ("flight", "clean", "learn-from", "promote")


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


def test_cli_overview_rendered():
    code, out, _ = _run(["cli", "overview", "--json"])
    assert code == 0 and "sections" in json.loads(out)
    code, out, _ = _run(["cli", "overview"])
    assert code == 0 and "cli" in out.lower()
    assert ("cli", "overview") in _paths()


def test_roles_list_rendered(tmp_path):
    code, out, _ = _run(["roles", "list", "--repo", str(tmp_path), "--json"])
    assert code == 0
    rec = json.loads(out)
    assert "roles" in rec and any(r["name"] == "explorer" for r in rec["roles"])

    code, out, _ = _run(["roles", "list", "--repo", str(tmp_path)])
    assert code == 0 and "explorer" in out
    assert ("roles", "list") in _paths()


def test_skills_list_rendered(tmp_path):
    code, out, _ = _run(["skills", "list", "--repo", str(tmp_path), "--json"])
    assert code == 0
    rec = json.loads(out)
    assert "model" in rec and "skills" in rec and isinstance(rec["skills"], list)

    code, out, _ = _run(["skills", "list", "--repo", str(tmp_path)])
    assert code == 0  # empty repo → "(no skills found)" or a layered list
    assert ("skills", "list") in _paths() and ("skills", "overview") in _paths()


def test_commands_list_empty_repo_rendered(tmp_path):
    code, out, _ = _run(["commands", "list", "--repo", str(tmp_path), "--json"])
    assert code == 0 and json.loads(out) == {"commands": []}
    code, out, _ = _run(["commands", "list", "--repo", str(tmp_path)])
    assert code == 0 and "no command templates" in out
    assert ("commands", "approve") in _paths()


def test_commands_approve_missing_errors_cleanly(tmp_path):
    code, out, err = _run(["commands", "approve", "nope", "--repo", str(tmp_path)])
    assert code == 1 and out.strip() == "" and "error:" in err and "Traceback" not in err


def test_hooks_list_empty_repo_rendered(tmp_path):
    code, out, _ = _run(["hooks", "list", "--repo", str(tmp_path), "--json"])
    assert code == 0 and json.loads(out) == {"hooks": []}
    code, out, _ = _run(["hooks", "list", "--repo", str(tmp_path)])
    assert code == 0 and "no hooks configured" in out
    assert ("hooks", "approve") in _paths()


def test_t7_host_commands_registered_not_tools():
    app = build_app()
    cmds = {c.name for c in app.list_commands()}
    top_level = {p[0] for p in _paths()}
    for name in _T7_HOST_COMMANDS:
        assert name in cmds, f"{name} should be a host command"
        assert name not in top_level, f"{name} must not also be a registry tool"


def test_flight_overview_and_clean_dry_run_exit_zero(tmp_path):
    # flight is a host command; bare `flight` falls through to overview.
    code, out, _ = _run(["flight"])
    assert code == 0
    # clean --dry-run on a non-git dir is a clean user error (exit 1), proving the
    # hyphenated flag survives the host-command configure.
    code, out, err = _run(["clean", "--repo", str(tmp_path), "--dry-run"])
    assert code == 1 and "error:" in err  # not a git repo
