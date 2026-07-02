"""Per-child git worktree + branch lifecycle for parallel subagent isolation.

Each parallel subagent child runs inside its OWN throwaway git worktree so that
concurrent writes never interfere.  This module owns the create/commit/merge/
remove cycle:

- ``worktree_add(repo_path, child_id)`` — create an isolated worktree on a fresh
  ``sub/<child_id>`` branch under ``.colleague/worktrees/<child_id>/``.
- ``commit_all(worktree_path, message)`` — stage every change in a child worktree
  and commit it onto its ``sub/<child_id>`` branch (so the branch carries the
  child's work for the post-join merge).  Returns ``True`` when a commit was made,
  ``False`` when the child produced no change (an empty diff is not an error).
- ``merge_branch(repo_path, child_id)`` — SEQUENTIALLY merge a child's
  ``sub/<child_id>`` branch into the working branch of *repo_path*.  Returns a
  :class:`MergeOutcome` describing whether the merge was clean, a no-op (nothing
  to bring in), or CONFLICTED; on conflict the merge is ABORTED so the working
  tree is left clean and the conflict is surfaced (never force-merged, never
  silently dropped).
- ``worktree_remove(repo_path, child_id)`` — idempotently remove the worktree and
  delete its branch; safe to call after a partial or errored child run.
- ``teardown_all(repo_path)`` — idempotently remove EVERY ``.colleague/worktrees/*``
  worktree and every ``sub/*`` branch, then run ``git worktree prune``; safe to call
  when none exist.

Design constraints (matching the rest of the colleague runtime):
- **Zero runtime dependencies** — stdlib only (``pathlib``, ``subprocess``).
- **subprocess-only git** — all git operations use ``subprocess.run([...])`` with a
  list argv (never ``shell=True``) for clarity and security.  This module is
  explicitly added to the ``_SUBPROCESS_ALLOWED`` frozenset in ``test_boundary.py``.
- **No socket, no daemon, no thread** — worktrees.py itself is single-threaded; the
  ThreadPoolExecutor that *calls* these functions lives in ``subagents.py`` only.
- **Idempotent teardown** — "not found" git exit codes are swallowed silently so that
  cleanup is always safe to call, even after a partial run or a crash.
"""

from __future__ import annotations

import os
import subprocess  # nosec B404 - driving git for worktree lifecycle is this module's job
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

try:
    import fcntl  # POSIX-only; guarded so a non-POSIX host degrades, never crashes.
except ImportError:  # pragma: no cover - exercised only on a non-POSIX host
    fcntl = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_WORKTREES_SUBDIR = ".colleague/worktrees"
#: Line prefix git emits for each entry of ``git worktree list --porcelain``.
_WORKTREE_LIST_PREFIX = "worktree "
#: Advisory lock file guarding git worktree ADMIN mutations (add/remove/prune)
#: for one repo (#239). See :func:`_admin_lock`.
_ADMIN_LOCK_NAME = ".worktree-admin.lock"


