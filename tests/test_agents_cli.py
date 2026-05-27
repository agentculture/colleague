"""``convertible agents`` CLI noun group — list and overview.

Acceptance:
1. ``agents list --json`` emits structured JSON with ``model`` + ``agents``.
2. ``agents list`` resolves the model overlay; ``--model X`` never shows Y's.
3. ``agents overview`` (text + JSON) describes the noun; bare noun → overview.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from convertible.cli import main

_MODEL_X = "Qwen/Qwen3-32B"
_SAFE_X = "Qwen-Qwen3-32B"
_MODEL_Y = "meta/Llama-3"
_SAFE_Y = "meta-Llama-3"


def test_agents_list_json_empty_repo(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["agents", "list", "--repo", str(tmp_path), "--model", _MODEL_X, "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["model"] == _MODEL_X
    assert payload["agents"] == []


def test_agents_list_json_with_layers(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "AGENTS.md").write_text("base")
    (tmp_path / f"AGENTS.convertible.{_SAFE_X}.md").write_text("model")

    rc = main(["agents", "list", "--repo", str(tmp_path), "--model", _MODEL_X, "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    scopes = [a["scope"] for a in payload["agents"]]
    assert scopes == ["base", "model"]


def test_agents_list_model_isolation(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """--model X shows X's overlay; --model Y does not show X's."""
    (tmp_path / f"AGENTS.convertible.{_SAFE_X}.md").write_text("x")

    rc = main(["agents", "list", "--repo", str(tmp_path), "--model", _MODEL_X, "--json"])
    assert rc == 0
    payload_x = json.loads(capsys.readouterr().out)
    assert any(a["scope"] == "model" for a in payload_x["agents"])

    rc = main(["agents", "list", "--repo", str(tmp_path), "--model", _MODEL_Y, "--json"])
    assert rc == 0
    payload_y = json.loads(capsys.readouterr().out)
    assert payload_y["agents"] == []


def test_agents_list_text_with_layers(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "AGENTS.md").write_text("base")
    rc = main(["agents", "list", "--repo", str(tmp_path), "--model", _MODEL_X])
    assert rc == 0
    assert "base" in capsys.readouterr().out  # the scope label "base"


def test_agents_overview_text(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["agents", "overview"])
    assert rc == 0
    assert "convertible agents" in capsys.readouterr().out


def test_agents_overview_json_shape(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["agents", "overview", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["subject"] == "convertible agents"
    assert isinstance(payload["sections"], list) and payload["sections"]


def test_agents_bare_noun_prints_overview(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["agents"])
    assert rc == 0
    assert capsys.readouterr().out.strip()
