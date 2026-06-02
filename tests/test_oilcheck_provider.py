"""Tests for the provider check-group (TDD, written before implementation).

Scenarios:
* Default rig (no provider env vars) → ``provider_config`` info emitted with
  default base_url; no ``provider_credentials`` or ``provider_budget`` failures;
  the resolved api_key string never appears in any check message.
* Non-default base_url + default/empty api_key + no CONVERTIBLE_BUDGET →
  both ``provider_credentials`` and ``provider_budget`` warnings fire, each with
  severity "warning" and non-empty remediation.
* Non-default base_url + CONVERTIBLE_API_KEY set + CONVERTIBLE_BUDGET set →
  neither warning fires.
* Sanity: feeding provider checks through ``diagnose()`` keeps healthy=True
  (warnings never flip health).
"""

from __future__ import annotations

import pytest

from colleague.config import _DEFAULT_API_KEY, _DEFAULT_BASE_URL
from colleague.oilcheck import diagnose
from colleague.oilcheck.provider import checks

_THIRD_PARTY_URL = "https://api.thirdparty.com/v1"
_REAL_KEY = "sk-real-secret-key-abc123"
_BUDGET_VAL = "50"

_PROVIDER_ENV_KEYS = (
    "CONVERTIBLE_BASE_URL",
    "OPENAI_BASE_URL",
    "CONVERTIBLE_API_KEY",
    "OPENAI_API_KEY",
    "CONVERTIBLE_MODEL",
    "CONVERTIBLE_BUDGET",
)


