"""Tests for the dual-model "deepthink" escalation seam (plan task t2).

Three surfaces under test:

1. The vLLM engine's tools-off wire contract: an EMPTY offered-tools list omits
   BOTH "tools" and "tool_choice" from the payload; ``tools=None`` still sends
   the full SCHEMAS (the plan-mode byte-identical pin, issue #204).
2. ``colleague.deepthink.run_deepthink`` — exactly one tools-off completion,
   pre-request windowing to the deepthink model's own budget, and total
   degradation-never-raises for every failure mode.
3. ``colleague.deepthink.deepthink_engine_config`` and the new
   ``Engine.make_count_tokens`` seam (base char-heuristic default; vLLM's
   exact-or-estimate override).

No network: every engine is a fake or has its wire call monkeypatched.
"""

from __future__ import annotations

import urllib.error

import pytest

from colleague.config import DeepthinkConfig, EngineConfig
from colleague.context import count_tokens_chars
from colleague.contract import DeepthinkCall
from colleague.deepthink import DeepthinkResult, deepthink_engine_config, run_deepthink
from colleague.engine import Engine
from colleague.engines import vllm_openai
from colleague.engines.vllm_openai import VllmOpenAIEngine
from colleague.loop import ModelResponse
from colleague.registry import load
from colleague.tools import SCHEMAS

_URL = "http://localhost:8001/v1/chat/completions"


def _engine_config(**overrides) -> EngineConfig:
    defaults = dict(api_key="k", model="m", base_url="http://localhost:8001/v1")
    defaults.update(overrides)
    return EngineConfig.resolve(**defaults)


def _dual_config(**dt_overrides) -> EngineConfig:
    dt_defaults = dict(
        model="deepthink-model",
        base_url="http://localhost:8002/v1",
        api_key="dt-key",
        context_budget=1000,
    )
    dt_defaults.update(dt_overrides)
    return EngineConfig(deepthink=DeepthinkConfig(**dt_defaults))


# ---------------------------------------------------------------------------
# (1) tools-off on the wire
# ---------------------------------------------------------------------------


