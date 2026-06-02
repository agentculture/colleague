"""Tests for the shared approval-ledger writer and the commands/hooks status display.

Covers ``colleague/cli/_approvals.py`` (the repo-confined merge-and-write shared
by both ``approve`` verbs) and the ``list`` status branches, which now read the
*merged* policy (repo-over-user + per-model overlay) via ``load_policy`` and
derive hook keys via ``colleague.hooks.referenced_repo_files`` — so display
agrees with enforcement.
"""

from __future__ import annotations

import argparse
import json

import pytest

from colleague.cli import _approvals
from colleague.cli._commands import commands as commands_cli
from colleague.cli._commands import hooks as hooks_cli
from colleague.cli._commands import skills as skills_cli
from colleague.policy import file_checksum


def _ns(**kw) -> argparse.Namespace:
    return argparse.Namespace(**kw)


def _write_raw(repo, obj) -> None:
    dotdir = repo / ".colleague"
    dotdir.mkdir(parents=True, exist_ok=True)
    (dotdir / "approvals.json").write_text(
        obj if isinstance(obj, str) else json.dumps(obj), encoding="utf-8"
    )


# --- _approvals.write_approval ----------------------------------------------


def test_write_approval_confined_to_repo_root(tmp_path, monkeypatch):
    # The write target is confined to the resolved repo root; a config dir name
    # that would escape via traversal is rejected rather than written out of tree.
    monkeypatch.setattr(_approvals, "CONFIG_DIR_NAME", "../evil")
    repo = tmp_path / "repo"
    repo.mkdir()
    with pytest.raises(ValueError):
        _approvals.write_approval(repo, "commands", "a", "sha256:1")


def test_write_approval_fresh(tmp_path):
    _approvals.write_approval(tmp_path, "commands", "a", "sha256:1")
    data = json.loads((tmp_path / ".colleague" / "approvals.json").read_text())
    assert data == {"commands": {"a": "sha256:1"}}


def test_write_approval_merges_preserving_other_sections(tmp_path):
    _approvals.write_approval(tmp_path, "commands", "a", "sha256:1")
    _approvals.write_approval(tmp_path, "hooks", "h.sh", "sha256:2")
    data = json.loads((tmp_path / ".colleague" / "approvals.json").read_text())
    assert data == {"commands": {"a": "sha256:1"}, "hooks": {"h.sh": "sha256:2"}}


def test_write_approval_replaces_malformed_ledger(tmp_path):
    _write_raw(tmp_path, "{broken")
    _approvals.write_approval(tmp_path, "commands", "a", "sha256:1")
    data = json.loads((tmp_path / ".colleague" / "approvals.json").read_text())
    assert data == {"commands": {"a": "sha256:1"}}


def test_write_approval_root_not_object_is_replaced(tmp_path):
    _write_raw(tmp_path, [1, 2])
    _approvals.write_approval(tmp_path, "commands", "a", "sha256:1")
    assert json.loads((tmp_path / ".colleague" / "approvals.json").read_text()) == {
        "commands": {"a": "sha256:1"}
    }


def test_write_approval_section_not_object_is_reset(tmp_path):
    _write_raw(tmp_path, {"commands": "oops"})
    _approvals.write_approval(tmp_path, "commands", "a", "sha256:1")
    assert json.loads((tmp_path / ".colleague" / "approvals.json").read_text()) == {
        "commands": {"a": "sha256:1"}
    }


# --- hooks status (merged policy + shared key derivation) --------------------


def _make_hook_repo(repo, command, *, hooks_json=True):
    """A repo with a hooks.json that runs *command* (so it shows in `hooks list`)."""
    dotdir = repo / ".colleague"
    dotdir.mkdir(parents=True, exist_ok=True)
    if hooks_json:
        (dotdir / "hooks.json").write_text(
            json.dumps({"hooks": {"pre_tool": [{"matcher": "run_command", "command": command}]}})
        )


def test_hook_status_ungated_when_no_section(tmp_path):
    script = tmp_path / "lint.sh"
    script.write_text("echo")
    assert hooks_cli._hook_approval_status("bash lint.sh", tmp_path) == "ungated"


def test_hook_status_exempt_for_inline_command(tmp_path):
    # Section present, but the command references no repo file → nothing to approve.
    _approvals.write_approval(tmp_path, "hooks", "other.sh", "sha256:x")
    assert hooks_cli._hook_approval_status("echo hi", tmp_path) == "exempt"


def test_hook_status_unapproved_for_referenced_unapproved_file(tmp_path):
    script = tmp_path / "lint.sh"
    script.write_text("echo")
    _approvals.write_approval(tmp_path, "hooks", "other.sh", "sha256:x")  # section present
    assert hooks_cli._hook_approval_status("bash lint.sh", tmp_path) == "unapproved"


def test_hook_status_approved_then_drifted(tmp_path):
    script = tmp_path / "lint.sh"
    script.write_text("echo lint")
    _approvals.write_approval(tmp_path, "hooks", "lint.sh", file_checksum(script))
    assert hooks_cli._hook_approval_status("lint.sh --fix", tmp_path) == "approved"
    script.write_text("tampered")
    assert hooks_cli._hook_approval_status("lint.sh --fix", tmp_path) == "drifted"


def test_hook_status_honors_per_model_overlay(tmp_path):
    script = tmp_path / "lint.sh"
    script.write_text("echo lint")
    # base: unapproved; per-model overlay: approved
    _approvals.write_approval(tmp_path, "hooks", "other.sh", "sha256:x")
    model_dir = tmp_path / ".colleague" / "m"
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "approvals.json").write_text(
        json.dumps({"hooks": {"lint.sh": file_checksum(script)}})
    )
    assert hooks_cli._hook_approval_status("bash lint.sh", tmp_path) == "unapproved"
    assert hooks_cli._hook_approval_status("bash lint.sh", tmp_path, "m") == "approved"


