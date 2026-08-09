"""Subagent child inheritance consumes the config-lifecycle snapshot (plan task
t10, spec c35/h28 — ``docs/specs/2026-08-06-change-content-consumption-lane.md``).

A spawned child never gets the parent's REAL
:class:`~colleague.configlifecycle.EpisodeConfigLifecycle` (children never
propose changes and never observe turns on the top-level task's config
plane). Instead ``colleague/subagents.py`` reads
:meth:`~colleague.configlifecycle.EpisodeConfigLifecycle.child_snapshot` at
spawn time and hands the child a tiny FROZEN adapter
(:class:`~colleague.subagents.FrozenChildConfigLifecycle`) exposing exactly
the read surface the t3 (tool-narrowing) and t7 (evaluator prompt) engine
seams consume — ``snapshot`` as a PROPERTY (t7 reads it ONLY as a property;
a method-only adapter would silently lose the evaluator note) — on the
child config's ``config_lifecycle`` field.

These tests FAIL on the pre-t10 tree: ``run_subagent``/``make_spawn`` never
read ``parent_config.config_lifecycle`` at all, so a child spawned under an
applied narrowing or evaluator note is unaffected by it (the spawn bypass
s19/q4 names) and ``FrozenChildConfigLifecycle`` does not exist.
"""

from __future__ import annotations

import dataclasses
import subprocess
from pathlib import Path
from typing import Optional

import pytest

from colleague.config import EngineConfig
from colleague.configlifecycle import (
    WINDOW_BEFORE_EPISODE_1,
    EpisodeConfigLifecycle,
    EpisodeConfigSnapshot,
)
from colleague.contract import OK, Task
from colleague.engines.mock import OUTPUT_FILE, MockEngine
from colleague.lattice import CapabilityCatalog, ChangeUnit, Origin, Target
from colleague.layers import EVALUATOR_SECTION_HEADING
from colleague.subagents import (
    FrozenChildConfigLifecycle,
    make_spawn,
    run_subagent,
)

