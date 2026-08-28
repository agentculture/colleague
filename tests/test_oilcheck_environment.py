"""Tests for the environment check-group (TDD — written before the implementation).

Test contract:
* Healthy baseline in the actual repo → ``git_present`` passes, ``cli_integrity``
  passes, no error-severity failures.
* Malformed ``hooks.json`` → ``hooks_valid`` is an ``error`` with non-empty
  remediation, and ``diagnose()`` is unhealthy.
* ``git`` absent (monkeypatched) → ``git_present`` error.
* ``gh`` absent (monkeypatched) → ``gh_present`` warning (does NOT flip health).
* ``webglass`` (t6) — absent/unhealthy → warning; healthy → ok; >10 sessions
  → warning naming the count. Always WARN-only: never flips ``diagnose()``
  health, and ``colleague doctor``'s exit code is unaffected either way.
* ``web_search_provider`` (t6) — ``WEBGLASS_BRAVE_API_KEY`` set → ok; unset →
  warning "unset in this process". Always WARN-only, and the key value is
  never present in any check's message/remediation.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import pytest

from colleague import livecheck
from colleague.cli._commands.doctor import cmd_doctor
from colleague.oilcheck import diagnose
from colleague.oilcheck import environment as env_mod

# The full set of ids emitted by this group (in any order).
_EXPECTED_IDS = {
    "config_dir",
    "hooks_valid",
    "commands_parse",
    "layering",
    "git_present",
    "gh_present",
    "cli_integrity",
    "webglass",
    "web_search_provider",
}

_VALID_SEVERITIES = {"error", "warning", "info"}
_CHECK_KEYS = {"id", "passed", "severity", "message", "remediation"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _check_by_id(checks: list[dict], cid: str) -> dict:
    """Return the check with the given id, or raise KeyError if absent."""
    for c in checks:
        if c["id"] == cid:
            return c
    raise KeyError(f"no check with id={cid!r} in {[c['id'] for c in checks]}")


# ---------------------------------------------------------------------------
# Shape + contract invariants
# ---------------------------------------------------------------------------


def test_environment_checks_returns_list() -> None:
    result = env_mod.checks()
    assert isinstance(result, list)


def test_environment_checks_emits_expected_ids() -> None:
    result = env_mod.checks()
    ids = {c["id"] for c in result}
    assert _EXPECTED_IDS == ids, f"unexpected ids: {ids ^ _EXPECTED_IDS}"


def test_environment_checks_all_have_valid_shape() -> None:
    for check in env_mod.checks():
        assert set(check) == _CHECK_KEYS, check
        assert isinstance(check["passed"], bool)
        assert check["severity"] in _VALID_SEVERITIES
        assert isinstance(check["message"], str) and check["message"]
        assert isinstance(check["remediation"], str)
        if check["passed"]:
            assert check["remediation"] == "", f"passing check must have empty remediation: {check}"


def test_environment_checks_never_raises_on_bare_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Group must not raise even when run from an empty temp dir."""
    monkeypatch.chdir(tmp_path)
    result = env_mod.checks()  # must not raise
    assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Healthy baseline (run in the actual repo)
# ---------------------------------------------------------------------------


def test_git_present_passes_in_real_repo() -> None:
    """git is present on this machine; the check must pass."""
    assert shutil.which("git") is not None, "git not found; cannot run baseline test"
    checks = env_mod.checks()
    c = _check_by_id(checks, "git_present")
    assert c["passed"] is True
    assert c["severity"] == "error"
    assert c["remediation"] == ""


def test_cli_integrity_passes_in_real_repo() -> None:
    checks = env_mod.checks()
    c = _check_by_id(checks, "cli_integrity")
    assert c["passed"] is True
    assert c["severity"] == "error"
    assert c["remediation"] == ""


