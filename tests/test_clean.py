"""``colleague clean`` (#162) — reap a repo a crashed work item left wedged.

Covers the plan's coverage targets: branch classification + reaping
(``colleague/*``-scoped, ``git update-ref -d`` on a corrupt tip), orphaned
0-byte artifact reaping, handoff crash-resilience, the headline ``git fetch``
un-wedge, the ``clean`` CLI verb, and the advisory ``doctor`` stale-ref check.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from colleague import artifact, handoff
from colleague.cli import main

# A SHA whose loose object we fabricate as 0 bytes — the crash signature.
_CORRUPT_SHA = "1b80678900000000000000000000000000002fdf"


def _git(repo: Path, *args: str, env: dict | None = None) -> None:
    subprocess.run(
        ["git", *args], cwd=str(repo), check=True, capture_output=True, text=True, env=env
    )


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "a.txt").write_text("hi\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")


def _wedge(repo: Path, ref: str = "colleague/d8ca-corrupt") -> None:
    """Leave a corrupt ``colleague/*`` ref exactly as a crashed git does.

    Writes the ref file directly (bypassing git's write-time object validation)
    pointing at a 0-byte loose object — the dangling-ref → empty-object state that
    breaks ``git fetch``.
    """
    obj_dir = repo / ".git" / "objects" / _CORRUPT_SHA[:2]
    obj_dir.mkdir(parents=True, exist_ok=True)
    (obj_dir / _CORRUPT_SHA[2:]).write_bytes(b"")  # 0-byte loose object
    ref_path = repo / ".git" / "refs" / "heads" / Path(ref)
    ref_path.parent.mkdir(parents=True, exist_ok=True)
    ref_path.write_text(_CORRUPT_SHA + "\n")


def _refs(repo: Path) -> set[str]:
    proc = subprocess.run(
        ["git", "for-each-ref", "--format=%(refname:short)", "refs/heads/"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    )
    return {line.strip() for line in proc.stdout.splitlines() if line.strip()}


# --- classification + reaping ----------------------------------------------


def test_corrupt_ref_classified_and_scoping(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    _init_repo(repo)
    _git(repo, "branch", "feature/keep")  # unrelated branch — never enumerated
    _wedge(repo)

    branches = handoff.list_colleague_branches(repo)
    by_ref = {b["ref"]: b for b in branches}
    assert "feature/keep" not in by_ref  # scoping: colleague/* only
    assert by_ref["colleague/d8ca-corrupt"]["corrupt"] is True
    assert by_ref["colleague/d8ca-corrupt"]["classification"] == "corrupt"


def test_reap_corrupt_default_and_unrelated_branch_survives(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    _init_repo(repo)
    _git(repo, "branch", "feature/keep")
    _wedge(repo)

    result = handoff.reap_colleague_branches(repo)
    actions = {r["ref"]: r["action"] for r in result}
    assert actions["colleague/d8ca-corrupt"] == "reaped"

    refs = _refs(repo)
    assert "colleague/d8ca-corrupt" not in refs  # reaped
    assert {"main", "feature/keep"} <= refs  # untouched


def test_reap_dry_run_changes_nothing(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    _init_repo(repo)
    _wedge(repo)

    result = handoff.reap_colleague_branches(repo, dry_run=True)
    assert result[0]["action"] == "would-reap"
    assert "colleague/d8ca-corrupt" in _refs(repo)  # still present


def test_delete_ref_refuses_non_colleague(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    _init_repo(repo)
    _git(repo, "branch", "feature/keep")
    # Defense in depth: even handed a non-colleague ref, the primitive refuses.
    assert handoff._delete_colleague_ref(repo, "feature/keep", dry_run=False) == "refused"
    assert "feature/keep" in _refs(repo)


def test_merged_branch_is_opt_in(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    _init_repo(repo)
    _git(repo, "branch", "colleague/merged")  # at main's tip -> ancestor -> merged

    [info] = handoff.list_colleague_branches(repo)
    assert info["merged"] is True and info["classification"] == "merged"

    # Default keeps a merged branch; --merged reaps it.
    assert handoff.reap_colleague_branches(repo)[0]["action"] == "kept"
    assert handoff.reap_colleague_branches(repo, include_merged=True)[0]["action"] == "reaped"
    assert "colleague/merged" not in _refs(repo)


def test_older_than_is_opt_in(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    _init_repo(repo)
    old = {
        **os.environ,
        "GIT_COMMITTER_DATE": "2020-01-01T00:00:00",
        "GIT_AUTHOR_DATE": "2020-01-01T00:00:00",
    }
    _git(repo, "checkout", "-q", "-b", "colleague/old", env=old)
    (repo / "old.txt").write_text("x\n")
    _git(repo, "add", "-A", env=old)
    _git(repo, "commit", "-q", "-m", "old", env=old)
    _git(repo, "checkout", "-q", "main")

    [info] = handoff.list_colleague_branches(repo)
    assert info["age_days"] is not None and info["age_days"] > 365
    assert info["classification"] == "live"  # ahead of main, not merged

    assert handoff.reap_colleague_branches(repo)[0]["action"] == "kept"  # default keeps it
    assert handoff.reap_colleague_branches(repo, older_than_days=30)[0]["action"] == "reaped"


def test_empty_loose_objects_reports_but_does_not_delete(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    _init_repo(repo)
    _wedge(repo)
    obj_path = repo / ".git" / "objects" / _CORRUPT_SHA[:2] / _CORRUPT_SHA[2:]

    empties = handoff.empty_loose_objects(repo)
    assert any(_CORRUPT_SHA[2:] in e for e in empties)
    assert obj_path.exists()  # conservative: reported, never deleted


# --- orphaned-artifact reaping ---------------------------------------------


def test_reap_artifacts_removes_empty_keeps_valid(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    cdir = repo / ".colleague"
    cdir.mkdir(parents=True)
    (cdir / "d8ca.x.json").write_bytes(b"")  # 0-byte crash leftover
    (cdir / "d8ca.x.trace.jsonl").write_bytes(b"")
    (cdir / "last_work").write_text("d8ca\n")  # points at the 0-byte artifact
    valid = cdir / "keepme.real.json"
    valid.write_text('{"task_id":"keepme","stats":{"request":"real"}}\n')

    actions = {r["artifact"]: r["action"] for r in artifact.reap_artifacts(repo)}
    assert actions["d8ca.x.json"] == "reaped"
    assert actions["d8ca.x.trace.jsonl"] == "reaped"
    assert actions["last_work"] == "cleared"
    assert not (cdir / "last_work").exists()
    assert valid.exists()  # a non-empty (gradable) artifact is never touched


def test_reap_artifacts_dry_run_changes_nothing(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    cdir = repo / ".colleague"
    cdir.mkdir(parents=True)
    (cdir / "d8ca.x.json").write_bytes(b"")

    actions = {r["artifact"]: r["action"] for r in artifact.reap_artifacts(repo, dry_run=True)}
    assert actions["d8ca.x.json"] == "would-reap"
    assert (cdir / "d8ca.x.json").exists()


# --- handoff crash-resilience ----------------------------------------------


def test_handoff_commit_failure_reaps_orphan_branch(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "r"
    _init_repo(repo)
    (repo / "a.txt").write_text("edited\n")  # a real change to hand off

    real_git = handoff._git

    def boom_on_commit(r, *args, check=True):
        if args and args[0] == "commit":
            raise handoff.HandoffError("simulated crash mid-commit")
        return real_git(r, *args, check=check)

    monkeypatch.setattr(handoff, "_git", boom_on_commit)

    with pytest.raises(handoff.HandoffError):
        handoff.handoff(repo, task_id="t1", instruction="do x", open_pr=False)

    # No orphan colleague/* branch left behind, operator restored to main.
    assert not any(r.startswith("colleague/") for r in _refs(repo))
    assert handoff.current_ref(repo) == "main"


# --- the headline: clean un-wedges git fetch -------------------------------


def test_clean_unwedges_git_fetch(tmp_path: Path) -> None:
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
    repo = tmp_path / "work"
    _init_repo(repo)
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "push", "-q", "-u", "origin", "main")
    _wedge(repo)

    before = subprocess.run(
        ["git", "fetch", "origin"], cwd=str(repo), capture_output=True, text=True
    )
    assert before.returncode != 0  # wedged: fetch aborts

    handoff.reap_colleague_branches(repo)

    after = subprocess.run(
        ["git", "fetch", "origin"], cwd=str(repo), capture_output=True, text=True
    )
    assert after.returncode == 0  # recovered


# --- the clean CLI verb -----------------------------------------------------


def test_clean_cli_json_reaps(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = tmp_path / "r"
    _init_repo(repo)
    _wedge(repo)
    (repo / ".colleague").mkdir()
    (repo / ".colleague" / "d8ca.x.json").write_bytes(b"")

    rc = main(["clean", "--repo", str(repo), "--json"])
    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert any(b["action"] == "reaped" for b in report["branches"])
    assert any(a["action"] == "reaped" for a in report["artifacts"])
    assert report["empty_loose_objects"]  # reported (git prune hint territory)
    assert "colleague/d8ca-corrupt" not in _refs(repo)


def test_clean_cli_dry_run_changes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "r"
    _init_repo(repo)
    _wedge(repo)

    rc = main(["clean", "--repo", str(repo), "--dry-run", "--json"])
    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert report["dry_run"] is True
    assert all(b["action"] in ("would-reap", "kept") for b in report["branches"])
    assert "colleague/d8ca-corrupt" in _refs(repo)  # untouched


def test_clean_cli_non_git_repo_is_user_error(tmp_path: Path) -> None:
    rc = main(["clean", "--repo", str(tmp_path)])  # tmp_path is not a git repo
    assert rc == 1  # EXIT_USER_ERROR


def test_explain_clean_resolves(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["explain", "clean"])
    assert rc == 0
    assert "colleague clean" in capsys.readouterr().out


# --- doctor advisory stale-ref check ---------------------------------------


def test_doctor_stale_refs_warns_but_stays_healthy(tmp_path: Path, monkeypatch) -> None:
    from colleague.oilcheck import diagnose, stale_refs

    repo = tmp_path / "r"
    _init_repo(repo)
    _wedge(repo)
    monkeypatch.chdir(repo)

    [check] = stale_refs.checks()
    assert check["id"] == "colleague_stale_refs"
    assert check["passed"] is False and check["severity"] == "warning"
    assert "clean" in check["remediation"]

    # Advisory: a wedged repo never flips the overall report unhealthy.
    report = diagnose()
    stale = [c for c in report["checks"] if c["id"] == "colleague_stale_refs"][0]
    assert stale["passed"] is False
    assert report["healthy"] is True


def test_doctor_stale_refs_clean_repo_passes(tmp_path: Path, monkeypatch) -> None:
    from colleague.oilcheck import stale_refs

    repo = tmp_path / "r"
    _init_repo(repo)
    monkeypatch.chdir(repo)

    [check] = stale_refs.checks()
    assert check["passed"] is True and check["remediation"] == ""


def test_doctor_stale_refs_non_git_is_noop(tmp_path: Path, monkeypatch) -> None:
    from colleague.oilcheck import stale_refs

    monkeypatch.chdir(tmp_path)  # not a git repo
    [check] = stale_refs.checks()
    assert check["passed"] is True
