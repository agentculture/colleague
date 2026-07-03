"""Guard against 'brain' vocabulary drifting back into the codebase.

Cortex/senses arc (spec
``docs/specs/2026-07-03-colleague-drives-with-a-cortex-and-senses-it-resol.md``,
claim "ROLE VOCABULARY, NOT MORE DEEPTHINK"): the second-model plumbing
generalizes to role-based two-model config — ``cortex`` is the main loop
model, ``senses`` is the declared front/perception role — and 'brain' is
FORBIDDEN as a name anywhere, in code or in docs. The sanctioned vocabulary
is ``cortex`` / ``senses`` / ``lobes``.

This mirrors ``tests/test_gemma_staged_config.py``'s
``test_no_gemma_in_source_code`` grep-test style (a plain, whole-word,
case-insensitive scan — deliberately simple so an ordinary prose edit can't
make it flaky) and ``tests/test_doc_config_drift.py``'s drift-guard shape
(read the live surface, assert the forbidden string is absent / the
sanctioned string is present).

Scope is deliberately narrow, matching the plan's allow-list:

- ``colleague/**/*.py`` — ALL source text (code, comments, and docstrings —
  broader than the gemma test's AST-only scan, because 'brain' is forbidden
  as vocabulary everywhere in code, not just as an identifier/string literal).
- ``docs/features/*.md`` — the feature-doc surface.
- ``CLAUDE.md`` (repo root) — the architecture doc.

Deliberately NOT scanned (the allow-list from the plan): ``CHANGELOG.md``,
``docs/specs/``, ``docs/plans/``, ``.devague/`` frames, and other dated
drive-notes — those are historical record and legitimately quote the old
'brain' framing (e.g. the pre-arc resident spec, or this very spec's own
claim text stating 'brain' is forbidden going forward). Rewriting history
would be dishonest; the guard applies to the LIVE surface only.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
COLLEAGUE_ROOT = REPO_ROOT / "colleague"
FEATURES_DIR = REPO_ROOT / "docs" / "features"
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"

#: Whole-word, case-insensitive — 'brain' but not 'brainstorm' and not a
#: substring of some unrelated identifier.
_BRAIN_RE = re.compile(r"\bbrain\b", re.IGNORECASE)


def _colleague_py_files() -> list[Path]:
    return sorted(COLLEAGUE_ROOT.glob("**/*.py"))


def _feature_doc_files() -> list[Path]:
    assert FEATURES_DIR.is_dir(), f"expected feature docs dir missing: {FEATURES_DIR}"
    return sorted(FEATURES_DIR.glob("*.md"))


def _violations_in(path: Path) -> list[tuple[int, str]]:
    """Return ``[(lineno, line_text), ...]`` for every whole-word 'brain' hit."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    hits: list[tuple[int, str]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if _BRAIN_RE.search(line):
            hits.append((lineno, line.strip()))
    return hits


def _format_violations(label: str, per_file: dict[Path, list[tuple[int, str]]]) -> str:
    lines = [f"Found forbidden 'brain' vocabulary in {label}:"]
    for path, hits in per_file.items():
        for lineno, text in hits:
            lines.append(f"  {path.relative_to(REPO_ROOT)}:{lineno}: {text}")
    lines.append(
        "'brain' is forbidden as role vocabulary anywhere in colleague/ code or "
        "docs/features/ + CLAUDE.md (cortex/senses spec). Use 'cortex' (the "
        "tool-calling driving mind), 'senses' (the tools-off front door), "
        "'lobes' (the role-resolution gateway), or a neutral term like "
        "'engine'/'driving mind' instead."
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Forbidden: 'brain' must not appear in the live code/docs surface.
# ---------------------------------------------------------------------------


def test_no_brain_in_colleague_source() -> None:
    """No file under colleague/ (code, comments, or docstrings) says 'brain'."""
    py_files = _colleague_py_files()
    assert py_files, f"expected to find .py files under {COLLEAGUE_ROOT}"

    per_file = {}
    for path in py_files:
        hits = _violations_in(path)
        if hits:
            per_file[path] = hits

    assert not per_file, _format_violations("colleague/ source", per_file)


def test_no_brain_in_feature_docs() -> None:
    """No file under docs/features/ says 'brain'."""
    doc_files = _feature_doc_files()
    assert doc_files, f"expected to find .md files under {FEATURES_DIR}"

    per_file = {}
    for path in doc_files:
        hits = _violations_in(path)
        if hits:
            per_file[path] = hits

    assert not per_file, _format_violations("docs/features/", per_file)


def test_no_brain_in_claude_md() -> None:
    """CLAUDE.md (the architecture doc) says 'brain' nowhere."""
    assert CLAUDE_MD.is_file(), f"expected CLAUDE.md missing: {CLAUDE_MD}"
    hits = _violations_in(CLAUDE_MD)
    assert not hits, _format_violations("CLAUDE.md", {CLAUDE_MD: hits})


# ---------------------------------------------------------------------------
# Sanity: the guard is not vacuous — the sanctioned vocabulary is actually in
# use where the cortex/senses arc is documented (mirrors the paired
# present/absent assertion style in tests/test_doc_config_drift.py).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("term", ["cortex", "senses", "lobes"])
def test_sanctioned_vocabulary_present_in_claude_md(term: str) -> None:
    """CLAUDE.md documents the cortex/senses/lobes vocabulary (not vacuous)."""
    text = CLAUDE_MD.read_text(encoding="utf-8")
    assert term in text.lower(), f"expected CLAUDE.md to mention {term!r} (cortex/senses arc)"


@pytest.mark.parametrize("term", ["cortex", "senses", "lobes"])
def test_sanctioned_vocabulary_present_in_feature_doc(term: str) -> None:
    """The cortex-senses feature doc documents the role vocabulary (not vacuous)."""
    path = FEATURES_DIR / "cortex-senses.md"
    assert path.is_file(), f"expected feature doc missing: {path}"
    text = path.read_text(encoding="utf-8")
    assert term in text.lower(), f"expected {path.name} to mention {term!r}"


def test_historical_docs_are_not_scanned_by_this_guard() -> None:
    """Documents the deliberate allow-list: this guard never touches history.

    docs/specs/, docs/plans/, .devague/, and CHANGELOG.md legitimately quote
    the historical 'brain' framing (including this very spec's own claim text
    forbidding it going forward) and a dated drive-note is a point-in-time
    record, not a live surface. This test exists so the allow-list is an
    explicit, intentional decision rather than an accidental gap discovered
    later.
    """
    scanned_roots = {COLLEAGUE_ROOT, FEATURES_DIR, CLAUDE_MD}
    excluded = {
        REPO_ROOT / "CHANGELOG.md",
        REPO_ROOT / "docs" / "specs",
        REPO_ROOT / "docs" / "plans",
        REPO_ROOT / ".devague",
    }
    assert scanned_roots.isdisjoint(excluded)