# --- hooks approve: canonical key normalization (qodo #4) -------------------


def test_hooks_approve_normalizes_key_to_repo_relative(tmp_path, capsys):
    script = tmp_path / "scripts" / "lint.sh"
    script.parent.mkdir(parents=True)
    script.write_text("echo")
    # Approve via a non-canonical path; the stored key must be canonical.
    hooks_cli.cmd_hooks_approve(
        _ns(name="./scripts/lint.sh", repo=str(tmp_path), algo="sha256", json=False)
    )
    out = capsys.readouterr().out
    assert "approved hooks/scripts/lint.sh" in out  # normalized, no leading ./
    data = json.loads((tmp_path / ".colleague" / "approvals.json").read_text())
    assert "scripts/lint.sh" in data["hooks"]
    # And a hook command referencing the same file is now seen as approved.
    assert hooks_cli._hook_approval_status("bash scripts/lint.sh", tmp_path) == "approved"


def test_hooks_approve_rejects_escape(tmp_path):
    from colleague.cli._errors import CliError

    with pytest.raises(CliError):
        hooks_cli.cmd_hooks_approve(
            _ns(name="../outside.sh", repo=str(tmp_path), algo="sha256", json=False)
        )


# --- hooks list: run_command policy display (merged) ------------------------


def test_hooks_list_run_command_text_no_hooks(tmp_path, capsys):
    _write_raw(tmp_path, {"run_command": {"allow": ["git"], "deny": ["rm"]}})
    hooks_cli.cmd_hooks_list(_ns(repo=str(tmp_path), json=False, model=None))
    out = capsys.readouterr().out
    assert "(no hooks configured)" in out
    assert "run_command: allow=['git'] deny=['rm']" in out  # colon form (empty hooks)


def test_hooks_list_run_command_json(tmp_path, capsys):
    _write_raw(tmp_path, {"run_command": {"allow": ["git"], "deny": []}})
    hooks_cli.cmd_hooks_list(_ns(repo=str(tmp_path), json=True, model=None))
    payload = json.loads(capsys.readouterr().out)
    assert payload["run_command_policy"] == {"allow": ["git"], "deny": []}
    assert payload["hooks"] == []


def test_hooks_list_with_hooks_text_no_colon(tmp_path, capsys):
    _make_hook_repo(tmp_path, "echo hi")
    _write_raw(
        tmp_path,
        {
            "hooks": {"pre_tool": [{"matcher": "run_command", "command": "echo hi"}]},
            "run_command": {"allow": ["git"], "deny": []},
        },
    )
    # rewrite hooks.json (clobbered by _write_raw on approvals only; ensure present)
    _make_hook_repo(tmp_path, "echo hi")
    hooks_cli.cmd_hooks_list(_ns(repo=str(tmp_path), json=False, model=None))
    out = capsys.readouterr().out
    assert "run_command allow=['git'] deny=[]" in out  # no-colon form (with hooks)


# --- commands list: status display branches (merged policy) -----------------


def _make_command(repo, name, body, description=None):
    cdir = repo / ".colleague" / "commands"
    cdir.mkdir(parents=True, exist_ok=True)
    text = (
        f"---\ndescription: {description}\n---\n{body}\n"
        if description is not None
        else body + "\n"
    )
    (cdir / f"{name}.md").write_text(text)
    return cdir / f"{name}.md"


def test_commands_list_status_text_with_and_without_description(tmp_path, capsys):
    _make_command(tmp_path, "withdesc", "Do $1", description="Has a description")
    _make_command(tmp_path, "nodesc", "Do $1")
    commands_cli.cmd_commands_list(_ns(repo=str(tmp_path), json=False, model=None))
    out = capsys.readouterr().out
    assert "withdesc\tHas a description\t[ungated]" in out
    assert "nodesc\t[ungated]" in out  # no-description branch


def test_commands_list_drifted_status_json(tmp_path, capsys):
    path = _make_command(tmp_path, "demo", "Do $1", description="d")
    _approvals.write_approval(tmp_path, "commands", "demo", file_checksum(path))
    path.write_text("tampered")  # drift
    commands_cli.cmd_commands_list(_ns(repo=str(tmp_path), json=True, model=None))
    payload = json.loads(capsys.readouterr().out)
    statuses = {c["name"]: c["status"] for c in payload["commands"]}
    assert statuses["demo"] == "drifted"


def test_commands_list_honors_per_model_overlay(tmp_path, capsys):
    path = _make_command(tmp_path, "demo", "Do $1", description="d")
    model_dir = tmp_path / ".colleague" / "m"
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "approvals.json").write_text(
        json.dumps({"commands": {"demo": file_checksum(path)}})
    )
    commands_cli.cmd_commands_list(_ns(repo=str(tmp_path), json=True, model=None))
    base = {c["name"]: c["status"] for c in json.loads(capsys.readouterr().out)["commands"]}
    assert base["demo"] == "ungated"  # base: no commands section
    commands_cli.cmd_commands_list(_ns(repo=str(tmp_path), json=True, model="m"))
    overlaid = {c["name"]: c["status"] for c in json.loads(capsys.readouterr().out)["commands"]}
    assert overlaid["demo"] == "approved"  # per-model overlay recognized


# --- skills list: empty branch ----------------------------------------------


def test_skills_list_empty_text(tmp_path, capsys):
    skills_cli.cmd_skills_list(_ns(repo=str(tmp_path), json=False, model="m"))
    assert "(no skills found)" in capsys.readouterr().out
