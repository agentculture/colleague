"""Engine wire pass-through: parts-content messages survive verbatim (t4, all-engines).

Wave 1 landed ``colleague/media.py`` (``build_part`` -> standard OpenAI content
parts: image_url data-URI / input_audio) and ``Task.attachments`` on the
contract. A later task (t3, built separately) makes the loop build the initial
user message as a parts LIST (``[{"type": "text", ...}, {"type": "image_url",
...}]``) instead of a plain string when attachments are present.

This module proves both bundled engines tolerate a message whose ``content``
is a parts list rather than a string:

* vllm-openai must serialize the parts list VERBATIM over the standard OpenAI
  wire (``json.dumps`` over ``urllib`` — no vLLM-only wire field is
  introduced by colleague).
* mock must accept a parts-shaped message without error.

Honest scope (t4): only ``colleague/engines/vllm_openai.py`` and
``colleague/engines/mock.py`` are engine-owned and in scope for a fix here.
Two str-assuming spots were found OUTSIDE the engines, in
``colleague/context.py`` — ``count_tokens_chars`` (line ~44-46) and
``_seg_chars`` (line ~126) both do ``len(m.get("content"))`` (or ``len(m.get(
"content") or "")``), which silently MISCOUNTS (not crashes) when ``content``
is a list of parts, since ``len()`` of a list returns the part count, not a
character count. They are left untouched here per the t4 task boundary — they
belong to whichever task owns ``context.py``/the context-budget windowing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from colleague import loop as loop_module
from colleague.config import EngineConfig
from colleague.contract import OK, Task
from colleague.engines import mock as mock_engine
from colleague.engines import vllm_openai
from colleague.engines.vllm_openai import VllmOpenAIEngine, _post_json

# A representative parts-content list: text + image + audio, exactly the shape
# colleague/media.py's build_part() produces (task t2) — the shape t3 will
# wire into the loop's initial user message when Task.attachments is set.
_PARTS_CONTENT = [
    {"type": "text", "text": "describe these attachments"},
    {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUFBQQ=="}},
    {"type": "input_audio", "input_audio": {"data": "QkJCQg==", "format": "wav"}},
]

_STANDARD_PART_KEYS = {"type", "text", "image_url", "input_audio"}


def _assert_only_standard_part_keys(content: object) -> None:
    """Every part in a list-shaped ``content`` uses ONLY standard OpenAI keys."""
    assert isinstance(content, list)
    for part in content:
        assert set(part.keys()) <= _STANDARD_PART_KEYS, f"non-standard part keys: {part}"


# ---------------------------------------------------------------------------
# vllm-openai: request-body capture — proves verbatim pass-through
# ---------------------------------------------------------------------------


def test_vllm_complete_forwards_parts_content_verbatim_to_post_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``_make_complete``'s ``complete`` closure hands the message list straight
    to ``_post_json`` — no per-message content transform. A list-shaped
    ``content`` on a user message survives byte-for-byte into the outgoing
    payload, and a plain string message stays untouched alongside it.
    """
    captured: dict[str, object] = {}

    def fake_post_json(url, payload, *, api_key, timeout):
        captured["payload"] = payload
        return {"choices": [{"message": {"content": "ok", "tool_calls": []}}], "usage": {}}

    monkeypatch.setattr(vllm_openai, "_post_json", fake_post_json)

    engine = VllmOpenAIEngine()
    config = EngineConfig.resolve(base_url="http://localhost:9999/v1", model="test-model")
    complete = engine._make_complete(config, tools=[])

    messages = [
        {"role": "system", "content": "you are a helpful engine"},
        {"role": "user", "content": _PARTS_CONTENT},
    ]
    complete(messages)

    sent = captured["payload"]["messages"]
    assert sent[1]["content"] == _PARTS_CONTENT  # survives verbatim
    _assert_only_standard_part_keys(sent[1]["content"])
    # The plain string message is untouched — no accidental promotion to a list.
    assert sent[0]["content"] == "you are a helpful engine"
    assert isinstance(sent[0]["content"], str)


