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

import json
import shutil
import subprocess  # nosec B404 - driving git/gh is the handoff's job
import time
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
    tip_sha: str | None = None
    """The work branch's tip commit SHA once ``committed`` is True (plan task
    t5, covers c5), or ``None`` when no commit landed. Read straight off the
    branch ref (:func:`_branch_tip_sha`) — valid before or after
    :func:`_restore_ref` switches the operator's checkout away from it."""


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


def diff_range(repo_path: str | Path, base: str) -> str:
    """Return ``git diff <base>...HEAD`` for *repo_path* (read-only).

    Used by the session's read-only ``review`` mode to source the committed diff
    operator-side and inject it into the reviewer's task — the read-only reviewer
    role withholds ``run_command``, so it cannot run git itself. Returns an empty
    string when the range can't be computed (e.g. an invalid base), never raising,
    so a review on a fresh repo degrades to "no committed changes" rather than a
    crash."""
    proc = _git(Path(repo_path), "diff", f"{base}...HEAD", check=False)
    return proc.stdout if proc.returncode == 0 else ""


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


#: Public alias — the work-branch name an isolated run pre-creates its worktree on
#: must match the name the handoff would mint, so they agree (#196).
branch_name = _branch_name


def head_sha(repo_path: str | Path) -> str | None:
    """The current HEAD commit SHA, or ``None`` when git can't answer (no commits).

    Captured *before* an isolated run so the handoff can tell a model self-commit
    (HEAD advanced past this base) from a genuinely empty run (#196). Public so the
    work path reads it without importing ``subprocess`` itself (boundary rule).
    """
    repo = Path(repo_path).resolve()
    proc = _git(repo, "rev-parse", "-q", "HEAD", check=False)
    return proc.stdout.strip() or None


def current_ref(repo: Path) -> str | None:
    """The operator's current branch name, or the commit SHA if detached.

    Captured before the handoff switches branches so we can return the operator
    there afterwards. A detached HEAD (e.g. the throwaway worktree the
    ``outsource`` skill drives in) has no branch name, so we fall back to the
    commit SHA. Returns ``None`` when git can't answer (treated as "don't
    restore").

    Public read-only accessor — also surfaced in the session cockpit's Context
    panel so an operator can see which branch a work item would build from.
    """
    proc = _git(repo, "symbolic-ref", "--short", "-q", "HEAD", check=False)
    name = proc.stdout.strip()
    if name:
        return name
    sha = _git(repo, "rev-parse", "-q", "HEAD", check=False)
    return sha.stdout.strip() or None


#: Back-compat alias for the historical private name (internal callers).
_current_ref = current_ref


def _branch_tip_sha(repo: Path, branch: str) -> str | None:
    """The tip commit SHA of *branch*, or ``None`` when git can't answer.

    Reads the ref directly (``rev-parse <branch>``) rather than ``HEAD``, so it
    is safe to call either while still checked out on ``branch`` (the normal
    handoff path, before :func:`_restore_ref` runs) or after the checkout has
    moved on (the branch ref itself doesn't change either way)."""
    proc = _git(repo, "rev-parse", "-q", branch, check=False)
    return proc.stdout.strip() or None


def _restore_ref(repo: Path, ref: str | None) -> None:
    """Return the operator to their pre-handoff branch/commit (best-effort).

    The ``colleague/<id>`` branch keeps its commit; this only stops the work item
    from stranding the operator on it. The worktree is clean immediately after
    the commit, so the checkout is safe — and a failure is swallowed (the commit
    already succeeded, so restoration must never raise).
    """
    if ref:
        _git(repo, "checkout", ref, check=False)


def _commit_on_branch(
    repo: Path, branch: str, commit_args: list[str], original_ref: str | None
) -> None:
    """Create the work branch and commit on it; self-clean on a catchable crash (#162).

    A catchable interruption between creating the branch and landing the commit (a
    ``HandoffError`` from git, or a Ctrl-C / ``KeyboardInterrupt``) must not strand
    the operator on — or leave behind — a half-made ``colleague/<id>`` branch.
    Restore the operator's ref, then reap the orphan branch (it points at the old
    HEAD; no commit landed), then re-raise. A SIGKILL/OOM *inside* the commit is
    uncatchable here — ``colleague clean`` recovers that.
    """
    try:
        _git(repo, "checkout", "-B", branch)
        _git(repo, *commit_args)
    except (HandoffError, KeyboardInterrupt):
        _restore_ref(repo, original_ref)
        if _current_ref(repo) != branch:
            _delete_colleague_ref(repo, branch, dry_run=False)
        raise