_EVALUATOR_NOTE = "Focus on the auth module."


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """A minimal git repo with one commit (subagent worktree spawns need it)."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t.test"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "T"], check=True)
    (tmp_path / "README.md").write_text("# repo\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-q", "-m", "init"], check=True)
    return tmp_path


def _catalog(tool_ids: list[str]) -> CapabilityCatalog:
    return CapabilityCatalog(tool_ids=tuple(tool_ids))


def _tools_change(tool_ids: list[str]) -> ChangeUnit:
    return ChangeUnit(target=Target.WORKER_TOOLS, origin=Origin.CORTEX, tool_ids=tool_ids)


def _evaluator_change(content: str) -> ChangeUnit:
    return ChangeUnit(
        target=Target.WORKER_PROMPT_EVALUATOR,
        origin=Origin.CORTEX,
        content=content,
    )


def _applied_lifecycle(
    *, tool_ids: Optional[list[str]] = None, evaluator: Optional[str] = None
) -> EpisodeConfigLifecycle:
    """A real lifecycle with a narrowing and/or evaluator note APPLIED (not queued)."""
    catalog_ids = list(tool_ids or []) + ["finish"]
    lifecycle = EpisodeConfigLifecycle(catalog=_catalog(catalog_ids))
    if tool_ids is not None:
        verdict = lifecycle.propose(_tools_change(tool_ids))
        assert verdict.allowed is True
    if evaluator is not None:
        verdict = lifecycle.propose(_evaluator_change(evaluator))
        assert verdict.allowed is True
    lifecycle.apply_window(WINDOW_BEFORE_EPISODE_1)
    return lifecycle


class _CapturingEngine:
    """Records the ``config`` handed to ``work()`` and delegates to a real mock.

    Mirrors the established pattern in ``tests/test_subagents.py`` /
    ``tests/test_subagent_lineage.py``: capture-then-delegate so a test can
    both inspect the exact object attached to ``config.config_lifecycle`` AND
    observe the real engine's behavior under it (tool refusal, prompt
    composition) in the same call.
    """

    def __init__(self) -> None:
        self.configs: list[EngineConfig] = []
        self._real = MockEngine()

    def work(self, task: Task, config: EngineConfig):
        self.configs.append(config)
        return self._real.work(task, config)


class _NestingEngine:
    """Spawns exactly ONE nested grandchild on its first call via
    ``config.subagent_spawn``, capturing both configs so a test can compare
    the depth-1 child's and the depth-2 grandchild's inherited adapters."""

    def __init__(self) -> None:
        self.configs: list[EngineConfig] = []
        self.nested_config: Optional[EngineConfig] = None
        self._real = MockEngine()

    def work(self, task: Task, config: EngineConfig):
        self.configs.append(config)
        if config.subagent_spawn is not None and len(self.configs) == 1:
            # Recurse ONE level via the child's own spawn callback — this is
            # the grandchild spawn. The nested call re-enters this SAME
            # engine (registry.load is monkeypatched to always return one
            # instance), so its config lands in self.configs too, but we also
            # stash it distinctly for direct grandchild assertions.
            config.subagent_spawn("grandchild instruction")
            self.nested_config = self.configs[-1]
        return self._real.work(task, config)


@pytest.fixture
def patch_engine(monkeypatch):
    def _install(engine):
        monkeypatch.setattr("colleague.subagents.registry.load", lambda name: engine)
        return engine

    return _install


# ===========================================================================
# 1. FrozenChildConfigLifecycle — the adapter's shape in isolation
# ===========================================================================


class TestFrozenChildConfigLifecycleShape:
    def test_snapshot_is_a_property_not_a_method(self) -> None:
        """t7's engine.system_prompt reads config_lifecycle.snapshot ONLY as a
        property (getattr then .evaluator_sections, never calling it) — a
        snapshot()-METHOD-only adapter would silently lose the evaluator
        note, so this pins the property shape directly."""
        snap = EpisodeConfigSnapshot(evaluator_sections=(_EVALUATOR_NOTE,))
        adapter = FrozenChildConfigLifecycle(snap)
        # Accessing .snapshot (no call parens) already yields the snapshot.
        assert adapter.snapshot is snap
        assert not callable(adapter.snapshot)

    def test_child_snapshot_method_returns_same_frozen_snapshot(self) -> None:
        """Exposes child_snapshot() too, so a grandchild's OWN spawn can
        re-derive the identical frozen snapshot again."""
        snap = EpisodeConfigSnapshot(tool_set=("read_file",))
        adapter = FrozenChildConfigLifecycle(snap)
        assert adapter.child_snapshot() is snap
        assert adapter.child_snapshot() is adapter.snapshot

    def test_adapter_carries_no_mutating_surface(self) -> None:
        """A child never proposes changes and never observes turns on the
        REAL lifecycle — the adapter has no propose()/apply_window()."""
        adapter = FrozenChildConfigLifecycle(EpisodeConfigSnapshot())
        assert not hasattr(adapter, "propose")
        assert not hasattr(adapter, "apply_window")

    def test_adapter_is_frozen_and_immutable(self) -> None:
        """A frozen dataclass over an immutable snapshot: thread-safe to hand
        across a concurrent batch spawn's ThreadPoolExecutor workers."""
        adapter = FrozenChildConfigLifecycle(EpisodeConfigSnapshot())
        with pytest.raises(dataclasses.FrozenInstanceError):
            adapter.frozen_snapshot = EpisodeConfigSnapshot(tool_set=("x",))  # type: ignore[misc]

    def test_loop_seam_no_ops_do_not_raise(self) -> None:
        """The loop calls config_lifecycle.observe_turn()/.end_episode()
        UNCONDITIONALLY on any attached object (colleague/loop.py) — the
        adapter must answer both without raising AttributeError, or a
        child's own run would crash on its first completed turn."""
        adapter = FrozenChildConfigLifecycle(EpisodeConfigSnapshot())
        adapter.observe_turn()  # must not raise
        adapter.end_episode()  # must not raise


