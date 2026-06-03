"""vLLM OpenAI driver: response parsing + a full loop over mocked HTTP (R2, h2).

The opt-in live end-to-end proof against a real server lives in
``test_vllm_live.py`` (skipped unless ``COLLEAGUE_VLLM_E2E=1``).
"""

from __future__ import annotations

import json
import urllib.error
from pathlib import Path

import pytest

from colleague.config import EngineConfig
from colleague.contract import OK, Task
from colleague.engines import vllm_openai
from colleague.engines.vllm_openai import VllmOpenAIEngine, _parse_response, _post_json


def _message_with_tool_call(name: str, arguments: dict) -> dict:
    return {
        "choices": [
            {
                "message": {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": f"call-{name}",
                            "function": {"name": name, "arguments": json.dumps(arguments)},
                        }
                    ],
                }
            }
        ],
        "usage": {"prompt_tokens": 5, "completion_tokens": 2},
    }


def test_parse_response_decodes_tool_calls_and_usage() -> None:
    resp = _parse_response(_message_with_tool_call("write_file", {"path": "a", "content": "b"}))
    assert len(resp.tool_calls) == 1
    call = resp.tool_calls[0]
    assert call.name == "write_file"
    assert call.arguments == {"path": "a", "content": "b"}  # JSON-string args decoded to a dict
    assert resp.prompt_tokens == 5
    assert resp.completion_tokens == 2


def test_parse_response_tolerates_plain_text() -> None:
    resp = _parse_response({"choices": [{"message": {"content": "just text"}}]})
    assert resp.content == "just text"
    assert resp.tool_calls == []


def test_post_json_preserves_vllm_error_body(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Response:
        def read(self) -> bytes:
            return b'{"error":{"message":"The model `Qwen/Qwen3-32B` does not exist."}}'

        def close(self) -> None:  # file-like protocol: HTTPError closes its fp on GC
            pass

    def fake_urlopen(*_args: object, **_kwargs: object) -> object:
        raise urllib.error.HTTPError(
            "http://localhost:8001/v1/chat/completions",
            404,
            "Not Found",
            {},
            _Response(),
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(urllib.error.HTTPError) as exc:
        _post_json("http://localhost:8001/v1/chat/completions", {}, api_key="EMPTY", timeout=1)

    assert "Qwen/Qwen3-32B" in str(exc.value)


def test_post_json_raises_legible_error_when_server_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A connection-level URLError (server down/refused) becomes a legible,
    endpoint-named error instead of the cryptic bare "URLError: <urlopen error
    ...>" the loop would otherwise surface (#92)."""

    def fake_urlopen(*_args: object, **_kwargs: object) -> object:
        raise urllib.error.URLError("[Errno 111] Connection refused")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(ConnectionError) as exc:
        _post_json("http://localhost:8001/v1/chat/completions", {}, api_key="EMPTY", timeout=1)

    msg = str(exc.value)
    assert "http://localhost:8001/v1/chat/completions" in msg
    assert "unreachable" in msg


def test_drive_runs_full_loop_over_mocked_http(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    turns = [
        _message_with_tool_call("write_file", {"path": "made.txt", "content": "by qwen"}),
        _message_with_tool_call("finish", {"summary": "wrote made.txt"}),
    ]
    captured: dict[str, object] = {}
    state = {"i": 0}

    def fake_post(url: str, payload: dict, *, api_key: str, timeout: float) -> dict:
        captured["url"] = url
        captured["payload"] = payload
        captured["api_key"] = api_key
        resp = turns[min(state["i"], len(turns) - 1)]
        state["i"] += 1
        return resp

    monkeypatch.setattr(vllm_openai, "_post_json", fake_post)

    task = Task.new(str(tmp_path), "write made.txt", engine="vllm-openai")
    cfg = EngineConfig.resolve(base_url="http://other-host:9999/v1", model="my-model")
    result = VllmOpenAIEngine().drive(task, cfg)

    assert result.status == OK
    assert (tmp_path / "made.txt").read_text() == "by qwen"
    assert result.summary == "wrote made.txt"
    assert result.usage.total_tokens == 14
    # config-only retarget (h2): URL + model came straight from EngineConfig, no code change.
    assert captured["url"] == "http://other-host:9999/v1/chat/completions"
    assert captured["payload"]["model"] == "my-model"
    assert any(s["function"]["name"] == "write_file" for s in captured["payload"]["tools"])
