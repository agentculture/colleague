"""Tests for colleague.capacity — advisory capacity assessment."""

from __future__ import annotations

import json
from pathlib import Path

from colleague.capacity import CapacityVerdict, assess_capacity

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAssessCapacity:
    """Core behaviour of assess_capacity."""

    def test_returns_capacity_verdict_with_counts(self, tmp_path: Path):
        """(1) assess_capacity over a tmp repo returns a CapacityVerdict with
        dep/folder/file counts and instruction_tokens computed from the
        instruction."""
        # Build a repo with known structure.
        repo = str(tmp_path)
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "x"\nversion = "1"\ndependencies = ["requests", "click"]\n'
        )
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("print('hi')\n")
        (tmp_path / "src" / "utils.py").write_text("pass\n")

        instruction = "Add a new endpoint"
        budget = 1000

        verdict = assess_capacity(repo, instruction, budget)

        assert isinstance(verdict, CapacityVerdict)
        assert verdict.dep_count == 2
        assert verdict.folder_count == 1  # src/
        # 3 files: pyproject.toml, src/main.py, src/utils.py
        assert verdict.file_count == 3
        # Char heuristic: max(1, len("Add a new endpoint") // 4) = max(1, 18//4) = 4
        assert verdict.instruction_tokens == 4
        assert verdict.verdict == "fits"  # 4 < 1000 * 0.5

    def test_large_instruction_verdict(self, tmp_path: Path):
        """(2) A large instruction yields verdict in {"large","over_split_capacity"}
        and the call does NOT raise (advisory, never blocks)."""
        repo = str(tmp_path)
        (tmp_path / "README.md").write_text("hello\n")

        # Very long instruction relative to budget.
        instruction = "x" * 100_000
        budget = 100  # budget_tokens * 4 = 400; instruction_tokens ≈ 25000

        verdict = assess_capacity(repo, instruction, budget)

        assert isinstance(verdict, CapacityVerdict)
        assert verdict.verdict in {"large", "over_split_capacity"}
        # Specifically, 25000 > 400 so it should be over_split_capacity.
        assert verdict.verdict == "over_split_capacity"

    def test_char_heuristic_fallback(self, tmp_path: Path):
        """(3) With count_tokens=None the char-heuristic fallback is used
        (instruction_tokens == max(1, len(instruction)//4))."""
        repo = str(tmp_path)
        (tmp_path / "README.md").write_text("hello\n")

        instruction = "Hello world"
        budget = 1000

        verdict = assess_capacity(repo, instruction, budget, count_tokens=None)

        expected = max(1, len(instruction) // 4)
        assert verdict.instruction_tokens == expected

    def test_empty_instruction_tokens(self, tmp_path: Path):
        """Empty instruction yields 0 tokens."""
        repo = str(tmp_path)
        (tmp_path / "README.md").write_text("hello\n")

        verdict = assess_capacity(repo, "", 1000)
        assert verdict.instruction_tokens == 0

    def test_no_dependency_files(self, tmp_path: Path):
        """When no dependency files exist, dep_count is 0."""
        repo = str(tmp_path)
        (tmp_path / "README.md").write_text("hello\n")

        verdict = assess_capacity(repo, "test", 1000)
        assert verdict.dep_count == 0

    def test_requirements_txt_count(self, tmp_path: Path):
        """requirements.txt non-comment lines are counted."""
        repo = str(tmp_path)
        (tmp_path / "requirements.txt").write_text("# comment\nrequests\nflask\n\n# another\n")

        verdict = assess_capacity(repo, "test", 1000)
        assert verdict.dep_count == 2

    def test_package_json_count(self, tmp_path: Path):
        """package.json dependencies keys are counted."""
        repo = str(tmp_path)
        (tmp_path / "package.json").write_text(
            json.dumps({"dependencies": {"express": "^4", "lodash": "^4"}})
        )

        verdict = assess_capacity(repo, "test", 1000)
        assert verdict.dep_count == 2

    def test_custom_count_tokens(self, tmp_path: Path):
        """When count_tokens is provided, it is used for instruction tokens."""
        repo = str(tmp_path)
        (tmp_path / "README.md").write_text("hello\n")

        def mock_count(messages):
            return 42

        verdict = assess_capacity(repo, "any instruction", 1000, count_tokens=mock_count)
        assert verdict.instruction_tokens == 42

    def test_verdict_fits(self, tmp_path: Path):
        """Small instruction → 'fits'."""
        repo = str(tmp_path)
        (tmp_path / "README.md").write_text("hello\n")

        verdict = assess_capacity(repo, "hi", 1000)
        assert verdict.verdict == "fits"

    def test_verdict_large(self, tmp_path: Path):
        """Instruction in the middle range → 'large'."""
        repo = str(tmp_path)
        (tmp_path / "README.md").write_text("hello\n")

        # budget=1000 → fits < 500, over > 4000.  We want 500 <= tokens <= 4000.
        # tokens = max(1, len(instruction)//4).  len=2000 → 500 tokens.
        instruction = "x" * 2000
        verdict = assess_capacity(repo, instruction, 1000)
        assert verdict.verdict == "large"

    def test_detail_contains_summary(self, tmp_path: Path):
        """detail is a one-line human summary."""
        repo = str(tmp_path)
        (tmp_path / "README.md").write_text("hello\n")

        verdict = assess_capacity(repo, "test", 1000)
        assert verdict.detail
        assert "deps" in verdict.detail
        assert "folders" in verdict.detail
        assert "files" in verdict.detail
        assert "tokens" in verdict.detail
