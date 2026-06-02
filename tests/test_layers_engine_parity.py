"""All-engines rule for layered config: AGENTS/skills injection is identical
across the mock and vllm-openai engines (the contract holds for every engine).

Acceptance:
1. For the same model + same AGENTS/skills files, both engines pass an identical
   ``system_prompt`` to ``loop.run`` — and it carries the layered content.
2. With no layer files, both engines pass ``system_prompt=None`` (byte-identical
   to the layer-free behavior the loop falls back to).
"""

from __future__ import annotations

from pathlib import Path

import colleague.engines.mock as mock_mod
import colleague.engines.vllm_openai as vllm_mod
from colleague.config import EngineConfig
from colleague.contract import TaskResult
from colleague.engines.mock import MockEngine
from colleague.engines.vllm_openai import VllmOpenAIEngine
from colleague.loop import _DEFAULT_SYSTEM


def _make_task(repo: Path):
    from colleague.contract import Task

    return Task(id="parity-1", repo_path=str(repo), instruction="do a thing")


def _spy_run(captured: dict, key: str):
    def spy(complete, task, *, max_steps, system_prompt=None, **kwargs):
        captured[key] = system_prompt
        return TaskResult(task_id=task.id, status="ok")

    return spy


def _capture_both(monkeypatch, repo: Path, model: str) -> dict:
    captured: dict = {}
    monkeypatch.setattr(mock_mod, "run", _spy_run(captured, "mock"))
    monkeypatch.setattr(vllm_mod, "run", _spy_run(captured, "vllm"))

    config = EngineConfig(model=model)
    task = _make_task(repo)
    MockEngine().drive(task, config)
    VllmOpenAIEngine().drive(task, config)
    return captured


def test_engines_inject_identical_system_prompt(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "AGENTS.md").write_text("Begin every summary with [AGENTS-OK].", encoding="utf-8")

    captured = _capture_both(monkeypatch, repo, "Qwen/Qwen3-32B")

    assert captured["mock"] == captured["vllm"]
    assert captured["mock"] is not None
    assert "[AGENTS-OK]" in captured["mock"]
    assert captured["mock"].startswith(_DEFAULT_SYSTEM)


def test_engines_inject_none_when_no_layers(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    captured = _capture_both(monkeypatch, repo, "Qwen/Qwen3-32B")

    assert captured["mock"] is None
    assert captured["vllm"] is None


def test_engine_system_prompt_helper_matches_across_engines(tmp_path: Path) -> None:
    """The base-class helper itself returns the same value for both engines."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "AGENTS.md").write_text("shared rule", encoding="utf-8")

    config = EngineConfig(model="Qwen/Qwen3-32B")
    task = _make_task(repo)
    assert MockEngine().system_prompt(task, config) == VllmOpenAIEngine().system_prompt(
        task, config
    )
