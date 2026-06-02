"""Tests for the doc-test-alignment check (d): test-names-vs-assertions.

TDD: these tests are written CATCH-first, then the implementation lands in
``checks/test_names.py``.

Two heuristic signals (both advisory, severity="warning" — never gate CI):
  1. zero-assertion test (real bug class)
  2. name/body token drift (tuned overlap heuristic)

Plus two suppression mechanisms (inline comment + file allow-list).

The check module is loaded via importlib (not as a package import) and
``run(repo)`` is invoked directly against synthetic fixture repos under
``tmp_path``; the CLI is also exercised via ``check.sh --only tests --json``.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import textwrap
from pathlib import Path
from types import ModuleType

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

SKILL_ROOT = Path(__file__).resolve().parents[1] / ".claude" / "skills" / "doc-test-alignment"
SCRIPTS_DIR = SKILL_ROOT / "scripts"
CHECKS_DIR = SCRIPTS_DIR / "checks"
TEST_NAMES_PY = CHECKS_DIR / "test_names.py"
ENTRY_SH = SCRIPTS_DIR / "check.sh"


# ---------------------------------------------------------------------------
# Module-loading helper (importlib, not package import)
# ---------------------------------------------------------------------------


def _load_test_names() -> ModuleType:
    """Load checks/test_names.py as a module with scripts/ on sys.path."""
    scripts_str = str(SCRIPTS_DIR)
    if scripts_str not in sys.path:
        sys.path.insert(0, scripts_str)
    spec = importlib.util.spec_from_file_location("checks.test_names", TEST_NAMES_PY)
    assert spec is not None, f"Could not create spec for {TEST_NAMES_PY}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


# ---------------------------------------------------------------------------
# Fixture-repo helpers
# ---------------------------------------------------------------------------


def _make_repo(tmp_path: Path, test_files: dict[str, str]) -> Path:
    """Build a fake repo: pyproject.toml + tests/ with the given test files.

    *test_files* maps a filename (e.g. "test_foo.py") to its source text.
    """
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "pyproject.toml").write_text("[project]\nname = 'fake'\n", encoding="utf-8")
    for name, src in test_files.items():
        (repo / "tests" / name).write_text(textwrap.dedent(src), encoding="utf-8")
    return repo


def _flagged_ids(checks: list[dict]) -> list[str]:
    """Return the ids of the warning (flagged) checks."""
    return [c["id"] for c in checks if c["severity"] == "warning"]


def _summary(checks: list[dict]) -> dict | None:
    """Return the single summary info check (passed=True info), if present."""
    infos = [c for c in checks if c["severity"] == "info" and c["passed"]]
    # The summary names how many were scanned/flagged.
    for c in infos:
        if "scanned" in c["message"]:
            return c
    return None


# ---------------------------------------------------------------------------
# Contract sanity
# ---------------------------------------------------------------------------


class TestModuleContract:
    def test_name_constant(self) -> None:
        mod = _load_test_names()
        assert mod.NAME == "tests"

    def test_run_callable(self) -> None:
        mod = _load_test_names()
        assert callable(mod.run)

    def test_tunables_present(self) -> None:
        """The threshold + stopwords must be module-level tunables."""
        mod = _load_test_names()
        assert hasattr(mod, "MIN_NAME_TOKEN_OVERLAP")
        assert hasattr(mod, "STOPWORDS")
        # threshold sits just above 0: zero overlap flags, >=1 token passes.
        assert 0.0 < mod.MIN_NAME_TOKEN_OVERLAP <= (1.0 / 3.0)

    def test_empty_repo_no_tests(self, tmp_path: Path) -> None:
        """A repo with an empty tests/ dir scans 0 functions, flags 0, stays passed."""
        mod = _load_test_names()
        repo = _make_repo(tmp_path, {})
        checks = mod.run(repo)
        summary = _summary(checks)
        assert summary is not None
        assert summary["passed"] is True
        assert _flagged_ids(checks) == []


# ---------------------------------------------------------------------------
# Signal 1 — zero-assertion test (CATCH-first)
# ---------------------------------------------------------------------------


class TestZeroAssertion:
    def test_catch_no_assertions(self, tmp_path: Path) -> None:
        """A test with no assertions at all is flagged (warning, 'no assertions')."""
        mod = _load_test_names()
        repo = _make_repo(
            tmp_path,
            {"test_writer.py": """
                def run():
                    return 1

                def test_writes_file():
                    run()
                """},
        )
        checks = mod.run(repo)
        flagged = [c for c in checks if c["severity"] == "warning"]
        assert any("no assertion" in c["message"].lower() for c in flagged), checks
        # All flagged checks are advisory warnings, never errors.
        assert all(c["severity"] == "warning" for c in flagged)
        for c in flagged:
            assert c["passed"] is False

    def test_assert_statement_passes(self, tmp_path: Path) -> None:
        """An ast.Assert satisfies signal 1 (no zero-assertion flag)."""
        mod = _load_test_names()
        repo = _make_repo(
            tmp_path,
            {"test_ok.py": """
                def add(a, b):
                    return a + b

                def test_add():
                    assert add(1, 1) == 2
                """},
        )
        checks = mod.run(repo)
        flagged = [c for c in checks if c["severity"] == "warning"]
        assert not any("no assertion" in c["message"].lower() for c in flagged), checks

    def test_pytest_raises_counts_as_assertion(self, tmp_path: Path) -> None:
        """with pytest.raises(...) is an assertion (no zero-assertion flag)."""
        mod = _load_test_names()
        repo = _make_repo(
            tmp_path,
            {"test_raises.py": """
                import pytest

                def boom():
                    raise ValueError("x")

                def test_boom():
                    with pytest.raises(ValueError):
                        boom()
                """},
        )
        checks = mod.run(repo)
        flagged = [c for c in checks if c["severity"] == "warning"]
        assert not any("no assertion" in c["message"].lower() for c in flagged), checks

    def test_assert_prefixed_helper_counts(self, tmp_path: Path) -> None:
        """A call to a local helper named assert_*/check_*/verify_* counts."""
        mod = _load_test_names()
        repo = _make_repo(
            tmp_path,
            {"test_helper.py": """
                def assert_valid(x):
                    assert x

                def verify_state(x):
                    assert x

                def test_state_is_valid():
                    state = compute_state()
                    assert_valid(state)
                """},
        )
        checks = mod.run(repo)
        flagged = [c for c in checks if c["severity"] == "warning"]
        # The assert_-prefixed helper call must suppress the no-assertion signal.
        assert not any("no assertion" in c["message"].lower() for c in flagged), checks

    def test_self_assert_method_counts(self, tmp_path: Path) -> None:
        """unittest-style self.assertEqual(...) counts as an assertion."""
        mod = _load_test_names()
        repo = _make_repo(
            tmp_path,
            {"test_unittest.py": """
                import unittest

                class TestMath(unittest.TestCase):
                    def test_add_numbers(self):
                        self.assertEqual(add(1, 1), 2)
                """},
        )
        checks = mod.run(repo)
        flagged = [c for c in checks if c["severity"] == "warning"]
        assert not any("no assertion" in c["message"].lower() for c in flagged), checks


# ---------------------------------------------------------------------------
# Signal 2 — name/body token drift (CATCH-first)
# ---------------------------------------------------------------------------


class TestNameDrift:
    def test_catch_name_drift(self, tmp_path: Path) -> None:
        """A name advertising yaml/parse/config whose body touches none → flagged."""
        mod = _load_test_names()
        repo = _make_repo(
            tmp_path,
            {"test_parser.py": """
                def add(a, b):
                    return a + b

                def test_parses_yaml_config():
                    assert add(1, 2) == 3
                """},
        )
        checks = mod.run(repo)
        flagged = [c for c in checks if c["severity"] == "warning"]
        drift = [c for c in flagged if "drift" in c["id"]]
        assert drift, checks
        # The unmatched name tokens (yaml/parse/config) should be named.
        msg = " ".join(c["message"].lower() for c in drift)
        assert "yaml" in msg or "parse" in msg or "config" in msg

    def test_token_overlap_passes(self, tmp_path: Path) -> None:
        """When the body uses a name token (add), overlap > 0 → not drift-flagged."""
        mod = _load_test_names()
        repo = _make_repo(
            tmp_path,
            {"test_adds.py": """
                def add(a, b):
                    return a + b

                def test_adds_two_numbers():
                    assert add(2, 2) == 4
                """},
        )
        checks = mod.run(repo)
        flagged = [c for c in checks if c["severity"] == "warning"]
        drift = [c for c in flagged if "drift" in c["id"]]
        assert not drift, checks

    def test_all_stopwords_name_not_drift_flagged(self, tmp_path: Path) -> None:
        """A name made entirely of stopwords has no salient tokens → skip (no flag)."""
        mod = _load_test_names()
        repo = _make_repo(
            tmp_path,
            {"test_basic.py": """
                def test_it_works():
                    assert True
                """},
        )
        checks = mod.run(repo)
        flagged = [c for c in checks if c["severity"] == "warning"]
        drift = [c for c in flagged if "drift" in c["id"]]
        assert not drift, checks

    def test_string_literal_tokens_satisfy_overlap(self, tmp_path: Path) -> None:
        """Words in string-literal constants count as salient body tokens."""
        mod = _load_test_names()
        repo = _make_repo(
            tmp_path,
            {"test_msg.py": """
                def test_error_message():
                    result = build()
                    assert "an error occurred" in result
                """},
        )
        checks = mod.run(repo)
        flagged = [c for c in checks if c["severity"] == "warning"]
        drift = [c for c in flagged if "drift" in c["id"]]
        # "error" + "message" both appear in the string literal → overlap > 0.
        assert not drift, checks


# ---------------------------------------------------------------------------
# Suppression (CATCH-first)
# ---------------------------------------------------------------------------


class TestSuppression:
    def test_inline_comment_suppresses(self, tmp_path: Path) -> None:
        """An inline `# doc-test-alignment: ok` comment suppresses both signals."""
        mod = _load_test_names()
        repo = _make_repo(
            tmp_path,
            {"test_supp.py": """
                def test_writes_file():  # doc-test-alignment: ok
                    run()
                """},
        )
        checks = mod.run(repo)
        flagged = [c for c in checks if c["severity"] == "warning"]
        assert flagged == [], checks
        # An info "suppressed" check should be present for the suppressed test.
        suppressed = [
            c for c in checks if c["severity"] == "info" and "suppress" in c["message"].lower()
        ]
        assert suppressed, checks

    def test_inline_comment_above_def_suppresses(self, tmp_path: Path) -> None:
        """The marker just ABOVE the def line also suppresses."""
        mod = _load_test_names()
        repo = _make_repo(
            tmp_path,
            {"test_supp2.py": """
                # doc-test-alignment: ok
                def test_writes_file():
                    run()
                """},
        )
        checks = mod.run(repo)
        flagged = [c for c in checks if c["severity"] == "warning"]
        assert flagged == [], checks

    def test_suppressions_file_suppresses(self, tmp_path: Path) -> None:
        """suppressions.txt with relpath::test_name suppresses that test."""
        mod = _load_test_names()
        repo = _make_repo(
            tmp_path,
            {"test_file.py": """
                def test_writes_file():
                    run()
                """},
        )
        supp_dir = repo / ".claude" / "skills" / "doc-test-alignment"
        supp_dir.mkdir(parents=True)
        (supp_dir / "suppressions.txt").write_text(
            "# allow this one\ntests/test_file.py::test_writes_file\n",
            encoding="utf-8",
        )
        checks = mod.run(repo)
        flagged = [c for c in checks if c["severity"] == "warning"]
        assert flagged == [], checks


# ---------------------------------------------------------------------------
# Output shape + advisory exit (CATCH-first)
# ---------------------------------------------------------------------------


class TestOutputShape:
    def test_summary_info_present(self, tmp_path: Path) -> None:
        """Exactly one summary info check with scanned/flagged counts."""
        mod = _load_test_names()
        repo = _make_repo(
            tmp_path,
            {"test_a.py": """
                def add(a, b):
                    return a + b

                def test_add():
                    assert add(1, 1) == 2
                """},
        )
        checks = mod.run(repo)
        summary = _summary(checks)
        assert summary is not None
        assert summary["passed"] is True
        assert summary["severity"] == "info"
        assert "scanned" in summary["message"]
        assert "flagged" in summary["message"]

    def test_no_check_per_passing_test(self, tmp_path: Path) -> None:
        """Passing tests do NOT each emit a check — only summary + flagged ones."""
        mod = _load_test_names()
        files = {f"test_mod{i}.py": """
            def add(a, b):
                return a + b

            def test_add():
                assert add(1, 1) == 2
            """ for i in range(5)}
        repo = _make_repo(tmp_path, files)
        checks = mod.run(repo)
        flagged = [c for c in checks if c["severity"] == "warning"]
        # 5 passing tests → 0 warnings, just the single summary info.
        assert flagged == []
        infos = [c for c in checks if c["severity"] == "info"]
        # Only the summary info (no per-passing-test info spam).
        assert len(infos) == 1

    def test_per_flag_id_shape(self, tmp_path: Path) -> None:
        """Flagged-drift check ids embed relpath + test name."""
        mod = _load_test_names()
        repo = _make_repo(
            tmp_path,
            {"test_parser.py": """
                def add(a, b):
                    return a + b

                def test_parses_yaml_config():
                    assert add(1, 2) == 3
                """},
        )
        checks = mod.run(repo)
        drift = [c for c in checks if c["severity"] == "warning" and "drift" in c["id"]]
        assert drift
        cid = drift[0]["id"]
        assert "test_parses_yaml_config" in cid
        assert "test_parser.py" in cid

    def test_run_never_raises_on_bad_syntax(self, tmp_path: Path) -> None:
        """A test file with a syntax error does not crash run() — it returns checks."""
        mod = _load_test_names()
        repo = _make_repo(
            tmp_path,
            {
                "test_broken.py": "def test_x(:\n    pass\n",
                "test_good.py": """
                def add(a, b):
                    return a + b

                def test_add():
                    assert add(1, 1) == 2
                """,
            },
        )
        checks = mod.run(repo)
        assert isinstance(checks, list)
        # The good file is still scanned; run did not raise.
        assert _summary(checks) is not None


# ---------------------------------------------------------------------------
# CLI integration: advisory exit stays 0 even with warnings
# ---------------------------------------------------------------------------


def _run_check(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(ENTRY_SH), *args],
        capture_output=True,
        text=True,
        check=False,
    )


class TestAdvisoryExit:
    def test_exit_0_even_with_warnings(self, tmp_path: Path) -> None:
        """A flagged (warning) test must NOT flip the exit code — stays 0."""
        repo = _make_repo(
            tmp_path,
            {"test_writer.py": """
                def run():
                    return 1

                def test_writes_file():
                    run()
                """},
        )
        result = _run_check("--only", "tests", "--json", "--repo", str(repo))
        assert result.returncode == 0, f"stderr: {result.stderr}"
        data = json.loads(result.stdout)
        # aligned stays True because the failed checks are warnings, not errors.
        assert data["aligned"] is True
        # And at least one warning was produced.
        warnings = [c for c in data["checks"] if c["severity"] == "warning"]
        assert warnings, data

    def test_cli_summary_present(self, tmp_path: Path) -> None:
        """The summary info check survives the round-trip through the CLI."""
        repo = _make_repo(
            tmp_path,
            {"test_a.py": """
                def add(a, b):
                    return a + b

                def test_add():
                    assert add(1, 1) == 2
                """},
        )
        result = _run_check("--only", "tests", "--json", "--repo", str(repo))
        assert result.returncode == 0
        data = json.loads(result.stdout)
        summaries = [
            c for c in data["checks"] if c["severity"] == "info" and "scanned" in c["message"]
        ]
        assert len(summaries) == 1, data