def test_no_error_severity_failures_in_real_repo() -> None:
    """A clean real-repo run must produce no failed error-severity checks."""
    checks = env_mod.checks()
    error_failures = [c for c in checks if c["severity"] == "error" and not c["passed"]]
    assert error_failures == [], f"unexpected error failures: {error_failures}"


# ---------------------------------------------------------------------------
# Malformed hooks.json → hooks_valid error
# ---------------------------------------------------------------------------


def test_hooks_valid_error_on_malformed_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A malformed hooks.json must produce a failed error check."""
    dot_conv = tmp_path / ".colleague"
    dot_conv.mkdir()
    (dot_conv / "hooks.json").write_text("{this is not json!!", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    checks = env_mod.checks()
    c = _check_by_id(checks, "hooks_valid")
    assert c["passed"] is False
    assert c["severity"] == "error"
    assert c["remediation"] != "", "malformed hooks.json must supply remediation"


def test_hooks_valid_error_makes_diagnose_unhealthy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """diagnose() must be unhealthy when hooks.json is malformed (error severity)."""
    dot_conv = tmp_path / ".colleague"
    dot_conv.mkdir()
    (dot_conv / "hooks.json").write_text("not json at all", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    report = diagnose()
    assert report["healthy"] is False
    hooks_check = _check_by_id(report["checks"], "hooks_valid")
    assert hooks_check["passed"] is False


def test_hooks_valid_passes_when_hooks_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When hooks.json is absent, hooks_valid is passed (config is optional)."""
    monkeypatch.chdir(tmp_path)
    checks = env_mod.checks()
    c = _check_by_id(checks, "hooks_valid")
    assert c["passed"] is True


def test_hooks_valid_passes_on_valid_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A valid hooks.json must produce a passing hooks_valid check."""
    dot_conv = tmp_path / ".colleague"
    dot_conv.mkdir()
    (dot_conv / "hooks.json").write_text('{"hooks": {}}', encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    checks = env_mod.checks()
    c = _check_by_id(checks, "hooks_valid")
    assert c["passed"] is True


# ---------------------------------------------------------------------------
# git absent → git_present error
# ---------------------------------------------------------------------------


def test_git_absent_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Monkeypatching which() so git returns None must produce a failed error check."""
    real_which = shutil.which

    def _which_no_git(name: str, *args, **kwargs):
        if name == "git":
            return None
        return real_which(name, *args, **kwargs)

    monkeypatch.setattr(shutil, "which", _which_no_git)
    checks = env_mod.checks()
    c = _check_by_id(checks, "git_present")
    assert c["passed"] is False
    assert c["severity"] == "error"
    assert c["remediation"] != ""


# ---------------------------------------------------------------------------
# gh absent → gh_present warning (health unaffected)
# ---------------------------------------------------------------------------


def test_gh_absent_warning_does_not_flip_health(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """gh absent → gh_present warning; diagnose() remains healthy if no other errors."""
    real_which = shutil.which

    def _which_no_gh(name: str, *args, **kwargs):
        if name == "gh":
            return None
        return real_which(name, *args, **kwargs)

    monkeypatch.setattr(shutil, "which", _which_no_gh)
    checks = env_mod.checks()
    c = _check_by_id(checks, "gh_present")
    assert c["passed"] is False
    assert c["severity"] == "warning"
    assert c["remediation"] != ""


def test_gh_absent_does_not_make_diagnose_unhealthy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """gh absent is a warning; it must not flip health on its own."""
    real_which = shutil.which

    def _which_no_gh(name: str, *args, **kwargs):
        if name == "gh":
            return None
        return real_which(name, *args, **kwargs)

    monkeypatch.setattr(shutil, "which", _which_no_gh)
    # Health must remain True (assuming git present and no other errors).
    if shutil.which("git") is None:
        pytest.skip("git not present; cannot isolate gh-only scenario")
    report = diagnose()
    # The report is healthy if the only warning-level failure is gh_present.
    gh_check = _check_by_id(report["checks"], "gh_present")
    assert gh_check["severity"] == "warning"  # never an error
    # Health depends on all checks; at minimum, this warning alone cannot flip it.
    error_failures = [c for c in report["checks"] if c["severity"] == "error" and not c["passed"]]
    assert error_failures == [], f"unexpected error failures while testing gh: {error_failures}"


# ---------------------------------------------------------------------------
# config_dir check (info, always passed)
# ---------------------------------------------------------------------------


def test_config_dir_info_passed_when_no_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    checks = env_mod.checks()
    c = _check_by_id(checks, "config_dir")
    assert c["passed"] is True
    assert c["severity"] == "info"


def test_config_dir_info_passed_when_config_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".colleague").mkdir()
    monkeypatch.chdir(tmp_path)
    checks = env_mod.checks()
    c = _check_by_id(checks, "config_dir")
    assert c["passed"] is True
    assert c["severity"] == "info"


