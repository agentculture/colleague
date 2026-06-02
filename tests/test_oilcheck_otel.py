"""Tests for the oilcheck otel check-group (GPS / OpenTelemetry readiness).

TDD-first: these tests are written against the spec in
``colleague/oilcheck/otel.py``'s module docstring.  They cover:

* Default env (telemetry off) — no error checks; otel_enabled info says
  disabled; diagnose() stays healthy.
* Enabled with SDK importable (the [otel] extra IS installed in dev) —
  otel_sdk passes.
* Enabled but SDK missing — simulate via monkeypatching; otel_sdk is an
  error with non-empty remediation, and diagnose() reports healthy=False.

The zero-deps constraint is tested separately in tests/test_zero_deps.py.
"""

from __future__ import annotations

import pytest

from colleague.oilcheck import diagnose
from colleague.oilcheck import otel as otel_group

_CHECK_KEYS = {"id", "passed", "severity", "message", "remediation"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _by_id(checks: list[dict], check_id: str) -> dict | None:
    """Return the first check with the given id, or None."""
    return next((c for c in checks if c["id"] == check_id), None)


# ---------------------------------------------------------------------------
# Shape contract
# ---------------------------------------------------------------------------


def test_checks_returns_list() -> None:
    result = otel_group.checks()
    assert isinstance(result, list)


def test_every_check_has_five_keys() -> None:
    for check in otel_group.checks():
        assert set(check) == _CHECK_KEYS, check


def test_passing_checks_have_empty_remediation() -> None:
    for check in otel_group.checks():
        if check["passed"]:
            assert check["remediation"] == ""


# ---------------------------------------------------------------------------
# Default environment: CONVERTIBLE_OTEL_ENABLED not set (telemetry off)
# ---------------------------------------------------------------------------


def test_default_no_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """With telemetry off, the group must not emit any error check."""
    monkeypatch.delenv("CONVERTIBLE_OTEL_ENABLED", raising=False)
    monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)
    checks = otel_group.checks()
    errors = [c for c in checks if c["severity"] == "error" and not c["passed"]]
    assert errors == [], f"unexpected errors: {errors}"


def test_otel_enabled_check_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """otel_enabled info check is emitted."""
    monkeypatch.delenv("CONVERTIBLE_OTEL_ENABLED", raising=False)
    checks = otel_group.checks()
    enabled_check = _by_id(checks, "otel_enabled")
    assert enabled_check is not None, "otel_enabled check missing"
    assert enabled_check["severity"] == "info"


def test_otel_enabled_reports_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """When CONVERTIBLE_OTEL_ENABLED is absent, otel_enabled says disabled."""
    monkeypatch.delenv("CONVERTIBLE_OTEL_ENABLED", raising=False)
    monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)
    enabled_check = _by_id(otel_group.checks(), "otel_enabled")
    assert enabled_check is not None
    # passed=True (it's an info observation), message should convey "disabled"
    assert enabled_check["passed"] is True
    assert (
        "disabled" in enabled_check["message"].lower() or "off" in enabled_check["message"].lower()
    )


def test_diagnose_healthy_when_otel_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """diagnose() stays healthy when telemetry is off."""
    monkeypatch.delenv("CONVERTIBLE_OTEL_ENABLED", raising=False)
    monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)
    report = diagnose()
    assert report["healthy"] is True


# ---------------------------------------------------------------------------
# Enabled with SDK importable (happy path)
# ---------------------------------------------------------------------------


def test_otel_sdk_passes_when_enabled_and_importable(monkeypatch: pytest.MonkeyPatch) -> None:
    """When CONVERTIBLE_OTEL_ENABLED=1 and [otel] extra is installed, otel_sdk passes."""
    monkeypatch.setenv("CONVERTIBLE_OTEL_ENABLED", "1")
    monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)
    # The [otel] extra IS installed in dev — sdk_available() should return True.
    from colleague.telemetry import sdk_available

    if not sdk_available():
        pytest.skip("opentelemetry SDK not installed — skipping happy-path test")
    checks = otel_group.checks()
    sdk_check = _by_id(checks, "otel_sdk")
    assert sdk_check is not None, "otel_sdk check missing"
    assert sdk_check["passed"] is True, f"otel_sdk should pass: {sdk_check}"
    assert sdk_check["severity"] == "info"
    assert sdk_check["remediation"] == ""


def test_otel_enabled_reports_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """When CONVERTIBLE_OTEL_ENABLED=1, otel_enabled message reflects that."""
    monkeypatch.setenv("CONVERTIBLE_OTEL_ENABLED", "1")
    monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)
    enabled_check = _by_id(otel_group.checks(), "otel_enabled")
    assert enabled_check is not None
    assert enabled_check["passed"] is True
    msg = enabled_check["message"].lower()
    assert "enabled" in msg or "on" in msg


# ---------------------------------------------------------------------------
# Enabled but SDK missing → error
# ---------------------------------------------------------------------------


