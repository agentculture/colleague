"""Repo-confined text search (grep) and file-pattern search (glob).

adapted-from: qwen-code packages/core/src/tools/ripGrep.ts, tools/grep.ts,
tools/glob.ts and config.ts:9280-9315 (backend selection).

qwen-code offers two Grep backends behind one tool name: a ``ripgrep``-backed
fast path when the ``rg`` binary is available (``ripGrep.ts``), and a pure
TypeScript walker fallback otherwise (``grep.ts``); ``config.ts`` (around line
9295) probes for ``rg`` once at tool-registration time and wires whichever
backend applies. :func:`grep_search` reproduces that same shape in Python:
:func:`_grep_ripgrep` shells out to an operator-installed ``rg`` (via
``shutil.which``) when present, :func:`_grep_stdlib` walks the tree by hand
otherwise, and both are required to agree byte-for-byte on the sorted result
list — the backend is an implementation detail, never something the caller
observes. :func:`glob` reproduces ``tools/glob.ts``'s "match a pattern, return
matches sorted by recency" contract without qwen-code's ``glob`` npm
dependency (stdlib only, decision: no brace-expansion — see the module
docstring below for the accepted gap).

Confinement (honesty condition h5): both entry points resolve the caller's
``path``/``pattern`` against ``root`` the same way ``colleague/tools.py``'s
``ToolExecutor._safe_path`` does (``Path.resolve()`` then verify the result is
``root`` itself or has ``root`` in its parents) and raise the identical
:class:`colleague.tools.ToolError` shape a confinement refusal in
``read_file`` would. ``tools.py`` is not edited by this module — a plain
:func:`colleague.tools.ToolError` import gives byte-identical error text/type
without duplicating the resolve()-based check as a bound method; this module
takes ``root: Path`` explicitly instead of being a method on ``ToolExecutor``
(the confinement condition is the same, factored to work standalone).

Two directories are excluded from both search entry points by default:
``.git`` (git's own admin tree) and ``.colleague/worktrees`` (the live
subagent worktree tree — mid-flight subagent writes should not leak into a
parent's search results). ``.colleague/neighbours`` (the read-only clone tree,
see ``colleague/neighbours.py``) is deliberately left searchable: those clones
exist to be read.

Registration into ``SCHEMAS``/``curate_schemas`` is a separate task (t13) —
this module is the search backend only, with no tool-schema or
``ToolExecutor`` wiring of its own.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess  # nosec B404 - ripgrep search backend, operator-installed CLI
from dataclasses import dataclass
from pathlib import Path

from colleague.tools import ToolError

#: Directory names pruned from every walk, regardless of where they occur.
_ALWAYS_EXCLUDED_DIR_NAMES = {".git"}
_ALWAYS_EXCLUDED_DIR_NAMES_GLOB = ".git"

#: A single relative path (root-anchored) pruned from every walk. Unlike
#: ``_ALWAYS_EXCLUDED_DIR_NAMES`` this only excludes the one canonical
#: location, not every directory that happens to share the name.
_WORKTREES_RELPATH = ".colleague/worktrees"

#: Default cap on results returned by grep_search / glob — mirrors qwen-code's
#: own MAX_FILE_COUNT-style ceilings (ripGrep.ts / glob.ts), sized generously
#: for a single tool-call result rather than the whole match set.
DEFAULT_MAX_RESULTS = 200

#: Ripgrep's search timeout — mirrors tools.py's _COMMAND_TIMEOUT_SECONDS so a
#: pathological rg invocation cannot stall the loop indefinitely.
_RIPGREP_TIMEOUT_SECONDS = 300


@dataclass(frozen=True)
class SearchMatch:
    """One grep_search hit: a POSIX-relative path, its 1-based line, and text."""

    path: str
    line: int
    text: str

    def as_tuple(self) -> tuple[str, int, str]:
        return (self.path, self.line, self.text)


# ---------------------------------------------------------------------------
# Confinement — mirrors ToolExecutor._safe_path (colleague/tools.py:844-849)
# ---------------------------------------------------------------------------


def confine(root: Path, rel: str) -> Path:
    """Resolve *rel* under *root*, refusing anything that escapes it.

    Same algorithm as ``ToolExecutor._safe_path``: resolve (following
    symlinks) then require the candidate to equal ``root`` or have ``root``
    among its parents. Raises the identical :class:`ToolError` shape
    ``read_file`` raises on an escape attempt, so a caller sees one error
    contract across every repo-confined tool.
    """
    candidate = (root / rel).resolve()
    if candidate != root and root not in candidate.parents:
        raise ToolError(f"path '{rel}' escapes the repo root")
    return candidate


def _refuse_pattern_escape(pattern: str) -> None:
    """Refuse a glob/grep pattern containing a literal ``..`` path segment.

    ``confine()`` catches an escaping ``path`` argument (including via
    symlink, since it resolves). A *pattern* like ``"../../etc/*"`` never
    passes through ``confine()`` on its own — nothing resolves it as a path,
    it is only ever compared against relative paths already enumerated from
    inside the confined tree, so a hostile pattern with a real path
    underneath it would just fail to match anything. To keep the error
    behaviour consistent (a refusal, not a silent empty result) any ``..``
    path component is rejected outright, using the same error shape.
    """
    parts = pattern.replace("\\", "/").split("/")
    if any(part == ".." for part in parts):
        raise ToolError(f"pattern '{pattern}' escapes the repo root")


def _is_contained(path: Path, root: Path) -> bool:
    """True when *path* (already resolved) sits under *root*."""
    try:
        resolved = path.resolve()
    except OSError:
        return False
    return resolved == root or root in resolved.parents


# ---------------------------------------------------------------------------
# Shared directory pruning (both grep backends + glob)
# ---------------------------------------------------------------------------


def _prune_dirnames(root: Path, current_dir: Path, dirnames: list[str]) -> None:
    """Mutate *dirnames* in place, removing excluded subdirectories.

    Called from an ``os.walk`` loop — mutating the ``dirnames`` list ``walk``
    handed back is how ``os.walk`` itself expects traversal pruning to happen.
    """
    rel_current = current_dir.relative_to(root).as_posix()
    kept = []
    for name in dirnames:
        if name in _ALWAYS_EXCLUDED_DIR_NAMES:
            continue
        child_rel = name if rel_current == "." else f"{rel_current}/{name}"
        if child_rel == _WORKTREES_RELPATH:
            continue
        kept.append(name)
    dirnames[:] = kept


def _iter_files(root: Path, base: Path) -> list[Path]:
    """Every regular file under *base* (which must already be confined),
    excluding ``.git`` and the ``.colleague/worktrees`` tree, and skipping
    any entry whose resolved target escapes *root* (a symlink pointing
    outside the repo)."""
    files: list[Path] = []
    if base.is_file():
        return [base] if _is_contained(base, root) else []
    for dirpath, dirnames, filenames in os.walk(base):
        current_dir = Path(dirpath)
        dirnames.sort()
        _prune_dirnames(root, current_dir, dirnames)
        for filename in sorted(filenames):
            candidate = current_dir / filename
            if candidate.is_symlink() and not _is_contained(candidate, root):
                continue
            files.append(candidate)
    return files


# ---------------------------------------------------------------------------
# glob-pattern → regex translation (stdlib only — no brace expansion)
# ---------------------------------------------------------------------------


def _translate_glob(pattern: str) -> re.Pattern[str]:
    """Translate a POSIX-style glob (``*``, ``?``, ``[seq]``, ``**``) into a
    compiled regex matched against a forward-slash relative path.

    Deviation from qwen-code's ``glob.ts`` (deliberate, stated explicitly):
    that implementation depends on the ``glob`` npm package, which also
    supports brace expansion (``*.{ts,tsx}``) — brace groups are NOT
    supported here (stdlib only, per repo convention). ``**`` IS supported,
    matching zero or more path segments.
    """
    i, n = 0, len(pattern)
    out: list[str] = []
    while i < n:
        c = pattern[i]
        if c == "*":
            if i + 1 < n and pattern[i + 1] == "*":
                j = i + 2
                if j < n and pattern[j] == "/":
                    out.append("(?:.*/)?")
                    i = j + 1
                else:
                    out.append(".*")
                    i = j
            else:
                out.append("[^/]*")
                i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        elif c == "[":
            j = i + 1
            if j < n and pattern[j] == "!":
                j += 1
            j += 1
            while j < n and pattern[j] != "]":
                j += 1
            if j >= n:
                out.append(re.escape(c))
                i += 1
            else:
                body = pattern[i + 1 : j]
                if body.startswith("!"):
                    body = "^" + body[1:]
                out.append(f"[{body}]")
                i = j + 1
        else:
            out.append(re.escape(c))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def _fnmatch_glob(relpath: str, glob_pattern: str) -> bool:
    """Match *relpath* (posix, relative to the search base) against a basename
    glob, tried both against the basename alone and the full relative path —
    mirrors ``rg --glob``'s "no slash means match the basename anywhere"
    behaviour for the common case (e.g. ``"*.py"``)."""
    if "/" in glob_pattern:
        return bool(_translate_glob(glob_pattern).match(relpath))
    basename = relpath.rsplit("/", 1)[-1]
    return bool(_translate_glob(glob_pattern).match(basename))


# ---------------------------------------------------------------------------
# grep_search
# ---------------------------------------------------------------------------


def _use_ripgrep() -> bool:
    """Backend-selection probe — mirrors config.ts:9280-9315's ``rg`` check:
    a shell-availability probe of the operator-installed ``rg`` binary,
    resolved once per call (no persistent state)."""
    return shutil.which("rg") is not None


def _grep_stdlib(
    root: Path,
    base: Path,
    pattern: re.Pattern[str],
    glob_pattern: str | None,
) -> list[SearchMatch]:
    matches: list[SearchMatch] = []
    for file_path in _iter_files(root, base):
        rel = file_path.relative_to(root).as_posix()
        if glob_pattern and not _fnmatch_glob(rel, glob_pattern):
            continue
        try:
            text = file_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                matches.append(SearchMatch(rel, line_no, line))
    return matches


def _grep_ripgrep(
    root: Path,
    base: Path,
    raw_pattern: str,
    glob_pattern: str | None,
) -> list[SearchMatch]:
    args = [
        "rg",
        "--line-number",
        "--no-heading",
        "--with-filename",
        "--ignore-case",
        "--no-ignore-vcs",
        "--hidden",
        "--path-separator",
        "/",
        "--glob",
        f"!{_ALWAYS_EXCLUDED_DIR_NAMES_GLOB}",
        "--glob",
        f"!{_WORKTREES_RELPATH}",
        "--regexp",
        raw_pattern,
    ]
    if glob_pattern:
        args.extend(["--glob", glob_pattern])
    args.append(str(base))
    proc = subprocess.run(  # nosec B603 B607 - fixed 'rg' argv, no shell
        args,
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=_RIPGREP_TIMEOUT_SECONDS,
    )
    # rg exits 1 for "no matches" (not an error) and 2 for a real failure.
    if proc.returncode not in (0, 1):
        raise ToolError(f"rg failed (exit {proc.returncode}): {proc.stderr.strip()}")

    matches: list[SearchMatch] = []
    for raw_line in proc.stdout.splitlines():
        if not raw_line:
            continue
        parts = raw_line.split(":", 2)
        if len(parts) != 3:
            continue
        file_field, line_field, content = parts
        if not line_field.isdigit():
            continue
        file_path = Path(file_field)
        if not file_path.is_absolute():
            file_path = root / file_path
        try:
            rel = file_path.resolve().relative_to(root).as_posix()
        except ValueError:
            continue
        matches.append(SearchMatch(rel, int(line_field), content))
    return matches


def grep_search(
    root: Path | str,
    pattern: str,
    *,
    path: str | None = None,
    glob: str | None = None,
    max_results: int = DEFAULT_MAX_RESULTS,
) -> list[SearchMatch]:
    """Search file contents under *root* for regex *pattern* (case-insensitive).

    Uses the operator-installed ``rg`` when it is on ``PATH`` (fast path,
    ``_grep_ripgrep``), else walks the tree by hand (``_grep_stdlib``,
    stdlib-only). Both backends are required to return the identical sorted
    match list on the same fixture tree — the caller never sees which one
    ran. Results are sorted by ``(path, line)`` for determinism, then
    truncated to *max_results*.

    ``path`` (optional) narrows the search to a subdirectory/file, confined
    under *root* exactly like ``read_file`` (escape — including via symlink —
    raises :class:`ToolError`). ``glob`` (optional) filters which files are
    searched by a basename or path glob (``"*.py"``, ``"src/**/*.ts"``);
    an escaping ``glob`` (a literal ``..`` segment) is refused the same way.
    """
    root = Path(root).resolve()
    base = confine(root, path or ".")
    if glob:
        _refuse_pattern_escape(glob)

    try:
        compiled = re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        raise ToolError(f"invalid regular expression '{pattern}': {exc}") from exc

    if _use_ripgrep():
        try:
            matches = _grep_ripgrep(root, base, pattern, glob)
        except FileNotFoundError:
            # rg vanished between the which() probe and the call (race) —
            # degrade to the stdlib walker rather than fail the search.
            matches = _grep_stdlib(root, base, compiled, glob)
    else:
        matches = _grep_stdlib(root, base, compiled, glob)

    matches.sort(key=SearchMatch.as_tuple)
    return matches[:max_results]


# ---------------------------------------------------------------------------
# glob
# ---------------------------------------------------------------------------


def glob(
    root: Path | str,
    pattern: str,
    *,
    path: str | None = None,
    max_results: int = DEFAULT_MAX_RESULTS,
) -> list[str]:
    """Return files under *root* matching glob *pattern*, newest-mtime first.

    ``path`` (optional) narrows the search to a subdirectory, confined under
    *root* the same way ``read_file`` is (escape — including via symlink —
    raises :class:`ToolError`). A *pattern* containing a literal ``..``
    segment is refused the same way (see :func:`_refuse_pattern_escape`).

    ``.git`` and ``.colleague/worktrees`` are excluded from every walk;
    ``.colleague/neighbours`` (read-only clone source) is not — neighbour
    clones are meant to be searched, just never written to.
    """
    root = Path(root).resolve()
    base = confine(root, path or ".")
    _refuse_pattern_escape(pattern)

    matched: list[tuple[str, float]] = []
    for file_path in _iter_files(root, base):
        rel = file_path.relative_to(root).as_posix()
        if not _fnmatch_glob(rel, pattern):
            continue
        try:
            mtime = file_path.stat().st_mtime
        except OSError:
            continue
        matched.append((rel, mtime))

    matched.sort(key=lambda item: (-item[1], item[0]))
    return [rel for rel, _mtime in matched[:max_results]]
