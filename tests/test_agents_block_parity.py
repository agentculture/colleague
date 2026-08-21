"""All-engines parity for ``TaskResult.agents`` (#411, plan t13; spec c17/h24).

The SAME task driven through the real mock engine and the vLLM driver over a
fake transport: with ``config.agents`` ARMED both results carry the ``agents``
block with the IDENTICAL key shape (``mock`` is the contract reference, h8 —
the loop-side fold lands in t15 and must keep this parity); UNARMED the key
is absent on both and the overall result shape stays identical (the
``tests/test_e2e_mock.py`` guarantee, unchanged). Also pins that the mock
engine's ``work()`` accepts the profile-bearing child config the cross-role
subagent path builds (``subagents.ChildSpec.profile``), exactly as the vLLM
engine does — there is one shared ``subagents.py`` seam, no per-engine fork.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from colleague import registry
from colleague.agents.artifact_block import AGENTS_BLOCK_KEYS, empty_agents_block
from colleague.config import EngineConfig
from colleague.contract import OK, Task
from colleague.subagents import ChildSpec
from tests.test_e2e_mock import _key_shape, _mock_vllm_http


def _run_both(tmp_path: Path, cfg: EngineConfig):
    mock_repo = tmp_path / "mock"
    vllm_repo = tmp_path / "vllm"
    mock_repo.mkdir()
    vllm_repo.mkdir()
    mock_result = registry.load("mock").work(Task.new(str(mock_repo), "do work"), cfg)
    vllm_result = registry.load("vllm-openai").work(Task.new(str(vllm_repo), "do work"), cfg)
    return mock_result, vllm_result


def test_armed_agents_block_has_identical_key_shape_on_both_engines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_vllm_http(monkeypatch)
    cfg = dataclasses.replace(EngineConfig.resolve(), agents=True)
    assert cfg.agents is True

    mock_result, vllm_result = _run_both(tmp_path, cfg)
    assert mock_result.status == OK and vllm_result.status == OK

    # Both carry the key, both with the versioned shape.
    for result in (mock_result, vllm_result):
        assert result.agents is not None
        d = result.to_dict()
        assert "agents" in d
        assert tuple(d["agents"].keys()) == AGENTS_BLOCK_KEYS
        assert d["agents"]["version"] == 1
        # JSON-clean — the artifact writer serializes it verbatim.
        json.dumps(d["agents"])

    # The headline: identical key shape — on the block AND the whole result.
    assert _key_shape(mock_result.to_dict()["agents"]) == _key_shape(
        vllm_result.to_dict()["agents"]
    )
    assert _key_shape(mock_result.to_dict()) == _key_shape(vllm_result.to_dict())


def test_unarmed_omits_the_key_on_both_engines_byte_identically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_vllm_http(monkeypatch)
    cfg = EngineConfig.resolve()
    assert cfg.agents is False  # default-OFF (#411 t7)

    mock_result, vllm_result = _run_both(tmp_path, cfg)
    for result in (mock_result, vllm_result):
        assert result.agents is None
        assert "agents" not in result.to_dict()
        assert '"agents"' not in json.dumps(result.to_dict())
    assert _key_shape(mock_result.to_dict()) == _key_shape(vllm_result.to_dict())


def test_armed_engine_floor_is_the_empty_block_until_the_loop_authors_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Honest pin of what the engine-side fold claims TODAY: the armed key is
    the empty-lists floor (no invocation records are authored at the engine
    level — the loop-side wiring appends them; this test must be updated, not
    deleted, when it does)."""
    _mock_vllm_http(monkeypatch)
    cfg = dataclasses.replace(EngineConfig.resolve(), agents=True)
    mock_result, vllm_result = _run_both(tmp_path, cfg)
    assert mock_result.agents == empty_agents_block()
    assert vllm_result.agents == empty_agents_block()


def test_mock_work_accepts_the_profile_bearing_child_config(tmp_path: Path) -> None:
    """The mock honours the same ChildSpec profile/context_mode-bearing config
    shape as vllm-openai: a ``ChildSpec(profile=..., context_mode=...)`` is
    accepted, and a child config carrying ``agents=True`` run through the
    mock yields the armed block — no per-engine divergence."""
    spec = ChildSpec(profile="associate", context_mode="clear")
    assert spec.profile == "associate" and spec.context_mode == "clear"
    cfg = dataclasses.replace(EngineConfig.resolve(), agents=True)
    repo = tmp_path / "repo"
    repo.mkdir()
    result = registry.load("mock").work(Task.new(str(repo), "do work"), cfg)
    assert result.status == OK
    assert result.changed_files == ["colleague-mock.md"]
    assert result.agents is not None
    assert tuple(result.to_dict()["agents"].keys()) == AGENTS_BLOCK_KEYS
