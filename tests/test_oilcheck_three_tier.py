"""Tests for the three-tier readiness doctor check-group (plan task t10).

The three-tier group has two layers:
  1. Static checks (always run): armed-state + gateway config presence.
     When not armed, reports informational OK lines and never fails.
  2. Probe checks (only with --probe, only when armed): worker role
     advertised, worker dialable, tool-calling probe, model-id match.

These tests monkeypatch urllib.request.urlopen and the config/lobes
resolution functions for determinism (no live server required).
"""

from __future__ import annotations

import json
import urllib.error

import pytest

import colleague.oilcheck as oilcheck
from colleague.oilcheck import diagnose

_CHECK_KEYS = {"id", "passed", "severity", "message", "remediation"}


def _find(results: list[dict], check_id: str) -> dict | None:
    return next((c for c in results if c["id"] == check_id), None)


# ---------------------------------------------------------------------------
# Helpers: fake HTTP responses
# ---------------------------------------------------------------------------


class _FakeResponse:
    """Minimal context-manager stand-in for an HTTP response."""

    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def _capabilities_with_worker(
    worker_model: str = "worker/model",
    worker_endpoint: str = "http://worker.example:8001",
    worker_ready: bool = True,
) -> dict:
    return {
        "cortex": {
            "model": "cortex/model",
            "endpoint": "http://cortex.example:8001",
            "path": "/v1/chat/completions",
            "context": 65536,
            "ready": True,
            "responsibilities": [],
            "forbidden_responsibilities": [],
        },
        "senses": {
            "model": "senses/model",
            "endpoint": "http://senses.example:8001",
            "path": "/v1/chat/completions",
            "context": 32768,
            "ready": True,
            "responsibilities": [],
            "forbidden_responsibilities": [],
        },
        "worker": {
            "model": worker_model,
            "endpoint": worker_endpoint,
            "path": "/v1/chat/completions",
            "context": 65536,
            "ready": worker_ready,
            "responsibilities": [],
            "forbidden_responsibilities": [],
        },
    }


def _capabilities_no_worker() -> dict:
    return {
        "cortex": {
            "model": "cortex/model",
            "endpoint": "http://cortex.example:8001",
            "path": "/v1/chat/completions",
            "context": 65536,
            "ready": True,
            "responsibilities": [],
            "forbidden_responsibilities": [],
        },
        "senses": {
            "model": "senses/model",
            "endpoint": "http://senses.example:8001",
            "path": "/v1/chat/completions",
            "context": 32768,
            "ready": True,
            "responsibilities": [],
            "forbidden_responsibilities": [],
        },
    }


def _models_list(model_ids: list[str]) -> dict:
    return {"object": "list", "data": [{"id": mid} for mid in model_ids]}


def _tool_call_response() -> dict:
    return {"choices": [{"message": {"tool_calls": [{"id": "1", "function": {"name": "ping"}}]}}]}


def _refused(*_a: object, **_k: object) -> None:
    raise urllib.error.URLError("Connection refused")


# ---------------------------------------------------------------------------
# Static checks: unarmed (default) — informational, never fails
# ---------------------------------------------------------------------------


def test_static_unarmed_reports_info_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """When three-tier is not armed, static checks report info/passed."""
    monkeypatch.delenv("COLLEAGUE_THREE_TIER", raising=False)
    monkeypatch.delenv("COLLEAGUE_LOBES_URL", raising=False)
    monkeypatch.delenv("CONVERTIBLE_LOBES_URL", raising=False)

    from colleague.oilcheck import three_tier

    checks = three_tier.checks()
    armed_check = _find(checks, "three_tier_armed")
    assert armed_check is not None
    assert armed_check["passed"] is True
    assert armed_check["severity"] == "info"
    assert armed_check["remediation"] == ""


