"""Tests for colleague/worktrees.py — per-child git worktree lifecycle.

Acceptance criteria (from t1 in the build plan):
1. worktree_add(repo, child_id) creates an isolated git worktree checked out on
   branch sub/<child_id>, using subprocess only.
2. Teardown is idempotent: after success, partial, or a simulated mid-run error,
   'git worktree list' shows no child worktrees under .colleague/worktrees and
   'git branch' lists no sub/<child_id> branches; a second teardown call is a no-op
   that raises nothing.
3. A write to the same repo-relative path from two different child worktrees does
   NOT affect the other worktree or the main working tree.
"""

from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path

import pytest

from colleague import worktrees

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run a git command in *repo*; raises CalledProcessError on failure."""
    return subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    )


def _git_unchecked(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run a git command in *repo*; never raises (returns the proc)."""
    return subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
    )


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    """A minimal git repo with one commit (required for 'git worktree add' to work)."""
    repo = tmp_path / "repo"
    repo.mkdir()

    # Configure git identity scoped to this repo only.
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@colleague.test")
    _git(repo, "config", "user.name", "Colleague Test")

    # Create an initial commit so worktree add has a HEAD to check out from.
    readme = repo / "README.md"
    readme.write_text("# test repo\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "initial commit")

    return repo


# ---------------------------------------------------------------------------
# Helpers shared across tests
# ---------------------------------------------------------------------------


def _worktree_paths(repo: Path) -> list[str]:
    """Return absolute paths of all worktrees registered for *repo*."""
    proc = _git(repo, "worktree", "list", "--porcelain")
    paths = []
    for line in proc.stdout.splitlines():
        if line.startswith("worktree "):
            paths.append(line[len("worktree ") :].strip())
    return paths


def _branch_list(repo: Path) -> list[str]:
    """Return all local branch names for *repo*.

    ``git branch --list`` prefixes the current branch with ``*`` and worktree
    branches with ``+``.  Strip all leading markers to get bare branch names.
    """
    proc = _git(repo, "branch", "--list")
    result = []
    for line in proc.stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # Remove leading * (current branch) or + (checked out in another worktree)
        name = stripped.lstrip("*+ ").strip()
        if name:
            result.append(name)
    return result


def _worktrees_dir(repo: Path) -> Path:
    return repo / ".colleague" / "worktrees"


# ---------------------------------------------------------------------------
# AC1 — worktree_add creates an isolated worktree on branch sub/<child_id>
# ---------------------------------------------------------------------------


class TestWorktreeAdd:
    """worktree_add creates the expected filesystem structure and git objects."""

    def test_returns_expected_path(self, git_repo: Path) -> None:
        from colleague.worktrees import worktree_add

        path = worktree_add(str(git_repo), "child-1")
        expected = str(_worktrees_dir(git_repo) / "child-1")
        assert path == expected

    def test_directory_exists_after_add(self, git_repo: Path) -> None:
        from colleague.worktrees import worktree_add

        path = worktree_add(str(git_repo), "child-2")
        assert Path(path).is_dir(), f"Expected worktree dir to exist at {path}"

    def test_branch_created_after_add(self, git_repo: Path) -> None:
        from colleague.worktrees import worktree_add

        worktree_add(str(git_repo), "child-3")
        branches = _branch_list(git_repo)
        assert "sub/child-3" in branches, f"Expected branch sub/child-3 in {branches}"

    def test_worktree_appears_in_git_worktree_list(self, git_repo: Path) -> None:
        from colleague.worktrees import worktree_add

        wt_path = worktree_add(str(git_repo), "child-4")
        paths = _worktree_paths(git_repo)
        assert wt_path in paths, f"Expected {wt_path} in git worktree list: {paths}"

    def test_worktree_checked_out_on_correct_branch(self, git_repo: Path) -> None:
        from colleague.worktrees import worktree_add

        wt_path = worktree_add(str(git_repo), "child-5")
        # Check which branch the worktree is on.
        proc = _git(Path(wt_path), "branch", "--show-current")
        branch = proc.stdout.strip()
        assert branch == "sub/child-5", f"Expected branch sub/child-5, got {branch!r}"

    def test_worktree_add_does_not_touch_gitignore(self, git_repo: Path) -> None:
        """worktree_add MUST NOT write the shared .gitignore.

        It is called from parallel worker threads (the batch path); a
        read/append/write of the shared .gitignore would race and dirty the main
        working tree during the parallel phase. The repo already ignores
        ``/.colleague/*``, so the write is unnecessary as well as unsafe. Adding a
        worktree must leave .gitignore byte-identical (or absent if it was absent).
        """
        from colleague.worktrees import worktree_add

        gitignore = git_repo / ".gitignore"
        before = gitignore.read_text(encoding="utf-8") if gitignore.exists() else None

        worktree_add(str(git_repo), "child-6")
        worktree_add(str(git_repo), "child-7")

        after = gitignore.read_text(encoding="utf-8") if gitignore.exists() else None
        assert after == before, (
            "worktree_add modified .gitignore — it must never write the shared "
            f"working tree. before={before!r} after={after!r}"
        )

    def test_subprocess_only_no_git_import(self, git_repo: Path) -> None:
        """worktrees.py must not import the git Python library — stdlib subprocess only."""
        import importlib
        import sys

        # Snapshot + remove for a fresh load, then RESTORE the original module:
        # leaving a re-imported module in sys.modules poisons identity
        # assertions in later same-worker tests (the test_context_window /
        # test_deepthink xdist collision class).
        saved = sys.modules.get("colleague.worktrees")
        if saved is not None:
            del sys.modules["colleague.worktrees"]

        try:
            mod = importlib.import_module("colleague.worktrees")
            # The module object must not have imported 'git' (GitPython) or similar.
            assert (
                not hasattr(mod, "git")
                or getattr(mod, "git", None) is None
                or callable(getattr(mod, "git", None))
            ), "worktrees.py must not import the 'git' library"
        finally:
            if saved is not None:
                sys.modules["colleague.worktrees"] = saved
        # Quick sanity: the module uses subprocess
        import subprocess as sp

        assert sp is not None


# ---------------------------------------------------------------------------
# AC2 — Idempotent teardown
# ---------------------------------------------------------------------------


class TestWorktreeRemoveIdempotent:
    """worktree_remove is idempotent: no raise on repeated or partial teardown."""

    def test_remove_existing_worktree(self, git_repo: Path) -> None:
        from colleague.worktrees import worktree_add, worktree_remove

        worktree_add(str(git_repo), "rem-1")
        worktree_remove(str(git_repo), "rem-1")

        paths = _worktree_paths(git_repo)
        child_path = str(_worktrees_dir(git_repo) / "rem-1")
        assert child_path not in paths, f"Worktree still listed after remove: {paths}"

    def test_remove_deletes_branch(self, git_repo: Path) -> None:
        from colleague.worktrees import worktree_add, worktree_remove

        worktree_add(str(git_repo), "rem-2")
        worktree_remove(str(git_repo), "rem-2")

        branches = _branch_list(git_repo)
        assert "sub/rem-2" not in branches, f"Branch still exists after remove: {branches}"

    def test_remove_nonexistent_is_noop(self, git_repo: Path) -> None:
        """Calling remove on a child that was never added must not raise."""
        from colleague.worktrees import worktree_remove

        # Should complete silently.
        worktree_remove(str(git_repo), "never-existed")

    def test_double_remove_is_noop(self, git_repo: Path) -> None:
        """Calling remove twice on the same child must not raise the second time."""
        from colleague.worktrees import worktree_add, worktree_remove

        worktree_add(str(git_repo), "double-1")
        worktree_remove(str(git_repo), "double-1")
        # Second call — must be a silent no-op.
        worktree_remove(str(git_repo), "double-1")

    def test_remove_after_directory_manually_deleted(self, git_repo: Path) -> None:
        """If the worktree directory was deleted externally, remove still cleans up."""
        import shutil

        from colleague.worktrees import worktree_add, worktree_remove

        wt_path = worktree_add(str(git_repo), "partial-1")
        # Simulate a mid-run crash by forcibly removing the directory.
        shutil.rmtree(wt_path)
        # Should not raise even though the dir is gone.
        worktree_remove(str(git_repo), "partial-1")
        # Branch should also be cleaned up.
        branches = _branch_list(git_repo)
        assert (
            "sub/partial-1" not in branches
        ), f"Branch sub/partial-1 still listed after partial teardown: {branches}"


class TestTeardownAll:
    """teardown_all removes ALL .colleague/worktrees/* entries and sub/* branches."""

    def test_teardown_all_removes_multiple_worktrees(self, git_repo: Path) -> None:
        from colleague.worktrees import teardown_all, worktree_add

        worktree_add(str(git_repo), "ta-1")
        worktree_add(str(git_repo), "ta-2")
        worktree_add(str(git_repo), "ta-3")

        teardown_all(str(git_repo))

        wt_dir = str(_worktrees_dir(git_repo))
        paths = _worktree_paths(git_repo)
        leftover = [p for p in paths if p.startswith(wt_dir)]
        assert leftover == [], f"Leftover worktrees after teardown_all: {leftover}"

        branches = _branch_list(git_repo)
        sub_branches = [b for b in branches if b.startswith("sub/")]
        assert sub_branches == [], f"Leftover sub/* branches after teardown_all: {sub_branches}"

    def test_teardown_all_when_none_exist(self, git_repo: Path) -> None:
        """teardown_all with no child worktrees is a silent no-op."""
        from colleague.worktrees import teardown_all

        teardown_all(str(git_repo))

    def test_teardown_all_twice_is_noop(self, git_repo: Path) -> None:
        from colleague.worktrees import teardown_all, worktree_add

        worktree_add(str(git_repo), "tt-1")
        teardown_all(str(git_repo))
        # Second call — must not raise.
        teardown_all(str(git_repo))

    def test_teardown_all_runs_git_worktree_prune(self, git_repo: Path) -> None:
        """After teardown_all, git worktree prune should be a no-op (nothing left to prune)."""
        from colleague.worktrees import teardown_all, worktree_add

        worktree_add(str(git_repo), "prune-1")
        teardown_all(str(git_repo))

        # Running prune again must succeed (returncode 0) — nothing left to clean.
        proc = _git_unchecked(git_repo, "worktree", "prune")
        assert proc.returncode == 0, f"git worktree prune failed: {proc.stderr}"

    def test_teardown_all_preserves_unrelated_sub_branch(self, git_repo: Path) -> None:
        """teardown_all must NOT delete a user's own ``sub/*`` branch (Qodo #4).

        Scope is limited to worktrees under ``.colleague/worktrees/``; a branch that
        merely uses the ``sub/`` prefix but has no worktree under our root (e.g. a
        user's own ``sub/user-feature``) is left untouched, while colleague's own
        child worktree + branch are still cleaned.
        """
        from colleague.worktrees import teardown_all, worktree_add

        # A user branch that merely uses the sub/ prefix — NOT created by colleague.
        _git_unchecked(git_repo, "branch", "sub/user-feature")

        # A real colleague worktree + branch.
        worktree_add(str(git_repo), "ours-1")

        teardown_all(str(git_repo))

        branches = _git_unchecked(git_repo, "branch", "--list").stdout
        assert "sub/user-feature" in branches, "teardown_all deleted an UNRELATED user branch"
        assert "sub/ours-1" not in branches, "colleague's own child branch should be cleaned"


# ---------------------------------------------------------------------------
# AC3 — Isolation: writes in one worktree don't affect other worktrees or main
# ---------------------------------------------------------------------------


class TestWorktreeIsolation:
    """Writes from different child worktrees do not affect each other or the main tree."""

    def test_writes_isolated_between_children(self, git_repo: Path) -> None:
        from colleague.worktrees import teardown_all, worktree_add

        wt_a = Path(worktree_add(str(git_repo), "iso-a"))
        wt_b = Path(worktree_add(str(git_repo), "iso-b"))

        # Both children write to the same repo-relative path "foo.txt"
        (wt_a / "foo.txt").write_text("content from child A\n", encoding="utf-8")
        (wt_b / "foo.txt").write_text("content from child B\n", encoding="utf-8")

        # Child A's foo.txt must contain only A's content.
        assert (wt_a / "foo.txt").read_text(
            encoding="utf-8"
        ) == "content from child A\n", "Child A's foo.txt was corrupted by child B's write"
        # Child B's foo.txt must contain only B's content.
        assert (wt_b / "foo.txt").read_text(
            encoding="utf-8"
        ) == "content from child B\n", "Child B's foo.txt was corrupted by child A's write"
        # The main working tree must have no foo.txt (it was never written there).
        assert not (
            git_repo / "foo.txt"
        ).exists(), "foo.txt appeared in the main working tree from a child write"

        teardown_all(str(git_repo))

    def test_write_in_child_does_not_modify_main_tree(self, git_repo: Path) -> None:
        from colleague.worktrees import worktree_add, worktree_remove

        wt = Path(worktree_add(str(git_repo), "iso-main"))

        # Write a new file inside the child worktree only.
        (wt / "child_only.txt").write_text("child content\n", encoding="utf-8")

        # Main tree must not see this file.
        assert not (
            git_repo / "child_only.txt"
        ).exists(), "child_only.txt leaked into the main working tree"

        worktree_remove(str(git_repo), "iso-main")


# ---------------------------------------------------------------------------
# #239 — concurrent-run gate correctness: the git worktree ADMIN directory
# (.git/worktrees/) is shared across every worktree of one repo. Unguarded
# concurrent add/remove/prune from SEPARATE colleague processes sharing a repo
# corrupts each other's view of that shared admin state, making
# isolation_worktree_add raise — which used to make _setup_isolation silently
# degrade THAT run to running in-place on the operator's real (shared) repo,
# where a second concurrent run's uncommitted files leak into the degraded
# run's changed-file scan / gate pytest invocation. _admin_lock (an advisory
# fcntl file lock over .colleague/worktrees/.worktree-admin.lock) serializes
# only the admin mutation itself so concurrent runs never race on it.
# ---------------------------------------------------------------------------


class TestConcurrentAdminMutations:
    def test_concurrent_isolation_cycles_never_race(self, git_repo: Path) -> None:
        """Reproduces #239's root mechanism deterministically: many threads each
        running isolation_worktree_add -> write -> isolation_worktree_remove
        concurrently against ONE shared repo must never raise. Before the
        _admin_lock fix this reliably reproduced git errors like::

            fatal: failed to read .git/worktrees/iso-t9-1/commondir: Success
            fatal: could not open '.git/worktrees/iso-t2-1/gitdir' for writing: ...

        i.e. one task's ``worktree add`` failing because a DIFFERENT task's
        concurrent remove/prune corrupted the shared .git/worktrees/ admin
        directory mid-flight — the "prune timing" / "worktree lock contention"
        mechanism #239 named. This is a pure git/OS-level integration test (real
        threads, real subprocess git calls), not a mock — the race is real.
        """
        errors: list[tuple[str, Exception]] = []
        lock = threading.Lock()
        n_threads = 10
        n_cycles = 12

        def worker(i: int) -> None:
            for c in range(n_cycles):
                task_id = f"t{i}-{c}"
                branch = f"colleague/{task_id}"
                try:
                    wt = worktrees.isolation_worktree_add(str(git_repo), task_id, branch)
                    (Path(wt) / f"file-{i}-{c}.txt").write_text("x", encoding="utf-8")
                    worktrees.isolation_worktree_remove(str(git_repo), wt)
                except Exception as exc:  # noqa: BLE001 - collecting for the assertion
                    with lock:
                        errors.append((task_id, exc))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], (
            f"{len(errors)}/{n_threads * n_cycles} concurrent isolation worktree "
            f"cycles raised (first: {errors[0] if errors else None})"
        )
        # No leftover branches/worktrees — every cycle's remove ran cleanly.
        remaining = _git(git_repo, "worktree", "list", "--porcelain").stdout
        assert "iso-t" not in remaining

    def test_concurrent_mixed_sub_and_iso_worktrees_never_race(self, git_repo: Path) -> None:
        """The admin lock guards BOTH worktree_add (sub/<id>, the subagent-batch
        path) and isolation_worktree_add (iso-<id>, the work-item path) — they
        share one repo's .git/worktrees/ admin directory, so a concurrent mix of
        both must be race-free too."""
        errors: list[tuple[str, Exception]] = []
        lock = threading.Lock()
        n_threads = 6
        n_cycles = 8

        def worker_iso(i: int) -> None:
            for c in range(n_cycles):
                task_id = f"i{i}-{c}"
                try:
                    wt = worktrees.isolation_worktree_add(
                        str(git_repo), task_id, f"colleague/{task_id}"
                    )
                    worktrees.isolation_worktree_remove(str(git_repo), wt)
                except Exception as exc:  # noqa: BLE001
                    with lock:
                        errors.append((f"iso-{task_id}", exc))

        def worker_sub(i: int) -> None:
            for c in range(n_cycles):
                child_id = f"s{i}-{c}"
                try:
                    worktrees.worktree_add(str(git_repo), child_id)
                    worktrees.worktree_remove(str(git_repo), child_id)
                except Exception as exc:  # noqa: BLE001
                    with lock:
                        errors.append((f"sub-{child_id}", exc))

        threads = []
        for i in range(n_threads):
            threads.append(threading.Thread(target=worker_iso, args=(i,)))
            threads.append(threading.Thread(target=worker_sub, args=(i,)))
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], (
            f"{len(errors)} concurrent mixed worktree cycles raised "
            f"(first: {errors[0] if errors else None})"
        )


