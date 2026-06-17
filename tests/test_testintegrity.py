"""Tests for colleague.testintegrity — mirror-detection heuristic (task t1).

Verifies that co-introduced novel symbols shared between a changed test file
and a changed module-under-test are flagged, while symbols also present in
other repo files are not.  Also verifies the TaskResult contract integration.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from colleague.contract import OK, TaskResult
from colleague.testintegrity import (
    MirrorFinding,
    TestIntegrityReport,
    detect_mirror,
)

# ── helpers ──────────────────────────────────────────────────────────────


def _make_repo(
    tmp_path: Path,
    *,
    test_file: str = "test_thing.py",
    test_content: str = "",
    impl_file: str = "thing.py",
    impl_content: str = "",
    extra_files: dict[str, str] | None = None,
) -> Path:
    """Create a minimal repo with a test file, an impl file, and optional extras."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / test_file).write_text(test_content)
    (repo / impl_file).write_text(impl_content)
    if extra_files:
        for name, content in extra_files.items():
            (repo / name).write_text(content)
    return repo


# ── detect_mirror: attribute mirror ──────────────────────────────────────


def test_detect_mirror_flags_attribute_in_test_and_impl(tmp_path: Path) -> None:
    """A symbol appearing in BOTH a changed test file and changed impl file,
    but NOWHERE ELSE in the repo, is flagged as a mirror finding."""
    test_content = """
import exc

def test_error():
    raise exc.response_error("boom")
"""
    impl_content = """
import exc

def handle():
    raise exc.response_error("boom")
"""
    repo = _make_repo(
        tmp_path,
        test_content=test_content,
        impl_content=impl_content,
        extra_files={"other.py": "x = 1\n"},
    )
    report = detect_mirror(str(repo), ["test_thing.py", "thing.py"])

    assert len(report.findings) >= 1
    symbols = {f.symbol for f in report.findings}
    assert "response_error" in symbols
    attr_finding = next(f for f in report.findings if f.symbol == "response_error")
    assert attr_finding.kind == "attribute"


def test_detect_mirror_dict_key(tmp_path: Path) -> None:
    """A dict-key string literal shared between test and impl is flagged."""
    test_content = """
def test_cost():
    data = {"TotalEstimate": 42}
    assert data["TotalEstimate"] == 42
"""
    impl_content = """
def compute():
    data = {"TotalEstimate": 100}
    return data["TotalEstimate"]
"""
    repo = _make_repo(
        tmp_path,
        test_content=test_content,
        impl_content=impl_content,
        extra_files={"other.py": "x = 1\n"},
    )
    report = detect_mirror(str(repo), ["test_thing.py", "thing.py"])

    assert len(report.findings) >= 1
    symbols = {f.symbol for f in report.findings}
    assert "TotalEstimate" in symbols
    key_finding = next(f for f in report.findings if f.symbol == "TotalEstimate")
    assert key_finding.kind == "dict_key"


def test_detect_mirror_not_flagged_when_symbol_exists_elsewhere(tmp_path: Path) -> None:
    """A symbol that ALSO appears in a third (non-changed) repo file is NOT
    flagged — it is not novel to the changed set."""
    test_content = """
import exc

def test_error():
    raise exc.response_error("boom")
"""
    impl_content = """
import exc

def handle():
    raise exc.response_error("boom")
"""
    # This third file also uses response_error, so it's NOT novel.
    extra_content = """
import exc

def legacy():
    raise exc.response_error("old")
"""
    repo = _make_repo(
        tmp_path,
        test_content=test_content,
        impl_content=impl_content,
        extra_files={"legacy.py": extra_content},
    )
    report = detect_mirror(str(repo), ["test_thing.py", "thing.py"])

    symbols = {f.symbol for f in report.findings}
    assert "response_error" not in symbols


# ── TestIntegrityReport.to_dict ──────────────────────────────────────────


def test_report_to_dict() -> None:
    """TestIntegrityReport.to_dict produces the expected shape."""
    finding = MirrorFinding(
        symbol="response_error",
        kind="attribute",
        test_file="test_thing.py",
        impl_file="thing.py",
    )
    report = TestIntegrityReport(findings=[finding])
    d = report.to_dict()
    assert "findings" in d
    assert len(d["findings"]) == 1
    f = d["findings"][0]
    assert f["symbol"] == "response_error"
    assert f["kind"] == "attribute"


def test_report_round_trips() -> None:
    """TestIntegrityReport round-trips through to_dict/from_dict."""
    finding = MirrorFinding(
        symbol="TotalEstimate",
        kind="dict_key",
        test_file="test_cost.py",
        impl_file="cost.py",
    )
    report = TestIntegrityReport(findings=[finding])
    reloaded = TestIntegrityReport.from_dict(report.to_dict())
    assert reloaded == report


