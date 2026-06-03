"""Per-child git worktree + branch lifecycle for parallel subagent isolation.

Each parallel subagent child runs inside its OWN throwaway git worktree so that
concurrent writes never interfere.  This module owns the create/remove cycle:

- ``worktree_add(repo_path, child_id)`` — create an isolated worktree on a fresh
  ``sub/<child_id>`` branch under ``.colleague/worktrees/<child_id>/``.
- ``worktree_remove(repo_path, child_id)`` — idempotently remove the worktree and
  delete its branch; safe to call after a partial or errored child run.
- ``teardown_all(repo_path)`` — idempotently remove EVERY ``.colleague/worktrees/*``
  worktree and every ``sub/*`` branch, then run ``git worktree prune``; safe to call
  when none exist.

Design constraints (matching the rest of the colleague chassis):
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

import subprocess  # nosec B404 - driving git for worktree lifecycle is this module's job
from pathlib import Path

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_WORKTREES_SUBDIR = ".colleague/worktrees"
_GITIGNORE_ENTRY = ".colleague/worktrees/"


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


def _ensure_gitignore(repo: Path) -> None:
    """Append ``.colleague/worktrees/`` to the repo's ``.gitignore`` if not already there.

    Creates the file if it does not exist.  Never writes a duplicate entry.
    """
    gitignore = repo / ".gitignore"
    if gitignore.exists():
        existing = gitignore.read_text(encoding="utf-8")
        # Check line-by-line to avoid a false positive from a partial substring match.
        if any(line.strip() == _GITIGNORE_ENTRY for line in existing.splitlines()):
            return
        # Append, ensuring there is a trailing newline before our entry.
        sep = "" if existing.endswith("\n") else "\n"
        gitignore.write_text(existing + sep + _GITIGNORE_ENTRY + "\n", encoding="utf-8")
    else:
        gitignore.write_text(_GITIGNORE_ENTRY + "\n", encoding="utf-8")


def _worktree_path(repo: Path, child_id: str) -> Path:
    """Return the expected worktree directory for *child_id* (not yet created)."""
    return repo / _WORKTREES_SUBDIR / child_id


def _branch_name(child_id: str) -> str:
    return f"sub/{child_id}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def worktree_add(repo_path: str, child_id: str) -> str:
    """Create an isolated git worktree for *child_id* on branch ``sub/<child_id>``.

    The worktree is placed at ``<repo_path>/.colleague/worktrees/<child_id>/``.
    The parent ``.colleague/worktrees/`` directory is ensured before the git call.
    The entry is appended to ``.gitignore`` (idempotent — no duplicate writes).

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

    # Register .colleague/worktrees/ in .gitignore before creating the worktree
    # so the new directory is excluded from the very first status/add scan.
    _ensure_gitignore(repo)

    _git(repo, "worktree", "add", str(wt_path), "-b", branch)

    return str(wt_path)


def worktree_remove(repo_path: str, child_id: str) -> None:
    """Remove the worktree and branch for *child_id*. IDEMPOTENT.

    Steps (each tolerating "not found"):
    1. ``git worktree remove --force <path>``
    2. ``git branch -D sub/<child_id>``

    If the worktree directory or the branch do not exist, the step is skipped
    silently — this function never raises on a "not found" condition.

    Args:
        repo_path: Absolute (or relative) path to the git repository root.
        child_id: The child identifier whose worktree and branch should be removed.
    """
    repo = Path(repo_path).resolve()
    wt_path = _worktree_path(repo, child_id)
    branch = _branch_name(child_id)

    # Step 1: remove the worktree.  git returns non-zero when the path is not
    # a registered worktree (or the directory is missing); we tolerate that.
    _git(repo, "worktree", "remove", "--force", str(wt_path), check=False)

    # Step 2: prune stale worktree bookkeeping (handles the case where the
    # directory was deleted externally but the worktree record still exists).
    _git(repo, "worktree", "prune", check=False)

    # Step 3: delete the per-child branch.  ``-D`` (force delete) is required
    # because the branch has not been merged to HEAD.  "not found" is non-zero
    # and silently tolerated.
    _git(repo, "branch", "-D", branch, check=False)


def teardown_all(repo_path: str) -> None:
    """Idempotently remove ALL ``.colleague/worktrees/*`` worktrees and ``sub/*`` branches.

    Safe to call when no child worktrees exist (the function becomes a no-op in
    that case).  Ends with ``git worktree prune`` to flush any stale metadata.

    Args:
        repo_path: Absolute (or relative) path to the git repository root.
    """
    repo = Path(repo_path).resolve()
    wt_root = repo / _WORKTREES_SUBDIR

    # Collect child IDs from the filesystem (the directory names under the
    # worktrees root) and from registered worktrees that might not have a dir
    # anymore (e.g. after an external crash).
    child_ids: set[str] = set()

    if wt_root.is_dir():
        for entry in wt_root.iterdir():
            if entry.is_dir():
                child_ids.add(entry.name)

    # Also scan git's own worktree list for sub/<id> branches pointing under
    # our worktrees root — catches entries whose directories were already removed.
    proc = _git(repo, "worktree", "list", "--porcelain", check=False)
    if proc.returncode == 0:
        lines = proc.stdout.splitlines()
        wt_root_str = str(wt_root)
        current_path: str | None = None
        for line in lines:
            if line.startswith("worktree "):
                current_path = line[len("worktree ") :].strip()
            elif line.startswith("branch ") and current_path is not None:
                if current_path.startswith(wt_root_str):
                    # Derive child_id from the last path component.
                    child_ids.add(Path(current_path).name)
                current_path = None
            elif not line.strip():
                current_path = None

    # Also pick up any sub/* branches that don't have a worktree dir.
    br_proc = _git(repo, "branch", "--list", "sub/*", check=False)
    if br_proc.returncode == 0:
        for branch_line in br_proc.stdout.splitlines():
            branch = branch_line.strip().lstrip("* ").strip()
            if branch.startswith("sub/"):
                child_ids.add(branch[len("sub/") :])

    # Remove each child worktree + branch idempotently.
    for child_id in child_ids:
        worktree_remove(repo_path, child_id)

    # Final prune to flush any remaining stale metadata.
    _git(repo, "worktree", "prune", check=False)
