"""Tests for the usage-readiness check-group (issue #53).

Scenarios:
* No CONVERTIBLE_ENGINE (fresh install) → effective engine resolves to the real
  ``vllm-openai``; ``usage_effective_engine`` is info/passed.
* CONVERTIBLE_ENGINE=mock → ``usage_effective_engine`` is a warning (not passed)
  with non-empty remediation, surfacing that a bare run drives the no-op mock.
* The group never emits severity="error", so a mock default never flips
  ``diagnose()`` unhealthy (the warning is advisory but visible).
* Contract compliance: five-key shape, unique ids, never raises.
"""

from __future__ import annotations

import pytest

from colleague.oilcheck import diagnose
from colleague.oilcheck.usage import checks


def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CONVERTIBLE_ENGINE", raising=False)


def _find(results: list[dict], check_id: str) -> dict | None:
    for c in results:
        if c["id"] == check_id:
            return c
    return None


# ---------------------------------------------------------------------------
# Scenario 1: fresh install → real engine, info/passed
# ---------------------------------------------------------------------------


def test_effective_engine_info_when_real(monkeypatch: pytest.MonkeyPatch) -> None:
    _clean_env(monkeypatch)
    c = _find(checks(), "usage_effective_engine")
    assert c is not None
    assert c["passed"] is True
    assert c["severity"] == "info"
    assert "vllm-openai" in c["message"]
    assert c["remediation"] == "", "passed checks carry empty remediation"


def test_effective_engine_info_when_explicit_real(monkeypatch: pytest.MonkeyPatch) -> None:
    _clean_env(monkeypatch)
    monkeypatch.setenv("CONVERTIBLE_ENGINE", "vllm-openai")
    c = _find(checks(), "usage_effective_engine")
    assert c is not None
    assert c["passed"] is True
    assert c["severity"] == "info"


# ---------------------------------------------------------------------------
# Scenario 2: mock configured → warning
# ---------------------------------------------------------------------------


def test_effective_engine_warns_when_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    _clean_env(monkeypatch)
    monkeypatch.setenv("CONVERTIBLE_ENGINE", "mock")
    c = _find(checks(), "usage_effective_engine")
    assert c is not None
    assert c["passed"] is False
    assert c["severity"] == "warning"
    assert "mock" in c["message"]
    assert c["remediation"], "failing checks must carry non-empty remediation"
    # The remediation must point at the fix.
    assert "CONVERTIBLE_ENGINE" in c["remediation"] or "--engine" in c["remediation"]


# ---------------------------------------------------------------------------
# Scenario 3: mock warning never flips diagnose() unhealthy
# ---------------------------------------------------------------------------


def test_mock_default_stays_healthy(monkeypatch: pytest.MonkeyPatch) -> None:
    _clean_env(monkeypatch)
    monkeypatch.setenv("CONVERTIBLE_ENGINE", "mock")
    report = diagnose()
    assert report["healthy"] is True, (
        "the mock-default warning is advisory and must not flip health; "
        f"failing checks: {[c for c in report['checks'] if not c['passed']]}"
    )
    # ...but it IS present and visible in the report.
    assert _find(report["checks"], "usage_effective_engine") is not None


def test_usage_group_never_emits_error(monkeypatch: pytest.MonkeyPatch) -> None:
    for engine in ["mock", "vllm-openai", "some-out-of-tree-engine"]:
        _clean_env(monkeypatch)
        monkeypatch.setenv("CONVERTIBLE_ENGINE", engine)
        for c in checks():
            assert c["severity"] != "error", f"usage group must not emit errors; got: {c}"


# ---------------------------------------------------------------------------
# Contract compliance
# ---------------------------------------------------------------------------


class TestCheckShape:
    _KEYS = {"id", "passed", "severity", "message", "remediation"}
    _SEVERITIES = {"error", "warning", "info"}

    def test_shape_and_uniqueness(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for engine in [None, "mock", "vllm-openai"]:
            _clean_env(monkeypatch)
            if engine is not None:
                monkeypatch.setenv("CONVERTIBLE_ENGINE", engine)
            result = checks()
            ids = [c["id"] for c in result]
            assert len(ids) == len(set(ids)), f"duplicate ids: {ids}"
            for c in result:
                assert set(c) == self._KEYS, f"bad shape: {c}"
                assert isinstance(c["id"], str) and c["id"]
                assert isinstance(c["passed"], bool)
                assert c["severity"] in self._SEVERITIES
                if c["passed"]:
                    assert c["remediation"] == ""

    def test_checks_never_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _clean_env(monkeypatch)
        monkeypatch.setenv("CONVERTIBLE_ENGINE", "")
        try:
            result = checks()
        except Exception as exc:  # pragma: no cover
            pytest.fail(f"checks() raised unexpectedly: {exc}")
        assert isinstance(result, list)
