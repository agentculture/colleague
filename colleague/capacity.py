"""Advisory capacity assessment for repo work items.

Sizing a work item against the model context budget without ever raising or
blocking.  Pure stdlib — no third-party imports.
"""

from __future__ import annotations

import json
import os
from contextlib import suppress
from dataclasses import dataclass
from typing import Callable, Optional, Sequence

# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

_SKIP_DIRS = frozenset({".git", ".venv", "node_modules", "__pycache__", ".colleague", ".devague"})

# Coarse per-signal token weights folded into the effective size estimate, so the
# verdict RELIES on the project complexity (deps/folders/files) the way #156 asks —
# not on the instruction text alone. Deliberately rough proxies for "context this
# structure may pull in", never a precise measure; the whole module is advisory.
_TOKENS_PER_FILE = 200
_TOKENS_PER_DEP = 100
_TOKENS_PER_FOLDER = 50


@dataclass
class CapacityVerdict:
    """Coarse, advisory capacity assessment for a repo work item."""

    dep_count: int
    folder_count: int
    file_count: int
    instruction_tokens: int
    verdict: str
    detail: str
    # The instruction estimate PLUS the coarse complexity contribution
    # (deps/folders/files). This — not ``instruction_tokens`` alone — drives the
    # verdict, so a structurally bigger repo reads as a bigger job (#156).
    effective_tokens: int = 0


# ---------------------------------------------------------------------------
# Dependency counting helpers
# ---------------------------------------------------------------------------


def _count_deps_pyproject(repo_path: str) -> int:
    """Read pyproject.toml and return len([project].dependencies)."""
    try:
        import tomllib
    except ImportError:
        # Python < 3.11 fallback — try tomli, then give up.
        try:
            import tomli as tomllib  # type: ignore[no-reassign]
        except ImportError:
            return 0

    path = os.path.join(repo_path, "pyproject.toml")
    with suppress(Exception):
        with open(path, "rb") as f:
            data = tomllib.load(f)
        deps = data.get("project", {}).get("dependencies")
        if isinstance(deps, list):
            return len(deps)
    return 0


def _count_deps_requirements(repo_path: str) -> int:
    """Count non-comment, non-blank lines in requirements.txt."""
    path = os.path.join(repo_path, "requirements.txt")
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
        count = 0
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                count += 1
        return count
    except Exception:
        return 0


def _count_deps_package_json(repo_path: str) -> int:
    """Return len(dependencies) from package.json."""
    path = os.path.join(repo_path, "package.json")
    with suppress(Exception):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        deps = data.get("dependencies")
        if isinstance(deps, dict):
            return len(deps)
    return 0


def _count_deps(repo_path: str) -> int:
    """Best-effort dependency count, trying pyproject.toml > requirements.txt > package.json."""
    for counter in (_count_deps_pyproject, _count_deps_requirements, _count_deps_package_json):
        n = counter(repo_path)
        if n > 0:
            return n
    return 0


# ---------------------------------------------------------------------------
# Repo walk helpers
# ---------------------------------------------------------------------------


def _walk_counts(repo_path: str) -> tuple[int, int]:
    """Return (folder_count, file_count) walking *repo_path*, skipping hidden/cache dirs."""
    folder_count = 0
    file_count = 0
    for dirpath, dirnames, filenames in os.walk(repo_path):
        # Prune skipped directories in-place.
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        folder_count += len(dirnames)
        file_count += len(filenames)
    return folder_count, file_count


# ---------------------------------------------------------------------------
# Token counting
# ---------------------------------------------------------------------------


def _count_instruction_tokens(
    instruction: str,
    count_tokens: Optional[Callable[[Sequence[dict]], int]],
) -> int:
    """Return instruction token count using *count_tokens* or char heuristic."""
    if count_tokens is not None:
        with suppress(Exception):
            return count_tokens([{"role": "user", "content": instruction}])
    # Char heuristic fallback (same shape as count_tokens_chars).
    if not instruction:
        return 0
    return max(1, len(instruction) // 4)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def assess_capacity(
    repo_path: str,
    instruction: str,
    budget_tokens: int,
    count_tokens: Optional[Callable[[Sequence[dict]], int]] = None,
    split_capacity_tokens: Optional[int] = None,
) -> CapacityVerdict:
    """Return an advisory :class:`CapacityVerdict` for *instruction* on *repo_path*.

    The verdict keys off an *effective* size = the instruction token estimate PLUS a
    coarse complexity contribution from the repo structure (deps/folders/files), so a
    structurally larger repo reads as a larger job (#156) — not the instruction text
    alone. ``split_capacity_tokens`` is the real "even a split can't hold it" ceiling
    (the caller passes the autosplit target = max children × per-child budget); when
    ``None`` it defaults to a coarse ``budget_tokens * 4`` proxy. Never raises, never
    blocks — all IO is wrapped with safe defaults.
    """
    # --- dependency count ---
    try:
        dep_count = _count_deps(repo_path)
    except Exception:
        dep_count = 0

    # --- folder / file counts ---
    try:
        folder_count, file_count = _walk_counts(repo_path)
    except Exception:
        folder_count = 0
        file_count = 0

    # --- instruction tokens + coarse complexity contribution ---
    instruction_tokens = _count_instruction_tokens(instruction, count_tokens)
    complexity_tokens = (
        file_count * _TOKENS_PER_FILE
        + dep_count * _TOKENS_PER_DEP
        + folder_count * _TOKENS_PER_FOLDER
    )
    effective_tokens = instruction_tokens + complexity_tokens

    # --- verdict (on the effective size, so the complexity signal counts) ---
    split_cap = (
        split_capacity_tokens
        if isinstance(split_capacity_tokens, int) and split_capacity_tokens > 0
        else int(budget_tokens * 4)
    )
    if effective_tokens < budget_tokens * 0.5:
        verdict = "fits"
    elif effective_tokens > split_cap:
        verdict = "over_split_capacity"
    else:
        verdict = "large"

    detail = (
        f"{dep_count} deps, {folder_count} folders, {file_count} files, "
        f"{instruction_tokens} instruction tokens (~{effective_tokens} effective) → {verdict}"
    )

    return CapacityVerdict(
        dep_count=dep_count,
        folder_count=folder_count,
        file_count=file_count,
        instruction_tokens=instruction_tokens,
        verdict=verdict,
        detail=detail,
        effective_tokens=effective_tokens,
    )
