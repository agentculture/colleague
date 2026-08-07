"""Tests for colleague.distill — the distillation child entry (plan task t10).

Covers the acceptance criteria:

1. Author resolves BY ROLE: lobes cortex when armed, deepthink/muse target in
   dual-model mode, unarmed = no completion and the rung-1 floor byte-identical.
2. The child detaches via the sanctioned one-shot pattern (start_new_session,
   no wait/poll — boundary test extended); outcome diagnosable as
   pending/done/dead from an outcome marker; a killed child leaves no partial
   record (validate-then-single-remember, atomic).
3. The run's return is never blocked by distillation.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from colleague import background, distill, lessons

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class FakeEngineConfig:
    """Minimal engine config for testing role resolution."""

    deepthink: Any = None
    model: str = "main-model"
    base_url: str = "http://localhost:8001/v1"
    api_key: str = "test"
    context_budget_tokens: int = 48000


@dataclass
class FakeRoleInfo:
    """Minimal role info for testing."""

    model: str = "cortex-model"
    endpoint: str = "http://localhost:8001"
    path: str = "/v1"
    context: int = 65536
    ready: bool = True
    responsibilities: tuple[str, ...] = ()
    forbidden_responsibilities: tuple[str, ...] = ()


@dataclass
class FakeLobesRoles:
    """Minimal lobes roles for testing."""

    cortex: FakeRoleInfo = field(default_factory=FakeRoleInfo)
    senses: FakeRoleInfo = field(default_factory=FakeRoleInfo)
    muse: FakeRoleInfo | None = None


def _make_fake_result(task_id: str = "test-123", status: str = "ok") -> Any:
    """Build a minimal TaskResult-like object for testing."""
    from colleague.contract import TaskResult, WorkStats

    result = TaskResult(task_id=task_id, status=status, summary="test summary")
    result.stats = WorkStats()
    result.stats.step_count = 5
    result.stats.tool_counts = {"read_file": 3, "edit_file": 2}
    result.changed_files = ["foo.py"]
    return result


# ===========================================================================
# AC1 — Author resolves BY ROLE
# ===========================================================================


class TestResolveDistillAuthor:
    """The distillation author resolves by role precedence (c16, h13)."""

    def test_lobes_cortex_when_armed(self) -> None:
        """When lobes is armed, the cortex role is the distillation author."""
        roles = FakeLobesRoles()
        config = FakeEngineConfig()

        author = distill.resolve_distill_author(config, roles)
        assert author is not None
        assert author.model == roles.cortex.model
        assert author.base_url == roles.cortex.endpoint

    def test_deepthink_muse_wins_over_cortex_in_dual_model(self) -> None:
        """In dual-model mode, the deepthink/muse target is the author, not cortex."""
        roles = FakeLobesRoles(muse=FakeRoleInfo(model="muse-model", endpoint="http://muse:8001"))
        config = FakeEngineConfig(
            deepthink=MagicMock(
                model="muse-model",
                base_url="http://muse:8001/v1",
                api_key="key",
                context_budget=48000,
            )
        )

        author = distill.resolve_distill_author(config, roles)
        assert author is not None
        assert author.model == "muse-model"

    def test_unarmed_yields_none(self) -> None:
        """When no lobes and no deepthink config, the author is None — rung-1 floor."""
        roles = None
        config = FakeEngineConfig()

        author = distill.resolve_distill_author(config, roles)
        assert author is None

    def test_no_deepthink_uses_cortex(self) -> None:
        """Without deepthink config but with lobes, cortex is the author."""
        roles = FakeLobesRoles()
        config = FakeEngineConfig(deepthink=None)

        author = distill.resolve_distill_author(config, roles)
        assert author is not None
        assert author.model == roles.cortex.model

    def test_env_config_always_wins(self) -> None:
        """An explicit env/config model pin always wins over lobes resolution."""
        roles = FakeLobesRoles(
            cortex=FakeRoleInfo(model="lobes-cortex"),
            muse=FakeRoleInfo(model="lobes-muse"),
        )
        # Simulate an explicit deepthink model from env/config that overrides lobes
        config = FakeEngineConfig(
            deepthink=MagicMock(
                model="env-pinned-model",
                base_url="http://env:8001/v1",
                api_key="key",
                context_budget=48000,
            )
        )

        author = distill.resolve_distill_author(config, roles)
        assert author is not None
        assert author.model == "env-pinned-model"


# ===========================================================================
# AC2 — Child detaches via sanctioned one-shot pattern
# ===========================================================================


class TestDetachDistillChild:
    """The distillation child detaches via background.spawn_background (c31, h26)."""

    def test_detach_uses_spawn_background(self, tmp_path: Path) -> None:
        """The child is launched via background.spawn_background, not a direct Popen."""
        repo = tmp_path / "repo"
        repo.mkdir()
        artifact_dir = repo / ".colleague"
        artifact_dir.mkdir()

        # Write a fake artifact
        result = _make_fake_result()
        artifact_path = artifact_dir / "test-123.test-summary.json"
        artifact_path.write_text(json.dumps(result.to_dict()), encoding="utf-8")

        with patch.object(background, "spawn_background") as mock_spawn:
            mock_spawn.return_value = background.BackgroundHandle(
                id="distill-handle",
                pid=99999,
                log_dir=".colleague/background/distill-handle/",
                flight="distill-flight",
            )

            distill.detach_distill_child(
                repo_path=repo,
                task_id="test-123",
                author_model="test-model",
                author_base_url="http://localhost:8001/v1",
                author_api_key="test-key",
            )

            mock_spawn.assert_called_once()
            call_args = mock_spawn.call_args
            # Verify start_new_session is used (via spawn_background, not direct Popen)
            assert call_args[0][0] == repo  # repo_path
            argv = call_args[0][1]
            assert "work" in argv or "distill" in " ".join(argv)

    def test_detach_is_one_shot_no_wait_no_poll(self) -> None:
        """The detach function returns immediately — no .wait() or .poll() calls."""
        # The function should not block; it delegates to spawn_background which
        # is the sanctioned one-shot pattern. Verify the source code has no
        # .wait() or .poll() calls.
        source = Path(distill.__file__).read_text(encoding="utf-8")
        assert ".wait(" not in source, "distill.py must not call .wait() (one-shot)"
        assert ".poll(" not in source, "distill.py must not call .poll() (one-shot)"

    def test_detach_builds_correct_argv(self, tmp_path: Path) -> None:
        """The child argv re-invokes colleague with the distillation subcommand."""
        repo = tmp_path / "repo"
        repo.mkdir()
        artifact_dir = repo / ".colleague"
        artifact_dir.mkdir()

        result = _make_fake_result()
        artifact_path = artifact_dir / "test-123.test-summary.json"
        artifact_path.write_text(json.dumps(result.to_dict()), encoding="utf-8")

        with patch.object(background, "spawn_background") as mock_spawn:
            mock_spawn.return_value = background.BackgroundHandle(
                id="h1", pid=1, log_dir=".colleague/background/h1/", flight="f1"
            )

            distill.detach_distill_child(
                repo_path=repo,
                task_id="test-123",
                author_model="test-model",
                author_base_url="http://localhost:8001/v1",
                author_api_key="test-key",
            )

            argv = mock_spawn.call_args[0][1]
            # The child should re-invoke the colleague CLI
            assert argv[0] == sys.executable
            assert "-m" in argv and "colleague" in argv


# ===========================================================================
# AC3 — Run's return is never blocked by distillation
# ===========================================================================


class TestNonBlockingDistillation:
    """The run's return is never blocked by distillation (c31)."""

    def test_distill_fn_returns_immediately(self, tmp_path: Path) -> None:
        """The distill_fn callable returns immediately after detaching the child."""
        repo = tmp_path / "repo"
        repo.mkdir()
        artifact_dir = repo / ".colleague"
        artifact_dir.mkdir()

        result = _make_fake_result()
        artifact_path = artifact_dir / "test-123.test-summary.json"
        artifact_path.write_text(json.dumps(result.to_dict()), encoding="utf-8")

        with patch.object(background, "spawn_background") as mock_spawn:
            mock_spawn.return_value = background.BackgroundHandle(
                id="h1", pid=1, log_dir=".colleague/background/h1/", flight="f1"
            )

            distill_fn = distill.make_distill_fn(
                repo_path=repo,
                author_model="test-model",
                author_base_url="http://localhost:8001/v1",
                author_api_key="test-key",
            )

            # This should return immediately (non-blocking)
            start = time.monotonic()
            result_text = distill_fn(result, "test request")
            elapsed = time.monotonic() - start

            # Should return within 100ms (the child is detached, not waited on)
            assert elapsed < 0.1, f"distill_fn took {elapsed:.3f}s — should be non-blocking"
            # Returns None (the raw text is written by the child, not returned)
            assert result_text is None

    def test_no_author_returns_none_immediately(self) -> None:
        """When no author is resolved, distill_fn is None — rung-1 floor."""
        distill_fn = distill.make_distill_fn(
            repo_path="/tmp/repo",
            author_model=None,
            author_base_url=None,
            author_api_key=None,
        )
        assert distill_fn is None

    def test_distill_fn_never_raises(self, tmp_path: Path) -> None:
        """distill_fn never raises — any failure is caught and the child is detached."""
        repo = tmp_path / "repo"
        repo.mkdir()

        with patch.object(background, "spawn_background") as mock_spawn:
            mock_spawn.side_effect = RuntimeError("spawn failed")

            distill_fn = distill.make_distill_fn(
                repo_path=repo,
                author_model="test-model",
                author_base_url="http://localhost:8001/v1",
                author_api_key="test-key",
            )

            # Should not raise
            result_text = distill_fn(_make_fake_result(), "request")
            assert result_text is None