def test_static_unarmed_never_flips_health(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unarmed three-tier group must never make doctor unhealthy."""
    monkeypatch.delenv("COLLEAGUE_THREE_TIER", raising=False)
    monkeypatch.delenv("COLLEAGUE_LOBES_URL", raising=False)

    from colleague.oilcheck import three_tier

    monkeypatch.setattr(oilcheck, "CHECK_GROUPS", [three_tier.checks])
    monkeypatch.setattr(oilcheck, "_REPO_AWARE_GROUPS", frozenset({three_tier.checks}))
    report = diagnose()
    assert report["healthy"] is True


def test_static_unarmed_no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Static checks when unarmed must not open any network connection."""
    monkeypatch.delenv("COLLEAGUE_THREE_TIER", raising=False)

    def _boom(*_a: object, **_k: object) -> None:
        raise AssertionError("three-tier static checks opened a connection")

    monkeypatch.setattr("urllib.request.urlopen", _boom)

    from colleague.oilcheck import three_tier

    checks = three_tier.checks()  # must not raise
    assert checks


# ---------------------------------------------------------------------------
# Static checks: armed via env
# ---------------------------------------------------------------------------


def test_static_armed_via_env_reports_armed(monkeypatch: pytest.MonkeyPatch) -> None:
    """When COLLEAGUE_THREE_TIER is set, the armed check reports armed=True."""
    monkeypatch.setenv("COLLEAGUE_THREE_TIER", "1")
    monkeypatch.setenv("COLLEAGUE_LOBES_URL", "http://lobes.example:8001")

    from colleague.oilcheck import three_tier

    checks = three_tier.checks()
    armed_check = _find(checks, "three_tier_armed")
    assert armed_check is not None
    assert armed_check["passed"] is True
    assert armed_check["severity"] == "info"
    assert "armed" in armed_check["message"].lower()


def test_static_armed_no_gateway_is_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    """When armed but no lobes gateway configured, report a warning."""
    monkeypatch.setenv("COLLEAGUE_THREE_TIER", "1")
    monkeypatch.delenv("COLLEAGUE_LOBES_URL", raising=False)
    monkeypatch.delenv("CONVERTIBLE_LOBES_URL", raising=False)

    from colleague.oilcheck import three_tier

    checks = three_tier.checks()
    gw_check = _find(checks, "three_tier_gateway")
    assert gw_check is not None
    assert gw_check["passed"] is False
    assert gw_check["severity"] == "warning"
    assert gw_check["remediation"]


def test_static_armed_with_gateway_is_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """When armed and gateway configured, report info/passed."""
    monkeypatch.setenv("COLLEAGUE_THREE_TIER", "1")
    monkeypatch.setenv("COLLEAGUE_LOBES_URL", "http://lobes.example:8001")

    from colleague.oilcheck import three_tier

    checks = three_tier.checks()
    gw_check = _find(checks, "three_tier_gateway")
    assert gw_check is not None
    assert gw_check["passed"] is True
    assert gw_check["severity"] == "info"
    assert gw_check["remediation"] == ""


# ---------------------------------------------------------------------------
# Probe checks: unarmed — empty (no network calls)
# ---------------------------------------------------------------------------


def test_probe_unarmed_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """When not armed, probe_checks returns an empty list (no network)."""
    monkeypatch.delenv("COLLEAGUE_THREE_TIER", raising=False)

    def _boom(*_a: object, **_k: object) -> None:
        raise AssertionError("probe_checks should not call urlopen when unarmed")

    monkeypatch.setattr("urllib.request.urlopen", _boom)

    from colleague.oilcheck import three_tier

    assert three_tier.probe_checks() == []


# ---------------------------------------------------------------------------
# Probe checks: armed, gateway reachable, worker role advertised
# ---------------------------------------------------------------------------


def test_probe_worker_role_advertised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When armed and gateway returns a worker role, report info/passed."""
    monkeypatch.setenv("COLLEAGUE_THREE_TIER", "1")
    monkeypatch.setenv("COLLEAGUE_LOBES_URL", "http://lobes.example:8001")

    from colleague import lobes as lobes_mod
    from colleague.lobes import LobesRoles, RoleInfo

    def _role(model: str, endpoint: str = "http://worker.example:8001") -> RoleInfo:
        return RoleInfo(
            model=model,
            endpoint=endpoint,
            path="/v1/chat/completions",
            context=65536,
            ready=True,
            responsibilities=(),
            forbidden_responsibilities=(),
        )

    monkeypatch.setattr(
        lobes_mod,
        "resolve_roles",
        lambda _url: LobesRoles(
            cortex=_role("cortex/model"),
            senses=_role("senses/model"),
            worker=_role("worker/model"),
        ),
    )

    from colleague.oilcheck import three_tier

    checks = three_tier.probe_checks()
    role_check = _find(checks, "three_tier_worker_role")
    assert role_check is not None
    assert role_check["passed"] is True
    assert role_check["severity"] == "info"
    assert "worker" in role_check["message"].lower()


def test_probe_worker_role_missing_is_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When armed but gateway advertises no worker role, report a warning."""
    monkeypatch.setenv("COLLEAGUE_THREE_TIER", "1")
    monkeypatch.setenv("COLLEAGUE_LOBES_URL", "http://lobes.example:8001")

    from colleague import lobes as lobes_mod
    from colleague.lobes import LobesRoles, RoleInfo

    def _role(model: str) -> RoleInfo:
        return RoleInfo(
            model=model,
            endpoint="http://example:8001",
            path="/v1/chat/completions",
            context=65536,
            ready=True,
            responsibilities=(),
            forbidden_responsibilities=(),
        )

    monkeypatch.setattr(
        lobes_mod,
        "resolve_roles",
        lambda _url: LobesRoles(
            cortex=_role("cortex/model"),
            senses=_role("senses/model"),
            worker=None,
        ),
    )

    from colleague.oilcheck import three_tier

    checks = three_tier.probe_checks()
    role_check = _find(checks, "three_tier_worker_role")
    assert role_check is not None
    assert role_check["passed"] is False
    assert role_check["severity"] == "warning"
    assert role_check["remediation"]


def test_probe_worker_role_not_ready_is_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When armed but worker role is not ready, report a warning."""
    monkeypatch.setenv("COLLEAGUE_THREE_TIER", "1")
    monkeypatch.setenv("COLLEAGUE_LOBES_URL", "http://lobes.example:8001")

    from colleague import lobes as lobes_mod
    from colleague.lobes import LobesRoles, RoleInfo

    def _role(model: str, ready: bool = True) -> RoleInfo:
        return RoleInfo(
            model=model,
            endpoint="http://example:8001",
            path="/v1/chat/completions",
            context=65536,
            ready=ready,
            responsibilities=(),
            forbidden_responsibilities=(),
        )

    monkeypatch.setattr(
        lobes_mod,
        "resolve_roles",
        lambda _url: LobesRoles(
            cortex=_role("cortex/model"),
            senses=_role("senses/model"),
            worker=_role("worker/model", ready=False),
        ),
    )

    from colleague.oilcheck import three_tier

    checks = three_tier.probe_checks()
    role_check = _find(checks, "three_tier_worker_role")
    assert role_check is not None
    assert role_check["passed"] is False
    assert role_check["severity"] == "warning"


# ---------------------------------------------------------------------------
# Probe checks: worker dialable
# ---------------------------------------------------------------------------


def test_probe_worker_dialable_ok(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the worker endpoint responds, report info/passed."""
    monkeypatch.setenv("COLLEAGUE_THREE_TIER", "1")
    monkeypatch.setenv("COLLEAGUE_LOBES_URL", "http://lobes.example:8001")

    from colleague import lobes as lobes_mod
    from colleague.lobes import LobesRoles, RoleInfo

    def _role(model: str, endpoint: str = "http://worker.example:8001") -> RoleInfo:
        return RoleInfo(
            model=model,
            endpoint=endpoint,
            path="/v1/chat/completions",
            context=65536,
            ready=True,
            responsibilities=(),
            forbidden_responsibilities=(),
        )

    monkeypatch.setattr(
        lobes_mod,
        "resolve_roles",
        lambda _url: LobesRoles(
            cortex=_role("cortex/model"),
            senses=_role("senses/model"),
            worker=_role("worker/model"),
        ),
    )

    # Mock urlopen for the worker dial probe (GET /models on worker endpoint)
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_a, **_k: _FakeResponse({"object": "list", "data": []}),
    )

    from colleague.oilcheck import three_tier

    checks = three_tier.probe_checks()
    dial_check = _find(checks, "three_tier_worker_dialable")
    assert dial_check is not None
    assert dial_check["passed"] is True
    assert dial_check["severity"] == "info"


