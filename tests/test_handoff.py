"""Git/PR handoff: gating, local-only commit, no-change short-circuit (R7, h7)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from colleague import handoff as ho
from colleague.handoff import handoff, has_remote, should_open_pr


def _run(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True)


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _run(repo, "init", "-q")
    _run(repo, "config", "user.email", "test@example.com")
    _run(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("seed\n")
    _run(repo, "add", "-A")
    _run(repo, "commit", "-q", "-m", "init")


def _current_branch(repo: Path) -> str:
    proc = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


def _head_sha(repo: Path) -> str:
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


def _branch_exists(repo: Path, name: str) -> bool:
    proc = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", name],
        cwd=str(repo),
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def test_local_only_repo_has_no_remote(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    assert has_remote(repo) is False
    assert should_open_pr(repo, open_pr=True) is False  # no remote -> never pushes


def test_handoff_commits_locally_without_pushing(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    before = _current_branch(repo)
    (repo / "feature.txt").write_text("new work\n")

    result = handoff(repo, "abc123", instruction="add feature", open_pr=True)

    # The branch carries the task-id AND a slug of the request (#132), so it is
    # recognisable in a `git branch` listing — the `colleague/` prefix is kept.
    assert result.branch == "colleague/abc123-add-feature"
    assert result.committed is True
    assert result.pushed is False
    assert result.pr_url is None
    # C2: the commit lands on the drive branch, but the operator is returned to
    # the branch they started on — a drive must not strand them on colleague/<id>.
    assert _current_branch(repo) == before
    # …and the drive branch still exists carrying the commit (not lost on restore).
    assert _branch_exists(repo, result.branch)
    # Restored to `before`, whose tree never had feature.txt (it lives only on the
    # drive branch) — proves the checkout actually moved off the drive branch.
    assert not (repo / "feature.txt").exists()


def test_handoff_restores_detached_head(tmp_path: Path) -> None:
    """C2: a drive that starts on a detached HEAD (the `ask-colleague` worktree case,
    `git worktree add --detach`) is returned to that same commit — detached, not
    stranded on the drive branch."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    original_sha = _head_sha(repo)
    _run(repo, "checkout", "-q", "--detach", "HEAD")
    (repo / "feature.txt").write_text("detached work\n")

    result = handoff(repo, "detached1", open_pr=False)

    assert result.committed is True
    assert result.branch == "colleague/detached1"
    # Back on the original commit, still detached (rev-parse --abbrev-ref == HEAD).
    assert _current_branch(repo) == "HEAD"
    assert _head_sha(repo) == original_sha
    # The commit is preserved on the drive branch.
    assert _branch_exists(repo, "colleague/detached1")


def test_handoff_respects_no_pr_flag(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "feature.txt").write_text("work\n")

    result = handoff(repo, "deadbeef", open_pr=False)
    assert result.committed is True
    assert result.pr_url is None


def test_handoff_no_changes_short_circuits(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)

    result = handoff(repo, "nochange", open_pr=True)
    assert result.committed is False
    assert result.branch is None
    assert "no changes" in result.note


def test_handoff_reports_changed_files(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "new.txt").write_text("hi\n")

    result = handoff(repo, "abc", open_pr=False)
    assert "new.txt" in result.changed_files