def _git(
    cwd: Path,
    *args: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run a git sub-command in *cwd*; raises on non-zero exit when *check* is True."""
    return subprocess.run(  # nosec B603 B607 - fixed 'git' argv, no shell
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=check,
    )


def _worktree_path(repo: Path, child_id: str) -> Path:
    """Return the expected worktree directory for *child_id* (not yet created)."""
    return repo / _WORKTREES_SUBDIR / child_id


def _branch_name(child_id: str) -> str:
    return f"sub/{child_id}"


@contextmanager
def _admin_lock(repo: Path) -> Iterator[None]:
    """Serialize git worktree ADMIN mutations (add/remove/prune) for *repo* (#239).

    git's own bookkeeping under ``.git/worktrees/<name>/`` is NOT safe against
    concurrent ``add``/``remove``/``prune`` invoked from separate colleague
    processes sharing one repo: a worktree mid-creation can be corrupted by an
    unrelated worktree's concurrent prune. Reproduced empirically — 8 threads x
    10 ``isolation_worktree_add``/``isolation_worktree_remove`` cycles against one
    shared repo raised ``CalledProcessError`` with git stderr like::

        fatal: failed to read .git/worktrees/iso-t9-1/commondir: Success
        fatal: could not open '.git/worktrees/iso-t2-1/gitdir' for writing: ...

    i.e. task ``t1-1``'s ``worktree add`` failed while reading/writing a
    DIFFERENT task's (``t9-1``, ``t2-1``) administrative entry — the shared
    ``.git/worktrees/`` directory listing was corrupted mid-flight by a
    concurrent prune/remove. This is the mechanism behind #239's spurious
    concurrent-run gate failures: ``isolation_worktree_add`` raising makes
    ``colleague/cli/_commands/work.py``'s ``_setup_isolation`` silently degrade
    that run to running IN-PLACE on the operator's real (shared) repo (the h7
    back-compat fallback) — at which point a SECOND concurrent run sharing that
    same directory can leak its own uncommitted files into the degraded run's
    changed-file scan / gate pytest invocation.

    A single advisory OS file lock (``fcntl.flock``, exclusive) over
    ``.colleague/worktrees/.worktree-admin.lock`` serializes ONLY the brief
    admin mutation itself (a handful of milliseconds) — never the work done
    inside an already-created worktree, so real subagent/work-item parallelism
    is untouched. Degrades to a no-op (unserialized, matching every other git
    call's best-effort tolerance in this module) when ``fcntl`` is unavailable
    (non-POSIX) or the lock file can't be opened — never raises, never blocks a
    run that has no lock available. NOT reentrant: callers in this module never
    nest one lock-guarded call inside another (e.g. :func:`teardown_all` calls
    the already-guarded :func:`worktree_remove` sequentially, never while
    holding its own lock).
    """
    lock_path = repo / _WORKTREES_SUBDIR / _ADMIN_LOCK_NAME
    handle = None
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(lock_path, "a+", encoding="utf-8")  # noqa: SIM115
    except OSError:
        handle = None
    if handle is not None and fcntl is not None:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except OSError:
            pass
    try:
        yield
    finally:
        if handle is not None:
            if fcntl is not None:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
            handle.close()


def iso_liveness_path(repo_path: str, task_id: str) -> Path:
    """Path to *task_id*'s isolation-worktree liveness marker (a pid file, #239).

    Mirrors :mod:`colleague.flight`'s ``feed_path``/``control_path`` pattern — a
    small, discoverable, public path helper so a caller (or a test) can inspect
    or fabricate the marker directly rather than re-deriving the naming scheme.
    """
    return Path(repo_path).resolve() / _WORKTREES_SUBDIR / f"iso-{task_id}.pid"


def _pid_alive(pid: int) -> bool:
    """Best-effort same-host liveness probe (mirrors ``colleague/rig.py``'s probe)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        # Exists but not ours (PermissionError) or unprobeable — treat as
        # alive, never steal/reap a holder we can't rule out.
        return True
    return True


def _write_liveness_marker(repo: Path, task_id: str) -> None:
    """Best-effort: stamp this process's PID as the holder of *task_id*'s worktree."""
    try:
        iso_liveness_path(str(repo), task_id).write_text(str(os.getpid()), encoding="utf-8")
    except OSError:
        pass  # a missing marker just falls back to the caller's active_task_ids signal


def _clear_liveness_marker(repo: Path, task_id: str) -> None:
    """Best-effort: remove *task_id*'s liveness marker; tolerates "already gone"."""
    try:
        iso_liveness_path(str(repo), task_id).unlink(missing_ok=True)
    except OSError:
        pass


def iso_worktree_is_live(repo_path: str, task_id: str) -> bool:
    """True when *task_id*'s isolation worktree has a liveness marker naming a
    still-running process (#239 h1).

    This is the pidfile companion to a caller-supplied ``active_task_ids``
    allow-list (e.g. flight tracking): a bare ``colleague work`` run (no
    ``--watch``) never registers as an active flight, so ``colleague clean
    --dry-run`` was flagging a genuinely live run's isolation worktree as
    "would reap" — the only signal it had was flight tracking. A missing or
    unreadable marker degrades to ``False`` (no opinion; the caller's
    ``active_task_ids``/flight check remains the fallback signal, preserving
    back-compat for worktrees created before this marker existed).
    """
    try:
        pid = int(iso_liveness_path(repo_path, task_id).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    return _pid_alive(pid)


@dataclass
class MergeOutcome:
    """The result of merging one ``sub/<child_id>`` branch into the working branch.

    Fields
    ------
    child_id:
        The child whose branch was merged.
    status:
        One of ``"merged"`` (clean integration, a merge commit or fast-forward was
        made), ``"noop"`` (nothing to bring in — the child branch is already an
        ancestor / produced no change), or ``"conflict"`` (the merge could not be
        completed cleanly and was ABORTED, leaving the working tree untouched).
    conflicted_paths:
        Repo-relative paths git reported as conflicting (only populated when
        ``status == "conflict"``); empty otherwise.
    detail:
        A short human-readable note (git stderr/stdout excerpt) for diagnostics.
    """

    child_id: str
    status: str
    conflicted_paths: list[str]
    detail: str = ""

    MERGED = "merged"
    NOOP = "noop"
    CONFLICT = "conflict"

    @property
    def clean(self) -> bool:
        """True when the merge integrated cleanly (or was a harmless no-op)."""
        return self.status in (self.MERGED, self.NOOP)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def worktree_add(repo_path: str, child_id: str) -> str:
    """Create an isolated git worktree for *child_id* on branch ``sub/<child_id>``.

    The worktree is placed at ``<repo_path>/.colleague/worktrees/<child_id>/``.
    The parent ``.colleague/worktrees/`` directory is ensured before the git call.
    This function does NOT modify the repo's ``.gitignore`` — it is called from
    parallel worker threads and must never write the shared working tree (the repo
    already ignores ``/.colleague/*``).

    Args:
        repo_path: Absolute (or relative) path to the git repository root.
        child_id: Unique identifier for this child subagent; used as both the
            directory name and the branch-name suffix.

    Returns:
        The absolute path of the newly created worktree directory (as a string).

    Raises:
        subprocess.CalledProcessError: if ``git worktree add`` fails.
    """
    repo = Path(repo_path).resolve()
    wt_path = _worktree_path(repo, child_id)
    branch = _branch_name(child_id)

    # Ensure the parent directory exists so git can place the worktree.
    wt_path.parent.mkdir(parents=True, exist_ok=True)

    # NOTE: we deliberately do NOT touch the repo's .gitignore here. worktree_add
    # is called from parallel worker threads (the batch path), and a
    # read/append/write of the shared .gitignore would (a) race across threads and
    # (b) dirty the main working tree DURING the parallel phase — both forbidden by
    # the spec (the parallel phase never writes the shared tree). It is also
    # unnecessary: the repo already ignores ``/.colleague/*`` (which covers
    # ``.colleague/worktrees/``). A git worktree lives in its own administrative
    # space anyway; the directory is not added to the parent index.
    #
    # The add is admin-lock-guarded (#239): a concurrent add/remove/prune from a
    # SEPARATE colleague process sharing this repo can corrupt this call's view of
    # the shared .git/worktrees/ admin directory (see _admin_lock's docstring for
    # the reproduced failure mode). Real subagent parallelism is unaffected — only
    # this brief admin mutation is serialized.
    with _admin_lock(repo):
        _git(repo, "worktree", "add", str(wt_path), "-b", branch)

    return str(wt_path)


def isolation_worktree_add(repo_path: str, task_id: str, branch: str) -> str:
    """Create an isolated worktree at HEAD on *branch* for an isolated write item (#196/#201).

    Unlike :func:`worktree_add` (which mints a ``sub/<id>`` branch for a parallel
    subagent child), this places the worktree on the caller-supplied work branch —
    the ``colleague/<id>`` name the handoff will use — so a model self-commit
    *during* the run lands on that branch directly, never on the operator's
    checked-out branch (#196). The worktree is created at the repo's current HEAD,
    so the operator's uncommitted edits are deliberately excluded (clean-HEAD
    isolation; ``--allow-dirty`` is moot for the isolated path — q1). Two concurrent
    isolated runs get distinct ``iso-<task_id>`` worktrees, so they can never
    cross-pollute each other's working tree (#201).

    Args:
        repo_path: Absolute (or relative) path to the git repository root.
        task_id: The work item's task id; names the worktree directory.
        branch: The work branch to create the worktree on (``colleague/<id>``).

    Returns:
        The absolute path of the newly created worktree directory (as a string).
    """
    repo = Path(repo_path).resolve()
    wt_path = repo / _WORKTREES_SUBDIR / f"iso-{task_id}"
    wt_path.parent.mkdir(parents=True, exist_ok=True)
    # Reclaim any leftovers a crashed prior run with this task id left behind: a
    # stale worktree dir or the ``colleague/<id>`` branch would make ``worktree add
    # -b`` fail and silently drop isolation back to the in-place path (colleague
    # review of t1, finding A). The branch is recreated from HEAD below, so dropping
    # the stale one loses nothing the operator could still recover (a same-id retry
    # only happens after a crash). All tolerant (``check=False``).
    #
    # The whole reclaim+add sequence is admin-lock-guarded (#239): unguarded, a
    # SEPARATE concurrent colleague process's own add/remove/prune on this shared
    # repo can corrupt this sequence's view of .git/worktrees/ (reproduced
    # empirically — see _admin_lock), which used to make this call raise and
    # silently degrade the run to in-place (h7's fallback) — the mechanism behind
    # #239's spurious concurrent-run gate failures.
    with _admin_lock(repo):
        _git(repo, "worktree", "remove", "--force", str(wt_path), check=False)
        _git(repo, "worktree", "prune", check=False)
        _git(repo, "branch", "-D", branch, check=False)
        _git(repo, "worktree", "add", str(wt_path), "-b", branch)
    # Liveness marker (#239 h1): stamp this process as the worktree's holder so
    # `colleague clean` never mistakes a still-running work item for orphaned
    # residue, regardless of whether it is also tracked as an active flight.
    _write_liveness_marker(repo, task_id)
    return str(wt_path)


def isolation_worktree_remove(repo_path: str, worktree_path: str) -> None:
    """Idempotently remove an isolation worktree, KEEPING its ``colleague/<id>`` branch.

    The branch is the deliverable (the operator merges it), so only the working
    directory is torn down. Best-effort: a teardown failure must never mask the
    work item's real outcome, so git errors are swallowed (``check=False``) and a
    trailing ``prune`` clears any stale administrative entry. Admin-lock-guarded
    (#239, see :func:`_admin_lock`); also clears the task's liveness marker (#239
    h1) written by :func:`isolation_worktree_add`, if any.
    """
    repo = Path(repo_path).resolve()
    with _admin_lock(repo):
        _git(repo, "worktree", "remove", "--force", str(worktree_path), check=False)
        _git(repo, "worktree", "prune", check=False)
    name = Path(worktree_path).name
    if name.startswith("iso-"):
        _clear_liveness_marker(repo, name[len("iso-") :])


def commit_all(worktree_path: str, message: str) -> bool:
    """Stage and commit every change inside a child worktree onto its sub branch.

    Runs ``git add -A`` then ``git commit -m <message>`` with ``cwd`` pinned to
    *worktree_path* (so the commit lands on the worktree's checked-out
    ``sub/<child_id>`` branch, not the parent working branch).

    An EMPTY diff is NOT an error — a child that wrote nothing simply has nothing
    to commit, and this returns ``False`` rather than raising.  A child commit
    identity is set inline (``-c user.name/-c user.email``) so the commit succeeds
    even in a worktree that inherited no committer config; this never mutates the
    repo's persisted git config.

    Args:
        worktree_path: Path to the child's worktree directory.
        message: The commit message.

    Returns:
        ``True`` if a commit was created, ``False`` if there was nothing to commit.
    """
    wt = Path(worktree_path)

    # Stage everything (new, modified, deleted).
    _git(wt, "add", "-A")

    # If the index matches HEAD there is nothing to commit — report False, not error.
    status = _git(wt, "status", "--porcelain", check=False)
    if status.returncode == 0 and not status.stdout.strip():
        return False

    # Commit with an inline identity so this works even when no committer is
    # configured for the worktree (the -c flags are per-invocation, not persisted).
    proc = _git(
        wt,
        "-c",
        "user.name=colleague-subagent",
        "-c",
        "user.email=subagent@colleague.local",
        "commit",
        "-m",
        message,
        check=False,
    )
    # A non-zero exit with "nothing to commit" in the output is still a no-op, not
    # a failure (covers a race where the index ended up clean after staging).
    if proc.returncode != 0:
        combined = (proc.stdout or "") + (proc.stderr or "")
        if "nothing to commit" in combined:
            return False
        raise subprocess.CalledProcessError(
            proc.returncode, proc.args, output=proc.stdout, stderr=proc.stderr
        )
    return True


def commit_iso_worktree_wip(worktree_path: str, *, reason: str = "interrupt") -> bool:
    """Commit an isolated work item's in-progress changes onto its ``colleague/<id>`` branch.

    Used on an ABNORMAL exit — a SIGTERM (a caller's ``timeout``), a Ctrl-C, or a
    cooperative stop — to preserve the model's work-in-progress that the success-path
    handoff would otherwise have committed (#222). A thin wrapper over
    :func:`commit_all`: it stages and commits everything in the worktree onto its
    checked-out branch (``colleague/<id>`` for an isolation worktree), returning
    ``True`` when a commit was made and ``False`` on an empty diff. Best-effort and
    idempotent — an empty diff is a no-op, never an error — so a handler can call it
    unconditionally on the way out.
    """
    return commit_all(worktree_path, f"colleague: WIP committed on {reason}")


def list_iso_worktrees(repo_path: str) -> list[str]:
    """Absolute paths of git-registered isolation worktrees (``.colleague/worktrees/iso-*``).

    Scoped STRICTLY to the ``iso-`` prefix DIRECTLY under this repo's worktrees root,
    so a parallel-subagent ``<child_id>`` worktree (no ``iso-`` prefix) or any
    unrelated worktree (a different parent directory) is never listed (#222 h3).
    Returns an empty list if ``git worktree list`` fails (tolerated, like every
    other git call here).
    """
    repo = Path(repo_path).resolve()
    wt_root_str = str(repo / _WORKTREES_SUBDIR)
    proc = _git(repo, "worktree", "list", "--porcelain", check=False)
    if proc.returncode != 0:
        return []
    found: list[str] = []
    for line in proc.stdout.splitlines():
        if not line.startswith(_WORKTREE_LIST_PREFIX):
            continue
        wt = Path(line[len(_WORKTREE_LIST_PREFIX) :].strip())
        if str(wt.parent) == wt_root_str and wt.name.startswith("iso-"):
            found.append(str(wt))
    return found


def reap_orphaned_iso_worktrees(
    repo_path: str,
    *,
    active_task_ids: "frozenset[str] | set[str] | tuple[str, ...]" = (),
    dry_run: bool = False,
) -> list[str]:
    """Remove orphaned isolation worktrees (``.colleague/worktrees/iso-*``); return their paths.

    Recovers the residue a SIGKILL/OOM/power-loss leaves behind when
    :func:`isolation_worktree_remove` could not run (#222): the ``iso-<id>`` worktree
    keeps its ``colleague/<id>`` branch checked out, which blocks ``git branch -D``
    until the worktree is removed — so ``colleague clean`` reaps these BEFORE the
    ``colleague/*`` branch reap, making the branch deletable in the same run. Each is
    removed via ``git worktree remove --force`` followed by a single ``prune`` (the
    :func:`isolation_worktree_remove` mechanism). Scoped STRICTLY to ``iso-*`` under
    this repo's worktrees root via :func:`list_iso_worktrees`; a ``sub/*`` child or an
    unrelated worktree is never touched (#222 h3).

    ``active_task_ids`` SPARES a still-running work item: any ``iso-<task_id>`` whose
    ``<task_id>`` is in the set is left untouched (the caller passes the currently
    recent/active flight ids, mirroring how the flight reap spares active flights),
    so ``colleague clean`` cannot delete an in-flight isolated worktree out from
    under a concurrent piloted run (review of #228, Qodo). A genuinely orphaned
    (non-active) ``iso-*`` worktree is still reaped, so the recovery contract holds.

    A worktree with a LIVE liveness marker (#239 h1, :func:`iso_worktree_is_live`)
    is ALSO spared, independent of ``active_task_ids`` — the flight allow-list only
    covers a ``--watch`` run, so a bare ``colleague work`` in flight (no flight
    tracking) used to be indistinguishable from orphaned residue and got flagged
    "would reap" by ``colleague clean --dry-run`` even while it was still running.
    A worktree with no marker (pre-#239 residue, or the marker write failed) falls
    back to the ``active_task_ids`` signal alone — unchanged behavior.

    ``dry_run=True`` reports the paths it would reap without changing anything.
    """
    active = set(active_task_ids)
    repo = Path(repo_path).resolve()
    paths = []
    for p in list_iso_worktrees(repo_path):
        task_id = Path(p).name[len("iso-") :]
        if task_id in active or iso_worktree_is_live(str(repo), task_id):
            continue
        paths.append(p)
    if paths and not dry_run:
        with _admin_lock(repo):
            for wt in paths:
                _git(repo, "worktree", "remove", "--force", wt, check=False)
            _git(repo, "worktree", "prune", check=False)
    return paths


def merge_branch(repo_path: str, child_id: str) -> MergeOutcome:
    """Merge a child's ``sub/<child_id>`` branch into the working branch of *repo_path*.

    This is the SEQUENTIAL post-join integration step — it runs in the main
    thread, never concurrently, so the merge phase is race-free.  A
    ``--no-ff`` merge is attempted so the child's commit is always recorded as a
    merge into history.

    Outcomes:
    - **merged** — git completed the merge cleanly (a merge commit was created).
    - **noop** — there was nothing to bring in (the branch is already an ancestor,
      e.g. the child produced no commit); reported as a clean no-op.
    - **conflict** — git reported a merge conflict.  The merge is immediately
      ABORTED (``git merge --abort``) so the working tree is restored to a clean
      state, and the conflicting paths are returned in the outcome.  The conflict
      is SURFACED, never force-merged and never silently dropped.

    Args:
        repo_path: Path to the git repository root (the main working tree).
        child_id: The child whose ``sub/<child_id>`` branch should be merged.

    Returns:
        A :class:`MergeOutcome` describing what happened.
    """
    repo = Path(repo_path).resolve()
    branch = _branch_name(child_id)

    # If the branch does not exist (e.g. the child never committed and its branch
    # was already cleaned), treat the merge as a harmless no-op.
    exists = _git(repo, "rev-parse", "--verify", "--quiet", branch, check=False)
    if exists.returncode != 0:
        return MergeOutcome(child_id, MergeOutcome.NOOP, [], "branch absent")

    proc = _git(
        repo,
        "-c",
        "user.name=colleague-merge",
        "-c",
        "user.email=merge@colleague.local",
        "merge",
        "--no-ff",
        "--no-edit",
        branch,
        check=False,
    )
    combined = (proc.stdout or "") + (proc.stderr or "")

    if proc.returncode == 0:
        if "Already up to date" in combined or "Already up-to-date" in combined:
            return MergeOutcome(child_id, MergeOutcome.NOOP, [], combined.strip())
        return MergeOutcome(child_id, MergeOutcome.MERGED, [], combined.strip())

    # Non-zero: a conflict (or another merge failure).  Collect the conflicted
    # paths, then ABORT so the working tree is left clean and uncorrupted.
    conflicts: list[str] = []
    diff = _git(repo, "diff", "--name-only", "--diff-filter=U", check=False)
    if diff.returncode == 0:
        conflicts = [ln.strip() for ln in diff.stdout.splitlines() if ln.strip()]

    # Abort the in-progress merge; tolerate "no merge to abort" (a non-conflict
    # failure such as a dirty tree leaves nothing to abort).
    _git(repo, "merge", "--abort", check=False)

    return MergeOutcome(child_id, MergeOutcome.CONFLICT, conflicts, combined.strip())


def worktree_remove(repo_path: str, child_id: str, *, delete_branch: bool = True) -> None:
    """Remove the worktree (and optionally the branch) for *child_id*. IDEMPOTENT.

    Steps (each tolerating "not found"):
    1. ``git worktree remove --force <path>``
    2. ``git worktree prune``
    3. ``git branch -D sub/<child_id>`` — ONLY when ``delete_branch`` is True.

    If the worktree directory or the branch do not exist, the step is skipped
    silently — this function never raises on a "not found" condition.

    ``delete_branch=False`` removes the worktree directory but PRESERVES the
    ``sub/<child_id>`` branch. The batch teardown uses this to retain a child
    whose merge CONFLICTED, so its committed work is not dropped and can be
    integrated manually (the merge child's summary points the operator at it).
    The commits live on the branch, not in the worktree dir, so removing the dir
    never loses them.

    Args:
        repo_path: Absolute (or relative) path to the git repository root.
        child_id: The child identifier whose worktree (and maybe branch) to remove.
        delete_branch: When False, keep the ``sub/<child_id>`` branch.

    Admin-lock-guarded (#239, see :func:`_admin_lock`) — steps 1-3 run as one
    serialized sequence against a repo shared with other concurrent colleague
    processes.
    """
    repo = Path(repo_path).resolve()
    wt_path = _worktree_path(repo, child_id)
    branch = _branch_name(child_id)

    with _admin_lock(repo):
        # Step 1: remove the worktree.  git returns non-zero when the path is not
        # a registered worktree (or the directory is missing); we tolerate that.
        _git(repo, "worktree", "remove", "--force", str(wt_path), check=False)

        # Step 2: prune stale worktree bookkeeping (handles the case where the
        # directory was deleted externally but the worktree record still exists).
        _git(repo, "worktree", "prune", check=False)

        # Step 3: delete the per-child branch.  ``-D`` (force delete) is required
        # because the branch has not been merged to HEAD.  "not found" is non-zero
        # and silently tolerated. Skipped entirely when delete_branch is False so a
        # conflicted child's work survives.
        if delete_branch:
            _git(repo, "branch", "-D", branch, check=False)


def teardown_all(repo_path: str) -> None:
    """Idempotently remove the worktrees colleague created under ``.colleague/worktrees/``.

    Scope is DELIBERATELY limited to worktrees registered under this repo's
    ``.colleague/worktrees/`` root — both the on-disk directories and git's own
    worktree list. It does NOT enumerate ``git branch --list sub/*``: a blanket
    ``sub/*`` sweep would force-delete unrelated user branches that happen to use
    the ``sub/`` prefix, and would also clobber a conflicted child's branch that
    the batch intentionally retained. A ``sub/<id>`` branch with NO worktree under
    our root is therefore left untouched.

    Safe to call when no child worktrees exist (the function becomes a no-op in
    that case).  Ends with ``git worktree prune`` to flush any stale metadata.

    Args:
        repo_path: Absolute (or relative) path to the git repository root.
    """
    repo = Path(repo_path).resolve()
    wt_root = repo / _WORKTREES_SUBDIR

    # Collect child IDs ONLY from worktrees we own: the directory names under the
    # worktrees root, plus git-registered worktrees whose path is under that root
    # (catches entries whose directories were already removed externally).
    child_ids: set[str] = set()
    if wt_root.is_dir():
        for entry in wt_root.iterdir():
            if entry.is_dir():
                child_ids.add(entry.name)
    child_ids |= _registered_child_ids(repo, wt_root)

    # Remove each child worktree + its branch idempotently. These are children WE
    # created (a worktree exists/existed under our root), so deleting their
    # ``sub/<id>`` branch is safe — unlike a blanket ``sub/*`` sweep.
    # worktree_remove is itself admin-lock-guarded (#239); called sequentially
    # here (never while THIS function holds the lock), so no nested acquisition.
    for child_id in child_ids:
        worktree_remove(repo_path, child_id)

    # Final prune to flush any remaining stale metadata — its own lock scope.
    with _admin_lock(repo):
        _git(repo, "worktree", "prune", check=False)


def _registered_child_ids(repo: Path, wt_root: Path) -> set[str]:
    """Child IDs of git-registered worktrees whose path is under *wt_root*.

    Extracted from :func:`teardown_all` so each function stays within the
    cognitive-complexity budget. Returns an empty set if ``git worktree list``
    fails (tolerated, like every other git call here).
    """
    proc = _git(repo, "worktree", "list", "--porcelain", check=False)
    if proc.returncode != 0:
        return set()
    wt_root_str = str(wt_root)
    found: set[str] = set()
    for line in proc.stdout.splitlines():
        if not line.startswith(_WORKTREE_LIST_PREFIX):
            continue
        wt = line[len(_WORKTREE_LIST_PREFIX) :].strip()
        if wt.startswith(wt_root_str):
            found.add(Path(wt).name)
    return found
