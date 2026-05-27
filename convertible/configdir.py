"""Config directory loader: resolve .convertible/ at repo and user levels (t1).

This module discovers and resolves configuration files from `.convertible/`
directories at two levels:

1. **Repo-level** — `.convertible/` inside the repo being driven.
2. **User-level** — `.convertible/` in the user's home directory.

Repo-level configuration takes precedence: files with the same name in both
locations are resolved from the repo.

The module exports a clean API for discovering and resolving config files
without any external dependencies — all functions use stdlib only.
"""

from __future__ import annotations

from pathlib import Path

# Module-level constant: the user-level config directory.
USER_CONFIG_DIR = Path.home() / ".convertible"


def config_roots(repo_path: str | Path, *, user_home: str | Path | None = None) -> list[Path]:
    """Return existing config roots in precedence order: [repo, user].

    Only includes roots that exist as directories. The `user_home` parameter
    allows tests to inject a fake home directory; defaults to Path.home().

    Args:
        repo_path: Path to the repo directory.
        user_home: (test fixture) Path to user's home; defaults to Path.home().

    Returns:
        List of existing .convertible/ directory Paths, repo before user.
    """
    if user_home is None:
        user_home = Path.home()
    else:
        user_home = Path(user_home)

    repo_path = Path(repo_path)
    roots = []

    repo_config = repo_path / ".convertible"
    if repo_config.is_dir():
        roots.append(repo_config)

    user_config = user_home / ".convertible"
    if user_config.is_dir():
        roots.append(user_config)

    return roots


def resolve_file(
    repo_path: str | Path, relative: str, *, user_home: str | Path | None = None
) -> Path | None:
    """Resolve a file path from config roots, returning the first existing match.

    Scans roots in precedence order (repo first). Returns None if the file
    does not exist in any root.

    Args:
        repo_path: Path to the repo directory.
        relative: Relative path within a config root (e.g., "commands/test.txt").
        user_home: (test fixture) Path to user's home; defaults to Path.home().

    Returns:
        Path to the first existing file, or None if none exists.
    """
    roots = config_roots(repo_path, user_home=user_home)
    relative_path = Path(relative)

    for root in roots:
        candidate = root / relative_path
        if candidate.is_file():
            return candidate

    return None


def collect_files(
    repo_path: str | Path, subdir: str, *, suffix: str = "", user_home: str | Path | None = None
) -> dict[str, Path]:
    """Collect files from subdir across config roots, mapping stem -> Path.

    Repo-level files shadow user-level files by stem. Only includes direct
    children of subdir, not nested files. Files are optionally filtered by
    suffix (e.g., ".txt" or ".json").

    Args:
        repo_path: Path to the repo directory.
        subdir: Subdirectory within each config root (e.g., "commands").
        suffix: (optional) Filter files by suffix (e.g., ".txt").
        user_home: (test fixture) Path to user's home; defaults to Path.home().

    Returns:
        Dictionary mapping file stem to Path, with repo entries shadowing user entries.
    """
    roots = config_roots(repo_path, user_home=user_home)
    result = {}

    # Collect from all roots; user entries first, then override with repo entries.
    for root in reversed(roots):  # reversed so repo (first in roots) overwrites user
        subdir_path = root / subdir
        if not subdir_path.is_dir():
            continue

        for entry in subdir_path.iterdir():
            # Only direct children, and only files
            if not entry.is_file():
                continue

            # Filter by suffix if provided
            if suffix and not entry.name.endswith(suffix):
                continue

            stem = entry.stem
            result[stem] = entry

    return result
