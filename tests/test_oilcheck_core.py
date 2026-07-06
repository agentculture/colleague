"""Tests for the oilcheck core spine: the check-group contract + ``diagnose()``.

These are written test-first (TDD). They pin the contract that the five sibling
check-group modules build against:

* the rubric shape ``{healthy: bool, checks: [...]}`` with the five-key check dict;
* the severity gating rule (only a failed ``error`` flips ``healthy``);
* the ``doctor`` exit-code semantics (1 when unhealthy, else 0);
* that ``diagnose()`` is read-only — no file writes, no network sockets.
"""

from __future__ import annotations

import socket

import pytest

import colleague.oilcheck as oilcheck
from colleague.cli import main
from colleague.oilcheck import diagnose, make_check

_VALID_SEVERITIES = {"error", "warning", "info"}
_CHECK_KEYS = {"id", "passed", "severity", "message", "remediation"}


# --- rubric shape ---------------------------------------------------------


def test_diagnose_returns_rubric_shape() -> None:
    report = diagnose()
    assert set(report) == {"healthy", "checks"}
    assert isinstance(report["healthy"], bool)
    assert isinstance(report["checks"], list)


def test_every_check_has_exactly_five_keys_and_valid_severity() -> None:
    report = diagnose()
    # The spine always produces at least one check (identity always reports).
    assert report["checks"]
    for check in report["checks"]:
        assert set(check) == _CHECK_KEYS, check
        assert isinstance(check["id"], str) and check["id"]
        assert isinstance(check["passed"], bool)
        assert check["severity"] in _VALID_SEVERITIES
        assert isinstance(check["message"], str)
        assert isinstance(check["remediation"], str)


def test_check_ids_are_unique() -> None:
    ids = [c["id"] for c in diagnose()["checks"]]
    assert len(ids) == len(set(ids)), f"duplicate check ids: {ids}"


def test_passing_checks_carry_empty_remediation() -> None:
    for check in diagnose()["checks"]:
        if check["passed"]:
            assert check["remediation"] == ""


# --- make_check helper ----------------------------------------------------


def test_make_check_shape() -> None:
    check = make_check("some_id", True, "info", "all good")
    assert check == {
        "id": "some_id",
        "passed": True,
        "severity": "info",
        "message": "all good",
        "remediation": "",
    }


def test_make_check_with_remediation() -> None:
    check = make_check("bad", False, "error", "broken", remediation="fix it")
    assert check["remediation"] == "fix it"
    assert set(check) == _CHECK_KEYS


# --- severity gating: only a failed error flips healthy -------------------


def _const_group(checks):
    """A check-group callable returning a fixed list (a temporary group)."""

    def _checks():
        return list(checks)

    return _checks


def test_failed_error_flips_healthy_false(monkeypatch: pytest.MonkeyPatch) -> None:
    bad = make_check("boom", False, "error", "exploded", remediation="defuse it")
    monkeypatch.setattr(oilcheck, "CHECK_GROUPS", [_const_group([bad])])
    report = diagnose()
    assert report["healthy"] is False
    assert report["checks"] == [bad]


def test_failed_warning_and_info_do_not_flip_healthy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failing_warn = make_check("warn", False, "warning", "soft fail", remediation="maybe")
    failing_info = make_check("info", False, "info", "fyi", remediation="note")
    monkeypatch.setattr(oilcheck, "CHECK_GROUPS", [_const_group([failing_warn, failing_info])])
    report = diagnose()
    assert report["healthy"] is True


def test_passing_error_does_not_flip_healthy(monkeypatch: pytest.MonkeyPatch) -> None:
    ok_error = make_check("checked", True, "error", "verified")
    monkeypatch.setattr(oilcheck, "CHECK_GROUPS", [_const_group([ok_error])])
    assert diagnose()["healthy"] is True


# --- doctor exit-code semantics -------------------------------------------


def test_doctor_exits_1_when_error_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = make_check("boom", False, "error", "exploded", remediation="defuse it")
    monkeypatch.setattr(oilcheck, "CHECK_GROUPS", [_const_group([bad])])
    rc = main(["doctor"])
    assert rc == 1
    out = capsys.readouterr().out
    assert "colleague doctor: unhealthy" in out
    assert "[FAIL] boom" in out
    assert "hint: defuse it" in out


def test_doctor_exits_0_with_only_warning_failures(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    failing_warn = make_check("warn", False, "warning", "soft fail", remediation="maybe")
    monkeypatch.setattr(oilcheck, "CHECK_GROUPS", [_const_group([failing_warn])])
    rc = main(["doctor"])
    assert rc == 0
    assert "colleague doctor: healthy" in capsys.readouterr().out


def test_doctor_json_emits_diagnose_dict(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import json

    ok = make_check("fine", True, "info", "ok")
    monkeypatch.setattr(oilcheck, "CHECK_GROUPS", [_const_group([ok])])
    rc = main(["doctor", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"healthy": True, "checks": [ok]}


# --- read-only: no file writes, no network --------------------------------


def test_diagnose_writes_no_files(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Run under an empty tmp cwd and assert nothing gets created there.
    monkeypatch.chdir(tmp_path)
    before = set(tmp_path.iterdir())
    diagnose()
    after = set(tmp_path.iterdir())
    assert before == after, f"diagnose() created: {after - before}"


def test_diagnose_opens_no_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*_args, **_kwargs):
        raise AssertionError("diagnose() opened a socket")

    monkeypatch.setattr(socket, "socket", _boom)
    # Must not raise: a read-only diagnose never constructs a socket.
    report = diagnose()
    assert set(report) == {"healthy", "checks"}


# --- registry wiring ------------------------------------------------------


def test_check_groups_registered_in_order() -> None:
    # The canonical group order. Note: the opt-in reachability probe is
    # deliberately NOT registered here (it is invoked only by diagnose(probe=True)).
    from colleague.oilcheck import (
        engines,
        environment,
        identity,
        organs,
        otel,
        provider,
        stale_refs,
        usage,
    )

    assert oilcheck.CHECK_GROUPS == [
        identity.checks,
        provider.checks,
        usage.checks,
        engines.checks,
        otel.checks,
        environment.checks,
        stale_refs.checks,
        organs.checks,
    ]


def test_identity_group_is_non_empty() -> None:
    from colleague.oilcheck import identity

    checks = identity.checks()
    assert isinstance(checks, list) and checks
    for check in checks:
        assert set(check) == _CHECK_KEYS


# --- make_check invariant: remediation empty when passed (PR #29 review) -----


def test_make_check_rejects_remediation_when_passed() -> None:
    # The contract says remediation MUST be "" when passed is True; the factory
    # now enforces it so a group cannot silently violate the invariant.
    with pytest.raises(ValueError):
        make_check("x", True, "info", "all good", remediation="nothing to do")


# --- identity group never raises (PR #29 review: contract is "never raise") --


def test_identity_group_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    from colleague.oilcheck import identity

    def _boom() -> object:
        raise PermissionError("denied")

    # A filesystem/permission error inside the group must become a failed check,
    # not crash colleague doctor (the aggregator does not wrap groups).
    monkeypatch.setattr(identity, "find_culture_yaml", _boom)
    checks = identity.checks()  # must not raise
    assert any(c["id"] == "identity_checks_error" for c in checks)
    err = next(c for c in checks if c["id"] == "identity_checks_error")
    assert err["passed"] is False
    assert err["severity"] == "error"
    assert err["remediation"]