def test_probe_worker_not_dialable_is_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the worker endpoint is unreachable, report a warning."""
    monkeypatch.setenv("COLLEAGUE_THREE_TIER", "1")
    monkeypatch.setenv("COLLEAGUE_LOBES_URL", "http://lobes.example:8001")

    from colleague import lobes as lobes_mod
    from colleague.lobes import LobesRoles, RoleInfo

    def _role(model: str, endpoint: str = "http://worker.example:8001") -> RoleInfo:
        return RoleInfo(
            model=model,
            endpoint=endpoint,
            path="/v1/chat/completions",
            context=65536,
            ready=True,
            responsibilities=(),
            forbidden_responsibilities=(),
        )

    monkeypatch.setattr(
        lobes_mod,
        "resolve_roles",
        lambda _url: LobesRoles(
            cortex=_role("cortex/model"),
            senses=_role("senses/model"),
            worker=_role("worker/model"),
        ),
    )

    monkeypatch.setattr("urllib.request.urlopen", _refused)

    from colleague.oilcheck import three_tier

    checks = three_tier.probe_checks()
    dial_check = _find(checks, "three_tier_worker_dialable")
    assert dial_check is not None
    assert dial_check["passed"] is False
    assert dial_check["severity"] == "warning"


# ---------------------------------------------------------------------------
# Probe checks: tool-calling probe on worker
# ---------------------------------------------------------------------------


def test_probe_worker_tool_calling_ok(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the worker emits a tool_call, report info/passed."""
    monkeypatch.setenv("COLLEAGUE_THREE_TIER", "1")
    monkeypatch.setenv("COLLEAGUE_LOBES_URL", "http://lobes.example:8001")

    from colleague import lobes as lobes_mod
    from colleague.lobes import LobesRoles, RoleInfo

    def _role(model: str, endpoint: str = "http://worker.example:8001") -> RoleInfo:
        return RoleInfo(
            model=model,
            endpoint=endpoint,
            path="/v1/chat/completions",
            context=65536,
            ready=True,
            responsibilities=(),
            forbidden_responsibilities=(),
        )

    monkeypatch.setattr(
        lobes_mod,
        "resolve_roles",
        lambda _url: LobesRoles(
            cortex=_role("cortex/model"),
            senses=_role("senses/model"),
            worker=_role("worker/model"),
        ),
    )

    # Mock urlopen: first call is GET /models (dial), second is POST tool-calling
    call_count = {"n": 0}

    def _multi(*_a: object, **_k: object) -> _FakeResponse:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return _FakeResponse({"object": "list", "data": []})
        return _FakeResponse(_tool_call_response())

    monkeypatch.setattr("urllib.request.urlopen", _multi)

    from colleague.oilcheck import three_tier

    checks = three_tier.probe_checks()
    tc_check = _find(checks, "three_tier_worker_tool_calling")
    assert tc_check is not None
    assert tc_check["passed"] is True
    assert tc_check["severity"] == "info"
    assert "tool_call" in tc_check["message"]


