"""Tests for the coherence CLI noun (colleague/cli/_commands/coherence.py).

Covers:
- overview text renders
- score on a tmp .md file with the coherence-CLI subprocess mocked
- not-installed degradation message
- show with a fabricated artifact directory
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from colleague.cli._commands import coherence as _mod
from colleague.cli._errors import CliError

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_md(tmp_path: Path) -> Path:
    """Create a temporary markdown file for scoring."""
    p = tmp_path / "test.md"
    p.write_text("# Hello\n\nSome content.\n")
    return p


@pytest.fixture
def mock_coherence_cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Monkeypatch shutil.which to pretend the coherence CLI is installed.

    Returns the path to a fake binary script that can be inspected.
    """
    fake = tmp_path / "coherence"
    fake.write_text("#!/usr/bin/env python3\nprint('ok')\n")
    fake.chmod(0o755)
    monkeypatch.setattr(
        _mod,
        "shutil",
        type(_mod.shutil)(
            which=lambda name: str(fake) if name == "coherence" else None,
            **{k: v for k, v in vars(_mod.shutil).items() if k != "which"},
        ),
    )
    # Also patch at the module level for the ALLOWED_CLI constant
    monkeypatch.setattr("shutil.which", lambda name: str(fake) if name == "coherence" else None)
    return fake


@pytest.fixture
def mock_score(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock _score_one so it never calls the real subprocess.

    Also fakes the coherence CLI's PRESENCE: scoring implies an installed CLI,
    and without patching ``shutil.which`` these tests only passed on machines
    that happen to have ``coherence`` on PATH (caught by CI, where it is
    absent and ``_check_cli_installed`` raised before the mock was reached).
    """
    monkeypatch.setattr(
        "shutil.which", lambda name: "/usr/bin/coherence" if name == "coherence" else None
    )

    def _fake_score_one(path: Path, root: Path, env: dict[str, str]) -> dict[str, Any]:
        return {
            "path": str(path),
            "meaning_score": 0.75,
            "status": "scored",
        }

    monkeypatch.setattr(_mod, "_score_one", _fake_score_one)


@pytest.fixture
def mock_embed_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock embed_env to return a configured embedder."""
    monkeypatch.setattr(
        _mod,
        "embed_env",
        lambda: {"COHERENCE_EMBED_URL": "http://localhost:8000/embed"},
    )


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------


class TestOverview:
    def test_overview_renders_text(self) -> None:
        result = _mod._coherence_overview()
        text = str(result)
        assert "coherence" in text.lower()
        assert "advisory" in text.lower()

    def test_overview_renders_json(self) -> None:
        result = _mod._coherence_overview()
        # The rendered wrapper is a dict subclass
        assert isinstance(result, dict)
        assert result.get("subject") == "colleague coherence"
        assert len(result.get("sections", [])) >= 1


# ---------------------------------------------------------------------------
# Score
# ---------------------------------------------------------------------------


class TestScore:
    def test_score_file_with_mock(
        self, tmp_md: Path, mock_score: None, mock_embed_env: None
    ) -> None:
        result = _mod._score_files([str(tmp_md)])
        text = str(result)
        assert "meaning" in text.lower()
        assert "0.75" in text

    def test_score_json_payload(self, tmp_md: Path, mock_score: None, mock_embed_env: None) -> None:
        result = _mod._score_files([str(tmp_md)])
        # The dict side carries the structured payload
        assert "files" in result
        assert len(result["files"]) == 1
        assert result["files"][0]["meaning_score"] == 0.75

    def test_score_nonexistent_file(
        self, tmp_path: Path, mock_score: None, mock_embed_env: None
    ) -> None:
        result = _mod._score_files([str(tmp_path / "nope.md")])
        text = str(result)
        assert "no valid markdown files" in text

    def test_score_no_embedder(self, tmp_md: Path, mock_score: None) -> None:
        """When embed_env returns None/empty, score raises CliError."""
        # Don't apply mock_embed_env — use the real embed_env which returns None
        # in test env
        # Force embed_env to return None
        import colleague.cli._commands.coherence as cm

        original = getattr(cm, "embed_env", None)
        try:
            cm.embed_env = lambda: None
            with pytest.raises(CliError) as exc_info:
                cm._score_files([str(tmp_md)])
            assert "no coherence embedder configured" in exc_info.value.message
        finally:
            if original is not None:
                cm.embed_env = original


# ---------------------------------------------------------------------------
# Not-installed degradation
# ---------------------------------------------------------------------------


class TestNotInstalled:
    def test_score_raises_when_cli_missing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_md: Path
    ) -> None:
        """When shutil.which returns None, score raises CliError."""
        import shutil

        monkeypatch.setattr(shutil, "which", lambda name: None)

        with pytest.raises(CliError) as exc_info:
            _mod._score_files([str(tmp_md)])

        assert exc_info.value.code == 2
        assert "coherence CLI not installed" in exc_info.value.message
        assert "uv tool install" in exc_info.value.remediation

    def test_show_raises_when_cli_missing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """When shutil.which returns None, show raises CliError."""
        monkeypatch.setattr("shutil.which", lambda name: None)

        # Fabricate an artifact
        artifact_dir = tmp_path / ".colleague" / "artifacts" / "task-001"
        artifact_dir.mkdir(parents=True)
        (artifact_dir / "result.json").write_text(
            json.dumps(
                {
                    "task_id": "task-001",
                    "stats": {"changed_files": ["README.md"]},
                }
            )
        )
        (tmp_path / "README.md").write_text("# Test\n")

        # Patch find_artifact to return our fake artifact
        monkeypatch.setattr(
            _mod,
            "find_artifact",
            lambda repo, task_id: artifact_dir / "result.json",
        )

        with pytest.raises(CliError) as exc_info:
            _mod._show_task("task-001", str(tmp_path))

        assert exc_info.value.code == 2
        assert "coherence CLI not installed" in exc_info.value.message


