"""``convertible commands`` CLI noun group — list and overview (t6).

Acceptance criteria:
1. ``convertible commands list --json`` emits structured JSON with a ``commands`` key.
2. ``convertible commands overview`` exits 0 and describes the noun.
3. ``convertible commands overview --json`` has the expected subject.
4. Bare ``convertible commands`` falls back to overview (non-empty output, exit 0).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from convertible.cli import main


def _make_commands_dir(repo: Path) -> Path:
    cmds_dir = repo / ".convertible" / "commands"
    cmds_dir.mkdir(parents=True)
    return cmds_dir


# ---------------------------------------------------------------------------
# commands list
# ---------------------------------------------------------------------------


def test_commands_list_json_empty_repo(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Empty repo → empty list, valid JSON shape."""
    rc = main(["commands", "list", "--repo", str(tmp_path), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert "commands" in payload
    assert isinstance(payload["commands"], list)


def test_commands_list_json_with_commands(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Repo with one command template → list contains that command."""
    cmds_dir = _make_commands_dir(tmp_path)
    (cmds_dir / "lint.md").write_text(
        "---\ndescription: Fix lint errors\n---\nFix lint under $1.\n"
    )
    rc = main(["commands", "list", "--repo", str(tmp_path), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    names = [c["name"] for c in payload["commands"]]
    assert "lint" in names


def test_commands_list_json_entry_has_name_and_description(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Each entry in the JSON list has ``name`` and ``description`` keys."""
    cmds_dir = _make_commands_dir(tmp_path)
    (cmds_dir / "fmt.md").write_text(
        "---\ndescription: Run the formatter\n---\nFormat $ARGUMENTS.\n"
    )
    rc = main(["commands", "list", "--repo", str(tmp_path), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["commands"]) == 1
    entry = payload["commands"][0]
    assert entry["name"] == "fmt"
    assert entry["description"] == "Run the formatter"


def test_commands_list_text_no_commands(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Text mode with no commands emits a '(no commands)' notice to stdout, exit 0."""
    rc = main(["commands", "list", "--repo", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert out.strip()  # not empty — something was emitted


def test_commands_list_text_with_commands(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Text mode with commands includes the command name in output."""
    cmds_dir = _make_commands_dir(tmp_path)
    (cmds_dir / "build.md").write_text("Build the project.")
    rc = main(["commands", "list", "--repo", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "build" in out


# ---------------------------------------------------------------------------
# commands overview
# ---------------------------------------------------------------------------


def test_commands_overview_text(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["commands", "overview"])
    assert rc == 0
    assert "convertible commands" in capsys.readouterr().out


def test_commands_overview_json_shape(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["commands", "overview", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["subject"] == "convertible commands"
    assert isinstance(payload["sections"], list)
    assert payload["sections"]


def test_commands_bare_noun_prints_overview(capsys: pytest.CaptureFixture[str]) -> None:
    """Bare 'convertible commands' (no sub-verb) should print an overview."""
    rc = main(["commands"])
    assert rc == 0
    assert capsys.readouterr().out.strip()
