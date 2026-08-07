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

from colleague.oilcheck import diagnose
from colleague.oilcheck.reachability import checks


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


class _RawResponse:
    """Response whose body is arbitrary (possibly non-JSON) bytes."""

    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self) -> "_RawResponse":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def read(self) -> bytes:
        return self.body


def _ok(*_args: object, **_kwargs: object) -> _FakeResponse:
    return _FakeResponse(
        {
            "object": "list",
            "data": [{"id": "unsloth/Qwen3.6-27B-NVFP4"}],
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
    assert "unsloth/Qwen3.6-27B-NVFP4" in c["message"]
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
# provider_model_available: match / empty / unparseable / partial config
#
# The configured model id is resolved via EngineConfig (explicit > COLLEAGUE_* >
# CONVERTIBLE_* > OPENAI_* > default), so these tests set COLLEAGUE_MODEL /
# COLLEAGUE_BASE_URL to stay independent of the rig's defaults.
# ---------------------------------------------------------------------------


def test_model_available_passes_when_served(monkeypatch: pytest.MonkeyPatch) -> None:
    """Happy path: the configured model IS in the served list → info/passed."""
    monkeypatch.setenv("COLLEAGUE_MODEL", "served/model")
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_a, **_k: _FakeResponse({"object": "list", "data": [{"id": "served/model"}]}),
    )
    c = _find(checks(), "provider_model_available")
    assert c is not None
    assert c["passed"] is True
    assert c["severity"] == "info"
    assert "served/model" in c["message"]
    assert c["remediation"] == "", "a passing check carries empty remediation"


@pytest.mark.parametrize(
    "payload",
    [
        {"object": "list", "data": []},  # reachable, but nothing served
        {"object": "list", "data": [{"name": "m"}]},  # entries without an "id" key
    ],
    ids=["empty-list", "entries-without-id"],
)
def test_model_available_warns_when_nothing_served(
    monkeypatch: pytest.MonkeyPatch, payload: dict
) -> None:
    """Reachable but the served set is empty → warning naming '(none)'."""
    monkeypatch.setenv("COLLEAGUE_MODEL", "wanted/model")
    monkeypatch.setattr("urllib.request.urlopen", lambda *_a, **_k: _FakeResponse(payload))
    c = _find(checks(), "provider_model_available")
    assert c is not None
    assert c["passed"] is False
    assert c["severity"] == "warning"
    assert "wanted/model" in c["message"]
    assert "(none)" in c["message"]
    assert c["remediation"]


@pytest.mark.parametrize(
    "make_response",
    [
        lambda: _RawResponse(b"<html>not json</html>"),  # body is not JSON
        lambda: _FakeResponse({"object": "list", "data": "not-a-list"}),  # data not a list
        lambda: _FakeResponse({"object": "list"}),  # no data key at all
    ],
    ids=["non-json", "data-not-list", "no-data-key"],
)
def test_model_available_omitted_when_list_unparseable(
    monkeypatch: pytest.MonkeyPatch, make_response
) -> None:
    """Unparseable /models body → omit the model verdict ('we cannot tell, say
    nothing'), but the server DID respond so reachability still passes."""
    monkeypatch.setattr("urllib.request.urlopen", lambda *_a, **_k: make_response())
    results = checks()
    assert _find(results, "provider_model_available") is None
    reachable = _find(results, "provider_reachable")
    assert reachable is not None and reachable["passed"] is True


def test_probe_targets_resolved_url_with_partial_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Partial config (only base_url overridden) → the probe targets the resolved
    {base_url}/models and the default model is still compared."""
    monkeypatch.setenv("COLLEAGUE_BASE_URL", "http://example.test:1234/v1")
    monkeypatch.delenv("COLLEAGUE_MODEL", raising=False)
    monkeypatch.delenv("CONVERTIBLE_MODEL", raising=False)
    captured: dict[str, str] = {}

    def _capture(request: object, *_a: object, **_k: object) -> _FakeResponse:
        captured["url"] = getattr(request, "full_url", request)  # urllib.request.Request
        return _FakeResponse({"object": "list", "data": []})

    monkeypatch.setattr("urllib.request.urlopen", _capture)
    results = checks()
    assert captured["url"] == "http://example.test:1234/v1/models"
    assert _find(results, "provider_reachable")["passed"] is True
    # The default model was resolved and compared even with only base_url set.
    assert _find(results, "provider_model_available") is not None


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
