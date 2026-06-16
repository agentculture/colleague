"""#196/#201: concurrent ``colleague work`` isolation guarantees.

Two separate ``colleague work`` invocations against the SAME repo must produce
disjoint ``colleague/<id>`` branches (#201 cross-pollution guard), and an
incomplete run (budget exhaustion) must leave the operator tree pristine (#201
no-strand guarantee).

These tests mirror the helper style of
``tests/test_write_apply_isolation.py`` so the suite reads as one coherent
surface.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from colleague.cli import main


def _run(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(repo), check=True, capture_output=True, text=True
    ).stdout.strip()


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _run(repo, "init", "-q", "-b", "feature")
    _run(repo, "config", "user.email", "op@example.com")
    _run(repo, "config", "user.name", "Operator")
    (repo / "README.md").write_text("seed\n")
    _run(repo, "add", "-A")
    _run(repo, "commit", "-q", "-m", "init")


def _branches(repo: Path) -> list[str]:
    out = _run(repo, "branch", "--format=%(refname:short)")
    return out.split()


def _colleague_branches(repo: Path) -> list[str]:
    return [b for b in _branches(repo) if b.startswith("colleague/")]


def _operator_dirty(repo: Path) -> str:
    """Porcelain status with colleague's own ``.colleague/`` bookkeeping excluded."""
    lines = _run(repo, "status", "--porcelain").splitlines()
    return "\n".join(ln for ln in lines if ".colleague/" not in ln)


def test_two_isolated_runs_produce_disjoint_branches(tmp_path: Path) -> None:
    """#201: two sequential ``colleague work`` runs in the same repo produce
    distinct ``colleague/<id>`` branches; the operator tree/branch are untouched."""
    repo = tmp_path / "repo"
    _init_repo(repo)

    before_branch = _run(repo, "rev-parse", "--abbrev-ref", "HEAD")
    before_head = _run(repo, "rev-parse", "HEAD")

    # Run 1 — instruction A
    rc1 = main(
        [
            "work",
            "implement feature alpha",
            "--repo",
            str(repo),
            "--engine",
            "mock",
            "--no-pr",
        ]
    )
    assert rc1 == 0

    # Run 2 — instruction B (different task id → different branch)
    rc2 = main(
        [
            "work",
            "implement feature beta",
            "--repo",
            str(repo),
            "--engine",
            "mock",
            "--no-pr",
        ]
    )
    assert rc2 == 0

    # Two distinct colleague branches exist.
    cb = _colleague_branches(repo)
    assert len(cb) == 2, f"expected 2 colleague branches, got {cb}"

    # Operator branch and HEAD are byte-identical.
    assert _run(repo, "rev-parse", "--abbrev-ref", "HEAD") == before_branch == "feature"
    assert _run(repo, "rev-parse", "HEAD") == before_head
    assert _operator_dirty(repo) == ""


def test_incomplete_run_leaves_operator_tree_clean(tmp_path: Path) -> None:
    """#201: a budget-exhausted run (``--max-steps 1``) returns non-zero but
    leaves the operator working tree clean and HEAD unmoved — no half-applied
    files in the caller's repo."""
    repo = tmp_path / "repo"
    _init_repo(repo)

    before_branch = _run(repo, "rev-parse", "--abbrev-ref", "HEAD")
    before_head = _run(repo, "rev-parse", "HEAD")

    # ``--max-steps 1`` forces the mock engine to hit the budget before calling
    # ``finish`` (the mock needs 2 steps: write_file + finish).
    rc = main(
        [
            "work",
            "do something",
            "--repo",
            str(repo),
            "--engine",
            "mock",
            "--no-pr",
            "--max-steps",
            "1",
        ]
    )
    # Incomplete run → non-zero exit.
    assert rc != 0, "expected non-zero exit for incomplete run"

    # Operator tree is clean and HEAD is unmoved.
    assert _run(repo, "rev-parse", "--abbrev-ref", "HEAD") == before_branch == "feature"
    assert _run(repo, "rev-parse", "HEAD") == before_head
    assert _operator_dirty(repo) == ""
