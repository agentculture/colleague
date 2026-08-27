"""Plan t20 (c43): ``colleague clean`` reaps ``.colleague/tool-output/`` and reports bytes freed."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from colleague import truncation
from colleague.cli._commands.clean import cmd_clean


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "a.txt").write_text("hi\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    spill = repo / ".colleague" / "tool-output"
    spill.mkdir(parents=True)
    (spill / "aa.txt").write_text("x" * 1000, encoding="utf-8")
    (spill / "bb.txt").write_text("y" * 24, encoding="utf-8")
    (spill / "keep.log").write_text("not a spill", encoding="utf-8")
    return repo


def _args(repo: Path, *, dry_run: bool, json_mode: bool) -> argparse.Namespace:
    return argparse.Namespace(
        repo=str(repo), dry_run=dry_run, json=json_mode, merged=False, older_than=None, base="main"
    )


def test_reap_spill_dir_counts_files_and_bytes(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    dry = truncation.reap_spill_dir(repo, dry_run=True)
    assert dry == {
        "dir": str(repo / ".colleague" / "tool-output"),
        "files": 2,
        "bytes_freed": 1024,
        "action": "would-reap",
    }
    assert (repo / ".colleague" / "tool-output" / "aa.txt").exists()
    real = truncation.reap_spill_dir(repo)
    assert real["action"] == "reaped" and real["bytes_freed"] == 1024 and real["files"] == 2
    assert not (repo / ".colleague" / "tool-output" / "aa.txt").exists()
    assert (repo / ".colleague" / "tool-output" / "keep.log").exists()
    assert truncation.reap_spill_dir(repo)["action"] == "none"
    assert truncation.reap_spill_dir(tmp_path / "nowhere") == {
        "dir": str(tmp_path / "nowhere" / ".colleague" / "tool-output"),
        "files": 0,
        "bytes_freed": 0,
        "action": "none",
    }


def test_clean_reports_and_reaps_the_spill(tmp_path: Path, capsys) -> None:
    repo = _repo(tmp_path)
    assert cmd_clean(_args(repo, dry_run=True, json_mode=False)) == 0
    out = capsys.readouterr().out
    assert "tool-output spill (would reap): 2 file(s), 1024 B" in out
    assert (repo / ".colleague" / "tool-output" / "aa.txt").exists()
    assert cmd_clean(_args(repo, dry_run=False, json_mode=True)) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["tool_output"]["files"] == 2
    assert report["tool_output"]["bytes_freed"] == 1024
    assert report["tool_output"]["action"] == "reaped"
    assert not (repo / ".colleague" / "tool-output" / "aa.txt").exists()
    assert cmd_clean(_args(repo, dry_run=False, json_mode=False)) == 0
    assert "nothing to reap" in capsys.readouterr().out
