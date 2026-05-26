"""Tests for the introspection verbs: overview, cli overview, doctor."""

from __future__ import annotations

import json

import pytest

from culture_agent_template.cli import main

# --- overview -------------------------------------------------------------


def test_overview_text(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["overview"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "# culture-agent-template" in out
    assert "Identity" in out


def test_overview_json_shape(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["overview", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["subject"] == "culture-agent-template"
    assert isinstance(payload["sections"], list)
    assert payload["sections"]


def test_overview_graceful_on_bad_path(capsys: pytest.CaptureFixture[str]) -> None:
    # Rubric contract: descriptive verbs never hard-fail on a missing target.
    rc = main(["overview", "/no/such/path/here"])
    assert rc == 0
    assert capsys.readouterr().out.strip()


# --- cli overview ---------------------------------------------------------


def test_cli_overview_text(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["cli", "overview"])
    assert rc == 0
    assert "# culture-agent-template cli" in capsys.readouterr().out


def test_cli_overview_json_shape(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["cli", "overview", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["subject"] == "culture-agent-template cli"
    assert isinstance(payload["sections"], list)


def test_cli_noun_bare_is_non_empty(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["cli"])
    assert rc == 0
    assert capsys.readouterr().out.strip()


def test_cli_overview_unknown_flag_structured_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # `cli overview` parse errors must route through the structured error
    # contract (error:/hint: + exit 1), not argparse's default stderr/exit 2.
    with pytest.raises(SystemExit) as exc:
        main(["cli", "overview", "--bogus"])
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "hint:" in err


# --- doctor ---------------------------------------------------------------


def test_doctor_text(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["doctor"])
    assert rc in (0, 1)
    assert "culture-agent-template doctor" in capsys.readouterr().out


def test_doctor_json_shape(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["doctor", "--json"])
    assert rc in (0, 1)
    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload["healthy"], bool)
    assert isinstance(payload["checks"], list)
    assert payload["checks"]
    for check in payload["checks"]:
        assert {"id", "passed", "severity", "message", "remediation"} <= set(check)