def test_probe_worker_tool_calling_no_tool_call_is_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the worker accepts but returns no tool_call, report a warning."""
    monkeypatch.setenv("COLLEAGUE_THREE_TIER", "1")
    monkeypatch.setenv("COLLEAGUE_LOBES_URL", "http://lobes.example:8001")

    from colleague import lobes as lobes_mod
    from colleague.lobes import LobesRoles, RoleInfo

    def _role(model: str, endpoint: str = "http://worker.example:8001") -> RoleInfo:
        return RoleInfo(
            model=model,
            endpoint=endpoint,
            path="/v1/chat/completions",
            context=65536,
            ready=True,
            responsibilities=(),
            forbidden_responsibilities=(),
        )

    monkeypatch.setattr(
        lobes_mod,
        "resolve_roles",
        lambda _url: LobesRoles(
            cortex=_role("cortex/model"),
            senses=_role("senses/model"),
            worker=_role("worker/model"),
        ),
    )

    call_count = {"n": 0}

    def _multi(*_a: object, **_k: object) -> _FakeResponse:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return _FakeResponse({"object": "list", "data": []})
        return _FakeResponse({"choices": [{"message": {"content": "hello"}}]})

    monkeypatch.setattr("urllib.request.urlopen", _multi)

    from colleague.oilcheck import three_tier

    checks = three_tier.probe_checks()
    tc_check = _find(checks, "three_tier_worker_tool_calling")
    assert tc_check is not None
    assert tc_check["passed"] is False
    assert tc_check["severity"] == "warning"


# ---------------------------------------------------------------------------
# Probe checks: served-model-id-matches-advert
# ---------------------------------------------------------------------------


def test_probe_model_id_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the worker model id is in the gateway's /v1/models list, pass."""
    monkeypatch.setenv("COLLEAGUE_THREE_TIER", "1")
    monkeypatch.setenv("COLLEAGUE_LOBES_URL", "http://lobes.example:8001")

    from colleague import lobes as lobes_mod
    from colleague.lobes import LobesRoles, RoleInfo

    def _role(model: str, endpoint: str = "http://worker.example:8001") -> RoleInfo:
        return RoleInfo(
            model=model,
            endpoint=endpoint,
            path="/v1/chat/completions",
            context=65536,
            ready=True,
            responsibilities=(),
            forbidden_responsibilities=(),
        )

    monkeypatch.setattr(
        lobes_mod,
        "resolve_roles",
        lambda _url: LobesRoles(
            cortex=_role("cortex/model"),
            senses=_role("senses/model"),
            worker=_role("worker/model"),
        ),
    )

    # urlopen calls: 1=GET /models (dial), 2=POST tool-calling, 3=GET /v1/models (gateway)
    call_count = {"n": 0}

    def _multi(*_a: object, **_k: object) -> _FakeResponse:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return _FakeResponse({"object": "list", "data": []})
        if call_count["n"] == 2:
            return _FakeResponse(_tool_call_response())
        return _FakeResponse(_models_list(["worker/model", "cortex/model"]))

    monkeypatch.setattr("urllib.request.urlopen", _multi)

    from colleague.oilcheck import three_tier

    checks = three_tier.probe_checks()
    match_check = _find(checks, "three_tier_worker_model_match")
    assert match_check is not None
    assert match_check["passed"] is True
    assert match_check["severity"] == "info"