# These read the *drive branch* commit by ref, not HEAD: since C2 returns the
# operator to their original branch after committing, HEAD is no longer the drive
# commit. Callers pass `colleague/<task_id>`.
def _commit_subject(repo: Path, ref: str = "HEAD") -> str:
    proc = subprocess.run(
        ["git", "log", "-1", "--format=%s", ref],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


def _commit_body(repo: Path, ref: str = "HEAD") -> str:
    proc = subprocess.run(
        ["git", "log", "-1", "--format=%b", ref],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


def _committed_files(repo: Path, ref: str = "HEAD") -> list[str]:
    proc = subprocess.run(
        ["git", "show", "--name-only", "--format=", ref],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    )
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def test_handoff_excludes_colleague_bookkeeping_dir(tmp_path: Path) -> None:
    """A prior run's untracked .colleague/* artifacts must not be swept in (#39)."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / ".colleague").mkdir()
    (repo / ".colleague" / "old.json").write_text("{}\n")  # leftover from a prior run
    (repo / ".colleague" / "old.trace.jsonl").write_text("\n")
    (repo / "feature.txt").write_text("real work\n")

    result = handoff(repo, "abc123", instruction="add feature", open_pr=False)

    committed = _committed_files(repo, result.branch)
    assert "feature.txt" in committed
    assert not any(p.startswith(".colleague/") for p in committed)
    # changed_files reflects the committed set, not the swept tree.
    assert result.changed_files == ["feature.txt"]


def test_handoff_only_bookkeeping_output_is_a_no_op(tmp_path: Path) -> None:
    """If the only untracked output is .colleague/*, there is nothing to commit (#39)."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / ".colleague").mkdir()
    (repo / ".colleague" / "x.json").write_text("{}\n")
    before = _current_branch(repo)

    result = handoff(repo, "abc123", open_pr=False)
    assert result.committed is False
    assert result.branch is None
    assert "hand off" in result.note
    # No-op must not strand the operator on a freshly-created task branch (Qodo).
    assert _current_branch(repo) == before


def test_handoff_no_op_preserves_current_branch(tmp_path: Path) -> None:
    """When only pre-existing untracked files exist, handoff is a true no-op (Qodo)."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "operator_wip.txt").write_text("do not commit me\n")
    before = _current_branch(repo)

    # The drive produced nothing of its own; operator_wip predates it (baseline).
    result = handoff(repo, "abc123", baseline_untracked=["operator_wip.txt"], open_pr=False)
    assert result.committed is False
    assert result.branch is None
    assert _current_branch(repo) == before


def test_handoff_does_not_sweep_preexisting_untracked(tmp_path: Path) -> None:
    """A pre-existing untracked file (operator WIP) is never swept into the commit (#39, Qodo)."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "operator_wip.txt").write_text("do not commit me\n")  # predates the drive
    (repo / "drive_output.txt").write_text("task work\n")  # produced by the drive

    result = handoff(
        repo,
        "t1",
        changed_files=["drive_output.txt"],
        baseline_untracked=["operator_wip.txt"],
        open_pr=False,
    )

    committed = _committed_files(repo, "colleague/t1")
    assert "drive_output.txt" in committed
    assert "operator_wip.txt" not in committed
    assert result.changed_files == ["drive_output.txt"]


def test_handoff_commits_run_command_tracked_edit(tmp_path: Path) -> None:
    """A modification to an already-tracked file (e.g. a run_command edit) is committed."""
    repo = tmp_path / "repo"
    _init_repo(repo)  # seeds + commits README.md
    (repo / "README.md").write_text("seed\nedited by the drive\n")  # modify a tracked file

    result = handoff(repo, "t1", open_pr=False)
    assert "README.md" in _committed_files(repo, "colleague/t1")
    assert result.changed_files == ["README.md"]


def test_handoff_commit_subject_is_short_with_full_body(tmp_path: Path) -> None:
    """Long instruction -> short subject + full instruction in the body (#40)."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "feature.txt").write_text("work\n")
    instruction = (
        "Build a static site with a read-only file list, inline car-metaphor content, "
        "and a strict length cap so the page never grows unbounded across runs"
    )

    result = handoff(repo, "deadbeef", instruction=instruction, open_pr=False)

    subject = _commit_subject(repo, result.branch)
    assert "\n" not in subject
    assert len(subject) <= len("colleague: ") + 64
    assert subject.startswith("colleague: Build a static site")
    assert subject.endswith("...")
    # Full instruction preserved in the body.
    assert instruction in _commit_body(repo, result.branch)


def test_handoff_short_instruction_needs_no_body(tmp_path: Path) -> None:
    """A short single-line instruction lives entirely in the subject (no redundant body)."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "feature.txt").write_text("work\n")

    result = handoff(repo, "t1", instruction="tidy up", open_pr=False)
    assert result.branch == "colleague/t1-tidy-up"
    assert _commit_subject(repo, result.branch) == "colleague: tidy up"
    assert _commit_body(repo, result.branch) == ""


def test_handoff_empty_instruction_falls_back_to_task_id(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "feature.txt").write_text("work\n")

    handoff(repo, "fallback-id", open_pr=False)
    assert _commit_subject(repo, "colleague/fallback-id") == "colleague: fallback-id"


def test_handoff_surfaces_gitignored_output(tmp_path: Path) -> None:
    """Reported changed_files that are gitignored are surfaced, not dropped (#39)."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / ".gitignore").write_text("site/\n")
    (repo / "site").mkdir()
    (repo / "site" / "index.html").write_text("<html></html>\n")
    (repo / "feature.txt").write_text("work\n")

    result = handoff(
        repo,
        "ignored1",
        changed_files=["site/index.html", "feature.txt"],
        open_pr=False,
    )

    assert result.committed is True
    assert "site/index.html" not in _committed_files(repo, "colleague/ignored1")
    assert "gitignored" in result.note
    assert "site/index.html" in result.note


def test_handoff_pr_title_is_short_subject(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The PR title is the concise subject, not the full instruction (#40)."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "feature.txt").write_text("work\n")
    long_instruction = "x" * 200

    monkeypatch.setattr(ho, "should_open_pr", lambda repo, open_pr: True)
    captured: dict[str, str] = {}

    def fake_pr(repo: Path, base: str, title: str) -> str:
        captured["title"] = title
        return "https://example.com/pr/1"

    monkeypatch.setattr(ho, "_gh_pr_create", fake_pr)

    real_git = ho._git

    def fake_git(repo: Path, *args: str, check: bool = True):  # type: ignore[no-untyped-def]
        if args and args[0] == "push":
            return subprocess.CompletedProcess(list(args), 0, "", "")
        return real_git(repo, *args, check=check)

    monkeypatch.setattr(ho, "_git", fake_git)

    handoff(repo, "task1", instruction=long_instruction, open_pr=True)

    assert "\n" not in captured["title"]
    assert len(captured["title"]) <= len("colleague: ") + 64
    assert captured["title"].endswith("...")


def test_pushed_but_pr_failed_note_is_not_misleading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Push lands but gh pr create fails: the note must not say 'local commit only' (Qodo #4)."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "feature.txt").write_text("work\n")

    monkeypatch.setattr(ho, "should_open_pr", lambda repo, open_pr: True)

    def boom(repo: Path, base: str, title: str) -> str:
        raise ho.HandoffError("gh exploded")

    monkeypatch.setattr(ho, "_gh_pr_create", boom)

    real_git = ho._git

    def fake_git(repo: Path, *args: str, check: bool = True):  # type: ignore[no-untyped-def]
        if args and args[0] == "push":  # pretend the push succeeded (no real remote)
            return subprocess.CompletedProcess(list(args), 0, "", "")
        return real_git(repo, *args, check=check)

    monkeypatch.setattr(ho, "_git", fake_git)

    result = handoff(repo, "task1", open_pr=True)
    assert result.pushed is True
    assert "PR creation failed" in result.note
    assert "local commit only" not in result.note


def test_handoff_skips_literal_tilde_pollution(tmp_path: Path) -> None:
    """A literal ``~/…`` dir at the repo root (shell-expansion test pollution)
    is never committed onto the work branch, and the skip is surfaced (#275)."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    fake_home = repo / "~" / ".culture"
    fake_home.mkdir(parents=True)
    (fake_home / "mesh.yaml").write_text("polluted: true\n")
    (repo / "feature.txt").write_text("real work\n")

    result = handoff(repo, "abc123", instruction="add feature", open_pr=False)

    committed = _committed_files(repo, result.branch)
    assert "feature.txt" in committed
    assert not any(p.startswith("~") for p in committed)
    assert result.changed_files == ["feature.txt"]
    assert "test-pollution" in result.note
    assert "~/.culture/mesh.yaml" in result.note


def test_handoff_commits_tilde_prefixed_legitimate_files(tmp_path: Path) -> None:
    """A tilde-PREFIXED root file (e.g. ``~notes.md``) is a legitimate deliverable
    — only the literal ``~`` segment is #275 pollution, so both files commit."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "~notes.md").write_text("real notes\n")
    (repo / "feature.txt").write_text("real work\n")

    result = handoff(repo, "abc123", instruction="add feature", open_pr=False)

    committed = _committed_files(repo, result.branch)
    assert "~notes.md" in committed
    assert "feature.txt" in committed
    assert sorted(result.changed_files) == ["feature.txt", "~notes.md"]
    assert "test-pollution" not in result.note


def test_handoff_only_tilde_pollution_is_a_no_op(tmp_path: Path) -> None:
    """If the only untracked output is a literal ``~`` dir, nothing is committed
    and the note names both the no-op and the skipped pollution (#275)."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "~").mkdir()
    (repo / "~" / "junk.txt").write_text("x\n")
    before = _current_branch(repo)

    result = handoff(repo, "abc123", open_pr=False)
    assert result.committed is False
    assert result.branch is None
    assert "hand off" in result.note
    assert "test-pollution" in result.note
    assert _current_branch(repo) == before


# ---------------------------------------------------------------------------
# Chain helpers (indefinite-run t5): commits_ahead, chain_handoff_finalize,
# reap_chain_intermediates — the --until-done loop's handoff-once seam (c26).
# ---------------------------------------------------------------------------


def _make_branch_with_commit(
    repo: Path, branch: str, filename: str, base: str | None = None
) -> None:
    """Create *branch* (from *base* or HEAD), commit one file, return to prior ref."""
    before = _current_branch(repo)
    args = ["checkout", "-q", "-b", branch] + ([base] if base else [])
    _run(repo, *args)
    (repo / filename).write_text(f"{filename}\n")
    _run(repo, "add", filename)
    _run(repo, "commit", "-q", "-m", f"add {filename}")
    _run(repo, "checkout", "-q", before)


def test_commits_ahead_counts_and_degrades(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    base_branch = _current_branch(repo)
    _make_branch_with_commit(repo, "colleague/ep1", "one.txt")
    assert ho.commits_ahead(repo, base_branch, "colleague/ep1") == 1
    assert ho.commits_ahead(repo, "colleague/ep1", base_branch) == 0
    # A broken ref degrades to 0 (the guard's conservative side), never raises.
    assert ho.commits_ahead(repo, "no-such-ref", "colleague/ep1") == 0


def test_chain_handoff_finalize_local_only_without_remote(tmp_path: Path) -> None:
    """No remote → the finalize is local-only (h7 gate), never pushes or raises."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _make_branch_with_commit(repo, "colleague/final1", "work.txt")
    before = _current_branch(repo)

    result = ho.chain_handoff_finalize(repo, "final1", "colleague/final1", instruction="do it")
    assert result.branch == "colleague/final1"
    assert result.committed is True
    assert result.pushed is False
    assert result.pr_url is None
    assert "local branches only" in result.note
    # The finalize never switches branches — operator checkout untouched.
    assert _current_branch(repo) == before


def test_chain_handoff_finalize_pushes_final_branch_with_explicit_head(
    tmp_path: Path, monkeypatch
) -> None:
    """With a remote + gh, the finalize pushes by refspec and PRs with --head."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True, capture_output=True)
    _run(repo, "remote", "add", "origin", str(bare))
    _make_branch_with_commit(repo, "colleague/final2", "work.txt")
    before = _current_branch(repo)

    calls: list[dict] = []

    def fake_pr(repo_arg, base_branch, title, head=None, body=None):
        calls.append({"base": base_branch, "title": title, "head": head})
        return "https://example.test/pr/9"

    monkeypatch.setattr(ho, "gh_available", lambda: True)
    monkeypatch.setattr(ho, "_gh_pr_create", fake_pr)

    result = ho.chain_handoff_finalize(
        repo, "final2", "colleague/final2", instruction="chain work", base_branch="main"
    )
    assert result.pushed is True
    assert result.pr_url == "https://example.test/pr/9"
    assert calls == [{"base": "main", "title": "colleague: chain work", "head": "colleague/final2"}]
    assert _current_branch(repo) == before
    # The push actually landed on the bare origin.
    ls = subprocess.run(
        ["git", "ls-remote", "--heads", str(bare), "colleague/final2"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "colleague/final2" in ls.stdout


def test_chain_handoff_finalize_respects_no_pr(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True, capture_output=True)
    _run(repo, "remote", "add", "origin", str(bare))
    _make_branch_with_commit(repo, "colleague/final3", "work.txt")
    monkeypatch.setattr(ho, "gh_available", lambda: True)

    result = ho.chain_handoff_finalize(repo, "final3", "colleague/final3", open_pr=False)
    assert result.pushed is False
    assert result.pr_url is None
    assert "local branches only" in result.note


def test_gh_pr_create_body_replaces_fill(monkeypatch) -> None:
    """--fill and --body are mutually exclusive: an explicit body (#340's
    gate-deferral warning) replaces the commit-derived fill; no body keeps the
    argv byte-identical to today. Never gh pr edit."""
    captured: list[list[str]] = []

    class _Proc:
        returncode = 0
        stdout = "https://example.test/pr/1\n"
        stderr = ""

    def fake_run(argv, **kwargs):
        captured.append(list(argv))
        return _Proc()

    monkeypatch.setattr(ho.subprocess, "run", fake_run)

    ho._gh_pr_create(Path("."), "main", "title", head="colleague/x")
    assert captured[0] == [
        "gh", "pr", "create", "--fill", "--base", "main",
        "--title", "title", "--head", "colleague/x",
    ]

    ho._gh_pr_create(Path("."), "main", "title", head="colleague/x", body="gates deferred")
    assert "--fill" not in captured[1]
    body_at = captured[1].index("--body")
    assert captured[1][body_at + 1] == "gates deferred"
    assert "edit" not in captured[1]


def test_chain_handoff_finalize_threads_body_to_pr(tmp_path: Path, monkeypatch) -> None:
    """The finalize passes an explicit PR body through to _gh_pr_create (#340 b3)."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True, capture_output=True)
    _run(repo, "remote", "add", "origin", str(bare))
    _make_branch_with_commit(repo, "colleague/final9", "work.txt")

    calls: list[dict] = []

    def fake_pr(repo_arg, base_branch, title, head=None, body=None):
        calls.append({"head": head, "body": body})
        return "https://example.test/pr/10"

    monkeypatch.setattr(ho, "gh_available", lambda: True)
    monkeypatch.setattr(ho, "_gh_pr_create", fake_pr)

    warning = "warning: handoff fired with pre-finish gates deferred on the final episode"
    result = ho.chain_handoff_finalize(
        repo, "final9", "colleague/final9", instruction="chain work", body=warning
    )
    assert result.pr_url == "https://example.test/pr/10"
    assert calls == [{"head": "colleague/final9", "body": warning}]

    # No body → None threads through (the --fill path stays the default).
    ho.chain_handoff_finalize(repo, "final9", "colleague/final9", instruction="chain work")
    assert calls[1]["body"] is None


def test_chain_handoff_finalize_body_offline_degrades(tmp_path: Path) -> None:
    """A warning body never breaks the offline/no-remote degrade (h18)."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _make_branch_with_commit(repo, "colleague/final10", "work.txt")
    result = ho.chain_handoff_finalize(repo, "final10", "colleague/final10", body="warn")
    assert result.pushed is False
    assert result.pr_url is None
    assert "local branches only" in result.note


def test_reap_chain_intermediates_ancestor_guard(tmp_path: Path) -> None:
    """Reaps only ancestors of the kept final branch; never the keep, never a
    non-ancestor (unique work), never a non-colleague ref (refused)."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    base_branch = _current_branch(repo)
    # ep1 <- ep2 (final): ep1 is an ancestor of ep2.
    _make_branch_with_commit(repo, "colleague/ep-a", "a.txt")
    _make_branch_with_commit(repo, "colleague/ep-b", "b.txt", base="colleague/ep-a")
    # A stray branch NOT reachable from the final (a degraded-base episode).
    _make_branch_with_commit(repo, "colleague/stray", "stray.txt", base=base_branch)

    actions = ho.reap_chain_intermediates(
        repo,
        ["colleague/ep-a", "colleague/stray", base_branch, "colleague/ep-b"],
        keep="colleague/ep-b",
    )
    by_ref = {a["ref"]: a["action"] for a in actions}
    assert by_ref["colleague/ep-a"] == "reaped"
    assert by_ref["colleague/stray"] == "kept"  # not an ancestor — unique work
    assert by_ref["colleague/ep-b"] == "kept"  # the deliverable
    # The base branch is an ancestor of the final tip, but it is outside the
    # colleague/* namespace — _delete_colleague_ref refuses it (defense in depth).
    assert by_ref[base_branch] == "refused"

    proc = subprocess.run(
        ["git", "for-each-ref", "--format=%(refname:short)", "refs/heads/"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    )
    remaining = set(proc.stdout.split())
    assert "colleague/ep-a" not in remaining
    assert {"colleague/ep-b", "colleague/stray", base_branch} <= remaining
