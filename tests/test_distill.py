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
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from colleague import background, distill

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
# AC3 (t4, spec c38/h30) — evaluator and distiller are distinct authority
# contracts even on a shared checkpoint. This pins the guard AT THE
# RESOLUTION SEAM ahead of t12's real arming: no config path sets
# ``evaluator_checkpoint``/``distiller_checkpoint`` today, so these tests
# declare them directly on a stand-in config object (duck-typed via
# getattr) — the same forward-compat shape a later t12 wiring would use.
# ===========================================================================


class TestEvaluatorDistillerAuthoritySplit:
    """resolve_distill_author refuses a declared evaluator seat as distiller
    unless a distinct distiller authority is declared (c38/h30)."""

    def test_refuses_cortex_when_it_is_the_declared_evaluator_seat(self) -> None:
        """cortex would normally author (test_no_deepthink_uses_cortex above);
        armed-evaluation mode must NOT silently reuse that seat as distiller."""
        roles = FakeLobesRoles(cortex=FakeRoleInfo(model="shared-checkpoint"))
        config = FakeEngineConfig(deepthink=None)
        config.evaluator_checkpoint = "shared-checkpoint"  # armed, no distinct distiller

        author = distill.resolve_distill_author(config, roles)
        assert author is None  # refused — falls to the rung-1 floor, never write memory

    def test_distinct_distiller_checkpoint_lifts_the_refusal(self) -> None:
        """A distiller checkpoint distinct from the evaluator's is honored:
        the guard only blocks the UNDECLARED case, never a genuinely
        separated authority."""
        roles = FakeLobesRoles(cortex=FakeRoleInfo(model="shared-checkpoint"))
        config = FakeEngineConfig(deepthink=None)
        config.evaluator_checkpoint = "shared-checkpoint"
        config.distiller_checkpoint = "a-genuinely-different-checkpoint"

        author = distill.resolve_distill_author(config, roles)
        assert author is not None  # a distinct distiller authority was declared

    def test_no_evaluator_declared_is_byte_identical(self) -> None:
        """With no evaluator/distiller declaration at all (today, always),
        cortex resolves exactly as it did before this guard existed."""
        roles = FakeLobesRoles(cortex=FakeRoleInfo(model="shared-checkpoint"))
        config = FakeEngineConfig(deepthink=None)

        author = distill.resolve_distill_author(config, roles)
        assert author is not None
        assert author.model == "shared-checkpoint"

    def test_deepthink_still_wins_over_a_refused_evaluator_seat(self) -> None:
        """Precedence is untouched by the guard: deepthink/muse beats cortex
        regardless of the evaluator/distiller declaration."""
        roles = FakeLobesRoles(cortex=FakeRoleInfo(model="shared-checkpoint"))
        config = FakeEngineConfig(
            deepthink=MagicMock(
                model="muse-model",
                base_url="http://muse:8001/v1",
                api_key="key",
                context_budget=48000,
            )
        )
        config.evaluator_checkpoint = "shared-checkpoint"

        author = distill.resolve_distill_author(config, roles)
        assert author is not None
        assert author.model == "muse-model"

    def test_from_config_twin_applies_the_same_guard(self) -> None:
        """resolve_distill_author_from_config (the t16 config-only seam) is
        guarded identically for the armed-lobes-main-model rung."""
        from colleague.distill import resolve_distill_author_from_config

        class _Cfg:
            deepthink = None
            model = "shared-checkpoint"
            base_url = "http://gw:1/v1"
            api_key = "k"
            lobes_gateway_url = "http://gw:1"
            evaluator_checkpoint = "shared-checkpoint"

        assert resolve_distill_author_from_config(_Cfg()) is None

        class _CfgWithDistiller(_Cfg):
            distiller_checkpoint = "a-genuinely-different-checkpoint"

        author = resolve_distill_author_from_config(_CfgWithDistiller())
        assert author is not None
        assert author.model == "shared-checkpoint"


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
            # The child re-invokes the module entry `python -m colleague.distill`
            # (the t17 live probe caught the original `-m colleague distill`
            # argv pointing at a CLI verb that never existed — a dead child).
            assert argv[0] == sys.executable
            assert "-m" in argv
            assert "colleague.distill" in argv


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

        valid_lesson = {
            "pattern": "budget spent re-reading a module before editing",
            "constant": "colleague/distill.py",
            "reason": "grep the symbol before opening files",
        }
        with patch("colleague.memory.remember") as mock_remember:
            mock_remember.return_value = True

            distill.upsert_lesson(repo, "test-123", valid_lesson)
            mock_remember.assert_called_once()

    def test_upsert_lesson_refuses_invalid(self, tmp_path: Path) -> None:
        """An invalid lesson is never remembered — no partial record."""
        repo = tmp_path / "repo"
        repo.mkdir()

        invalid_lesson = {"pattern": "x"}  # missing required keys
        with patch("colleague.memory.remember") as mock_remember:
            distill.upsert_lesson(repo, "test-123", invalid_lesson)
            mock_remember.assert_not_called()

    def test_upsert_lesson_uses_same_work_lesson_id(self, tmp_path: Path) -> None:
        """The upsert uses the SAME work-lesson id as the rung-1 record."""
        repo = tmp_path / "repo"
        repo.mkdir()

        valid_lesson = {
            "pattern": "budget spent re-reading a module before editing",
            "constant": "colleague/distill.py",
            "reason": "grep the symbol before opening files",
        }
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


