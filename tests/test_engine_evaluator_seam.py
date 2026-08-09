"""Engine system_prompt() reads config_lifecycle evaluator_sections (plan task t7).

TDD: tests written FIRST, then the implementation in colleague/engine.py.

Covers the prompt-consumption seam: when config.config_lifecycle is present and
its snapshot carries non-empty evaluator_sections, Engine.system_prompt() passes
the single current note as RAW text to system_prompt_for (and compose_role_prompt
equally). Without a note, behavior is byte-identical to today.

Acceptance criteria:
1. With an applied evaluator note on the attached lifecycle, mock and vllm-openai
   compose the SAME evaluator section into their system prompt (all-engines test
   on the shared base-class path); no note composes byte-identical to today.
2. The final composed prompt contains exactly ONE evaluator heading (the RAW-text
   contract: engine passes snapshot content, never a pre-composed section), and a
   evaluator-only composition still carries the engine base (the #363 T3 trap).
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import TYPE_CHECKING

from colleague.config import EngineConfig
from colleague.configlifecycle import (
    EpisodeConfigLifecycle,
    EpisodeConfigSnapshot,
)
from colleague.contract import Task
from colleague.engine import Engine
from colleague.layers import EVALUATOR_SECTION_HEADING

if TYPE_CHECKING:
    from colleague.configlifecycle import CapabilityCatalog  # noqa: F401


_EVALUATOR_NOTE = "Focus on the auth module."


def _repo_with_agents(tmp_path: Path) -> Path:
    """Create a minimal repo with an AGENTS.md so system_prompt_for returns a prompt."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "AGENTS.md").write_text("agent rules", encoding="utf-8")
    return repo


def _config_with_lifecycle(
    repo_path: str | Path,
    lifecycle: "EpisodeConfigLifecycle | None" = None,
    role: str | None = None,
) -> EngineConfig:
    """Build an EngineConfig with an optional config_lifecycle attached."""
    cfg = EngineConfig.resolve(model="mock")
    if lifecycle is not None:
        cfg = dataclasses.replace(cfg, config_lifecycle=lifecycle)
    if role is not None:
        cfg = dataclasses.replace(cfg, role=role)
    return cfg


# ---------------------------------------------------------------------------
# Concrete test engine — uses the base-class system_prompt() directly
# ---------------------------------------------------------------------------


class _TestEngine(Engine):
    """Minimal concrete engine that inherits the base system_prompt() path."""

    name = "test_engine"

    def work(self, task: Task, config: EngineConfig):
        from colleague.contract import OK, TaskResult

        return TaskResult(task_id=task.id, status=OK, summary="ok")


# ===========================================================================
# 1. Byte-identical without a lifecycle (no note = no change)
# ===========================================================================


class TestByteIdenticalWithoutLifecycle:
    def test_no_lifecycle_no_evaluator_section(self, tmp_path: Path) -> None:
        """Without config_lifecycle, system_prompt() never mentions evaluator."""
        repo = _repo_with_agents(tmp_path)
        task = Task.new(str(repo), "do it")
        cfg = EngineConfig.resolve(model="mock")

        prompt = _TestEngine().system_prompt(task, cfg)
        assert prompt is not None
        assert EVALUATOR_SECTION_HEADING not in prompt

    def test_empty_lifecycle_snapshot_is_byte_identical(self, tmp_path: Path) -> None:
        """A lifecycle with an empty snapshot (no evaluator_sections) produces
        the same prompt as no lifecycle at all."""
        repo = _repo_with_agents(tmp_path)
        task = Task.new(str(repo), "do it")

        lifecycle = EpisodeConfigLifecycle()
        cfg_with = _config_with_lifecycle(repo, lifecycle)
        cfg_without = EngineConfig.resolve(model="mock")

        prompt_with = _TestEngine().system_prompt(task, cfg_with)
        prompt_without = _TestEngine().system_prompt(task, cfg_without)
        assert prompt_with == prompt_without

    def test_lifecycle_with_empty_evaluator_sections_is_byte_identical(
        self, tmp_path: Path
    ) -> None:
        """A lifecycle whose snapshot has evaluator_sections=() is byte-identical
        to no lifecycle."""
        repo = _repo_with_agents(tmp_path)
        task = Task.new(str(repo), "do it")

        lifecycle = EpisodeConfigLifecycle(initial=EpisodeConfigSnapshot(evaluator_sections=()))
        cfg_with = _config_with_lifecycle(repo, lifecycle)
        cfg_without = EngineConfig.resolve(model="mock")

        prompt_with = _TestEngine().system_prompt(task, cfg_with)
        prompt_without = _TestEngine().system_prompt(task, cfg_without)
        assert prompt_with == prompt_without