# ===========================================================================
# Outcome marker: pending/done/dead diagnosis
# ===========================================================================


class TestOutcomeMarker:
    """Outcome diagnosable as pending/done/dead from an outcome marker (h26)."""

    def test_outcome_marker_path(self, tmp_path: Path) -> None:
        """The outcome marker is written next to the artifact."""
        repo = tmp_path / "repo"
        repo.mkdir()
        artifact_dir = repo / ".colleague"
        artifact_dir.mkdir()

        result = _make_fake_result()
        artifact_path = artifact_dir / "test-123.test-summary.json"
        artifact_path.write_text(json.dumps(result.to_dict()), encoding="utf-8")

        outcome_path = distill.outcome_marker_path(artifact_path)
        assert outcome_path is not None
        assert str(outcome_path).endswith(".distill.json")

    def test_outcome_marker_pending(self, tmp_path: Path) -> None:
        """A freshly detached child writes a pending outcome marker."""
        marker_path = tmp_path / "test-123.test-summary.distill.json"
        distill.write_outcome_marker(marker_path, status="pending", pid=12345)

        data = json.loads(marker_path.read_text(encoding="utf-8"))
        assert data["status"] == "pending"
        assert data["pid"] == 12345

    def test_outcome_marker_done(self, tmp_path: Path) -> None:
        """A completed child writes a done outcome marker with the lesson."""
        marker_path = tmp_path / "test-123.test-summary.distill.json"
        lesson = {"cause": "test", "lesson": "learned", "next_delta": "improve"}
        distill.write_outcome_marker(marker_path, status="done", lesson=lesson)

        data = json.loads(marker_path.read_text(encoding="utf-8"))
        assert data["status"] == "done"
        assert data["lesson"] == lesson

    def test_outcome_marker_dead(self, tmp_path: Path) -> None:
        """A killed child writes a dead outcome marker."""
        marker_path = tmp_path / "test-123.test-summary.distill.json"
        distill.write_outcome_marker(marker_path, status="dead", reason="killed")

        data = json.loads(marker_path.read_text(encoding="utf-8"))
        assert data["status"] == "dead"
        assert data["reason"] == "killed"

    def test_read_outcome_marker_pending(self, tmp_path: Path) -> None:
        """Reading a pending marker returns 'pending'."""
        marker_path = tmp_path / "test-123.test-summary.distill.json"
        distill.write_outcome_marker(marker_path, status="pending", pid=12345)

        status = distill.read_outcome_status(marker_path)
        assert status == "pending"

    def test_read_outcome_marker_done(self, tmp_path: Path) -> None:
        """Reading a done marker returns 'done'."""
        marker_path = tmp_path / "test-123.test-summary.distill.json"
        distill.write_outcome_marker(marker_path, status="done")

        status = distill.read_outcome_status(marker_path)
        assert status == "done"

    def test_read_outcome_marker_missing(self, tmp_path: Path) -> None:
        """Reading a missing marker returns None."""
        marker_path = tmp_path / "nonexistent.distill.json"
        status = distill.read_outcome_status(marker_path)
        assert status is None

    def test_read_outcome_marker_corrupt(self, tmp_path: Path) -> None:
        """Reading a corrupt marker returns None."""
        marker_path = tmp_path / "corrupt.distill.json"
        marker_path.write_text("{not valid json", encoding="utf-8")

        status = distill.read_outcome_status(marker_path)
        assert status is None