def test_otel_sdk_error_when_enabled_and_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """When telemetry is enabled but the SDK is not importable, emit an error."""
    monkeypatch.setenv("CONVERTIBLE_OTEL_ENABLED", "1")
    monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)

    # Simulate missing SDK by making sdk_available() return False.
    import colleague.telemetry as tel_pkg

    monkeypatch.setattr(tel_pkg, "sdk_available", lambda: False)

    checks = otel_group.checks()
    sdk_check = _by_id(checks, "otel_sdk")
    assert sdk_check is not None, "otel_sdk check missing"
    assert sdk_check["passed"] is False
    assert sdk_check["severity"] == "error"
    assert sdk_check["remediation"] != "", "remediation must be non-empty for a failing error"
    # Remediation should mention how to install the extra.
    assert (
        "otel" in sdk_check["remediation"].lower() or "install" in sdk_check["remediation"].lower()
    )


def test_diagnose_unhealthy_when_enabled_sdk_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """diagnose() reports healthy=False when enabled+SDK-missing error fires."""
    monkeypatch.setenv("CONVERTIBLE_OTEL_ENABLED", "1")
    monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)

    import colleague.telemetry as tel_pkg

    monkeypatch.setattr(tel_pkg, "sdk_available", lambda: False)

    report = diagnose()
    assert report["healthy"] is False


# ---------------------------------------------------------------------------
# otel_endpoint advisory check
# ---------------------------------------------------------------------------


def test_otel_endpoint_check_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """otel_endpoint info check is always emitted."""
    monkeypatch.delenv("CONVERTIBLE_OTEL_ENABLED", raising=False)
    checks = otel_group.checks()
    endpoint_check = _by_id(checks, "otel_endpoint")
    assert endpoint_check is not None, "otel_endpoint check missing"
    assert endpoint_check["severity"] == "info"


def test_otel_endpoint_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """When OTEL_EXPORTER_OTLP_ENDPOINT is set, otel_endpoint reflects it."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://my-collector:4318")
    monkeypatch.delenv("CONVERTIBLE_OTEL_ENABLED", raising=False)
    endpoint_check = _by_id(otel_group.checks(), "otel_endpoint")
    assert endpoint_check is not None
    assert endpoint_check["passed"] is True
    assert (
        "http://my-collector:4318" in endpoint_check["message"]
        or "set" in endpoint_check["message"].lower()
    )


def test_otel_endpoint_when_not_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """When OTEL_EXPORTER_OTLP_ENDPOINT is absent, otel_endpoint still passes (advisory)."""
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("CONVERTIBLE_OTEL_ENABLED", raising=False)
    endpoint_check = _by_id(otel_group.checks(), "otel_endpoint")
    assert endpoint_check is not None
    assert endpoint_check["severity"] == "info"
    # It's advisory — still passes even when unset.
    assert endpoint_check["passed"] is True


# ---------------------------------------------------------------------------
# SDK missing + telemetry DISABLED → no error (only info)
# ---------------------------------------------------------------------------


def test_no_error_when_sdk_missing_but_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """If telemetry is off, a missing SDK is NOT an error."""
    monkeypatch.delenv("CONVERTIBLE_OTEL_ENABLED", raising=False)
    monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)

    import colleague.telemetry as tel_pkg

    monkeypatch.setattr(tel_pkg, "sdk_available", lambda: False)

    checks = otel_group.checks()
    errors = [c for c in checks if c["severity"] == "error" and not c["passed"]]
    assert errors == [], f"should be no errors when disabled: {errors}"

    sdk_check = _by_id(checks, "otel_sdk")
    assert sdk_check is not None
    assert sdk_check["passed"] is True  # advisory / info when disabled
    assert sdk_check["severity"] == "info"


# ---------------------------------------------------------------------------
# OTEL_SDK_DISABLED kill-switch messaging (PR #29 review, finding 6)
# ---------------------------------------------------------------------------


def test_kill_switch_message_mentions_otel_sdk_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # OTEL_SDK_DISABLED forces telemetry off even with CONVERTIBLE_OTEL_ENABLED=1,
    # so the disabled message must not advise re-setting CONVERTIBLE_OTEL_ENABLED.
    monkeypatch.setenv("CONVERTIBLE_OTEL_ENABLED", "1")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    enabled = _by_id(otel_group.checks(), "otel_enabled")
    assert enabled is not None
    assert "OTEL_SDK_DISABLED" in enabled["message"]


# ---------------------------------------------------------------------------
# OTLP endpoint credential redaction (PR #29 review, security suggestion)
# ---------------------------------------------------------------------------


def test_endpoint_credentials_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CONVERTIBLE_OTEL_ENDPOINT", raising=False)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://user:s3cret@otlp.example.com:4318")
    endpoint = _by_id(otel_group.checks(), "otel_endpoint")
    assert endpoint is not None
    assert "s3cret" not in endpoint["message"]  # password stripped
    assert "user:" not in endpoint["message"]  # userinfo stripped
    assert "otlp.example.com" in endpoint["message"]  # host still reported