def handoff(
    repo_path: str | Path,
    task_id: str,
    *,
    instruction: str = "",
    changed_files: list[str] | None = None,
    baseline_untracked: list[str] | None = None,
    open_pr: bool = True,
    base_branch: str = "main",
    base_sha: str | None = None,
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

    # A clean working tree is terminal: either the model self-committed during an
    # isolated run (#196 reap) or there is genuinely nothing to hand off. The
    # decision lives in a helper so ``handoff`` stays under the S3776 threshold.
    early = _handoff_clean_tree(
        repo, branch, instruction, task_id, open_pr, base_branch, ignored, base_sha
    )
    if early is not None:
        return early

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
    # #275: an entry whose first segment is exactly ``~`` is shell-expansion
    # pollution (a run_command test wrote a "~/…" path relative to the repo
    # instead of $HOME), never a deliverable — skip it and surface it in the
    # note instead of committing a fake home directory onto the work branch.
    # Only the literal ``~`` dir qualifies: a tilde-PREFIXED root file like
    # ``~notes.md`` is a legitimate deliverable and is committed as usual.
    pollution = [p for p in produced if p.split("/", 1)[0] == "~"]
    if pollution:
        produced = [p for p in produced if p not in pollution]
    if produced:
        _git(repo, "add", "--", *produced)

    # The committed set is exactly what is now staged — derive changed_files from
    # it (not from the pre-stage porcelain) so the artifact agrees with the commit.
    staged = _staged_paths(repo)
    if not staged:
        # Only excluded/ignored/pre-existing output — nothing of the task's own
        # to commit. We have NOT switched branches, so operator state is intact.
        result.branch = None
        result.note = _with_ignored("no task changes to hand off", ignored, pollution)
        return result
    result.changed_files = staged

    # Capture where the operator was so we can return them there after committing
    # — the work branch keeps the commit, but a work item must not strand the
    # operator on a freshly-made task branch.
    original_ref = _current_ref(repo)
    subject = _commit_subject(instruction, task_id)
    body = (instruction or "").strip()
    commit_args = ["commit", "-m", subject]
    # Preserve the full instruction in the commit body when it carries more than
    # the (possibly truncated, single-line) subject already shows (#40).
    if body and f"colleague: {body}" != subject:
        commit_args += ["-m", body]
    _commit_on_branch(repo, branch, commit_args, original_ref)
    result.committed = True
    result.tip_sha = _branch_tip_sha(repo, branch)

    if not should_open_pr(repo, open_pr):
        result.note = _with_ignored(
            "local commit only (--no-pr, no remote, or gh unavailable)", ignored, pollution
        )
        _restore_ref(repo, original_ref)
        return result

    try:
        _git(repo, "push", "-u", "origin", branch)
        result.pushed = True
        result.pr_url = _gh_pr_create(repo, base_branch, subject)
        result.note = _with_ignored("pushed and opened PR", ignored, pollution)
    except HandoffError as exc:
        # Distinguish a push that already landed from one that never left: the
        # note must not contradict result.pushed (observability).
        if result.pushed:
            result.note = _with_ignored(
                f"pushed branch; PR creation failed: {exc}", ignored, pollution
            )
        else:
            result.note = _with_ignored(
                f"local commit only (push failed: {exc})", ignored, pollution
            )
    # Restore only after push + `gh pr create` (which infer the head from the
    # checked-out branch) have run on the work branch.
    _restore_ref(repo, original_ref)
    return result


def _finish_self_committed(
    repo: Path,
    branch: str,
    instruction: str,
    task_id: str,
    open_pr: bool,
    base_branch: str,
    ignored: list[str],
    base_sha: str,
) -> HandoffResult:
    """Report an isolated run whose model committed its own work during the loop (#196).

    The work is already committed in the isolation worktree (created on the
    ``colleague/<id>`` branch), so there is nothing to stage — only to optionally
    push + open a PR. No operator ref is restored: the isolation worktree is
    disposable and was never on the operator's branch, which is the whole point —
    a self-commit can no longer advance the operator's HEAD.

    Two robustness guards (PR #207 review):
    - **Force the branch to HEAD** (``checkout -B``) before reporting, so the work
      is captured on ``colleague/<id>`` even if the model committed on a *different*
      ref (it ran ``git checkout -b X`` / ``--detach`` via ``run_command``). A no-op
      in the normal case (already on the branch); without it that commit would be
      lost on worktree teardown.
    - **Populate ``changed_files``** from ``base_sha..HEAD`` (symmetric with the
      normal path's staged set), so a self-commit whose edits came via ``run_command``
      isn't reported as ``changed files: (none)`` despite a real commit.
    """
    _git(repo, "checkout", "-B", branch)
    result = HandoffResult(branch=branch)
    result.committed = True
    result.tip_sha = _branch_tip_sha(repo, branch)
    result.changed_files = _committed_paths(repo, base_sha)
    subject = _commit_subject(instruction, task_id)
    if not should_open_pr(repo, open_pr):
        result.note = _with_ignored(
            "local commit only (model self-committed in isolation)", ignored
        )
        return result
    try:
        _git(repo, "push", "-u", "origin", branch)
        result.pushed = True
        result.pr_url = _gh_pr_create(repo, base_branch, subject)
        result.note = _with_ignored("pushed and opened PR", ignored)
    except HandoffError as exc:
        if result.pushed:
            result.note = _with_ignored(f"pushed branch; PR creation failed: {exc}", ignored)
        else:
            result.note = _with_ignored(f"local commit only (push failed: {exc})", ignored)
    return result


def _handoff_clean_tree(
    repo: Path,
    branch: str,
    instruction: str,
    task_id: str,
    open_pr: bool,
    base_branch: str,
    ignored: list[str],
    base_sha: str | None,
) -> HandoffResult | None:
    """Terminal handoff for a CLEAN working tree, or ``None`` to keep staging.

    ``git status`` is the authority on whether work happened — so ``run_command``
    edits the loop's change-tracking never saw are still captured. A clean tree is
    terminal in two ways: the model self-committed during an isolated run
    (``base_sha`` given and HEAD advanced past it -> #196 reap via
    :func:`_finish_self_committed`), or there is genuinely nothing to hand off.
    Returns ``None`` when the tree is dirty so :func:`handoff` proceeds to stage +
    commit. Extracted from ``handoff`` to keep its cognitive complexity under the
    S3776 threshold (PR #207 review)."""
    status = _git(repo, "status", "--porcelain")
    if status.stdout.strip():
        return None
    head_sha_now = _git(repo, "rev-parse", "-q", "HEAD", check=False).stdout.strip()
    if base_sha and head_sha_now and head_sha_now != base_sha:
        return _finish_self_committed(
            repo, branch, instruction, task_id, open_pr, base_branch, ignored, base_sha
        )
    result = HandoffResult(branch=None)
    result.note = _with_ignored("no changes to hand off", ignored)
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


def _committed_paths(repo: Path, base_sha: str | None) -> list[str]:
    """Files a model self-commit changed — ``base_sha..HEAD`` (PR #207 review).

    Symmetric with :func:`_staged_paths` but for the self-commit path, where the
    work is already committed (no index to read). Returns ``[]`` when ``base_sha``
    is unknown or git can't answer (never raises)."""
    if not base_sha:
        return []
    proc = _git(repo, "diff", "--name-only", f"{base_sha}..HEAD", check=False)
    if proc.returncode != 0:
        return []
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


def working_tree_dirty(repo_path: str | Path) -> bool:
    """True when the work tree has uncommitted changes to *tracked* files.

    Targets exactly the handoff hazard (#149): the handoff's ``git add -u``
    would sweep tracked modifications/deletions onto the work branch (and
    restore HEAD over them), silently swallowing the operator's in-progress
    work. Untracked files are deliberately excluded — they are already protected
    by the handoff's ``baseline_untracked`` snapshot (#39), so flagging them
    would over-refuse. This is intentionally narrower than the ask-colleague
    skill's coarser full-porcelain bash guard; keep it that way.

    Returns ``False`` outside a git repo (or on any git error) so the caller can
    consult it unconditionally — a non-git target has no handoff hazard to guard.
    """
    try:
        proc = _git(
            Path(repo_path).resolve(),
            "status",
            "--porcelain",
            "--untracked-files=no",
            check=False,
        )
    except (HandoffError, OSError):
        return False
    if proc.returncode != 0:
        return False
    # Changes confined to the committed eidetic memory store are colleague's own
    # state, not operator work-in-progress: a memory-armed run (spec R1 / plan t2)
    # reinforces recalled records and upserts a lesson into ``.eidetic/`` on every
    # run, so counting those as "dirty" would make each memory-armed run block the
    # next one. They are still swept onto the work branch by the handoff — lessons
    # travel with the work — which is desirable, not a hazard.
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    non_memory = [ln for ln in lines if not ln[3:].lstrip().startswith(".eidetic/")]
    return bool(non_memory)


def heal_stash(repo_path: str | Path) -> str | None:
    """Stash the operator's uncommitted tracked edits for the session heal (#168).

    Runs ``git stash push`` (tracked changes only — untracked files stay put,
    matching :func:`working_tree_dirty`'s hazard scope) with a recognizable
    message and returns the stash ref (``stash@{0}``) on success, ``None`` when
    there was nothing to stash or git failed. The caller owns telling the
    operator the recovery line (``git stash pop``).
    """
    repo = Path(repo_path).resolve()
    try:
        proc = _git(repo, "stash", "push", "-m", "colleague session heal (#168)", check=False)
    except (HandoffError, OSError):
        return None
    if proc.returncode != 0 or "No local changes" in (proc.stdout or ""):
        return None
    return "stash@{0}"


def commits_ahead(repo_path: str | Path, base_ref: str, tip_ref: str) -> int:
    """Commits reachable from ``tip_ref`` but not ``base_ref`` — read-only.

    The chain loop's no-progress evidence (indefinite-run c22): counts what an
    episode actually landed on its branch past the prior episode's tip (or the
    chain-start HEAD for episode 1). Returns ``0`` on any git error — a count
    the guard treats as "no new commits", so a broken ref degrades toward the
    conservative halt rather than an infinite chain. Lives here because
    ``handoff.py`` is the sanctioned subprocess consumer (``test_boundary.py``).
    """
    try:
        proc = _git(
            Path(repo_path).resolve(),
            "rev-list",
            "--count",
            f"{base_ref}..{tip_ref}",
            check=False,
        )
    except (HandoffError, OSError):
        return 0
    out = proc.stdout.strip()
    return int(out) if proc.returncode == 0 and out.isdigit() else 0


def chain_handoff_finalize(
    repo_path: str | Path,
    task_id: str,
    branch: str,
    *,
    instruction: str = "",
    open_pr: bool = True,
    base_branch: str = "main",
    body: str | None = None,
) -> HandoffResult:
    """The chain's ONE handoff, at chain end (indefinite-run c26).

    Every episode of an armed chain commits locally with push/PR suppressed;
    when the chain COMPLETES, this pushes the final episode's ``branch`` — which
    carries the cumulative diff, because each episode based its worktree on the
    prior tip — and opens the single PR. Gated by the same
    :func:`should_open_pr` predicate as the per-work-item handoff (h7): with
    ``open_pr=False`` (the arming invocation's ``--no-pr``), no remote, or no
    ``gh``, it returns a local-only result without touching the network.

    Unlike :func:`handoff` this never stages or commits (the episodes already
    did) and never switches branches: the push names the branch by refspec and
    ``gh pr create`` gets an explicit ``--head``, so the operator's checkout is
    untouched. Push/PR failures degrade to the local-only outcome, never raise.

    ``body`` (#340 b3): optional explicit PR body — the gate-deferral warning
    the human reviewer at gate 3 must see; ``None`` keeps today's ``--fill``
    body. Threaded verbatim to :func:`_gh_pr_create`; every degrade path
    behaves identically with or without it.
    """
    repo = Path(repo_path).resolve()
    result = HandoffResult(branch=branch, committed=True, tip_sha=_branch_tip_sha(repo, branch))
    if not should_open_pr(repo, open_pr):
        result.note = "chain final: local branches only (--no-pr, no remote, or gh unavailable)"
        return result
    subject = _commit_subject(instruction, task_id)
    try:
        _git(repo, "push", "-u", "origin", branch)
        result.pushed = True
        result.pr_url = _gh_pr_create(repo, base_branch, subject, head=branch, body=body)
        result.note = "chain final: pushed and opened PR"
    except HandoffError as exc:
        if result.pushed:
            result.note = f"chain final: pushed branch; PR creation failed: {exc}"
        else:
            result.note = f"chain final: local branches only (push failed: {exc})"
    return result


def reap_chain_intermediates(
    repo_path: str | Path, branches: list[str], *, keep: str
) -> list[dict]:
    """Reap a COMPLETED chain's intermediate ``colleague/*`` branches (c26).

    ``branches`` is the chain's episode branches in order; ``keep`` is the
    final episode's branch (never deleted — it is the deliverable). Each
    intermediate is deleted only when its tip is an **ancestor** of ``keep``
    (``merge-base --is-ancestor``): because episode N+1 based on episode N's
    tip, a healthy chain's intermediates are all reachable from the final
    branch, so reaping loses nothing (artifacts keep the evidence). A tip that
    is NOT reachable — a mid-chain base-ref degrade rebased that episode onto
    HEAD — is ``kept`` rather than destroyed. Deletion goes through
    :func:`_delete_colleague_ref` (``colleague/*`` only, defense in depth).

    Returns one ``{ref, action}`` dict per input branch, ``action`` in
    ``reaped`` / ``kept`` / ``failed`` / ``refused``.
    """
    repo = Path(repo_path).resolve()
    results: list[dict] = []
    for ref in branches:
        if ref == keep:
            results.append({"ref": ref, "action": "kept"})
            continue
        ancestor = _git(repo, "merge-base", "--is-ancestor", ref, keep, check=False)
        if ancestor.returncode != 0:
            results.append({"ref": ref, "action": "kept"})
            continue
        results.append({"ref": ref, "action": _delete_colleague_ref(repo, ref, dry_run=False)})
    return results


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


def _with_ignored(note: str, ignored: list[str], pollution: list[str] | None = None) -> str:
    """Append the not-committed advisories to ``note`` (surfaced, not dropped — #39/#275)."""
    if ignored:
        listed = ", ".join(ignored)
        note = f"{note}; {len(ignored)} file(s) produced but not committed (gitignored): {listed}"
    if pollution:
        listed = ", ".join(pollution)
        note = (
            f"{note}; {len(pollution)} test-pollution path(s) skipped "
            f"(literal ~ at the repo root): {listed}"
        )
    return note


def _gh_pr_create(
    repo: Path,
    base_branch: str,
    title: str,
    head: str | None = None,
    body: str | None = None,
) -> str | None:
    """Open the PR via ``gh pr create``; ``head`` names the source branch explicitly.

    Without ``head`` the head branch is inferred from the checkout (the
    per-work-item :func:`handoff` path, which runs while checked out on the
    work branch). The chain's final handoff (:func:`chain_handoff_finalize`)
    runs from the operator's own ref, so it must pass ``head`` explicitly.

    ``body`` (#340 b3): an explicit PR body — the chain's gate-deferral
    warning. ``--fill`` and ``--body`` are mutually exclusive, so a body
    REPLACES the commit-derived fill; ``None`` keeps the argv byte-identical
    to today. Deliberately never ``gh pr edit`` (no-ops on Projects-classic
    repos — recorded gotcha).
    """
    argv = ["gh", "pr", "create"]
    if body is None:
        argv.append("--fill")
    argv += ["--base", base_branch, "--title", title]
    if body is not None:
        argv += ["--body", body]
    if head:
        argv += ["--head", head]
    proc = subprocess.run(  # nosec B603 B607 - fixed 'gh' argv, no shell
        argv,
        cwd=str(repo),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise HandoffError(f"gh pr create failed: {proc.stderr.strip()}")
    url = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    return url or None


# ---------------------------------------------------------------------------
# Cleanup / reap (#162) — recover a repo a crashed work item left wedged.
#
# A crashed/SIGKILL'd ``work --apply`` can leave a dangling ``colleague/<id>``
# ref pointing at half-written (0-byte) loose objects, which breaks ``git
# fetch``. These helpers (and the ``colleague clean`` verb that drives them)
# reap such refs + the orphaned ``.colleague/`` artifacts, scoped *strictly* to
# ``colleague/*``. The git work lives here because ``handoff.py`` is the
# sanctioned subprocess consumer (``tests/test_boundary.py``); the ``clean`` CLI
# verb and the doctor stale-ref check call into these helpers and never import
# subprocess themselves.
#
# Honest limit: a SIGKILL/OOM/power-loss *during* the commit can still corrupt
# objects — git/filesystem durability is not colleague's to guarantee. That is
# exactly why this recovery path exists rather than a promise it can't keep.
# ---------------------------------------------------------------------------

#: The ref namespace colleague owns — every reap is scoped to this and nothing
#: else (mirrors ``worktrees.teardown_all`` and the ask-colleague skill guard).
_COLLEAGUE_REF_PREFIX = "colleague/"


def is_git_repo(repo_path: str | Path) -> bool:
    """True when ``repo_path`` is inside a git work tree — read-only.

    The ``colleague clean`` verb uses this to reject a non-git ``--repo`` as a
    user-input error before attempting any reap.
    """
    proc = _git(Path(repo_path).resolve(), "rev-parse", "--is-inside-work-tree", check=False)
    return proc.returncode == 0 and proc.stdout.strip() == "true"


def _git_objects_dir(repo: Path) -> Path | None:
    """The repo's ``.git/objects`` directory (resolved; ``None`` outside a repo).

    Resolved via ``git rev-parse`` rather than assuming ``repo/.git/objects`` so
    a worktree (``.git`` is a file) or a custom ``GIT_DIR`` still works.
    """
    proc = _git(repo, "rev-parse", "--absolute-git-dir", check=False)
    git_dir = proc.stdout.strip()
    if proc.returncode != 0 or not git_dir:
        return None
    return Path(git_dir) / "objects"


def _classify_branch(repo: Path, ref: str, obj: str, *, now: float, base_branch: str) -> dict:
    """Classify one ``colleague/*`` tip: corrupt / merged / live (+ age in days).

    ``cat-file -t`` *inflates* the object (``cat-file -e`` only stats the file, so
    a 0-byte loose object slips past it as "exists"); a non-zero exit means the
    tip is missing/unreadable — the ``git fetch`` breaker. Merge/age checks need a
    readable tip, so they are skipped for a corrupt one.
    """
    corrupt = (not obj) or _git(repo, "cat-file", "-t", obj, check=False).returncode != 0
    merged = False
    age_days: int | None = None
    if not corrupt:
        anc = _git(repo, "merge-base", "--is-ancestor", obj, base_branch, check=False)
        merged = anc.returncode == 0
        age = _git(repo, "log", "-1", "--format=%ct", obj, check=False)
        date_raw = age.stdout.strip()
        if age.returncode == 0 and date_raw.isdigit():
            age_days = max(0, int((now - int(date_raw)) // 86400))
    if corrupt:
        classification = "corrupt"
    elif merged:
        classification = "merged"
    else:
        classification = "live"
    return {
        "ref": ref,
        "object": obj,
        "corrupt": corrupt,
        "merged": merged,
        "age_days": age_days,
        "classification": classification,
    }


def list_colleague_branches(repo_path: str | Path, *, base_branch: str = "main") -> list[dict]:
    """Classify every ``colleague/*`` local branch — read-only.

    Enumerates **only** ``refs/heads/colleague/`` (never a blanket sweep) and,
    per branch, reports:

    * ``ref`` — short ref name (``colleague/<id>-<slug>``);
    * ``object`` — the tip object name recorded in the ref;
    * ``corrupt`` — ``True`` when the tip object is missing/unreadable (the
      ``git fetch`` breaker), detected with ``git cat-file -t``;
    * ``merged`` — ``True`` when the (non-corrupt) tip is an ancestor of
      ``base_branch`` (already integrated, safe to drop);
    * ``age_days`` — whole days since the tip's committer date, or ``None`` when
      the date can't be read (e.g. a corrupt tip);
    * ``classification`` — the primary label for display: ``corrupt`` >
      ``merged`` > ``live`` (``age_days`` is reported but is a reap *policy*
      input, not a classification).

    Returns ``[]`` outside a git repo or on any git error — a non-repo has no
    colleague branches to reap.
    """
    repo = Path(repo_path).resolve()
    # Deliberately NO ``committerdate`` in the format: that field forces
    # for-each-ref to *read* the tip commit object, so a corrupt tip (the case
    # we most need to surface) makes the whole command fail. ``objectname`` is
    # read straight from the ref file — no object access — so corrupt refs still
    # list. Age is looked up separately (and tolerates a corrupt tip).
    proc = _git(
        repo,
        "for-each-ref",
        "--format=%(refname:short)%09%(objectname)",
        "refs/heads/colleague/",
        check=False,
    )
    now = time.time()
    branches: list[dict] = []
    for line in proc.stdout.splitlines():
        parts = line.split("\t")
        ref = parts[0].strip() if parts else ""
        if not ref:
            continue
        obj = parts[1].strip() if len(parts) > 1 else ""
        branches.append(_classify_branch(repo, ref, obj, now=now, base_branch=base_branch))
    return branches


def empty_loose_objects(repo_path: str | Path) -> list[str]:
    """The 0-byte loose object files under ``.git/objects`` — read-only.

    A valid loose object is never 0 bytes (it carries at least a zlib header),
    so a 0-byte file is unambiguously a truncated/interrupted write. These are
    only *reported* (and ``git prune`` suggested) — colleague never reaches into
    ``.git/objects`` to delete them (conservative, #162). Returns paths relative
    to the repo for legible reporting. ``[]`` outside a repo / on any error.
    """
    repo = Path(repo_path).resolve()
    objects = _git_objects_dir(repo)
    if objects is None or not objects.is_dir():
        return []
    empties: list[str] = []
    # Loose objects live under two-hex-char shards: .git/objects/ab/cdef...
    # The whole scan is wrapped: a concurrent `git gc`/prune can remove a shard
    # mid-iteration (so `iterdir()`/`stat()` raises), and a recovery tool must
    # never crash on a repo that is already in a bad state — return what we found.
    try:
        for shard in objects.iterdir():
            if shard.is_dir() and len(shard.name) == 2:
                for obj in shard.iterdir():
                    if obj.is_file() and obj.stat().st_size == 0:
                        empties.append(_relpath(obj, repo))
    except OSError:
        pass
    return sorted(empties)


def _relpath(path: Path, repo: Path) -> str:
    """``path`` relative to ``repo`` when possible, else its absolute string."""
    try:
        return str(path.relative_to(repo))
    except ValueError:
        return str(path)


def _delete_colleague_ref(repo: Path, ref: str, *, dry_run: bool) -> str:
    """Delete one ``colleague/*`` ref via ``git update-ref -d`` — guarded.

    ``git update-ref -d`` (plumbing) deletes the ref even when its tip object is
    missing/corrupt, where ``git branch -D`` can choke. Refuses — never deletes
    — any ref outside ``refs/heads/colleague/`` (defense in depth even though the
    enumerator only yields colleague refs). Returns the action taken:
    ``would-reap`` (dry-run), ``reaped``, ``failed``, or ``refused``.
    """
    if not ref.startswith(_COLLEAGUE_REF_PREFIX):
        return "refused"
    if dry_run:
        return "would-reap"
    proc = _git(repo, "update-ref", "-d", f"refs/heads/{ref}", check=False)
    return "reaped" if proc.returncode == 0 else "failed"


def reap_colleague_branches(
    repo_path: str | Path,
    *,
    dry_run: bool = False,
    include_merged: bool = False,
    older_than_days: int | None = None,
    base_branch: str = "main",
) -> list[dict]:
    """Reap stale/corrupt ``colleague/*`` branches; return per-branch actions.

    The reap set is **always** ``corrupt`` (the ``git fetch`` breaker), plus —
    only when opted in — ``merged`` (``include_merged``) and branches older than
    ``older_than_days``. Everything else is ``kept``. Deletion goes through
    :func:`_delete_colleague_ref` (``git update-ref -d``, ``colleague/*`` only).

    Returns one dict per branch: ``{ref, classification, action}`` where
    ``action`` is ``reaped`` / ``would-reap`` (dry-run) / ``kept`` / ``failed`` /
    ``refused``. Read-only outside a git repo (returns ``[]``).
    """
    repo = Path(repo_path).resolve()
    results: list[dict] = []
    for branch in list_colleague_branches(repo, base_branch=base_branch):
        age = branch["age_days"]
        should_reap = (
            branch["corrupt"]
            or (include_merged and branch["merged"])
            or (older_than_days is not None and age is not None and age >= older_than_days)
        )
        action = (
            _delete_colleague_ref(repo, branch["ref"], dry_run=dry_run) if should_reap else "kept"
        )
        results.append(
            {"ref": branch["ref"], "classification": branch["classification"], "action": action}
        )
    return results


# ---------------------------------------------------------------------------
# Finished-task ledger reap (#411 t19) — ``.colleague/ledger/<id>.jsonl``.
#
# The agents-mode task ledger lives under the OPERATOR repo (``task.
# flight_repo_path or task.repo_path`` — the flight-plane precedent), never
# inside a throwaway worktree, so it survives the worktree's teardown and
# accumulates. ``colleague clean`` reaps a ledger ONLY once its task is
# provably over: the task's artifact exists with a terminal status (``ok`` /
# ``incomplete`` / ``error`` — the whole closed status set), OR the task is
# orphaned (its iso liveness marker names a dead pid, or the caller just reaped
# its iso worktree). A live task — named in ``active_task_ids`` (the recent
# flight ids) or holding an ALIVE liveness marker — is NEVER touched, and a
# ledger with no artifact and no liveness opinion (an in-place run never stamps
# a marker) is kept: absence of evidence is not evidence of death.
#
# No git/subprocess involved; it sits here because ``clean`` gathers every reap
# from this module (the sanctioned "reap scope" home, see above).
# ---------------------------------------------------------------------------

#: Mirrors ``colleague.agents.state.ledger._LEDGER_SUBDIR`` (pinned by
#: ``tests/test_ledger_reap.py`` against ``ledger_path``).
_LEDGER_SUBDIR = Path(".colleague") / "ledger"

#: An artifact carrying this status is FINAL (the run completed); ``incomplete`` /
#: ``error`` artifacts are RESUMABLE (``work --continue``) and their ledger is the
#: continuation seed (#411 c35) — the reap keeps those.
_TERMINAL_STATUSES = frozenset({"ok"})
_RESUMABLE_STATUSES = frozenset({"incomplete", "error"})


def ledger_dir(repo_path: str | Path) -> Path:
    """``<repo>/.colleague/ledger`` — where agents-mode task ledgers live."""
    return Path(repo_path) / _LEDGER_SUBDIR


def _artifact_status(repo: Path, task_id: str) -> str | None:
    """``task_id``'s artifact status, or ``None`` when it is absent/unparseable.

    A 0-byte / unparseable artifact (a truncated write) has no status — the
    artifact reap handles that file; this helper stays conservative.
    """
    from colleague.artifact import find_artifact  # local: keeps module import order flat

    path = find_artifact(repo, task_id)
    if path is None:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    status = data.get("status") if isinstance(data, dict) else None
    return status if isinstance(status, str) else None


def _artifact_is_final(repo: Path, task_id: str) -> bool:
    """True when ``task_id``'s artifact exists, parses, and says the run COMPLETED (``ok``)."""
    return _artifact_status(repo, task_id) in _TERMINAL_STATUSES


def _artifact_is_resumable(repo: Path, task_id: str) -> bool:
    """True when the artifact says ``incomplete`` / ``error`` — a ``work --continue`` seed."""
    return _artifact_status(repo, task_id) in _RESUMABLE_STATUSES


def _liveness_opinion(repo: Path, task_id: str) -> bool | None:
    """``True`` = marker names a live pid, ``False`` = a dead one, ``None`` = no
    (parseable) marker — no opinion either way."""
    from colleague.worktrees import iso_liveness_path, iso_worktree_is_live

    marker = iso_liveness_path(str(repo), task_id)
    try:
        int(marker.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    return iso_worktree_is_live(str(repo), task_id)


def _ledger_is_reapable(repo: Path, task_id: str, *, active: set, orphaned: set) -> bool:
    """The reap predicate: NOT live, NOT resumable, and (final OR orphaned)."""
    if not task_id or task_id in active:
        return False
    alive = _liveness_opinion(repo, task_id)
    if alive is True or _artifact_is_resumable(repo, task_id):
        return False
    return task_id in orphaned or alive is False or _artifact_is_final(repo, task_id)


def reap_finished_ledgers(
    repo_path: str | Path,
    *,
    active_task_ids: "frozenset[str] | set[str] | tuple[str, ...]" = (),
    orphaned_task_ids: "frozenset[str] | set[str] | tuple[str, ...]" = (),
    dry_run: bool = False,
) -> list[str]:
    """Remove finished/orphaned task ledgers under ``.colleague/ledger/``; return their paths.

    A ``<id>.jsonl`` directly under the ledger dir is reaped when — and only
    when — its task is NOT live, NOT resumable, and is either **final** (its
    artifact parses with status ``ok``, :func:`_artifact_is_final`) or
    **orphaned** (``id`` in ``orphaned_task_ids`` — e.g. the iso worktrees
    ``clean`` just reaped — or its liveness marker names a dead pid). **Live**
    wins over everything: an ``id`` in ``active_task_ids`` or an ALIVE marker
    keeps the ledger. **Resumable** wins next: an ``incomplete`` / ``error``
    artifact means ``work --continue`` can still seed from this ledger (#411
    c35), so it is kept even when orphaned. A ledger with no artifact and no
    marker is kept (a run may still be going). Anything that is not ``*.jsonl``
    directly in the dir is never touched. ``dry_run=True`` reports without
    removing; an unlink failure is skipped (not reported, never raised).
    Missing dir = ``[]``.
    """
    repo = Path(repo_path)
    ldir = ledger_dir(repo)
    if not ldir.is_dir():
        return []
    active = set(active_task_ids)
    orphaned = set(orphaned_task_ids)
    reaped: list[str] = []
    for path in sorted(ldir.glob("*.jsonl")):
        if not path.is_file():
            continue
        task_id = path.name[: -len(".jsonl")]
        if not _ledger_is_reapable(repo, task_id, active=active, orphaned=orphaned):
            continue
        if not dry_run:
            try:
                path.unlink()
            except OSError:
                continue
        reaped.append(str(path))
    return reaped