# ---------------------------------------------------------------------------
# layering check (warning on failure, info on success)
# ---------------------------------------------------------------------------


def test_layering_info_passed_in_real_repo() -> None:
    checks = env_mod.checks()
    c = _check_by_id(checks, "layering")
    assert c["passed"] is True
    assert c["severity"] in ("info", "warning")


# ---------------------------------------------------------------------------
# commands_parse check
# ---------------------------------------------------------------------------


def test_commands_parse_passed_when_no_templates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    checks = env_mod.checks()
    c = _check_by_id(checks, "commands_parse")
    assert c["passed"] is True


def test_commands_parse_passed_with_valid_template(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cmd_dir = tmp_path / ".colleague" / "commands"
    cmd_dir.mkdir(parents=True)
    (cmd_dir / "hello.md").write_text("Hello $1!", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    checks = env_mod.checks()
    c = _check_by_id(checks, "commands_parse")
    assert c["passed"] is True


def test_commands_parse_error_on_unreadable_template(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A template that cannot be read (e.g. permission error) → failed check."""
    cmd_dir = tmp_path / ".colleague" / "commands"
    cmd_dir.mkdir(parents=True)
    bad_file = cmd_dir / "bad.md"
    bad_file.write_text("ok", encoding="utf-8")
    bad_file.chmod(0o000)  # make unreadable

    monkeypatch.chdir(tmp_path)
    try:
        checks = env_mod.checks()
        c = _check_by_id(checks, "commands_parse")
        # If we can't read the file, expect a failure
        # (skip if running as root where permissions don't apply)
        import os

        if os.getuid() == 0:
            pytest.skip("running as root; file permissions don't apply")
        assert c["passed"] is False
        assert c["remediation"] != ""
    finally:
        bad_file.chmod(0o644)  # restore so tmp_path cleanup works


# --- config_dir probe failure surfaces, not masked (PR #29 review, finding 4) -


def test_config_dir_probe_failure_surfaces_as_failed_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A config_roots() exception must become a failed check, not a passing info."""
    import colleague.configdir as configdir

    def _boom(_repo: Path) -> object:
        raise OSError("permission denied")

    monkeypatch.setattr(configdir, "config_roots", _boom)
    c = _check_by_id(env_mod.checks(), "config_dir")
    assert c["passed"] is False
    assert c["severity"] == "warning"  # config is optional → warning, not error
    assert c["remediation"] != ""


# ---------------------------------------------------------------------------
# webglass check (t6) — always WARN-only
# ---------------------------------------------------------------------------


def _status(*, present, healthy, detail="", sessions=None) -> dict:
    return {"present": present, "healthy": healthy, "detail": detail, "sessions": sessions}


def test_webglass_absent_warns_and_stays_exit_0(monkeypatch: pytest.MonkeyPatch) -> None:
    """webglass not on PATH → warning row; a bare doctor run still exits 0."""
    monkeypatch.setattr(
        livecheck,
        "webglass_status",
        lambda: _status(present=False, healthy=False, detail="webglass not on PATH"),
    )
    c = _check_by_id(env_mod.checks(), "webglass")
    assert c["passed"] is False
    assert c["severity"] == "warning"
    assert c["remediation"] != ""

    report = diagnose()
    assert report["healthy"] is True, "webglass warning must never flip health"
    args = argparse.Namespace(json=True, probe=False, repo=".")
    assert cmd_doctor(args) == 0


def test_webglass_unhealthy_warns(monkeypatch: pytest.MonkeyPatch) -> None:
    """webglass present but 'webglass doctor' unhealthy → warning row."""
    monkeypatch.setattr(
        livecheck,
        "webglass_status",
        lambda: _status(present=True, healthy=False, detail="exit 1"),
    )
    c = _check_by_id(env_mod.checks(), "webglass")
    assert c["passed"] is False
    assert c["severity"] == "warning"


def test_webglass_healthy_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """webglass healthy with <= threshold sessions → ok."""
    monkeypatch.setattr(
        livecheck,
        "webglass_status",
        lambda: _status(present=True, healthy=True, detail="webglass doctor exited 0", sessions=3),
    )
    c = _check_by_id(env_mod.checks(), "webglass")
    assert c["passed"] is True
    assert c["remediation"] == ""


def test_webglass_over_threshold_sessions_warns_with_count(monkeypatch: pytest.MonkeyPatch) -> None:
    """12 sessions (> 10) → warning row naming the count; exit code unaffected."""
    monkeypatch.setattr(
        livecheck,
        "webglass_status",
        lambda: _status(present=True, healthy=True, detail="webglass doctor exited 0", sessions=12),
    )
    c = _check_by_id(env_mod.checks(), "webglass")
    assert c["passed"] is False
    assert c["severity"] == "warning"
    assert "12" in c["message"]
    assert c["remediation"] != ""

    report = diagnose()
    assert report["healthy"] is True
    args = argparse.Namespace(json=True, probe=False, repo=".")
    assert cmd_doctor(args) == 0


def test_webglass_status_shells_out_via_livecheck() -> None:
    """The real (unmocked) resolver is :func:`colleague.livecheck.webglass_status`."""
    result = livecheck.webglass_status()
    assert set(result) == {"present", "healthy", "detail", "sessions"}


# ---------------------------------------------------------------------------
# web_search_provider check (t6) — always WARN-only; never prints the key
# ---------------------------------------------------------------------------


def test_web_search_provider_ok_when_key_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEBGLASS_BRAVE_API_KEY", "sekrit-value-do-not-print")
    c = _check_by_id(env_mod.checks(), "web_search_provider")
    assert c["passed"] is True
    assert c["remediation"] == ""
    assert "sekrit-value-do-not-print" not in c["message"]
    assert "sekrit-value-do-not-print" not in c["remediation"]


def test_web_search_provider_warns_when_key_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WEBGLASS_BRAVE_API_KEY", raising=False)
    c = _check_by_id(env_mod.checks(), "web_search_provider")
    assert c["passed"] is False
    assert c["severity"] == "warning"
    assert "unset in this process" in c["message"]
    assert c["remediation"] != ""


def test_web_search_provider_never_flips_health_or_exit_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("WEBGLASS_BRAVE_API_KEY", raising=False)
    report = diagnose()
    assert report["healthy"] is True
    args = argparse.Namespace(json=True, probe=False, repo=".")
    assert cmd_doctor(args) == 0


def test_webglass_key_never_printed_across_all_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    """No check message/remediation ever contains the raw key value (either row)."""
    secret = "super-secret-brave-key-xyz"
    monkeypatch.setenv("WEBGLASS_BRAVE_API_KEY", secret)
    monkeypatch.setattr(
        livecheck,
        "webglass_status",
        lambda: _status(present=True, healthy=True, detail="webglass doctor exited 0", sessions=1),
    )
    for c in env_mod.checks():
        assert secret not in c["message"]
        assert secret not in c["remediation"]