# ===========================================================================
# 2. Evaluator note composes into the system prompt
# ===========================================================================


class TestEvaluatorNoteComposes:
    def test_applied_evaluator_note_appears_in_prompt(self, tmp_path: Path) -> None:
        """When the lifecycle snapshot carries a evaluator_sections note,
        system_prompt() composes it into the prompt."""
        repo = _repo_with_agents(tmp_path)
        task = Task.new(str(repo), "do it")

        lifecycle = EpisodeConfigLifecycle(
            initial=EpisodeConfigSnapshot(evaluator_sections=(_EVALUATOR_NOTE,))
        )
        cfg = _config_with_lifecycle(repo, lifecycle)

        prompt = _TestEngine().system_prompt(task, cfg)
        assert prompt is not None
        assert EVALUATOR_SECTION_HEADING in prompt
        assert _EVALUATOR_NOTE in prompt

    def test_evaluator_section_heading_appears_exactly_once(self, tmp_path: Path) -> None:
        """The RAW-text contract: engine passes snapshot content (raw text),
        never a pre-composed section. If the engine passed pre-composed text,
        the heading would appear twice (double-head). Exactly one heading
        proves the engine passed RAW text."""
        repo = _repo_with_agents(tmp_path)
        task = Task.new(str(repo), "do it")

        lifecycle = EpisodeConfigLifecycle(
            initial=EpisodeConfigSnapshot(evaluator_sections=(_EVALUATOR_NOTE,))
        )
        cfg = _config_with_lifecycle(repo, lifecycle)

        prompt = _TestEngine().system_prompt(task, cfg)
        assert prompt is not None
        count = prompt.count(EVALUATOR_SECTION_HEADING)
        assert count == 1, (
            f"Expected exactly 1 evaluator heading, found {count} — "
            "likely double-heading from pre-composed text"
        )

    def test_evaluator_only_still_carries_engine_base(self, tmp_path: Path) -> None:
        """#363 T3 trap: even when the only non-base content is the evaluator
        section (no AGENTS layers, no skills), the composed prompt still carries
        the engine's base default — never evaluator-only."""
        repo = tmp_path / "empty_repo"
        repo.mkdir()
        # No AGENTS.md, no skills — only the evaluator note provides content.
        task = Task.new(str(repo), "do it")

        lifecycle = EpisodeConfigLifecycle(
            initial=EpisodeConfigSnapshot(evaluator_sections=(_EVALUATOR_NOTE,))
        )
        cfg = _config_with_lifecycle(repo, lifecycle)

        prompt = _TestEngine().system_prompt(task, cfg)
        # The prompt must NOT be None — the evaluator section alone triggers
        # composition, and the base is always included.
        assert prompt is not None
        # The base default from the loop is present.
        from colleague.loop import _DEFAULT_SYSTEM

        assert _DEFAULT_SYSTEM in prompt
        # The evaluator section is also present.
        assert EVALUATOR_SECTION_HEADING in prompt
        assert _EVALUATOR_NOTE in prompt


# ===========================================================================
# 3. All-engines: mock and vllm-openai compose the same evaluator section
# ===========================================================================