# ---------------------------------------------------------------------------
# Qodo #386 regression: the child never reads a sidecar as the artifact
# ---------------------------------------------------------------------------


class TestFindArtifactSidecars:
    def test_feedback_sidecar_never_selected(self, tmp_path: Path) -> None:
        """`<id>.feedback.json` sorts before the artifact but must never win
        (Qodo #386 bug 4: the broad glob + lexicographic pick could read a
        feedback record as the run artifact)."""
        adir = tmp_path / ".colleague"
        adir.mkdir()
        (adir / "abc123.feedback.json").write_text(
            json.dumps({"task_id": "abc123", "rating": 5}), encoding="utf-8"
        )
        (adir / "abc123.cortex.feedback.json").write_text(
            json.dumps({"task_id": "abc123", "rating": 3, "author": "cortex"}),
            encoding="utf-8",
        )
        artifact = adir / "abc123.some-task-slug.json"
        artifact.write_text(
            json.dumps({"task_id": "abc123", "status": "ok", "summary": "s"}),
            encoding="utf-8",
        )
        found = distill._find_artifact(tmp_path, "abc123")
        assert found == artifact

    def test_no_artifact_only_sidecars_yields_none(self, tmp_path: Path) -> None:
        adir = tmp_path / ".colleague"
        adir.mkdir()
        (adir / "abc123.feedback.json").write_text(
            json.dumps({"task_id": "abc123", "rating": 5}), encoding="utf-8"
        )
        assert distill._find_artifact(tmp_path, "abc123") is None


# ---------------------------------------------------------------------------
# Bounded-completion sizing + reasoning-consumes-max_tokens (t3)
# ---------------------------------------------------------------------------
#
# Live sizing experiment against unsloth/Qwen3.8-27B-NVFP4 (2026-08-20), with
# realistic rung-2 payloads composed by `_compose_child_prompt`:
#
#   payload | max_tokens | finish_reason | reasoning | content | completion tok
#   A       |  400       | length        | 1854 ch   |    0 ch |  400
#   A       | 1600       | stop          | 2530 ch   |  655 ch |  669
#   B       | 1600       | stop          | 6346 ch   |  459 ch | 1449
#   C       | 1600       | stop          | 4854 ch   |  709 ch | 1160
#
# The degradation reproduces (payload A at 400: a 200 with zero content), and
# the worst realistic payload spends 1449 of the 1600 cap — a 151-token margin.


class _FakeCompletionResponse:
    """A context-manager stand-in for ``urllib.request.urlopen``'s response."""

    def __init__(self, body: dict) -> None:
        self._body = json.dumps(body).encode("utf-8")

    def __enter__(self) -> "_FakeCompletionResponse":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