class TestIsolationLivenessMarker:
    """#239 h1: colleague clean must never flag a LIVE run's isolation worktree
    as reapable. isolation_worktree_add stamps a pid-file liveness marker
    (mirroring colleague/rig.py's os.kill(pid, 0) probe) that reap_orphaned_
    iso_worktrees consults BEFORE the caller-supplied active_task_ids
    (flight-tracking) signal, so a bare (non-``--watch``) `colleague work` run
    — which never registers as an active flight — is still recognized as live.
    """

    def test_add_writes_liveness_marker_with_current_pid(self, git_repo: Path) -> None:
        worktrees.isolation_worktree_add(str(git_repo), "live1", "colleague/live1")
        marker = worktrees.iso_liveness_path(str(git_repo), "live1")
        assert marker.exists()
        assert marker.read_text(encoding="utf-8").strip() == str(os.getpid())

    def test_remove_clears_liveness_marker(self, git_repo: Path) -> None:
        wt = worktrees.isolation_worktree_add(str(git_repo), "live2", "colleague/live2")
        marker = worktrees.iso_liveness_path(str(git_repo), "live2")
        assert marker.exists()
        worktrees.isolation_worktree_remove(str(git_repo), wt)
        assert not marker.exists()

    def test_iso_worktree_is_live_true_for_current_process(self, git_repo: Path) -> None:
        worktrees.isolation_worktree_add(str(git_repo), "live3", "colleague/live3")
        assert worktrees.iso_worktree_is_live(str(git_repo), "live3") is True

    def test_iso_worktree_is_live_false_when_marker_absent(self, git_repo: Path) -> None:
        # No worktree/marker for this task id at all.
        assert worktrees.iso_worktree_is_live(str(git_repo), "never-existed") is False

    def test_iso_worktree_is_live_false_for_dead_pid(self, git_repo: Path) -> None:
        worktrees.isolation_worktree_add(str(git_repo), "dead1", "colleague/dead1")
        marker = worktrees.iso_liveness_path(str(git_repo), "dead1")
        marker.write_text(str(_dead_pid()), encoding="utf-8")
        assert worktrees.iso_worktree_is_live(str(git_repo), "dead1") is False

    def test_reap_spares_a_live_runs_worktree_with_no_active_task_ids(self, git_repo: Path) -> None:
        """The headline #239 regression: `colleague clean --dry-run` flagged a
        LIVE (in-flight, un-watched) run's isolation worktree as "would reap"
        because the only signal it had was active_task_ids (flight tracking),
        which a bare `colleague work` (no --watch) never populates. The
        liveness marker alone must now spare it."""
        live = worktrees.isolation_worktree_add(str(git_repo), "inflight", "colleague/inflight")

        # No active_task_ids passed — mirrors an un-watched run mid-flight.
        reaped = worktrees.reap_orphaned_iso_worktrees(str(git_repo))
        assert reaped == []
        assert Path(live).exists()

        reported = worktrees.reap_orphaned_iso_worktrees(str(git_repo), dry_run=True)
        assert reported == []  # dry-run must not list it as "would reap" either

    def test_reap_still_reaps_a_dead_holders_worktree(self, git_repo: Path) -> None:
        """A worktree whose creating process has actually exited (a crashed run,
        #222's motivating case) remains reapable — the liveness marker degrading
        to a dead PID must not make orphaned residue permanently un-reapable."""
        orphan = worktrees.isolation_worktree_add(str(git_repo), "crashed1", "colleague/crashed1")
        marker = worktrees.iso_liveness_path(str(git_repo), "crashed1")
        marker.write_text(str(_dead_pid()), encoding="utf-8")

        reaped = worktrees.reap_orphaned_iso_worktrees(str(git_repo))
        assert reaped == [orphan]
        assert not Path(orphan).exists()

    def test_reap_missing_marker_falls_back_to_active_task_ids(self, git_repo: Path) -> None:
        """A worktree with no marker at all (e.g. created by a pre-#239 colleague
        version) preserves the old behavior exactly: reap-by-default, spared only
        via active_task_ids."""
        orphan = worktrees.isolation_worktree_add(str(git_repo), "legacy1", "colleague/legacy1")
        worktrees.iso_liveness_path(str(git_repo), "legacy1").unlink()

        reaped = worktrees.reap_orphaned_iso_worktrees(str(git_repo))
        assert reaped == [orphan]


def _dead_pid() -> int:
    """A PID guaranteed to have already exited (spawn a trivial process, reap it)."""
    proc = subprocess.Popen(
        [os.environ.get("COMSPEC", "true")] if os.name == "nt" else ["true"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    proc.wait()
    return proc.pid