# ---------------------------------------------------------------------------
# Show
# ---------------------------------------------------------------------------


class TestShow:
    def test_show_fabricated_artifact(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """show resolves a fabricated artifact and returns its data."""
        # Fabricate an artifact directory
        artifact_dir = tmp_path / ".colleague" / "artifacts" / "task-001"
        artifact_dir.mkdir(parents=True)
        artifact_file = artifact_dir / "result.json"
        artifact_file.write_text(
            json.dumps(
                {
                    "task_id": "task-001",
                    "stats": {"changed_files": ["README.md", "CHANGELOG.md"]},
                    "coherence_report": {
                        "status": "scored",
                        "files": [
                            {"path": "README.md", "meaning_score": 0.82},
                        ],
                    },
                }
            )
        )
        (tmp_path / "README.md").write_text("# Test\n")
        (tmp_path / "CHANGELOG.md").write_text("## v0.1.0\n")

        # Patch find_artifact
        monkeypatch.setattr(
            _mod,
            "find_artifact",
            lambda repo, task_id: artifact_file,
        )

        # Patch _check_cli_installed to do nothing (skip CLI check)
        monkeypatch.setattr(_mod, "_check_cli_installed", lambda: None)

        # Patch embed_env
        monkeypatch.setattr(
            _mod,
            "embed_env",
            lambda: {"COHERENCE_EMBED_URL": "http://localhost:8000/embed"},
        )

        # Patch _score_one
        def _fake_score_one(path: Path, root: Path, env: dict[str, str]) -> dict[str, Any]:
            return {"path": str(path), "meaning_score": 0.9, "status": "scored"}

        monkeypatch.setattr(_mod, "_score_one", _fake_score_one)

        result = _mod._show_task("task-001", str(tmp_path))
        text = str(result)
        assert "task-001" in text
        assert "meaning" in text.lower()

        # Check structured payload
        assert result["task_id"] == "task-001"
        assert result["existing_report"] is not None
        assert result["existing_report"]["status"] == "scored"

    def test_show_no_md_files(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """show reports 'no changed .md files' when the artifact has none."""
        artifact_dir = tmp_path / ".colleague" / "artifacts" / "task-002"
        artifact_dir.mkdir(parents=True)
        artifact_file = artifact_dir / "result.json"
        artifact_file.write_text(
            json.dumps(
                {
                    "task_id": "task-002",
                    "stats": {"changed_files": ["main.py", "test_main.py"]},
                }
            )
        )

        monkeypatch.setattr(
            _mod,
            "find_artifact",
            lambda repo, task_id: artifact_file,
        )

        result = _mod._show_task("task-002", str(tmp_path))
        text = str(result)
        assert "no changed .md files" in text

    def test_show_no_existing_report(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """show reports None for existing_report when the artifact has none."""
        artifact_dir = tmp_path / ".colleague" / "artifacts" / "task-003"
        artifact_dir.mkdir(parents=True)
        artifact_file = artifact_dir / "result.json"
        artifact_file.write_text(
            json.dumps(
                {
                    "task_id": "task-003",
                    "stats": {"changed_files": []},
                }
            )
        )

        monkeypatch.setattr(
            _mod,
            "find_artifact",
            lambda repo, task_id: artifact_file,
        )

        result = _mod._show_task("task-003", str(tmp_path))
        assert result["existing_report"] is None

    def test_show_last_resolves(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """show with 'last' resolves via get_last_work."""
        artifact_dir = tmp_path / ".colleague" / "artifacts" / "task-last"
        artifact_dir.mkdir(parents=True)
        artifact_file = artifact_dir / "result.json"
        artifact_file.write_text(
            json.dumps(
                {
                    "task_id": "task-last",
                    "stats": {"changed_files": []},
                }
            )
        )

        monkeypatch.setattr(
            _mod,
            "get_last_work",
            lambda repo: "task-last",
        )
        monkeypatch.setattr(
            _mod,
            "find_artifact",
            lambda repo, task_id: artifact_file,
        )

        result = _mod._show_task("last", str(tmp_path))
        assert result["task_id"] == "task-last"

    def test_show_last_no_work_item(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """show with 'last' raises when no work item recorded."""
        monkeypatch.setattr(
            _mod,
            "get_last_work",
            lambda repo: None,
        )

        with pytest.raises(CliError) as exc_info:
            _mod._show_task("last", str(tmp_path))

        assert "no 'last' work item" in exc_info.value.message

    def test_show_missing_artifact(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """show raises when the artifact is not found."""
        monkeypatch.setattr(
            _mod,
            "find_artifact",
            lambda repo, task_id: None,
        )

        with pytest.raises(CliError) as exc_info:
            _mod._show_task("nonexistent", str(tmp_path))

        assert "no artifact found" in exc_info.value.message


# ---------------------------------------------------------------------------
# Legacy argparse path
# ---------------------------------------------------------------------------


class TestLegacyParser:
    def test_register_creates_subparsers(self) -> None:
        """register() wires a real 'coherence' subparser with score/show/overview."""
        import argparse

        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command", parser_class=type(parser))
        _mod.register(sub)

        # The 'coherence' noun is actually registered on the sub-parser action.
        assert "coherence" in sub.choices

        # A bare 'coherence' invocation parses to the no-verb default, which
        # itself delegates to the overview command.
        ns = parser.parse_args(["coherence"])
        assert ns.func is _mod._no_verb

        # Each verb sub-parser is wired to its own handler.
        ns_score = parser.parse_args(["coherence", "score", "a.md"])
        assert ns_score.func is _mod.cmd_coherence_score
        assert ns_score.paths == ["a.md"]

        ns_show = parser.parse_args(["coherence", "show", "task-1"])
        assert ns_show.func is _mod.cmd_coherence_show
        assert ns_show.ref == "task-1"

    def test_overview_cmd(self) -> None:
        """cmd_coherence_overview returns 0."""
        import argparse

        args = argparse.Namespace(json=False)
        rc = _mod.cmd_coherence_overview(args)
        assert rc == 0


class TestScoreRenderedSurface:
    """The agentfront-rendered tool passes ONE string, not a list (caught live)."""

    def test_score_accepts_a_single_path_string(
        self, tmp_md: Path, mock_score: None, mock_embed_env: None
    ) -> None:
        result = _mod._score_files(str(tmp_md))
        payload = result.data if hasattr(result, "data") else result
        assert isinstance(payload, dict)
        files = payload.get("files", [])
        assert len(files) == 1
        assert files[0]["path"] == str(tmp_md)
