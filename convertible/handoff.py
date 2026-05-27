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
from dataclasses import dataclass
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
    open_pr: bool = True,
    base_branch: str = "main",
) -> HandoffResult:
    """Branch + commit the working-tree changes; push + open a PR when gated on.

    Returns a :class:`HandoffResult`; ``pr_url`` is ``None`` whenever the run
    stays local (gating off, no remote, no gh, or a push/PR failure).
    """
    repo = Path(repo_path).resolve()
    branch = _branch_name(task_id)
    result = HandoffResult(branch=branch)

    # Nothing staged or unstaged -> nothing to hand off.
    status = _git(repo, "status", "--porcelain")
    if not status.stdout.strip():
        result.branch = None
        result.note = "no changes to hand off"
        return result

    _git(repo, "checkout", "-B", branch)
    _git(repo, "add", "-A")
    message = f"convertible: {instruction or task_id}".strip()
    _git(repo, "commit", "-m", message)
    result.committed = True

    if not should_open_pr(repo, open_pr):
        result.note = "local commit only (--no-pr, no remote, or gh unavailable)"
        return result

    try:
        _git(repo, "push", "-u", "origin", branch)
        result.pushed = True
        result.pr_url = _gh_pr_create(repo, base_branch, message)
        result.note = "pushed and opened PR"
    except HandoffError as exc:
        result.note = f"local commit only (push/PR failed: {exc})"
    return result


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
