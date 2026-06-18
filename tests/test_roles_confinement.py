"""Write-confinement proof for typed-subagent roles (#t12, c22/h16).

The headline safety claim, mechanically: NO offered tool — for ANY role — can
write OUTSIDE the repo/worktree box, and there is NO code path that enables a
cross-repo out-of-repo write (the "free-run" mode is explicitly absent from this
spec). Writes stay confined to the repo and the agent's own worktree.

Two layers:
1. A read-only role offers no write_file/edit_file/run_command at all.
2. The writer role DOES offer the file-write tools, but ``ToolExecutor._safe_path``
   confines them to the repo root — a path that escapes the root is refused.

Honest limit (documented, not a bug): ``run_command`` for the writer role is
arbitrary shell by design (the trusted-operator D2 model — bypassable by sh -c),
so this proves *file-write-tool* confinement + the absence of a cross-repo write
*mode*, not an OS sandbox.
"""

from __future__ import annotations

import subprocess

import pytest

import colleague.roles as roles_mod
import colleague.subagents as subagents_mod
import colleague.tools as tools_mod
from colleague.roles import BUILTIN_ROLES
from colleague.tools import ToolError, ToolExecutor, curate_schemas

_FILE_WRITE_TOOLS = {"write_file", "edit_file"}
_ALL_WRITE = {"write_file", "edit_file", "run_command"}


@pytest.fixture
def git_repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return tmp_path


def test_read_only_roles_offer_no_write_tool_at_all():
    for name in ("explorer", "planner", "reviewer", "validator"):
        offered = {s["function"]["name"] for s in curate_schemas(name)}
        assert not (offered & _ALL_WRITE), f"{name} offers a write tool: {offered & _ALL_WRITE}"


@pytest.mark.parametrize("escape", ["../escape.txt", "../../etc/escape", "/etc/escape"])
def test_writer_file_writes_are_confined_to_repo(git_repo, escape):
    # The writer role offers write_file/edit_file, but a path escaping the repo
    # root is refused — writes cannot land outside the box.
    ex = ToolExecutor(str(git_repo), allowlist=BUILTIN_ROLES["writer"])
    with pytest.raises(ToolError):
        ex.execute("write_file", {"path": escape, "content": "x"})


def test_every_role_file_write_surface_is_repo_confined(git_repo):
    # For EVERY role, any offered file-write tool confines to the repo box: a
    # read-only role offers none; the writer offers them but they refuse escapes.
    for name, role in BUILTIN_ROLES.items():
        offered = {s["function"]["name"] for s in curate_schemas(role)}
        ex = ToolExecutor(str(git_repo), allowlist=role)
        for tool in offered & _FILE_WRITE_TOOLS:
            with pytest.raises(ToolError):
                ex.execute(tool, {"path": "../../outside.txt", "content": "x"})


def test_no_cross_repo_free_run_write_mode_exists():
    # The free-run cross-repo write mode is parked (out of scope): no module
    # exposes a free-run/out-of-repo write entry point. The ToolExecutor confines
    # to a single resolved root; there is no multi-repo write seam.
    for mod in (tools_mod, subagents_mod, roles_mod):
        leaked = [n for n in dir(mod) if "free_run" in n.lower() or "freerun" in n.lower()]
        assert not leaked, f"{mod.__name__} exposes a free-run symbol: {leaked}"


def test_tool_executor_confines_to_one_root(git_repo):
    # A normal in-box write succeeds; the executor's root is the single confinement
    # boundary (no parameter widens it to another repo).
    ex = ToolExecutor(str(git_repo), allowlist=BUILTIN_ROLES["writer"])
    out = ex.execute("write_file", {"path": "inside.txt", "content": "ok"})
    assert (git_repo / "inside.txt").read_text() == "ok"
    assert out is not None
