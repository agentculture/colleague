"""``colleague roles`` CLI noun — list + overview for typed subagent roles.

Acceptance:
1. ``roles list --json`` emits the resolved roles (5 built-ins) with
   read_only/tools/skills.
2. read-only roles carry no write_file/edit_file/run_command; validator has
   run_tests; writer is the full surface.
3. ``roles overview`` (and bare ``roles``) describes the noun, exit 0.
4. ``explain roles`` returns the catalog entry.
"""

from __future__ import annotations

import json

import pytest

from colleague.cli import main


def test_roles_list_json_shape(tmp_path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["roles", "list", "--repo", str(tmp_path), "--model", "test-model", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["model"] == "test-model"
    names = {r["name"] for r in payload["roles"]}
    assert names == {"explorer", "planner", "reviewer", "validator", "writer"}
    for r in payload["roles"]:
        assert set(r) >= {"name", "read_only", "tools", "skills"}


def test_read_only_roles_have_no_write_tools(tmp_path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["roles", "list", "--repo", str(tmp_path), "--model", "m", "--json"])
    assert rc == 0
    roles = {r["name"]: r for r in json.loads(capsys.readouterr().out)["roles"]}
    write_tools = {"write_file", "edit_file", "run_command"}
    for name in ("explorer", "planner", "reviewer", "validator"):
        assert roles[name]["read_only"] is True
        assert not (set(roles[name]["tools"]) & write_tools), name
    assert "run_tests" in roles["validator"]["tools"]
    assert roles["writer"]["read_only"] is False
    assert "write_file" in roles["writer"]["tools"]


def test_roles_list_text(tmp_path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["roles", "list", "--repo", str(tmp_path), "--model", "m"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "explorer" in out and "read-only" in out
    assert "writer" in out


def test_roles_overview(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["roles", "overview"])
    assert rc == 0
    assert "role" in capsys.readouterr().out.lower()


def test_roles_bare_runs_overview(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["roles"]) == 0


def test_explain_roles(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["explain", "roles"])
    assert rc == 0
    assert "roles" in capsys.readouterr().out.lower()
