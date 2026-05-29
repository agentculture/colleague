"""Tests for the shared CLI approval helpers and the commands/hooks status + display.

Covers ``convertible/cli/_approvals.py`` (the read/write/verify primitives shared
by the ``commands`` and ``hooks`` nouns) plus the previously-thin status and
run_command-policy-display branches in the two command modules.
"""

from __future__ import annotations

import argparse
import json

from convertible.cli import _approvals
from convertible.cli._commands import commands as commands_cli
from convertible.cli._commands import hooks as hooks_cli
from convertible.cli._commands import skills as skills_cli
from convertible.policy import file_checksum


def _ns(**kw) -> argparse.Namespace:
    return argparse.Namespace(**kw)


def _write_raw(repo, obj) -> None:
    dotdir = repo / ".convertible"
    dotdir.mkdir(parents=True, exist_ok=True)
    (dotdir / "approvals.json").write_text(
        obj if isinstance(obj, str) else json.dumps(obj), encoding="utf-8"
    )


# --- _approvals.approvals_path / read_section -------------------------------


def test_approvals_path(tmp_path):
    assert _approvals.approvals_path(tmp_path) == tmp_path / ".convertible" / "approvals.json"


def test_read_section_absent_file(tmp_path):
    assert _approvals.read_section(tmp_path, "commands") is None


def test_read_section_malformed_json(tmp_path):
    _write_raw(tmp_path, "{not valid json")
    assert _approvals.read_section(tmp_path, "commands") is None


def test_read_section_root_not_object(tmp_path):
    _write_raw(tmp_path, [1, 2, 3])
    assert _approvals.read_section(tmp_path, "commands") is None


def test_read_section_section_not_object(tmp_path):
    _write_raw(tmp_path, {"commands": "oops"})
    assert _approvals.read_section(tmp_path, "commands") is None


def test_read_section_valid(tmp_path):
    _write_raw(tmp_path, {"commands": {"a": "sha256:abc"}})
    assert _approvals.read_section(tmp_path, "commands") == {"a": "sha256:abc"}


# --- _approvals.write_approval ----------------------------------------------


def test_write_approval_fresh(tmp_path):
    _approvals.write_approval(tmp_path, "commands", "a", "sha256:1")
    data = json.loads((tmp_path / ".convertible" / "approvals.json").read_text())
    assert data == {"commands": {"a": "sha256:1"}}


def test_write_approval_merges_preserving_other_sections(tmp_path):
    _approvals.write_approval(tmp_path, "commands", "a", "sha256:1")
    _approvals.write_approval(tmp_path, "hooks", "h.sh", "sha256:2")
    data = json.loads((tmp_path / ".convertible" / "approvals.json").read_text())
    assert data == {"commands": {"a": "sha256:1"}, "hooks": {"h.sh": "sha256:2"}}


def test_write_approval_replaces_malformed_ledger(tmp_path):
    _write_raw(tmp_path, "{broken")
    _approvals.write_approval(tmp_path, "commands", "a", "sha256:1")
    data = json.loads((tmp_path / ".convertible" / "approvals.json").read_text())
    assert data == {"commands": {"a": "sha256:1"}}


def test_write_approval_root_not_object_is_replaced(tmp_path):
    _write_raw(tmp_path, [1, 2])
    _approvals.write_approval(tmp_path, "commands", "a", "sha256:1")
    assert json.loads((tmp_path / ".convertible" / "approvals.json").read_text()) == {
        "commands": {"a": "sha256:1"}
    }


def test_write_approval_section_not_object_is_reset(tmp_path):
    _write_raw(tmp_path, {"commands": "oops"})
    _approvals.write_approval(tmp_path, "commands", "a", "sha256:1")
    assert json.loads((tmp_path / ".convertible" / "approvals.json").read_text()) == {
        "commands": {"a": "sha256:1"}
    }


# --- _approvals.verify_status -----------------------------------------------


def test_verify_status_approved(tmp_path):
    f = tmp_path / "x.md"
    f.write_text("hello")
    assert _approvals.verify_status(f, file_checksum(f)) == "approved"


def test_verify_status_drifted_on_mismatch(tmp_path):
    f = tmp_path / "x.md"
    f.write_text("hello")
    assert _approvals.verify_status(f, "sha256:deadbeef") == "drifted"


def test_verify_status_drifted_on_missing_file(tmp_path):
    assert _approvals.verify_status(tmp_path / "nope.md", "sha256:x") == "drifted"


# --- hooks status helpers ---------------------------------------------------


def test_candidate_keys_normal():
    assert hooks_cli._candidate_keys("bash lint.sh") == ("bash lint.sh", "bash")


