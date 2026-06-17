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
        elif isinstance(node, ast.Subscript):
            # d["key"] — the index is a string constant
            idx = node.slice
            if isinstance(idx, ast.Constant) and isinstance(idx.value, str):
                keys.add(idx.value)
        elif isinstance(node, ast.Dict):
            for k in node.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    keys.add(k.value)

    return {"attribute": attrs, "dict_key": keys}


# ── public API ──────────────────────────────────────────────────────────


def detect_mirror(repo_path: str | Path, changed_files: list[str]) -> TestIntegrityReport:
    """Detect mirror signatures among *changed_files* in *repo_path*.

    Partition *changed_files* into test files and module-under-test files.
    For each (test, impl) pair, find identifiers that appear in BOTH but
    NOWHERE ELSE in the repository's other .py files.  Return one
    :class:`MirrorFinding` per (symbol, test_file, impl_file) triple.

    Advisory: never raises on a malformed/unparseable file — skip it.
    """
    repo = Path(repo_path)

    # ── partition changed files ──────────────────────────────────────
    test_files: list[str] = []
    impl_files: list[str] = []
    for f in changed_files:
        if not f.endswith(".py"):
            continue
        if _is_test_file(f):
            test_files.append(f)
        else:
            impl_files.append(f)

    if not test_files or not impl_files:
        return TestIntegrityReport()

    # ── gather identifiers from changed files ────────────────────────
    def _read(path: str) -> str:
        try:
            return (repo / path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return ""

    test_ids: dict[str, dict[str, set[str]]] = {}
    for tf in test_files:
        test_ids[tf] = _extract_identifiers(_read(tf))

    impl_ids: dict[str, dict[str, set[str]]] = {}
    for mf in impl_files:
        impl_ids[mf] = _extract_identifiers(_read(mf))

    # ── gather identifiers from ALL other .py files in the repo ─────
    other_attrs: set[str] = set()
    other_keys: set[str] = set()
    changed_set = set(changed_files)
    for py_path in repo.rglob("*.py"):
        rel = str(py_path.relative_to(repo))
        if rel in changed_set:
            continue
        try:
            source = py_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        ids = _extract_identifiers(source)
        other_attrs |= ids["attribute"]
        other_keys |= ids["dict_key"]

    # ── find mirror signatures ──────────────────────────────────────
    findings: list[MirrorFinding] = []
    for tf, tids in test_ids.items():
        for mf, mids in impl_ids.items():
            for kind in ("attribute", "dict_key"):
                shared = tids[kind] & mids[kind]
                if kind == "attribute":
                    novel = shared - other_attrs
                else:
                    novel = shared - other_keys
                for symbol in sorted(novel):
                    findings.append(
                        MirrorFinding(
                            symbol=symbol,
                            kind=kind,
                            test_file=tf,
                            impl_file=mf,
                        )
                    )

    return TestIntegrityReport(findings=findings)