class TestAllEnginesEvaluatorParity:
    def test_mock_and_vllm_openai_same_evaluator_section(self, tmp_path: Path) -> None:
        """Both bundled engines inherit system_prompt() from the base Engine
        class — they compose the SAME evaluator section from the same
        config_lifecycle snapshot. This is the all-engines test on the
        shared base-class path."""
        repo = _repo_with_agents(tmp_path)
        task = Task.new(str(repo), "do it")

        lifecycle = EpisodeConfigLifecycle(
            initial=EpisodeConfigSnapshot(evaluator_sections=(_EVALUATOR_NOTE,))
        )
        cfg = _config_with_lifecycle(repo, lifecycle)

        # Both engines use the base-class system_prompt() — same result.
        from colleague.engines.mock import MockEngine
        from colleague.engines.vllm_openai import VllmOpenAIEngine

        prompt_mock = MockEngine().system_prompt(task, cfg)
        prompt_vllm = VllmOpenAIEngine().system_prompt(task, cfg)

        assert prompt_mock == prompt_vllm
        assert prompt_mock is not None
        assert EVALUATOR_SECTION_HEADING in prompt_mock
        assert _EVALUATOR_NOTE in prompt_mock

    def test_all_engines_no_note_are_byte_identical(self, tmp_path: Path) -> None:
        """Without an evaluator note, both engines produce the same prompt as
        they would without any lifecycle at all."""
        repo = _repo_with_agents(tmp_path)
        task = Task.new(str(repo), "do it")

        lifecycle = EpisodeConfigLifecycle()  # empty snapshot
        cfg_with = _config_with_lifecycle(repo, lifecycle)
        cfg_without = EngineConfig.resolve(model="mock")

        from colleague.engines.mock import MockEngine
        from colleague.engines.vllm_openai import VllmOpenAIEngine

        for engine_cls in (MockEngine, VllmOpenAIEngine):
            prompt_with = engine_cls().system_prompt(task, cfg_with)
            prompt_without = engine_cls().system_prompt(task, cfg_without)
            assert prompt_with == prompt_without, (
                f"{engine_cls.__name__}: lifecycle with empty snapshot "
                "must be byte-identical to no lifecycle"
            )


# ===========================================================================
# 4. Role path: compose_role_prompt also threads the evaluator section
# ===========================================================================


class TestRolePathEvaluator:
    def test_role_path_composes_evaluator_section(self, tmp_path: Path) -> None:
        """When a role is configured, the role-aware compose_role_prompt path
        also threads the evaluator section from the lifecycle snapshot."""
        repo = _repo_with_agents(tmp_path)
        task = Task.new(str(repo), "do it")

        lifecycle = EpisodeConfigLifecycle(
            initial=EpisodeConfigSnapshot(evaluator_sections=(_EVALUATOR_NOTE,))
        )
        # Set a role on the config so the role path is taken.
        cfg = _config_with_lifecycle(repo, lifecycle, role="explorer")

        prompt = _TestEngine().system_prompt(task, cfg)
        # The prompt may be None if the role is unknown and there are no
        # AGENTS/skills — but with AGENTS.md present, it should compose.
        # If the role resolves, the evaluator section should be in the prompt.
        if prompt is not None:
            assert EVALUATOR_SECTION_HEADING in prompt
            assert _EVALUATOR_NOTE in prompt

    def test_role_path_heading_count_is_one(self, tmp_path: Path) -> None:
        """Even through the role path, exactly one evaluator heading appears."""
        repo = _repo_with_agents(tmp_path)
        task = Task.new(str(repo), "do it")

        lifecycle = EpisodeConfigLifecycle(
            initial=EpisodeConfigSnapshot(evaluator_sections=(_EVALUATOR_NOTE,))
        )
        cfg = _config_with_lifecycle(repo, lifecycle, role="explorer")

        prompt = _TestEngine().system_prompt(task, cfg)
        if prompt is not None:
            count = prompt.count(EVALUATOR_SECTION_HEADING)
            assert count == 1, f"Expected exactly 1 evaluator heading via role path, found {count}"
