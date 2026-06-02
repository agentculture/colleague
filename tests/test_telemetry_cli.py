"""``colleague telemetry`` CLI noun group — status and overview (issue #22).

Acceptance criteria:
1. ``telemetry status --json`` emits the resolved config + ``sdk_installed``.
2. ``telemetry status`` (text) reports enabled/endpoint, exit 0.
3. ``telemetry overview`` (and bare ``telemetry``) describes the noun, exit 0.
4. ``explain telemetry`` returns the catalog entry.
"""

from __future__ import annotations

import json

import pytest

from colleague.cli import main

_TELEMETRY_ENV = [
    "CONVERTIBLE_OTEL_ENABLED",
    "CONVERTIBLE_OTEL_ENDPOINT",
    "CONVERTIBLE_OTEL_SERVICE_NAME",
    "OTEL_SDK_DISABLED",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_SERVICE_NAME",
]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _TELEMETRY_ENV:
        monkeypatch.delenv(key, raising=False)


def test_status_json_shape(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["telemetry", "status", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["enabled"] is False
    assert "sdk_installed" in payload
    assert payload["service_name"] == "colleague"
    assert payload["otlp_endpoint"].startswith("http")


def test_status_reflects_env(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CONVERTIBLE_OTEL_ENABLED", "1")
    monkeypatch.setenv("CONVERTIBLE_OTEL_SERVICE_NAME", "myagent")
    rc = main(["telemetry", "status", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["enabled"] is True
    assert payload["service_name"] == "myagent"


def test_status_text(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["telemetry", "status"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "enabled:" in out
    assert "sdk_installed:" in out


def test_overview_text(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["telemetry", "overview"])
    assert rc == 0
    assert "colleague telemetry" in capsys.readouterr().out


def test_overview_json_shape(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["telemetry", "overview", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["subject"] == "colleague telemetry"
    assert isinstance(payload["sections"], list)
    assert payload["sections"]


def test_bare_noun_prints_overview(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["telemetry"])
    assert rc == 0
    assert capsys.readouterr().out.strip()


def test_explain_telemetry(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["explain", "telemetry"])
    assert rc == 0
    assert "colleague telemetry" in capsys.readouterr().out
