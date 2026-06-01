"""Tests for the opt-in provider-reachability probe (issue #53, doctor --probe).

The probe is the deliberate exception to the "no network" check-group rule, so
these tests monkeypatch ``urllib.request.urlopen`` for determinism (no live
server required). Scenarios:

* urlopen succeeds → ``provider_reachable`` info/passed.
* urlopen raises HTTPError (server responded 401/404) → still reachable (info).
* urlopen raises URLError / OSError (refused / timeout) → warning, not error.
* The probe never flips ``diagnose(probe=True)`` unhealthy (warning is advisory).
* ``diagnose()`` (default) does NOT include the probe; ``diagnose(probe=True)`` does.
* Contract compliance: five-key shape, never raises.
"""

from __future__ import annotations

import json
import urllib.error

import pytest

from convertible.oilcheck import diagnose
from convertible.oilcheck.reachability import checks


class _FakeResponse:
    """Minimal context-manager stand-in for an HTTP response."""

    def __init__(self, payload: dict | None = None) -> None:
        self.payload = payload or {"object": "list", "data": []}

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def _ok(*_args: object, **_kwargs: object) -> _FakeResponse:
    return _FakeResponse(
        {
            "object": "list",
            "data": [{"id": "sakamakismile/Qwen3.6-27B-Text-NVFP4-MTP"}],
        }
    )


def _missing_model(*_args: object, **_kwargs: object) -> _FakeResponse:
    return _FakeResponse({"object": "list", "data": [{"id": "other/model"}]})


def _refused(*_args: object, **_kwargs: object) -> _FakeResponse:
    raise urllib.error.URLError("Connection refused")


def _http_error(*_args: object, **_kwargs: object) -> _FakeResponse:
    raise urllib.error.HTTPError(
        "http://localhost:8001/v1/models", 404, "Not Found", {}, None  # type: ignore[arg-type]
    )


def _timeout(*_args: object, **_kwargs: object) -> _FakeResponse:
    raise TimeoutError("timed out")


def _find(results: list[dict], check_id: str) -> dict | None:
    for c in results:
        if c["id"] == check_id:
            return c
    return None


# ---------------------------------------------------------------------------
# Reachable
# ---------------------------------------------------------------------------


def test_reachable_when_urlopen_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("urllib.request.urlopen", _ok)
    c = _find(checks(), "provider_reachable")
    assert c is not None
    assert c["passed"] is True
    assert c["severity"] == "info"
    assert c["remediation"] == ""


def test_probe_warns_when_configured_model_is_not_served(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("urllib.request.urlopen", _missing_model)
    c = _find(checks(), "provider_model_available")
    assert c is not None
    assert c["passed"] is False
    assert c["severity"] == "warning"
    assert "sakamakismile/Qwen3.6-27B-Text-NVFP4-MTP" in c["message"]
    assert "other/model" in c["message"]
    assert c["remediation"]


def test_reachable_when_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 401/404 means the server responded — it is up, just not at /models."""
    monkeypatch.setattr("urllib.request.urlopen", _http_error)
    c = _find(checks(), "provider_reachable")
    assert c is not None
    assert c["passed"] is True
    assert c["severity"] == "info"


# ---------------------------------------------------------------------------
# Unreachable → warning (never error)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fake", [_refused, _timeout])
def test_unreachable_is_warning(monkeypatch: pytest.MonkeyPatch, fake) -> None:
    monkeypatch.setattr("urllib.request.urlopen", fake)
    c = _find(checks(), "provider_reachable")
    assert c is not None
    assert c["passed"] is False
    assert c["severity"] == "warning", "unreachable is advisory, never an error"
    assert c["remediation"], "failing checks must carry non-empty remediation"


def test_unreachable_never_flips_health(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("urllib.request.urlopen", _refused)
    report = diagnose(probe=True)
    assert report["healthy"] is True, "an unreachable provider must not flip doctor unhealthy"
    assert _find(report["checks"], "provider_reachable") is not None


# ---------------------------------------------------------------------------
# Probe is opt-in: only present with probe=True
# ---------------------------------------------------------------------------


def test_diagnose_default_excludes_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    # No monkeypatch needed: the probe must NOT run, so no network call happens.
    report = diagnose()
    assert _find(report["checks"], "provider_reachable") is None


def test_diagnose_probe_includes_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("urllib.request.urlopen", _ok)
    report = diagnose(probe=True)
    assert _find(report["checks"], "provider_reachable") is not None


# ---------------------------------------------------------------------------
# Contract compliance
# ---------------------------------------------------------------------------


class TestCheckShape:
    _KEYS = {"id", "passed", "severity", "message", "remediation"}
    _SEVERITIES = {"error", "warning", "info"}

    @pytest.mark.parametrize("fake", [_ok, _refused, _http_error, _timeout])
    def test_shape(self, monkeypatch: pytest.MonkeyPatch, fake) -> None:
        monkeypatch.setattr("urllib.request.urlopen", fake)
        for c in checks():
            assert set(c) == self._KEYS, f"bad shape: {c}"
            assert c["severity"] in self._SEVERITIES
            assert c["severity"] != "error", "reachability never emits error"
            if c["passed"]:
                assert c["remediation"] == ""

    def test_checks_never_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _boom(*_a: object, **_k: object) -> _FakeResponse:
            raise RuntimeError("unexpected")

        monkeypatch.setattr("urllib.request.urlopen", _boom)
        try:
            result = checks()
        except Exception as exc:  # pragma: no cover
            pytest.fail(f"checks() raised unexpectedly: {exc}")
        assert isinstance(result, list)
