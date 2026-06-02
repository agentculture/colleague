"""``colleague skills`` CLI noun group — list and overview.

Acceptance:
1. ``skills list --json`` emits structured JSON with ``model`` + ``skills``.
2. ``skills list`` resolves base + model overlay; ``--model X`` never shows Y's.
3. ``skills overview`` (text + JSON) describes the noun; bare noun → overview.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from colleague.cli import main

_MODEL_X = "Qwen/Qwen3-32B"
_SAFE_X = "Qwen-Qwen3-32B"
_MODEL_Y = "meta/Llama-3"
_SAFE_Y = "meta-Llama-3"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_skills_list_json_empty_repo(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["skills", "list", "--repo", str(tmp_path), "--model", _MODEL_X, "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["model"] == _MODEL_X
    assert payload["skills"] == []


def test_skills_list_json_base_and_overlay(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(tmp_path / ".colleague" / "skills" / "base_skill.md", "# base")
    _write(tmp_path / ".colleague" / _SAFE_X / "skills" / "model_skill.md", "# model")

    rc = main(["skills", "list", "--repo", str(tmp_path), "--model", _MODEL_X, "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    by_name = {s["name"]: s["scope"] for s in payload["skills"]}
    assert by_name == {"base_skill": "base", "model_skill": "model"}


def test_skills_list_model_isolation(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write(tmp_path / ".colleague" / _SAFE_X / "skills" / "only_x.md", "# x")

    rc = main(["skills", "list", "--repo", str(tmp_path), "--model", _MODEL_X, "--json"])
    assert rc == 0
    names_x = {s["name"] for s in json.loads(capsys.readouterr().out)["skills"]}
    assert "only_x" in names_x

    rc = main(["skills", "list", "--repo", str(tmp_path), "--model", _MODEL_Y, "--json"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["skills"] == []


def test_skills_list_text_with_skills(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write(tmp_path / ".colleague" / "skills" / "greet.md", "# greet")
    rc = main(["skills", "list", "--repo", str(tmp_path), "--model", _MODEL_X])
    assert rc == 0
    assert "greet" in capsys.readouterr().out


def test_skills_overview_text(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["skills", "overview"])
    assert rc == 0
    assert "colleague skills" in capsys.readouterr().out


def test_skills_overview_json_shape(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["skills", "overview", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["subject"] == "colleague skills"
    assert isinstance(payload["sections"], list) and payload["sections"]


def test_skills_bare_noun_prints_overview(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["skills"])
    assert rc == 0
    assert capsys.readouterr().out.strip()