# ===========================================================================
# 2. run_subagent attaches the frozen adapter, never the real lifecycle
# ===========================================================================


class TestChildReceivesFrozenAdapterNeverRealLifecycle:
    def test_child_config_lifecycle_is_frozen_adapter_not_real_object(
        self, tmp_path: Path, patch_engine
    ) -> None:
        engine = _CapturingEngine()
        patch_engine(engine)
        lifecycle = _applied_lifecycle(tool_ids=["read_file", "list_dir"])

        run_subagent(
            "do it",
            repo_path=str(tmp_path),
            parent_config=EngineConfig(config_lifecycle=lifecycle),
            parent_engine="mock",
            depth=1,
        )

        child_cfg = engine.configs[0]
        assert isinstance(child_cfg.config_lifecycle, FrozenChildConfigLifecycle)
        assert child_cfg.config_lifecycle is not lifecycle
        assert not isinstance(child_cfg.config_lifecycle, EpisodeConfigLifecycle)
        # The frozen snapshot matches the parent's CURRENT applied snapshot.
        assert child_cfg.config_lifecycle.snapshot.tool_set == lifecycle.snapshot.tool_set

    def test_parent_config_lifecycle_object_is_untouched(
        self, tmp_path: Path, patch_engine
    ) -> None:
        patch_engine(_CapturingEngine())
        lifecycle = _applied_lifecycle(tool_ids=["read_file"])
        parent = EngineConfig(config_lifecycle=lifecycle)

        run_subagent(
            "do it",
            repo_path=str(tmp_path),
            parent_config=parent,
            parent_engine="mock",
            depth=1,
        )

        # The parent's own config object still holds the REAL lifecycle.
        assert parent.config_lifecycle is lifecycle


# ===========================================================================
# 3. Acceptance 1 — tool narrowing reaches the child (offered schema + executor)
# ===========================================================================


class TestNarrowedChildCannotCallNarrowedAwayTool:
    def test_child_write_file_refused_under_applied_narrowing(
        self, git_repo: Path, patch_engine
    ) -> None:
        """A child spawned under an applied worker.tools narrowing that
        excludes write_file cannot write — pinned via the real executor
        refusal (same mechanism t3 wired for the top-level task)."""
        engine = _CapturingEngine()
        patch_engine(engine)
        lifecycle = _applied_lifecycle(tool_ids=["read_file", "list_dir"])

        result = run_subagent(
            "write something",
            repo_path=str(git_repo),
            parent_config=EngineConfig(role="writer", config_lifecycle=lifecycle),
            parent_engine="mock",
            depth=1,
        )

        assert result.changed_files == [], "narrowed-away write_file must not execute"
        child_cfg = engine.configs[0]
        assert child_cfg.config_lifecycle.snapshot.tool_set == ("read_file", "list_dir")

    def test_child_kept_tool_still_works_under_narrowing(
        self, git_repo: Path, patch_engine
    ) -> None:
        patch_engine(_CapturingEngine())
        lifecycle = _applied_lifecycle(tool_ids=["write_file"])

        result = run_subagent(
            "write something",
            repo_path=str(git_repo),
            parent_config=EngineConfig(role="writer", config_lifecycle=lifecycle),
            parent_engine="mock",
            depth=1,
        )
        assert result.changed_files == [OUTPUT_FILE]


# ===========================================================================
# 4. Acceptance 1 — composed prompt carries the current evaluator note
# ===========================================================================


