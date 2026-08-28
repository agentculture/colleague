"""Tests for colleague/search_tools.py (task t5).

Covers c7/h5 per the confirmed plan: grep_search's dual backend (ripgrep when
on PATH, a pure-stdlib walker otherwise) must agree on a fixture tree; glob()
must sort by mtime descending and stay repo-confined (including via symlink);
neighbour clones stay searchable while ``.git``/``.colleague/worktrees`` are
excluded by default.
"""

from __future__ import annotations

import os
import re
import shutil
import time
from pathlib import Path

import pytest

from colleague.search_tools import (
    SearchMatch,
    _grep_ripgrep,
    _grep_stdlib,
    _use_ripgrep,
    confine,
    glob,
    grep_search,
)
from colleague.tools import ToolError

RG_AVAILABLE = shutil.which("rg") is not None


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _build_fixture(root: Path) -> None:
    """A small tree exercising both the excluded and searchable corners.

    ``src/`` holds ordinary matches (mixed case, to prove case-insensitivity
    is identical across backends). ``.git/`` and ``.colleague/worktrees/``
    each hold a matching file that must NEVER show up in results.
    ``.colleague/neighbours/`` holds a matching file that MUST show up (the
    read-only neighbour-clone contract).
    """
    _write(root / "src" / "a.py", "line one\nTARGET_TOKEN here\nline three\n")
    _write(root / "src" / "sub" / "b.py", "alpha\nbeta target_token gamma\n")
    _write(root / "docs" / "note.md", "nothing interesting here\n")
    _write(root / ".git" / "HEAD", "TARGET_TOKEN inside git admin, must be excluded\n")
    _write(
        root / ".colleague" / "worktrees" / "childA" / "file.py",
        "TARGET_TOKEN inside a live subagent worktree, must be excluded\n",
    )
    _write(
        root / ".colleague" / "neighbours" / "other-repo" / "lib.py",
        "TARGET_TOKEN inside a read-only neighbour clone, must be included\n",
    )


def _sorted_tuples(matches: list[SearchMatch]) -> list[tuple[str, int, str]]:
    return sorted(m.as_tuple() for m in matches)


# ---------------------------------------------------------------------------
# grep_search — both backends, identical output
# ---------------------------------------------------------------------------


def test_grep_search_stdlib_backend_finds_matches_and_excludes_defaults(
    tmp_path: Path,
) -> None:
    _build_fixture(tmp_path)

    results = _grep_stdlib(
        tmp_path.resolve(),
        tmp_path.resolve(),
        re.compile("target_token", re.IGNORECASE),
        None,
    )
    rels = {m.path for m in results}

    assert "src/a.py" in rels
    assert "src/sub/b.py" in rels
    assert ".git/HEAD" not in rels
    assert ".colleague/worktrees/childA/file.py" not in rels
    # Neighbour clones are read-only source, but searchable.
    assert ".colleague/neighbours/other-repo/lib.py" in rels


@pytest.mark.skipif(not RG_AVAILABLE, reason="rg not on PATH — skipping ripgrep half")
def test_grep_search_ripgrep_backend_finds_matches_and_excludes_defaults(
    tmp_path: Path,
) -> None:
    _build_fixture(tmp_path)

    results = _grep_ripgrep(tmp_path.resolve(), tmp_path.resolve(), "target_token", None)
    rels = {m.path for m in results}

    assert "src/a.py" in rels
    assert "src/sub/b.py" in rels
    assert ".git/HEAD" not in rels
    assert ".colleague/worktrees/childA/file.py" not in rels
    assert ".colleague/neighbours/other-repo/lib.py" in rels


@pytest.mark.skipif(not RG_AVAILABLE, reason="rg not on PATH — skipping ripgrep half")
def test_grep_search_backends_agree_on_fixture_tree(tmp_path: Path) -> None:
    """The acceptance criterion: both backends must produce IDENTICAL output."""
    _build_fixture(tmp_path)

    stdlib_matches = _sorted_tuples(
        _grep_stdlib(
            tmp_path.resolve(),
            tmp_path.resolve(),
            re.compile("target_token", re.IGNORECASE),
            None,
        )
    )
    rg_matches = _sorted_tuples(
        _grep_ripgrep(tmp_path.resolve(), tmp_path.resolve(), "target_token", None)
    )

    assert stdlib_matches == rg_matches
    assert stdlib_matches  # sanity: the fixture actually produced matches