# ===========================================================================
# Killed child leaves no partial record (atomic validate-then-remember)
# ===========================================================================


class TestAtomicLessonUpsert:
    """A killed child leaves no partial record — validate-then-single-remember (h26)."""

    def test_upsert_lesson_validates_before_remember(self, tmp_path: Path) -> None:
        """The lesson is validated before being remembered — atomic upsert."""
        repo = tmp_path / "repo"
        repo.mkdir()

        valid_lesson = {"cause": "x", "lesson": "y", "next_delta": "z"}
        with patch("colleague.memory.remember") as mock_remember:
            mock_remember.return_value = True

            distill.upsert_lesson(repo, "test-123", valid_lesson)
            mock_remember.assert_called_once()

    def test_upsert_lesson_refuses_invalid(self, tmp_path: Path) -> None:
        """An invalid lesson is never remembered — no partial record."""
        repo = tmp_path / "repo"
        repo.mkdir()

        invalid_lesson = {"cause": "x"}  # missing required keys
        with patch("colleague.memory.remember") as mock_remember:
            distill.upsert_lesson(repo, "test-123", invalid_lesson)
            mock_remember.assert_not_called()

    def test_upsert_lesson_uses_same_work_lesson_id(self, tmp_path: Path) -> None:
        """The upsert uses the SAME work-lesson id as the rung-1 record."""
        repo = tmp_path / "repo"
        repo.mkdir()

        valid_lesson = {"cause": "x", "lesson": "y", "next_delta": "z"}
        with patch("colleague.memory.remember") as mock_remember:
            mock_remember.return_value = True

            distill.upsert_lesson(repo, "test-123", valid_lesson)

            call_args = mock_remember.call_args
            record = call_args[0][1]
            assert record["id"] == "work-lesson-test-123"
            assert record["type"] == "work-lesson"


