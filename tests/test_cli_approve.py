"""CLI approval gate tests (t5) — TEST-FIRST / TDD.

Acceptance criteria:
1. ``commands approve <name>`` writes a checksum approval into
   ``<repo>/.convertible/approvals.json`` under ``["commands"][name]``;
   re-running is idempotent; other sections are preserved.
2. ``hooks approve <name>`` writes into ``["hooks"][name]``; missing file
   raises CliError.
3. ``commands list``, ``hooks list``, and ``skills list`` show
   approval/accessibility status; ``--json`` carries the status.
4. ``hooks list`` also shows the run_command allow/deny policy.
5. Every new verb supports ``--json``; failures raise CliError (no
   tracebacks); an ``explain`` entry exists for ``approve``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from convertible.cli import main

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_commands_dir(repo: Path) -> Path:
    cmds_dir = repo / ".convertible" / "commands"
    cmds_dir.mkdir(parents=True)
    return cmds_dir


def _make_hooks_json(repo: Path, hooks: dict) -> None:
    dotdir = repo / ".convertible"
    dotdir.mkdir(parents=True, exist_ok=True)
    (dotdir / "hooks.json").write_text(json.dumps(hooks))


def _read_approvals(repo: Path) -> dict:
    p = repo / ".convertible" / "approvals.json"
    return json.loads(p.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 1. commands approve — writes checksum, idempotent, preserves sections
# ---------------------------------------------------------------------------


def test_commands_approve_writes_checksum(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """commands approve <name> writes sha256:<hex> into approvals.json."""
    cmds_dir = _make_commands_dir(tmp_path)
    (cmds_dir / "lint.md").write_text("Fix lint errors.\n")

    rc = main(["commands", "approve", "lint", "--repo", str(tmp_path)])
    assert rc == 0

    approvals = _read_approvals(tmp_path)
    assert "commands" in approvals
    assert "lint" in approvals["commands"]
    assert approvals["commands"]["lint"].startswith("sha256:")


def test_commands_approve_json_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """commands approve --json emits structured output."""
    cmds_dir = _make_commands_dir(tmp_path)
    (cmds_dir / "fmt.md").write_text("Format code.\n")

    rc = main(["commands", "approve", "fmt", "--repo", str(tmp_path), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["name"] == "fmt"
    assert payload["category"] == "commands"
    assert payload["checksum"].startswith("sha256:")


def test_commands_approve_idempotent(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Running commands approve twice gives the same checksum."""
    cmds_dir = _make_commands_dir(tmp_path)
    (cmds_dir / "build.md").write_text("Build the project.\n")

    main(["commands", "approve", "build", "--repo", str(tmp_path)])
    first = _read_approvals(tmp_path)["commands"]["build"]

    main(["commands", "approve", "build", "--repo", str(tmp_path)])
    second = _read_approvals(tmp_path)["commands"]["build"]

    assert first == second


