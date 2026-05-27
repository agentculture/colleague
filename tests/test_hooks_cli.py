"""``convertible hooks`` CLI noun group — list and overview (t6).

Acceptance criteria:
1. ``convertible hooks list --json`` emits structured JSON with a ``hooks`` key.
2. ``convertible hooks overview`` exits 0 and describes the noun.
3. ``convertible hooks overview --json`` has the expected subject.
4. Bare ``convertible hooks`` falls back to overview (non-empty output, exit 0).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from convertible.cli import main


def _make_hooks_json(repo: Path, hooks: dict) -> None:
    dotdir = repo / ".convertible"
    dotdir.mkdir(parents=True, exist_ok=True)
    (dotdir / "hooks.json").write_text(json.dumps(hooks))


# ---------------------------------------------------------------------------
# hooks list
# ---------------------------------------------------------------------------


def test_hooks_list_json_empty_repo(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Empty repo → empty list, valid JSON shape."""
    rc = main(["hooks", "list", "--repo", str(tmp_path), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert "hooks" in payload
    assert isinstance(payload["hooks"], list)


def test_hooks_list_json_with_hooks(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Repo with configured hooks → list contains those hooks."""
    _make_hooks_json(
        tmp_path,
        {
            "hooks": {
                "pre_tool": [{"matcher": "run_command", "command": "echo pre"}],
                "finish": [{"command": "echo done"}],
            }
        },
    )
    rc = main(["hooks", "list", "--repo", str(tmp_path), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["hooks"]) == 2
    events = [h["event"] for h in payload["hooks"]]
    assert "pre_tool" in events
    assert "finish" in events


def test_hooks_list_json_entry_shape(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Each entry has ``event``, ``matcher``, and ``command`` keys."""
    _make_hooks_json(
        tmp_path,
        {"hooks": {"pre_tool": [{"matcher": "run_command", "command": "echo hi"}]}},
    )
    rc = main(["hooks", "list", "--repo", str(tmp_path), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["hooks"]) == 1
    entry = payload["hooks"][0]
    assert entry["event"] == "pre_tool"
    assert entry["matcher"] == "run_command"
    assert entry["command"] == "echo hi"


def test_hooks_list_text_no_hooks(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Text mode with no hooks emits a notice to stdout, exit 0."""
    rc = main(["hooks", "list", "--repo", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert out.strip()  # not empty


def test_hooks_list_text_with_hooks(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Text mode with hooks includes the event name in output."""
    _make_hooks_json(
        tmp_path,
        {"hooks": {"task_start": [{"command": "echo start"}]}},
    )
    rc = main(["hooks", "list", "--repo", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "task_start" in out


# ---------------------------------------------------------------------------
# hooks overview
# ---------------------------------------------------------------------------


def test_hooks_overview_text(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["hooks", "overview"])
    assert rc == 0
    assert "convertible hooks" in capsys.readouterr().out


def test_hooks_overview_json_shape(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["hooks", "overview", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["subject"] == "convertible hooks"
    assert isinstance(payload["sections"], list)
    assert payload["sections"]


def test_hooks_bare_noun_prints_overview(capsys: pytest.CaptureFixture[str]) -> None:
    """Bare 'convertible hooks' (no sub-verb) should print an overview."""
    rc = main(["hooks"])
    assert rc == 0
    assert capsys.readouterr().out.strip()
