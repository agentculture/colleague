"""Correction-diff capture tests — plan task t7, covers c5/h5/h28.

Tests the correction module that resolves squash merge commits from PR URLs
and computes per-file hunks between a work-tip and the merge commit, scoped
to the task's changed files.

Key properties:
- ANY missing fact (tip SHA, merge commit, changed_files) yields an honest
  no-diff record naming the missing fact — never a diff against a guessed base.
- A code-lesson built from a hunk quotes the hunk verbatim as evidence.
- Interpretation fields are marked origin=model.
- Offline degradation: when gh is unavailable, returns an honest no-diff record.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from colleague.correction import (
    CorrectionDiff,
    CorrectionRecord,
    DiffHunk,
    MissingFact,
    build_code_lesson,
    capture_correction_diff,
    resolve_merge_commit,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_git_repo(tmp_path: Path) -> Path:
    """Create a minimal git repo with one commit."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@test.com"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Test"],
        check=True,
        capture_output=True,
    )
    (repo / "file.txt").write_text("original\n")
    subprocess.run(
        ["git", "-C", str(repo), "add", "file.txt"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "initial"],
        check=True,
        capture_output=True,
    )
    return repo


# ---------------------------------------------------------------------------
# resolve_merge_commit tests
# ---------------------------------------------------------------------------


