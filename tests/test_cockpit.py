"""Tests for :mod:`colleague.cockpit` — the shared repo-context cockpit builder.

The builder is the single source of truth for the repo + branch + working-tree
facts that the interactive session and the headless ``tui --repo`` surfaces show.
It must resolve a real git repo, degrade safely on a non-git path (never raise),
keep the panel ids/labels identical to ``session._context_panel``, and — being a
top-level module that *calls* the sanctioned subprocess consumers — never import
``subprocess`` itself.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from colleague.cockpit import (
    build_cockpit_state,
    build_repo_context_panel,
    resolve_repo_context,
)


def _git_repo(path: Path, *, branch: str = "wip-branch") -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.dev"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True)
    (path / "f.txt").write_text("hello\n")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True)
    # Use a known branch name so the assertion is deterministic regardless of the
    # ambient ``init.defaultBranch`` (main vs master).
    subprocess.run(["git", "checkout", "-q", "-b", branch], cwd=path, check=True)


# ── resolve_repo_context ─────────────────────────────────────────────────────


def test_resolve_repo_context_clean_repo(tmp_path: Path) -> None:
    _git_repo(tmp_path, branch="feature-z")
    ctx = resolve_repo_context(tmp_path)
    assert ctx["branch"] == "feature-z"
    assert ctx["is_git"] is True
    assert ctx["dirty"] is False
    # No identity config → falls back to the repo folder name.
    assert ctx["ident"] == tmp_path.name


def test_resolve_repo_context_dirty_tree(tmp_path: Path) -> None:
    _git_repo(tmp_path)
    (tmp_path / "f.txt").write_text("changed\n")  # tracked modification
    ctx = resolve_repo_context(tmp_path)
    assert ctx["dirty"] is True


def test_resolve_repo_context_non_git_degrades(tmp_path: Path) -> None:
    # A non-git path must degrade to safe defaults, never raise.
    ctx = resolve_repo_context(tmp_path)
    assert ctx == {
        "ident": tmp_path.name,
        "branch": "unknown",
        "dirty": False,
        "is_git": False,
    }


# ── build_repo_context_panel ─────────────────────────────────────────────────


def test_build_repo_context_panel_ids_match_session(tmp_path: Path) -> None:
    _git_repo(tmp_path, branch="topic")
    panel = build_repo_context_panel(tmp_path)
    assert panel.id == "context"
    assert panel.title == "Context"
    by_id = {item.id: item for item in panel.items}
    # Ids + labels MUST match session._context_panel so TAUI selectors are stable
    # across the interactive and headless surfaces.
    assert by_id["ctx.repo"].label == "📁 repo"
    assert by_id["ctx.branch"].label == "🌿 branch"
    assert by_id["ctx.tree"].label == "🧭 working tree"
    assert by_id["ctx.branch"].status == "topic"
    assert by_id["ctx.tree"].status == "clean"


def test_build_repo_context_panel_dirty_label(tmp_path: Path) -> None:
    _git_repo(tmp_path)
    (tmp_path / "f.txt").write_text("changed\n")
    panel = build_repo_context_panel(tmp_path)
    by_id = {item.id: item for item in panel.items}
    assert by_id["ctx.tree"].status == "dirty (tracked changes)"


def test_build_cockpit_state_wraps_panel(tmp_path: Path) -> None:
    _git_repo(tmp_path)
    state = build_cockpit_state(tmp_path)
    assert [p.id for p in state.panels] == ["context"]


# ── boundary: cockpit.py must not import subprocess itself ────────────────────


def test_cockpit_does_not_import_subprocess() -> None:
    source = Path("colleague/cockpit.py").read_text(encoding="utf-8")
    assert "import subprocess" not in source