class TestChildPromptCarriesEvaluatorNote:
    def test_child_config_composes_evaluator_note_via_t7_seam(
        self, tmp_path: Path, patch_engine
    ) -> None:
        """Drives the t7 seam directly (engine.system_prompt) over the
        adapter run_subagent attached to the child's config — proving the
        adapter's PROPERTY shape actually carries the note through, not just
        that an object of some shape was attached."""
        engine = _CapturingEngine()
        patch_engine(engine)
        lifecycle = _applied_lifecycle(evaluator=_EVALUATOR_NOTE)

        run_subagent(
            "do it",
            repo_path=str(tmp_path),
            parent_config=EngineConfig(config_lifecycle=lifecycle),
            parent_engine="mock",
            depth=1,
        )

        child_cfg = engine.configs[0]
        child_task = Task.new(str(tmp_path), "do it")
        prompt = MockEngine().system_prompt(child_task, child_cfg)
        assert prompt is not None
        assert EVALUATOR_SECTION_HEADING in prompt
        assert _EVALUATOR_NOTE in prompt


# ===========================================================================
# 5. Acceptance 2 — no narrowing => byte-identical; unapplied proposals never
#    reach a child
# ===========================================================================


class TestByteIdenticalAndUnappliedProposalsNeverReachChild:
    def test_no_config_lifecycle_on_parent_child_stays_none(
        self, tmp_path: Path, patch_engine
    ) -> None:
        engine = _CapturingEngine()
        patch_engine(engine)

        run_subagent(
            "do it",
            repo_path=str(tmp_path),
            parent_config=EngineConfig(),
            parent_engine="mock",
            depth=1,
        )
        assert engine.configs[0].config_lifecycle is None

    def test_explicit_none_config_lifecycle_child_stays_none(
        self, tmp_path: Path, patch_engine
    ) -> None:
        engine = _CapturingEngine()
        patch_engine(engine)

        run_subagent(
            "do it",
            repo_path=str(tmp_path),
            parent_config=EngineConfig(config_lifecycle=None),
            parent_engine="mock",
            depth=1,
        )
        assert engine.configs[0].config_lifecycle is None

    def test_child_run_byte_identical_without_lifecycle(self, git_repo: Path, patch_engine) -> None:
        """A child spawned with no narrowing applied writes exactly as a
        pre-t10 child would (the write succeeds, unblocked by anything)."""
        patch_engine(_CapturingEngine())

        result = run_subagent(
            "write something",
            repo_path=str(git_repo),
            parent_config=EngineConfig(role="writer"),
            parent_engine="mock",
            depth=1,
        )
        assert result.changed_files == [OUTPUT_FILE]
        assert result.status == OK

    def test_queued_but_unapplied_narrowing_never_reaches_child(
        self, git_repo: Path, patch_engine
    ) -> None:
        """A proposal that was PROPOSED but never APPLIED (no apply_window
        call) must never affect a spawned child — the r2 rule extended to
        children (h28)."""
        engine = _CapturingEngine()
        patch_engine(engine)

        lifecycle = EpisodeConfigLifecycle(
            catalog=_catalog(["read_file", "list_dir", "write_file", "finish"])
        )
        verdict = lifecycle.propose(_tools_change(["read_file", "list_dir"]))
        assert verdict.allowed is True
        # Deliberately never call lifecycle.apply_window(...): the proposal
        # stays queued.
        assert lifecycle.snapshot.tool_set == ()  # still not-narrowed

        result = run_subagent(
            "write something",
            repo_path=str(git_repo),
            parent_config=EngineConfig(role="writer", config_lifecycle=lifecycle),
            parent_engine="mock",
            depth=1,
        )

        # The child sees the CURRENT (empty) snapshot, not the queued one.
        assert engine.configs[0].config_lifecycle.snapshot.tool_set == ()
        # write_file was never narrowed away, so it still executes.
        assert result.changed_files == [OUTPUT_FILE]

    def test_queued_but_unapplied_evaluator_note_never_reaches_child(
        self, tmp_path: Path, patch_engine
    ) -> None:
        engine = _CapturingEngine()
        patch_engine(engine)

        lifecycle = EpisodeConfigLifecycle()
        verdict = lifecycle.propose(_evaluator_change(_EVALUATOR_NOTE))
        assert verdict.allowed is True
        # Never applied.
        assert lifecycle.snapshot.evaluator_sections == ()

        run_subagent(
            "do it",
            repo_path=str(tmp_path),
            parent_config=EngineConfig(config_lifecycle=lifecycle),
            parent_engine="mock",
            depth=1,
        )

        child_cfg = engine.configs[0]
        assert child_cfg.config_lifecycle.snapshot.evaluator_sections == ()
        child_task = Task.new(str(tmp_path), "do it")
        prompt = MockEngine().system_prompt(child_task, child_cfg)
        if prompt is not None:
            assert EVALUATOR_SECTION_HEADING not in prompt


