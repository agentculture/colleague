"""Affected-tests pre-handoff gate — bounded-depth transitive reverse-import
selection + pytest execution.

Sibling to :mod:`colleague.lint` and :mod:`colleague.testintegrity` in
structure: pure stdlib, advisory + non-blocking, returns an
:class:`AffectedTestsReport` (or ``None``), never raises.  Strict no-op when
disabled or when nothing is affected.

Selection
---------
Build the repo's module import graph with :mod:`ast`, collecting **all** imports
— including *function-local / lazy* ones (``ast.walk`` over the whole tree, not
just the module body).  This matters: colleague registers every CLI command via
a lazy ``from colleague.cli._commands import <cmd>`` **inside** ``register()``, so
a module-level-only graph would dead-end at the ``colleague.cli`` hub and miss
every transitively-affected test.  For each test file we compute the modules
reachable within ``depth`` hops of its import closure and select it iff a changed
module is in that set.  The default depth (``_DEFAULT_DEPTH`` = 3) reaches the
#210/t2 motivating case: ``tests/test_cli_plan.py`` imports only
``colleague.cli`` but transitively reaches the changed
``colleague.plan.cli_driver`` at depth 3
(``test_cli_plan → colleague.cli → (lazy) _commands.plan → cli_driver``).

Because the CLI hub fans out widely, the selected set is **capped**
(``_DEFAULT_MAX_FILES``); on overflow the report records ``total`` vs the capped
``selected`` honestly (``capped=True``) — never a silent truncation.

Execution
---------
Run ``pytest`` on the selected files via :mod:`subprocess`.  A missing/unrunnable
pytest degrades to ``status='skipped'`` with a reason — never a traceback and
never a blocked handoff.  Zero runtime dependencies beyond the stdlib; this is a
sanctioned ``subprocess`` consumer (see ``tests/test_boundary.py``).
"""

from __future__ import annotations

import ast
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# Default bounded depth for the transitive reverse-import closure.  Must reach
# the #210/t2 motivating case (a changed module 3 import-edges from a sibling
# test via a lazy CLI-register import), so the floor is 3.  Tunable by the caller.
_DEFAULT_DEPTH = 3

# Cap on the number of selected test files.  The CLI-hub transitive fan-out can
# make a leaf change reach many tests; the cap bounds handoff time.  Overflow is
# reported honestly (capped=True), never silently dropped.
_DEFAULT_MAX_FILES = 20

# pytest subprocess ceiling — a hung test run must never block the handoff.
_PYTEST_TIMEOUT = 600

# Vendored / generated trees pruned from the repo scan.
_SKIP_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        ".env",
        "node_modules",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        "build",
        "dist",
        "site-packages",
        ".colleague",
        ".devague",
    }
)

# ── report ──────────────────────────────────────────────────────────────


@dataclass
class AffectedTestsReport:
    """Outcome of the affected-tests gate.

    ``status`` is one of ``"passed"`` / ``"failed"`` / ``"skipped"``.  ``selected``
    is the (possibly capped) list of test files that were run; ``total`` is how
    many matched before the cap (``capped`` is True when ``total`` exceeded the
    cap).  ``passed`` / ``failed`` are pytest counts (best-effort, parsed from the
    summary line; ``None`` when not run).  ``reason`` carries the skip cause.
    """

    status: str
    selected: list[str] = field(default_factory=list)
    total: int = 0
    capped: bool = False
    passed: Optional[int] = None
    failed: Optional[int] = None
    reason: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "selected": list(self.selected),
            "total": self.total,
            "capped": self.capped,
            "passed": self.passed,
            "failed": self.failed,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AffectedTestsReport":
        return cls(
            status=str(data.get("status", "skipped")),
            selected=list(data.get("selected", [])),
            total=int(data.get("total", 0)),
            capped=bool(data.get("capped", False)),
            passed=data.get("passed"),
            failed=data.get("failed"),
            reason=data.get("reason"),
        )

    def summary_line(self) -> str:
        """One-line human summary for stderr."""
        cap = f" (capped from {self.total})" if self.capped else ""
        if self.status == "skipped":
            return f"affected-tests: skipped — {self.reason or 'unavailable'}"
        counts = []
        if self.passed is not None:
            counts.append(f"{self.passed} passed")
        if self.failed is not None:
            counts.append(f"{self.failed} failed")
        tail = ", ".join(counts) or self.status
        return f"affected-tests: {self.status} — {len(self.selected)} file(s){cap}: {tail}"


# ── repo module graph ───────────────────────────────────────────────────


