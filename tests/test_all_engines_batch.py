"""Batched tool execution across BOTH engines (plan task t17, spec c39/h28,
c19/h14, docs/specs/2026-08-27-adopt-from-qwen-code.md).

The mock engine gained an opt-in batch scenario in ``colleague/engines/
mock_scenarios.py`` — one turn carrying three read-only calls plus one
write, then a finish turn — so batched tool execution
(``colleague/toolbatch_loop.py``, plan task t15) is exercised on the
reference backend too, not only on ``vllm-openai``. This module:

1. proves mock and vllm-openai produce the IDENTICAL ``Step`` sequence
   (tool names, indices, ok flags) and the IDENTICAL ``TaskResult`` shape
   for the SAME batch turn, scripted from the ONE shared fixture in
   ``tests/_batch_fixture.py`` (h8: the mock stays the reference the live
   engine is compared against);
2. pins that the batch marker is opt-in — task text without it leaves the
   mock's default script byte-identical (c39's instruction);
3. is a diff-scope check on ``colleague/engines/vllm_openai.py``: its
   ``_build_chat_payload`` emits only OpenAI-surface keys (plus the #416
   ``chat_template_kwargs`` extension), and a multi-turn run makes exactly
   ONE ``/tokenize`` call — no per-turn tokenize call remains (c19/h14).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from colleague.config import EngineConfig
from colleague.contract import OK, Task
from colleague.engines import vllm_openai
from colleague.engines.mock import OUTPUT_FILE, MockEngine
from colleague.engines.vllm_openai import VllmOpenAIEngine
from tests._batch_fixture import (
    BATCH_TASK_INSTRUCTION,
    EXPECTED_STEP_SHAPE,
    make_batch_repo,
    step_shape,
    vllm_batch_turns,
)


def _key_shape(value):
    """Recursive key signature, ignoring concrete values (mirrors test_e2e_mock.py)."""
    if isinstance(value, dict):
        return {k: _key_shape(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return _key_shape(value[0]) if value else None
    return None


def _script_vllm_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    turns = vllm_batch_turns()
    state = {"i": 0}

    def fake_post(url: str, payload: dict, *, api_key: str, timeout: float) -> dict:
        turn = turns[min(state["i"], len(turns) - 1)]
        state["i"] += 1
        return turn

    monkeypatch.setattr(vllm_openai, "_post_json", fake_post)


# ---------------------------------------------------------------------------
# (1) identical Step sequence + result shape across engines, from ONE fixture
# ---------------------------------------------------------------------------


def test_mock_and_vllm_produce_identical_batch_step_sequence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _script_vllm_batch(monkeypatch)
    cfg = EngineConfig.resolve()

    mock_repo = make_batch_repo(tmp_path / "mock")
    vllm_repo = make_batch_repo(tmp_path / "vllm")

    mock_result = MockEngine().work(
        Task.new(str(mock_repo), BATCH_TASK_INSTRUCTION, engine="mock"), cfg
    )
    vllm_result = VllmOpenAIEngine().work(
        Task.new(str(vllm_repo), "identical batch task", engine="vllm-openai"), cfg
    )

    assert mock_result.status == OK
    assert vllm_result.status == OK

    # Tool names + ok flags, in request order.
    assert step_shape(mock_result) == list(EXPECTED_STEP_SHAPE)
    assert step_shape(vllm_result) == list(EXPECTED_STEP_SHAPE)

    # Indices, explicitly (the batch's parallel read section must still land
    # in request order — colleague/toolbatch_loop.py's bookkeeping pin).
    assert [s.index for s in mock_result.steps] == [0, 1, 2, 3, 4]
    assert [s.index for s in vllm_result.steps] == [0, 1, 2, 3, 4]

    # Result shape (TaskResult keys, recursively): identical across engines.
    assert _key_shape(mock_result.to_dict()) == _key_shape(vllm_result.to_dict())


def test_default_mock_scenario_is_unaffected_by_the_batch_scenario(tmp_path: Path) -> None:
    """A task without the batch marker keeps the default two-turn script (c39)."""
    result = MockEngine().work(
        Task.new(str(tmp_path), "no marker in this instruction"), EngineConfig.resolve()
    )
    assert result.status == OK
    assert result.changed_files == [OUTPUT_FILE]
    assert [s.tool for s in result.steps] == ["write_file", "finish"]


# ---------------------------------------------------------------------------
# (3) diff-scope: vllm_openai.py's payload stays OpenAI-surface + chat_template_kwargs,
# and no per-turn /tokenize call remains
# ---------------------------------------------------------------------------

#: The documented OpenAI-surface keys (CLAUDE.md's "vLLM adapter only touches
#: the OpenAI surface" convention) plus the #416 ``chat_template_kwargs``
#: extension — the one non-OpenAI key this adapter is allowed to send.
_ALLOWED_PAYLOAD_KEYS = {
    "model",
    "messages",
    "temperature",
    "tools",
    "tool_choice",
    "stream",
    "stream_options",
    "max_tokens",
    "chat_template_kwargs",
}


@pytest.mark.parametrize("offered_tools", [[], [{"type": "function", "function": {"name": "x"}}]])
def test_build_chat_payload_emits_only_openai_surface_keys(
    offered_tools: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COLLEAGUE_STREAM", "0")
    config = EngineConfig(base_url="http://example.invalid/v1", model="m", watch=False)
    payload, _streaming = VllmOpenAIEngine._build_chat_payload(
        config, [{"role": "user", "content": "hi"}], offered_tools
    )
    assert set(payload.keys()) <= _ALLOWED_PAYLOAD_KEYS, payload.keys()
    # tools/tool_choice are honestly paired: never one without the other.
    assert ("tools" in payload) == ("tool_choice" in payload) == bool(offered_tools)


def test_no_per_turn_tokenize_call_remains_for_a_three_turn_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reuses the counting fake vLLM rig from tests/test_tokenize_once.py (c19/h14):
    a run with several turns still makes exactly ONE ``/tokenize`` call."""
    from tests.test_tokenize_once import _config, _repo, _Rig, _three_turn_script

    monkeypatch.setenv("COLLEAGUE_STREAM", "0")
    monkeypatch.delenv("COLLEAGUE_EXACT_TOKENS", raising=False)
    repo = _repo(tmp_path)
    rig = _Rig(max_model_len=8192, turns=_three_turn_script(repo))
    with rig as base_url:
        config = _config(base_url, lint=False, affected_tests=False, testintegrity=False)
        result = VllmOpenAIEngine().work(
            Task(
                id="t17-batch-diff-scope",
                repo_path=str(repo),
                instruction="three turns",
                engine="vllm-openai",
            ),
            config,
        )
    assert result.status == OK
    assert rig.calls["/v1/chat/completions"] == 3
    assert rig.calls["/tokenize"] == 1
