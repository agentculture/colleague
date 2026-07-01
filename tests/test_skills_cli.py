"""``colleague skills`` CLI noun group — list and overview.

Acceptance:
1. ``skills list --json`` emits structured JSON with ``model`` + ``skills``.
2. ``skills list`` resolves base + model overlay; ``--model X`` never shows Y's.
3. ``skills overview`` (text + JSON) describes the noun; bare noun → overview.
4. (t11) ``skills list --role NAME`` filters to that role's curated skill_subset
   before listing; an unknown role name is a clean error.
5. (t11) ``skills list --budget N`` (with or without ``--role``) shows composed
   vs omitted skills at that token cap, with each skill's declared priority, in
   both text and ``--json`` — mirroring exactly what
   :func:`colleague.layers.compose_skills` would compose/omit at drive time.
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


# --- t11: --role filters to a role's curated skill_subset -------------------


def _write_role_fixture(tmp_path: Path) -> None:
    """A repo whose catalog mirrors this repo's real shape: an investigation
    -shaped pair (explore-a low priority, explore-b high priority) plus a
    release-shaped skill (cicd) the explorer role's curated subset excludes
    entirely, regardless of any token budget."""
    _write(tmp_path / ".colleague" / "skills" / "cicd.md", "# cicd\nOpen and manage PRs.")
    _write(
        tmp_path / ".colleague" / "skills" / "explore-a.md",
        "<!-- skill-priority: 90 -->\n# explore-a\n"
        "Explore A summary sentence padded to be longer for budget testing purposes here.\n",
    )
    _write(
        tmp_path / ".colleague" / "skills" / "explore-b.md",
        "<!-- skill-priority: 1 -->\n# explore-b\nShort survey note.\n",
    )


def test_skills_list_role_filters_to_curated_subset(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_role_fixture(tmp_path)
    rc = main(
        [
            "skills",
            "list",
            "--repo",
            str(tmp_path),
            "--model",
            _MODEL_X,
            "--role",
            "explorer",
            "--json",
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["role"] == "explorer"
    names = {s["name"] for s in payload["skills"]}
    assert names == {"explore-a", "explore-b"}  # cicd excluded by the curated subset


def test_skills_list_unknown_role_is_a_clean_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(
        ["skills", "list", "--repo", str(tmp_path), "--model", _MODEL_X, "--role", "no-such-role"]
    )
    assert rc != 0
    err = capsys.readouterr().err
    assert "unknown role" in err
    assert "hint:" in err


# --- t11: --budget shows composed vs omitted --------------------------------


def test_skills_list_budget_json_shows_composed_and_omitted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_role_fixture(tmp_path)
    rc = main(
        [
            "skills",
            "list",
            "--repo",
            str(tmp_path),
            "--model",
            _MODEL_X,
            "--role",
            "explorer",
            "--budget",
            "25",
            "--json",
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["role"] == "explorer"
    assert payload["budget"] == 25
    composed_names = {c["name"] for c in payload["composed"]}
    omitted_names = {o["name"] for o in payload["omitted"]}
    # cicd is excluded by the role subset entirely — never composed, never omitted.
    assert "cicd" not in composed_names and "cicd" not in omitted_names
    # explore-b (priority 1) survives the budget; explore-a (priority 90) is
    # dropped by the cap, not the role filter.
    assert composed_names == {"explore-b"}
    assert omitted_names == {"explore-a"}
    # every entry carries its declared priority.
    for entry in payload["composed"] + payload["omitted"]:
        assert "priority" in entry
    by_name = {e["name"]: e["priority"] for e in payload["composed"] + payload["omitted"]}
    assert by_name["explore-b"] == 1
    assert by_name["explore-a"] == 90


def test_skills_list_budget_text_shows_composed_and_omitted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_role_fixture(tmp_path)
    rc = main(
        [
            "skills",
            "list",
            "--repo",
            str(tmp_path),
            "--model",
            _MODEL_X,
            "--role",
            "explorer",
            "--budget",
            "25",
        ]
    )
    assert rc == 0
    text = capsys.readouterr().out
    assert "budget: 25 tokens" in text
    assert "role: explorer" in text
    assert "explore-b" in text.split("omitted")[0]  # composed section
    assert "explore-a" not in text.split("omitted")[0]
    assert "explore-a" in text.split("omitted")[1]  # omitted section
    assert "cicd" not in text


def test_skills_list_budget_zero_is_plain_listing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """--budget defaults to 0, meaning "no budget given" — the classic listing
    shape, byte-identical to omitting the flag."""
    _write_role_fixture(tmp_path)
    with_flag = main(
        ["skills", "list", "--repo", str(tmp_path), "--model", _MODEL_X, "--budget", "0", "--json"]
    )
    assert with_flag == 0
    payload_with = json.loads(capsys.readouterr().out)

    without_flag = main(["skills", "list", "--repo", str(tmp_path), "--model", _MODEL_X, "--json"])
    assert without_flag == 0
    payload_without = json.loads(capsys.readouterr().out)

    assert payload_with == payload_without
    assert "composed" not in payload_with
    assert "budget" not in payload_with
