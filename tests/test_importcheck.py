"""Tests for the importability-check gate (#482).

Reproduces the run cc5d1f1a2c5f shape: a module that compiles fine (valid
syntax) but raises at *import* time because it references a symbol that
doesn't exist — a hallucinated ``from colleague.hooks import Policy``-style
import, or a lost re-export.  ``py_compile`` alone is blind to this; only an
actual import smoke catches it (acceptance criterion 1).

Acceptance criterion 2 is the load-bearing test in this file
(``test_worktree_version_wins_over_installed_package``): it proves the
worktree-resolution fix is not vacuous by making an "installed" copy of a
package differ from the "worktree" copy under test and asserting the
*worktree* version's ``ImportError`` text is what gets reported.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from colleague.importcheck import (
    ImportCheckReport,
    run_import_check,
)


def _write(root: Path, rel: str, body: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")


# ── acceptance 1: an ImportError-raising module is caught, naming module + error ──


def test_missing_symbol_import_yields_finding_naming_module_and_error(
    tmp_path: Path,
) -> None:
    """A module compiling fine but importing a non-existent symbol -> a
    finding naming the module and carrying the ImportError text (#482 shape:
    a hallucinated ``from colleague.hooks import Policy``)."""
    _write(tmp_path, "widgets/__init__.py", "")
    _write(
        tmp_path,
        "widgets/broken.py",
        "from widgets.helper import does_not_exist\n",
    )
    _write(tmp_path, "widgets/helper.py", "real_thing = 1\n")

    report = run_import_check(tmp_path, ["widgets/broken.py"])

    assert report.status == "failed"
    assert len(report.findings) == 1
    finding = report.findings[0]
    assert finding.module == "widgets.broken"
    assert finding.stage == "import"
    assert "does_not_exist" in finding.error
    assert "ImportError" in finding.error


def test_clean_module_passes(tmp_path: Path) -> None:
    _write(tmp_path, "widgets/__init__.py", "")
    _write(tmp_path, "widgets/ok.py", "value = 42\n")

    report = run_import_check(tmp_path, ["widgets/ok.py"])

    assert report.status == "passed"
    assert report.checked == ["widgets/ok.py"]
    assert report.findings == []


def test_syntax_error_is_caught_at_compile_stage(tmp_path: Path) -> None:
    _write(tmp_path, "widgets/__init__.py", "")
    _write(tmp_path, "widgets/bad_syntax.py", "def f(:\n    pass\n")

    report = run_import_check(tmp_path, ["widgets/bad_syntax.py"])

    assert report.status == "failed"
    assert report.findings[0].stage == "compile"


# ── acceptance 2: worktree resolution wins over an installed package (c20) ──


def test_worktree_version_wins_over_installed_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prove the fix is not vacuous.

    Sets up a synthetic "installed package" at a location the child's ambient
    PYTHONPATH already points to (mimicking site-packages / an editable
    install elsewhere), whose copy of the module imports CLEANLY.  The
    worktree under test (repo_path) has a DIFFERENT copy of the *same* dotted
    module that is broken.  If import resolution ever let the ambient
    (installed) copy win, this run would report ``status="passed"`` — the
    exact vacuous-pass failure mode c20 warns about.  Asserting ``"failed"``
    with the worktree's specific error text proves repo_path resolution
    actually won.
    """
    installed_root = tmp_path / "installed_site"
    worktree_root = tmp_path / "worktree"

    # The "installed" copy: clean, importable.
    _write(installed_root, "sparkmod/__init__.py", "")
    _write(installed_root, "sparkmod/thing.py", "value = 'installed-clean'\n")

    # The worktree copy of the SAME dotted module: broken.
    _write(worktree_root, "sparkmod/__init__.py", "")
    _write(
        worktree_root,
        "sparkmod/thing.py",
        "raise ImportError('worktree-broken-marker')\n",
    )

    # Simulate an ambient PYTHONPATH that already resolves the "installed"
    # copy (as a real site-packages / editable-install entry would).
    monkeypatch.setenv("PYTHONPATH", str(installed_root))

    report = run_import_check(worktree_root, ["sparkmod/thing.py"])

    assert report.status == "failed", (
        "worktree resolution must win: a pass here means the ambient "
        "(installed) copy was imported instead of the worktree's — the "
        "exact vacuous-pass bug c20 describes"
    )
    assert len(report.findings) == 1
    assert "worktree-broken-marker" in report.findings[0].error
    assert "installed-clean" not in report.findings[0].error


# ── criterion 3: off-knob + no-op behavior ──


def test_off_knob_skips_without_running_anything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path, "widgets/broken.py", "from widgets.nope import x\n")
    monkeypatch.setenv("COLLEAGUE_IMPORT_CHECK", "0")

    report = run_import_check(tmp_path, ["widgets/broken.py"])

    assert report.status == "skipped"
    assert report.reason == "COLLEAGUE_IMPORT_CHECK=0"
    assert report.checked == []
    assert report.findings == []


def test_empty_changed_files_is_a_strict_noop(tmp_path: Path) -> None:
    report = run_import_check(tmp_path, [])
    assert report.status == "skipped"


def test_non_py_changes_are_a_strict_noop(tmp_path: Path) -> None:
    report = run_import_check(tmp_path, ["README.md", "docs/foo.txt"])
    assert report.status == "skipped"


def test_never_raises_on_unexpected_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """The public function degrades to a skipped report instead of raising,
    even given a nonsense repo path."""
    report = run_import_check("/definitely/not/a/real/path/at/all", ["x.py"])
    assert isinstance(report, ImportCheckReport)
    assert report.status in ("skipped", "failed")


def test_report_round_trips_through_dict() -> None:
    from colleague.importcheck import ImportCheckFinding

    report = ImportCheckReport(
        status="failed",
        checked=["a.py"],
        findings=[ImportCheckFinding(module="a", path="a.py", stage="import", error="boom")],
    )
    restored = ImportCheckReport.from_dict(report.to_dict())
    assert restored.status == "failed"
    assert restored.checked == ["a.py"]
    assert restored.findings[0].module == "a"
    assert restored.findings[0].error == "boom"


def test_non_identifier_path_components_skip_the_import_smoke(tmp_path: Path) -> None:
    """A valid standalone script under a non-package dir (``.claude/``, a dashed
    directory) has no importable dotted name — it is compile-checked only,
    never smoke-imported, so it can never manufacture a false
    ``import-check-failed`` (Qodo #486 thread 8)."""
    _write(tmp_path, ".claude/skills/helper.py", "x = 1\n")
    _write(tmp_path, "my-scripts/tool.py", "y = 2\n")
    report = run_import_check(tmp_path, [".claude/skills/helper.py", "my-scripts/tool.py"])
    assert report.status == "passed"
    assert report.findings == []
    # Both files were still compile-checked (they appear in ``checked``).
    assert set(report.checked) == {".claude/skills/helper.py", "my-scripts/tool.py"}


def test_non_identifier_path_with_syntax_error_still_fails_at_compile(tmp_path: Path) -> None:
    _write(tmp_path, ".claude/broken.py", "def (:\n")
    report = run_import_check(tmp_path, [".claude/broken.py"])
    assert report.status == "failed"
    assert report.findings[0].stage == "compile"
