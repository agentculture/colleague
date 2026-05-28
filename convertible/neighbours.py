"""Neighbour clone manager — read-only, shallow clones of operator-configured repos.

Reads an allow-list from ``.convertible/neighbours.json`` (a list of
``{"name": str, "url": str}`` objects). For each entry the manager can:

- **clone_all()** — shallow-clone (``git clone --depth 1``) every entry into
  ``.convertible/neighbours/<name>`` inside the repo root.
- **clone_path(name)** — return the local clone ``Path`` for a named entry, or
  ``None`` if the name is not in the allow-list.
- **refresh(name)** — re-fetch from upstream (``git fetch --depth 1`` + reset)
  so the clone is current without creating any local commits.
- **cleanup()** — remove the entire ``.convertible/neighbours/`` tree (to be
  wired to the finish lifecycle by a later task).
- **neighbours()** — return the current allow-list entries as a list of dicts.

Design constraints (enforced by tests and explicit in v0 scope):
- **Zero runtime dependencies** — stdlib only (``json``, ``pathlib``,
  ``subprocess``, ``shutil``).
- **Read-only contract** — no ``commit`` or ``push`` code path exists; this
  module never writes to any git history.
- The clone root (``.convertible/neighbours/``) must be gitignored (handled by
  the repo's ``.gitignore``; this module does not modify git config).
- All git calls use ``subprocess.run([...], check=...)`` with a list argv
  (not ``shell=True``) for security and clarity.
"""

from __future__ import annotations

import json
import shutil
import subprocess  # nosec B404 - shelling out to git for clone/fetch/reset ops
from pathlib import Path


class NeighbourError(Exception):
    """Raised when a git operation on a neighbour clone fails."""


class NeighbourManager:
    """Manages shallow clones of operator-configured neighbour repos.

    All clones live under ``<repo_root>/.convertible/neighbours/<name>/`` and
    are kept out of version control via a ``.gitignore`` entry. The manager
    never commits or pushes anything.

    Args:
        repo_path: Absolute (or relative) path to the repo root being driven.
    """

    _CONFIG_RELPATH = ".convertible/neighbours.json"
    _CLONE_SUBDIR = ".convertible/neighbours"

    def __init__(self, repo_path: str | Path) -> None:
        self._repo = Path(repo_path).resolve()

    # ------------------------------------------------------------------
    # Public read-only API
    # ------------------------------------------------------------------

    def neighbours(self) -> list[dict]:
        """Return the allow-list entries from ``.convertible/neighbours.json``.

        Returns an empty list when the file is absent or contains an empty
        array.
        """
        return self._load_config()

    def clone_all(self) -> None:
        """Shallow-clone every allow-listed neighbour repo (idempotent).

        Already-cloned entries are skipped. Raises :class:`NeighbourError` if
        a ``git clone`` call fails for any entry.
        """
        entries = self._load_config()
        if not entries:
            return

        clone_root = self._repo / self._CLONE_SUBDIR
        clone_root.mkdir(parents=True, exist_ok=True)

        for entry in entries:
            name = entry["name"]
            url = entry["url"]
            dest = clone_root / name

            if dest.is_dir():
                # Already cloned; skip to keep clone_all() idempotent.
                continue

            self._git_clone(url, dest)

    def clone_path(self, name: str) -> Path | None:
        """Return the local clone ``Path`` for *name*, or ``None`` if not configured.

        The path is always ``<repo_root>/.convertible/neighbours/<name>``; it
        is returned whether or not the clone has actually been created yet.
        Returns ``None`` only when *name* is not in the allow-list at all.
        """
        names = {e["name"] for e in self._load_config()}
        if name not in names:
            return None
        return self._repo / self._CLONE_SUBDIR / name

    def refresh(self, name: str) -> None:
        """Re-fetch the latest state of the *name* clone from upstream.

        Uses ``git fetch --depth 1`` followed by a hard reset to
        ``FETCH_HEAD`` so the working tree reflects the upstream tip without
        creating any local commits.

        Raises:
            NeighbourError: if the clone does not exist or the git call fails.
        """
        dest = self._repo / self._CLONE_SUBDIR / name
        if not dest.is_dir():
            raise NeighbourError(
                f"Cannot refresh '{name}': clone directory does not exist at {dest}"
            )

        self._git(dest, "fetch", "--depth", "1")
        self._git(dest, "reset", "--hard", "FETCH_HEAD")

    def cleanup(self) -> None:
        """Remove the entire ``.convertible/neighbours/`` tree.

        Safe to call even when no clones exist. Intended to be wired to the
        finish lifecycle hook by a later task — this method itself does nothing
        beyond ``shutil.rmtree``.
        """
        clone_root = self._repo / self._CLONE_SUBDIR
        if clone_root.exists():
            shutil.rmtree(clone_root)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_config(self) -> list[dict]:
        """Load and return the allow-list; returns [] when absent or empty."""
        config_path = self._repo / self._CONFIG_RELPATH
        if not config_path.is_file():
            return []
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        if not isinstance(data, list):
            return []
        return data

    def _git(self, cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
        """Run a git sub-command in *cwd*; raises NeighbourError on failure."""
        proc = subprocess.run(  # nosec B603 B607 - fixed 'git' argv, no shell
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise NeighbourError(f"git {' '.join(args)} failed in {cwd}: {proc.stderr.strip()}")
        return proc

    def _git_clone(self, url: str, dest: Path) -> None:
        """Shallow-clone *url* into *dest* (``git clone --depth 1``)."""
        proc = subprocess.run(  # nosec B603 B607 - fixed 'git' argv, no shell
            ["git", "clone", "--depth", "1", url, str(dest)],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise NeighbourError(
                f"git clone --depth 1 {url} → {dest} failed: {proc.stderr.strip()}"
            )
