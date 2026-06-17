"""Test-integrity mirror-detection heuristic — pure stdlib, no new deps.

Detects the *mirror signature*: an identifier (attribute access or
string-literal dict key) that appears in BOTH a changed test file and a
changed module-under-test, yet is found NOWHERE ELSE in the repository.
This is the mechanical signal that a test merely mirrors the
implementation's own (possibly wrong) assumption.

Sibling to :mod:`colleague.lint` in structure: dataclass report,
``to_dict`` / ``from_dict`` round-trip, best-effort (never raises).
"""

from __future__ import annotations

import ast
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class MirrorFinding:
    """One mirror-signature finding.

    Fields
    ------
    symbol:
        The identifier (attribute name or dict-key string literal).
    kind:
        Either ``"attribute"`` or ``"dict_key"``.
    test_file:
        The changed test file in which the symbol appears.
    impl_file:
        The changed module-under-test in which the symbol appears.
    """

    symbol: str
    kind: str
    test_file: str
    impl_file: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "kind": self.kind,
            "test_file": self.test_file,
            "impl_file": self.impl_file,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MirrorFinding":
        return cls(
            symbol=str(data["symbol"]),
            kind=str(data["kind"]),
            test_file=str(data["test_file"]),
            impl_file=str(data["impl_file"]),
        )


@dataclass
class TestIntegrityReport:
    """Report from the test-integrity mirror-detection heuristic.

    ``findings`` is a list of :class:`MirrorFinding` objects, one per
    (symbol, test_file, impl_file) triple that exhibits the mirror
    signature.  Empty when no suspicious mirroring was detected.
    """

    # Opt out of pytest collection: the ``Test`` prefix makes pytest try to
    # collect this dataclass as a test class (it cannot, it has __init__).
    __test__ = False

    findings: list[MirrorFinding] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "findings": [f.to_dict() for f in self.findings],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TestIntegrityReport":
        return cls(
            findings=[MirrorFinding.from_dict(f) for f in data.get("findings", [])],
        )


# ── identifier extraction ───────────────────────────────────────────────


def _is_test_file(name: str) -> bool:
    """Return True if *name* looks like a test file.

    Matches ``test_*.py``, ``*_test.py``, or anything under a ``tests/``
    directory.
    """
    base = Path(name).name
    if base.startswith("test_") and base.endswith(".py"):
        return True
    if base.endswith("_test.py"):
        return True
    if Path(name).parts and "tests" in Path(name).parts:
        return True
    return False


def _string_dict_keys(node: ast.AST) -> set[str]:
    """String-literal dict keys introduced by *node*.

    Handles both subscript access (``d["key"]``) and dict literals
    (``{"key": ...}``); any non-string key is ignored. Returns an empty set for
    any other node type.
    """
    if isinstance(node, ast.Subscript):
        idx = node.slice
        if isinstance(idx, ast.Constant) and isinstance(idx.value, str):
            return {idx.value}
        return set()
    if isinstance(node, ast.Dict):
        return {
            k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)
        }
    return set()


def _extract_identifiers(source: str) -> dict[str, set[str]]:
    """Extract candidate identifiers from *source*.

    Returns a mapping of kind (``"attribute"`` or ``"dict_key"``) to the
    set of identifier strings found in the source.  Unparseable source
    yields empty sets (never raises).
    """
    attrs: set[str] = set()
    keys: set[str] = set()
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        return {"attribute": set(), "dict_key": set()}

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            attrs.add(node.attr)
        else:
            keys |= _string_dict_keys(node)

    return {"attribute": attrs, "dict_key": keys}


#: Directory names skipped when scanning the repo for the "nowhere else" check.
#: Vendored / generated / VCS trees are not the repo's own source — including
#: them would both slow the gate (a .venv has thousands of files) and mask a
#: novel symbol that happens to appear in a third-party package.
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


