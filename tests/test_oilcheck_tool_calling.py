"""Tests for the opt-in tool-calling round-trip probe (issue #182, doctor --probe).

Like the reachability probe these monkeypatch ``urllib.request.urlopen`` for
determinism (no live server). Scenarios:

* urlopen succeeds (200) → ``tool_calling`` info/passed (WORKS).
* HTTPError 500 with an ``EngineCore`` body → ``tool_calling`` error (SERVER-CRASHED).
* HTTPError 400 → ``tool_calling`` error (TOOL-CALLS-UNSUPPORTED).
* OSError/URLError (server down) → check omitted (reachability covers "down").
* ``diagnose()`` excludes the probe; ``diagnose(probe=True)`` includes it and goes
  unhealthy on a crashing server (the #182 "it was green" fix).
* Contract: five-key shape, never raises.
"""

from __future__ import annotations

import io
import json
import urllib.error

import pytest

from colleague.oilcheck import diagnose
from colleague.oilcheck.tool_calling import checks

_TOOL_CALL_BODY = {
    "choices": [{"message": {"tool_calls": [{"id": "1", "function": {"name": "ping"}}]}}]
}
_NO_TOOL_CALL_BODY = {"choices": [{"message": {"content": "ready"}}]}


class _Resp:
    """200 context-manager stand-in carrying a JSON body the probe now reads (#184)."""

    def __init__(self, body: dict) -> None:
        self._body = json.dumps(body).encode("utf-8")

    def __enter__(self) -> "_Resp":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


def _ok(*_a: object, **_k: object) -> _Resp:
    return _Resp(_TOOL_CALL_BODY)


def _ok_no_tool_call(*_a: object, **_k: object) -> _Resp:
    return _Resp(_NO_TOOL_CALL_BODY)


def _timeout(*_a: object, **_k: object):
    raise TimeoutError("timed out")


def _raise_http(code: int, body: str):
    def _raise(*_a: object, **_k: object):
        raise urllib.error.HTTPError(
            "http://localhost:8001/v1/chat/completions",
            code,
            "Server Error",
            {},  # type: ignore[arg-type]
            io.BytesIO(body.encode("utf-8")),
        )

    return _raise


def _refused(*_a: object, **_k: object):
    raise urllib.error.URLError("Connection refused")


def _find(results: list[dict], check_id: str) -> dict | None:
    return next((c for c in results if c["id"] == check_id), None)


_ENGINECORE_BODY = (
    '{"error":{"message":"EngineCore encountered an issue. See stack trace above '
    'for the root cause.","type":"InternalServerError","code":500}}'
)


def test_works_only_when_the_server_emits_a_tool_call(monkeypatch: pytest.MonkeyPatch) -> None:
    # #184: a 2xx that actually carries a tool_call is the only WORKS.
    monkeypatch.setattr("urllib.request.urlopen", _ok)
    tc = _find(checks(), "tool_calling")
    assert tc is not None
    assert tc["passed"] is True
    assert tc["severity"] == "info"
    assert "tool_call" in tc["message"]


def test_accepted_but_no_tool_call_is_a_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    # #184: a 2xx text completion (server ignored the tools) must NOT be a green —
    # this is the false-green the probe exists to catch.
    monkeypatch.setattr("urllib.request.urlopen", _ok_no_tool_call)
    tc = _find(checks(), "tool_calling")
    assert tc is not None
    assert tc["passed"] is False
    assert tc["severity"] == "warning"
    assert "no tool_call" in tc["message"]


def test_timeout_is_reported_not_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    # #184: a tool-calling POST that hangs is a distinct signal; it must surface as
    # a check, not be dropped by the OSError omit clause (TimeoutError ⊂ OSError).
    monkeypatch.setattr("urllib.request.urlopen", _timeout)
    tc = _find(checks(), "tool_calling")
    assert tc is not None
    assert tc["passed"] is False
    assert tc["severity"] == "warning"
    assert "timed out" in tc["message"]


def test_server_crash_is_an_actionable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("urllib.request.urlopen", _raise_http(500, _ENGINECORE_BODY))
    tc = _find(checks(), "tool_calling")
    assert tc is not None
    assert tc["passed"] is False
    assert tc["severity"] == "error"  # hard incompatibility, not advisory
    assert "crashed" in tc["message"].lower()
    assert "speculative-decoding" in tc["remediation"] or "MTP" in tc["remediation"]


def test_tool_calls_unsupported_points_at_the_parser_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "urllib.request.urlopen",
        _raise_http(400, '{"error":"auto tool choice requires --tool-call-parser"}'),
    )
    tc = _find(checks(), "tool_calling")
    assert tc is not None
    assert tc["passed"] is False
    assert tc["severity"] == "error"
    assert "--enable-auto-tool-choice" in tc["remediation"]


def test_server_down_is_omitted(monkeypatch: pytest.MonkeyPatch) -> None:
    # provider_reachable already reports "down" — the tool-calling probe must not
    # double-report it as a tool-calling failure.
    monkeypatch.setattr("urllib.request.urlopen", _refused)
    assert checks() == []


def test_other_http_status_is_inconclusive_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    # A 401 (auth) is explained by other checks — don't flip unhealthy on it.
    monkeypatch.setattr("urllib.request.urlopen", _raise_http(401, "unauthorized"))
    tc = _find(checks(), "tool_calling")
    assert tc is not None
    assert tc["passed"] is False
    assert tc["severity"] == "warning"


def test_default_diagnose_excludes_the_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    # If urlopen is touched at all without --probe, that's a no-network violation.
    def _boom(*_a: object, **_k: object):
        raise AssertionError("default diagnose must not open a connection")

    monkeypatch.setattr("urllib.request.urlopen", _boom)
    report = diagnose(probe=False)
    assert _find(report["checks"], "tool_calling") is None


def test_probe_diagnose_goes_unhealthy_on_a_crashing_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#182: doctor --probe must NOT be green when the server crashes on tools."""
    monkeypatch.setattr("urllib.request.urlopen", _raise_http(500, _ENGINECORE_BODY))
    report = diagnose(probe=True)
    tc = _find(report["checks"], "tool_calling")
    assert tc is not None and tc["passed"] is False
    assert report["healthy"] is False  # the error check flips doctor unhealthy → exit 1


def test_probe_check_has_the_five_key_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("urllib.request.urlopen", _ok)
    tc = _find(checks(), "tool_calling")
    assert set(tc) == {"id", "passed", "severity", "message", "remediation"}