class TestResolveMergeCommit:
    """resolve_merge_commit resolves the squash merge via gh pr view --json."""

    def test_resolves_merge_commit_from_pr_url(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Given a pr_url, calls gh pr view --json and extracts mergeCommit.oid."""
        repo = _make_git_repo(tmp_path)
        pr_url = "https://github.com/org/repo/pull/42"

        fake_json = json.dumps({"mergeCommit": {"oid": "abc123def456"}})

        def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(argv, 0, fake_json, "")

        monkeypatch.setattr(subprocess, "run", fake_run)

        result = resolve_merge_commit(repo, pr_url)

        assert result == "abc123def456"

    def test_degrades_when_gh_unavailable(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """When gh is not on PATH, returns None (honest offline degradation)."""
        repo = _make_git_repo(tmp_path)

        monkeypatch.setattr("shutil.which", lambda x: None)

        result = resolve_merge_commit(repo, "https://github.com/org/repo/pull/1")

        assert result is None

    def test_degrades_when_gh_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """When gh pr view exits non-zero, returns None."""
        repo = _make_git_repo(tmp_path)

        def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(argv, 1, "", "not found")

        monkeypatch.setattr(subprocess, "run", fake_run)

        result = resolve_merge_commit(repo, "https://github.com/org/repo/pull/1")

        assert result is None

    def test_degrades_when_merge_commit_missing_from_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """When gh output has no mergeCommit key, returns None."""
        repo = _make_git_repo(tmp_path)

        fake_json = json.dumps({"title": "some PR"})

        def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(argv, 0, fake_json, "")

        monkeypatch.setattr(subprocess, "run", fake_run)

        result = resolve_merge_commit(repo, "https://github.com/org/repo/pull/1")

        assert result is None

    def test_degrades_when_no_pr_url(self, tmp_path: Path) -> None:
        """When pr_url is None, returns None immediately — no subprocess call."""
        repo = _make_git_repo(tmp_path)

        result = resolve_merge_commit(repo, None)

        assert result is None


# ---------------------------------------------------------------------------
# capture_correction_diff tests
# ---------------------------------------------------------------------------


class TestCaptureCorrectionDiff:
    """capture_correction_diff computes per-file hunks or returns honest no-diff."""

    def test_returns_no_diff_when_tip_missing(self, tmp_path: Path) -> None:
        """Missing tip_sha yields an honest no-diff record naming the missing fact."""
        repo = _make_git_repo(tmp_path)

        result = capture_correction_diff(
            repo=repo,
            tip_sha=None,
            merge_sha="merge123",
            changed_files=["file.txt"],
        )

        assert isinstance(result, CorrectionRecord)
        assert result.ok is False
        assert len(result.missing) == 1
        assert result.missing[0] == MissingFact.TIP_SHA
        assert result.hunks == {}

    def test_returns_no_diff_when_merge_missing(self, tmp_path: Path) -> None:
        """Missing merge_sha yields an honest no-diff record naming the missing fact."""
        repo = _make_git_repo(tmp_path)
        tip = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

        result = capture_correction_diff(
            repo=repo,
            tip_sha=tip,
            merge_sha=None,
            changed_files=["file.txt"],
        )

        assert isinstance(result, CorrectionRecord)
        assert result.ok is False
        assert MissingFact.MERGE_SHA in result.missing
        assert result.hunks == {}

    def test_returns_no_diff_when_changed_files_empty(self, tmp_path: Path) -> None:
        """Empty changed_files yields an honest no-diff record."""
        repo = _make_git_repo(tmp_path)
        tip = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

        result = capture_correction_diff(
            repo=repo,
            tip_sha=tip,
            merge_sha="merge123",
            changed_files=[],
        )

        assert isinstance(result, CorrectionRecord)
        assert result.ok is False
        assert MissingFact.CHANGED_FILES in result.missing

    def test_returns_per_file_hunks_when_all_facts_present(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Given all facts, returns per-file hunks scoped to changed_files."""
        repo = _make_git_repo(tmp_path)

        # Create a second commit to serve as the "merge" point
        (repo / "file.txt").write_text("original\ncorrected\n")
        subprocess.run(
            ["git", "-C", str(repo), "add", "file.txt"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-m", "merge"],
            check=True,
            capture_output=True,
            text=True,
        )
        merge_sha = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

        # tip is the parent of merge
        tip_sha = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD~1"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

        result = capture_correction_diff(
            repo=repo,
            tip_sha=tip_sha,
            merge_sha=merge_sha,
            changed_files=["file.txt"],
        )

        assert isinstance(result, CorrectionRecord)
        assert result.ok is True
        assert "file.txt" in result.hunks
        hunk = result.hunks["file.txt"]
        assert isinstance(hunk, DiffHunk)
        assert hunk.file_path == "file.txt"
        assert "corrected" in hunk.text

    def test_scopes_diff_to_changed_files_only(self, tmp_path: Path) -> None:
        """Only files in changed_files appear in the result, even if others changed."""
        repo = _make_git_repo(tmp_path)

        # Create two changed files
        (repo / "file.txt").write_text("original\nchanged_a\n")
        (repo / "other.txt").write_text("new content\n")
        subprocess.run(
            ["git", "-C", str(repo), "add", "."],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-m", "merge"],
            check=True,
            capture_output=True,
            text=True,
        )

        merge_sha = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        tip_sha = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD~1"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

        # Only request file.txt — other.txt should NOT appear
        result = capture_correction_diff(
            repo=repo,
            tip_sha=tip_sha,
            merge_sha=merge_sha,
            changed_files=["file.txt"],
        )

        assert isinstance(result, CorrectionRecord)
        assert result.ok is True
        assert "file.txt" in result.hunks
        assert "other.txt" not in result.hunks

    def test_degrades_on_git_diff_failure(self, tmp_path: Path) -> None:
        """When git diff fails (e.g. bad SHA), returns honest no-diff record."""
        repo = _make_git_repo(tmp_path)

        result = capture_correction_diff(
            repo=repo,
            tip_sha="nonexistent_sha",
            merge_sha="another_bad_sha",
            changed_files=["file.txt"],
        )

        assert isinstance(result, CorrectionRecord)
        assert result.ok is False
        # Should name the git error, not silently succeed
        assert result.missing or result.note


# ---------------------------------------------------------------------------
# build_code_lesson tests
# ---------------------------------------------------------------------------


class TestBuildCodeLesson:
    """build_code_lesson creates a code-lesson from a DiffHunk."""

    def test_code_lesson_quotes_hunk_verbatim_as_evidence(self) -> None:
        """The evidence field contains the hunk text verbatim."""
        hunk = DiffHunk(file_path="src/foo.py", text="@ -1,3 +1,4 @@\n-old()\n+new()")

        lesson = build_code_lesson(hunk)

        assert lesson.evidence == hunk.text
        assert lesson.origin == "model"
        assert lesson.file_path == "src/foo.py"

    def test_code_lesson_marks_interpretation_as_origin_model(self) -> None:
        """Interpretation fields (pattern, constant, reason) are marked origin=model."""
        hunk = DiffHunk(file_path="src/bar.py", text="some hunk text")

        lesson = build_code_lesson(hunk)

        assert lesson.origin == "model"

    def test_code_lesson_carries_file_path_from_hunk(self) -> None:
        """The code-lesson records the file path from the source hunk."""
        hunk = DiffHunk(file_path="tests/test_thing.py", text="hunk")

        lesson = build_code_lesson(hunk)

        assert lesson.file_path == "tests/test_thing.py"

    def test_code_lesson_has_low_default_confidence(self) -> None:
        """A correction-derived lesson defaults to low confidence."""
        hunk = DiffHunk(file_path="x.py", text="hunk")

        lesson = build_code_lesson(hunk)

        assert lesson.confidence == "low"

    def test_code_lesson_constant_defaults_to_file_path(self) -> None:
        """constant (the answer-shaped repo anchor, #396) defaults to the
        hunk's file_path when the caller supplies no more specific anchor."""
        hunk = DiffHunk(file_path="src/foo.py", text="hunk")

        lesson = build_code_lesson(hunk)

        assert lesson.constant == "src/foo.py"

    def test_code_lesson_constant_override_wins_over_file_path(self) -> None:
        """An explicit constant overrides the file_path default."""
        hunk = DiffHunk(file_path="src/foo.py", text="hunk")

        lesson = build_code_lesson(hunk, constant="src/foo.py:42")

        assert lesson.constant == "src/foo.py:42"

    def test_code_lesson_carries_pattern_and_reason(self) -> None:
        """pattern/reason ride through unchanged when supplied."""
        hunk = DiffHunk(file_path="src/foo.py", text="hunk")

        lesson = build_code_lesson(hunk, pattern="import ordering", reason="isort convention")

        assert lesson.pattern == "import ordering"
        assert lesson.reason == "isort convention"


# ---------------------------------------------------------------------------
# Dataclass shape tests
# ---------------------------------------------------------------------------


class TestDataclassShapes:
    """Verify the dataclass shapes match the spec."""

    def test_correction_record_has_required_fields(self) -> None:
        """CorrectionRecord has ok, missing, hunks, note fields."""
        record = CorrectionRecord(
            ok=False,
            missing=[MissingFact.TIP_SHA],
            hunks={},
            note="tip_sha was None",
        )
        assert record.ok is False
        assert MissingFact.TIP_SHA in record.missing
        assert record.hunks == {}
        assert "tip_sha" in record.note.lower()

    def test_diff_hunk_has_file_path_and_text(self) -> None:
        """DiffHunk has file_path and text fields."""
        hunk = DiffHunk(file_path="foo.py", text="@@ -1 +1 @@")
        assert hunk.file_path == "foo.py"
        assert hunk.text == "@@ -1 +1 @@"

    def test_missing_fact_is_enum(self) -> None:
        """MissingFact is an enum with the expected members."""
        assert hasattr(MissingFact, "TIP_SHA")
        assert hasattr(MissingFact, "MERGE_SHA")
        assert hasattr(MissingFact, "CHANGED_FILES")

    def test_correction_diff_is_alias(self) -> None:
        """CorrectionDiff is an alias for CorrectionRecord (back-compat)."""
        assert CorrectionDiff is CorrectionRecord


# ---------------------------------------------------------------------------
# Qodo #386 regression: nested paths survive diff parsing intact
# ---------------------------------------------------------------------------


def test_parse_diff_output_keeps_nested_paths() -> None:
    """A file under a directory keeps its FULL relative path (Qodo #386 bug 3:
    the old ---/+++ split truncated to a basename and dropped nested files)."""
    from colleague.correction import _parse_diff_output

    diff_text = (
        "diff --git a/colleague/loop.py b/colleague/loop.py\n"
        "index 111..222 100644\n"
        "--- a/colleague/loop.py\n"
        "+++ b/colleague/loop.py\n"
        "@@ -1,2 +1,2 @@\n"
        "-old line\n"
        "+new line\n"
        "diff --git a/top.py b/top.py\n"
        "index 333..444 100644\n"
        "--- a/top.py\n"
        "+++ b/top.py\n"
        "@@ -5,1 +5,1 @@\n"
        "-a\n"
        "+b\n"
    )
    hunks = _parse_diff_output(diff_text, ["colleague/loop.py", "top.py"])
    assert set(hunks) == {"colleague/loop.py", "top.py"}
    assert "+new line" in hunks["colleague/loop.py"]
    assert "@@ -1,2 +1,2 @@" in hunks["colleague/loop.py"]
    assert "+b" in hunks["top.py"]


def test_parse_diff_output_scopes_to_requested_files() -> None:
    from colleague.correction import _parse_diff_output

    diff_text = (
        "diff --git a/pkg/wanted.py b/pkg/wanted.py\n"
        "--- a/pkg/wanted.py\n"
        "+++ b/pkg/wanted.py\n"
        "@@ -1 +1 @@\n"
        "-x\n"
        "+y\n"
        "diff --git a/pkg/unwanted.py b/pkg/unwanted.py\n"
        "--- a/pkg/unwanted.py\n"
        "+++ b/pkg/unwanted.py\n"
        "@@ -1 +1 @@\n"
        "-p\n"
        "+q\n"
    )
    hunks = _parse_diff_output(diff_text, ["pkg/wanted.py"])
    assert set(hunks) == {"pkg/wanted.py"}