def test_probe_model_id_mismatch_is_error_with_model_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the worker model id is NOT in the gateway's /v1/models list,
    report an error that NAMES the failing model id and exits 1.
    """
    monkeypatch.setenv("COLLEAGUE_THREE_TIER", "1")
    monkeypatch.setenv("COLLEAGUE_LOBES_URL", "http://lobes.example:8001")

    from colleague import lobes as lobes_mod
    from colleague.lobes import LobesRoles, RoleInfo

    def _role(model: str, endpoint: str = "http://worker.example:8001") -> RoleInfo:
        return RoleInfo(
            model=model,
            endpoint=endpoint,
            path="/v1/chat/completions",
            context=65536,
            ready=True,
            responsibilities=(),
            forbidden_responsibilities=(),
        )

    monkeypatch.setattr(
        lobes_mod,
        "resolve_roles",
        lambda _url: LobesRoles(
            cortex=_role("cortex/model"),
            senses=_role("senses/model"),
            worker=_role("worker/model"),
        ),
    )

    call_count = {"n": 0}

    def _multi(*_a: object, **_k: object) -> _FakeResponse:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return _FakeResponse({"object": "list", "data": []})
        if call_count["n"] == 2:
            return _FakeResponse(_tool_call_response())
        return _FakeResponse(_models_list(["other/model", "cortex/model"]))

    monkeypatch.setattr("urllib.request.urlopen", _multi)

    from colleague.oilcheck import three_tier

    checks = three_tier.probe_checks()
    match_check = _find(checks, "three_tier_worker_model_match")
    assert match_check is not None
    assert match_check["passed"] is False
    assert match_check["severity"] == "error"
    # The failing model id MUST appear in the message
    assert "worker/model" in match_check["message"]
    assert match_check["remediation"]


def test_probe_model_mismatch_flips_doctor_unhealthy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A model-id mismatch must make doctor exit 1 (unhealthy)."""
    monkeypatch.setenv("COLLEAGUE_THREE_TIER", "1")
    monkeypatch.setenv("COLLEAGUE_LOBES_URL", "http://lobes.example:8001")

    from colleague import lobes as lobes_mod
    from colleague.lobes import LobesRoles, RoleInfo

    def _role(model: str, endpoint: str = "http://worker.example:8001") -> RoleInfo:
        return RoleInfo(
            model=model,
            endpoint=endpoint,
            path="/v1/chat/completions",
            context=65536,
            ready=True,
            responsibilities=(),
            forbidden_responsibilities=(),
        )

    monkeypatch.setattr(
        lobes_mod,
        "resolve_roles",
        lambda _url: LobesRoles(
            cortex=_role("cortex/model"),
            senses=_role("senses/model"),
            worker=_role("worker/model"),
        ),
    )

    # diagnose(probe=True) runs reachability, tool_calling, organs, then
    # three_tier probes. We need to return appropriate responses for each:
    # - reachability GET /models → models list
    # - tool_calling POST → tool call response
    # - organs GET /capabilities → capabilities
    # - three_tier GET /models (dial) → models list
    # - three_tier POST tool-calling → tool call response
    # - three_tier GET /v1/models (gateway) → models list WITHOUT worker/model
    call_count = {"n": 0}

    def _multi(*_a: object, **_k: object) -> _FakeResponse:
        call_count["n"] += 1
        # All calls return OK-ish responses; the last one (gateway /v1/models)
        # returns a list WITHOUT the worker model to trigger the mismatch.
        if call_count["n"] >= 6:
            return _FakeResponse(_models_list(["other/model"]))
        if call_count["n"] == 5:
            return _FakeResponse(_tool_call_response())
        return _FakeResponse({"object": "list", "data": []})

    monkeypatch.setattr("urllib.request.urlopen", _multi)

    report = diagnose(probe=True)
    assert report["healthy"] is False
    match_check = _find(report["checks"], "three_tier_worker_model_match")
    assert match_check is not None
    assert match_check["passed"] is False
    assert match_check["severity"] == "error"
    assert "worker/model" in match_check["message"]