def _iter_repo_py(repo: Path) -> "list[Path]":
    """Yield repo-owned ``*.py`` files, skipping vendored/generated/VCS trees.

    Walks ``repo`` via :func:`os.walk` with ``followlinks=False``, pruning any
    directory in :data:`_SKIP_DIRS` (in place, so ``os.walk`` never descends into
    it) so the "nowhere else in the repo" scan stays fast and considers only
    first-party source.

    Symlink-safe (Qodo PR #211): ``followlinks=False`` means a symlinked directory
    is never descended into — so a ``repo/loop -> repo`` cycle cannot hang the
    post-loop gate and a symlink into a huge external tree (e.g. ``/usr``) cannot
    balloon the scan, with no manual stack or visited-set needed. Symlinked
    ``*.py`` files are skipped too, keeping the scan confined to the repo's own
    source.
    """
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(repo, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        base = Path(dirpath)
        for name in filenames:
            entry = base / name
            if name.endswith(".py") and not entry.is_symlink():
                found.append(entry)
    return found


# ── public API ──────────────────────────────────────────────────────────


def _partition_changed_files(changed_files: list[str]) -> tuple[list[str], list[str]]:
    """Split *changed_files* into (test files, module-under-test files).

    Non-``.py`` paths are ignored.
    """
    test_files: list[str] = []
    impl_files: list[str] = []
    for f in changed_files:
        if not f.endswith(".py"):
            continue
        (test_files if _is_test_file(f) else impl_files).append(f)
    return test_files, impl_files


def _read_file(repo: Path, rel: str) -> str:
    """Read *rel* under *repo*; return ``""`` on any read/decode error."""
    try:
        return (repo / rel).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _gather_other_identifiers(repo: Path, changed_set: set[str]) -> tuple[set[str], set[str]]:
    """Union of (attribute, dict_key) identifiers across all OTHER repo ``.py`` files.

    "Other" = every repo-owned source file not in *changed_set*; this is the
    "nowhere else" universe a co-introduced symbol is checked against.
    """
    other_attrs: set[str] = set()
    other_keys: set[str] = set()
    for py_path in _iter_repo_py(repo):
        rel = str(py_path.relative_to(repo))
        if rel in changed_set:
            continue
        ids = _extract_identifiers(_read_file(repo, rel))
        other_attrs |= ids["attribute"]
        other_keys |= ids["dict_key"]
    return other_attrs, other_keys


def _find_mirrors(
    test_ids: dict[str, dict[str, set[str]]],
    impl_ids: dict[str, dict[str, set[str]]],
    other: dict[str, set[str]],
) -> list[MirrorFinding]:
    """Build a finding per (symbol, test_file, impl_file) exhibiting the mirror signature.

    A symbol qualifies when it appears in BOTH a changed test file and a changed
    impl file (per kind) yet is absent from *other* (the rest of the repo).
    """
    findings: list[MirrorFinding] = []
    for tf, tids in test_ids.items():
        for mf, mids in impl_ids.items():
            for kind in ("attribute", "dict_key"):
                novel = (tids[kind] & mids[kind]) - other[kind]
                for symbol in sorted(novel):
                    findings.append(
                        MirrorFinding(symbol=symbol, kind=kind, test_file=tf, impl_file=mf)
                    )
    return findings


def detect_mirror(repo_path: str | Path, changed_files: list[str]) -> TestIntegrityReport:
    """Detect mirror signatures among *changed_files* in *repo_path*.

    Partition *changed_files* into test files and module-under-test files.
    For each (test, impl) pair, find identifiers that appear in BOTH but
    NOWHERE ELSE in the repository's other .py files.  Return one
    :class:`MirrorFinding` per (symbol, test_file, impl_file) triple.

    Advisory: never raises on a malformed/unparseable file — skip it.
    """
    repo = Path(repo_path)
    test_files, impl_files = _partition_changed_files(changed_files)
    if not test_files or not impl_files:
        return TestIntegrityReport()

    test_ids = {tf: _extract_identifiers(_read_file(repo, tf)) for tf in test_files}
    impl_ids = {mf: _extract_identifiers(_read_file(repo, mf)) for mf in impl_files}

    other_attrs, other_keys = _gather_other_identifiers(repo, set(changed_files))
    findings = _find_mirrors(test_ids, impl_ids, {"attribute": other_attrs, "dict_key": other_keys})
    return TestIntegrityReport(findings=findings)
