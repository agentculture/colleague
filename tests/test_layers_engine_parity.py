"""All-engines rule for layered config: AGENTS/skills injection is identical
across the mock and vllm-openai engines (the contract holds for every engine).

Acceptance:
1. For the same model + same AGENTS/skills files, both engines pass an identical
   ``system_prompt`` to ``loop.run`` — and it carries the layered content.
2. With no layer files, both engines pass an IDENTICAL composed prompt — the
   loop's ``_DEFAULT_SYSTEM`` base plus the acting seat's writer prompt
   fragment.

   Updated by plan t5 (``docs/plans/2026-08-29-purpose-tools-get-chosen.md``,
   prompt/surface unification): this used to be ``system_prompt=None`` on both
   engines, because ``Engine.system_prompt`` read ``config.role`` by NAME and a
   bare run has none. The acting seat's TOOL surface has been the writer's
   since deviation d14 (``colleague.actingsurface.curate_for_depth``), so the
   roleless prompt made the two halves disagree about which role was acting.
   Both halves now read the SAME resolution
   (``actingsurface.acting_role_name`` → ``loop.resolve_role`` →
   ``curate_for_depth``), so a bare run composes the writer's fragment exactly
   as an explicit ``--role writer`` run does. The all-engines invariant this
   file exists to protect — mock and vllm-openai inject the SAME prompt —
   is unchanged and still asserted.
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


def _capture_both(monkeypatch, repo: Path, model: str, role: str | None = None) -> dict:
    captured: dict = {}
    monkeypatch.setattr(mock_mod, "run", _spy_run(captured, "mock"))
    monkeypatch.setattr(vllm_mod, "run", _spy_run(captured, "vllm"))

    config = EngineConfig(model=model, role=role)
    task = _make_task(repo)
    MockEngine().work(task, config)
    VllmOpenAIEngine().work(task, config)
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


def test_engines_inject_identical_acting_seat_prompt_when_no_layers(
    tmp_path: Path, monkeypatch
) -> None:
    """No layer files: both engines inject the SAME composed prompt — the
    base plus the acting seat's writer fragment (plan t5; was ``None`` on both
    before the prompt/surface unification, see this module's docstring)."""
    from colleague.roles import BUILTIN_ROLES

    repo = tmp_path / "repo"
    repo.mkdir()

    captured = _capture_both(monkeypatch, repo, "Qwen/Qwen3-32B")

    assert captured["mock"] == captured["vllm"]
    assert captured["mock"] is not None
    assert captured["mock"].startswith(_DEFAULT_SYSTEM)
    assert captured["mock"].endswith(BUILTIN_ROLES["writer"].prompt_fragment)


def test_bare_run_and_explicit_writer_role_compose_the_same_prompt(
    tmp_path: Path, monkeypatch
) -> None:
    """Plan t5, acceptance 1 (prompt half): a bare run (``role=None``) and an
    explicit ``--role writer`` run compose an IDENTICAL system prompt, on both
    engines, with an operator overlay present and without one."""
    repo = tmp_path / "repo"
    repo.mkdir()

    bare = _capture_both(monkeypatch, repo, "Qwen/Qwen3-32B")
    explicit = _capture_both(monkeypatch, repo, "Qwen/Qwen3-32B", role="writer")

    assert bare["mock"] == explicit["mock"] == bare["vllm"] == explicit["vllm"]
    assert bare["mock"] is not None


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
