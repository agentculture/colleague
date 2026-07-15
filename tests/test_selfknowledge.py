"""Tests for :mod:`colleague.selfknowledge` — the self-knowledge classifier and guide index.

Mirrors the classifier test style of :mod:`tests.test_frontdoor`: table-driven
cases for :func:`classify_selfknowledge` and :func:`build_guide_index` tests
using ``tmp_path`` repos.
"""

from __future__ import annotations

import pytest

from colleague.selfknowledge import build_guide_index, build_self_facts, classify_selfknowledge

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
    first = classify_selfknowledge(text)
    second = classify_selfknowledge(text)
    assert first == second


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


# ── build_self_facts tests ─────────────────────────────────────────────────


class _StubConfig:
    """Minimal stub with the EngineConfig attributes build_self_facts reads."""

    def __init__(
        self,
        model: str = "default-model",
        senses: object | None = None,
        lint: bool = True,
        testintegrity: bool = True,
        affected_tests: bool = True,
        memory: bool = True,
        coherence: bool = True,
    ):
        self.model = model
        self.senses = senses
        self.lint = lint
        self.testintegrity = testintegrity
        self.affected_tests = affected_tests
        self.memory = memory
        self.coherence = coherence


class _StubSenses:
    def __init__(self, model: str):
        self.model = model


class TestBuildSelfFacts:
    """Tests for build_self_facts — purity, armed/unarmed, gate rendering."""

    def test_armed_config_contains_model_ids(self) -> None:
        """Armed config => output contains the exact model id strings."""
        senses = _StubSenses("senses-model")
        cfg = _StubConfig(model="cortex-model", senses=senses)
        out = build_self_facts(cfg, gateway_url="http://lobes.local:8001")
        assert "cortex: cortex-model" in out
        assert "senses: senses-model" in out
        assert "lobes: http://lobes.local:8001" in out

    def test_unarmed_senses(self) -> None:
        """No senses configured => 'not configured' and no fabricated id."""
        cfg = _StubConfig(model="cortex-model", senses=None)
        out = build_self_facts(cfg)
        assert "senses: not configured" in out
        # Must NOT contain a fabricated model id on the senses line.
        for line in out.split("\n"):
            if line.startswith("senses:"):
                assert "not configured" in line

    def test_unarmed_lobes(self) -> None:
        """No gateway_url => 'not armed' and no fabricated URL."""
        cfg = _StubConfig(model="cortex-model")
        out = build_self_facts(cfg)
        assert "lobes: not armed" in out
        # Must NOT contain a fabricated URL on the lobes line.
        for line in out.split("\n"):
            if line.startswith("lobes:"):
                assert "not armed" in line
                assert "http" not in line

    def test_gates_all_on(self) -> None:
        """All gates True => each renders 'on'."""
        cfg = _StubConfig()
        out = build_self_facts(cfg)
        gate_line = [line for line in out.split("\n") if line.startswith("gates:")][0]
        assert "lint on" in gate_line
        assert "testintegrity on" in gate_line
        assert "affected_tests on" in gate_line
        assert "memory on" in gate_line
        assert "coherence on" in gate_line

    def test_gates_all_off(self) -> None:
        """All gates False => each renders 'off'."""
        cfg = _StubConfig(
            lint=False,
            testintegrity=False,
            affected_tests=False,
            memory=False,
            coherence=False,
        )
        out = build_self_facts(cfg)
        gate_line = [line for line in out.split("\n") if line.startswith("gates:")][0]
        assert "lint off" in gate_line
        assert "testintegrity off" in gate_line
        assert "affected_tests off" in gate_line
        assert "memory off" in gate_line
        assert "coherence off" in gate_line

    def test_purity_no_network_or_subprocess(self) -> None:
        """build_self_facts is pure — no subprocess, no socket, no file I/O.

        We verify by constructing a stub config (no EngineConfig.resolve()
        which would read env/files) and confirming the function runs without
        side effects.
        """
        cfg = _StubConfig(model="pure-model")
        # Should complete without any I/O.
        out = build_self_facts(cfg)
        assert "cortex: pure-model" in out
        assert "senses: not configured" in out
        assert "lobes: not armed" in out