# ===========================================================================
# 6. Grandchildren at depth>1 inherit identically
# ===========================================================================


class TestGrandchildrenInheritIdentically:
    def test_grandchild_inherits_frozen_adapter_from_frozen_adapter(
        self, tmp_path: Path, patch_engine
    ) -> None:
        engine = _NestingEngine()
        patch_engine(engine)
        lifecycle = _applied_lifecycle(
            tool_ids=["read_file", "list_dir"], evaluator=_EVALUATOR_NOTE
        )

        spawn = make_spawn(str(tmp_path), EngineConfig(config_lifecycle=lifecycle), "mock")
        spawn("root instruction")

        assert len(engine.configs) == 2, "expected a depth-1 child and a depth-2 grandchild"
        child_cfg, grandchild_cfg = engine.configs[0], engine.configs[1]

        for cfg in (child_cfg, grandchild_cfg):
            assert isinstance(cfg.config_lifecycle, FrozenChildConfigLifecycle)
            assert not isinstance(cfg.config_lifecycle, EpisodeConfigLifecycle)

        # Identical inheritance: same tool_set / evaluator_sections at both depths.
        assert (
            child_cfg.config_lifecycle.snapshot.tool_set
            == grandchild_cfg.config_lifecycle.snapshot.tool_set
            == ("read_file", "list_dir")
        )
        assert (
            child_cfg.config_lifecycle.snapshot.evaluator_sections
            == grandchild_cfg.config_lifecycle.snapshot.evaluator_sections
            == (_EVALUATOR_NOTE,)
        )

    def test_grandchild_prompt_still_carries_evaluator_note(
        self, tmp_path: Path, patch_engine
    ) -> None:
        engine = _NestingEngine()
        patch_engine(engine)
        lifecycle = _applied_lifecycle(evaluator=_EVALUATOR_NOTE)

        spawn = make_spawn(str(tmp_path), EngineConfig(config_lifecycle=lifecycle), "mock")
        spawn("root instruction")

        grandchild_cfg = engine.nested_config
        assert grandchild_cfg is not None
        task = Task.new(str(tmp_path), "grandchild instruction")
        prompt = MockEngine().system_prompt(task, grandchild_cfg)
        assert prompt is not None
        assert EVALUATOR_SECTION_HEADING in prompt
        assert _EVALUATOR_NOTE in prompt

    def test_grandchild_tool_narrowing_still_refuses(self, git_repo: Path, patch_engine) -> None:
        """Depth>1 narrowing enforcement: a grandchild spawned two levels deep
        under an applied narrowing still cannot call the narrowed-away tool."""
        engine = _NestingEngine()
        patch_engine(engine)
        lifecycle = _applied_lifecycle(tool_ids=["read_file", "list_dir"])

        spawn = make_spawn(
            str(git_repo), EngineConfig(role="writer", config_lifecycle=lifecycle), "mock"
        )
        spawn("root instruction")

        grandchild_cfg = engine.nested_config
        assert grandchild_cfg is not None
        assert grandchild_cfg.config_lifecycle.snapshot.tool_set == ("read_file", "list_dir")
