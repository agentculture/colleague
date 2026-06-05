"""`colleague backends` — discovery surface (R4, c7/h14 backends-list half).

`backends` is the primary noun; `wheels` is a deprecated alias kept for
back-compatibility. The alias-guard test pins that `wheels` still resolves.
"""

from __future__ import annotations

import json

import pytest

from colleague.cli import main


def test_backends_list_text_shows_both_engines(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["backends", "list"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "mock" in out
    assert "vllm-openai" in out


def test_backends_list_json_shape(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["backends", "list", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    names = {e["name"] for e in payload["engines"]}
    assert {"mock", "vllm-openai"} <= names


def test_backends_no_verb_prints_overview(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["backends"])
    assert rc == 0
    assert "colleague backends" in capsys.readouterr().out


def test_backends_list_empty_catalog_message(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """With no backend plugins discovered, `backends list` prints the empty-state message."""
    from colleague import registry

    monkeypatch.setattr(registry, "catalog", lambda: [])
    rc = main(["backends", "list"])
    assert rc == 0
    assert "(no backend plugins installed)" in capsys.readouterr().out


def test_backends_overview_json_shape(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["backends", "overview", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["subject"] == "colleague backends"


def test_wheels_alias_still_resolves(capsys: pytest.CaptureFixture[str]) -> None:
    """Back-compat: the deprecated `wheels` alias dispatches to the same handlers."""
    rc = main(["wheels", "list", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    names = {e["name"] for e in payload["engines"]}
    assert {"mock", "vllm-openai"} <= names


def test_wheels_alias_overview_shows_backends_subject(capsys: pytest.CaptureFixture[str]) -> None:
    """The alias surfaces the canonical `backends` subject (nudging users to the new name)."""
    rc = main(["wheels", "overview", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["subject"] == "colleague backends"
