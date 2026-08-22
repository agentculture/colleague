"""Unset byte-identical + all-engines result-shape parity (#416 t9, spec
c1/h1, c18/h14).

Two pins:

* **Payload-equality pin** — with the kill-switch (``reasoning_effort =
  "default"``, the concrete "unset" case: ``reasoning_effort_effective`` is
  ``None``) the ``_build_chat_payload`` output equals the FROZEN pre-#416
  fixture (frozen from ``git show main:colleague/engines/vllm_openai.py``
  before t3 landed) for the tools-on, tools-off, streamed and blocking
  shapes. With the knob SET the payload gains exactly one key
  (``chat_template_kwargs``) and nothing else moves.
* **All-engines result-shape parity** — the same task driven through mock and
  vllm-openai yields TaskResult ``to_dict()`` key sets that are IDENTICAL
  with the knob unset AND set; the effort appears ONLY in the config
  snapshot (``EngineConfig.to_dict()``), never in the result shape (s7: the
  mock builds no wire payload, so the all-engines rule constrains the RESULT
  shape, not the wire).
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from colleague import registry
from colleague.config import EngineConfig
from colleague.contract import OK, Task
from colleague.engines import vllm_openai
from colleague.engines.vllm_openai import VllmOpenAIEngine

# ---------------------------------------------------------------------------
# Frozen pre-#416 payload fixture (git show main:colleague/engines/
# vllm_openai.py, _build_chat_payload, before t3 landed). The pre-change
# builder emitted EXACTLY: model / messages / temperature, + tools /
# tool_choice when tools were offered, + stream / stream_options when
# streaming was armed. No chat_template_kwargs — the key did not exist.
# ---------------------------------------------------------------------------

_MESSAGES: list[dict[str, Any]] = [{"role": "user", "content": "hi"}]
_TOOLS: list[dict[str, Any]] = [{"type": "function", "function": {"name": "read_file"}}]


def _frozen_pre_change_payload(
    *, tools: bool, streaming: bool, temperature: float
) -> dict[str, Any]:
    """The pre-#416 payload shape, frozen from main (the fixture the pin
    asserts against). The pre-change builder emitted ``config.temperature``
    verbatim — the fixture mirrors that, so the pin is value-for-value."""
    payload: dict[str, Any] = {
        "model": "m",
        "messages": _MESSAGES,
        "temperature": temperature,
    }
    if tools:
        payload["tools"] = _TOOLS
        payload["tool_choice"] = "auto"
    if streaming:
        payload["stream"] = True
        payload["stream_options"] = {"include_usage": True}
    return payload


def _kill_switched_cfg() -> EngineConfig:
    """A config with the kill-switch armed: ``reasoning_effort_effective`` is
    ``None`` — the concrete "unset" case the spec's byte-identical claim is
    about (h1)."""
    cfg = EngineConfig.resolve(base_url="http://host:9999/v1", model="m")
    return dataclasses.replace(cfg, reasoning_effort="default")


# ── payload-equality pin: unset == frozen pre-change fixture ───────────────


@pytest.mark.parametrize(
    "tools,streaming",
    [
        (True, True),  # tools-on, streamed (the default headless shape)
        (True, False),  # tools-on, blocking (COLLEAGUE_STREAM=0)
        (False, True),  # tools-off, streamed (the deepthink seam)
        (False, False),  # tools-off, blocking
    ],
)
def test_unset_payload_equals_frozen_pre_change_fixture(
    monkeypatch: pytest.MonkeyPatch, tools: bool, streaming: bool
) -> None:
    """Kill-switched (unset) config → ``_build_chat_payload`` output equals
    the frozen pre-#416 fixture key-for-key and value-for-value, for all
    four shapes (c1/h1)."""
    if streaming:
        monkeypatch.delenv("COLLEAGUE_STREAM", raising=False)
    else:
        monkeypatch.setenv("COLLEAGUE_STREAM", "0")

    cfg = _kill_switched_cfg()
    assert cfg.reasoning_effort_effective is None  # sanity: really unset
    payload, got_streaming = VllmOpenAIEngine._build_chat_payload(
        cfg, _MESSAGES, _TOOLS if tools else []
    )
    assert got_streaming is streaming  # sanity: the shape we asked for
    assert payload == _frozen_pre_change_payload(
        tools=tools, streaming=streaming, temperature=cfg.temperature
    )
    assert "chat_template_kwargs" not in payload


# ── knob set: exactly one new key, nothing else moves ──────────────────────


@pytest.mark.parametrize("rung", ["off", "low", "medium", "high", "xhigh"])
def test_set_payload_gains_exactly_chat_template_kwargs(
    monkeypatch: pytest.MonkeyPatch, rung: str
) -> None:
    """With the knob set, the payload is the frozen pre-change fixture PLUS
    exactly one key — ``chat_template_kwargs`` — and no other key moves
    (c1/h1: the increment is one body key, nothing else)."""
    monkeypatch.delenv("COLLEAGUE_STREAM", raising=False)
    cfg = dataclasses.replace(
        EngineConfig.resolve(base_url="http://host:9999/v1", model="m"),
        reasoning_effort=rung,
    )
    payload, _streaming = VllmOpenAIEngine._build_chat_payload(cfg, _MESSAGES, [])
    frozen = _frozen_pre_change_payload(tools=False, streaming=True, temperature=cfg.temperature)
    assert set(payload) == set(frozen) | {"chat_template_kwargs"}
    for key, value in frozen.items():
        assert payload[key] == value
    if rung == "off":
        assert payload["chat_template_kwargs"] == {"enable_thinking": False}
    else:
        assert payload["chat_template_kwargs"] == {"reasoning_effort": rung}


# ---------------------------------------------------------------------------
# All-engines result-shape parity (c18/h14): the effort appears ONLY in the
# config snapshot, never in the TaskResult shape.
# ---------------------------------------------------------------------------


def _mock_vllm_http(monkeypatch: pytest.MonkeyPatch) -> None:
    """The same scripted two-turn vLLM HTTP as tests/test_e2e_mock.py (the
    mock engine is the contract reference; the vLLM driver runs over mocked
    HTTP — no network)."""
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
                                        {"path": "out.txt", "content": "from the model"}
                                    ),
                                },
                            }
                        ],
                    }
                }
            ],
            "usage": {"prompt_tokens": 7, "completion_tokens": 3},
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
                                    "arguments": json.dumps({"summary": "wrote out.txt"}),
                                },
                            }
                        ],
                    }
                }
            ],
            "usage": {"prompt_tokens": 4, "completion_tokens": 1},
        },
    ]
    state = {"i": 0}

    def fake_post(url: str, payload: dict, *, api_key: str, timeout: float) -> dict:
        turn = turns[min(state["i"], len(turns) - 1)]
        state["i"] += 1
        return turn

    monkeypatch.setattr(vllm_openai, "_post_json", fake_post)


def _drive_both_engines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cfg: EngineConfig
) -> tuple[dict[str, Any], dict[str, Any]]:
    _mock_vllm_http(monkeypatch)
    mock_repo = tmp_path / "mock"
    vllm_repo = tmp_path / "vllm"
    mock_repo.mkdir()
    vllm_repo.mkdir()
    mock_result = registry.load("mock").work(Task.new(str(mock_repo), "do work"), cfg)
    vllm_result = registry.load("vllm-openai").work(Task.new(str(vllm_repo), "do work"), cfg)
    assert mock_result.status == OK
    assert vllm_result.status == OK
    return mock_result.to_dict(), vllm_result.to_dict()


def test_result_key_sets_identical_across_engines_knob_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Knob unset (kill-switch): TaskResult ``to_dict()`` key sets are
    IDENTICAL on mock and vllm-openai (c18/h14)."""
    cfg = _kill_switched_cfg()
    mock_dict, vllm_dict = _drive_both_engines(tmp_path, monkeypatch, cfg)
    assert set(mock_dict) == set(vllm_dict)
    # The effort is absent from the RESULT shape on both engines …
    for d in (mock_dict, vllm_dict):
        assert "reasoning_effort" not in d
        assert "reasoning_effort_seats" not in d
    # … and present in the CONFIG SNAPSHOT on both (identical keys, h14).
    snap = cfg.to_dict()
    assert "reasoning_effort" in snap and "reasoning_effort_seats" in snap


def test_result_key_sets_identical_across_engines_knob_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Knob SET (a rung + a per-seat override): TaskResult ``to_dict()`` key
    sets are STILL identical on mock and vllm-openai — the effort only
    appears in the config snapshot, never in the result shape (c18/h14)."""
    cfg = dataclasses.replace(
        EngineConfig.resolve(base_url="http://host:9999/v1", model="m"),
        reasoning_effort="high",
        reasoning_effort_seats={"senses": "off"},
    )
    mock_dict, vllm_dict = _drive_both_engines(tmp_path, monkeypatch, cfg)
    assert set(mock_dict) == set(vllm_dict)
    for d in (mock_dict, vllm_dict):
        assert "reasoning_effort" not in d
        assert "reasoning_effort_seats" not in d
    # The config snapshot carries the SET values on both engines — the
    # snapshot is engine-independent (EngineConfig is shared).
    snap = cfg.to_dict()
    assert snap["reasoning_effort"] == "high"
    assert snap["reasoning_effort_seats"] == {"senses": "off"}
