"""Parallel subagent batch orchestration (t3): ``make_batch_spawn`` + ``batch_spawn``.

A single subagent delegation can carry a BATCH of instructions; colleague runs
those child drives CONCURRENTLY via a ``ThreadPoolExecutor`` confined to
``colleague/subagents.py``, each child isolated in its OWN throwaway git
worktree on branch ``sub/<child_id>``. After the executor join, a SEQUENTIAL
merge-subagent ("child C") git-merges the per-child branches back into the
working branch of the repo and resolves (or surfaces) conflicts.

These tests pin the behavior t4 (the ``subagents`` tool) and t5 (loop wiring)
code against:

(a) A batch run via ``make_batch_spawn`` with the mock engine runs each child in
    its own worktree/branch and returns a FLAT ``list[SubResult]`` — the N child
    results in INPUT ORDER followed by ONE merge child. SubResults have the exact
    existing shape. Collection happens AFTER the join (main thread).
(b) MERGE: two children touching DIFFERENT files cleanly integrate both into the
    main tree; two children touching the SAME file in conflicting ways surface
    the conflict in the merge child's SubResult — nothing force-merged or dropped.
(c) CONCURRENCY: with width>1 a batch of 3 artificially-delayed children overlaps
    in flight (asserted via a high-water-mark counter, not wall-clock elapsed
    time — see TestConcurrency's docstring); with width==1 NO ThreadPoolExecutor
    is ever instantiated (sequential path).
"""

from __future__ import annotations

import concurrent.futures
import subprocess
import threading
import time
from pathlib import Path

import pytest