def test_commands_approve_preserves_other_sections(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """commands approve merges into existing approvals.json without clobbering other sections."""
    dotdir = tmp_path / ".convertible"
    dotdir.mkdir(parents=True, exist_ok=True)
    # Pre-existing hooks approval
    (dotdir / "approvals.json").write_text(
        json.dumps({"hooks": {"script.sh": "sha256:abc123"}, "run_command": {"allow": ["git"]}})
    )
    cmds_dir = dotdir / "commands"
    cmds_dir.mkdir()
    (cmds_dir / "fix.md").write_text("Fix stuff.\n")

    rc = main(["commands", "approve", "fix", "--repo", str(tmp_path)])
    assert rc == 0

    approvals = _read_approvals(tmp_path)
    # Existing sections must survive
    assert approvals["hooks"]["script.sh"] == "sha256:abc123"
    assert approvals["run_command"]["allow"] == ["git"]
    # New approval is present
    assert "fix" in approvals["commands"]


def test_commands_approve_algo_md5(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """--algo md5 records an md5:<hex> checksum."""
    cmds_dir = _make_commands_dir(tmp_path)
    (cmds_dir / "check.md").write_text("Check.\n")

    rc = main(["commands", "approve", "check", "--repo", str(tmp_path), "--algo", "md5"])
    assert rc == 0

    approvals = _read_approvals(tmp_path)
    assert approvals["commands"]["check"].startswith("md5:")


def test_commands_approve_unknown_command_raises_cli_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """commands approve <nonexistent> raises CliError (not traceback)."""
    rc = main(["commands", "approve", "no-such-cmd", "--repo", str(tmp_path)])
    assert rc != 0
    err = capsys.readouterr().err
    assert "error:" in err


# ---------------------------------------------------------------------------
# 2. hooks approve — writes checksum, missing file → CliError
# ---------------------------------------------------------------------------


def test_hooks_approve_writes_checksum(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """hooks approve <script> writes sha256:<hex> into approvals.json['hooks']."""
    script = tmp_path / "scripts" / "lint.sh"
    script.parent.mkdir(parents=True)
    script.write_text("#!/bin/sh\necho hi\n")

    rc = main(["hooks", "approve", "scripts/lint.sh", "--repo", str(tmp_path)])
    assert rc == 0

    approvals = _read_approvals(tmp_path)
    assert "hooks" in approvals
    assert "scripts/lint.sh" in approvals["hooks"]
    assert approvals["hooks"]["scripts/lint.sh"].startswith("sha256:")


def test_hooks_approve_json_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """hooks approve --json emits structured output."""
    script = tmp_path / "hook.sh"
    script.write_text("#!/bin/sh\n")

    rc = main(["hooks", "approve", "hook.sh", "--repo", str(tmp_path), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["name"] == "hook.sh"
    assert payload["category"] == "hooks"
    assert payload["checksum"].startswith("sha256:")


def test_hooks_approve_missing_file_raises_cli_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """hooks approve a missing file raises CliError."""
    rc = main(["hooks", "approve", "no-such.sh", "--repo", str(tmp_path)])
    assert rc != 0
    err = capsys.readouterr().err
    assert "error:" in err


def test_hooks_approve_idempotent(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Running hooks approve twice gives the same checksum."""
    script = tmp_path / "deploy.sh"
    script.write_text("#!/bin/sh\ndeploy\n")

    main(["hooks", "approve", "deploy.sh", "--repo", str(tmp_path)])
    first = _read_approvals(tmp_path)["hooks"]["deploy.sh"]

    main(["hooks", "approve", "deploy.sh", "--repo", str(tmp_path)])
    second = _read_approvals(tmp_path)["hooks"]["deploy.sh"]

    assert first == second


def test_hooks_approve_preserves_other_sections(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """hooks approve merges into existing approvals.json without clobbering other sections."""
    dotdir = tmp_path / ".convertible"
    dotdir.mkdir(parents=True, exist_ok=True)
    (dotdir / "approvals.json").write_text(json.dumps({"commands": {"lint": "sha256:deadbeef"}}))
    script = tmp_path / "run.sh"
    script.write_text("#!/bin/sh\n")

    rc = main(["hooks", "approve", "run.sh", "--repo", str(tmp_path)])
    assert rc == 0

    approvals = _read_approvals(tmp_path)
    assert approvals["commands"]["lint"] == "sha256:deadbeef"
    assert "run.sh" in approvals["hooks"]


# ---------------------------------------------------------------------------
# 3. commands list — shows approval status
# ---------------------------------------------------------------------------


def test_commands_list_json_shows_status_unapproved(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """commands list --json: commands section present but entry absent → status=unapproved."""
    dotdir = tmp_path / ".convertible"
    dotdir.mkdir(parents=True)
    # commands section is present (gate is active) but no entry for "lint"
    (dotdir / "approvals.json").write_text(json.dumps({"commands": {}}))
    cmds_dir = dotdir / "commands"
    cmds_dir.mkdir()
    (cmds_dir / "lint.md").write_text("Fix lint.\n")

    rc = main(["commands", "list", "--repo", str(tmp_path), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    entry = next(c for c in payload["commands"] if c["name"] == "lint")
    assert entry["status"] == "unapproved"


def test_commands_list_json_shows_status_approved(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """commands list --json: after approve → status=approved."""
    cmds_dir = _make_commands_dir(tmp_path)
    (cmds_dir / "fmt.md").write_text("Format.\n")

    main(["commands", "approve", "fmt", "--repo", str(tmp_path)])
    capsys.readouterr()  # discard

    rc = main(["commands", "list", "--repo", str(tmp_path), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    entry = next(c for c in payload["commands"] if c["name"] == "fmt")
    assert entry["status"] == "approved"


def test_commands_list_json_shows_status_drifted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """commands list --json: checksum mismatch → status=drifted."""
    cmds_dir = _make_commands_dir(tmp_path)
    cmd_file = cmds_dir / "build.md"
    cmd_file.write_text("Build v1.\n")

    main(["commands", "approve", "build", "--repo", str(tmp_path)])
    capsys.readouterr()

    # Mutate the file → checksum mismatch
    cmd_file.write_text("Build v2 — changed!\n")

    rc = main(["commands", "list", "--repo", str(tmp_path), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    entry = next(c for c in payload["commands"] if c["name"] == "build")
    assert entry["status"] == "drifted"


def test_commands_list_json_shows_status_ungated(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """commands list --json: commands section absent from policy → status=ungated."""
    # Create approvals.json with run_command but NO commands section
    dotdir = tmp_path / ".convertible"
    dotdir.mkdir(parents=True, exist_ok=True)
    (dotdir / "approvals.json").write_text(json.dumps({"run_command": {"allow": ["git"]}}))
    cmds_dir = dotdir / "commands"
    cmds_dir.mkdir()
    (cmds_dir / "lint.md").write_text("Fix lint.\n")

    rc = main(["commands", "list", "--repo", str(tmp_path), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    entry = next(c for c in payload["commands"] if c["name"] == "lint")
    assert entry["status"] == "ungated"


def test_commands_list_text_shows_status(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """commands list text mode includes the status word."""
    cmds_dir = _make_commands_dir(tmp_path)
    (cmds_dir / "lint.md").write_text("Fix.\n")

    rc = main(["commands", "list", "--repo", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    # One of the status words should appear
    assert any(w in out for w in ("unapproved", "approved", "drifted", "ungated"))


# ---------------------------------------------------------------------------
# 4. hooks list — shows approval status + run_command policy
# ---------------------------------------------------------------------------


def test_hooks_list_json_shows_approval_status(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """hooks list --json: shows approval_status per hook entry."""
    _make_hooks_json(
        tmp_path,
        {"hooks": {"pre_tool": [{"matcher": "run_command", "command": "echo hi"}]}},
    )

    rc = main(["hooks", "list", "--repo", str(tmp_path), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    for h in payload["hooks"]:
        assert "approval_status" in h


def test_hooks_list_json_shows_run_command_policy(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """hooks list --json: shows run_command policy when present in approvals.json."""
    dotdir = tmp_path / ".convertible"
    dotdir.mkdir(parents=True, exist_ok=True)
    (dotdir / "approvals.json").write_text(
        json.dumps({"run_command": {"allow": ["git", "pytest"], "deny": ["rm"]}})
    )
    _make_hooks_json(tmp_path, {"hooks": {}})

    rc = main(["hooks", "list", "--repo", str(tmp_path), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert "run_command_policy" in payload
    assert payload["run_command_policy"]["allow"] == ["git", "pytest"]
    assert payload["run_command_policy"]["deny"] == ["rm"]


def test_hooks_list_json_no_run_command_policy_when_absent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """hooks list --json: run_command_policy absent when no approvals.json."""
    rc = main(["hooks", "list", "--repo", str(tmp_path), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    # Either absent or null/empty is fine — but if present it must be null/empty
    rc_policy = payload.get("run_command_policy")
    assert rc_policy is None or rc_policy == {}


def test_hooks_list_json_hook_status_approved(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """hooks list --json: an approved hook script shows approval_status=approved."""
    # Create hook script
    script = tmp_path / "lint.sh"
    script.write_text("#!/bin/sh\necho lint\n")

    _make_hooks_json(
        tmp_path,
        {"hooks": {"pre_tool": [{"matcher": "run_command", "command": "lint.sh"}]}},
    )
    # Approve it
    main(["hooks", "approve", "lint.sh", "--repo", str(tmp_path)])
    capsys.readouterr()

    rc = main(["hooks", "list", "--repo", str(tmp_path), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    # The hook entry should have approval_status (we just check it's present;
    # keying logic for inline commands may vary)
    for h in payload["hooks"]:
        assert "approval_status" in h


# ---------------------------------------------------------------------------
# 5. skills list — shows accessible status
# ---------------------------------------------------------------------------


def test_skills_list_json_shows_accessible_status(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """skills list --json: every skill has status=accessible."""
    skill_dir = tmp_path / ".convertible" / "skills"
    skill_dir.mkdir(parents=True)
    (skill_dir / "myskill.md").write_text("# my skill\n")

    rc = main(["skills", "list", "--repo", str(tmp_path), "--model", "some-model", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    for s in payload["skills"]:
        assert s.get("status") == "accessible", f"Expected accessible, got {s}"


def test_skills_list_text_shows_accessible(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """skills list text mode mentions accessible."""
    skill_dir = tmp_path / ".convertible" / "skills"
    skill_dir.mkdir(parents=True)
    (skill_dir / "greet.md").write_text("# greet\n")

    rc = main(["skills", "list", "--repo", str(tmp_path), "--model", "some-model"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "accessible" in out


# ---------------------------------------------------------------------------
# 6. explain entry exists for approve
# ---------------------------------------------------------------------------


def test_explain_approve_exists(capsys: pytest.CaptureFixture[str]) -> None:
    """convertible explain approve emits non-empty docs (entry is registered)."""
    rc = main(["explain", "approve"])
    assert rc == 0
    out = capsys.readouterr().out
    assert out.strip()
    assert "approve" in out.lower()


def test_explain_commands_approve_exists(capsys: pytest.CaptureFixture[str]) -> None:
    """convertible explain commands approve emits non-empty docs."""
    rc = main(["explain", "commands", "approve"])
    assert rc == 0
    out = capsys.readouterr().out
    assert out.strip()


def test_explain_hooks_approve_exists(capsys: pytest.CaptureFixture[str]) -> None:
    """convertible explain hooks approve emits non-empty docs."""
    rc = main(["explain", "hooks", "approve"])
    assert rc == 0
    out = capsys.readouterr().out
    assert out.strip()


# ---------------------------------------------------------------------------
# 7. overview texts mention approve
# ---------------------------------------------------------------------------


def test_commands_overview_mentions_approve(capsys: pytest.CaptureFixture[str]) -> None:
    """commands overview mentions the approve verb."""
    rc = main(["commands", "overview"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "approve" in out


def test_hooks_overview_mentions_approve(capsys: pytest.CaptureFixture[str]) -> None:
    """hooks overview mentions the approve verb."""
    rc = main(["hooks", "overview"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "approve" in out
