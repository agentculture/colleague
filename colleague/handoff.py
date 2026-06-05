"""Git/PR handoff (R7): branch -> commit -> push -> ``gh pr create``, gated.

After a work item edits the working tree, the handoff captures the change as a
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

from colleague.slug import slugify


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


def _branch_name(task_id: str, instruction: str = "") -> str:
    """The work branch: ``colleague/<task_id>-<slug>`` (bare id when no slug).

    The ``task_id`` keeps the branch unique; the request *slug* (same helper the
    artifact filename uses, so the two agree) makes it recognisable in a ``git
    branch`` listing. The ``colleague/`` prefix is preserved so the ``outsource``
    skill's ``colleague/*`` cleanup match and the PR flow are unaffected.
    """
    slug = slugify(instruction)
    return f"colleague/{task_id}-{slug}" if slug else f"colleague/{task_id}"


def _current_ref(repo: Path) -> str | None:
    """The operator's current branch name, or the commit SHA if detached.

    Captured before the handoff switches branches so we can return the operator
    there afterwards. A detached HEAD (e.g. the throwaway worktree the
    ``outsource`` skill drives in) has no branch name, so we fall back to the
    commit SHA. Returns ``None`` when git can't answer (treated as "don't
    restore").
    """
    proc = _git(repo, "symbolic-ref", "--short", "-q", "HEAD", check=False)
    name = proc.stdout.strip()
    if name:
        return name
    sha = _git(repo, "rev-parse", "-q", "HEAD", check=False)
    return sha.stdout.strip() or None


def _restore_ref(repo: Path, ref: str | None) -> None:
    """Return the operator to their pre-handoff branch/commit (best-effort).

    The ``colleague/<id>`` branch keeps its commit; this only stops the work item
    from stranding the operator on it. The worktree is clean immediately after
    the commit, so the checkout is safe — and a failure is swallowed (the commit
    already succeeded, so restoration must never raise).
    """
    if ref:
        _git(repo, "checkout", ref, check=False)


def handoff(
    repo_path: str | Path,
    task_id: str,
    *,
    instruction: str = "",
    changed_files: list[str] | None = None,
    baseline_untracked: list[str] | None = None,
    open_pr: bool = True,
    base_branch: str = "main",
) -> HandoffResult:
    """Branch + commit the working-tree changes; push + open a PR when gated on.

    Returns a :class:`HandoffResult`; ``pr_url`` is ``None`` whenever the run
    stays local (gating off, no remote, no gh, or a push/PR failure).

    After committing, the operator is returned to the branch (or detached commit)
    they were on before the work item — the ``colleague/<id>`` branch keeps the
    commit, but a work item never strands the operator on a freshly-made task branch
    (the no-op paths below never switch branches at all).

    Staging commits **only the task's own work** (#39): all tracked
    modifications (so ``run_command`` edits to tracked files are captured) plus
    the new untracked files the *drive itself* produced — i.e. untracked files
    that were **not** present before the work item (``baseline_untracked``) and are
    not under colleague's own ``.colleague/`` bookkeeping dir. Pre-existing
    untracked files (operator work-in-progress) and prior runs' artifacts are
    never swept in. ``changed_files`` is the loop-tracked set; any of those paths
    that are gitignored (so they can't land in the commit) are surfaced in
    :attr:`HandoffResult.note` rather than dropped silently.

    ``baseline_untracked`` is the set of untracked paths captured *before* the
    drive (see :func:`untracked_snapshot`); when ``None`` no baseline filtering
    is applied (every work item-produced untracked file is a candidate).
    """
    repo = Path(repo_path).resolve()
    branch = _branch_name(task_id, instruction)
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

    # Stage BEFORE switching branches: a no-op must never leave the operator
    # checked out on a freshly-created task branch (the index built here is
    # carried into the `checkout -B` below when we do commit).
    #   1. tracked modifications/deletions (run_command + write_file edits to
    #      already-tracked files), never sweeping untracked files;
    #   2. the new untracked files the work item produced — excluding pre-existing
    #      operator work-in-progress and `.colleague/` bookkeeping (#39).
    _git(repo, "add", "-u", "--", ".", ":(exclude).colleague")
    baseline = set(baseline_untracked or [])
    produced = [
        path
        for path in _untracked_paths(repo)
        if path not in baseline and not path.startswith(".colleague/")
    ]
    if produced:
        _git(repo, "add", "--", *produced)

    # The committed set is exactly what is now staged — derive changed_files from
    # it (not from the pre-stage porcelain) so the artifact agrees with the commit.
    staged = _staged_paths(repo)
    if not staged:
        # Only excluded/ignored/pre-existing output — nothing of the task's own
        # to commit. We have NOT switched branches, so operator state is intact.
        result.branch = None
        result.note = _with_ignored("no task changes to hand off", ignored)
        return result
    result.changed_files = staged

    # Capture where the operator was so we can return them there after committing
    # — the work branch keeps the commit, but a work item must not strand the
    # operator on a freshly-made task branch.
    original_ref = _current_ref(repo)
    _git(repo, "checkout", "-B", branch)
    subject = _commit_subject(instruction, task_id)
    body = (instruction or "").strip()
    commit_args = ["commit", "-m", subject]
    # Preserve the full instruction in the commit body when it carries more than
    # the (possibly truncated, single-line) subject already shows (#40).
    if body and f"colleague: {body}" != subject:
        commit_args += ["-m", body]
    _git(repo, *commit_args)
    result.committed = True

    if not should_open_pr(repo, open_pr):
        result.note = _with_ignored(
            "local commit only (--no-pr, no remote, or gh unavailable)", ignored
        )
        _restore_ref(repo, original_ref)
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
    # Restore only after push + `gh pr create` (which infer the head from the
    # checked-out branch) have run on the work branch.
    _restore_ref(repo, original_ref)
    return result


def _commit_subject(instruction: str, task_id: str) -> str:
    """A single short commit subject: ``colleague: <first line | task_id>`` (#40).

    The full instruction goes in the commit *body*; the subject takes the first
    line truncated to a git-friendly length so ``git log --oneline`` / PR titles
    stay readable.
    """
    stripped = (instruction or "").strip()
    if not stripped:
        return f"colleague: {task_id}"
    first = stripped.splitlines()[0].strip()
    if len(first) > 64:
        first = first[:61].rstrip() + "..."
    return f"colleague: {first}"


def _staged_paths(repo: Path) -> list[str]:
    """The paths staged for commit (index vs HEAD) — the committed set (#39)."""
    proc = _git(repo, "diff", "--cached", "--name-only")
    return sorted({line.strip() for line in proc.stdout.splitlines() if line.strip()})


def _untracked_paths(repo: Path) -> list[str]:
    """Untracked, non-gitignored paths in the work tree (``git status`` ``??``)."""
    proc = _git(repo, "status", "--porcelain", "--untracked-files=all")
    return [line[3:] for line in proc.stdout.splitlines() if line.startswith("?? ")]


def untracked_snapshot(repo_path: str | Path) -> list[str]:
    """Untracked paths *now* — captured before a work item as the handoff baseline.

    Returns ``[]`` outside a git repo (or on any git error) so the caller can
    pass it through unconditionally; a missing baseline just means no filtering.
    """
    try:
        return _untracked_paths(Path(repo_path).resolve())
    except HandoffError:
        return []


def _ignored_paths(repo: Path, paths: list[str]) -> list[str]:
    """Subset of ``paths`` that git ignores (so they cannot land in a commit).

    Uses ``check-ignore --stdin`` so the path list never becomes argv (no
    ``ARG_MAX`` blow-up for a large changed_files set) and leading-dash paths are
    never mistaken for flags.
    """
    if not paths:
        return []
    proc = subprocess.run(  # nosec B603 B607 - fixed 'git' argv, no shell
        ["git", "check-ignore", "--stdin"],
        cwd=str(repo),
        input="\n".join(paths),
        capture_output=True,
        text=True,
    )
    # 0 = some ignored, 1 = none ignored; anything else (128 = not a git repo) ->
    # surface nothing rather than raising.
    if proc.returncode not in (0, 1):
        return []
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
