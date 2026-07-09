"""Config directory loader: resolve .colleague/ at repo and user levels (t1).

This module discovers and resolves configuration files from `.colleague/`
directories at two levels:

1. **Repo-level** — `.colleague/` inside the repo being driven.
2. **User-level** — `.colleague/` in the user's home directory.

Repo-level configuration takes precedence: files with the same name in both
locations are resolved from the repo.

**Back-compat (rename to colleague):** the legacy `.convertible/` directory name
is still honored as a *deprecated read fallback*, so a repo or home that still
carries the old config dir keeps working without a manual move. The
repo-overrides-user invariant above is preserved: a repo-level file always wins
over any user-level file, and *within a single level* the new `.colleague/`
shadows the legacy `.convertible/`. The resolution order is therefore
``[repo/.colleague, repo/.convertible, user/.colleague, user/.convertible]``.

The module exports a clean API for discovering and resolving config files
without any external dependencies — all functions use stdlib only.

**Whole-file vs. per-key resolution:** :func:`resolve_file` returns only the
first existing match (whole-file shadowing — a repo-level file, once present,
hides a user-level file of the same name entirely). :func:`resolve_files`
(plural) returns *every* existing match in the same precedence order instead,
so a caller that wants to merge contents per-key (e.g. ``colleague.config``'s
persistent ``config.json`` — a repo-level file that never mentions a key
should not make a user-level default for that key disappear) can fold the
lower-precedence files in to fill the gaps the higher-precedence file leaves.
"""

from __future__ import annotations

import os
from pathlib import Path

# Module-level constants: the config directory name and the user-level path.
CONFIG_DIR_NAME = ".colleague"
# Deprecated legacy config dir name (pre-rename); read-only fallback, lowest
# precedence. Writes never target it — see the module docstring.
LEGACY_CONFIG_DIR_NAME = ".convertible"
USER_CONFIG_DIR = Path.home() / CONFIG_DIR_NAME


def _default_user_home() -> Path:
    """The user-home base used when no explicit ``user_home=`` is given.

    Hermeticity guard (task t1): ``COLLEAGUE_HOME`` (``CONVERTIBLE_HOME``
    honored as a deprecated fallback, matching every other env-var convention
    in this codebase) overrides the real ``Path.home()`` when set to a
    non-blank value. This exists so a test suite can make EVERY test hermetic
    against the developer's real ``~/.colleague/``/``~/.convertible/`` by
    setting the env var once (see ``tests/conftest.py``), instead of every
    individual test needing to monkeypatch ``Path.home()`` itself — a gap that
    let a real user-level config leak into any test that forgot to (CI stayed
    green only because CI's home happens to be empty). An explicit
    ``user_home=`` argument on :func:`config_roots` (or its callers) always
    takes precedence over this — see there.
    """
    for env_key in ("COLLEAGUE_HOME", "CONVERTIBLE_HOME"):
        value = os.environ.get(env_key)
        if value and value.strip():
            return Path(value.strip())
    return Path.home()


def config_roots(repo_path: str | Path, *, user_home: str | Path | None = None) -> list[Path]:
    """Return existing config roots in precedence order.

    Order is ``[repo/.colleague, repo/.convertible, user/.colleague,
    user/.convertible]`` — repo overrides user (the module invariant), and
    within each level the new ``.colleague/`` name overrides the deprecated
    legacy ``.convertible/`` read fallback. Only includes roots that exist as
    directories. The `user_home` parameter allows tests to inject a fake home
    directory; defaults to :func:`_default_user_home` (``COLLEAGUE_HOME`` /
    ``CONVERTIBLE_HOME`` env var, else the real ``Path.home()``).

    Args:
        repo_path: Path to the repo directory.
        user_home: (test fixture) Path to user's home; defaults to
            :func:`_default_user_home` when omitted — an explicit value here
            always wins over the ``COLLEAGUE_HOME``/``CONVERTIBLE_HOME`` env var.

    Returns:
        List of existing config directory Paths, highest precedence first.
    """
    if user_home is None:
        user_home = _default_user_home()
    else:
        user_home = Path(user_home)

    repo_path = Path(repo_path)
    roots = []

    # Levels outer (repo beats user), dir-names inner (new beats legacy), so the
    # repo-overrides-user invariant holds across the rename: a repo-level config
    # always wins over a user-level one regardless of which dir name each uses.
    for base in (repo_path, user_home):
        for dir_name in (CONFIG_DIR_NAME, LEGACY_CONFIG_DIR_NAME):
            candidate = base / dir_name
            if candidate.is_dir():
                roots.append(candidate)

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


def resolve_files(
    repo_path: str | Path, relative: str, *, user_home: str | Path | None = None
) -> list[Path]:
    """Resolve a file across ALL config roots, in precedence order.

    Unlike :func:`resolve_file` (which returns only the *first* existing
    match — whole-file shadowing), this returns **every** existing match,
    highest precedence first. It is the plumbing a per-key config merge
    (see ``colleague.config``'s ``load_config_file``/``_load_lobes_override``
    and the senses/voice/deepthink section loaders) needs: a lower-precedence
    file can fill in a key a higher-precedence file never mentions, instead of
    being shadowed out of existence entirely.

    Args:
        repo_path: Path to the repo directory.
        relative: Relative path within a config root (e.g., "config.json").
        user_home: (test fixture) Path to user's home; defaults to Path.home().

    Returns:
        List of existing file Paths, highest precedence first. Empty list if
        the file exists in no root.
    """
    roots = config_roots(repo_path, user_home=user_home)
    relative_path = Path(relative)

    return [root / relative_path for root in roots if (root / relative_path).is_file()]


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