def _completion_body(
    *,
    content: str = "",
    reasoning: str = "",
    finish_reason: str = "stop",
    reasoning_key: str = "reasoning",
) -> dict:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if reasoning:
        message[reasoning_key] = reasoning
    return {"choices": [{"finish_reason": finish_reason, "message": message}]}


def _patch_urlopen(body: dict, captured: dict | None = None):
    """Return a ``urlopen`` stand-in serving *body*, recording the request."""

    def fake_urlopen(request: Any, timeout: float | None = None) -> _FakeCompletionResponse:
        if captured is not None:
            captured["url"] = request.full_url
            captured["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeCompletionResponse(body)

    return fake_urlopen


_VALID_LESSON = {
    "pattern": "the reasoning budget is spent before the answer is emitted",
    "constant": "colleague/distill.py::_DISTILL_MAX_TOKENS",
    "reason": "a reasoning model bills thinking against the same max_tokens",
}


class TestBoundedCompletionSizing:
    """The distill completion is sized from the live measurement (h10)."""

    def test_max_tokens_covers_the_measured_envelope(self) -> None:
        """The cap clears 2x the worst measured realistic payload (1449 tokens)."""
        assert distill._DISTILL_MAX_TOKENS >= 2 * 1449

    def test_request_carries_the_sized_cap(self, monkeypatch: Any) -> None:
        import urllib.request

        captured: dict = {}
        monkeypatch.setattr(
            urllib.request,
            "urlopen",
            _patch_urlopen(_completion_body(content="{}"), captured),
        )
        distill._openai_completion("m", "http://rig/v1", "k", "prompt")
        assert captured["body"]["max_tokens"] == distill._DISTILL_MAX_TOKENS

    def test_completion_reports_finish_reason_and_parts(self, monkeypatch: Any) -> None:
        """The completion is structured: content, reasoning and finish_reason."""
        import urllib.request

        monkeypatch.setattr(
            urllib.request,
            "urlopen",
            _patch_urlopen(
                _completion_body(content="", reasoning="thinking hard", finish_reason="length")
            ),
        )
        completion = distill._openai_completion("m", "http://rig/v1", "k", "prompt")
        assert completion.finish_reason == "length"
        assert completion.content == ""
        assert completion.reasoning == "thinking hard"
        assert completion.truncated is True
        # The combined text keeps the pre-change shape (content then reasoning).
        assert "thinking hard" in completion.text

    def test_reasoning_content_spelling_is_read(self, monkeypatch: Any) -> None:
        """Some servers spell the field ``reasoning_content`` (s14)."""
        import urllib.request

        monkeypatch.setattr(
            urllib.request,
            "urlopen",
            _patch_urlopen(
                _completion_body(
                    content="",
                    reasoning="thought",
                    reasoning_key="reasoning_content",
                )
            ),
        )
        completion = distill._openai_completion("m", "http://rig/v1", "k", "prompt")
        assert completion.reasoning == "thought"


class TestTruncatedDistillation:
    """A reasoning-consumed completion is a recorded warning, never a silent
    empty lesson (h10)."""

    @staticmethod
    def _seed_artifact(tmp_path: Path, task_id: str = "abc123") -> Path:
        adir = tmp_path / ".colleague"
        adir.mkdir(exist_ok=True)
        artifact = adir / f"{task_id}.some-slug.json"
        artifact.write_text(
            json.dumps(
                {
                    "task_id": task_id,
                    "status": "INCOMPLETE",
                    "summary": "s",
                    "stats": {"step_count": 9},
                }
            ),
            encoding="utf-8",
        )
        return artifact

    @staticmethod
    def _marker(artifact: Path) -> dict:
        return json.loads(artifact.with_suffix(".distill.json").read_text(encoding="utf-8"))

    def test_length_truncation_is_recorded_and_never_remembered(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        artifact = self._seed_artifact(tmp_path)
        monkeypatch.setattr(
            distill,
            "_openai_completion",
            lambda *a, **k: distill.DistillCompletion(
                content="", reasoning="x" * 1854, finish_reason="length"
            ),
        )
        with patch("colleague.memory.remember") as mock_remember:
            rc = distill.child_main(
                ["--repo", str(tmp_path), "--task-id", "abc123", "--model", "m"]
            )
            mock_remember.assert_not_called()
        assert rc == 1
        marker = self._marker(artifact)
        assert marker["status"] == "failed"
        assert "lesson" not in marker
        reason = marker["reason"]
        assert "truncat" in reason.lower()
        assert "finish_reason=length" in reason
        assert str(distill._DISTILL_MAX_TOKENS) in reason

    def test_truncated_but_parseable_lesson_is_never_remembered(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        """A length-cut completion can still carry an early balanced JSON
        object (the tolerant parser extracts it) — a mid-draft, not a lesson.
        Truncation always routes to the failed branch (Qodo #406 review)."""
        artifact = self._seed_artifact(tmp_path)
        lesson_json = (
            '{"pattern": "trace-first stalls",'
            ' "constant": "colleague/loop.py:_execute_step",'
            ' "reason": "all steps went to tracing before execution"}'
        )
        monkeypatch.setattr(
            distill,
            "_openai_completion",
            lambda *a, **k: distill.DistillCompletion(
                content=lesson_json, reasoning="r" * 500, finish_reason="length"
            ),
        )
        with patch("colleague.memory.remember") as mock_remember:
            rc = distill.child_main(
                ["--repo", str(tmp_path), "--task-id", "abc123", "--model", "m"]
            )
            mock_remember.assert_not_called()
        assert rc == 1
        marker = self._marker(artifact)
        assert marker["status"] == "failed"
        assert "lesson" not in marker
        reason = marker["reason"]
        assert "truncat" in reason.lower()
        assert "finish_reason=length" in reason

    def test_empty_content_is_recorded_as_such(self, tmp_path: Path, monkeypatch: Any) -> None:
        """An empty completion that STOPPED is still named honestly."""
        artifact = self._seed_artifact(tmp_path)
        monkeypatch.setattr(
            distill,
            "_openai_completion",
            lambda *a, **k: distill.DistillCompletion(
                content="", reasoning="", finish_reason="stop"
            ),
        )
        with patch("colleague.memory.remember") as mock_remember:
            rc = distill.child_main(
                ["--repo", str(tmp_path), "--task-id", "abc123", "--model", "m"]
            )
            mock_remember.assert_not_called()
        assert rc == 1
        marker = self._marker(artifact)
        assert marker["status"] == "failed"
        assert "no content" in marker["reason"].lower()

    def test_lesson_carried_in_reasoning_still_validates(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        """Regression: a server that puts the JSON in ``reasoning`` with empty
        ``content`` still produces a validated lesson — the empty-content guard
        must not swallow it."""
        artifact = self._seed_artifact(tmp_path)
        monkeypatch.setattr(
            distill,
            "_openai_completion",
            lambda *a, **k: distill.DistillCompletion(
                content="",
                reasoning=json.dumps(_VALID_LESSON),
                finish_reason="stop",
            ),
        )
        with patch("colleague.memory.remember") as mock_remember:
            mock_remember.return_value = True
            rc = distill.child_main(
                ["--repo", str(tmp_path), "--task-id", "abc123", "--model", "m"]
            )
            mock_remember.assert_called_once()
        assert rc == 0
        marker = self._marker(artifact)
        assert marker["status"] == "done"
        assert marker["lesson"]["constant"] == _VALID_LESSON["constant"]

    def test_truncated_partial_json_names_truncation_not_schema(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        """Content that STARTED the JSON but got cut names the truncation —
        a schema complaint would send the operator hunting the wrong bug."""
        artifact = self._seed_artifact(tmp_path)
        monkeypatch.setattr(
            distill,
            "_openai_completion",
            lambda *a, **k: distill.DistillCompletion(
                content='{"pattern": "half a thou',
                reasoning="y" * 4000,
                finish_reason="length",
            ),
        )
        with patch("colleague.memory.remember") as mock_remember:
            rc = distill.child_main(
                ["--repo", str(tmp_path), "--task-id", "abc123", "--model", "m"]
            )
            mock_remember.assert_not_called()
        assert rc == 1
        marker = self._marker(artifact)
        assert marker["status"] == "failed"
        assert "truncat" in marker["reason"].lower()