def test_candidate_keys_unbalanced_quote_falls_back():
    # shlex raises ValueError on an unbalanced quote → single-key tuple.
    assert hooks_cli._candidate_keys('echo "oops') == ('echo "oops',)


def test_hook_status_ungated_when_no_section(tmp_path):
    assert hooks_cli._hook_approval_status("echo hi", tmp_path) == "ungated"


def test_hook_status_unapproved_when_section_present_no_entry(tmp_path):
    _approvals.write_approval(tmp_path, "hooks", "other.sh", "sha256:x")
    assert hooks_cli._hook_approval_status("echo hi", tmp_path) == "unapproved"


def test_hook_status_approved_then_drifted_first_token_key(tmp_path):
    script = tmp_path / "lint.sh"
    script.write_text("echo lint")
    _approvals.write_approval(tmp_path, "hooks", "lint.sh", file_checksum(script))
    # command's first token ('lint.sh') is the approval key
    assert hooks_cli._hook_approval_status("lint.sh --fix", tmp_path) == "approved"
    script.write_text("tampered")
    assert hooks_cli._hook_approval_status("lint.sh --fix", tmp_path) == "drifted"


def test_hook_status_drifted_when_key_matches_but_file_missing(tmp_path):
    _approvals.write_approval(tmp_path, "hooks", "gone.sh", "sha256:x")
    assert hooks_cli._hook_approval_status("gone.sh", tmp_path) == "drifted"


# --- hooks list: run_command policy display ---------------------------------


def test_hooks_list_run_command_text_no_hooks(tmp_path, capsys):
    _write_raw(tmp_path, {"run_command": {"allow": ["git"], "deny": ["rm"]}})
    hooks_cli.cmd_hooks_list(_ns(repo=str(tmp_path), json=False, model=None))
    out = capsys.readouterr().out
    assert "(no hooks configured)" in out
    assert "run_command: allow=['git'] deny=['rm']" in out  # colon form (empty hooks)


def test_hooks_list_run_command_text_with_hooks(tmp_path, capsys):
    (tmp_path / ".convertible").mkdir()
    (tmp_path / ".convertible" / "hooks.json").write_text(
        json.dumps({"hooks": {"pre_tool": [{"matcher": "run_command", "command": "echo hi"}]}})
    )
    _write_raw(
        tmp_path,
        {
            "hooks": {"pre_tool": [{"matcher": "run_command", "command": "echo hi"}]},
            "run_command": {"allow": ["git"], "deny": []},
        },
    )
    hooks_cli.cmd_hooks_list(_ns(repo=str(tmp_path), json=False, model=None))
    out = capsys.readouterr().out
    assert "run_command allow=['git'] deny=[]" in out  # no-colon form (with hooks)


def test_hooks_list_run_command_json(tmp_path, capsys):
    _write_raw(tmp_path, {"run_command": {"allow": ["git"], "deny": []}})
    hooks_cli.cmd_hooks_list(_ns(repo=str(tmp_path), json=True, model=None))
    payload = json.loads(capsys.readouterr().out)
    assert payload["run_command_policy"] == {"allow": ["git"], "deny": []}
    assert payload["hooks"] == []


# --- commands list: status display branches ---------------------------------


def _make_command(repo, name, body, description=None):
    cdir = repo / ".convertible" / "commands"
    cdir.mkdir(parents=True, exist_ok=True)
    if description is not None:
        text = f"---\ndescription: {description}\n---\n{body}\n"
    else:
        text = body + "\n"
    (cdir / f"{name}.md").write_text(text)
    return cdir / f"{name}.md"


def test_commands_list_status_text_with_and_without_description(tmp_path, capsys):
    _make_command(tmp_path, "withdesc", "Do $1", description="Has a description")
    _make_command(tmp_path, "nodesc", "Do $1")  # no metadata block
    commands_cli.cmd_commands_list(_ns(repo=str(tmp_path), json=False))
    out = capsys.readouterr().out
    assert "withdesc\tHas a description\t[ungated]" in out
    assert "nodesc\t[ungated]" in out  # no-description branch


def test_commands_list_drifted_status_json(tmp_path, capsys):
    path = _make_command(tmp_path, "demo", "Do $1", description="d")
    _approvals.write_approval(tmp_path, "commands", "demo", file_checksum(path))
    path.write_text("tampered")  # drift
    commands_cli.cmd_commands_list(_ns(repo=str(tmp_path), json=True))
    payload = json.loads(capsys.readouterr().out)
    statuses = {c["name"]: c["status"] for c in payload["commands"]}
    assert statuses["demo"] == "drifted"


# --- skills list: empty branch ----------------------------------------------


def test_skills_list_empty_text(tmp_path, capsys):
    skills_cli.cmd_skills_list(_ns(repo=str(tmp_path), json=False, model="m"))
    assert "(no skills found)" in capsys.readouterr().out
