"""#182: the vLLM engine makes a server crash legible and can dump its request.

Two boundary-ownership behaviors, both stub-driven (no live server):

* A 500 whose body names ``EngineCore``/``InternalServerError`` becomes an
  actionable error (likely cause + ``doctor --probe``), the upstream body is
  preserved, a generic 500 stays generic, and a 400 is untouched (never blamed
  on a server crash).
* ``COLLEAGUE_DUMP_REQUEST`` dumps the exact outgoing payload to stderr without
  the api_key, and is a strict no-op when unset.
"""

from __future__ import annotations

import urllib.error

import pytest

from colleague.config import EngineConfig
from colleague.engines import vllm_openai
from colleague.engines.vllm_openai import VllmOpenAIEngine, _post_json

_URL = "http://localhost:8001/v1/chat/completions"


class _Body:
    """File-like HTTPError fp carrying a canned body."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def close(self) -> None:
        pass


def _raise_http(code: int, body: str):
    def fake_urlopen(*_a: object, **_k: object) -> object:
        raise urllib.error.HTTPError(_URL, code, "Server Error", {}, _Body(body.encode()))

    return fake_urlopen


_ENGINECORE = (
    '{"error":{"message":"EngineCore encountered an issue. See stack trace above.",'
    '"type":"InternalServerError","code":500}}'
)


def test_enginecore_500_becomes_actionable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("urllib.request.urlopen", _raise_http(500, _ENGINECORE))
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post_json(_URL, {}, api_key="EMPTY", timeout=1)
    msg = str(exc.value)
    assert "doctor --probe" in msg  # points the operator at the new probe
    assert "tool-call" in msg or "tool-calling" in msg
    assert "EngineCore" in msg  # original upstream body preserved


def test_generic_500_is_server_side_but_not_a_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("urllib.request.urlopen", _raise_http(500, '{"error":"overloaded"}'))
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post_json(_URL, {}, api_key="EMPTY", timeout=1)
    msg = str(exc.value)
    assert "returned a 500" in msg  # generic server-side note
    assert "doctor --probe" not in msg  # no crash hint without the markers
    assert "overloaded" in msg


def test_400_is_not_attributed_to_a_server_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("urllib.request.urlopen", _raise_http(400, '{"error":"bad request"}'))
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post_json(_URL, {}, api_key="EMPTY", timeout=1)
    msg = str(exc.value)
    assert "returned a 500" not in msg
    assert "doctor --probe" not in msg
    assert "bad request" in msg


def _complete_with(monkeypatch: pytest.MonkeyPatch):
    """Build the engine's complete() with _post_json stubbed to a canned reply."""
    monkeypatch.setattr(
        vllm_openai,
        "_post_json",
        lambda *_a, **_k: {"choices": [{"message": {"content": "ok"}}], "usage": {}},
    )
    config = EngineConfig.resolve(
        api_key="SECRETKEY123", model="m/odel", base_url="http://localhost:8001/v1"
    )
    return VllmOpenAIEngine()._make_complete(config)


def test_dump_request_emits_payload_without_api_key(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("COLLEAGUE_DUMP_REQUEST", "1")
    complete = _complete_with(monkeypatch)
    complete([{"role": "user", "content": "hi"}])
    err = capsys.readouterr().err
    assert "outgoing request payload" in err
    assert '"tool_choice": "auto"' in err  # the real payload was dumped
    assert "m/odel" in err
    assert "SECRETKEY123" not in err  # the api_key is a header, never in the dump


def test_no_dump_when_env_unset(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("COLLEAGUE_DUMP_REQUEST", raising=False)
    complete = _complete_with(monkeypatch)
    complete([{"role": "user", "content": "hi"}])
    assert "outgoing request payload" not in capsys.readouterr().err