# ── TaskResult contract integration ─────────────────────────────────────


def test_task_result_test_integrity_report_defaults_none() -> None:
    """TaskResult.test_integrity_report is None by default."""
    result = TaskResult(task_id="t1", status=OK)
    assert result.test_integrity_report is None


def test_task_result_test_integrity_report_omitted_when_none() -> None:
    """to_dict() OMITS 'test_integrity_report' when it is None.

    Mirrors the lint_report omit-when-None pattern so a no-flag run is
    byte-identical to pre-t1 artifacts.
    """
    result = TaskResult(task_id="t1", status=OK)
    serialized = result.to_dict()
    assert "test_integrity_report" not in serialized


def test_task_result_test_integrity_report_present_when_set() -> None:
    """When test_integrity_report is set, it appears in to_dict and round-trips."""
    finding = MirrorFinding(
        symbol="response_error",
        kind="attribute",
        test_file="test_thing.py",
        impl_file="thing.py",
    )
    report = TestIntegrityReport(findings=[finding])
    result = TaskResult(
        task_id="t1",
        status=OK,
        test_integrity_report=report,
    )
    serialized = result.to_dict()
    assert "test_integrity_report" in serialized
    assert serialized["test_integrity_report"]["findings"][0]["symbol"] == "response_error"

    # Round-trip
    reloaded = TaskResult.from_dict(json.loads(json.dumps(serialized)))
    assert reloaded == result
    assert reloaded.test_integrity_report is not None
    assert reloaded.test_integrity_report.findings[0].symbol == "response_error"


# ── detect_mirror: edge cases ───────────────────────────────────────────


def test_detect_mirror_skips_unparseable_file(tmp_path: Path) -> None:
    """A malformed/unparseable .py file is silently skipped (never raises)."""
    test_content = "def test_ok(): pass\n"
    impl_content = "def handle(): pass\n"
    repo = _make_repo(
        tmp_path,
        test_content=test_content,
        impl_content=impl_content,
    )
    # Write a broken file that is NOT in changed_files — just ensure
    # the function doesn't crash on a repo with a broken file.
    (repo / "broken.py").write_text("this is not valid python {{{")
    report = detect_mirror(str(repo), ["test_thing.py", "thing.py"])
    assert isinstance(report, TestIntegrityReport)


def test_detect_mirror_empty_changed_files(tmp_path: Path) -> None:
    """Empty changed_files list returns an empty report."""
    repo = _make_repo(tmp_path)
    report = detect_mirror(str(repo), [])
    assert report.findings == []


def test_detect_mirror_no_test_files(tmp_path: Path) -> None:
    """When changed_files has no test files, no mirror findings are produced."""
    impl_content = "def handle(): raise exc.response_error('boom')\n"
    repo = _make_repo(
        tmp_path,
        test_content="def test_ok(): pass\n",
        impl_content=impl_content,
    )
    report = detect_mirror(str(repo), ["thing.py"])
    assert report.findings == []


def test_detect_mirror_survives_symlink_cycle(tmp_path: Path) -> None:
    """A symlink cycle in the repo must not hang the scan (Qodo PR #211).

    `_iter_repo_py` skips symlinked dirs + keeps a visited-set of resolved paths,
    so a `repo/loop -> repo` cycle terminates and the mirror is still flagged.
    """
    import os

    repo = _make_repo(
        tmp_path,
        test_content="import exc\n\ndef test_x():\n    raise exc.response_error('boom')\n",
        impl_content="import exc\n\ndef handle():\n    raise exc.response_error('boom')\n",
    )
    try:
        os.symlink(repo, repo / "loop")  # cycle: repo/loop -> repo
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")

    # Must terminate (no hang) and still flag the co-introduced novel symbol.
    report = detect_mirror(str(repo), ["test_thing.py", "thing.py"])
    assert "response_error" in {f.symbol for f in report.findings}


def test_iter_repo_py_skips_symlinked_dir(tmp_path: Path) -> None:
    """A symlinked directory is not descended into (no external-tree blow-up)."""
    import os

    from colleague.testintegrity import _iter_repo_py

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "real.py").write_text("x = 1\n")
    external = tmp_path / "external"
    external.mkdir()
    (external / "huge.py").write_text("y = 2\n")
    try:
        os.symlink(external, repo / "linked")  # symlinked dir into an external tree
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")

    found = {p.name for p in _iter_repo_py(repo)}
    assert "real.py" in found
    assert "huge.py" not in found  # the symlinked dir was not followed