def _iter_repo_py(repo: Path) -> list[Path]:
    """Yield repo-owned ``*.py`` files, skipping vendored/generated trees."""
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(repo, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        base = Path(dirpath)
        for name in filenames:
            entry = base / name
            if name.endswith(".py") and not entry.is_symlink():
                found.append(entry)
    return found


def _module_name(rel: str) -> str:
    """Map a repo-relative ``*.py`` path to its dotted module name.

    ``colleague/plan/cli_driver.py`` → ``colleague.plan.cli_driver``;
    ``colleague/cli/__init__.py`` → ``colleague.cli`` (a package).
    """
    p = Path(rel)
    parts = list(p.parts)
    parts[-1] = p.stem  # drop .py
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _is_package_path(rel: str) -> bool:
    return Path(rel).name == "__init__.py"


def _is_test_file(rel: str) -> bool:
    """True for a pytest-discoverable test file (``test_*.py`` / ``*_test.py``).

    Deliberately does NOT treat every file under a ``tests/`` directory as a test:
    pytest only collects the ``test_*`` / ``_test`` naming, so a ``conftest.py`` or
    a shared fixture helper under ``tests/`` must not be selected and handed to
    pytest (it would be wasteful noise against the file cap).
    """
    base = Path(rel).name
    return base.endswith(".py") and (base.startswith("test_") or base.endswith("_test.py"))


def _package_parts(current_module: str, is_package: bool) -> list[str]:
    """The package a relative import is resolved against: the module itself when
    it is a package (``__init__``), else its parent."""
    parts = current_module.split(".") if current_module else []
    if not is_package and parts:
        parts = parts[:-1]
    return parts


def _import_targets(node: ast.Import) -> set[str]:
    """Candidate module names for an ``import a.b.c`` node (full + top-level)."""
    out: set[str] = set()
    for alias in node.names:
        out.add(alias.name)
        out.add(alias.name.split(".")[0])
    return out


def _resolve_from_module(node: ast.ImportFrom, pkg_parts: list[str]) -> str:
    """The imported module for a ``from … import …`` node, resolving a relative
    ``level`` against *pkg_parts*."""
    if not node.level:
        return node.module or ""
    base = pkg_parts[: len(pkg_parts) - (node.level - 1)] if node.level > 1 else pkg_parts
    prefix = ".".join(base)
    return f"{prefix}.{node.module}" if node.module else prefix


def _import_from_targets(node: ast.ImportFrom, pkg_parts: list[str]) -> set[str]:
    """Candidate module names for a ``from pkg.mod import name`` node — both
    ``pkg.mod`` and each ``pkg.mod.name`` (the caller keeps the real ones)."""
    mod = _resolve_from_module(node, pkg_parts)
    if not mod:
        return set()
    out = {mod}
    for alias in node.names:
        out.add(f"{mod}.{alias.name}")
    return out


def _candidate_imports(source: str, current_module: str, is_package: bool) -> set[str]:
    """Return candidate imported module names from *source* (ALL imports).

    Walks the **whole** tree (``ast.walk``) so function-local / lazy imports are
    captured.  Relative imports (``level > 0``) are resolved against the current
    module's package.  Unparseable source yields an empty set.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        return set()
    pkg_parts = _package_parts(current_module, is_package)
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out |= _import_targets(node)
        elif isinstance(node, ast.ImportFrom):
            out |= _import_from_targets(node, pkg_parts)
    return out


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def build_import_graph(repo: Path) -> tuple[dict[str, set[str]], dict[str, str]]:
    """Build the forward import graph for *repo*.

    Returns ``(graph, module_to_rel)`` where ``graph`` maps a module name to the
    set of repo modules it imports (edges to non-repo modules are dropped), and
    ``module_to_rel`` maps a module name to its repo-relative path.
    """
    rel_by_module: dict[str, str] = {}
    package_flags: dict[str, bool] = {}
    sources: dict[str, str] = {}
    for path in _iter_repo_py(repo):
        rel = str(path.relative_to(repo))
        mod = _module_name(rel)
        rel_by_module[mod] = rel
        package_flags[mod] = _is_package_path(rel)
        sources[mod] = _read(path)

    known = set(rel_by_module)
    graph: dict[str, set[str]] = {}
    for mod, source in sources.items():
        edges: set[str] = set()
        for cand in _candidate_imports(source, mod, package_flags.get(mod, False)):
            if cand in known and cand != mod:
                edges.add(cand)
        graph[mod] = edges
    return graph, rel_by_module


# ── selection ───────────────────────────────────────────────────────────


def _step_frontier(
    graph: dict[str, set[str]], frontier: set[str], targets: set[str], seen: set[str]
) -> Optional[set[str]]:
    """Expand one BFS layer. Returns the next frontier, or ``None`` if a target
    module was reached this layer."""
    nxt: set[str] = set()
    for node in frontier:
        for neigh in graph.get(node, ()):  # noqa: SIM118
            if neigh in targets:
                return None
            if neigh not in seen:
                seen.add(neigh)
                nxt.add(neigh)
    return nxt


def _reaches_within(graph: dict[str, set[str]], start: str, targets: set[str], depth: int) -> bool:
    """True iff any *targets* module is reachable from *start* within *depth* hops."""
    if start in targets:
        return True
    seen = {start}
    frontier = {start}
    for _ in range(max(0, depth)):
        nxt = _step_frontier(graph, frontier, targets, seen)
        if nxt is None:
            return True
        if not nxt:
            break
        frontier = nxt
    return False


def select_affected_tests(
    repo_path: str | Path,
    changed_files: list[str],
    *,
    depth: int = _DEFAULT_DEPTH,
    max_files: int = _DEFAULT_MAX_FILES,
) -> tuple[list[str], int, bool]:
    """Select test files whose bounded-depth transitive import closure reaches a
    changed module.

    Returns ``(selected, total, capped)``: ``selected`` is sorted and capped at
    ``max_files``; ``total`` is the count before the cap; ``capped`` is True when
    ``total`` exceeded ``max_files``.  Never raises.
    """
    repo = Path(repo_path)
    changed_py = [f for f in changed_files if f.endswith(".py")]
    if not changed_py:
        return [], 0, False

    graph, rel_by_module = build_import_graph(repo)
    rel_to_module = {rel: mod for mod, rel in rel_by_module.items()}

    # Target modules = the changed files that map to a known repo module.
    targets = {rel_to_module[f] for f in changed_py if f in rel_to_module}
    if not targets:
        return [], 0, False

    matched: set[str] = set()
    # A changed test file is always its own affected test.
    for f in changed_py:
        if _is_test_file(f) and (repo / f).is_file():
            matched.add(f)
    # Reverse reachability: every test module that reaches a target within depth.
    for mod, rel in rel_by_module.items():
        if not _is_test_file(rel):
            continue
        if rel in matched:
            continue
        if _reaches_within(graph, mod, targets, depth):
            matched.add(rel)

    ordered = sorted(matched)
    total = len(ordered)
    capped = total > max_files
    return ordered[:max_files], total, capped


# ── execution ───────────────────────────────────────────────────────────


def _parse_counts(text: str) -> tuple[Optional[int], Optional[int]]:
    """Best-effort parse of pytest's summary line → (passed, failed+errors).

    Regex-free token scan (a ``<n> passed`` / ``<n> failed`` / ``<n> error[s]``
    pair in pytest's own bounded summary output), so there is no backtracking
    surface at all.
    """
    passed = failed = None
    for line in text.splitlines():
        words = line.replace(",", " ").split()
        for i, word in enumerate(words):
            if i == 0 or not words[i - 1].isdigit():
                continue
            count = int(words[i - 1])
            if word == "passed":
                passed = count
            elif word in ("failed", "error", "errors"):
                failed = (failed or 0) + count
    return passed, failed


def run_affected_tests(
    repo_path: str | Path,
    changed_files: list[str],
    *,
    depth: int = _DEFAULT_DEPTH,
    max_files: int = _DEFAULT_MAX_FILES,
    pytest_args: Optional[list[str]] = None,
) -> Optional[AffectedTestsReport]:
    """Run pytest on the affected tests for *changed_files*.

    When *pytest_args* is given it is used as the pytest selection verbatim (the
    ``--test`` override); otherwise the bounded-depth transitive selection is
    used.  Returns ``None`` when nothing is selected (a strict no-op).  A missing
    or unrunnable pytest degrades to ``status='skipped'`` — never raises, never
    blocks the handoff.
    """
    if pytest_args is not None:
        selected, total, capped = list(pytest_args), len(pytest_args), False
    else:
        selected, total, capped = select_affected_tests(
            repo_path, changed_files, depth=depth, max_files=max_files
        )
    if not selected:
        return None

    try:
        proc = subprocess.run(
            ["pytest", "-p", "no:cacheprovider", "-q", *selected],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            check=False,
            timeout=_PYTEST_TIMEOUT,
        )
    except FileNotFoundError:
        return AffectedTestsReport(
            status="skipped",
            selected=selected,
            total=total,
            capped=capped,
            reason="pytest not found",
        )
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return AffectedTestsReport(
            status="skipped",
            selected=selected,
            total=total,
            capped=capped,
            reason=f"pytest unrunnable: {type(exc).__name__}",
        )

    passed, failed = _parse_counts((proc.stdout or "") + (proc.stderr or ""))
    # returncode 5 = "no tests collected"; treat as skipped, not a failure.
    if proc.returncode == 5:
        return AffectedTestsReport(
            status="skipped",
            selected=selected,
            total=total,
            capped=capped,
            passed=passed,
            failed=failed,
            reason="no tests collected",
        )
    status = "passed" if proc.returncode == 0 else "failed"
    return AffectedTestsReport(
        status=status,
        selected=selected,
        total=total,
        capped=capped,
        passed=passed,
        failed=failed,
    )
