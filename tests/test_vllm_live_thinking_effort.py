"""Live proof for the per-seat thinking effort (#416, plan t11 / spec c20).

Skipped unless ``COLLEAGUE_VLLM_E2E=1`` with a reachable rig (the same gate as
``tests/test_vllm_live.py``). Builds each seat's payload through colleague's
OWN builder (``VllmOpenAIEngine._build_chat_payload``) and posts it blocking
via ``_post_json`` so the assertion covers the real wire shape:

- a senses/Talker seat (table: ``off``) reports
  ``usage.completion_tokens_details.reasoning_tokens == 0``;
- a deepthink seat (table: ``xhigh``) reports ``> 0``;
- the acting seat (table: ``medium``) still forms a tool call.

Honesty (h16): tokens are read EXACTLY from ``usage``; when the served
checkpoint does not report ``completion_tokens_details`` the test reports
``unmeasured`` via ``pytest.skip`` — never a pass.
"""

from __future__ import annotations

import os

import pytest

from colleague import effort
from colleague.config import DeepthinkConfig, EngineConfig, SensesConfig
from colleague.deepthink import deepthink_engine_config
from colleague.engines.vllm_openai import (
    VllmOpenAIEngine,
    _blocking_payload,
    _post_json,
)
from colleague.senses import senses_engine_config
from colleague.tools import SCHEMAS

#: The rig env captured at import time — the suite's autouse ``_isolate_provider_env``
#: scrubs ``COLLEAGUE_*`` before every test (hermeticity), so a live proof must
#: restore the operator's rig variables itself. Run with e.g.
#: ``COLLEAGUE_VLLM_E2E=1 COLLEAGUE_BASE_URL=http://localhost:8001/v1
#: COLLEAGUE_API_KEY=… COLLEAGUE_MODEL=<served id>
#: uv run pytest tests/test_vllm_live_thinking_effort.py``.
_RIG_ENV = {k: v for k, v in os.environ.items() if k.startswith(("COLLEAGUE_", "CONVERTIBLE_"))}


@pytest.fixture(autouse=True)
def _restore_rig_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in _RIG_ENV.items():
        monkeypatch.setenv(key, value)


pytestmark = pytest.mark.skipif(
    "1" not in (os.environ.get("COLLEAGUE_VLLM_E2E"), os.environ.get("CONVERTIBLE_VLLM_E2E")),
    reason="set COLLEAGUE_VLLM_E2E=1 (with a live vLLM server) to run the live proof",
)

_ASK = [{"role": "user", "content": "Reply with exactly the single word: pong"}]
_TOOL_ASK = [{"role": "user", "content": "Read the file README.md using the read_file tool."}]


def _post(config: EngineConfig, messages, tools):
    payload, _streaming = VllmOpenAIEngine._build_chat_payload(config, messages, tools)
    payload = _blocking_payload(payload)
    payload["max_tokens"] = 2000
    url = f"{config.base_url.rstrip('/')}/chat/completions"
    data = _post_json(url, payload, api_key=config.api_key, timeout=config.timeout)
    return payload, data


def _reasoning_tokens(data) -> int:
    details = (data.get("usage") or {}).get("completion_tokens_details")
    if not isinstance(details, dict) or "reasoning_tokens" not in details:
        pytest.skip("unmeasured: the served checkpoint reports no completion_tokens_details")
    return int(details["reasoning_tokens"])


def _same_rig_seat(config: EngineConfig, cls):
    """A seat config on the SAME served model (the table row is what differs)."""
    return cls(
        model=config.model,
        base_url=config.base_url,
        api_key=config.api_key,
        context_budget=config.context_budget_tokens,
    )


def test_live_senses_seat_sends_thinking_off() -> None:
    base = EngineConfig.resolve()
    if base.senses is None:
        base.senses = _same_rig_seat(base, SensesConfig)
    seat = senses_engine_config(base)
    assert seat is not None
    payload, data = _post(seat, _ASK, [])
    assert payload.get("chat_template_kwargs") == {"enable_thinking": False}
    assert _reasoning_tokens(data) == 0


def test_live_deepthink_seat_keeps_full_thinking() -> None:
    base = EngineConfig.resolve()
    if base.deepthink is None:
        base.deepthink = _same_rig_seat(base, DeepthinkConfig)
    seat = deepthink_engine_config(base)
    assert seat is not None
    payload, data = _post(seat, _ASK, [])
    assert payload.get("chat_template_kwargs") == {"reasoning_effort": "xhigh"}
    assert _reasoning_tokens(data) > 0


def test_live_acting_seat_at_medium_forms_a_tool_call() -> None:
    base = EngineConfig.resolve()
    assert base.reasoning_effort_effective == effort.SEAT_TABLE["cortex"] == "medium"
    read_file = [s for s in SCHEMAS if s.get("function", {}).get("name") == "read_file"]
    assert read_file, "read_file schema missing"
    payload, data = _post(base, _TOOL_ASK, read_file)
    assert payload.get("chat_template_kwargs") == {"reasoning_effort": "medium"}
    message = data["choices"][0]["message"]
    calls = message.get("tool_calls") or []
    assert calls and calls[0]["function"]["name"] == "read_file"