# ---------------------------------------------------------------------------
# Probe checks: gateway unreachable
# ---------------------------------------------------------------------------


def test_probe_gateway_unreachable_is_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When armed but the gateway is unreachable, report a warning."""
    monkeypatch.setenv("COLLEAGUE_THREE_TIER", "1")
    monkeypatch.setenv("COLLEAGUE_LOBES_URL", "http://lobes.example:8001")

    from colleague import lobes as lobes_mod

    monkeypatch.setattr(lobes_mod, "resolve_roles", lambda _url: None)

    from colleague.oilcheck import three_tier

    checks = three_tier.probe_checks()
    # Should have at least one check about the gateway being unreachable
    assert any(c["id"] == "three_tier_worker_role" and not c["passed"] for c in checks)


# ---------------------------------------------------------------------------
# Probe checks: not registered in CHECK_GROUPS
# ---------------------------------------------------------------------------


def test_probe_checks_not_registered() -> None:
    """probe_checks must not be in CHECK_GROUPS (probe-only)."""
    from colleague.oilcheck import three_tier

    assert three_tier.probe_checks not in oilcheck.CHECK_GROUPS


# ---------------------------------------------------------------------------
# Integration: diagnose with probe includes three-tier checks
# ---------------------------------------------------------------------------


def test_diagnose_default_excludes_three_tier_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default diagnose (no --probe) must not include three-tier probe checks."""
    monkeypatch.setenv("COLLEAGUE_THREE_TIER", "1")
    monkeypatch.setenv("COLLEAGUE_LOBES_URL", "http://lobes.example:8001")

    def _boom(*_a: object, **_k: object) -> None:
        raise AssertionError("default diagnose must not open a connection")

    monkeypatch.setattr("urllib.request.urlopen", _boom)

    report = diagnose()
    # Static checks ARE present (they are registered)
    assert _find(report["checks"], "three_tier_armed") is not None
    # Probe checks are NOT present
    assert _find(report["checks"], "three_tier_worker_role") is None


