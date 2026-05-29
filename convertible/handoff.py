"""Git/PR handoff (R7): branch -> commit -> push -> ``gh pr create``, gated.

After a drive edits the working tree, the handoff captures the change as a
branch and commit, and — when a remote and the ``gh`` CLI are available and PR
creation is requested — pushes and opens a pull request.

Gating (honesty condition h7): with ``open_pr=False`` (the CLI's ``--no-pr``) or
no configured remote, the handoff commits locally and returns ``pr_url=None``
without ever pushing — so offline and CI runs never reach the network. Push/PR
failures degrade to the same local-commit outcome rather than raising.
"""

from __future__ import annotations

import shutil
import subprocess  # nosec B404 - driving git/gh is the handoff's job
from dataclasses import dataclass, field
from pathlib import Path


class HandoffError(Exception):
    """A git operation that must succeed (e.g. commit) failed."""


@dataclass
class HandoffResult:
    """Outcome of the handoff: the branch made, the PR opened (if any)."""

    branch: str | None = None
    committed: bool = False
    pushed: bool = False
    pr_url: str | None = None
    changed_files: list[str] = field(default_factory=list)
    note: str = ""


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(  # nosec B603 B607 - fixed 'git' argv, no shell
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
    )
    if check and proc.returncode != 0:
        raise HandoffError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc


def has_remote(repo: Path) -> bool:
    """True when the repo has at least one git remote configured."""
    proc = _git(repo, "remote", check=False)
    return proc.returncode == 0 and bool(proc.stdout.strip())


def gh_available() -> bool:
    """True when the ``gh`` CLI is on PATH."""
    return shutil.which("gh") is not None


def should_open_pr(repo: Path, open_pr: bool) -> bool:
    """Decide whether to push + open a PR, the core gating predicate (h7)."""
    return open_pr and has_remote(repo) and gh_available()


def _branch_name(task_id: str) -> str:
    return f"convertible/{task_id}"


def handoff(
    repo_path: str | Path,
    task_id: str,
    *,
    instruction: str = "",
    changed_files: list[str] | None = None,
    open_pr: bool = True,
    base_branch: str = "main",
) -> HandoffResult:
    """Branch + commit the working-tree changes; push + open a PR when gated on.

    Returns a :class:`HandoffResult`; ``pr_url`` is ``None`` whenever the run
    stays local (gating off, no remote, no gh, or a push/PR failure).

    Staging excludes convertible's own ``.convertible/`` bookkeeping dir so a
    handoff never sweeps prior runs' result artifacts / traces into the commit
    (#39).  ``changed_files`` is the loop-tracked set; any of those paths that
    are gitignored (so they can't land in the commit) are surfaced in
    :attr:`HandoffResult.note` rather than dropped silently.
    """
    repo = Path(repo_path).resolve()
    branch = _branch_name(task_id)
    result = HandoffResult(branch=branch)
    ignored = _ignored_paths(repo, changed_files or [])

    # Nothing staged or unstaged -> nothing to hand off. This is the authority on
    # whether work happened — so edits made via run_command (which the loop's
    # change-tracking doesn't see) are still captured here.
    status = _git(repo, "status", "--porcelain")
    if not status.stdout.strip():
        result.branch = None
        result.note = _with_ignored("no changes to hand off", ignored)
        return result

    _git(repo, "checkout", "-B", branch)
    # Stage everything *except* convertible's own bookkeeping dir. The plain
    # ``-A`` this replaced swept in prior runs' untracked ``.convertible/*.json``
    # / ``*.trace.jsonl`` artifacts (#39); the exclude pathspec keeps the
    # run_command-edits-still-captured behaviour while committing only the task's
    # own work.
    _git(repo, "add", "-A", "--", ".", ":(exclude).convertible")
    # The committed set is exactly what is now staged — derive changed_files from
    # it (not from the pre-stage porcelain) so the artifact agrees with the commit.
    staged = _staged_paths(repo)
    if not staged:
        # Everything was excluded (.convertible bookkeeping) or gitignored — no
        # task output of our own to commit.
        result.branch = None
        result.note = _with_ignored("no changes to hand off (only harness/ignored output)", ignored)
        return result
    result.changed_files = staged

    subject = _commit_subject(instruction, task_id)
    body = (instruction or "").strip()
    commit_args = ["commit", "-m", subject]
    # Preserve the full instruction in the commit body when it carries more than
    # the (possibly truncated, single-line) subject already shows (#40).
    if body and f"convertible: {body}" != subject:
        commit_args += ["-m", body]
    _git(repo, *commit_args)
    result.committed = True

    if not should_open_pr(repo, open_pr):
        result.note = _with_ignored(
            "local commit only (--no-pr, no remote, or gh unavailable)", ignored
        )
        return result

    try:
        _git(repo, "push", "-u", "origin", branch)
        result.pushed = True
        result.pr_url = _gh_pr_create(repo, base_branch, subject)
        result.note = _with_ignored("pushed and opened PR", ignored)
    except HandoffError as exc:
        # Distinguish a push that already landed from one that never left: the
        # note must not contradict result.pushed (observability).
        if result.pushed:
            result.note = _with_ignored(f"pushed branch; PR creation failed: {exc}", ignored)
        else:
            result.note = _with_ignored(f"local commit only (push failed: {exc})", ignored)
    return result


def _commit_subject(instruction: str, task_id: str) -> str:
    """A single short commit subject: ``convertible: <first line | task_id>`` (#40).

    The full instruction goes in the commit *body*; the subject takes the first
    line truncated to a git-friendly length so ``git log --oneline`` / PR titles
    stay readable.
    """
    stripped = (instruction or "").strip()
    if not stripped:
        return f"convertible: {task_id}"
    first = stripped.splitlines()[0].strip()
    if len(first) > 64:
        first = first[:61].rstrip() + "..."
    return f"convertible: {first}"


def _staged_paths(repo: Path) -> list[str]:
    """The paths staged for commit (index vs HEAD) — the committed set (#39)."""
    proc = _git(repo, "diff", "--cached", "--name-only")
    return sorted({line.strip() for line in proc.stdout.splitlines() if line.strip()})


def _ignored_paths(repo: Path, paths: list[str]) -> list[str]:
    """Subset of ``paths`` that git ignores (so they cannot land in a commit)."""
    if not paths:
        return []
    proc = _git(repo, "check-ignore", *paths, check=False)
    return sorted({line.strip() for line in proc.stdout.splitlines() if line.strip()})


def _with_ignored(note: str, ignored: list[str]) -> str:
    """Append a gitignored-output advisory to ``note`` (surfaced, not dropped — #39)."""
    if not ignored:
        return note
    listed = ", ".join(ignored)
    return f"{note}; {len(ignored)} file(s) produced but not committed (gitignored): {listed}"


def _gh_pr_create(repo: Path, base_branch: str, title: str) -> str | None:
    proc = subprocess.run(  # nosec B603 B607 - fixed 'gh' argv, no shell
        ["gh", "pr", "create", "--fill", "--base", base_branch, "--title", title],
        cwd=str(repo),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise HandoffError(f"gh pr create failed: {proc.stderr.strip()}")
    url = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    return url or None
