"""Tests for the affected-tests gate (#213) — bounded-depth transitive
reverse-import selection (incl. lazy imports) + pytest execution.

The fixture reproduces the #210/t2 shape: a test that reaches the changed module
ONLY via a depth-3 *lazy* (function-local) import chain
(``test_via_hub → pkg → (lazy) pkg.cmd → pkg.impl``).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from colleague.affectedtests import (
    AffectedTestsReport,
    build_import_graph,
    run_affected_tests,
    select_affected_tests,
)


def _write(repo: Path, rel: str, body: str) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")


@pytest.fixture
def lazy_chain_repo(tmp_path: Path) -> Path:
    """A repo where the only path from test_via_hub to the changed leaf module
    (pkg/impl.py) is a depth-3 chain through a LAZY import inside pkg/__init__."""
    _write(
        tmp_path,
        "pkg/__init__.py",
        "def register():\n    from pkg.cmd import run\n    return run\n",
    )
    _write(tmp_path, "pkg/cmd.py", "from pkg.impl import thing\n\n\ndef run():\n    return thing\n")
    _write(tmp_path, "pkg/impl.py", "thing = 1\n")
    _write(
        tmp_path,
        "tests/test_via_hub.py",
        "from pkg import register\n\n\ndef test_x():\n    assert register\n",
    )
    _write(
        tmp_path,
        "tests/test_direct.py",
        "from pkg.impl import thing\n\n\ndef test_y():\n    assert thing\n",
    )
    _write(tmp_path, "tests/test_unrelated.py", "def test_z():\n    assert True\n")
    return tmp_path


# ── acceptance 1: lazy / function-local imports are captured ──────────────


def test_lazy_function_local_import_is_an_edge(lazy_chain_repo: Path) -> None:
    graph, _ = build_import_graph(lazy_chain_repo)
    # The pkg -> pkg.cmd edge exists ONLY because of the lazy import inside
    # register(); a module-level-only scan would miss it.
    assert "pkg.cmd" in graph["pkg"], "ast.walk must capture function-local imports"
    assert "pkg.impl" in graph["pkg.cmd"]


# ── acceptance 2: bounded-depth transitive selection (depth >= 3) ─────────


def test_transitive_depth3_selects_the_lazy_chain_test(lazy_chain_repo: Path) -> None:
    selected, total, capped = select_affected_tests(lazy_chain_repo, ["pkg/impl.py"], depth=3)
    assert "tests/test_via_hub.py" in selected, "the #210/t2 transitive case must be selected"
    assert "tests/test_direct.py" in selected
    assert "tests/test_unrelated.py" not in selected
    assert capped is False
    assert total == 2


def test_depth_below_chain_length_misses_the_lazy_chain(lazy_chain_repo: Path) -> None:
    # depth 2 cannot reach a leaf 3 edges away; the direct importer still is.
    selected, _, _ = select_affected_tests(lazy_chain_repo, ["pkg/impl.py"], depth=2)
    assert "tests/test_via_hub.py" not in selected
    assert "tests/test_direct.py" in selected


def test_vendored_trees_are_pruned(lazy_chain_repo: Path) -> None:
    _write(lazy_chain_repo, ".venv/test_fake.py", "from pkg.impl import thing\n")
    selected, _, _ = select_affected_tests(lazy_chain_repo, ["pkg/impl.py"], depth=3)
    assert not any(".venv" in s for s in selected)


def test_changed_test_file_is_its_own_affected_test(lazy_chain_repo: Path) -> None:
    selected, _, _ = select_affected_tests(lazy_chain_repo, ["tests/test_direct.py"], depth=3)
    assert "tests/test_direct.py" in selected


def test_no_changed_python_is_a_noop(lazy_chain_repo: Path) -> None:
    assert select_affected_tests(lazy_chain_repo, ["README.md"], depth=3) == ([], 0, False)


# ── acceptance 3: cap is honest, never a silent drop ──────────────────────


def test_cap_reports_total_and_capped(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/impl.py", "thing = 1\n")
    for i in range(5):
        _write(
            tmp_path,
            f"tests/test_{i}.py",
            "from pkg.impl import thing\n\n\ndef test_a():\n    assert thing\n",
        )
    selected, total, capped = select_affected_tests(tmp_path, ["pkg/impl.py"], depth=3, max_files=2)
    assert len(selected) == 2
    assert total == 5
    assert capped is True


# ── acceptance 4: execution — pytest on selected only, degrade-to-skipped ──


def test_run_affected_returns_none_when_nothing_selected(lazy_chain_repo: Path) -> None:
    assert run_affected_tests(lazy_chain_repo, ["README.md"]) is None


def test_run_affected_skips_when_pytest_missing(lazy_chain_repo: Path, monkeypatch) -> None:
    def _boom(*a, **k):
        raise FileNotFoundError("pytest")

    monkeypatch.setattr(subprocess, "run", _boom)
    report = run_affected_tests(lazy_chain_repo, ["pkg/impl.py"], depth=3)
    assert report is not None
    assert report.status == "skipped"
    assert report.reason and "pytest" in report.reason
    # never raises, never blocks


def test_run_affected_runs_pytest_on_selected_only(lazy_chain_repo: Path, monkeypatch) -> None:
    captured: dict = {}

    def _fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="2 passed in 0.01s\n", stderr="")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    report = run_affected_tests(lazy_chain_repo, ["pkg/impl.py"], depth=3)
    assert report is not None and report.status == "passed"
    assert report.passed == 2
    # only the selected files were passed to pytest (plus pytest's own flags)
    assert "tests/test_via_hub.py" in captured["cmd"]
    assert "tests/test_unrelated.py" not in captured["cmd"]


def test_run_affected_failure_status(lazy_chain_repo: Path, monkeypatch) -> None:
    def _fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd, 1, stdout="1 failed, 1 passed in 0.02s\n", stderr=""
        )

    monkeypatch.setattr(subprocess, "run", _fake_run)
    report = run_affected_tests(lazy_chain_repo, ["pkg/impl.py"], depth=3)
    assert report is not None and report.status == "failed"
    assert report.failed == 1


def test_pytest_args_override_used_verbatim(lazy_chain_repo: Path, monkeypatch) -> None:
    def _fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout="1 passed\n", stderr="")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    report = run_affected_tests(
        lazy_chain_repo, ["pkg/impl.py"], pytest_args=["tests/test_direct.py"]
    )
    assert report is not None and report.selected == ["tests/test_direct.py"]


def test_report_roundtrips(lazy_chain_repo: Path) -> None:
    r = AffectedTestsReport(
        status="failed", selected=["a.py"], total=3, capped=True, passed=2, failed=1
    )
    assert AffectedTestsReport.from_dict(r.to_dict()) == r