# ===========================================================================
# Boundary: distill.py confined to one-shot detach
# ===========================================================================


class TestDistillBoundary:
    """distill.py boundary checks (mirrors test_boundary.py patterns)."""

    def test_distill_module_has_no_forbidden_primitives(self) -> None:
        """distill.py must not use socket, asyncio, threading, or direct subprocess."""
        source = Path(distill.__file__).read_text(encoding="utf-8")
        for forbidden in (
            "import socket",
            "import asyncio",
            "import threading",
            "concurrent.futures",
            "import subprocess",
            ".wait(",
            ".poll(",
        ):
            assert (
                forbidden not in source
            ), f"distill.py must not use {forbidden!r} (one-shot, no daemon)"

    def test_distill_module_imports_stdlib_only(self) -> None:
        """Importing colleague.distill introduces no third-party module."""
        before = set(sys.modules.keys())
        import colleague.distill as _distill  # noqa: F401

        _distill.resolve_distill_author(FakeEngineConfig(), None)

        new_top_level = {name.split(".")[0] for name in (set(sys.modules.keys()) - before) if name}
        third_party = []
        for name in sorted(new_top_level):
            is_stdlib = name in sys.stdlib_module_names
            is_colleague = name.startswith("colleague")
            is_builtin = name.startswith("_")
            if not (is_stdlib or is_colleague or is_builtin):
                third_party.append(name)
        assert not third_party, f"colleague.distill leaked third-party imports: {third_party}"


