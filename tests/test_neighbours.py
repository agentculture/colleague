"""Neighbour clone manager — acceptance criteria for convertible/neighbours.py.

AC1: No allow-list → neighbour set is EMPTY; clone_all() is a safe no-op.
AC2: Allow-listed repo is shallow-cloned (--depth 1) into
     .convertible/neighbours/<name> inside the repo root; clone_path() returns
     that path.
AC3: Public API exposes only clone/refresh/read/cleanup — never commit/push.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import convertible.neighbours as nb
from convertible.neighbours import NeighbourManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )


def _make_source_repo(path: Path) -> Path:
    """Create a minimal local git repo to use as a clone source."""
    path.mkdir(parents=True, exist_ok=True)
    _run(path, "git", "init", "-b", "main")
    _run(path, "git", "config", "user.email", "test@example.com")
    _run(path, "git", "config", "user.name", "Test")
    readme = path / "README.md"
    readme.write_text("hello from source\n")
    _run(path, "git", "add", "-A")
    _run(path, "git", "commit", "-m", "init")
    return path


def _make_consumer_repo(path: Path) -> Path:
    """Create a minimal local git repo to act as the 'consumer' (the repo being driven)."""
    path.mkdir(parents=True, exist_ok=True)
    _run(path, "git", "init", "-b", "main")
    _run(path, "git", "config", "user.email", "test@example.com")
    _run(path, "git", "config", "user.name", "Test")
    seed = path / "seed.txt"
    seed.write_text("consumer repo\n")
    _run(path, "git", "add", "-A")
    _run(path, "git", "commit", "-m", "init")
    return path


def _write_neighbours_json(repo: Path, entries: list[dict]) -> None:
    """Write .convertible/neighbours.json in the given repo."""
    import json

    config_dir = repo / ".convertible"
    config_dir.mkdir(exist_ok=True)
    (config_dir / "neighbours.json").write_text(json.dumps(entries))


# ---------------------------------------------------------------------------
# AC1 — empty / missing config → no neighbours, clone_all() is safe no-op
# ---------------------------------------------------------------------------


def test_no_config_file_gives_empty_neighbour_set(tmp_path: Path) -> None:
    """AC1: With no .convertible/neighbours.json, the manager yields an empty set."""
    repo = _make_consumer_repo(tmp_path / "consumer")
    manager = NeighbourManager(repo)
    assert manager.neighbours() == []


def test_empty_config_gives_empty_neighbour_set(tmp_path: Path) -> None:
    """AC1: An empty list in the config file → empty set."""
    repo = _make_consumer_repo(tmp_path / "consumer")
    _write_neighbours_json(repo, [])
    manager = NeighbourManager(repo)
    assert manager.neighbours() == []


def test_clone_all_with_no_config_is_safe_noop(tmp_path: Path) -> None:
    """AC1: clone_all() with no config raises nothing and creates no directories."""
    repo = _make_consumer_repo(tmp_path / "consumer")
    manager = NeighbourManager(repo)
    manager.clone_all()  # must not raise
    clone_root = repo / ".convertible" / "neighbours"
    assert not clone_root.exists()


# ---------------------------------------------------------------------------
# AC2 — allow-listed repo is shallow-cloned inside the repo root
# ---------------------------------------------------------------------------


def test_clone_all_shallow_clones_into_repo(tmp_path: Path) -> None:
    """AC2: clone_all() does a --depth 1 clone into .convertible/neighbours/<name>."""
    source = _make_source_repo(tmp_path / "source")
    repo = _make_consumer_repo(tmp_path / "consumer")
    _write_neighbours_json(repo, [{"name": "mysvc", "url": str(source)}])

    manager = NeighbourManager(repo)
    manager.clone_all()

    clone_dir = repo / ".convertible" / "neighbours" / "mysvc"
    assert clone_dir.is_dir(), "Clone directory must exist inside repo"
    # Confirm the cloned content is accessible
    assert (clone_dir / "README.md").is_file()


def test_clone_path_returns_path_inside_repo(tmp_path: Path) -> None:
    """AC2: clone_path(name) returns a path that is inside the repo root."""
    source = _make_source_repo(tmp_path / "source")
    repo = _make_consumer_repo(tmp_path / "consumer")
    _write_neighbours_json(repo, [{"name": "svc", "url": str(source)}])

    manager = NeighbourManager(repo)
    manager.clone_all()

    path = manager.clone_path("svc")
    assert path is not None
    # The clone path must be inside the repo root
    assert path == repo / ".convertible" / "neighbours" / "svc"
    repo_resolved = repo.resolve()
    assert path.resolve().is_relative_to(repo_resolved), "Clone path must be under repo root"


def test_clone_path_for_unknown_name_returns_none(tmp_path: Path) -> None:
    """AC2: clone_path for a name not in config returns None."""
    repo = _make_consumer_repo(tmp_path / "consumer")
    manager = NeighbourManager(repo)
    assert manager.clone_path("nonexistent") is None


def test_shallow_clone_depth_is_one(tmp_path: Path) -> None:
    """AC2: The clone is shallow (depth=1), so only one commit is fetched.

    Uses a ``file://`` URL so git honours ``--depth 1`` (local-path remotes
    ignore the flag without ``file://``; see ``git help clone``).
    """
    source = _make_source_repo(tmp_path / "source")
    # Add extra commits to the source to confirm shallow behaviour
    (source / "extra.txt").write_text("extra\n")
    _run(source, "git", "add", "-A")
    _run(source, "git", "commit", "-m", "second commit")
    (source / "more.txt").write_text("more\n")
    _run(source, "git", "add", "-A")
    _run(source, "git", "commit", "-m", "third commit")

    repo = _make_consumer_repo(tmp_path / "consumer")
    # Must use file:// so git respects --depth 1 (local paths skip depth)
    _write_neighbours_json(repo, [{"name": "svc", "url": f"file://{source}"}])

    manager = NeighbourManager(repo)
    manager.clone_all()

    clone_dir = repo / ".convertible" / "neighbours" / "svc"
    # In a --depth 1 clone, git log has exactly 1 entry
    proc = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"],
        cwd=str(clone_dir),
        capture_output=True,
        text=True,
        check=True,
    )
    assert proc.stdout.strip() == "1", "Shallow clone must have exactly 1 commit"


# ---------------------------------------------------------------------------
# AC2 — refresh() re-fetches without committing
# ---------------------------------------------------------------------------


def test_refresh_pulls_new_content(tmp_path: Path) -> None:
    """AC2: refresh() fetches new commits from the source repo."""
    source = _make_source_repo(tmp_path / "source")
    repo = _make_consumer_repo(tmp_path / "consumer")
    _write_neighbours_json(repo, [{"name": "svc", "url": str(source)}])

    manager = NeighbourManager(repo)
    manager.clone_all()

    # Add a new file to the source
    new_file = source / "update.txt"
    new_file.write_text("updated content\n")
    _run(source, "git", "add", "-A")
    _run(source, "git", "commit", "-m", "upstream update")

    manager.refresh("svc")

    clone_dir = repo / ".convertible" / "neighbours" / "svc"
    assert (clone_dir / "update.txt").is_file(), "refresh() must bring in new files"


# ---------------------------------------------------------------------------
# AC2 — cleanup() removes the clone root
# ---------------------------------------------------------------------------


def test_cleanup_removes_clone_root(tmp_path: Path) -> None:
    """AC2/AC3: cleanup() removes the .convertible/neighbours/ directory."""
    source = _make_source_repo(tmp_path / "source")
    repo = _make_consumer_repo(tmp_path / "consumer")
    _write_neighbours_json(repo, [{"name": "svc", "url": str(source)}])

    manager = NeighbourManager(repo)
    manager.clone_all()

    clone_root = repo / ".convertible" / "neighbours"
    assert clone_root.is_dir()

    manager.cleanup()
    assert not clone_root.exists(), "cleanup() must remove the clone root"


def test_cleanup_is_safe_noop_when_nothing_cloned(tmp_path: Path) -> None:
    """AC3: cleanup() raises nothing when the clone root does not exist."""
    repo = _make_consumer_repo(tmp_path / "consumer")
    manager = NeighbourManager(repo)
    manager.cleanup()  # must not raise


# ---------------------------------------------------------------------------
# AC3 — public API exposes only clone/refresh/read/cleanup, never commit/push
# ---------------------------------------------------------------------------


def test_public_api_has_no_commit_or_push(tmp_path: Path) -> None:
    """AC3: NeighbourManager must not expose any commit or push method."""
    repo = _make_consumer_repo(tmp_path / "consumer")
    manager = NeighbourManager(repo)

    forbidden = {"commit", "push", "git_push", "git_commit"}
    exposed = {name for name in dir(manager) if not name.startswith("_")}
    overlap = forbidden & exposed
    assert not overlap, f"Public API must not expose commit/push methods; found: {overlap}"


def test_module_has_no_commit_or_push_functions() -> None:
    """AC3: The neighbours module itself must not expose commit or push at module level."""
    forbidden = {"commit", "push", "git_push", "git_commit"}
    module_names = {name for name in dir(nb) if not name.startswith("_")}
    overlap = forbidden & module_names
    assert not overlap, f"Module must not expose commit/push; found: {overlap}"


def test_allowed_public_methods_cover_contract(tmp_path: Path) -> None:
    """AC3: The expected read-only public contract is present."""
    repo = _make_consumer_repo(tmp_path / "consumer")
    manager = NeighbourManager(repo)

    required = {"clone_all", "clone_path", "refresh", "cleanup", "neighbours"}
    for method in required:
        assert hasattr(manager, method), f"NeighbourManager must expose '{method}'"
