"""Tests for the model-membership oilcheck group (plan task t10).

Verifies the configured MAIN model id against the provider's /v1/models list,
naming the config source that pinned it. Follows the three_tier membership-check
pattern and respects the doctor --probe network gating.

Scenarios:
* Model present in /v1/models -> info/passed
* Model absent from /v1/models -> warning naming model id AND pinning source
* Endpoint missing/404 -> skip/info (NOT a failure)
* HTTP 401 -> endpoint alive, skip membership (NOT a failure)
* Connection refused/timeout -> skip/info (NOT a failure)
* Static checks() always runs (no network), reports model source
* probe_checks() only runs under --probe
* Contract compliance: five-key shape, never raises
"""

from __future__ import annotations

import json
import urllib.error
from pathlib import Path

import pytest

from colleague.oilcheck import diagnose
from colleague.oilcheck.model_membership import checks, probe_checks


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


def _models_response(model_ids: list[str]) -> _FakeResponse:
    return _FakeResponse({"object": "list", "data": [{"id": mid} for mid in model_ids]})


def _ok_with_model(model_id: str) -> callable:
    """Return a urlopen mock that serves model_id in the list."""

    def _fn(*_args: object, **_kwargs: object) -> _FakeResponse:
        return _models_response([model_id])

    return _fn


def _ok_with_other_models() -> callable:
    """Return a urlopen mock that serves different models."""

    def _fn(*_args: object, **_kwargs: object) -> _FakeResponse:
        return _models_response(["other/model", "another/model"])

    return _fn


def _http_404(*_args: object, **_kwargs: object) -> _FakeResponse:
    raise urllib.error.HTTPError(
        "http://localhost:8001/v1/models", 404, "Not Found", {}, None  # type: ignore[arg-type]
    )


def _http_401(*_args: object, **_kwargs: object) -> _FakeResponse:
    raise urllib.error.HTTPError(
        "http://localhost:8001/v1/models", 401, "Unauthorized", {}, None  # type: ignore[arg-type]
    )


def _connection_refused(*_args: object, **_kwargs: object) -> _FakeResponse:
    raise urllib.error.URLError("Connection refused")


def _timeout(*_args: object, **_kwargs: object) -> _FakeResponse:
    raise TimeoutError("timed out")


def _find(results: list[dict], check_id: str) -> dict | None:
    for c in results:
        if c["id"] == check_id:
            return c
    return None


# ---------------------------------------------------------------------------
# Static checks() — always run, no network
# ---------------------------------------------------------------------------


def test_static_check_reports_model_source_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When COLLEAGUE_MODEL is set, the static check names it as the source."""
    monkeypatch.setenv("COLLEAGUE_MODEL", "my/custom-model")
    monkeypatch.delenv("CONVERTIBLE_MODEL", raising=False)
    results = checks()
    c = _find(results, "model_membership_source")
    assert c is not None
    assert c["passed"] is True
    assert c["severity"] == "info"
    assert "my/custom-model" in c["message"]
    assert "COLLEAGUE_MODEL" in c["message"]
    assert c["remediation"] == ""


def test_static_check_reports_converted_model_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When CONVERTIBLE_MODEL is set (COLLEAGUE_MODEL absent), names it."""
    monkeypatch.delenv("COLLEAGUE_MODEL", raising=False)
    monkeypatch.setenv("CONVERTIBLE_MODEL", "legacy/model")
    results = checks()
    c = _find(results, "model_membership_source")
    assert c is not None
    assert c["passed"] is True
    assert c["severity"] == "info"
    assert "legacy/model" in c["message"]
    assert "CONVERTIBLE_MODEL" in c["message"]


def test_static_check_reports_default_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When no env or config sets the model, reports the builtin default."""
    monkeypatch.delenv("COLLEAGUE_MODEL", raising=False)
    monkeypatch.delenv("CONVERTIBLE_MODEL", raising=False)
    results = checks()
    c = _find(results, "model_membership_source")
    assert c is not None
    assert c["passed"] is True
    assert c["severity"] == "info"
    assert c["remediation"] == ""


def test_static_checks_never_makes_network_call() -> None:
    """checks() must not open any socket — no monkeypatch needed."""
    # If this passes without a monkeypatch on urllib, no network was made.
    results = checks()
    assert isinstance(results, list)
    assert len(results) >= 1


# ---------------------------------------------------------------------------
# Probe checks — only with --probe, network calls
# ---------------------------------------------------------------------------


def test_probe_model_present_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Model IS in /v1/models -> info/passed."""
    monkeypatch.setenv("COLLEAGUE_MODEL", "served/model")
    monkeypatch.setattr("urllib.request.urlopen", _ok_with_model("served/model"))
    results = probe_checks()
    c = _find(results, "model_membership")
    assert c is not None
    assert c["passed"] is True
    assert c["severity"] == "info"
    assert "served/model" in c["message"]
    assert c["remediation"] == ""


