"""Tests for :mod:`colleague.selfknowledge` — the self-knowledge classifier and guide index.

Mirrors the classifier test style of :mod:`tests.test_frontdoor`: table-driven
cases for :func:`classify_selfknowledge` and :func:`build_guide_index` tests
using ``tmp_path`` repos.
"""

from __future__ import annotations

import pytest

from colleague.selfknowledge import build_guide_index, classify_selfknowledge

# ── Self-knowledge positive cases (should return True) ─────────────────────

SELFKNOWLEDGE_TRUE_CASES: tuple[str, ...] = (
    # Identity questions.
    "what model are you",
    "what model is this",
    "which model is this",
    "what are you",
    "who are you",
    # Architecture / mechanism questions.
    "how do you work",
    "what can you do",
    "what do you do",
    "what is cortex",
    "what is senses",
    "explain yourself",
    "tell me about yourself",
    "what are your capabilities",
    # Gate-specific questions.
    "how does the affected-tests gate work",
    "what gates are enabled",
    "why is there no --no-hooks flag",
    "how does the lint gate work",
    "what is the test-integrity gate",
)

# ── Self-knowledge negative cases (should return False) ────────────────────

SELFKNOWLEDGE_FALSE_CASES: tuple[str, ...] = (
    # Imperative-work guards (start-of-message verbs).
    "fix the affected-tests gate",
    "edit selfknowledge.py",
    "add a feature to the lint gate",
    "write a new gate",
    "implement the approval gate",
    "refactor the loop",
    "remove the test-integrity check",
    "create a new command",
    # Repo-touching signals.
    "what does frontdoor.py do",
    "git status",
    "run pytest on the repo",
    "cat loop.py",
    # Ambiguous / non-self-knowledge.
    "what do you think about that",
    "hello",
    "thanks",
    "",
    "   ",
)


@pytest.mark.parametrize("text", SELFKNOWLEDGE_TRUE_CASES)
def test_selfknowledge_true_cases(text: str) -> None:
    assert classify_selfknowledge(text) is True


@pytest.mark.parametrize("text", SELFKNOWLEDGE_FALSE_CASES)
def test_selfknowledge_false_cases(text: str) -> None:
    assert classify_selfknowledge(text) is False


@pytest.mark.parametrize("text", SELFKNOWLEDGE_TRUE_CASES + SELFKNOWLEDGE_FALSE_CASES)
def test_deterministic(text: str) -> None:
    assert classify_selfknowledge(text) == classify_selfknowledge(text)


# ── build_guide_index tests ────────────────────────────────────────────────


def test_build_guide_index_empty_repo(tmp_path) -> None:
    """Empty repo => empty list."""
    assert build_guide_index(tmp_path) == []


def test_build_guide_index_claude_only(tmp_path) -> None:
    """Repo with only CLAUDE.md => just that file."""
    (tmp_path / "CLAUDE.md").write_text("guide")
    assert build_guide_index(tmp_path) == ["CLAUDE.md"]


def test_build_guide_index_with_features(tmp_path) -> None:
    """docs/features/*.md discovered and sorted."""
    (tmp_path / "CLAUDE.md").write_text("guide")
    features = tmp_path / "docs" / "features"
    features.mkdir(parents=True)
    (features / "affected-tests.md").write_text("doc")
    (features / "lint-gate.md").write_text("doc")
    (features / "README.md").write_text("index")
    assert build_guide_index(tmp_path) == [
        "CLAUDE.md",
        "docs/features/README.md",
        "docs/features/affected-tests.md",
        "docs/features/lint-gate.md",
    ]


def test_build_guide_index_missing_docs(tmp_path) -> None:
    """Missing docs/ dir never raises."""
    (tmp_path / "CLAUDE.md").write_text("guide")
    # No docs/ directory at all.
    result = build_guide_index(tmp_path)
    assert result == ["CLAUDE.md"]


def test_build_guide_index_non_md_ignored(tmp_path) -> None:
    """Non-.md files under docs/features/ are ignored."""
    features = tmp_path / "docs" / "features"
    features.mkdir(parents=True)
    (features / "affected-tests.md").write_text("doc")
    (features / "notes.txt").write_text("not a guide")
    (features / "data.json").write_text("{}")
    assert build_guide_index(tmp_path) == ["docs/features/affected-tests.md"]


def test_build_guide_index_subdirs_ignored(tmp_path) -> None:
    """Subdirectories under docs/features/ are ignored (only files)."""
    features = tmp_path / "docs" / "features"
    features.mkdir(parents=True)
    (features / "affected-tests.md").write_text("doc")
    (features / "subdir").mkdir()
    (features / "subdir" / "nested.md").write_text("nested")
    assert build_guide_index(tmp_path) == ["docs/features/affected-tests.md"]