def test_diagnose_probe_includes_three_tier_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """diagnose(probe=True) must include three-tier probe checks when armed."""
    monkeypatch.setenv("COLLEAGUE_THREE_TIER", "1")
    monkeypatch.setenv("COLLEAGUE_LOBES_URL", "http://lobes.example:8001")

    from colleague import lobes as lobes_mod
    from colleague.lobes import LobesRoles, RoleInfo

    def _role(model: str, endpoint: str = "http://worker.example:8001") -> RoleInfo:
        return RoleInfo(
            model=model,
            endpoint=endpoint,
            path="/v1/chat/completions",
            context=65536,
            ready=True,
            responsibilities=(),
            forbidden_responsibilities=(),
        )

    monkeypatch.setattr(
        lobes_mod,
        "resolve_roles",
        lambda _url: LobesRoles(
            cortex=_role("cortex/model"),
            senses=_role("senses/model"),
            worker=_role("worker/model"),
        ),
    )

    # diagnose(probe=True) runs reachability, tool_calling, organs, then
    # three_tier probes — each calls urlopen. Return a generic OK for all.
    def _always_ok(*_a: object, **_k: object) -> _FakeResponse:
        # Detect if this is a POST (tool-calling) or GET (models/capabilities)
        return _FakeResponse(_tool_call_response())

    monkeypatch.setattr("urllib.request.urlopen", _always_ok)

    report = diagnose(probe=True)
    assert _find(report["checks"], "three_tier_worker_role") is not None
    assert _find(report["checks"], "three_tier_worker_dialable") is not None
    assert _find(report["checks"], "three_tier_worker_tool_calling") is not None
    assert _find(report["checks"], "three_tier_worker_model_match") is not None


# ---------------------------------------------------------------------------
# Contract compliance: five-key shape, never raises
# ---------------------------------------------------------------------------


class TestCheckShape:
    @pytest.mark.parametrize(
        "armed",
        [True, False],
        ids=["armed", "unarmed"],
    )
    def test_static_checks_shape(self, monkeypatch: pytest.MonkeyPatch, armed: bool) -> None:
        if armed:
            monkeypatch.setenv("COLLEAGUE_THREE_TIER", "1")
            monkeypatch.setenv("COLLEAGUE_LOBES_URL", "http://lobes.example:8001")
        else:
            monkeypatch.delenv("COLLEAGUE_THREE_TIER", raising=False)

        from colleague.oilcheck import three_tier

        for c in three_tier.checks():
            assert set(c) == _CHECK_KEYS, f"bad shape: {c}"
            if c["passed"]:
                assert c["remediation"] == ""

    def test_static_checks_never_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Even with a broken config, checks() must not raise."""
        monkeypatch.setenv("COLLEAGUE_THREE_TIER", "1")

        from colleague.oilcheck import three_tier

        result = three_tier.checks()
        assert isinstance(result, list)

    def test_probe_checks_never_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Even with a broken gateway, probe_checks() must not raise."""
        monkeypatch.setenv("COLLEAGUE_THREE_TIER", "1")
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", "http://lobes.example:8001")

        from colleague import lobes as lobes_mod

        def _boom(_url: str) -> None:
            raise RuntimeError("gateway exploded")

        monkeypatch.setattr(lobes_mod, "resolve_roles", _boom)

        from colleague.oilcheck import three_tier

        result = three_tier.probe_checks()
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Worker probe cap sizing (t3) — see tests/test_oilcheck_tool_calling.py for
# the measurement table. The worker seat on the operator rig is
# unsloth/Qwen3.6-35B-A3B-NVFP4, which at max_tokens=128 returns a 200 with
# finish_reason=length and NO tool_calls — the probe's false negative.
# ---------------------------------------------------------------------------


def test_worker_probe_cap_clears_the_measured_worst_case() -> None:
    """The cap covers 2x the worst measured worker tool-call spend (163 tokens)."""
    from colleague.oilcheck import three_tier

    assert three_tier._PROBE_MAX_TOKENS >= 2 * 163


def test_worker_probe_request_carries_the_sized_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    from colleague.oilcheck import three_tier

    captured: dict = {}

    def _capture(request: object, timeout: float | None = None) -> _FakeResponse:
        captured["body"] = json.loads(request.data.decode("utf-8"))  # type: ignore[attr-defined]
        return _FakeResponse(_tool_call_response())

    monkeypatch.setattr("urllib.request.urlopen", _capture)
    three_tier._worker_tool_calling("http://worker.example:8001/v1", "worker/model", "k")
    assert captured["body"]["max_tokens"] == three_tier._PROBE_MAX_TOKENS