from colleague.config import EngineConfig
from colleague.contract import ERROR, OK, SubResult, Usage
from colleague.subagents import make_batch_spawn

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    )


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    """A minimal git repo with one commit (needed for 'git worktree add')."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@colleague.test")
    _git(repo, "config", "user.name", "Colleague Test")
    # An initial commit so worktree add has a HEAD to branch from.
    (repo / "README.md").write_text("# test repo\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "initial commit")
    return repo


def _branch_list(repo: Path) -> list[str]:
    proc = _git(repo, "branch", "--list")
    names = []
    for line in proc.stdout.splitlines():
        name = line.strip().lstrip("*+ ").strip()
        if name:
            names.append(name)
    return names


def _worktree_paths(repo: Path) -> list[str]:
    proc = _git(repo, "worktree", "list", "--porcelain")
    return [
        line[len("worktree ") :].strip()
        for line in proc.stdout.splitlines()
        if line.startswith("worktree ")
    ]


def _items(*specs: str) -> list[dict]:
    """Build batch items from instruction strings (engine/model inherit parent)."""
    return [{"instruction": s, "engine": None, "model": None} for s in specs]


# ---------------------------------------------------------------------------
# (a) Flat list shape: N children in order + a final merge child.
# ---------------------------------------------------------------------------


class TestBatchShape:
    def test_returns_flat_list_children_then_merge(self, git_repo: Path) -> None:
        batch = make_batch_spawn(str(git_repo), EngineConfig(model="X"), "mock")
        results = batch(_items("alpha task", "beta task"))

        # 2 children + 1 merge child = 3 SubResults, flat, in order.
        assert isinstance(results, list)
        assert len(results) == 3
        for r in results:
            assert isinstance(r, SubResult)

        # Children carry the exact existing SubResult shape.
        for r in results[:2]:
            assert r.engine == "mock"
            assert r.model == "X"
            assert r.status == OK
            assert isinstance(r.usage, Usage)
            assert r.task_id  # a real child task id

        # The final element is the merge child ("child C").
        merge = results[-1]
        assert isinstance(merge, SubResult)
        assert isinstance(merge.usage, Usage)
        assert merge.task_id

    def test_subresult_to_dict_shape_unchanged(self, git_repo: Path) -> None:
        """Each SubResult serializes with the exact existing keys (t7/e2e guard)."""
        batch = make_batch_spawn(str(git_repo), EngineConfig(), "mock")
        results = batch(_items("only task"))
        expected_keys = {
            "task_id",
            "engine",
            "model",
            "status",
            "summary",
            "changed_files",
            "usage",
        }
        for r in results:
            expect = set(expected_keys)
            if not r.task_id.startswith("merge-"):
                # t5: real children carry their built seat's rung; the merge
                # child runs no model — no seat built, honestly no rung.
                expect.add("reasoning_effort")
            assert set(r.to_dict().keys()) == expect

    def test_each_child_ran_in_its_own_worktree_branch(self, git_repo: Path) -> None:
        """During the run each child drives inside its own worktree path; cleaned after."""
        # The real _run_child_in_worktree creates the worktree internally and hands
        # the worktree path to run_subagent as its repo_path. Spy on run_subagent to
        # observe the repo_path each child actually drove against — it must be a
        # per-child worktree dir, NOT the bare repo root.
        seen_repo_paths: list[str] = []

        import colleague.subagents as sa

        real_run = sa.run_subagent

        def _spy_run(
            instruction,
            *,
            repo_path,
            parent_config,
            parent_engine,
            depth,
            engine=None,
            model=None,
            role=None,
            counter=None,
            spec=None,
        ):
            seen_repo_paths.append(repo_path)
            return real_run(
                instruction,
                repo_path=repo_path,
                parent_config=parent_config,
                parent_engine=parent_engine,
                depth=depth,
                engine=engine,
                model=model,
                role=role,
                counter=counter,
                spec=spec,
            )

        sa.run_subagent = _spy_run
        try:
            batch = make_batch_spawn(str(git_repo), EngineConfig(), "mock")
            batch(_items("one", "two"))
        finally:
            sa.run_subagent = real_run

        repo_root = Path(str(git_repo)).resolve()
        assert len(seen_repo_paths) == 2
        resolved = [Path(rp).resolve() for rp in seen_repo_paths]
        for rp in resolved:
            assert rp != repo_root, "child drove against the bare repo root, not a worktree"
            assert ".colleague/worktrees" in str(rp), f"not a worktree path: {rp}"
        # Two DISTINCT worktree paths (one per child).
        assert len(set(resolved)) == 2

        # Cleanup: no leftover worktree DIRECTORIES after the batch (the isolation
        # dirs are always removed — no disk leak). Branch retention is exercised
        # precisely in TestMerge: a cleanly-merged child's branch is deleted, a
        # CONFLICTED child's branch is retained. Here both real-mock children write
        # the same fixed mock output file, so the second conflicts and its sub/<id>
        # branch is intentionally kept; we only require the worktree dirs are gone.
        wt_dir = str((git_repo / ".colleague" / "worktrees").resolve())
        leftover = [p for p in _worktree_paths(git_repo) if p.startswith(wt_dir)]
        assert leftover == [], f"Leftover worktrees: {leftover}"


# ---------------------------------------------------------------------------
# (b) Merge: clean (different files) vs conflict (same file).
# ---------------------------------------------------------------------------


class TestMerge:
    def test_clean_merge_different_files(self, git_repo: Path) -> None:
        """Two children writing DIFFERENT files: merge brings both to the main tree."""
        # Drive children that each write a distinct file. We monkeypatch the
        # per-child runner to write deterministic content into the worktree, then
        # commit it on the sub branch (mirroring the real flow).
        import colleague.subagents as sa
        from colleague import worktrees

        def _fake_child(
            repo_path,
            child_id,
            instruction,
            *,
            parent_config,
            parent_engine,
            depth,
            engine=None,
            model=None,
            role=None,
            counter=None,
            spec=None,
        ):
            # Create the isolated worktree (the real runner does this), write a
            # unique file inside it keyed on the instruction, and commit the branch.
            wt = worktrees.worktree_add(repo_path, child_id)
            fname = f"{instruction}.txt"
            (Path(wt) / fname).write_text(f"from {instruction}\n", encoding="utf-8")
            worktrees.commit_all(wt, f"child {child_id}")
            return SubResult(
                task_id=f"t-{child_id}",
                engine=engine or parent_engine,
                model=model or parent_config.model,
                status=OK,
                summary=f"wrote {fname}",
                changed_files=[fname],
                usage=Usage(),
            )

        orig = sa._run_child_in_worktree
        sa._run_child_in_worktree = _fake_child
        try:
            batch = make_batch_spawn(str(git_repo), EngineConfig(), "mock")
            results = batch(_items("fileA", "fileB"))
        finally:
            sa._run_child_in_worktree = orig

        merge = results[-1]
        assert merge.status == OK, f"merge should be clean, got {merge.status}: {merge.summary}"
        # Both files landed on the working tree of the main repo.
        assert (git_repo / "fileA.txt").exists(), "child A's file missing after merge"
        assert (git_repo / "fileB.txt").exists(), "child B's file missing after merge"
        assert (git_repo / "fileA.txt").read_text(encoding="utf-8") == "from fileA\n"
        assert (git_repo / "fileB.txt").read_text(encoding="utf-8") == "from fileB\n"

    def test_conflicting_merge_surfaces_conflict(self, git_repo: Path) -> None:
        """Two children writing the SAME file conflictingly: conflict surfaced, nothing forced."""
        import colleague.subagents as sa
        from colleague import worktrees

        def _fake_child(
            repo_path,
            child_id,
            instruction,
            *,
            parent_config,
            parent_engine,
            depth,
            engine=None,
            model=None,
            role=None,
            counter=None,
            spec=None,
        ):
            # Both children write the SAME path with DIFFERENT content -> conflict.
            wt = worktrees.worktree_add(repo_path, child_id)
            (Path(wt) / "shared.txt").write_text(f"content from {instruction}\n", encoding="utf-8")
            worktrees.commit_all(wt, f"child {child_id}")
            return SubResult(
                task_id=f"t-{child_id}",
                engine=engine or parent_engine,
                model=model or parent_config.model,
                status=OK,
                summary=f"wrote shared.txt as {instruction}",
                changed_files=["shared.txt"],
                usage=Usage(),
            )

        orig = sa._run_child_in_worktree
        sa._run_child_in_worktree = _fake_child
        try:
            batch = make_batch_spawn(str(git_repo), EngineConfig(), "mock")
            results = batch(_items("childX", "childY"))
        finally:
            sa._run_child_in_worktree = orig

        merge = results[-1]
        # The conflict is SURFACED — not OK, and the path is named in the summary.
        assert merge.status != OK, "a real conflict must not report OK"
        assert "shared.txt" in merge.summary, f"conflicted path not surfaced: {merge.summary!r}"
        # Nothing was force-merged into a clobbered single state silently: the repo
        # has no dangling merge in progress (we abort a conflicted merge), and the
        # two child branches are NOT both silently dropped — the conflict is recorded.
        # The working tree is left in a clean (non-conflicted) state.
        status = _git(git_repo, "status", "--porcelain")
        assert "UU" not in status.stdout, "an unresolved merge conflict leaked to the tree"

    def test_conflict_removes_worktree_but_RETAINS_branch(self, git_repo: Path) -> None:
        """On conflict: worktree DIRS are removed (no disk leak) but the conflicted
        child's ``sub/<id>`` branch is RETAINED so its committed work is not dropped.

        This is the corrected behavior (Qodo #2): the merge child's summary tells
        the operator to integrate the conflicted branch manually, so teardown must
        NOT force-delete it. The cleanly-merged child's branch IS deleted.
        """
        import colleague.subagents as sa
        from colleague import worktrees

        def _fake_child(
            repo_path,
            child_id,
            instruction,
            *,
            parent_config,
            parent_engine,
            depth,
            engine=None,
            model=None,
            role=None,
            counter=None,
            spec=None,
        ):
            wt = worktrees.worktree_add(repo_path, child_id)
            # Both children write the SAME path with DIFFERENT content -> the
            # second branch conflicts when merged after the first.
            (Path(wt) / "shared.txt").write_text(f"{instruction}\n", encoding="utf-8")
            worktrees.commit_all(wt, f"child {child_id}")
            return SubResult(
                task_id=f"t-{child_id}",
                engine=parent_engine,
                model=parent_config.model,
                status=OK,
                summary="wrote shared.txt",
                changed_files=["shared.txt"],
                usage=Usage(),
            )

        orig = sa._run_child_in_worktree
        sa._run_child_in_worktree = _fake_child
        try:
            batch = make_batch_spawn(str(git_repo), EngineConfig(), "mock")
            results = batch(_items("p", "q"))
        finally:
            sa._run_child_in_worktree = orig

        # No worktree DIRECTORY leak.
        wt_dir = str((git_repo / ".colleague" / "worktrees").resolve())
        assert [p for p in _worktree_paths(git_repo) if p.startswith(wt_dir)] == []

        # The merge child (last result) surfaces the conflict — it is NOT silent.
        merge_child = results[-1]
        assert merge_child.status == ERROR
        assert "CONFLICT" in merge_child.summary
        assert "manually" in merge_child.summary

        # Exactly the conflicted child's branch is RETAINED (work preserved); the
        # cleanly-merged child's branch is gone.
        retained = [b for b in _branch_list(git_repo) if b.startswith("sub/")]
        assert len(retained) == 1, f"expected the 1 conflicted branch retained, got {retained}"

        # And that retained branch actually carries a commit (the work survives).
        log = subprocess.run(
            ["git", "log", "--oneline", retained[0]],
            cwd=git_repo,
            capture_output=True,
            text=True,
            check=True,
        )
        assert log.stdout.strip(), "retained conflicted branch should carry the child's commit"


# ---------------------------------------------------------------------------
# (c) Concurrency proof: width>1 overlaps; width==1 never makes an executor.
# ---------------------------------------------------------------------------


_DELAY = 0.1


class TestConcurrency:
    def test_width_gt_1_runs_children_concurrently(self, git_repo: Path) -> None:
        """3 delayed children at width 3 overlap in flight.

        Asserted via a concurrency HIGH-WATER MARK (a shared counter of
        currently-sleeping children under a lock), not wall-clock elapsed time.
        A wall-clock threshold (the prior form of this test asserted
        ``elapsed < 0.6 * sequential_sum``) is a flaky-under-load anti-pattern:
        on a box also running many OTHER concurrent pytest-xdist workers (e.g.
        colleague's own multi-task parallel build topology — the #239
        "shifting failures... under pytest -n auto" class), thread scheduling
        can genuinely get starved past an absolute time budget with zero change
        in actual concurrency behavior, producing a spurious failure unrelated
        to any product regression (confirmed: this exact assertion flaked once
        under `pytest -n auto` for the full suite while passing every standalone
        rerun). A high-water mark is deterministic regardless of how slow the
        box is, as long as the sleeps genuinely overlap at all.
        """
        import colleague.subagents as sa

        active = 0
        high_water = 0
        state_lock = threading.Lock()

        def _slow_child(
            repo_path,
            child_id,
            instruction,
            *,
            parent_config,
            parent_engine,
            depth,
            engine=None,
            model=None,
            role=None,
            counter=None,
            spec=None,
        ):
            nonlocal active, high_water
            with state_lock:
                active += 1
                high_water = max(high_water, active)
            try:
                time.sleep(_DELAY)
            finally:
                with state_lock:
                    active -= 1
            return SubResult(
                task_id=f"t-{child_id}",
                engine=parent_engine,
                model=parent_config.model,
                status=OK,
                summary="slow child done",
                changed_files=[],
                usage=Usage(),
            )

        orig = sa._run_child_in_worktree
        sa._run_child_in_worktree = _slow_child
        try:
            cfg = EngineConfig(subagent_concurrency=3)
            batch = make_batch_spawn(str(git_repo), cfg, "mock")
            results = batch(_items("c1", "c2", "c3"))
        finally:
            sa._run_child_in_worktree = orig

        # 3 children + 1 merge child.
        assert len(results) == 4
        # At least 2 children were sleeping at the same instant -- true
        # sequential execution could never observe high_water > 1.
        assert high_water >= 2, (
            f"width=3 batch never observed 2+ children running concurrently "
            f"(high water mark={high_water}) — children did not overlap"
        )

    def test_width_1_never_creates_threadpool(self, git_repo: Path, monkeypatch) -> None:
        """With width==1, ThreadPoolExecutor must NEVER be instantiated."""

        class _Boom:
            def __init__(self, *a, **k):
                raise AssertionError(
                    "ThreadPoolExecutor was created on the width==1 sequential path"
                )

        monkeypatch.setattr(concurrent.futures, "ThreadPoolExecutor", _Boom)

        # Default subagent_concurrency is 1 -> effective width 1 -> sequential.
        cfg = EngineConfig()  # subagent_concurrency defaults to 1
        batch = make_batch_spawn(str(git_repo), cfg, "mock")
        # Two children: must run sequentially, no executor created.
        results = batch(_items("s1", "s2"))
        assert len(results) == 3  # 2 children + merge
        for r in results[:2]:
            assert r.status == OK

    def test_width_1_runs_children_in_order(self, git_repo: Path) -> None:
        """Width-1 sequential path still returns children in input order + merge."""
        import colleague.subagents as sa

        order: list[str] = []

        def _ordered_child(
            repo_path,
            child_id,
            instruction,
            *,
            parent_config,
            parent_engine,
            depth,
            engine=None,
            model=None,
            role=None,
            counter=None,
            spec=None,
        ):
            order.append(instruction)
            return SubResult(
                task_id=f"t-{child_id}",
                engine=parent_engine,
                model=parent_config.model,
                status=OK,
                summary=f"did {instruction}",
                changed_files=[],
                usage=Usage(),
            )

        orig = sa._run_child_in_worktree
        sa._run_child_in_worktree = _ordered_child
        try:
            cfg = EngineConfig()  # width 1
            batch = make_batch_spawn(str(git_repo), cfg, "mock")
            results = batch(_items("first", "second", "third"))
        finally:
            sa._run_child_in_worktree = orig

        assert order == ["first", "second", "third"]
        assert [r.summary for r in results[:3]] == ["did first", "did second", "did third"]


# ---------------------------------------------------------------------------
# Depth guard: a batch past the depth cap is refused before any work.
# ---------------------------------------------------------------------------


class TestDepthCap:
    def test_batch_past_depth_cap_refused(self, git_repo: Path) -> None:
        from colleague.config import MAX_SUBAGENT_DEPTH
        from colleague.subagents import SubagentError

        batch = make_batch_spawn(
            str(git_repo), EngineConfig(), "mock", depth=MAX_SUBAGENT_DEPTH + 1
        )
        with pytest.raises(SubagentError):
            batch(_items("x", "y"))
        # No worktrees were created.
        wt_dir = str((git_repo / ".colleague" / "worktrees").resolve())
        assert [p for p in _worktree_paths(git_repo) if p.startswith(wt_dir)] == []