# ===========================================================================
# Integration: make_distill_fn + resolve_distill_author together
# ===========================================================================


class TestDistillIntegration:
    """Integration tests for the distillation child entry."""

    def test_make_distill_fn_with_author(self, tmp_path: Path) -> None:
        """make_distill_fn returns a callable when an author is resolved."""
        repo = tmp_path / "repo"
        repo.mkdir()

        distill_fn = distill.make_distill_fn(
            repo_path=repo,
            author_model="test-model",
            author_base_url="http://localhost:8001/v1",
            author_api_key="test-key",
        )
        assert distill_fn is not None
        assert callable(distill_fn)

    def test_make_distill_fn_without_author(self) -> None:
        """make_distill_fn returns None when no author is resolved."""
        distill_fn = distill.make_distill_fn(
            repo_path="/tmp/repo",
            author_model=None,
            author_base_url=None,
            author_api_key=None,
        )
        assert distill_fn is None

    def test_resolve_distill_author_with_lobes_roles(self) -> None:
        """resolve_distill_author works with real lobes LobesRoles."""
        from colleague.lobes import LobesRoles, RoleInfo

        roles = LobesRoles(
            cortex=RoleInfo(
                model="cortex-m",
                endpoint="http://cortex:8001",
                path="/v1",
                context=65536,
                ready=True,
                responsibilities=(),
                forbidden_responsibilities=(),
            ),
            senses=RoleInfo(
                model="senses-m",
                endpoint="http://senses:8001",
                path="/v1",
                context=32768,
                ready=True,
                responsibilities=(),
                forbidden_responsibilities=(),
            ),
        )
        config = FakeEngineConfig()

        author = distill.resolve_distill_author(config, roles)
        assert author is not None
        assert author.model == "cortex-m"

    def test_resolve_distill_author_muse_overrides_cortex(self) -> None:
        """When muse is present and deepthink is configured, muse is the author."""
        from colleague.lobes import LobesRoles, RoleInfo

        roles = LobesRoles(
            cortex=RoleInfo(
                model="cortex-m",
                endpoint="http://cortex:8001",
                path="/v1",
                context=65536,
                ready=True,
                responsibilities=(),
                forbidden_responsibilities=(),
            ),
            senses=RoleInfo(
                model="senses-m",
                endpoint="http://senses:8001",
                path="/v1",
                context=32768,
                ready=True,
                responsibilities=(),
                forbidden_responsibilities=(),
            ),
            muse=RoleInfo(
                model="muse-m",
                endpoint="http://muse:8001",
                path="/v1",
                context=65536,
                ready=True,
                responsibilities=(),
                forbidden_responsibilities=(),
            ),
        )
        config = FakeEngineConfig(
            deepthink=MagicMock(
                model="muse-m",
                base_url="http://muse:8001/v1",
                api_key="key",
                context_budget=48000,
            )
        )

        author = distill.resolve_distill_author(config, roles)
        assert author is not None
        assert author.model == "muse-m"
