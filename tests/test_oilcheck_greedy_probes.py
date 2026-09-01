"""Test that oilcheck probes stay greedy and exclude sampling keys.

Acceptance criterion (issue #479, task t1):
  A test asserts the request bodies built by oilcheck/tool_calling.py and
  oilcheck/three_tier.py are unchanged, temperature 0.0 included, and carry
  no sampling keys.

Why this matters: Issue #479 adds reasoning-aware sampling keys (top_p, top_k,
min_p, presence_penalty, repetition_penalty) to the vLLM adapter payload. The
oilcheck probes are determinism probes, not reasoning work, and must stay
greedy (temperature 0.0) and exclude sampling keys.

This test verifies that both probes' request bodies have:
  - temperature = 0.0 (greedy decoding)
  - NO sampling keys: top_p, top_k, min_p, presence_penalty, repetition_penalty
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from colleague.oilcheck import tool_calling


class _CaptureResponse:
    """Context manager stand-in that captures the request body."""

    def __init__(self, response_body: dict) -> None:
        self._response_body = response_body
        self.captured_request: dict | None = None

    def __enter__(self) -> "_CaptureResponse":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def read(self) -> bytes:
        return json.dumps(self._response_body).encode("utf-8")


def _capture_factory(response_body: dict):
    """Factory that creates a capture function for urlopen."""

    def _capture(request: Any, timeout: float | None = None) -> _CaptureResponse:
        resp = _CaptureResponse(response_body)
        # Capture the request body that was sent
        req_data = request.data.decode("utf-8")  # type: ignore[attr-defined]
        resp.captured_request = json.loads(req_data)
        return resp

    return _capture


_SUCCESS_RESPONSE = {
    "choices": [{"message": {"tool_calls": [{"id": "1", "function": {"name": "ping"}}]}}]
}

_SAMPLING_KEYS = {"top_p", "top_k", "min_p", "presence_penalty", "repetition_penalty"}


def test_tool_calling_probe_is_greedy_no_sampling_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify tool_calling probe has temperature=0.0 and no sampling keys."""
    captured_requests: list[dict] = []

    def _capture(request: Any, timeout: float | None = None) -> _CaptureResponse:
        resp = _CaptureResponse(_SUCCESS_RESPONSE)
        req_data = request.data.decode("utf-8")  # type: ignore[attr-defined]
        resp.captured_request = json.loads(req_data)
        captured_requests.append(resp.captured_request)
        return resp

    monkeypatch.setattr("urllib.request.urlopen", _capture)
    tool_calling.checks()

    assert len(captured_requests) == 1, "Expected exactly one request to be made"
    body = captured_requests[0]

    # Assert temperature is 0.0 (greedy)
    assert body["temperature"] == 0.0, (
        f"tool_calling probe must use greedy decoding (temperature=0.0), "
        f"got temperature={body.get('temperature')}"
    )

    # Assert no sampling keys are present
    present_keys = set(body.keys()) & _SAMPLING_KEYS
    assert (
        not present_keys
    ), f"tool_calling probe must not include sampling keys, but found: {present_keys}"


def test_three_tier_worker_tool_calling_probe_is_greedy_no_sampling_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify three_tier worker tool-calling probe has temperature=0.0 and no sampling keys."""
    from colleague.oilcheck.three_tier import _worker_tool_calling

    captured_requests: list[dict] = []

    def _capture(request: Any, timeout: float | None = None) -> _CaptureResponse:
        resp = _CaptureResponse(_SUCCESS_RESPONSE)
        req_data = request.data.decode("utf-8")  # type: ignore[attr-defined]
        resp.captured_request = json.loads(req_data)
        captured_requests.append(resp.captured_request)
        return resp

    monkeypatch.setattr("urllib.request.urlopen", _capture)
    _worker_tool_calling(
        base_url="http://worker.example:8001",
        model="test-model",
        api_key="test-key",
    )

    assert len(captured_requests) == 1, "Expected exactly one request to be made"
    body = captured_requests[0]

    # Assert temperature is 0.0 (greedy)
    assert body["temperature"] == 0.0, (
        f"three_tier worker probe must use greedy decoding (temperature=0.0), "
        f"got temperature={body.get('temperature')}"
    )

    # Assert no sampling keys are present
    present_keys = set(body.keys()) & _SAMPLING_KEYS
    assert (
        not present_keys
    ), f"three_tier worker probe must not include sampling keys, but found: {present_keys}"


def test_probe_request_bodies_have_only_expected_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify probe request bodies have only the expected keys (no surprises)."""
    from colleague.oilcheck.three_tier import _worker_tool_calling

    captured_requests: list[dict] = []

    def _capture(request: Any, timeout: float | None = None) -> _CaptureResponse:
        resp = _CaptureResponse(_SUCCESS_RESPONSE)
        req_data = request.data.decode("utf-8")  # type: ignore[attr-defined]
        resp.captured_request = json.loads(req_data)
        captured_requests.append(resp.captured_request)
        return resp

    monkeypatch.setattr("urllib.request.urlopen", _capture)

    # Test tool_calling probe
    tool_calling.checks()
    assert len(captured_requests) == 1
    tool_calling_body = captured_requests[0]

    expected_keys_tool_calling = {
        "model",
        "messages",
        "tools",
        "tool_choice",
        "max_tokens",
        "temperature",
    }
    assert set(tool_calling_body.keys()) == expected_keys_tool_calling, (
        f"tool_calling probe has unexpected keys. "
        f"Expected: {expected_keys_tool_calling}, "
        f"Got: {set(tool_calling_body.keys())}"
    )

    # Test three_tier worker probe
    captured_requests.clear()
    _worker_tool_calling(
        base_url="http://worker.example:8001",
        model="test-model",
        api_key="test-key",
    )
    assert len(captured_requests) == 1
    worker_body = captured_requests[0]

    expected_keys_worker = {
        "model",
        "messages",
        "tools",
        "tool_choice",
        "max_tokens",
        "temperature",
    }
    assert set(worker_body.keys()) == expected_keys_worker, (
        f"three_tier worker probe has unexpected keys. "
        f"Expected: {expected_keys_worker}, "
        f"Got: {set(worker_body.keys())}"
    )