class TestToolsOffOnWire:
    def test_empty_tools_omits_tools_and_tool_choice(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict = {}

        def fake_post_json(url, payload, *, api_key, timeout):
            captured["payload"] = payload
            return {"choices": [{"message": {"content": "ok"}}], "usage": {}}

        monkeypatch.setattr(vllm_openai, "_post_json", fake_post_json)
        config = _engine_config()
        complete = VllmOpenAIEngine().make_complete(config, tools=[])
        complete([{"role": "user", "content": "hi"}])

        assert "tools" not in captured["payload"]
        assert "tool_choice" not in captured["payload"]

    def test_tools_none_still_sends_full_schemas(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Plan-mode byte-identical pin: omitting ``tools`` keeps today's behavior."""
        captured: dict = {}

        def fake_post_json(url, payload, *, api_key, timeout):
            captured["payload"] = payload
            return {"choices": [{"message": {"content": "ok"}}], "usage": {}}

        monkeypatch.setattr(vllm_openai, "_post_json", fake_post_json)
        config = _engine_config()
        complete = VllmOpenAIEngine().make_complete(config)  # tools=None (default)
        complete([{"role": "user", "content": "hi"}])

        assert captured["payload"]["tools"] == SCHEMAS
        assert captured["payload"]["tool_choice"] == "auto"


# ---------------------------------------------------------------------------
# Fake engine for exercising run_deepthink without any network
# ---------------------------------------------------------------------------


class _FakeEngine:
    """Records make_complete()/complete() calls; no network, fully scripted."""

    name = "fake"

    def __init__(self, response: ModelResponse | None = None, raise_on_complete=None) -> None:
        self.make_complete_calls: list[list[dict] | None] = []
        self.complete_call_count = 0
        self.captured_messages: list[dict] | None = None
        self._response = response or ModelResponse(
            content="the answer", prompt_tokens=5, completion_tokens=7
        )
        self._raise_on_complete = raise_on_complete

    def make_count_tokens(self, config: EngineConfig):
        def counter(messages: list[dict]) -> int:
            return sum(len(m.get("content") or "") for m in messages)

        return counter

    def make_complete(self, config: EngineConfig, tools=None):
        self.make_complete_calls.append(tools)

        def complete(messages: list[dict]) -> ModelResponse:
            self.complete_call_count += 1
            self.captured_messages = messages
            if self._raise_on_complete is not None:
                raise self._raise_on_complete
            return self._response

        return complete


# ---------------------------------------------------------------------------
# (2) run_deepthink — tools-off + exactly one completion
# ---------------------------------------------------------------------------


class TestRunDeepthinkToolsOffAndSingleCall:
    def test_make_complete_called_with_empty_tools(self) -> None:
        fake = _FakeEngine()
        config = _dual_config()

        result = run_deepthink(
            "a hard question",
            config=config,
            point="tool",
            engine_name="fake",
            engine_loader=lambda name: fake,
        )

        assert fake.make_complete_calls == [[]]
        assert fake.complete_call_count == 1
        assert result.call.degraded is False
        assert result.call.point == "tool"
        assert result.text == "the answer"
        assert result.call.tokens == 12  # 5 + 7, exact — never estimated
        assert result.call.duration is not None
        assert result.call.duration >= 0

    def test_result_is_deepthink_result_with_deepthink_call(self) -> None:
        fake = _FakeEngine()
        config = _dual_config()
        result = run_deepthink(
            "q",
            config=config,
            point="plan_proposal",
            engine_name="fake",
            engine_loader=lambda n: fake,
        )
        assert isinstance(result, DeepthinkResult)
        assert isinstance(result.call, DeepthinkCall)


# ---------------------------------------------------------------------------
# (3) windowing before the request
# ---------------------------------------------------------------------------


class TestWindowing:
    def _counter(self, messages: list[dict]) -> int:
        return sum(len(m.get("content") or "") for m in messages)

    def test_huge_question_is_truncated_under_send_budget(self) -> None:
        fake = _FakeEngine()
        config = _dual_config(context_budget=100)  # reserve=25, send_budget=75
        huge_question = "x" * 1000

        run_deepthink(
            huge_question,
            config=config,
            point="p",
            engine_name="fake",
            engine_loader=lambda n: fake,
            count_tokens=self._counter,
        )

        sent = fake.captured_messages
        assert sent is not None
        total_chars = sum(len(m.get("content") or "") for m in sent)
        assert total_chars <= 75
        assert "[deepthink digest truncated to fit budget]" in sent[-1]["content"]

    def test_small_question_passes_through_untouched(self) -> None:
        fake = _FakeEngine()
        config = _dual_config(context_budget=100000)
        small_question = "hi there"

        run_deepthink(
            small_question,
            config=config,
            point="p",
            engine_name="fake",
            engine_loader=lambda n: fake,
            count_tokens=self._counter,
        )

        sent = fake.captured_messages
        assert sent is not None
        assert sent[-1]["content"] == small_question
        assert "truncated" not in sent[-1]["content"]


# ---------------------------------------------------------------------------
# (4) degradation — never raises
# ---------------------------------------------------------------------------


class TestDegradation:
    def test_no_dual_config_degrades_immediately(self) -> None:
        config = EngineConfig()  # deepthink is None
        result = run_deepthink("q", config=config, point="p", engine_name="whatever")

        assert result.text == ""
        assert result.call.degraded is True
        assert result.call.point == "p"
        assert result.call.duration is not None
        assert result.call.duration >= 0

    def test_engine_loader_raising_degrades(self) -> None:
        config = _dual_config()

        def bad_loader(name: str):
            raise RuntimeError("no such engine")

        result = run_deepthink(
            "q", config=config, point="p", engine_name="dead", engine_loader=bad_loader
        )

        assert result.text == ""
        assert result.call.degraded is True
        assert result.call.duration is not None
        assert result.call.duration >= 0

    def test_complete_raising_url_error_degrades(self) -> None:
        fake = _FakeEngine(raise_on_complete=urllib.error.URLError("connection refused"))
        config = _dual_config()

        result = run_deepthink(
            "q", config=config, point="p", engine_name="fake", engine_loader=lambda n: fake
        )

        assert result.text == ""
        assert result.call.degraded is True
        assert result.call.duration is not None
        assert result.call.duration >= 0

    def test_complete_raising_timeout_degrades(self) -> None:
        fake = _FakeEngine(raise_on_complete=TimeoutError("timed out"))
        config = _dual_config()

        result = run_deepthink(
            "q", config=config, point="p", engine_name="fake", engine_loader=lambda n: fake
        )

        assert result.text == ""
        assert result.call.degraded is True

    def test_mock_engine_not_implemented_degrades_never_raises(self) -> None:
        config = _dual_config()

        result = run_deepthink(
            "q", config=config, point="p", engine_name="mock", engine_loader=load
        )

        assert result.text == ""
        assert result.call.degraded is True
        assert result.call.duration is not None
        assert result.call.duration >= 0


# ---------------------------------------------------------------------------
# deepthink_engine_config
# ---------------------------------------------------------------------------


class TestDeepthinkEngineConfig:
    def test_none_without_dual_config(self) -> None:
        config = EngineConfig()
        assert deepthink_engine_config(config) is None

    def test_maps_replaced_fields_and_inherits_the_rest(self) -> None:
        config = EngineConfig(
            model="main-model",
            base_url="http://main:8001/v1",
            api_key="main-key",
            max_steps=99,
            timeout=42.0,
            deepthink=DeepthinkConfig(
                model="dt-model",
                base_url="http://dt:8002/v1",
                api_key="dt-key",
                context_budget=12345,
            ),
        )

        dt_config = deepthink_engine_config(config)

        assert dt_config is not None
        assert dt_config.model == "dt-model"
        assert dt_config.base_url == "http://dt:8002/v1"
        assert dt_config.api_key == "dt-key"
        assert dt_config.context_budget_tokens == 12345
        # unrelated knobs inherit unchanged from the main config
        assert dt_config.max_steps == 99
        assert dt_config.timeout == 42.0


# ---------------------------------------------------------------------------
# Engine.make_count_tokens
# ---------------------------------------------------------------------------


class _StubEngine(Engine):
    name = "stub"

    def work(self, task, config):  # pragma: no cover - not exercised here
        raise NotImplementedError


class TestMakeCountTokens:
    def test_base_default_is_char_heuristic(self) -> None:
        engine = _StubEngine()
        counter = engine.make_count_tokens(EngineConfig())
        assert counter is count_tokens_chars

    def test_mock_engine_inherits_base_default(self) -> None:
        engine = load("mock")
        counter = engine.make_count_tokens(EngineConfig())
        assert counter is count_tokens_chars

    def test_vllm_override_returns_callable(self) -> None:
        engine = VllmOpenAIEngine()
        config = _engine_config()
        counter = engine.make_count_tokens(config)
        assert callable(counter)
        assert counter is not count_tokens_chars