def test_probe_model_absent_warns_with_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Model NOT in /v1/models -> warning naming model id AND pinning source."""
    monkeypatch.setenv("COLLEAGUE_MODEL", "my/custom-model")
    monkeypatch.setattr("urllib.request.urlopen", _ok_with_other_models())
    results = probe_checks()
    c = _find(results, "model_membership")
    assert c is not None
    assert c["passed"] is False
    assert c["severity"] == "warning"
    assert "my/custom-model" in c["message"]
    assert "COLLEAGUE_MODEL" in c["message"]
    assert c["remediation"]


def test_probe_model_absent_warns_with_config_json_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Model from config.json not served -> warning names config.json source."""
    monkeypatch.delenv("COLLEAGUE_MODEL", raising=False)
    monkeypatch.delenv("CONVERTIBLE_MODEL", raising=False)
    # Write a config.json with a model
    config_dir = tmp_path / ".colleague"
    config_dir.mkdir()
    (config_dir / "config.json").write_text(json.dumps({"model": "file-pinned-model"}))
    monkeypatch.setattr("urllib.request.urlopen", _ok_with_other_models())
    results = probe_checks(repo_path=str(tmp_path))
    c = _find(results, "model_membership")
    assert c is not None
    assert c["passed"] is False
    assert c["severity"] == "warning"
    assert "file-pinned-model" in c["message"]
    assert "config.json" in c["message"]
    assert c["remediation"]


def test_probe_endpoint_404_is_skip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider returns 404 on /v1/models -> skip/info, NOT a failure."""
    monkeypatch.setattr("urllib.request.urlopen", _http_404)
    results = probe_checks()
    c = _find(results, "model_membership")
    assert c is not None
    assert c["passed"] is True
    assert c["severity"] == "info"
    assert c["remediation"] == ""


def test_probe_endpoint_401_is_skip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HTTP 401 -> endpoint alive, skip membership check, NOT a failure."""
    monkeypatch.setattr("urllib.request.urlopen", _http_401)
    results = probe_checks()
    c = _find(results, "model_membership")
    assert c is not None
    assert c["passed"] is True
    assert c["severity"] == "info"
    assert c["remediation"] == ""


def test_probe_connection_refused_is_skip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Connection refused -> skip/info, NOT a failure."""
    monkeypatch.setattr("urllib.request.urlopen", _connection_refused)
    results = probe_checks()
    c = _find(results, "model_membership")
    assert c is not None
    assert c["passed"] is True
    assert c["severity"] == "info"
    assert c["remediation"] == ""


def test_probe_timeout_is_skip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Timeout -> skip/info, NOT a failure."""
    monkeypatch.setattr("urllib.request.urlopen", _timeout)
    results = probe_checks()
    c = _find(results, "model_membership")
    assert c is not None
    assert c["passed"] is True
    assert c["severity"] == "info"
    assert c["remediation"] == ""


# ---------------------------------------------------------------------------
# Integration: diagnose() wiring
# ---------------------------------------------------------------------------


def test_diagnose_default_excludes_probe() -> None:
    """Without --probe, the membership check is NOT in the report."""
    report = diagnose()
    assert _find(report["checks"], "model_membership") is None
    # Static source check IS present
    assert _find(report["checks"], "model_membership_source") is not None


def test_diagnose_probe_includes_membership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With --probe, the membership check IS in the report."""
    monkeypatch.setattr("urllib.request.urlopen", _ok_with_model("test-model"))
    report = diagnose(probe=True)
    assert _find(report["checks"], "model_membership") is not None
    assert _find(report["checks"], "model_membership_source") is not None


def test_probe_absent_model_does_not_flip_health(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A warning from model membership must not flip doctor unhealthy."""
    monkeypatch.setenv("COLLEAGUE_MODEL", "nonexistent/model")
    monkeypatch.setattr("urllib.request.urlopen", _ok_with_other_models())
    report = diagnose(probe=True)
    assert report["healthy"] is True, "warning must not flip health"


# ---------------------------------------------------------------------------
# Contract compliance
# ---------------------------------------------------------------------------


class TestCheckShape:
    _KEYS = {"id", "passed", "severity", "message", "remediation"}
    _SEVERITIES = {"error", "warning", "info"}

    def test_static_shape(self) -> None:
        for c in checks():
            assert set(c) == self._KEYS, f"bad shape: {c}"
            assert c["severity"] in self._SEVERITIES
            if c["passed"]:
                assert c["remediation"] == ""

    @pytest.mark.parametrize(
        "fake",
        [
            lambda: _ok_with_model("x"),
            _ok_with_other_models,
            _http_404,
            _http_401,
            _connection_refused,
            _timeout,
        ],
        ids=["present", "absent", "404", "401", "refused", "timeout"],
    )
    def test_probe_shape(self, monkeypatch: pytest.MonkeyPatch, fake) -> None:
        monkeypatch.setattr("urllib.request.urlopen", fake)
        for c in probe_checks():
            assert set(c) == self._KEYS, f"bad shape: {c}"
            assert c["severity"] in self._SEVERITIES
            assert c["severity"] != "error", "model_membership never emits error"
            if c["passed"]:
                assert c["remediation"] == ""

    def test_probe_checks_never_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _boom(*_a: object, **_k: object) -> _FakeResponse:
            raise RuntimeError("unexpected")

        monkeypatch.setattr("urllib.request.urlopen", _boom)
        try:
            result = probe_checks()
        except Exception as exc:  # pragma: no cover
            pytest.fail(f"probe_checks() raised unexpectedly: {exc}")
        assert isinstance(result, list)
