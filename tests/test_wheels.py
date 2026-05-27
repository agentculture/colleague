"""`convertible wheels` — discovery surface (R4, c7/h14 wheels-list half)."""

from __future__ import annotations

import json

import pytest

from convertible.cli import main


def test_wheels_list_text_shows_both_engines(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["wheels", "list"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "mock" in out
    assert "vllm-openai" in out


def test_wheels_list_json_shape(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["wheels", "list", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    names = {e["name"] for e in payload["engines"]}
    assert {"mock", "vllm-openai"} <= names


def test_wheels_no_verb_prints_overview(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["wheels"])
    assert rc == 0
    assert "convertible wheels" in capsys.readouterr().out


def test_wheels_overview_json_shape(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["wheels", "overview", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["subject"] == "convertible wheels"