def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove all provider-related env vars so tests start from a clean slate."""
    for key in _PROVIDER_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find(results: list[dict], check_id: str) -> dict | None:
    for c in results:
        if c["id"] == check_id:
            return c
    return None


def _ids(results: list[dict]) -> list[str]:
    return [c["id"] for c in results]


# ---------------------------------------------------------------------------
# Scenario 1: default rig (no env vars)
# ---------------------------------------------------------------------------


class TestDefaultRig:
    def test_provider_config_info_present(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _clean_env(monkeypatch)
        result = checks()
        c = _find(result, "provider_config")
        assert c is not None, f"provider_config missing; got ids: {_ids(result)}"
        assert c["passed"] is True
        assert c["severity"] == "info"

    def test_provider_config_contains_default_base_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clean_env(monkeypatch)
        result = checks()
        c = _find(result, "provider_config")
        assert c is not None
        assert _DEFAULT_BASE_URL in c["message"]

    def test_provider_config_has_empty_remediation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _clean_env(monkeypatch)
        c = _find(checks(), "provider_config")
        assert c is not None
        assert c["remediation"] == "", "passed checks must carry empty remediation"

    def test_no_credentials_warning_on_default_rig(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Local vLLM needs no key — provider_credentials must be silent or passed."""
        _clean_env(monkeypatch)
        result = checks()
        cred = _find(result, "provider_credentials")
        # Either absent or passed — must not be a failing check.
        if cred is not None:
            assert cred["passed"] is True, "provider_credentials must not fail on default rig"

    def test_no_budget_warning_on_default_rig(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Local rig has no cost — provider_budget must be silent or passed."""
        _clean_env(monkeypatch)
        result = checks()
        budget = _find(result, "provider_budget")
        if budget is not None:
            assert budget["passed"] is True, "provider_budget must not fail on default rig"

    def test_api_key_never_appears_in_any_message(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The default api_key 'EMPTY' must not be leaked into check messages."""
        _clean_env(monkeypatch)
        result = checks()
        for c in result:
            assert (
                _DEFAULT_API_KEY not in c["message"]
            ), f"api_key '{_DEFAULT_API_KEY}' leaked into check {c['id']!r}: {c['message']!r}"


# ---------------------------------------------------------------------------
# Scenario 2: non-default base_url, default key, no budget
# ---------------------------------------------------------------------------


class TestThirdPartyNoKey:
    def setup_method(self, _method):
        self._url = _THIRD_PARTY_URL

    def test_provider_credentials_fires_as_warning(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _clean_env(monkeypatch)
        monkeypatch.setenv("CONVERTIBLE_BASE_URL", self._url)
        result = checks()
        cred = _find(result, "provider_credentials")
        assert cred is not None, f"provider_credentials missing; ids: {_ids(result)}"
        assert cred["passed"] is False
        assert cred["severity"] == "warning"

    def test_provider_credentials_has_non_empty_remediation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clean_env(monkeypatch)
        monkeypatch.setenv("CONVERTIBLE_BASE_URL", self._url)
        cred = _find(checks(), "provider_credentials")
        assert cred is not None
        assert cred["remediation"], "remediation must be non-empty when check fails"

    def test_provider_budget_fires_as_warning(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _clean_env(monkeypatch)
        monkeypatch.setenv("CONVERTIBLE_BASE_URL", self._url)
        result = checks()
        budget = _find(result, "provider_budget")
        assert budget is not None, f"provider_budget missing; ids: {_ids(result)}"
        assert budget["passed"] is False
        assert budget["severity"] == "warning"

    def test_provider_budget_has_non_empty_remediation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clean_env(monkeypatch)
        monkeypatch.setenv("CONVERTIBLE_BASE_URL", self._url)
        budget = _find(checks(), "provider_budget")
        assert budget is not None
        assert budget["remediation"], "remediation must be non-empty when check fails"

    def test_real_key_never_in_messages(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Even when the user sets a real key it must not appear in any message."""
        _clean_env(monkeypatch)
        monkeypatch.setenv("CONVERTIBLE_BASE_URL", self._url)
        monkeypatch.setenv("CONVERTIBLE_API_KEY", _REAL_KEY)
        result = checks()
        for c in result:
            assert (
                _REAL_KEY not in c["message"]
            ), f"api_key leaked into check {c['id']!r}: {c['message']!r}"


# ---------------------------------------------------------------------------
# Scenario 3: non-default base_url + key set + budget set → no warnings
# ---------------------------------------------------------------------------


class TestThirdPartyConfigured:
    def test_no_credentials_warning_when_key_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _clean_env(monkeypatch)
        monkeypatch.setenv("CONVERTIBLE_BASE_URL", _THIRD_PARTY_URL)
        monkeypatch.setenv("CONVERTIBLE_API_KEY", _REAL_KEY)
        monkeypatch.setenv("CONVERTIBLE_BUDGET", _BUDGET_VAL)
        result = checks()
        cred = _find(result, "provider_credentials")
        # Must be absent or passed.
        if cred is not None:
            assert (
                cred["passed"] is True
            ), "provider_credentials should not fail when api_key is explicitly set"

    def test_no_budget_warning_when_budget_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _clean_env(monkeypatch)
        monkeypatch.setenv("CONVERTIBLE_BASE_URL", _THIRD_PARTY_URL)
        monkeypatch.setenv("CONVERTIBLE_API_KEY", _REAL_KEY)
        monkeypatch.setenv("CONVERTIBLE_BUDGET", _BUDGET_VAL)
        result = checks()
        budget = _find(result, "provider_budget")
        if budget is not None:
            assert (
                budget["passed"] is True
            ), "provider_budget should not fail when CONVERTIBLE_BUDGET is set"

    def test_provider_config_info_still_present_with_third_party(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clean_env(monkeypatch)
        monkeypatch.setenv("CONVERTIBLE_BASE_URL", _THIRD_PARTY_URL)
        monkeypatch.setenv("CONVERTIBLE_API_KEY", _REAL_KEY)
        monkeypatch.setenv("CONVERTIBLE_BUDGET", _BUDGET_VAL)
        result = checks()
        c = _find(result, "provider_config")
        assert c is not None
        assert c["passed"] is True
        assert _THIRD_PARTY_URL in c["message"]


# ---------------------------------------------------------------------------
# Scenario 4: sanity — warnings never flip healthy
# ---------------------------------------------------------------------------


class TestWarningsDoNotFlipHealth:
    def test_third_party_no_key_still_healthy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Both provider warnings fire but diagnose() must still be healthy."""
        _clean_env(monkeypatch)
        monkeypatch.setenv("CONVERTIBLE_BASE_URL", _THIRD_PARTY_URL)
        # No api_key, no budget — worst case for this group.
        report = diagnose()
        assert report["healthy"] is True, (
            "provider warnings must not flip healthy; "
            f"failing checks: {[c for c in report['checks'] if not c['passed']]}"
        )

    def test_default_rig_is_healthy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _clean_env(monkeypatch)
        report = diagnose()
        assert report["healthy"] is True


# ---------------------------------------------------------------------------
# Contract compliance: every check returned has the five-key shape
# ---------------------------------------------------------------------------


class TestCheckShape:
    _KEYS = {"id", "passed", "severity", "message", "remediation"}
    _SEVERITIES = {"error", "warning", "info"}

    def test_all_checks_have_correct_shape(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for env_setup in [
            {},
            {"CONVERTIBLE_BASE_URL": _THIRD_PARTY_URL},
            {
                "CONVERTIBLE_BASE_URL": _THIRD_PARTY_URL,
                "CONVERTIBLE_API_KEY": _REAL_KEY,
                "CONVERTIBLE_BUDGET": _BUDGET_VAL,
            },
        ]:
            _clean_env(monkeypatch)
            for k, v in env_setup.items():
                monkeypatch.setenv(k, v)
            result = checks()
            for c in result:
                assert set(c) == self._KEYS, f"bad shape: {c}"
                assert isinstance(c["id"], str) and c["id"]
                assert isinstance(c["passed"], bool)
                assert c["severity"] in self._SEVERITIES
                assert isinstance(c["message"], str)
                assert isinstance(c["remediation"], str)
                if c["passed"]:
                    assert (
                        c["remediation"] == ""
                    ), f"passed check {c['id']!r} must have empty remediation"

    def test_no_errors_in_provider_group(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The provider group must never emit severity='error'."""
        for env_setup in [
            {},
            {"CONVERTIBLE_BASE_URL": _THIRD_PARTY_URL},
            {
                "CONVERTIBLE_BASE_URL": _THIRD_PARTY_URL,
                "CONVERTIBLE_API_KEY": _REAL_KEY,
                "CONVERTIBLE_BUDGET": _BUDGET_VAL,
            },
        ]:
            _clean_env(monkeypatch)
            for k, v in env_setup.items():
                monkeypatch.setenv(k, v)
            result = checks()
            for c in result:
                assert c["severity"] != "error", f"provider group must not emit errors; got: {c}"

    def test_check_ids_unique_within_group(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _clean_env(monkeypatch)
        monkeypatch.setenv("CONVERTIBLE_BASE_URL", _THIRD_PARTY_URL)
        result = checks()
        ids = [c["id"] for c in result]
        assert len(ids) == len(set(ids)), f"duplicate ids in provider group: {ids}"

    def test_checks_never_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """checks() must not raise under any circumstance."""
        _clean_env(monkeypatch)
        # Corrupt the env deliberately with an unusual value
        monkeypatch.setenv("CONVERTIBLE_BASE_URL", "not-a-real-url-at-all")
        try:
            result = checks()
        except Exception as exc:
            pytest.fail(f"checks() raised unexpectedly: {exc}")
        assert isinstance(result, list)
