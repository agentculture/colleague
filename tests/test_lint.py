"""Tests for colleague.lint — the lint pre-finish gate module."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest

from colleague.contract import LintReport
from colleague.lint import detect_linters, run_lint_gate


def _make_repo(tmp_path: Path, pyproject: str | None = None, flake8: str | None = None) -> Path:
    """Create a minimal repo dir with optional config files."""
    repo = tmp_path / "repo"
    repo.mkdir()
    if pyproject is not None:
        (repo / "pyproject.toml").write_text(pyproject)
    if flake8 is not None:
        (repo / ".flake8").write_text(flake8)
    return repo


# ── detect_linters ──────────────────────────────────────────────────────


def test_detect_none(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    assert detect_linters(repo) == set()


def test_detect_black_isort(tmp_path: Path) -> None:
    pyproject = """
[tool.black]
line-length = 88

[tool.isort]
profile = "black"
"""
    repo = _make_repo(tmp_path, pyproject=pyproject)
    assert detect_linters(repo) == {"black", "isort"}


def test_detect_flake8_from_dotflake8(tmp_path: Path) -> None:
    flake8_cfg = "[flake8]\nmax-line-length = 88\n"
    repo = _make_repo(tmp_path, flake8=flake8_cfg)
    assert "flake8" in detect_linters(repo)


def test_detect_malformed_pyproject_no_raise(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, pyproject="not valid toml {{{")
    result = detect_linters(repo)
    assert isinstance(result, set)


# ── run_lint_gate ────────────────────────────────────────────────────────


def test_gate_no_linters_returns_none(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    (repo / "a.py").write_text("x = 1\n")
    assert run_lint_gate(repo, ["a.py"]) is None


def test_gate_no_python_files_returns_none(tmp_path: Path) -> None:
    pyproject = "[tool.black]\n"
    repo = _make_repo(tmp_path, pyproject=pyproject)
    (repo / "README.md").write_text("# hi\n")
    assert run_lint_gate(repo, ["README.md"]) is None


def test_gate_black_fixes_file(tmp_path: Path) -> None:
    if shutil.which("black") is None:
        pytest.skip("black not installed")

    pyproject = "[tool.black]\n"
    repo = _make_repo(tmp_path, pyproject=pyproject)
    m = repo / "m.py"
    m.write_text("x = {  'a':1 }\n")
    before = m.read_text()

    report = run_lint_gate(repo, ["m.py"])

    assert report is not None
    assert isinstance(report, LintReport)
    after = m.read_text()
    assert after != before  # black reformatted


def test_gate_missing_binary_skipped(tmp_path: Path, monkeypatch: Any) -> None:
    pyproject = "[tool.black]\n"
    repo = _make_repo(tmp_path, pyproject=pyproject)
    (repo / "m.py").write_text("x = 1\n")

    def _raise(*args: Any, **kwargs: Any) -> None:
        raise FileNotFoundError("no such binary")

    monkeypatch.setattr("colleague.lint.subprocess.run", _raise)

    report = run_lint_gate(repo, ["m.py"])
    assert report is not None
    assert isinstance(report, LintReport)
    assert any("black" in s for s in report.skipped)
