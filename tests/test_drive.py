"""`convertible drive` — the headline verb wires engine->loop->artifact->handoff (c4)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from convertible.cli import main
from convertible.engines.mock import OUTPUT_FILE


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True)


def test_drive_mock_writes_artifact_and_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["drive", "set up the repo", "--repo", str(tmp_path), "--engine", "mock", "--no-pr"])
    assert rc == 0
    assert (tmp_path / OUTPUT_FILE).exists()
    artifacts = list((tmp_path / ".convertible").glob("*.json"))
    assert len(artifacts) == 1
    payload = json.loads(artifacts[0].read_text())
    assert payload["status"] == "ok"
    assert OUTPUT_FILE in payload["changed_files"]


def test_drive_json_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(
        ["drive", "do work", "--repo", str(tmp_path), "--engine", "mock", "--no-pr", "--json"]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert payload["pr_url"] is None


def test_drive_in_git_repo_creates_branch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@e.com")
    _git(tmp_path, "config", "user.name", "T")
    (tmp_path / "seed").write_text("x")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "init")

    rc = main(
        ["drive", "add a file", "--repo", str(tmp_path), "--engine", "mock", "--no-pr", "--json"]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["branch"].startswith("convertible/")
    assert payload["pr_url"] is None  # --no-pr never pushes


def test_drive_unknown_engine_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["drive", "x", "--repo", str(tmp_path), "--engine", "nope"])
    assert rc == 1
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "wheels list" in err


def test_drive_bad_repo_errors(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["drive", "x", "--repo", "/no/such/dir", "--engine", "mock"])
    assert rc == 1
    assert "not a directory" in capsys.readouterr().err