def test_vllm_post_json_serializes_parts_content_over_the_real_wire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One level lower: patch ``urllib.request.urlopen`` itself and inspect the
    actual JSON *bytes* ``_post_json`` puts on the wire — proving the parts
    list round-trips through real ``json.dumps``/``json.loads`` with no
    colleague-added wire field, not merely that a dict reference was passed
    around in memory.
    """
    captured: dict[str, object] = {}

    class _Resp:
        def __enter__(self) -> "_Resp":
            return self

        def __exit__(self, *exc: object) -> bool:
            return False

        def read(self) -> bytes:
            return json.dumps({"choices": [{"message": {"content": "ok"}}], "usage": {}}).encode(
                "utf-8"
            )

    def fake_urlopen(request, timeout=None):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _Resp()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    payload = {
        "model": "test-model",
        "messages": [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": _PARTS_CONTENT},
        ],
        "temperature": 0.0,
    }
    _post_json("http://localhost:9999/v1/chat/completions", payload, api_key="EMPTY", timeout=5)

    sent_messages = captured["body"]["messages"]
    assert sent_messages[1]["content"] == _PARTS_CONTENT
    _assert_only_standard_part_keys(sent_messages[1]["content"])
    # Only standard OpenAI top-level fields are present — no vLLM-only extras.
    assert set(captured["body"].keys()) <= {
        "model",
        "messages",
        "temperature",
        "tools",
        "tool_choice",
    }


def test_vllm_drive_over_mocked_http_tolerates_parts_content_first_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A full drive (``work()``) over mocked HTTP, with the FIRST user message
    already parts-shaped (simulating a post-t3 attachments-carrying task),
    completes cleanly end to end — proves the whole vllm-openai request path
    (not merely the ``complete`` closure) tolerates a list ``content``.
    """
    turns = [
        {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "1",
                                "function": {
                                    "name": "write_file",
                                    "arguments": json.dumps(
                                        {"path": "seen.txt", "content": "described"}
                                    ),
                                },
                            }
                        ],
                    }
                }
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2},
        },
        {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "2",
                                "function": {
                                    "name": "finish",
                                    "arguments": json.dumps({"summary": "described"}),
                                },
                            }
                        ],
                    }
                }
            ],
            "usage": {"prompt_tokens": 3, "completion_tokens": 1},
        },
    ]
    captured: dict[str, object] = {"payloads": []}
    state = {"i": 0}

    def fake_post(url, payload, *, api_key, timeout):
        captured["payloads"].append(payload)
        turn = turns[min(state["i"], len(turns) - 1)]
        state["i"] += 1
        return turn

    monkeypatch.setattr(vllm_openai, "_post_json", fake_post)
    # Simulate t3's loop change: the first user message is already a parts list.
    monkeypatch.setattr(loop_module, "_build_user_message", lambda task: _PARTS_CONTENT)

    task = Task.new(str(tmp_path), "describe the attachments", engine="vllm-openai")
    cfg = EngineConfig.resolve()

    result = VllmOpenAIEngine().work(task, cfg)

    assert result.status == OK
    first_payload = captured["payloads"][0]
    assert first_payload["messages"][1]["content"] == _PARTS_CONTENT
    _assert_only_standard_part_keys(first_payload["messages"][1]["content"])


# ---------------------------------------------------------------------------
# mock: message-walking tolerance
# ---------------------------------------------------------------------------


def test_mock_script_complete_tolerates_parts_content_message() -> None:
    """Direct unit call to the seam mock walks messages through:
    ``_script(task)``'s returned ``complete`` closure. The mock's turns are a
    fixed script that never inspects message content, so calling it with a
    parts-shaped message list must not raise — proven directly, not assumed.
    """
    task = Task.new("/tmp/does-not-matter-for-this-call", "describe the attachments")
    complete = mock_engine._script(task)

    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": _PARTS_CONTENT},
    ]
    first = complete(messages)
    assert first.tool_calls  # first scripted turn (write_file)

    # The running history grows with the parts-content message still present
    # further back — the second scripted turn is reached identically.
    messages.append({"role": "assistant", "content": first.content})
    second = complete(messages)
    assert second.tool_calls  # second scripted turn (finish)


def test_mock_engine_work_tolerates_parts_content_initial_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Full ``work()`` run with the FIRST user message forced to a parts list
    (simulating the post-t3 attachments-carrying loop path) completes cleanly
    — the mock engine's scripted responses never depend on message shape, so
    the work item finishes OK with no exception raised while walking messages.
    """
    monkeypatch.setattr(loop_module, "_build_user_message", lambda task: _PARTS_CONTENT)

    task = Task.new(str(tmp_path), "describe the attachments", engine="mock")
    cfg = EngineConfig.resolve()

    result = mock_engine.MockEngine().work(task, cfg)

    assert result.status == OK
    assert (tmp_path / mock_engine.OUTPUT_FILE).exists()