def test_grep_search_public_api_agrees_across_forced_backend_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Drive the *public* grep_search() through both code paths by forcing
    ``_use_ripgrep()``'s return value, so the dispatch logic itself (not just
    the two private walkers) is exercised identically. Skips the ripgrep arm
    with an explicit reason when ``rg`` is not installed."""
    _build_fixture(tmp_path)

    import colleague.search_tools as search_tools

    monkeypatch.setattr(search_tools, "_use_ripgrep", lambda: False)
    stdlib_out = _sorted_tuples(grep_search(tmp_path, "target_token"))

    if not RG_AVAILABLE:
        pytest.skip("rg not on PATH — skipping ripgrep half of the public-API check")

    monkeypatch.setattr(search_tools, "_use_ripgrep", lambda: True)
    rg_out = _sorted_tuples(grep_search(tmp_path, "target_token"))

    assert stdlib_out == rg_out


def test_grep_search_glob_filter_narrows_by_filename(tmp_path: Path) -> None:
    _write(tmp_path / "keep.py", "TARGET_TOKEN\n")
    _write(tmp_path / "skip.md", "TARGET_TOKEN\n")

    results = grep_search(tmp_path, "target_token", glob="*.py")
    rels = {m.path for m in results}

    assert rels == {"keep.py"}


def test_grep_search_max_results_truncates(tmp_path: Path) -> None:
    for i in range(5):
        _write(tmp_path / f"f{i}.py", "TARGET_TOKEN\n")

    results = grep_search(tmp_path, "target_token", max_results=2)
    assert len(results) == 2


def test_grep_search_glob_param_escape_refused(tmp_path: Path) -> None:
    _write(tmp_path / "a.py", "hit\n")
    with pytest.raises(ToolError):
        grep_search(tmp_path, "hit", glob="../*.py")


def test_grep_search_path_escape_refused(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside_root_for_search_tools_test"
    outside.mkdir(exist_ok=True)
    try:
        with pytest.raises(ToolError):
            grep_search(tmp_path, "hit", path="../" + outside.name)
    finally:
        shutil.rmtree(outside, ignore_errors=True)


def test_grep_search_invalid_regex_raises_tool_error(tmp_path: Path) -> None:
    with pytest.raises(ToolError):
        grep_search(tmp_path, "(unclosed")


# ---------------------------------------------------------------------------
# glob() — mtime-descending, confinement, exclusions
# ---------------------------------------------------------------------------


def test_glob_sorts_by_mtime_descending(tmp_path: Path) -> None:
    oldest = tmp_path / "oldest.txt"
    middle = tmp_path / "middle.txt"
    newest = tmp_path / "newest.txt"
    for p in (oldest, middle, newest):
        p.write_text("x", encoding="utf-8")

    now = time.time()
    os.utime(oldest, (now - 300, now - 300))
    os.utime(middle, (now - 200, now - 200))
    os.utime(newest, (now - 100, now - 100))

    results = glob(tmp_path, "*.txt")

    assert results == ["newest.txt", "middle.txt", "oldest.txt"]


def test_glob_recursive_pattern_matches_nested_files(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "a.py", "x")
    _write(tmp_path / "src" / "sub" / "b.py", "x")
    _write(tmp_path / "docs" / "note.md", "x")

    results = set(glob(tmp_path, "**/*.py"))

    assert results == {"src/a.py", "src/sub/b.py"}


def test_glob_excludes_git_and_worktrees_but_includes_neighbours(tmp_path: Path) -> None:
    _build_fixture(tmp_path)

    results = set(glob(tmp_path, "**/*.py"))

    assert "src/a.py" in results
    assert "src/sub/b.py" in results
    assert ".colleague/neighbours/other-repo/lib.py" in results
    assert not any(r.startswith(".git/") for r in results)
    assert not any(r.startswith(".colleague/worktrees/") for r in results)


def test_glob_path_param_confines_search(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "a.py", "x")
    _write(tmp_path / "docs" / "b.py", "x")

    results = glob(tmp_path, "*.py", path="src")

    # Results are always root-relative (like read_file's `path` convention),
    # even when `path` narrows the search to a subdirectory.
    assert results == ["src/a.py"]


def test_glob_path_escape_refused(tmp_path: Path) -> None:
    with pytest.raises(ToolError):
        glob(tmp_path, "*.py", path="../..")


def test_glob_pattern_escape_refused(tmp_path: Path) -> None:
    with pytest.raises(ToolError):
        glob(tmp_path, "../../*.py")


def test_glob_symlink_escape_refused(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    _write(outside / "secret.py", "x")

    link = root / "escape_link"
    link.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ToolError):
        glob(root, "*.py", path="escape_link")


def test_grep_search_symlink_escape_refused(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    _write(outside / "secret.py", "TARGET_TOKEN\n")

    link = root / "escape_link"
    link.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ToolError):
        grep_search(root, "target_token", path="escape_link")


def test_glob_max_results_truncates(tmp_path: Path) -> None:
    for i in range(5):
        (tmp_path / f"f{i}.txt").write_text("x", encoding="utf-8")

    results = glob(tmp_path, "*.txt", max_results=2)
    assert len(results) == 2


# ---------------------------------------------------------------------------
# confine() — the factored-out resolve()-based check (mirrors
# ToolExecutor._safe_path without duplicating it as a bound method)
# ---------------------------------------------------------------------------


def test_confine_allows_paths_under_root(tmp_path: Path) -> None:
    _write(tmp_path / "a" / "b.txt", "x")
    root = tmp_path.resolve()

    resolved = confine(root, "a/b.txt")

    assert resolved == root / "a" / "b.txt"


def test_confine_allows_root_itself(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    assert confine(root, ".") == root


def test_confine_refuses_parent_traversal(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    with pytest.raises(ToolError, match="escapes the repo root"):
        confine(root, "../escape")


def test_use_ripgrep_matches_shutil_which(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    assert _use_ripgrep() is False

    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/rg")
    assert _use_ripgrep() is True
