"""Tests for the introspection verbs: overview, cli overview, doctor."""

from __future__ import annotations

import json

import pytest

from colleague.cli import main

# --- overview -------------------------------------------------------------


def test_overview_text(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["overview"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "# colleague" in out
    assert "Identity" in out


def test_overview_identity_surfaces_drive_model_consistent_with_whoami(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """overview's Identity block must agree with whoami, not show a bare
    ``model: unknown`` (the mesh model) while whoami reports the live drive
    model. Regression for the overview/whoami model disagreement."""
    from colleague.cli._commands.whoami import report

    ident = report()
    rc = main(["overview"])
    assert rc == 0
    out = capsys.readouterr().out
    # The useful, live-resolved drive engine/model are surfaced...
    assert f"drive engine: {ident['drive_engine']}" in out
    expected_model = (
        ident["drive_model"] if ident["drive_model"] is not None else "(mock backend — no model)"
    )
    assert f"drive model: {expected_model}" in out
    # ...and the bare, often-``unknown`` mesh ``model:`` line is gone.
    assert "\n- model:" not in out and "model: unknown" not in out


def test_overview_json_shape(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["overview", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["subject"] == "colleague"
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
    assert "# colleague cli" in capsys.readouterr().out


def test_cli_overview_json_shape(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["cli", "overview", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["subject"] == "colleague cli"
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
    assert "colleague doctor" in capsys.readouterr().out


def test_doctor_json_shape(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["doctor", "--json"])
    assert rc in (0, 1)
    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload["healthy"], bool)
    assert isinstance(payload["checks"], list)
    assert payload["checks"]
    for check in payload["checks"]:
        assert {"id", "passed", "severity", "message", "remediation"} <= set(check)


def _fake_models_ok(*_args: object, **_kwargs: object):
    """Stand-in /models response so --probe needs no live server."""

    class _R:
        def __enter__(self):
            return self

        def __exit__(self, *exc: object) -> bool:
            return False

        def read(self) -> bytes:
            return b'{"object": "list", "data": []}'

    return _R()


def test_doctor_probe_runs_reachability_check(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # cmd_doctor → diagnose(probe=True) is the only seam exercising the flag; the
    # underlying probe is unit-tested in test_oilcheck_reachability. Stub urlopen
    # so this stays a no-network CLI test.
    monkeypatch.setattr("urllib.request.urlopen", _fake_models_ok)
    rc = main(["doctor", "--probe"])
    assert rc in (0, 1)
    assert "provider_reachable" in capsys.readouterr().out


def test_doctor_without_probe_omits_reachability_check(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # No --probe ⇒ no network call, no reachability check (opt-in contract).
    rc = main(["doctor"])
    assert rc in (0, 1)
    assert "provider_reachable" not in capsys.readouterr().out
